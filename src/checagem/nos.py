"""Nós do grafo. Cada nó recebe o estado e devolve só as chaves que altera."""

import asyncio
import logging
import re
import time

from checagem import redator
from checagem.config import Config
from checagem.llm import Interpretacao, Modelos
from checagem.regras import avaliar
from checagem.schemas import Achado, Consulta, Estado
from checagem.tools import Ferramentas
from checagem.tools.busca import buscar_web
from checagem.validacao import (
    EntradaRecusada,
    cnpj_valido,
    extrair_cnpj,
    extrair_dominio,
    normalizar_dominio,
    parece_cpf,
    recusar_cpf,
    so_digitos,
    validar_cnpj_ou_recusar,
)

log = logging.getLogger(__name__)

_RE_RESTO = re.compile(r"(https?://\S+|\S+@\S+|\S+\.[a-z]{2,}\S*|[\d./-]{8,}|cnpj|site|[,;:()|])", re.IGNORECASE)


def nome_por_regex(texto: str) -> str | None:
    """Sem LLM: o nome é o que sobra depois de tirar CNPJ, domínio, e-mail e pontuação."""
    resto = re.sub(r"\s+", " ", _RE_RESTO.sub(" ", texto)).strip(" -")
    return resto[:120] or None


class Nos:
    def __init__(self, cfg: Config, ferramentas: Ferramentas, modelos: Modelos):
        self.cfg = cfg
        self.f = ferramentas
        self.m = modelos

    # --- Entrada -------------------------------------------------------------

    async def preparar(self, estado: Estado) -> dict:
        """Validações em código, depois o interpretador. Recusa sai antes de qualquer chamada externa."""
        texto = estado.get("entrada_bruta", "")
        try:
            recusar_cpf(texto)
            cnpj = extrair_cnpj(texto)
            if cnpj:
                validar_cnpj_ou_recusar(cnpj)

            interp = await self._interpretar(texto)
            consulta = self._montar_consulta(texto, cnpj, interp)
        except EntradaRecusada as e:
            return {"erro": str(e)}

        if consulta.vazia():
            return {"erro": "Informe o nome, o CNPJ ou o site do vendedor."}
        return {"consulta": consulta, "prazo": time.monotonic() + self.cfg.timeout_global}

    async def _interpretar(self, texto: str) -> Interpretacao:
        try:
            return await self.m.interpretar(texto)
        except Exception as e:
            log.warning("interpretador falhou (%s); seguindo só com regex", type(e).__name__)
            return Interpretacao()

    def _montar_consulta(self, texto: str, cnpj_regex: str | None, interp: Interpretacao) -> Consulta:
        """O LLM só sugere; o código revalida. CNPJ e domínio achados por regex têm prioridade."""
        for campo in (interp.nome, interp.cnpj, interp.produto):
            if campo and parece_cpf(campo):
                raise EntradaRecusada("A entrada parece conter um CPF. Este agente só consulta pessoa jurídica.")

        cnpj = cnpj_regex
        if not cnpj and interp.cnpj and cnpj_valido(interp.cnpj):
            cnpj = so_digitos(interp.cnpj)

        dominio = extrair_dominio(texto) or (normalizar_dominio(interp.dominio) if interp.dominio else None)
        nome = interp.nome or nome_por_regex(texto)
        return Consulta(nome=nome, cnpj=cnpj, dominio=dominio, produto=interp.produto)

    # --- Ramos paralelos -----------------------------------------------------

    async def _com_prazo(self, estado: Estado, fonte: str, coro) -> Achado:
        """Garante que nenhum ramo passa do prazo global: estourou, vira `falhou`."""
        sobra = estado["prazo"] - time.monotonic()
        try:
            return await asyncio.wait_for(coro, timeout=max(sobra, 0.01))
        except TimeoutError:
            return Achado(fonte=fonte, status="falhou", dados={"erro": "prazo global da consulta esgotado"})
        except Exception as e:  # ferramentas não levantam, mas o grafo não pode cair
            log.exception("ramo %s erro inesperado", fonte)
            return Achado(fonte=fonte, status="falhou", dados={"erro": f"erro inesperado: {type(e).__name__}"})

    async def ramo_cnpj(self, estado: Estado) -> dict:
        c = estado["consulta"]
        if not c.cnpj:
            return {"achados": [Achado(fonte="cnpj", status="sem_dados", dados={"nao_informado": True})]}
        return {"achados": [await self._com_prazo(estado, "cnpj", self._cnpj(c, estado["prazo"]))]}

    async def _cnpj(self, c: Consulta, prazo: float) -> Achado:
        achado = await self.f.cnpj(c.cnpj, prazo=prazo)
        atividade = (achado.dados.get("cnae_principal") or {}).get("descricao")
        if achado.status == "ok" and c.produto and atividade:
            try:
                achado.dados["compatibilidade_cnae"] = await self.m.classificar_cnae(atividade, c.produto)
            except Exception as e:
                log.warning("classificador de CNAE falhou (%s)", type(e).__name__)
                achado.dados["compatibilidade_cnae"] = "incerto"
        return achado

    async def ramo_dominio(self, estado: Estado) -> dict:
        c = estado["consulta"]
        if not c.dominio:
            return {"achados": [Achado(fonte="dominio", status="sem_dados", dados={"nao_informado": True})]}
        return {"achados": [await self._com_prazo(estado, "dominio", self.f.dominio(c.dominio, prazo=estado["prazo"]))]}

    async def ramo_web(self, estado: Estado) -> dict:
        c = estado["consulta"]
        return {"achados": [await self._com_prazo(estado, "web", self._web(c, estado["prazo"]))]}

    async def _web(self, c: Consulta, prazo: float) -> Achado:
        achado = await buscar_web(c, self.f.busca, self.cfg, prazo=prazo)
        resultados = achado.dados.get("resultados") or []
        if achado.status != "ok" or not resultados:
            return achado
        empresa = c.nome or c.cnpj or ""
        try:
            rotulos = await self.m.classificar_trechos(empresa, resultados)
        except Exception as e:
            log.warning("classificador de trechos falhou (%s); trechos ficam incertos", type(e).__name__)
            rotulos = {}
        validos = {"reclamacao", "mencao", "nao_relacionado", "incerto"}
        for i, r in enumerate(resultados):
            rotulo = rotulos.get(i)
            r["rotulo"] = rotulo if rotulo in validos else "incerto"  # ids desconhecidos são ignorados
        return achado

    # --- Junção e saída ------------------------------------------------------

    async def avaliar_regras(self, estado: Estado) -> dict:
        sinais = avaliar(estado.get("achados", []), estado["consulta"], self.cfg.data_hoje(), self.cfg)
        return {"sinais": sinais}

    async def redigir(self, estado: Estado) -> dict:
        """Até 2 tentativas com LLM; se ambas forem rejeitadas, modelo de texto sem LLM."""
        sinais = estado["sinais"]
        correcao = None
        for tentativa in range(2):
            try:
                redacao = await self.m.redigir(sinais, correcao)
            except Exception as e:
                log.info("redator indisponível (%s); usando modelo de texto", type(e).__name__)
                break
            problemas = redator.validar_redacao(redacao, sinais)
            if not problemas:
                return {"relatorio": redator.relatorio_de_redacao(redacao, sinais)}
            log.warning("redação rejeitada (tentativa %d): %s", tentativa + 1, problemas)
            correcao = "; ".join(problemas)
        return {"relatorio": redator.modelo_de_texto(sinais)}

    async def validar_saida(self, estado: Estado) -> dict:
        sinais = estado["sinais"]
        relatorio = estado["relatorio"]
        problemas = redator.validar_relatorio(relatorio, sinais)
        if problemas:
            log.error("relatório final rejeitado: %s; usando modelo de texto", problemas)
            return {"relatorio": redator.modelo_de_texto(sinais)}
        return {}
