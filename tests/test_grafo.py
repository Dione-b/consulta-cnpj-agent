"""Dataset de casos da spec, ponta a ponta no grafo, com fixtures e modelo falso."""

import asyncio
import time
from dataclasses import replace

import pytest

from checagem.config import AVISO
from checagem.grafo import checar
from checagem.llm import ModelosSemLLM
from checagem.redator import TERMOS_PROIBIDOS
from checagem.schemas import Achado
from checagem.tools import Ferramentas, ferramentas
from fakes import ModelosFalsos


def ids(estado, tipo=None):
    return {s.id for s in estado["sinais"] if tipo is None or s.tipo == tipo}


CASOS = [
    # (descrição, entrada, alertas esperados, positivos esperados, lacunas esperadas)
    ("1 empresa grande, ativa e antiga", "Magazine Luiza 47.960.950/0001-21 magazineluiza.com.br",
     set(), {"empresa_antiga", "dominio_antigo"}, set()),
    ("3 cnpj baixado", "Casa das Capinhas 12.345.678/0001-95",
     {"cnpj_inativo"}, {"empresa_antiga"}, {"nao_informado", "sem_mencoes_web"}),
    ("4 empresa e domínio novos", "Ofertas Relampago, 23.456.789/0001-95, ofertasrelampago.com.br",
     {"empresa_jovem", "dominio_recente", "reclamacoes_web"}, set(), set()),
    ("5 fonte do cnpj fora do ar", "Loja Estavel 34.567.890/0001-30 lojaestavel.com.br",
     set(), {"dominio_antigo"}, {"fonte_indisponivel", "sem_mencoes_web"}),
    ("8 sinais conflitantes", "Pagina Nova Livros 45.678.901/0001-75 paginanova.com.br",
     {"empresa_jovem"}, {"dominio_antigo"}, {"sem_mencoes_web"}),
]


@pytest.mark.parametrize("_desc,entrada,alertas,positivos,lacunas", CASOS, ids=[c[0] for c in CASOS])
async def test_casos_da_spec(cfg, _desc, entrada, alertas, positivos, lacunas):
    estado = await checar(entrada, cfg, modelos=ModelosFalsos())
    assert "erro" not in estado
    assert ids(estado, "alerta") == alertas
    assert ids(estado, "positivo") == positivos
    assert lacunas <= ids(estado, "lacuna")

    rel = estado["relatorio"]
    assert rel.markdown.endswith(AVISO + "\n")
    assert "## O que não foi possível verificar" in rel.markdown
    assert all(s.evidencia for s in rel.sinais)  # 100% dos sinais com fonte
    for s in estado["sinais"]:
        assert f"[{s.id}]" in rel.markdown
    assert TERMOS_PROIBIDOS.search(rel.resumo) is None


async def test_caso2_cnpj_invalido_recusado_sem_chamada_externa(cfg):
    class Explode:
        def __getattr__(self, _):
            raise AssertionError("nenhuma ferramenta deveria ser chamada")

    f = Ferramentas(cnpj=Explode(), dominio=Explode(), busca=Explode())
    modelos = ModelosFalsos()
    estado = await checar("Loja X 47.960.950/0001-22", cfg, f=f, modelos=modelos)
    assert "CNPJ inválido" in estado["erro"]
    assert "relatorio" not in estado
    assert modelos.chamadas["interpretar"] == []


async def test_caso6_cpf_recusado(cfg):
    estado = await checar("vendedor 123.456.789-09", cfg, modelos=ModelosFalsos())
    assert "pessoa física" in estado["erro"]


async def test_entrada_vazia_recusada(cfg):
    estado = await checar("   ", cfg, modelos=ModelosSemLLM())
    assert "Informe" in estado["erro"]


async def test_cnae_incompativel_pelo_classificador(cfg):
    modelos = ModelosFalsos(cnae="incompativel")
    estado = await checar("Pagina Nova Livros, 45.678.901/0001-75, vende pneus", cfg, modelos=modelos)
    assert "cnae_incompativel" in ids(estado, "alerta")
    assert modelos.chamadas["cnae"] == [("Comércio varejista de livros", "pneus")]


async def test_sem_llm_tudo_vira_lacuna_ou_regra(cfg):
    estado = await checar("Ofertas Relampago 23.456.789/0001-95", cfg, modelos=ModelosSemLLM())
    # Sem classificador, trechos ficam incertos: nenhum alerta de reclamação é inventado.
    assert "reclamacoes_web" not in ids(estado)
    assert "empresa_jovem" in ids(estado, "alerta")
    assert estado["relatorio"].markdown.endswith(AVISO + "\n")


async def test_ramos_rodam_em_paralelo_e_prazo_global(cfg):
    """Ramo lento estoura o prazo global e vira lacuna; os outros seguem."""
    reais = ferramentas(cfg)

    async def cnpj_lento(cnpj, prazo=None):
        await asyncio.sleep(5)
        return Achado(fonte="cnpj", status="ok")

    f = Ferramentas(cnpj=cnpj_lento, dominio=reais.dominio, busca=reais.busca)
    inicio = time.monotonic()
    estado = await checar(
        "Loja Estavel 34.567.890/0001-30 lojaestavel.com.br", replace(cfg, timeout_global=0.3), f=f, modelos=ModelosFalsos()
    )
    assert time.monotonic() - inicio < 2
    falhas = {a.fonte for a in estado["achados"] if a.status == "falhou"}
    assert "cnpj" in falhas
    assert "dominio_antigo" in ids(estado, "positivo")
    assert "fonte_indisponivel" in ids(estado, "lacuna")


async def test_um_achado_por_fonte(cfg):
    estado = await checar("Magazine Luiza 47.960.950/0001-21 magazineluiza.com.br", cfg, modelos=ModelosFalsos())
    assert sorted(a.fonte for a in estado["achados"]) == ["cnpj", "dominio", "web"]
