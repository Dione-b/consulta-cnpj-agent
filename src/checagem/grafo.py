"""Montagem do StateGraph.

    preparar ─┬─ ramo_cnpj ────┐
              ├─ ramo_dominio ─┼─ avaliar_regras ─ redigir ─ validar_saida
              └─ ramo_web ─────┘
    (entrada recusada vai de preparar direto ao fim)
"""

import logging
import time
import uuid

from langgraph.graph import END, START, StateGraph

from checagem.config import Config
from checagem.llm import Modelos, ModelosSemLLM
from checagem.nos import Nos
from checagem.schemas import Estado
from checagem.tools import Ferramentas, ferramentas

log = logging.getLogger(__name__)

RAMOS = ["ramo_cnpj", "ramo_dominio", "ramo_web"]


def construir(cfg: Config, f: Ferramentas | None = None, modelos: Modelos | None = None):
    nos = Nos(cfg, f or ferramentas(cfg), modelos or ModelosSemLLM())
    g = StateGraph(Estado)
    g.add_node("preparar", nos.preparar)
    g.add_node("ramo_cnpj", nos.ramo_cnpj)
    g.add_node("ramo_dominio", nos.ramo_dominio)
    g.add_node("ramo_web", nos.ramo_web)
    g.add_node("avaliar_regras", nos.avaliar_regras)
    g.add_node("redigir", nos.redigir)
    g.add_node("validar_saida", nos.validar_saida)

    g.add_edge(START, "preparar")
    g.add_conditional_edges("preparar", lambda e: END if e.get("erro") else RAMOS, [*RAMOS, END])
    g.add_edge(RAMOS, "avaliar_regras")  # espera os três ramos
    g.add_edge("avaliar_regras", "redigir")
    g.add_edge("redigir", "validar_saida")
    g.add_edge("validar_saida", END)
    return g.compile()


async def checar(entrada: str, cfg: Config | None = None, f: Ferramentas | None = None, modelos: Modelos | None = None) -> Estado:
    cfg = cfg or Config()
    id_consulta = uuid.uuid4().hex[:12]
    inicio = time.monotonic()
    estado = await construir(cfg, f, modelos).ainvoke({"entrada_bruta": entrada, "achados": []})
    # Log sem o texto digitado: só id, status por fonte e duração.
    log.info(
        "consulta %s concluida em %.1fs; fontes=%s; recusada=%s",
        id_consulta,
        time.monotonic() - inicio,
        {a.fonte: a.status for a in estado.get("achados", [])},
        bool(estado.get("erro")),
    )
    return estado
