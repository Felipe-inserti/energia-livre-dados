# Registro de métricas

Nunca otimizar antes de medir a versão simples. Preencher "Antes" na versão ingênua e "Depois" após a melhoria.

| Nível | Métrica | Antes (versão simples) | Depois | Fase |
|---|---|---|---|---|
| Negócio | Custo anual de energia do consumidor-exemplo (backtest) | estratégia ingênua: R$ __ | estratégia otimizada: R$ __ | 6 |
| Negócio | Economia | — | R$ __ / __% | 6 |
| Negócio | Exposição ao PLD (MWh descobertos ou sobrando) | __ | __ | 6 |
| Ciência | MAPE mensal da previsão de carga (12 meses à frente, rolling origin) | baseline: __% | modelo: __% | 5 |
| Engenharia | Dados lidos por consulta típica | 0,037 GB (37,3 MB processados; 37,7 MB faturados), ONS, raw sem partição | __ GB | 1 → 2 |
| Engenharia | Tempo de carga diária | full: 5,8 min (ONS 4,6 min + CCEE 1,2 min; o INMET entra na tarefa 1.8) | incremental: __ min | 1 → 4 |
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

### CCEE, PLD e consumo por ramo: carga full ingênua (tarefa 1.7)

Medido em 02/10/2026, rodando `uv run python -m ingestion.ccee` na máquina local (WSL2), sem
paralelismo e **sem download**: os arquivos foram baixados à mão (o portal bloqueia scripts) e
são lidos de `data/manual/ccee/`. Três tabelas no raw, uma carga por arquivo, sem partição.

| Medida | Valor |
|---|---|
| Arquivos | 10 (6 de PLD horário, 1 de PLD semanal, 3 de consumo por ramo) |
| Volume dos arquivos carregados | **7,4 MB** (leitura local, sem download) |
| Linhas nos CSVs / carregadas no raw | 214.443 / 214.443 (iguais) |
| Tempo total da carga | **74,9 s (1,2 min)** |
| Leitura da pasta | 0,0 s |
| Gravação no GCS (bronze) | 10,1 s (~1,0 s por arquivo) |
| Carga no BigQuery | 64,7 s (~6,5 s por arquivo, 86% do tempo) |
| Valores vazios no raw | 0 NULL e 0 strings vazias nas 3 tabelas (batem com os CSVs) |

Linhas por arquivo (todas validadas contra os CSVs):

| Arquivo | Linhas | MB |
|---|---|---|
| `pld_horario_2021.csv` | 35.040 | 1,31 |
| `pld_horario_2022.csv` | 35.040 | 1,25 |
| `pld_horario_2023.csv` | 35.040 | 1,28 |
| `pld_horario_2024.csv` | 35.136 | 1,29 |
| `pld_horario_2025.csv` | 35.040 | 1,02 |
| `pld_horario_2026.csv` (até 02/10/2026) | 26.400 | 0,78 |
| `pld_historico_semanal_2001_2020.csv` | 12.312 | 0,45 |
| `consumo_ramo_atividade_2024.csv` | 135 | 0,01 |
| `consumo_ramo_atividade_2025.csv` | 180 | 0,02 |
| `consumo_ramo_atividade_2026.csv` | 120 | 0,01 |

**Consulta típica** ("PLD médio por hora do SUDESTE em 2024"), `raw.ccee_pld_horario` sem
partição, colunas STRING, cache desligado:

| Medida | Valor |
|---|---|
| Estimativa do dry-run | 5.397.600 bytes |
| Bytes processados | **5.397.600 (5,4 MB)** |
| Bytes faturados | 10.485.760 (10,5 MB): **o mínimo de 10 MiB por consulta do BigQuery** |

**Leituras para a comparação com as sprints seguintes**
- **O faturado está no piso, então ele não serve para comparar.** A tabela horária é pequena
  (~200 mil linhas, 5,4 MB lidos), abaixo do mínimo de 10 MiB cobrado por consulta. Na
  Sprint 2, particionar vai reduzir os bytes **processados**, mas o **faturado** continuará em
  10,5 MB. Para esta tabela, compare os bytes processados. A consulta do ONS (37,3 MB) não tem
  esse problema e é a que vale para o "antes e depois" em bytes faturados.
- **O tempo de carga depende do número de arquivos, não do volume.** Cada job de carga do
  BigQuery custa cerca de 6,5 a 7 s de sobrecarga (CCEE: 6,5 s por arquivo; ONS: 7,0 s). Os
  três arquivos de consumo, de 10 a 20 KB cada, gastaram o mesmo tempo que os de 1 MB. A CCEE
  levou 86% do tempo no BigQuery com apenas 7,4 MB, enquanto o ONS levou 68% com 40,9 MB.
  Carregar vários arquivos num único job (por exemplo, um curinga `gs://.../*.csv` a partir
  do bronze) eliminaria quase toda essa sobrecarga; fica como candidato para a Sprint 4.
- **Dados vindos de download manual:** o arquivo de 2026 é um retrato de 02/10/2026 (26.400
  linhas, 275 dias de 96 linhas) e envelhece todo dia; a carga não registra a data do download
  (só o log, com a data de modificação do arquivo).
