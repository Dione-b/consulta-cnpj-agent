"""Modelo falso determinístico para testar o grafo sem rede e sem LLM."""

import re

from checagem.llm import Interpretacao, ItemRedigido, Redacao
from checagem.schemas import Sinal

PALAVRAS_RECLAMACAO = ("não chegou", "não entregou", "não recebi", "estorno", "não enviado", "não responde", "rastreio")


class ModelosFalsos:
    def __init__(self, redacoes: list[Redacao] | None = None, cnae: str = "compativel"):
        self.redacoes = list(redacoes or [])  # respostas do redator em ordem; vazio = redação correta
        self.cnae = cnae
        self.chamadas: dict[str, list] = {"interpretar": [], "trechos": [], "cnae": [], "redigir": []}

    async def interpretar(self, texto: str) -> Interpretacao:
        self.chamadas["interpretar"].append(texto)
        # Imita um LLM: o nome é o que vem antes do primeiro número/vírgula; "vende X" vira produto.
        nome = re.split(r"[,\d]|\s(?:vende|site)\b", texto, maxsplit=1)[0].strip(" ,") or None
        produto = m.group(1).strip() if (m := re.search(r"vende\s+([^,]+)", texto)) else None
        return Interpretacao(nome=nome, produto=produto)

    async def classificar_trechos(self, empresa: str, trechos: list[dict]) -> dict[int, str]:
        self.chamadas["trechos"].append((empresa, trechos))
        rotulos = {}
        for i, t in enumerate(trechos):
            texto = f"{t['titulo']} {t['trecho']}".lower()
            if empresa.lower() not in texto:
                rotulos[i] = "nao_relacionado"
            elif any(p in texto for p in PALAVRAS_RECLAMACAO):
                rotulos[i] = "reclamacao"
            else:
                rotulos[i] = "mencao"
        return rotulos

    async def classificar_cnae(self, atividade: str, produto: str) -> str:
        self.chamadas["cnae"].append((atividade, produto))
        return self.cnae

    async def redigir(self, sinais: list[Sinal], correcao: str | None = None) -> Redacao:
        self.chamadas["redigir"].append((sinais, correcao))
        if self.redacoes:
            return self.redacoes.pop(0)
        return redacao_correta(sinais)


def redacao_correta(sinais: list[Sinal]) -> Redacao:
    return Redacao(
        resumo=f"O relatório reúne {len(sinais)} sinais das fontes públicas consultadas.",
        itens=[ItemRedigido(id=s.id, texto=f"{s.descricao} [{s.id}]") for s in sinais],
    )
