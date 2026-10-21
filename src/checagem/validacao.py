"""Validações de entrada feitas em código, antes de qualquer chamada externa."""

import re


class EntradaRecusada(ValueError):
    """Entrada que o agente se recusa a processar. A mensagem vai para o usuário."""


def so_digitos(texto: str) -> str:
    return re.sub(r"\D", "", texto)


def _digito(base: str, pesos: list[int]) -> str:
    resto = sum(int(d) * p for d, p in zip(base, pesos)) % 11
    return "0" if resto < 2 else str(11 - resto)


def cnpj_valido(cnpj: str) -> bool:
    d = so_digitos(cnpj)
    if len(d) != 14 or d == d[0] * 14:
        return False
    p1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    p2 = [6] + p1
    return d[12] == _digito(d[:12], p1) and d[13] == _digito(d[:13], p2)


# CNPJ formatado (00.000.000/0000-00) ou 14 dígitos seguidos.
_RE_CNPJ = re.compile(r"(?<!\d)(\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2})(?!\d)")
# CPF formatado (000.000.000-00) ou 11 dígitos seguidos.
_RE_CPF = re.compile(r"(?<![\d./-])(\d{3}\.?\d{3}\.?\d{3}-?\d{2})(?![\d./-])")
_RE_DOMINIO = re.compile(
    r"(?:https?://)?(?:www\.)?((?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,})(?:[/:?#]\S*)?",
    re.IGNORECASE,
)


def parece_cpf(texto: str) -> bool:
    """Há na entrada um número com formato de CPF (11 dígitos) que não faz parte de um CNPJ."""
    sem_cnpj = _RE_CNPJ.sub(" ", texto)
    return bool(_RE_CPF.search(sem_cnpj))


def extrair_cnpj(texto: str) -> str | None:
    m = _RE_CNPJ.search(texto)
    return so_digitos(m.group(1)) if m else None


def normalizar_dominio(texto: str) -> str | None:
    """Tira esquema, www., porta e caminho; devolve em minúsculas ou None."""
    m = _RE_DOMINIO.search(texto.strip())
    return m.group(1).lower() if m else None


def extrair_dominio(texto: str) -> str | None:
    # Ignora e-mails: o domínio de um e-mail não é o site da loja.
    sem_email = re.sub(r"\S+@\S+", " ", texto)
    return normalizar_dominio(sem_email)


def validar_cnpj_ou_recusar(cnpj: str) -> str:
    d = so_digitos(cnpj)
    if not cnpj_valido(d):
        raise EntradaRecusada(f"CNPJ inválido: {cnpj!r}. Confira os dígitos verificadores.")
    return d


def recusar_cpf(texto: str) -> None:
    if parece_cpf(texto):
        raise EntradaRecusada(
            "A entrada parece conter um CPF. Este agente só consulta pessoa jurídica (CNPJ) "
            "e não processa dados de pessoa física."
        )
