"""Regras determinísticas: achados -> sinais.

Funções puras. Quem decide o que é sinal é este módulo; os dois pontos que dependem de LLM
(`cnae_incompativel` e `reclamacoes_web`) recebem a classificação já pronta em `Achado.dados`
e aqui só se aplica o enum.

Formato esperado de `Achado.dados` (normalizado pelas ferramentas):
- cnpj:    situacao, data_abertura (AAAA-MM-DD), razao_social, nome_fantasia,
           cnae_principal {codigo, descricao}, uf, municipio,
           compatibilidade_cnae ("compativel" | "incompativel" | "incerto", opcional)
- dominio: data_registro (AAAA-MM-DD), servidores_nome
- web:     resultados [{titulo, url, trecho, rotulo}]
           rotulo in {"reclamacao", "mencao", "nao_relacionado", "incerto"}
Qualquer fonte pode trazer dados["nao_informado"] = True quando a entrada não tinha o dado.
"""

import re
import unicodedata
from datetime import date

from rapidfuzz import fuzz

from checagem.config import Config
from checagem.schemas import Achado, Consulta, Sinal

_NOMES_FONTE = {"cnpj": "cadastro do CNPJ", "dominio": "registro do domínio", "web": "busca web"}


def _evidencia(achado: Achado) -> list[str]:
    return [achado.url_fonte] if achado.url_fonte else [achado.rotulo]


def _data(valor) -> date | None:
    if not valor:
        return None
    try:
        return date.fromisoformat(str(valor)[:10])
    except ValueError:
        return None


def _anos(a: date, b: date) -> int:
    """Anos completos entre a e b."""
    return b.year - a.year - ((b.month, b.day) < (a.month, a.day))


def _mais_de_anos(inicio: date, hoje: date, anos: int) -> bool:
    try:
        limite = inicio.replace(year=inicio.year + anos)
    except ValueError:  # 29/02
        limite = inicio.replace(year=inicio.year + anos, day=28)
    return hoje > limite


def _por_fonte(achados: list[Achado], fonte: str) -> Achado | None:
    for a in achados:
        if a.fonte == fonte:
            return a
    return None


# --- Lacunas ---------------------------------------------------------------


def regra_lacunas(achados: list[Achado]) -> list[Sinal]:
    sinais: list[Sinal] = []
    falhas = [a for a in achados if a.status == "falhou"]
    if falhas:
        nomes = ", ".join(_NOMES_FONTE[a.fonte] for a in falhas)
        sinais.append(
            Sinal(
                id="fonte_indisponivel",
                tipo="lacuna",
                descricao=f"Não foi possível consultar: {nomes}.",
                evidencia=[e for a in falhas for e in _evidencia(a)],
                peso=2,
            )
        )
    ausentes = [a for a in achados if a.status == "sem_dados"]
    nao_informados = [a for a in ausentes if a.dados.get("nao_informado")]
    # Busca web que rodou e não achou nada é tratada em regra_web (sem_mencoes_web).
    sem_retorno = [a for a in ausentes if not a.dados.get("nao_informado") and a.fonte != "web"]
    if nao_informados:
        nomes = ", ".join(_NOMES_FONTE[a.fonte] for a in nao_informados)
        sinais.append(
            Sinal(
                id="nao_informado",
                tipo="lacuna",
                descricao=f"A entrada não trazia o dado necessário para consultar: {nomes}.",
                evidencia=[a.rotulo for a in nao_informados],
                peso=1,
            )
        )
    if sem_retorno:
        nomes = ", ".join(_NOMES_FONTE[a.fonte] for a in sem_retorno)
        sinais.append(
            Sinal(
                id="dado_ausente",
                tipo="lacuna",
                descricao=f"A fonte respondeu, mas sem os dados necessários: {nomes}.",
                evidencia=[e for a in sem_retorno for e in _evidencia(a)],
                peso=1,
            )
        )
    return sinais


# --- CNPJ ------------------------------------------------------------------


def regra_cnpj_inativo(cnpj: Achado) -> list[Sinal]:
    situacao = str(cnpj.dados.get("situacao") or "").strip().upper()
    if not situacao or situacao == "ATIVA":
        return []
    return [
        Sinal(
            id="cnpj_inativo",
            tipo="alerta",
            descricao=f"Situação cadastral do CNPJ: {situacao.lower()} (não está ativa).",
            evidencia=_evidencia(cnpj),
            peso=3,
        )
    ]


def regra_idade_empresa(cnpj: Achado, hoje: date, cfg: Config) -> list[Sinal]:
    abertura = _data(cnpj.dados.get("data_abertura"))
    if abertura is None:
        return []
    dias = (hoje - abertura).days
    if dias < cfg.dias_empresa_jovem:
        return [
            Sinal(
                id="empresa_jovem",
                tipo="alerta",
                descricao=f"Empresa aberta em {abertura.isoformat()}, há {dias} dias.",
                evidencia=_evidencia(cnpj),
                peso=2,
            )
        ]
    if _mais_de_anos(abertura, hoje, cfg.anos_empresa_antiga):
        return [
            Sinal(
                id="empresa_antiga",
                tipo="positivo",
                descricao=f"Empresa aberta em {abertura.isoformat()}, há {_anos(abertura, hoje)} anos.",
                evidencia=_evidencia(cnpj),
                peso=1,
            )
        ]
    return []


_SUFIXOS = re.compile(r"\b(ltda|s\.?\s?a|me|epp|eireli|mei|cia|comercio|comercial|servicos|e)\b")


def normalizar_nome(nome: str) -> str:
    s = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^\w\s]", " ", s)
    s = _SUFIXOS.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def similaridade_nome(informado: str, candidatos: list[str]) -> float:
    a = normalizar_nome(informado)
    notas = [fuzz.token_set_ratio(a, normalizar_nome(c)) / 100 for c in candidatos if c]
    return max(notas, default=0.0)


def regra_nome_divergente(consulta: Consulta, cnpj: Achado, cfg: Config) -> list[Sinal]:
    if not consulta.nome:
        return []
    candidatos = [cnpj.dados.get("razao_social") or "", cnpj.dados.get("nome_fantasia") or ""]
    if not any(candidatos):
        return []
    nota = similaridade_nome(consulta.nome, candidatos)
    if nota >= cfg.similaridade_minima:
        return []
    registrados = " / ".join(c for c in candidatos if c)
    return [
        Sinal(
            id="nome_divergente",
            tipo="alerta",
            descricao=(
                f"O nome informado ({consulta.nome}) difere do registrado no CNPJ "
                f"({registrados}); similaridade {nota:.2f}."
            ),
            evidencia=_evidencia(cnpj),
            peso=2,
        )
    ]


def regra_cnae(consulta: Consulta, cnpj: Achado) -> list[Sinal]:
    classe = cnpj.dados.get("compatibilidade_cnae")
    cnae = cnpj.dados.get("cnae_principal") or {}
    descricao_cnae = cnae.get("descricao") or "não informada"
    if classe == "incompativel":
        return [
            Sinal(
                id="cnae_incompativel",
                tipo="alerta",
                descricao=(
                    f"A atividade principal registrada ({descricao_cnae}) não parece relacionada "
                    f"ao que o vendedor diz vender ({consulta.produto})."
                ),
                evidencia=_evidencia(cnpj),
                peso=2,
            )
        ]
    if classe == "incerto":
        return [
            Sinal(
                id="cnae_incerto",
                tipo="lacuna",
                descricao=(
                    f"Não foi possível dizer se a atividade principal ({descricao_cnae}) "
                    f"tem relação com o que o vendedor diz vender."
                ),
                evidencia=_evidencia(cnpj),
                peso=1,
            )
        ]
    return []


# --- Domínio ---------------------------------------------------------------


def regra_idade_dominio(dominio: Achado, hoje: date, cfg: Config) -> list[Sinal]:
    registro = _data(dominio.dados.get("data_registro"))
    if registro is None:
        return []
    dias = (hoje - registro).days
    nome = dominio.dados.get("dominio", "domínio")
    if dias < cfg.dias_dominio_recente:
        return [
            Sinal(
                id="dominio_recente",
                tipo="alerta",
                descricao=f"O domínio {nome} foi registrado em {registro.isoformat()}, há {dias} dias.",
                evidencia=_evidencia(dominio),
                peso=2,
            )
        ]
    if _mais_de_anos(registro, hoje, cfg.anos_dominio_antigo):
        return [
            Sinal(
                id="dominio_antigo",
                tipo="positivo",
                descricao=(
                    f"O domínio {nome} foi registrado em {registro.isoformat()}, "
                    f"há {_anos(registro, hoje)} anos."
                ),
                evidencia=_evidencia(dominio),
                peso=1,
            )
        ]
    return []


# --- Web -------------------------------------------------------------------


def regra_web(web: Achado, cfg: Config) -> list[Sinal]:
    if web.status == "falhou" or web.dados.get("nao_informado"):
        return []  # já vira fonte_indisponivel / nao_informado
    resultados = web.dados.get("resultados") or []
    reclamacoes = [r for r in resultados if r.get("rotulo") == "reclamacao" and r.get("url")]
    mencoes = [r for r in resultados if r.get("rotulo") == "mencao" and r.get("url")]
    incertos = [r for r in resultados if r.get("rotulo") in (None, "incerto")]

    sinais: list[Sinal] = []
    if len(reclamacoes) >= cfg.minimo_reclamacoes:
        sinais.append(
            Sinal(
                id="reclamacoes_web",
                tipo="alerta",
                descricao=f"{len(reclamacoes)} resultados na web relatam reclamações sobre esta empresa.",
                evidencia=[r["url"] for r in reclamacoes],
                peso=3,
            )
        )
    elif reclamacoes:
        sinais.append(
            Sinal(
                id="reclamacao_isolada",
                tipo="lacuna",
                descricao=(
                    "Um único resultado na web relata reclamação; abaixo do mínimo para "
                    "considerar um padrão."
                ),
                evidencia=[r["url"] for r in reclamacoes],
                peso=1,
            )
        )
    if incertos:
        sinais.append(
            Sinal(
                id="reclamacoes_incertas",
                tipo="lacuna",
                descricao=(
                    f"{len(incertos)} resultados da web não puderam ser classificados com segurança "
                    "(podem tratar de outra empresa com nome parecido)."
                ),
                evidencia=[r.get("url") or web.rotulo for r in incertos],
                peso=1,
            )
        )
    if not reclamacoes and not mencoes and not incertos:
        sinais.append(
            Sinal(
                id="sem_mencoes_web",
                tipo="lacuna",
                descricao=(
                    "A busca não encontrou menções relevantes a esta empresa. "
                    "Ausência de reclamações não prova idoneidade."
                ),
                evidencia=_evidencia(web),
                peso=1,
            )
        )
    return sinais


# --- Agregação -------------------------------------------------------------


def avaliar(achados: list[Achado], consulta: Consulta, hoje: date, cfg: Config | None = None) -> list[Sinal]:
    """Aplica todas as regras. Sinais conflitantes são todos mantidos, sem desempate."""
    cfg = cfg or Config()
    sinais = regra_lacunas(achados)

    cnpj = _por_fonte(achados, "cnpj")
    if cnpj and cnpj.status == "ok":
        sinais += regra_cnpj_inativo(cnpj)
        sinais += regra_idade_empresa(cnpj, hoje, cfg)
        sinais += regra_nome_divergente(consulta, cnpj, cfg)
        sinais += regra_cnae(consulta, cnpj)

    dominio = _por_fonte(achados, "dominio")
    if dominio and dominio.status == "ok":
        sinais += regra_idade_dominio(dominio, hoje, cfg)

    web = _por_fonte(achados, "web")
    if web:
        sinais += regra_web(web, cfg)

    ordem = {"alerta": 0, "positivo": 1, "lacuna": 2}
    return sorted(sinais, key=lambda s: (ordem[s.tipo], -s.peso, s.id))
