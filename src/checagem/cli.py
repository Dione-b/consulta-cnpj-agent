"""Linha de comando: checagem "Loja X, 12.345.678/0001-90, lojax.com.br"."""

import argparse
import asyncio
import json
import logging
import os
import sys
from dataclasses import replace

from checagem.config import Config, carregar_env
from checagem.grafo import checar
from checagem.llm import Modelos, ModelosLangChain, ModelosSemLLM


def _callbacks() -> list:
    """Traces no Langfuse quando as chaves estão no ambiente (opcional)."""
    if not os.getenv("LANGFUSE_PUBLIC_KEY"):
        return []
    try:
        from langfuse.langchain import CallbackHandler
    except ImportError:
        print("aviso: LANGFUSE_* definido, mas o pacote langfuse não está instalado", file=sys.stderr)
        return []
    return [CallbackHandler()]


def escolher_modelos(cfg: Config, sem_llm: bool) -> Modelos:
    if sem_llm:
        return ModelosSemLLM()
    if cfg.modelo.startswith("openai:") and not os.getenv("OPENAI_API_KEY"):
        print("aviso: OPENAI_API_KEY ausente; rodando sem LLM (classificações viram lacunas)", file=sys.stderr)
        return ModelosSemLLM()
    return ModelosLangChain(cfg.modelo, callbacks=_callbacks())


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="checagem", description="Lista sinais públicos sobre um vendedor, com fonte.")
    p.add_argument("entrada", nargs="+", help="nome, CNPJ e/ou site do vendedor (texto livre)")
    p.add_argument("--mock", action="store_true", help="usar fixtures em vez das APIs reais")
    p.add_argument("--sem-llm", action="store_true", help="não chamar modelo de linguagem")
    p.add_argument("--json", action="store_true", help="imprimir o relatório em JSON")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)
    carregar_env()

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    for ruidoso in ("httpx", "httpcore", "openai"):
        logging.getLogger(ruidoso).setLevel(logging.WARNING)

    cfg = Config()
    if args.mock:
        cfg = replace(cfg, mock=True)

    estado = asyncio.run(checar(" ".join(args.entrada), cfg, modelos=escolher_modelos(cfg, args.sem_llm)))
    if erro := estado.get("erro"):
        print(f"Consulta recusada: {erro}", file=sys.stderr)
        return 2

    relatorio = estado["relatorio"]
    if args.json:
        print(json.dumps(relatorio.model_dump(), ensure_ascii=False, indent=2))
    else:
        print(relatorio.markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
