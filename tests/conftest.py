from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from checagem.config import Config, carregar_env

carregar_env()  # OPENAI_API_KEY do .env para os testes -m llm

FIXTURES = Path(__file__).parent / "fixtures"
HOJE = date(2026, 10, 21)


@pytest.fixture
def cfg(tmp_path) -> Config:
    """Config isolada: cache em diretório temporário, data fixa, fixtures do repositório."""
    return replace(Config(), dir_cache=tmp_path / "cache", dir_fixtures=FIXTURES, hoje=HOJE, mock=True)


@pytest.fixture
def cfg_real(cfg) -> Config:
    return replace(cfg, mock=False, searxng_url="http://searx.test")
