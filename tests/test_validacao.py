import pytest

from checagem.schemas import Consulta
from checagem.validacao import (
    EntradaRecusada,
    cnpj_valido,
    extrair_cnpj,
    extrair_dominio,
    normalizar_dominio,
    parece_cpf,
    recusar_cpf,
    validar_cnpj_ou_recusar,
)

CNPJ_OK = "47960950000121"


@pytest.mark.parametrize("cnpj", [CNPJ_OK, "47.960.950/0001-21", "11.222.333/0001-81"])
def test_cnpj_valido(cnpj):
    assert cnpj_valido(cnpj)


@pytest.mark.parametrize("cnpj", ["47960950000122", "11111111111111", "123", "4796095000012a"])
def test_cnpj_invalido(cnpj):
    assert not cnpj_valido(cnpj)


def test_caso2_cnpj_invalido_recusado():
    with pytest.raises(EntradaRecusada, match="CNPJ inválido"):
        validar_cnpj_ou_recusar("47.960.950/0001-22")


@pytest.mark.parametrize("texto", ["123.456.789-09", "12345678909", "vendedor cpf 123.456.789-09"])
def test_caso6_cpf_recusado(texto):
    assert parece_cpf(texto)
    with pytest.raises(EntradaRecusada, match="pessoa física"):
        recusar_cpf(texto)


def test_cnpj_nao_e_confundido_com_cpf():
    assert not parece_cpf("Loja X 47.960.950/0001-21 lojax.com.br")
    assert not parece_cpf(CNPJ_OK)


def test_extrair():
    texto = "Loja X, 47.960.950/0001-21, https://www.LojaX.com.br/produtos?id=1"
    assert extrair_cnpj(texto) == CNPJ_OK
    assert extrair_dominio(texto) == "lojax.com.br"


def test_extrair_dominio_ignora_email():
    assert extrair_dominio("contato@lojax.com.br") is None


@pytest.mark.parametrize(
    "entrada,esperado",
    [
        ("HTTPS://Exemplo.com.br/", "exemplo.com.br"),
        ("www.exemplo.com:443/x", "exemplo.com"),
        ("exemplo.store", "exemplo.store"),
        ("sem dominio", None),
    ],
)
def test_normalizar_dominio(entrada, esperado):
    assert normalizar_dominio(entrada) == esperado


def test_consulta_normaliza():
    c = Consulta(nome="  Loja  ", cnpj="47.960.950/0001-21", dominio="https://WWW.Loja.com.br/a")
    assert c.cnpj == CNPJ_OK
    assert c.dominio == "loja.com.br"
    assert c.nome == "Loja"


def test_consulta_rejeita_cnpj_invalido():
    with pytest.raises(ValueError):
        Consulta(cnpj="47960950000122")


def test_carregar_env(tmp_path, monkeypatch):
    import os

    from checagem.config import carregar_env

    monkeypatch.delenv("X_TESTE_A", raising=False)
    monkeypatch.delenv("X_TESTE_VAZIA", raising=False)
    monkeypatch.setenv("X_TESTE_B", "do_ambiente")
    arq = tmp_path / ".env"
    arq.write_text('# comentario\nX_TESTE_A="valor"\nX_TESTE_B=do_arquivo\nX_TESTE_VAZIA=\n', encoding="utf-8")
    carregar_env(arq)
    assert os.environ["X_TESTE_A"] == "valor"
    assert os.environ["X_TESTE_B"] == "do_ambiente"  # ambiente tem prioridade
    assert "X_TESTE_VAZIA" not in os.environ
    monkeypatch.delenv("X_TESTE_A")
