"""Data de registro do domínio via RDAP (padrão IETF).

A rota Registro.br da BrasilAPI não informa a data de registro, só status e vencimento;
por isso `.br` vai direto ao RDAP do Registro.br e os demais TLDs ao bootstrap do rdap.org.
"""

import json
import logging
from pathlib import Path
from typing import Protocol

from checagem.config import Config
from checagem.http import ErroFonte, Http, NaoEncontrado
from checagem.schemas import Achado

log = logging.getLogger(__name__)

URL_RDAP_BR = "https://rdap.registro.br/domain/{dominio}"
URL_RDAP = "https://rdap.org/domain/{dominio}"


def url_rdap(dominio: str) -> str:
    modelo = URL_RDAP_BR if dominio.endswith(".br") else URL_RDAP
    return modelo.format(dominio=dominio)


def normalizar(bruto: dict, dominio: str, url: str) -> Achado:
    """Extrai só a data de registro e os servidores de nome. Entidades (titular, contatos) são descartadas."""
    eventos = bruto.get("events") if isinstance(bruto, dict) else None
    data_registro = None
    for ev in eventos or []:
        if isinstance(ev, dict) and ev.get("eventAction") == "registration" and ev.get("eventDate"):
            data_registro = str(ev["eventDate"])[:10]
            break
    servidores = [
        str(ns.get("ldhName")).lower()
        for ns in (bruto.get("nameservers") or [] if isinstance(bruto, dict) else [])
        if isinstance(ns, dict) and ns.get("ldhName")
    ]
    dados = {"dominio": dominio, "data_registro": data_registro, "servidores_nome": servidores}
    return Achado(fonte="dominio", status="ok" if data_registro else "sem_dados", dados=dados, url_fonte=url)


class ConsultaDominio(Protocol):
    async def __call__(self, dominio: str, prazo: float | None = None) -> Achado: ...


class ConsultaDominioReal:
    def __init__(self, http: Http, cfg: Config):
        self.http = http
        self.cfg = cfg

    async def __call__(self, dominio: str, prazo: float | None = None) -> Achado:
        url = url_rdap(dominio)
        try:
            bruto = await self.http.get_json(url, timeout=self.cfg.timeout_dominio, ttl=self.cfg.ttl_dominio, prazo=prazo)
            return normalizar(bruto, dominio, url)
        except NaoEncontrado:
            dados = {"dominio": dominio, "erro": "domínio não encontrado no RDAP"}
            return Achado(fonte="dominio", status="sem_dados", dados=dados, url_fonte=url)
        except ErroFonte as e:
            log.warning("fonte dominio falhou", extra={"erro": str(e)})
            return Achado(fonte="dominio", status="falhou", dados={"dominio": dominio, "erro": str(e)}, url_fonte=url)
        except Exception as e:  # nunca levantar para o grafo
            log.exception("fonte dominio erro inesperado")
            dados = {"dominio": dominio, "erro": f"erro inesperado: {type(e).__name__}"}
            return Achado(fonte="dominio", status="falhou", dados=dados, url_fonte=url)


class ConsultaDominioMock:
    """Lê `dominio_{dominio}.json` (resposta RDAP). `{"_simular": "falha"}` simula queda."""

    def __init__(self, dir_fixtures: Path):
        self.dir = Path(dir_fixtures)

    async def __call__(self, dominio: str, prazo: float | None = None) -> Achado:
        url = url_rdap(dominio)
        arquivo = self.dir / f"dominio_{dominio}.json"
        if not arquivo.exists():
            return Achado(fonte="dominio", status="sem_dados", dados={"dominio": dominio}, url_fonte=url)
        bruto = json.loads(arquivo.read_text(encoding="utf-8"))
        if "_simular" in bruto:
            dados = {"dominio": dominio, "erro": f"simulado: {bruto['_simular']}"}
            return Achado(fonte="dominio", status="falhou", dados=dados, url_fonte=url)
        return normalizar(bruto, dominio, url)
