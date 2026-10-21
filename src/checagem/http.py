"""Cliente HTTP comum às ferramentas: timeout, retentativa, cache e limite de concorrência."""

import asyncio
import logging
import time

import diskcache
import httpx
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from checagem.config import Config

log = logging.getLogger(__name__)

USER_AGENT = "checagem-vendedor/0.1 (projeto didatico)"


class ErroFonte(Exception):
    """Falha definitiva de uma fonte (4xx, JSON inválido, prazo esgotado)."""


class ErroTransitorio(ErroFonte):
    """Timeout ou 5xx: vale tentar de novo."""


class NaoEncontrado(ErroFonte):
    """404: a fonte respondeu que não tem o registro."""


def restante(prazo: float | None, timeout: float) -> float:
    """Timeout efetivo respeitando o prazo global da consulta."""
    if prazo is None:
        return timeout
    sobra = prazo - time.monotonic()
    if sobra <= 0:
        raise ErroFonte("prazo global da consulta esgotado")
    return min(timeout, sobra)


class Http:
    def __init__(self, cfg: Config, transport: httpx.AsyncBaseTransport | None = None):
        self.cfg = cfg
        self._transport = transport
        self._sem = asyncio.Semaphore(cfg.max_concorrencia)
        self._cache = diskcache.Cache(str(cfg.dir_cache))

    async def get_json(
        self,
        url: str,
        *,
        timeout: float,
        ttl: int,
        prazo: float | None = None,
        params: dict | None = None,
    ):
        chave = f"{url}?{sorted((params or {}).items())}"
        em_cache = self._cache.get(chave)
        if em_cache is not None:
            return em_cache

        async for tentativa in AsyncRetrying(
            stop=stop_after_attempt(self.cfg.max_tentativas),
            wait=wait_exponential(multiplier=0.5, max=2),
            retry=retry_if_exception_type(ErroTransitorio),
            reraise=True,
        ):
            with tentativa:
                dados = await self._uma_vez(url, timeout=restante(prazo, timeout), params=params)

        self._cache.set(chave, dados, expire=ttl)
        return dados

    async def _uma_vez(self, url: str, *, timeout: float, params: dict | None):
        async with self._sem:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=timeout,
                follow_redirects=True,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            ) as cliente:
                try:
                    resp = await cliente.get(url, params=params)
                except httpx.TimeoutException as e:
                    raise ErroTransitorio(f"timeout após {timeout:.1f}s") from e
                except httpx.TransportError as e:
                    raise ErroTransitorio(f"erro de rede: {type(e).__name__}") from e
        if resp.status_code == 404:
            raise NaoEncontrado("HTTP 404")
        if resp.status_code >= 500:
            raise ErroTransitorio(f"HTTP {resp.status_code}")
        if resp.status_code >= 400:
            raise ErroFonte(f"HTTP {resp.status_code}")
        try:
            return resp.json()
        except ValueError as e:
            raise ErroFonte("resposta não é JSON") from e
