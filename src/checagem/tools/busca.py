"""Busca de menções e reclamações na web, atrás da interface `BuscaWeb`."""

import asyncio
import json
import logging
from pathlib import Path
from typing import Protocol, TypedDict

from checagem.config import Config
from checagem.http import ErroFonte, Http
from checagem.schemas import Achado, Consulta

log = logging.getLogger(__name__)

MAX_TITULO = 200
MAX_TRECHO = 500
MAX_RESULTADOS_POR_BUSCA = 5


class Resultado(TypedDict):
    titulo: str
    url: str
    trecho: str


class BuscaWeb(Protocol):
    nome: str

    async def buscar(self, q: str, prazo: float | None = None) -> list[Resultado]:
        """Levanta `ErroFonte` em falha; o agregador `buscar_web` trata."""
        ...


class SearxngBusca:
    """SearXNG auto-hospedado. Precisa do formato `json` habilitado em `search.formats`."""

    nome = "searxng"

    def __init__(self, http: Http, cfg: Config):
        self.http = http
        self.cfg = cfg

    async def buscar(self, q: str, prazo: float | None = None) -> list[Resultado]:
        url = self.cfg.searxng_url.rstrip("/") + "/search"
        bruto = await self.http.get_json(
            url,
            params={"q": q, "format": "json", "language": "pt-BR", "safesearch": 1},
            timeout=self.cfg.timeout_busca,
            ttl=self.cfg.ttl_busca,
            prazo=prazo,
        )
        resultados = bruto.get("results") if isinstance(bruto, dict) else None
        if not isinstance(resultados, list):
            raise ErroFonte("resposta do SearXNG fora do formato")
        return [
            Resultado(
                titulo=str(r.get("title") or "")[:MAX_TITULO],
                url=str(r["url"]),
                trecho=str(r.get("content") or "")[:MAX_TRECHO],
            )
            for r in resultados[:MAX_RESULTADOS_POR_BUSCA]
            if isinstance(r, dict) and r.get("url")
        ]


class TavilyBusca:
    """Alternativa paga (https://tavily.com). Não implementada na v1.

    Para implementar: POST https://api.tavily.com/search com {"query": q, "max_results": 5}
    e a chave em TAVILY_API_KEY; mapear results[].title/url/content para `Resultado`.
    """

    nome = "tavily"

    async def buscar(self, q: str, prazo: float | None = None) -> list[Resultado]:
        raise NotImplementedError("TavilyBusca ainda não implementada; use SearxngBusca.")


class MockBusca:
    """Lê `busca.json`: {"<consulta>": [{titulo, url, trecho}] | {"_simular": "falha"}}."""

    nome = "mock"

    def __init__(self, dir_fixtures: Path):
        arquivo = Path(dir_fixtures) / "busca.json"
        self.tabela = json.loads(arquivo.read_text(encoding="utf-8")) if arquivo.exists() else {}

    async def buscar(self, q: str, prazo: float | None = None) -> list[Resultado]:
        valor = self.tabela.get(q, [])
        if isinstance(valor, dict) and "_simular" in valor:
            raise ErroFonte(f"simulado: {valor['_simular']}")
        return [Resultado(titulo=r["titulo"][:MAX_TITULO], url=r["url"], trecho=r["trecho"][:MAX_TRECHO]) for r in valor]


def consultas_fixas(consulta: Consulta, orcamento: int) -> list[str]:
    """Consultas geradas por código, nunca pelo LLM."""
    qs = []
    if consulta.nome:
        qs += [f"{consulta.nome} reclamações", f"{consulta.nome} golpe"]
    if consulta.cnpj:
        qs.append(consulta.cnpj)
    return qs[:orcamento]


async def buscar_web(consulta: Consulta, busca: BuscaWeb, cfg: Config, prazo: float | None = None) -> Achado:
    qs = consultas_fixas(consulta, cfg.orcamento_buscas)
    if not qs:
        return Achado(fonte="web", status="sem_dados", dados={"nao_informado": True, "resultados": []})

    respostas = await asyncio.gather(*(busca.buscar(q, prazo) for q in qs), return_exceptions=True)

    vistos: set[str] = set()
    resultados: list[dict] = []
    falhas: list[str] = []
    for q, resp in zip(qs, respostas):
        if isinstance(resp, BaseException):
            falhas.append(f"{q}: {resp}" if isinstance(resp, ErroFonte) else f"{q}: {type(resp).__name__}")
            continue
        for r in resp:
            if r["url"] in vistos:
                continue
            vistos.add(r["url"])
            resultados.append({**r, "consulta": q, "rotulo": None})

    dados = {"motor": busca.nome, "consultas": qs, "resultados": resultados, "falhas": falhas}
    if len(falhas) == len(qs):
        log.warning("busca web falhou em todas as consultas")
        return Achado(fonte="web", status="falhou", dados=dados)
    return Achado(fonte="web", status="ok" if resultados else "sem_dados", dados=dados)
