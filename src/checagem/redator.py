"""Montagem e validação do relatório. O Markdown, as seções e o aviso são sempre do código."""

import re

from checagem.config import AVISO
from checagem.llm import Redacao
from checagem.schemas import Relatorio, Sinal

TERMOS_PROIBIDOS = re.compile(
    r"\b(golp\w*|fraud\w*|segur[oa]s?|confi[aá]ve(l|is)|idône[oa]s?|"
    r"recomend\w*|aconselh\w*|(n[aã]o\s+)?compre(m)?)\b",
    re.IGNORECASE,
)
RE_ID_CITADO = re.compile(r"\[([a-z0-9_]+)\]")

TITULOS = {
    "alerta": "Sinais de alerta",
    "positivo": "Sinais positivos",
    "lacuna": "O que não foi possível verificar",
}


def _por_tipo(sinais: list[Sinal], tipo: str) -> list[Sinal]:
    return sorted((s for s in sinais if s.tipo == tipo), key=lambda s: (-s.peso, s.id))


MAX_FONTES_EXIBIDAS = 5


def _fontes(sinal: Sinal) -> str:
    exibidas = sinal.evidencia[:MAX_FONTES_EXIBIDAS]
    texto = ", ".join(f"<{e}>" if e.startswith("http") else f"`{e}`" for e in exibidas)
    if resto := len(sinal.evidencia) - len(exibidas):
        texto += f" e mais {resto}"
    return texto


def montar(sinais: list[Sinal], resumo: str, textos: dict[str, str]) -> Relatorio:
    """Monta o relatório com as 5 seções fixas. `textos` mapeia id do sinal -> frase."""
    linhas = ["## Resumo", "", resumo, ""]
    for tipo in ("alerta", "positivo", "lacuna"):
        linhas += [f"## {TITULOS[tipo]}", ""]
        grupo = _por_tipo(sinais, tipo)
        if not grupo:
            linhas.append("- Nenhum.")
        for s in grupo:
            texto = textos.get(s.id) or f"{s.descricao} [{s.id}]"
            linhas.append(f"- {texto} Fonte: {_fontes(s)}")
        linhas.append("")
    linhas += ["## Aviso", "", AVISO, ""]
    return Relatorio(
        resumo=resumo,
        sinais=sinais,
        nao_verificado=[s.descricao for s in _por_tipo(sinais, "lacuna")],
        aviso=AVISO,
        markdown="\n".join(linhas),
    )


def resumo_padrao(sinais: list[Sinal]) -> str:
    n = {t: len(_por_tipo(sinais, t)) for t in TITULOS}
    return (
        f"Foram encontrados {n['alerta']} sinal(is) de alerta e {n['positivo']} sinal(is) positivo(s) "
        f"nas fontes públicas consultadas; {n['lacuna']} ponto(s) não puderam ser verificados."
    )


def modelo_de_texto(sinais: list[Sinal]) -> Relatorio:
    """Relatório sem LLM: usado no modo sem modelo e quando o redator falha duas vezes."""
    return montar(sinais, resumo_padrao(sinais), {})


def validar_redacao(redacao: Redacao, sinais: list[Sinal]) -> list[str]:
    """Devolve a lista de problemas; vazia quando a redação pode ser usada."""
    ids = {s.id for s in sinais}
    problemas: list[str] = []
    textos = [redacao.resumo] + [i.texto for i in redacao.itens]

    for t in textos:
        if m := TERMOS_PROIBIDOS.search(t):
            problemas.append(f"termo proibido: {m.group(0)!r}")
        for citado in RE_ID_CITADO.findall(t):
            if citado not in ids:
                problemas.append(f"id inexistente citado: {citado!r}")

    for item in redacao.itens:
        if item.id not in ids:
            problemas.append(f"item para sinal inexistente: {item.id!r}")
        elif f"[{item.id}]" not in item.texto:
            problemas.append(f"item {item.id!r} não cita o próprio id")

    faltando = ids - {i.id for i in redacao.itens}
    if faltando:
        problemas.append(f"sinais sem item: {sorted(faltando)}")
    if len(re.findall(r"[.!?](\s|$)", redacao.resumo.strip())) > 2:
        problemas.append("resumo com mais de duas frases")
    return problemas


def relatorio_de_redacao(redacao: Redacao, sinais: list[Sinal]) -> Relatorio:
    return montar(sinais, redacao.resumo.strip(), {i.id: i.texto.strip() for i in redacao.itens})


def validar_relatorio(relatorio: Relatorio, sinais: list[Sinal]) -> list[str]:
    """Checagem final sobre o Markdown pronto (vale também para o modelo de texto)."""
    problemas = []
    if AVISO not in relatorio.markdown:
        problemas.append("aviso ausente")
    if f"## {TITULOS['lacuna']}" not in relatorio.markdown:
        problemas.append("seção do que não foi verificado ausente")
    ids = {s.id for s in sinais}
    for citado in RE_ID_CITADO.findall(relatorio.markdown):
        if citado not in ids:
            problemas.append(f"id inexistente citado: {citado!r}")
    if any(not s.evidencia for s in sinais):
        problemas.append("sinal sem fonte")
    return problemas
