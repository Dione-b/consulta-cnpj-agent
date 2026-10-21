"""Schemas de tudo que circula no grafo."""

import operator
from datetime import datetime, timezone
from typing import Annotated, Literal, TypedDict

from pydantic import BaseModel, Field, field_validator

from checagem.validacao import cnpj_valido, normalizar_dominio, so_digitos

Fonte = Literal["cnpj", "dominio", "web"]


def agora_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Consulta(BaseModel):
    nome: str | None = None
    cnpj: str | None = None  # só dígitos, 14, dígito verificador válido
    dominio: str | None = None  # sem esquema, minúsculas
    produto: str | None = None  # o que o vendedor diz vender (regra cnae_incompativel)

    @field_validator("cnpj")
    @classmethod
    def _cnpj(cls, v: str | None) -> str | None:
        if v is None:
            return None
        d = so_digitos(v)
        if not cnpj_valido(d):
            raise ValueError("CNPJ inválido")
        return d

    @field_validator("dominio")
    @classmethod
    def _dominio(cls, v: str | None) -> str | None:
        if v is None:
            return None
        d = normalizar_dominio(v)
        if d is None:
            raise ValueError("domínio inválido")
        return d

    @field_validator("nome", "produto")
    @classmethod
    def _texto(cls, v: str | None) -> str | None:
        v = (v or "").strip()
        return v or None

    def vazia(self) -> bool:
        return not (self.nome or self.cnpj or self.dominio)


class Achado(BaseModel):
    fonte: Fonte
    status: Literal["ok", "falhou", "sem_dados"]
    dados: dict = Field(default_factory=dict)
    url_fonte: str | None = None
    consultado_em: str = Field(default_factory=agora_iso)  # ISO 8601

    @property
    def rotulo(self) -> str:
        """Referência usada como evidência quando não há URL."""
        return f"achado:{self.fonte}@{self.consultado_em}"


class Sinal(BaseModel):
    id: str  # ex.: "empresa_jovem"
    tipo: Literal["alerta", "positivo", "lacuna"]
    descricao: str
    evidencia: list[str] = Field(min_length=1)  # URLs ou rótulos de Achado
    peso: int = Field(ge=1, le=3)  # só para ordenar


class Relatorio(BaseModel):
    resumo: str
    sinais: list[Sinal]
    nao_verificado: list[str]
    aviso: str
    markdown: str = ""


class Estado(TypedDict, total=False):
    entrada_bruta: str
    consulta: Consulta
    prazo: float  # time.monotonic() limite da consulta
    achados: Annotated[list[Achado], operator.add]  # reducer dos ramos paralelos
    sinais: list[Sinal]
    relatorio: Relatorio
    erro: str
