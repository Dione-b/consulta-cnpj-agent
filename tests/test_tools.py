import json
import time

import httpx
import pytest
import respx

from checagem.http import Http
from checagem.schemas import Consulta
from checagem.tools import ferramentas
from checagem.tools.busca import MockBusca, SearxngBusca, buscar_web, consultas_fixas
from checagem.tools.cnpj import ConsultaCnpjMock, ConsultaCnpjReal
from checagem.tools.dominio import ConsultaDominioReal, url_rdap
from conftest import FIXTURES

CNPJ = "47960950000121"
URL_BRASIL = f"https://brasilapi.com.br/api/cnpj/v1/{CNPJ}"
URL_MINHA = f"https://minhareceita.org/{CNPJ}"


def bruto_cnpj(nome="cnpj_47960950000121.json"):
    return json.loads((FIXTURES / nome).read_text(encoding="utf-8"))


# --- CNPJ ------------------------------------------------------------------


@respx.mock
async def test_cnpj_sucesso_descarta_socios_e_contatos(cfg_real):
    respx.get(URL_BRASIL).respond(json=bruto_cnpj())
    achado = await ConsultaCnpjReal(Http(cfg_real), cfg_real)(CNPJ)
    assert achado.status == "ok"
    assert achado.dados["situacao"] == "ATIVA"
    assert achado.dados["data_abertura"] == "1966-10-24"
    assert achado.url_fonte == URL_BRASIL
    texto = json.dumps(achado.model_dump(), ensure_ascii=False)
    for proibido in ("qsa", "FULANO", "email", "telefone", "logradouro"):
        assert proibido not in texto


@respx.mock
async def test_cnpj_500_tenta_duas_vezes_e_usa_alternativa(cfg_real):
    primaria = respx.get(URL_BRASIL).respond(500)
    respx.get(URL_MINHA).respond(json=bruto_cnpj())
    achado = await ConsultaCnpjReal(Http(cfg_real), cfg_real)(CNPJ)
    assert primaria.call_count == 2
    assert achado.status == "ok"
    assert achado.url_fonte == URL_MINHA


@respx.mock
async def test_caso5_cnpj_todas_as_fontes_fora_vira_falhou(cfg_real):
    respx.get(URL_BRASIL).respond(500)
    respx.get(URL_MINHA).mock(side_effect=httpx.ConnectTimeout("timeout"))
    achado = await ConsultaCnpjReal(Http(cfg_real), cfg_real)(CNPJ)
    assert achado.status == "falhou"
    assert "timeout" in achado.dados["erro"]


@respx.mock
async def test_cnpj_400_nao_repete(cfg_real):
    rota = respx.get(URL_BRASIL).respond(400)
    respx.get(URL_MINHA).respond(400)
    achado = await ConsultaCnpjReal(Http(cfg_real), cfg_real)(CNPJ)
    assert rota.call_count == 1
    assert achado.status == "falhou"


@respx.mock
async def test_cnpj_404_e_sem_dados(cfg_real):
    respx.get(URL_BRASIL).respond(404)
    achado = await ConsultaCnpjReal(Http(cfg_real), cfg_real)(CNPJ)
    assert achado.status == "sem_dados"


@respx.mock
async def test_cnpj_campos_ausentes_viram_sem_dados(cfg_real):
    respx.get(URL_BRASIL).respond(json={"cnpj": CNPJ})
    achado = await ConsultaCnpjReal(Http(cfg_real), cfg_real)(CNPJ)
    assert achado.status == "sem_dados"
    assert achado.dados["situacao"] is None  # nunca valor inventado


@respx.mock
async def test_cnpj_cache(cfg_real):
    rota = respx.get(URL_BRASIL).respond(json=bruto_cnpj())
    http = Http(cfg_real)
    await ConsultaCnpjReal(http, cfg_real)(CNPJ)
    await ConsultaCnpjReal(http, cfg_real)(CNPJ)
    assert rota.call_count == 1


async def test_cnpj_prazo_global_esgotado(cfg_real):
    achado = await ConsultaCnpjReal(Http(cfg_real), cfg_real)(CNPJ, prazo=time.monotonic() - 1)
    assert achado.status == "falhou"
    assert "prazo" in achado.dados["erro"]


async def test_cnpj_mei_descarta_nome_da_pessoa(cfg):
    achado = await ConsultaCnpjMock(cfg.dir_fixtures)("56789012000100")
    assert achado.dados["razao_social"] is None
    assert achado.dados["empresario_individual"] is True
    assert "MARIA DA SILVA" not in json.dumps(achado.model_dump(), ensure_ascii=False)


async def test_cnpj_mock_simula_falha(cfg):
    assert (await ConsultaCnpjMock(cfg.dir_fixtures)("34567890000130")).status == "falhou"


# --- Domínio ---------------------------------------------------------------


def test_url_rdap_por_tld():
    assert url_rdap("loja.com.br") == "https://rdap.registro.br/domain/loja.com.br"
    assert url_rdap("loja.com") == "https://rdap.org/domain/loja.com"


@respx.mock
async def test_dominio_sucesso_descarta_titular(cfg_real):
    bruto = json.loads((FIXTURES / "dominio_magazineluiza.com.br.json").read_text(encoding="utf-8"))
    respx.get(url_rdap("magazineluiza.com.br")).respond(json=bruto)
    achado = await ConsultaDominioReal(Http(cfg_real), cfg_real)("magazineluiza.com.br")
    assert achado.status == "ok"
    assert achado.dados["data_registro"] == "1997-10-06"
    assert "PESSOA TITULAR" not in json.dumps(achado.model_dump())


@respx.mock
async def test_dominio_sem_evento_de_registro(cfg_real):
    respx.get(url_rdap("x.com")).respond(json={"events": [{"eventAction": "expiration", "eventDate": "2030-01-01"}]})
    achado = await ConsultaDominioReal(Http(cfg_real), cfg_real)("x.com")
    assert achado.status == "sem_dados"


@respx.mock
async def test_dominio_timeout_vira_falhou(cfg_real):
    rota = respx.get(url_rdap("x.com")).mock(side_effect=httpx.ReadTimeout("t"))
    achado = await ConsultaDominioReal(Http(cfg_real), cfg_real)("x.com")
    assert rota.call_count == 2
    assert achado.status == "falhou"


@respx.mock
async def test_dominio_json_invalido_vira_falhou(cfg_real):
    respx.get(url_rdap("x.com")).respond(text="<html>")
    assert (await ConsultaDominioReal(Http(cfg_real), cfg_real)("x.com")).status == "falhou"


# --- Busca -----------------------------------------------------------------


def test_consultas_fixas_e_orcamento():
    c = Consulta(nome="Loja X", cnpj=CNPJ)
    assert consultas_fixas(c, 6) == ["Loja X reclamações", "Loja X golpe", CNPJ]
    assert consultas_fixas(c, 2) == ["Loja X reclamações", "Loja X golpe"]


@respx.mock
async def test_searxng_e_deduplicacao(cfg_real):
    resultado = {"title": "t", "url": "https://a.com/1", "content": "x" * 900}
    respx.get("http://searx.test/search").respond(json={"results": [resultado, {"title": "sem url"}]})
    achado = await buscar_web(Consulta(nome="Loja X", cnpj=CNPJ), SearxngBusca(Http(cfg_real), cfg_real), cfg_real)
    assert achado.status == "ok"
    assert len(achado.dados["resultados"]) == 1  # mesma URL em 3 consultas
    assert len(achado.dados["resultados"][0]["trecho"]) == 500


@respx.mock
async def test_busca_toda_fora_vira_falhou(cfg_real):
    respx.get("http://searx.test/search").respond(503)
    achado = await buscar_web(Consulta(nome="Loja X"), SearxngBusca(Http(cfg_real), cfg_real), cfg_real)
    assert achado.status == "falhou"


async def test_busca_parcial_segue(cfg):
    achado = await buscar_web(Consulta(nome="Loja Estavel"), MockBusca(cfg.dir_fixtures), cfg)
    assert achado.status == "sem_dados"
    assert len(achado.dados["falhas"]) == 1


async def test_busca_sem_nome_nem_cnpj(cfg):
    achado = await buscar_web(Consulta(dominio="x.com"), MockBusca(cfg.dir_fixtures), cfg)
    assert achado.dados["nao_informado"] is True


@pytest.mark.parametrize("mock", [True, False])
def test_fabrica(cfg, mock):
    from dataclasses import replace

    f = ferramentas(replace(cfg, mock=mock))
    assert (f.busca.nome == "mock") is mock
