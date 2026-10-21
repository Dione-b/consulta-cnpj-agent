# Agente de Checagem de Vendedor

Recebe nome, CNPJ e/ou site de um vendedor e devolve um relatório de **sinais públicos com fonte**.
Nunca conclui que o vendedor é golpista nem que é seguro. Projeto didático da aula de agentes (LangGraph).

```
preparar ─┬─ ramo_cnpj ────┐
          ├─ ramo_dominio ─┼─ avaliar_regras ─ redigir ─ validar_saida
          └─ ramo_web ─────┘
```

- **preparar**: recusa CPF e CNPJ inválido em código, antes de qualquer chamada externa; o interpretador (LLM) só sugere nome e produto.
- **ramos**: rodam em paralelo; cada um devolve um `Achado` e nunca levanta exceção. Fonte fora do ar vira `falhou`, e isso vira a lacuna `fonte_indisponivel`.
- **avaliar_regras**: código determinístico (`regras.py`). O LLM só classifica trechos e CNAE dentro de enums fechados.
- **redigir**: o LLM recebe só os `Sinal` validados (nunca o texto da web) e devolve uma frase por sinal. O código monta as seções e o aviso, valida e, se falhar duas vezes, usa um modelo de texto.

## Instalação

```bash
python -m venv .venv && .venv/bin/pip install -e '.[dev]'
```

ou, com `uv`: `uv sync --extra dev`.

```bash
cp .env.example .env
```

Busca web (SearXNG local, com saída JSON habilitada em `searxng/settings.yml`). Defina antes `SEARXNG_SECRET` no `.env` (`openssl rand -hex 32`):

```bash
docker compose up -d searxng
```

## Uso

```bash
.venv/bin/checagem "Loja X, vende celulares, 12.345.678/0001-95, lojax.com.br"
```

- `--mock`: usa as fixtures de `tests/fixtures` em vez das APIs.
- `--sem-llm`: sem modelo; as classificações viram lacunas e o relatório sai do modelo de texto.
- `--json`: imprime o `Relatorio` em JSON. Código de saída 2 = consulta recusada.

Sem `OPENAI_API_KEY`, o CLI roda automaticamente sem LLM e avisa no stderr. O modelo é definido em `CHECAGEM_MODELO` (formato `provedor:modelo` do `init_chat_model`).

## Testes

```bash
.venv/bin/pytest
```

Roda sem rede e sem LLM (fixtures + `respx` + modelo falso em `tests/fakes.py`).

```bash
.venv/bin/pytest -m llm
```

Usa o modelo real: classificador ≥ 8/10 trechos rotulados, CNAE, interpretador e caso 7 ponta a ponta.

## Fontes

| Fonte | Rota | Observação |
| --- | --- | --- |
| CNPJ | `brasilapi.com.br/api/cnpj/v1/{cnpj}`, alternativa `minhareceita.org/{cnpj}` | Mesmo schema; QSA, contatos e endereço são descartados na ferramenta |
| Domínio `.br` | `rdap.registro.br/domain/{d}` | A rota Registro.br da BrasilAPI **não traz data de registro**, por isso o RDAP |
| Outros TLDs | `rdap.org/domain/{d}` | Cobertura varia por TLD; sem data vira `dado_ausente` |
| Web | SearXNG `/search?format=json` | `TavilyBusca` é só esqueleto atrás de `BuscaWeb` |

Consultas de busca são fixas: `"{nome} reclamações"`, `"{nome} golpe"` e `"{cnpj}"`.

## Privacidade e logs

- Só pessoa jurídica. Para empresário individual/MEI, a razão social (nome civil) é descartada.
- Os logs registram id da consulta, status por fonte e duração, **nunca o texto digitado**.
- Cache em disco (`~/.cache/checagem` ou `CHECAGEM_CACHE`): CNPJ e domínio por 24 h, busca por 1 h. Ele guarda só respostas públicas das APIs e expira sozinho. Apague a pasta para limpar.
- Chaves só em variáveis de ambiente (`.env` está no `.gitignore`).

## Diferenças em relação à spec

- `Consulta.produto` foi adicionado (necessário para `cnae_incompativel`).
- Lacunas extras com id próprio: `nao_informado`, `dado_ausente`, `cnae_incerto`, `reclamacoes_incertas`, `reclamacao_isolada`.
- O classificador de trechos tem o rótulo `mencao` (menção sem reclamação), para distinguir "sem menções" de "menções neutras".
- O redator devolve saída estruturada; o Markdown e o aviso são montados pelo código.
