# Registro de métricas

Nunca otimizar antes de medir a versão simples. Preencher "Antes" na versão ingênua e "Depois" após a melhoria.

| Nível | Métrica | Antes (versão simples) | Depois | Fase |
|---|---|---|---|---|
| Negócio | Custo anual de energia do consumidor-exemplo (backtest) | estratégia ingênua: R$ __ | estratégia otimizada: R$ __ | 6 |
| Negócio | Economia | — | R$ __ / __% | 6 |
| Negócio | Exposição ao PLD (MWh descobertos ou sobrando) | __ | __ | 6 |
| Ciência | MAPE mensal da previsão de carga (12 meses à frente, rolling origin) | baseline: __% | modelo: __% | 5 |
| Engenharia | Dados lidos por consulta típica | 0,037 GB (37,3 MB processados; 37,7 MB faturados), ONS, raw sem partição | __ GB | 1 → 2 |
| Engenharia | Tempo de carga diária | full: 4,6 min (só ONS; CCEE e INMET entram nas tarefas 1.7 e 1.8) | incremental: __ min | 1 → 4 |
| Engenharia | Tempo do backfill completo (2021–hoje) | — | __ min | 4 |
| Engenharia | Problemas de dados capturados pelos testes | — | __ registros (tipos: __) | 3 |
| Engenharia | Idempotência | — | 2 execuções → mesma contagem: sim/não | 4 |

---

## Detalhe das medições da Sprint 1 (o "antes")

### ONS, curva de carga horária: carga full ingênua (tarefa 1.6)

Medido em 02/10/2026, rodando `uv run python -m ingestion.ons` na máquina local (WSL2), sem
paralelismo: um arquivo por vez, um job de carga do BigQuery por arquivo, tabela sem partição.

| Medida | Valor |
|---|---|
| Arquivos | 27 (anos 2000 a 2026) |
| Volume baixado | **40,9 MB** |
| Linhas nos CSVs / carregadas no raw | 937.816 / 937.816 (iguais) |
| Tempo total da carga | **275,5 s (4,6 min)** |
| Download | 46,3 s (~1,7 s por arquivo) |
| Gravação no GCS (bronze) | 40,6 s (~1,5 s por arquivo) |
| Carga no BigQuery | 188,6 s (~7,0 s por arquivo, 68% do tempo) |
| Valores vazios no raw | 259 NULL e 0 strings vazias (batem com os CSVs) |

**Consulta típica** ("carga média por hora do SE em 2024"), tabela `raw.ons_curva_carga` sem
partição, colunas STRING, cache desligado:

| Medida | Valor |
|---|---|
| Estimativa do dry-run | 37.316.177 bytes |
| Bytes processados | **37.316.177 (37,3 MB)** |
| Bytes faturados | 37.748.736 (37,7 MB, arredondado pelo BigQuery) |
| Tabela inteira lida? | sim: a consulta filtra o SE e o ano de 2024, mas sem partição lê as colunas citadas de todas as linhas (2000 a 2026) |

**Leituras para a comparação com as sprints seguintes**
- O gargalo da carga não é o download, é o BigQuery: 27 jobs de carga com ~7 s de sobrecarga
  cada. Esse é o custo da "carga por arquivo" e de refazer tudo a cada execução; o incremental
  (Sprint 4) só carrega o que mudou.
- Os 37,3 MB processados são o "antes" da Sprint 2. A Sprint 2 mede três pontos (raw STRING,
  tipada sem partição, particionada e clusterizada) para separar o efeito de cada decisão (ver
  `decisoes.md`). Note que a consulta lê **a tabela toda de 2000 a 2026** para responder sobre
  um ano: com partição por data, deve ler algo próximo de 1/27 disso.
- O arquivo de 2026 é um retrato do dia da carga (26.208 linhas, até 01/10): a próxima carga
  full o regrava inteiro.

