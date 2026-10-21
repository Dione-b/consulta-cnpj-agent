"""Limiares, timeouts e TTLs. Valores iniciais, a calibrar no marco 5."""

import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path


RAIZ = Path(__file__).resolve().parents[2]


def carregar_env(arquivo: Path = RAIZ / ".env") -> None:
    """Lê KEY=VALOR do .env sem sobrescrever variáveis já definidas. Valores vazios são ignorados."""
    if not arquivo.exists():
        return
    for linha in arquivo.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.removeprefix("export ").split("=", 1)
        chave, valor = chave.strip(), valor.strip().strip("'\"")
        if valor and chave not in os.environ:
            os.environ[chave] = valor


def _env_data(nome: str) -> date | None:
    valor = os.getenv(nome)
    return date.fromisoformat(valor) if valor else None


def _env_bool(nome: str, padrao: bool) -> bool:
    valor = os.getenv(nome)
    if valor is None:
        return padrao
    return valor.strip().lower() in {"1", "true", "sim", "yes"}


@dataclass(frozen=True)
class Config:
    # Regras
    dias_empresa_jovem: int = 180
    anos_empresa_antiga: int = 5
    dias_dominio_recente: int = 90
    anos_dominio_antigo: int = 3
    similaridade_minima: float = 0.6
    minimo_reclamacoes: int = 2

    # Timeouts (s)
    timeout_cnpj: float = 8.0
    timeout_dominio: float = 8.0
    timeout_busca: float = 10.0
    timeout_global: float = 45.0

    # Cache (s)
    ttl_cnpj: int = 24 * 3600
    ttl_dominio: int = 24 * 3600
    ttl_busca: int = 3600

    # Limites
    max_concorrencia: int = 3
    max_tentativas: int = 2
    orcamento_buscas: int = 6

    # Ambiente
    hoje: date | None = field(default_factory=lambda: _env_data("CHECAGEM_HOJE"))  # fixa a data nos testes
    mock: bool = field(default_factory=lambda: _env_bool("CHECAGEM_MOCK", False))
    modelo: str = field(default_factory=lambda: os.getenv("CHECAGEM_MODELO", "openai:gpt-4.1-mini"))
    searxng_url: str = field(default_factory=lambda: os.getenv("SEARXNG_URL", "http://localhost:8080"))
    dir_cache: Path = field(
        default_factory=lambda: Path(os.getenv("CHECAGEM_CACHE", Path.home() / ".cache" / "checagem"))
    )
    dir_fixtures: Path = field(
        default_factory=lambda: Path(
            os.getenv("CHECAGEM_FIXTURES", RAIZ / "tests" / "fixtures")
        )
    )

    def data_hoje(self) -> date:
        return self.hoje or date.today()


AVISO = "Este relatório lista dados públicos e não é uma avaliação de idoneidade. Confirme antes de pagar."
