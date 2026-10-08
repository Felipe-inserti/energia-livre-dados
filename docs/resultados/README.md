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

## Candidatos da Sprint 5 (Parte A)

`candidatos_<periodo>_<serie>_*`, gerados por `uv run --env-file .env python -m ml.avaliar_candidatos --periodo <periodo>`. Período `desenvolvimento`,
série `original` (o teste final usará `reconstruida`, de `fct_carga_mensal.carga_ajustada_reconstruida_mwmed`):
- `_resumo.csv`: uma linha por candidato (MAPE, MAE, viés, MAPE em h=1 e h=12, diferença contra o ingênuo e o erro-padrão dela, anos melhores, erro anual de dezembro, pior ano, tempo).
- `_por_horizonte.csv`, `_erro_anual.csv`: como nos baselines, com a coluna `candidato`.
- `_previsoes.csv`: cada previsão (origem, horizonte, alvo, previsto, real, erro). **É o insumo dos cenários de consumo e dos intervalos**: o erro por origem e horizonte, com todos os 12 horizontes de cada origem juntos (preserva a correlação entre meses).
- `.meta.json`: data, commit, hashes de conteúdo do código e dos seeds, critério, escolha e parâmetros. `arvore_com_mudancas: true` enquanto o código não estiver commitado; os hashes valem como conferência.
O teste final **não** foi rodado para os candidatos.

### Teste final dos candidatos e análise de erros (Sprint 5, Checkpoint B)
`candidatos_teste_final_{reconstruida,original}_*`: **rodado uma vez por série**, só a média ETS+SARIMA+regressão e o ingênuo. A regra pré-registrada (a Sprint 6 usa essa média independentemente do resultado) e a ressalva (vitória no desenvolvimento de 0,255 pp, menor que 1 EP) estão no `.meta.json`. Na série reconstruída o modelo tem 654 pares (janela de 72 meses desde dez/2020); `sazonal_ingenuo_mesmos_pares` é o ingênuo restrito a eles. **Não rodar de novo.**
`analise_teste_final_*` (por mês-calendário, ano, horizonte, temperatura, out/2021, intervalos e cobertura), `quantis_erro_desenvolvimento_*` e `erros_por_origem_*` vêm de `python -m ml.analise_erros`, que só lê estes arquivos e a temperatura mensal.

### Em produção (Checkpoint C)
`ml/previsao.py` grava no BigQuery (`marts.fct_previsao_carga` e `marts.fct_erro_previsao_carga`) a previsão de 12 meses de cada origem nova e os erros por origem e horizonte (os 1.152 do desenvolvimento, os 654 do teste final e, com o tempo, os realizados em produção). Os arquivos `erros_por_origem_*` e `candidatos_*_previsoes.csv` daqui são a fonte do backtest dessa tabela. A calibração dos intervalos está em `ml/intervalos.py` (produção: todos os erros; backtest da Sprint 6: crescente no tempo, só alvos `<= t`).

**Hashes do teste final.** Os `hashes_de_conteudo` do `.meta.json` do teste final foram tirados no momento da execução. Depois dela, `ml/modelos.py` (o `import lightgbm` passou para dentro da função, para a imagem do Airflow não precisar dele) e `ml/registro.py` (funções de produção acrescentadas) mudaram, sem alterar nenhuma conta do modelo. A prova: o desenvolvimento foi regenerado do zero depois dessas mudanças e as previsões saíram idênticas byte a byte (`cmp`). O teste final **não** foi rodado de novo.

**Arredondamento da série (08/10/2026).** O `fct_carga_mensal` passou a sair com 3 casas decimais (1 kW) porque o `AVG` do BigQuery não é reproduzível bit a bit. O desenvolvimento (`candidatos_desenvolvimento_original_*`) e as análises derivadas dele (`quantis_erro_desenvolvimento_*`, `erros_por_origem_desenvolvimento_original.csv` e as coberturas) foram regenerados com a série arredondada; as métricas não mudaram na precisão reportada (2,66%, viés +0,45%). Os arquivos do **teste final** não foram regenerados: vieram do mart anterior ao arredondamento, e o modelo de produção difere do avaliado apenas por esse arredondamento de 1 kW na entrada.

