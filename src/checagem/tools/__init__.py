"""Ferramentas de coleta. Cada uma devolve um `Achado` e nunca levanta exceção para o grafo."""

from dataclasses import dataclass

from checagem.config import Config
from checagem.http import Http
from checagem.tools.busca import BuscaWeb, MockBusca, SearxngBusca
from checagem.tools.cnpj import ConsultaCnpj, ConsultaCnpjMock, ConsultaCnpjReal
from checagem.tools.dominio import ConsultaDominio, ConsultaDominioMock, ConsultaDominioReal


@dataclass
class Ferramentas:
    cnpj: ConsultaCnpj
    dominio: ConsultaDominio
    busca: BuscaWeb


def ferramentas(cfg: Config) -> Ferramentas:
    """Escolhe a versão mock (fixtures JSON) ou real (APIs) conforme `cfg.mock`."""
    if cfg.mock:
        return Ferramentas(
            cnpj=ConsultaCnpjMock(cfg.dir_fixtures),
            dominio=ConsultaDominioMock(cfg.dir_fixtures),
            busca=MockBusca(cfg.dir_fixtures),
        )
    http = Http(cfg)
    return Ferramentas(
        cnpj=ConsultaCnpjReal(http, cfg),
        dominio=ConsultaDominioReal(http, cfg),
        busca=SearxngBusca(http, cfg),
    )
