# Resultados dos baselines (Sprint 4, Parte B)

Gerados por `uv run --env-file .env python -m ml.avaliar --periodo <periodo>` (só leitura no BigQuery). SE/CO.
Números lidos e comentados em `docs/metricas.md`; decisões em `docs/decisoes.md`.

| Período | Alvos | Uso |
|---|---|---|
| `desenvolvimento` | 2012-01 a 2019-12 | escolha de modelos |
| `estresse_2020` | 2020-01 a 2020-12 | pandemia, à parte |
| `teste_final` | 2021-01 a 2025-12 | **usado uma vez** (07/10/2026); não rodar de novo |

Cada período tem 4 arquivos:
- `baseline_<periodo>_por_horizonte.csv`: MAPE, MAE (MWmed) e viés (MWmed e %) por horizonte (1 a 12) e `geral`, nos recortes
  `todas_as_origens` e `origem_dezembro` (a decisão do contrato).
- `baseline_<periodo>_erro_anual.csv`: erro do ano inteiro (média dos 12 meses previstos contra a dos reais), origem de dezembro.
- `baseline_<periodo>_previsoes.csv`: cada previsão (origem, horizonte, alvo, previsto, real, erro). Insumo dos cenários de consumo da Sprint 5.
- `baseline_<periodo>.meta.json`: data de geração (UTC), commit de referência, parâmetros, séries usadas e bytes lidos.

Séries: `original` (curva do ONS como veio), `ajustada` (levada a uma definição só; existe a partir de 2018) e
`original_nos_pares_da_ajustada` (a original restrita aos mesmos pares da ajustada, para comparar sem trocar os meses).

Convenção: erro = previsto − real; **viés positivo = previu acima do real**.

**Proveniência do teste final:** `baseline_teste_final_*` foi **gerado no commit `4bc1a17`** (o commit provisório "wip: Sprint 4B até o checkpoint B",
já no GitHub), em 2026-10-07T22:19:47Z, com a árvore limpa antes da execução. É o commit que o `.meta.json` dele cita e **não foi regenerado**: o teste
final é usado uma vez. O `arvore_com_mudancas: true` desse arquivo é um artefato (o `git status` rodava depois de gravar os próprios CSVs; o código foi
corrigido depois). Para conferir que o código é o mesmo, compare os hashes de conteúdo de `docs/metricas.md` (seção 6) com `git rev-parse 4bc1a17:<arquivo>`.

**Desenvolvimento e estresse de 2020** foram regenerados depois, com a árvore limpa, no commit citado no `.meta.json` de cada um.
