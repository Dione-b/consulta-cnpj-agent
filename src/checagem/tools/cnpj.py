"""Cadastro público do CNPJ: BrasilAPI, com MinhaReceita como alternativa (mesmo schema)."""

import json
import logging
import re
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, ValidationError

from checagem.config import Config
from checagem.http import ErroFonte, Http, NaoEncontrado
from checagem.schemas import Achado

log = logging.getLogger(__name__)

URL_BRASILAPI = "https://brasilapi.com.br/api/cnpj/v1/{cnpj}"
URL_MINHARECEITA = "https://minhareceita.org/{cnpj}"

# Empresário individual: a razão social é o nome civil da pessoa (muitas vezes com CPF).
NATUREZA_EMPRESARIO_INDIVIDUAL = 2135


class _RespostaCnpj(BaseModel):
    """Só os campos que usamos. `extra="ignore"` descarta QSA, telefones, e-mail e endereço."""

    model_config = ConfigDict(extra="ignore")

    cnpj: str | None = None
    descricao_situacao_cadastral: str | None = None
    data_inicio_atividade: str | None = None
    razao_social: str | None = None
    nome_fantasia: str | None = None
    cnae_fiscal: int | str | None = None
    cnae_fiscal_descricao: str | None = None
    uf: str | None = None
    municipio: str | None = None
    natureza_juridica: str | None = None
    codigo_natureza_juridica: int | None = None
    opcao_pelo_mei: bool | None = None


def _sem_dado_pessoal(texto: str | None) -> str | None:
    """Descarta textos que contenham sequência de dígitos com cara de CPF."""
    if not texto or re.search(r"\d{3}\.?\d{3}\.?\d{3}-?\d{2}", texto):
        return None
    return texto.strip() or None


def normalizar(bruto: dict, url: str) -> Achado:
    try:
        r = _RespostaCnpj.model_validate(bruto)
    except ValidationError:
        return Achado(fonte="cnpj", status="falhou", dados={"erro": "resposta fora do formato"}, url_fonte=url)

    pessoa_fisica = r.codigo_natureza_juridica == NATUREZA_EMPRESARIO_INDIVIDUAL or bool(r.opcao_pelo_mei)
    dados = {
        "situacao": r.descricao_situacao_cadastral,
        "data_abertura": r.data_inicio_atividade,
        # Para empresário individual/MEI a razão social identifica uma pessoa: não entra no estado.
        "razao_social": None if pessoa_fisica else _sem_dado_pessoal(r.razao_social),
        "nome_fantasia": _sem_dado_pessoal(r.nome_fantasia),
        "cnae_principal": {"codigo": str(r.cnae_fiscal) if r.cnae_fiscal else None, "descricao": r.cnae_fiscal_descricao},
        "uf": r.uf,
        "municipio": r.municipio,
        "natureza_juridica": r.natureza_juridica,
        "empresario_individual": pessoa_fisica,
    }
    essenciais = (dados["situacao"], dados["data_abertura"])
    status = "ok" if any(essenciais) else "sem_dados"
    return Achado(fonte="cnpj", status=status, dados=dados, url_fonte=url)


class ConsultaCnpj(Protocol):
    async def __call__(self, cnpj: str, prazo: float | None = None) -> Achado: ...


class ConsultaCnpjReal:
    def __init__(self, http: Http, cfg: Config):
        self.http = http
        self.cfg = cfg

    async def __call__(self, cnpj: str, prazo: float | None = None) -> Achado:
        ultimo_erro = "sem resposta"
        url = URL_BRASILAPI.format(cnpj=cnpj)
        for modelo in (URL_BRASILAPI, URL_MINHARECEITA):
            url = modelo.format(cnpj=cnpj)
            try:
                bruto = await self.http.get_json(url, timeout=self.cfg.timeout_cnpj, ttl=self.cfg.ttl_cnpj, prazo=prazo)
                return normalizar(bruto, url)
            except NaoEncontrado:
                return Achado(fonte="cnpj", status="sem_dados", dados={"erro": "CNPJ não encontrado"}, url_fonte=url)
            except ErroFonte as e:
                ultimo_erro = str(e)
                log.warning("fonte cnpj falhou", extra={"url": modelo, "erro": ultimo_erro})
            except Exception as e:  # nunca levantar para o grafo
                ultimo_erro = f"erro inesperado: {type(e).__name__}"
                log.exception("fonte cnpj erro inesperado")
        return Achado(fonte="cnpj", status="falhou", dados={"erro": ultimo_erro}, url_fonte=url)


class ConsultaCnpjMock:
    """Lê `cnpj_{cnpj}.json` (resposta no formato BrasilAPI). `{"_simular": "falha"}` simula queda."""

    def __init__(self, dir_fixtures: Path):
        self.dir = Path(dir_fixtures)

    async def __call__(self, cnpj: str, prazo: float | None = None) -> Achado:
        url = URL_BRASILAPI.format(cnpj=cnpj)
        arquivo = self.dir / f"cnpj_{cnpj}.json"
        if not arquivo.exists():
            return Achado(fonte="cnpj", status="sem_dados", dados={"erro": "CNPJ não encontrado"}, url_fonte=url)
        bruto = json.loads(arquivo.read_text(encoding="utf-8"))
        if "_simular" in bruto:
            return Achado(fonte="cnpj", status="falhou", dados={"erro": f"simulado: {bruto['_simular']}"}, url_fonte=url)
        return normalizar(bruto, url)
