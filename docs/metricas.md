# Registro de métricas

Nunca otimizar antes de medir a versão simples. Preencher "Antes" na versão ingênua e "Depois" após a melhoria.

| Nível | Métrica | Antes (versão simples) | Depois | Fase |
|---|---|---|---|---|
| Negócio | Custo anual de energia do consumidor-exemplo (backtest) | estratégia ingênua: R$ __ | estratégia otimizada: R$ __ | 6 |
| Negócio | Economia | — | R$ __ / __% | 6 |
| Negócio | Exposição ao PLD (MWh descobertos ou sobrando) | __ | __ | 6 |
| Ciência | MAPE mensal da previsão de carga (12 meses à frente, rolling origin) | baseline (sazonal ingênuo): **2,92%** no desenvolvimento (2012–2019, original); 4,30% no teste final (2021–2025, ajustada) | desenvolvimento: **2,66%** (média ETS+SARIMA+regressão), vitória marginal sobre o ingênuo (+0,26 pp, EP 0,27 pp); teste final (ajustada): **3,11%** contra 4,17% do ingênuo nos mesmos pares (4,30% em todos os pares); origem de dezembro 2,53% contra 4,30% | 5 |
| Engenharia | Dados lidos por consulta típica (**bytes processados**) | 0,037 GB (ONS, raw STRING sem partição: 37,3 MB processados; 37,7 MB faturados) | tipado sem partição: 0,018 GB (18,3 MB); **fato particionado por mês e clusterizado: 0,0007 GB (0,74 MB processados, −98,0% contra o raw)**. O faturado cai para 10,5 MB, o piso de 10 MiB do BigQuery, então a métrica de comparação são os bytes processados | 1 → 2 |
| Engenharia | Tempo de carga diária | full: **9,3 min** (ONS 4,9 + CCEE 1,2 + INMET 3,1 + feriados 0,2; sem o tempo do download manual) | incremental (DAG diária, ONS): **1,6 min** (1 min 33 s; só a ingestão do ONS leva 20 s, contra 4,9 min da carga full do ONS). Seção "Sprint 4, Parte A" | 1 → 4 |
| Engenharia | Tempo do backfill completo (2021–hoje) | — | **~125 s (2,1 min)**: ingestão 74 s + dbt 51 s, de 2021-01 a 2026-10 (70 partições). A carga full de 2000 a hoje leva 94 s | 4 |
| Engenharia | Problemas de dados capturados pelos testes | — | **10 registros em 173 testes** (10 estações do INMET abaixo de 95% de horas válidas em 2026, `warn`), 0 `error`; mais 240 horas nulas e 20 horas inexistentes, já conhecidas e cobertas por exceções. Detalhe na seção "Sprint 3, Parte A" | 3 |
| Engenharia | MB gravados no GCS por execução da ingestão do ONS | full: **40,9 MB** (os 27 arquivos, toda vez) | por hash: **2,45 MB** na execução com revisão (−94,0%) e **0,00 MB** na seguinte (−100%) | 3 |
| Engenharia | Revisões retroativas do ONS | não medidas (o bronze era sobrescrito) | 1 de 27 arquivos mudou: 480 valores revisados (1,8% das linhas do arquivo), diferença máxima de 0,517%. Na Sprint 4: a revisão depende da idade do dado (nada de real passou de 27 dias; as "5 linhas de agosto" eram ruído de 7e-12), e os 93,8% de 06/10 eram valor provisório do NE substituído | 3 → 4 |
| Engenharia | Freshness do ONS | sem freshness | antes da carga `ERROR STALE` (120 h); depois, com os limites iniciais, `WARN` (48,8 h); com os limites calibrados (72 h e 120 h), `PASS` | 3 |
| Engenharia | Idempotência | — | **sim**: janela do dia duas vezes (ingestão + dbt) → 5.152 grupos (mês × submercado, 4 tabelas) iguais, 0 diferenças, sem tolerância; o backfill, idem | 4 |

---

## Detalhe das medições da Sprint 1 (o "antes")

### Resumo da carga full da Sprint 1 (as quatro fontes e os feriados)

Medido em 02/10/2026, na máquina local (WSL2), uma execução de cada extrator (ONS, CCEE, INMET e
feriados, nesta ordem), depois da refatoração do `ingestion/common/`. Tempo = download ou leitura +
GCS + BigQuery; não inclui a validação do raw nem a consulta típica, nem o tempo que a pessoa
gasta baixando à mão os arquivos da CCEE e do INMET.

| Fonte | Tabela no raw | Arquivos | Volume | Linhas | Jobs de carga | Tempo total | Tempo no BigQuery |
|---|---|---|---|---|---|---|---|
| ONS | `ons_curva_carga` | 27 (baixados) | 40,9 MB | 937.816 | 27 | 292,2 s (4,9 min) | 204,2 s |
| CCEE | `ccee_pld_horario`, `ccee_pld_semanal`, `ccee_consumo_ramo_atividade` | 10 (manuais) | 7,4 MB | 214.443 | 10 | 74,6 s (1,2 min) | 63,6 s |
| INMET | `inmet_estacoes_horario` | 6 ZIPs (manuais) | 535,9 MB | 1.837.272 | 12 | 183,2 s (3,1 min) | 138,9 s |
| Feriados | `feriados` | biblioteca `holidays` 0.105 | n/a | 285 | 1 | 9,5 s | 6,9 s |
| **Total** | **6 tabelas** | | **584,2 MB no bronze** | **2.989.816** | **50** | **559,5 s (9,3 min)** | **413,6 s (74%)** |

Três consultas típicas, uma por fonte, sem partição e com colunas STRING (o "antes" da Sprint 2):

| Consulta | Bytes processados | Bytes faturados |
|---|---|---|
| ONS: carga média por hora do SE em 2024 | **37,3 MB** | 37,7 MB |
| CCEE: PLD médio por hora do SUDESTE em 2024 | 5,4 MB | 10,5 MB (piso de 10 MiB) |
| INMET: temperatura média por hora (UTC) em SP em 2024 | 58,3 MB | 58,7 MB |

O raw tem 2,99 milhões de linhas em 6 tabelas, validadas arquivo a arquivo (e, no INMET, por ZIP
e estação) contra os CSVs de origem.

### Evidência para o incremental da Sprint 4: um job por arquivo contra blocos grandes

Os extratores carregam de duas formas, e as medições mostram que o custo depende do **número de
jobs**, não do volume:

| | ONS | CCEE | INMET |
|---|---|---|---|
| Como carrega | um job por arquivo | um job por arquivo | **blocos de ~43 MB** (12 jobs) |
| Linhas | 937.816 | 214.443 | **1.837.272** |
| Tempo total | 4,9 min | 1,2 min | **3,1 min** |
| Tempo no BigQuery | 204,2 s | 63,6 s | 138,9 s |
| Tempo no BigQuery por job | 7,6 s | 6,4 s | 11,6 s |
| Linhas por job (média) | 34,7 mil | 21,4 mil | 153 mil |
| Linhas por segundo de BigQuery | 4,6 mil | 3,4 mil | **13,2 mil** |

- **O INMET carregou o dobro de linhas do ONS em 37% menos tempo total** (1,84 milhão em 3,1
  min contra 0,94 milhão em 4,9 min), e a 2,9 vezes a velocidade no BigQuery (13,2 mil contra 4,6
  mil linhas por segundo), apesar de subir 13 vezes mais bytes ao GCS (536 MB contra 41 MB).
- **Modelo de custo por job:** ajustando os dados do ONS e do INMET, cada job custa cerca de
  **6,4 s fixos + 34 s por milhão de linhas**. A CCEE serve de checagem (jobs de 21 mil linhas:
  previsto 7,1 s, medido 6,4 s; os 3 arquivos de consumo, com 120 a 180 linhas, levaram de 5 a
  10 s cada, contando o GCS). É uma estimativa de duas execuções com variação de rede de cerca de 6% (o ONS levou
  275,5 s numa execução e 292,2 s na outra), então vale a ordem de grandeza, não o decimal.
- **O que isso diz para a Sprint 4:**
  1. A carga full tem 50 jobs, e ~6,4 s de cada um é custo fixo (320 s dos 414 s de BigQuery).
  2. Uma carga incremental de um dia (poucas centenas de linhas) custa o mesmo job fixo, cerca
     de 6 a 7 s por tabela, em vez de recarregar tudo: o ganho vem de não repetir os 50 jobs.
  3. Projeção (não medida): o ONS carregado em blocos de ~40 MB, como o INMET, seria cerca de 3
     jobs de ~17 s, perto de 50 s de BigQuery em vez de 204 s (-75%).
  4. Por isso o incremental da Sprint 4 deve combinar as duas coisas: buscar só o período novo e
     agrupar o que for carregar numa mesma execução.

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

### Validação da refatoração: ONS e CCEE reexecutados (02/10/2026, 15:05 UTC)

Depois de extrair a parte comum para `ingestion/common/` (`raw.py`, `manual.py`), o ONS e a CCEE
foram rodados de novo. Resultado contra a primeira execução:

| Medida | ONS, 1ª execução | ONS, reexecução | CCEE, 1ª | CCEE, reexecução |
|---|---|---|---|---|
| Linhas carregadas | 937.816 | 937.816 | 214.443 | 214.443 |
| Valores vazios no raw | 259 NULL | 259 NULL | 0 | 0 |
| Volume | 40,9 MB | 40,9 MB | 7,4 MB | 7,4 MB |
| Tempo total | 275,5 s | 292,2 s (+6%) | 74,9 s | 74,6 s |
| Bytes processados (consulta típica) | 37.316.177 | **37.316.108** | 5.397.600 | 5.397.600 |
| Bytes faturados | 37.748.736 | 37.748.736 | 10.485.760 | 10.485.760 |

**A refatoração não mudou nada.** Linhas, vazios, volume e faturado são idênticos; o tempo do ONS
variou 6% (rede) e o da CCEE, 0,4%. A única diferença está nos bytes processados do ONS (69
bytes, 0,0002%), e **não vem da refatoração**:
- Os bytes que a consulta lê são a soma de (tamanho do texto + 2) de `id_subsistema`,
  `din_instante` e do valor (NULL conta 0). Essa conta, feita nos CSVs, **reproduz exatamente** o
  número do BigQuery: com as cópias locais de 2000 a 2025 (da manhã) e o arquivo de 2026
  baixado agora, dá 37.316.108 bytes em 937.816 linhas, igual à reexecução.
- Os arquivos de 2024 e 2025 estão idênticos (hash) às cópias da manhã. Portanto o que mudou
  entre as 13:50 e as 15:06 (UTC) foi o arquivo do ano corrente (2026), com as mesmas 26.208
  linhas e valores de tamanho de texto diferente. É a primeira evidência medida das **revisões
  do ONS** (o portal avisa que os dados mudam depois de publicados): o arquivo vivo mudou em
  cerca de 75 minutos.
- Não dá para provar, porque o arquivo de 2026 das 13:50 não foi guardado: o bronze o
  sobrescreveu. É exatamente o custo da decisão de sobrescrever o bronze (ver `decisoes.md`) que
  a tarefa 3.4 vai resolver.

### INMET, estações automáticas: carga full ingênua (tarefa 1.8)

Medido em 02/10/2026 (15:16 UTC), `uv run python -m ingestion.inmet`, sem download (ZIPs lidos de
`data/manual/inmet/`), só as 37 estações do SE/CO selecionadas. Carga em **blocos de ~43 MB**
(12 jobs), com `raw.inmet_estacoes_horario` sem partição e colunas STRING.

| Medida | Valor |
|---|---|
| ZIPs | 6 (2021 a 2026), 37 estações cada |
| Volume dos ZIPs (bronze) | **535,9 MB** |
| Linhas nos CSVs / carregadas no raw | 1.837.272 / 1.837.272 (iguais) |
| Tempo total da carga | **183,2 s (3,1 min)** |
| Leitura e transformação | 9,6 s |
| Gravação no GCS (bronze) | 34,8 s (~15 MB/s) |
| Carga no BigQuery | 138,9 s (12 jobs, 11,6 s por job, 76% do tempo) |
| Valores vazios de temperatura no raw | 24.781 NULL e 0 strings vazias (1,35%; batem com os CSVs, 222 grupos ZIP x estação) |

Linhas por ZIP (todas validadas por estação): 2021, 2022, 2023 e 2025 com 324.120; 2024 com
325.008 (bissexto); 2026 com 215.784 (até 31/08).

**Consulta típica** ("temperatura média por hora (UTC) em SP em 2024"), tabela sem partição,
colunas STRING, cache desligado:

| Medida | Valor |
|---|---|
| Estimativa do dry-run | 58.259.163 bytes |
| Bytes processados | **58.259.163 (58,3 MB)** |
| Bytes faturados | 58.720.256 (58,7 MB) |

Os 58,3 MB ficam acima do piso de 10 MiB (diferente da CCEE), então o faturado é comparável com o
do mart da Sprint 2. A estimativa feita antes da carga (~60 MB) acertou.

### Feriados (tarefa 1.8)

`uv run python -m ingestion.feriados`: 285 linhas (feriados nacionais de 2000 a 2030, biblioteca
`holidays` 0.105), 1 job `TRUNCATE`, 9,5 s no total (6,9 s no BigQuery), validação de contagem,
datas únicas e ausência de nulos ok. Uma data com dois feriados numa linha só (2000-04-21).

---

## Sprint 2: staging (tarefa 2.2)

Medido em 02/10/2026 depois do primeiro `dbt run` dos 6 modelos de staging (tabelas, sem partição,
dataset `staging`).

### Tempo do `dbt run` e do `dbt test`

`dbt run`: **6 modelos em 12,22 s** (4 threads; PASS=6). O tempo total é praticamente o do maior
modelo (INMET), porque os modelos rodam em paralelo.

| Modelo | Linhas | Lido do raw | Tempo |
|---|---|---|---|
| `stg_feriados` | 285 | 11,2 KiB | 2,43 s |
| `stg_ccee__pld_semanal` | 12.312 | 1,2 MiB | 2,62 s |
| `stg_ccee__consumo_ramo_atividade` | 435 | 75,1 KiB | 2,65 s |
| `stg_ccee__pld_horario` | 201.696 | 19,0 MiB | 3,16 s |
| `stg_ons__curva_carga` | 937.796 | 98,1 MiB | 3,82 s |
| `stg_inmet__estacoes_horario` | 1.837.272 | 349,1 MiB | 4,68 s |
| **Total** | 2.989.596 | **467,5 MiB (490 MB)** | **12,22 s** |

Os 490 MB lidos são exatamente a estimativa do dry-run feito antes da execução e ficam sob o teto
de 1 GiB por job do perfil (o maior job leu 349 MiB). `dbt test`: **30 testes em 13,85 s**, todos
passam (27 do YAML e 3 singulares: `ons_descarta_so_horas_conhecidas`,
`ons_linhas_conferem_com_raw` e `ccee_pld_semanal_tres_linhas_por_semana`).

### O ponto intermediário: consulta típica no raw (STRING) contra o staging (tipado, sem partição)

Resultado idêntico nas três (24 linhas iguais): a conversão de fuso do staging está certa (ONS e CCEE
com hora local, INMET em UTC). Cache desligado.

| Consulta | Raw: processados | Staging: processados | Efeito da tipagem | Raw: faturados | Staging: faturados |
|---|---|---|---|---|---|
| ONS: carga média por hora do SE em 2024 | 37,3 MB | **18,3 MB** | **−51,0%** | 37,7 MB | 18,9 MB (−50,0%) |
| INMET: temperatura média por hora (UTC) em SP em 2024 | 58,3 MB | **36,5 MB** | **−37,3%** | 58,7 MB | 36,7 MB (−37,5%) |
| CCEE: PLD médio por hora do SUDESTE em 2024 | 5,4 MB | 6,4 MB | **+18,6%** | 10,5 MB | 10,5 MB (0%, piso) |

Esse é o efeito **só da tipagem** (nenhuma partição ainda). A tarefa 2.6 mede o terceiro ponto
(particionada e clusterizada); a diferença entre esse ponto e este é o efeito da partição.

**Por que a tipagem reduz o ONS e o INMET** (bytes por linha lida; no BigQuery um texto ocupa o
tamanho em bytes mais 2, e um NULL não ocupa nada):

| | Raw (texto) | Staging (tipado) |
|---|---|---|
| ONS | 39,8 B/linha: id 3,5 + data-hora como texto 21 + valor como texto ~15 | **19,5 B/linha**: id 3,5 + TIMESTAMP 8 + FLOAT64 8 |
| INMET | 31,7 B/linha: UF 4 + data 12 + hora 10 + temperatura ~5 | **19,9 B/linha**: UF 4 + TIMESTAMP 8 + FLOAT64 8 |

Os textos longos (data-hora de 19 caracteres, hora `0000 UTC`) viram um TIMESTAMP de 8 bytes, e
isso explica quase todo o ganho.

**Por que a CCEE aumentou 18,6%.** O staging da CCEE lê **31,75 bytes por linha**
(submercado 7,75 + instante TIMESTAMP 8 + preço NUMERIC 16), contra **26,76** no raw
(`mes_referencia` 8 + submercado 7,75 + `hora` ~3,6 + preço como texto ~7,4). O NUMERIC ocupa
16 bytes, contra ~7 bytes de um texto curto como `61.07`, e isso (+8,5 B) pesa mais que o ganho de
juntar mês e hora num TIMESTAMP (−3,6 B): saldo de +5,0 B por linha, ou +1,0 MB nas 201.696
linhas. Com FLOAT64 (8 bytes) o staging leria 23,75 B/linha (−11% contra o raw), então o NUMERIC custa
8 bytes por linha (1,6 MB nesta consulta). **É um trade-off aceito** (ver `decisoes.md`): a
precisão monetária do preço vale mais que 1,6 MB, e a diferença é invisível no faturado, que fica
no piso de 10 MiB (10,5 MB nos dois). Para essa tabela compare sempre os bytes processados.

### Armazenamento: raw contra staging

| Tabela | Raw | Staging |
|---|---|---|
| ONS | 102,8 MB | 83,8 MB (−19%) |
| CCEE PLD horário | 19,9 MB | 20,7 MB (+4%) |
| CCEE PLD semanal | 1,3 MB | 1,5 MB (+19%) |
| INMET | 366,0 MB | 398,4 MB (+9%) |
| **Total (6 tabelas)** | **490,1 MB** | **504,5 MB (+3%)** |

**A tipagem não encolhe tudo.** O ONS cai 19% (texto longo vira 8 bytes), mas o INMET **cresce
9%**: as 17 medidas são textos curtos (`0`, `19,5` ocupam de 3 a 6 bytes) que viram FLOAT64 de 8
bytes cada. O ganho da tipagem em bytes lidos depende de **quais colunas a consulta toca**: a
consulta típica do INMET lê só 3 colunas (a data-hora, que encolhe muito) e por isso cai 37%, mas
uma consulta que lesse todas as medidas leria mais que no raw. O armazenamento custa centavos; o
que importa para o custo é o que cada consulta lê.

### Previsão para a 2.6 (não medida)

A consulta típica do ONS particionada por data e clusterizada por subsistema leria só as linhas de
2024 do SE: ~8.784 linhas × 19,5 B, cerca de **0,2 MB processados** (projeção). Mas o **faturado só
pode cair até o piso de 10,5 MB** (−44% contra os 18,9 MB de hoje), então, como na CCEE, o ganho da
partição só aparecerá nos bytes **processados**. Registrar os dois na 2.6.

---

## Sprint 2: intermediários, fatos e partição (tarefas 2.4 a 2.6)

Medido em 02/10/2026 depois do `dbt run` dos 3 intermediários e dos 4 fatos (as 3 dimensões foram
refeitas junto), do `dbt test` e de `scripts/medir_consultas.py --isolar-cluster`.

> **A MÉTRICA DE COMPARAÇÃO SÃO OS BYTES PROCESSADOS, não os faturados.** O BigQuery fatura no mínimo
> 10 MiB (10.485.760 bytes) por consulta, e com este volume (18 a 366 MB por tabela) todas as consultas
> nos fatos terminam no piso de 10,5 MB: o faturado esconde o ganho da partição. O processado mostra o que
> a consulta de fato leu.

### Tempo do `dbt run` e do `dbt test`

`dbt run`: **10 modelos em 22,30 s** (PASS=10, 4 threads), lendo 455 MiB (477 MB) no total.

| Modelo | Linhas | Lido | Tempo |
|---|---|---|---|
| `dim_submercado` | 4 | 0 | 2,74 s |
| `dim_estacao` | 37 | 86,2 MiB | 3,54 s |
| `dim_tempo` | 271.752 | 7,9 KiB | 4,65 s |
| `fct_clima_horario` | 1.837.272 | 269,2 MiB | 4,57 s |
| `fct_pld_horario` | 201.696 | 7,6 MiB | 3,90 s |
| `fct_pld_semanal` | 12.312 | 574 KiB | 2,94 s |
| `fct_carga_horaria` | 937.796 | 24,6 MiB | 8,70 s |
| `int_clima_estado_horario` | 347.592 | 36,9 MiB | 3,85 s |
| `int_clima_submercado_horario` | 49.656 | 5,6 MiB | 2,25 s |
| `int_submercado_horario` | 937.988 | 24,5 MiB | 6,65 s |

O `dbt run` de staging (6 modelos) levou 12,22 s; este leva 22,30 s porque os 3 intermediários formam uma
cadeia (`dim_tempo` → `int_clima_estado_horario` → `int_clima_submercado_horario` →
`int_submercado_horario`, cerca de 17 s em sequência). O fato do ONS (8,70 s) levou mais que o staging dele
(3,82 s); não isolei a causa (a escrita particionada e clusterizada, ou a concorrência das 4 threads).
`dbt test`: **145 testes em 55,34 s**, todos passam (PASS=145, WARN=0).

### O "depois": a consulta típica nos três pontos (raw, tipado sem partição, fato particionado)

Resultado idêntico nos três pontos nas três fontes (24 linhas): a conversão de fuso, a tipagem e a
tradução do submercado para código estão certas.

| Consulta | Raw (STRING) | Tipado, sem partição | **Fato particionado e clusterizado** | Efeito total |
|---|---|---|---|---|
| **ONS**: carga média por hora do SE em 2024 | 37,32 MB | 18,29 MB (−51,0%) | **0,74 MB** (−95,9% contra o tipado) | **−98,0%** |
| **CCEE**: PLD médio por hora do SUDESTE em 2024 | 5,40 MB | 6,40 MB (+18,6%) | **1,05 MB** (−83,6% contra o tipado) | **−80,6%** |
| **INMET**: temperatura média por hora (UTC) em SP em 2024 | 58,26 MB | 36,55 MB (−37,3%) | **6,19 MB** (−83,1% contra o tipado) | **−89,4%** |

Bytes **processados**. Os mesmos pontos, nos **faturados**: ONS 37,7 → 18,9 → **10,5 MB**; CCEE 10,5 → 10,5 →
10,5 MB; INMET 58,7 → 36,7 → **10,5 MB**. No fato, todos estão no piso de 10 MiB; por isso o ganho real
(−98%, −81%, −89%) só aparece nos bytes processados. A previsão feita antes da execução (ONS ~0,74 MB, CCEE ~1,1
MB, INMET ~7 MB) acertou nas três.

Configuração real das tabelas (conferida no BigQuery, não só no que o dbt pediu):

| Fato | Partição | Cluster | Partições | Linhas |
|---|---|---|---|---|
| `fct_carga_horaria` | mensal em `instante_utc` | `codigo_submercado` | 322 | 937.796 |
| `fct_pld_horario` | mensal em `instante_utc` | `codigo_submercado` | 70 | 201.696 |
| `fct_clima_horario` | mensal em `instante_utc` | `uf`, `estacao_codigo` | 68 | 1.837.272 |

### Experimento: isolando o efeito da partição e o do cluster

Cópias temporárias do fato (sem nada, só partição mensal, só cluster), medidas com a mesma consulta e já apagadas.
Bytes processados:

| Fonte | Sem partição e sem cluster | Só partição | Só cluster | Partição e cluster (o fato) | Cluster sobre a partição |
|---|---|---|---|---|---|
| ONS | 18,29 MB | 0,74 MB (**−95,9%**) | 18,29 MB (+0,0%) | 0,74 MB (−95,9%) | +0,0% |
| CCEE | 5,55 MB | 1,05 MB (**−81,1%**) | 5,55 MB (+0,0%) | 1,05 MB (−81,1%) | +0,0% |
| INMET | 36,55 MB | 6,48 MB (−82,3%) | **5,93 MB (−83,8%)** | 6,19 MB (−83,1%) | **−4,4%** |

**O que o experimento mostra**
- **A partição é o que reduz os bytes** nas três fontes (−96%, −81%, −82%). O filtro de intervalo em
  `instante_utc` poda as partições mensais (o ONS lê 13 de 322; o INMET, 13 de 68).
- **No ONS e na CCEE o cluster não faz nada (+0,0%).** As tabelas são pequenas demais: a documentação do
  BigQuery diz que clusterizar tabelas ou partições pequenas dá melhora "geralmente desprezível", e com ~60 KB
  por partição mensal tudo cabe num bloco só, que é lido inteiro.
- **No INMET o cluster sozinho reduz 83,8%, porque o filtro é em `uf` (`uf = 'SP'`), que é muito seletivo**
  (4 das 37 estações) e a tabela inteira (36,5 MB, 68 meses) já é grande o bastante para ter vários blocos: o
  BigQuery lê só os blocos de SP, 16,2% da tabela. **Mas por cima da partição mensal o cluster reduz só 4,4%**
  (6,48 → 6,19 MB): cada partição mensal do INMET tem ~0,5 MB e cabe em um ou dois blocos, então não há bloco
  de outra UF para podar dentro dela. Se o cluster funcionasse dentro de cada partição, a consulta leria
  ~0,76 MB (13 de 68 meses × 4 de 37 estações); leu 6,19 MB. **Os dois efeitos se sobrepõem em vez de
  somar** (partição 82,3%, cluster 83,8%, os dois 83,1%): para o INMET, no nosso tamanho, o cluster sozinho
  rendeu até um pouco mais que a combinação (5,93 contra 6,19 MB).
- **A estimativa do dry-run diverge do processado em tabela clusterizada**, como a documentação avisa ("não se
  recebe uma estimativa de custo exata antes da execução porque o número de blocos lidos não é conhecido"):
  no INMET só com cluster, a estimativa foi 36,55 MB (a tabela inteira) e o processado, 5,93 MB; no fato
  (partição e cluster), 6,48 e 6,19 MB. Nas tabelas sem cluster (sem nada ou só partição) a estimativa é
  exatamente igual ao processado. Por isso o script mostra os dois lado a lado, e a medição vale o
  **processado** (depois de executar).
- **Conclusão prática:** com estes volumes, o que reduz bytes é a partição por mês; o cluster só ajuda quando o
  filtro é muito seletivo e a tabela é grande o suficiente (INMET sem partição) e se torna redundante por cima
  de uma partição mensal pequena. Mantive o cluster nos fatos porque não custa nada e passa a valer quando as
  tabelas crescerem (com partições de GBs), mas o ganho medido hoje vem só da partição.

### Dois efeitos laterais que a medição revelou

- **O fato da CCEE sem partição já é 13% menor que o staging** (5,55 contra 6,40 MB), só por trocar o nome do
  submercado pelo código do ONS (média de 7,75 contra 3,5 bytes por linha: −4,25 B × 201.696 linhas = −0,86 MB).
  É um ganho da harmonização da chave (a `dim_submercado`), não da partição, e reduz o custo extra do NUMERIC
  visto na 2.2: o fato sem partição lê 5,55 MB, quase o mesmo que o raw (5,40 MB, +2,8%), contra os 6,40 MB do
  staging (+18,6%).
- **O faturado só vai ao piso de 10,5 MB depois da partição**: o ONS cai de 18,9 para 10,5 MB (−44%) e o INMET de
  36,7 para 10,5 MB (−71%), mas a CCEE já estava no piso desde o raw, e o ONS não passa dali mesmo lendo 0,74 MB.


## Sprint 2: documentação e exploração (tarefas 2.7 e 2.8)

### Documentação do dbt (2.7)

| Medida | Antes | Depois |
|---|---|---|
| Colunas dos modelos com descrição | 45 de 141 (32%) | 141 de 141 |
| Colunas (modelos e fontes) conferidas contra o BigQuery | não medido | 200 de 200 (`scripts/verificar_docs.py`) |
| Blocos de documentação reutilizáveis | 0 | 14 (`dbt/models/_docs.md`) |

`dbt docs generate` só lê metadados: sem bytes processados. A conferência contra as colunas reais pegou 21
colunas das fontes (raw) que o YAML não declarava (as 17 medidas do INMET e as de consumo da CCEE), que a
contagem só dos modelos não mostrava.

### Notebook de exploração (2.8): custo das consultas (sem cache, `notebooks/01_exploracao.ipynb`)

| Consulta | Linhas devolvidas | MB processados |
|---|---|---|
| 1. carga mensal do SE | 321 | 22,6 |
| 2. perfil por hora do dia | 72 | 10,8 |
| 3. carga x temperatura (média diária) | 1.440 | 28,4 |
| 4. PLD horário do SE | 50.424 | 9,9 |
| 5. PLD médio anual | 104 | 10,3 |
| **Total** | 52.361 | **82,0** |

Todas abaixo do teto de 200 MiB por consulta. Estimado antes (dry-run): ~94 MB; medido: 82,0 MB. Em tabelas pequenas o faturado fica no
piso de 10 MiB por consulta, então o total faturado é maior que o processado.
Arquivos: o notebook sem saídas tem 23,7 KB (executado, com as imagens embutidas, tem 620 KB); as 5 figuras somam
~630 KB em `docs/figuras/` (a de dispersão tem 238 KB; limite por figura: 300 KB). O `lineage.png` tem 155 KB.

## Sprint 3, Parte A: qualidade de dados (tarefas 3.1 a 3.4)

Medido em 06/10/2026 (UTC), na máquina local, com os logs em `data/logs/` (`dbt_test_3.2.log`,
`resumo_testes_3.2.log`, `revisoes_3.4_comparacao.log`, `ons_3.4_carga1.log`, `ons_3.4_carga2.log`,
`freshness_3.3_antes.log`, `freshness_3.3_depois.log`).

### Testes do dbt (3.1 e 3.2)

| Medida | Antes (Sprint 2) | Depois |
|---|---|---|
| Testes do dbt | 145 | **173** (+28: 6 singulares novos, 5 do seed, 11 nas colunas de chave do raw e 6 das lacunas da 3.1) |
| Resultado do `dbt test` | — | **172 pass, 1 warn, 0 error** (61,3 s; os 30 testes de staging da Sprint 2 levavam 13,9 s) |
| `dbt run` (16 modelos) | — | 25,9 s, sem erro |
| Lacunas achadas pela auditoria da 3.1 | não medido | 4 (mais as sources sem teste), todas fechadas |

Por tipo (`scripts/resumir_testes.py`): `not_null` 81, `relationships` 24, `singular` 24, `accepted_values` 16,
`unique_combination_of_columns` 12, `equal_rowcount` 9, `unique` 7. Só o tipo `singular` teve registros
problemáticos.

**Registros problemáticos encontrados:**

| Teste | Severidade | Registros | O que são |
|---|---|---|---|
| `fct_clima_horario_completude_estacao_por_ano` | warn | **10** | estações do INMET com menos de 95% de horas válidas de temperatura em 2026: A037 (13,6%), A704 (72,5%), A554 (77,6%), A516 (81,6%), A502 (83,8%), A508 (90,1%), A539 (90,5%), A659 (90,6%), A570 (93,9%), A614 (94,7%); iguais às 10 de `fontes.md` |
| os outros 5 testes novos e os 167 antigos | error/warn | 0 | passaram |

**Leitura honesta:** os testes novos **não acharam dado corrompido** nos dados atuais; acharam exatamente
a degradação do INMET que a exploração já tinha documentado, e provaram que a regra funciona. Provas de que
o teste pega: com o teto do PLD de 2024 trocado de 1.470,57 para 1.400, 4 horas falharam (teste manual,
fora do `dbt test`). Os casos já conhecidos passam por exceção declarada: 240 horas de carga nula (3 dias
inteiros de 2013 a 2015) e 20 horas locais inexistentes descartadas no staging. Piso e teto do PLD: 0 violações
em 201.696 horas. Faixa da carga: 610 a 62.150 MWmed por subsistema (teto do teste: 100.000). Temperatura
observada: de −4,7 a 42,7 °C (faixa do teste: −10 a 46).

### Freshness (3.3)

| Fonte | Antes da carga do ONS | Depois, limites iniciais | Depois, limites calibrados |
|---|---|---|---|
| ONS (warn 72 h, error 120 h) | `ERROR STALE`, 120,4 h | `WARN`, 48,8 h (limites antigos: 48 h e 96 h) | `PASS`, 48,9 h |
| PLD horário (warn 7 dias) | `PASS`, 95 h | `PASS`, 95,8 h | `PASS` |
| INMET (warn 60 dias) | `PASS`, 866 h (36 dias) | `PASS` | `PASS` |
| Consumo por ramo (warn 75 dias) | `PASS`, 842 h (35 dias) | `PASS` | `PASS` |

O aviso do ONS com os limites iniciais ensinou que o atraso normal é de 2 dias, não de 1 (ver
`decisoes.md`, "Recalibração"). Custo da freshness: leituras de uma coluna por fonte, ~1,5 s cada.

### Bronze do ONS por hash e MB gravados no GCS (3.4)

Duas execuções seguidas de `ingestion.ons` (27 arquivos, 40,9 MB baixados; o raw continua em carga full):

| Medida | Antes (carga full, Sprint 1) | 1ª execução com hash | 2ª execução com hash |
|---|---|---|---|
| Arquivos gravados no GCS | 27 | 1 (o de 2026, 1,23 MB) | 0 |
| Pulados por hash igual | — | 26 | 27 |
| Versões antigas arquivadas | — | 1 (1,22 MB) | 0 |
| **MB gravados no GCS** | **40,9** | **2,45 (−94,0%)** | **0,00 (−100%)** |
| Tempo no GCS | 40,6 s | 9,8 s (−76%) | 5,3 s (−87%) |
| Tempo no BigQuery | 188,6 s | 187,4 s | 165,6 s |
| Tempo total | 275,5 s e 292,2 s (duas execuções) | 243,2 s | 217,5 s |
| Bytes processados (consulta típica) | 37,3 MB | 37,3 MB | 37,3 MB |

O ganho está na escrita no bronze, não no tempo total: o raw ainda recarrega os 40,9 MB em 27 jobs (cerca de
76% a 77% do tempo), e isso só muda na Sprint 4. A diferença de tempo total contra a Sprint 1 vem quase toda
do GCS (~31 s a menos na 1ª execução, ~35 s na 2ª), o resto é variação de rede. A consulta típica não mudou,
como esperado. A 2ª execução não gravou nada: a idempotência do bronze está provada com o ONS sem ter
publicado entre as duas.

### Revisões retroativas do ONS (3.4): primeira medição real

Comparação do bronze de 02/10 (carga das ~15:06 UTC) com o ONS baixado em 06/10 às ~02:35 UTC
(`scripts/comparar_revisoes_ons.py`, só leitura; a carga seguinte mediu o mesmo, linha a linha):

| Medida | Valor |
|---|---|
| Arquivos comparados | 27 |
| Idênticos (hash) | **26** (2000 a 2025) |
| Com revisão | **1** (2026: 1.216.589 para 1.229.830 bytes) |
| Linhas do arquivo antigo / novo | 26.208 / 26.496 |
| Linhas novas / removidas | +288 (dias 1 a 3 de outubro) / 0 |
| **Valores revisados** | **480** (1,8% das linhas do arquivo antigo) |
| Nulo virou valor / valor virou nulo / nome mudou | 0 / 0 / 0 |
| Por mês | setembro **475** (16,5% das 2.880 horas), agosto 5, outubro 0 |
| Por subsistema | N 247, NE 101, SE 90, S 42 |
| Diferença máxima | 281,6 MWmed = **0,517%** do valor antigo |
| Diferença absoluta média / líquida | 9,2 MWmed por linha revisada / −545,0 MWmed no total |

Conclusão: a revisão se concentra no **mês anterior** ao corrente, é pequena (< 1%) e só em valores
numéricos. É uma observação de 4 dias (decisão da janela do incremental em `decisoes.md`). A diferença de 69
bytes do dia 02/10 não é recuperável porque o bronze era sobrescrito.

## Sprint 3, Parte B: Airflow (tarefas 3.5 a 3.7)

Medido em 06/10/2026 (UTC), com os logs em `data/logs/` (`airflow_build_3.5.log`,
`airflow_execucao_completa.txt`, `airflow_falha_proposital.txt`, `airflow_bytes_3.6.log`,
`airflow_bytes_falha.log`). Duas execuções: a agendada `scheduled__2026-10-06T21:00:00+00:00` (sucesso) e a
`manual__2026-10-06T22:12:05.158514+00:00`, com `falha_proposital=true`.

### Infra (3.5)

| Medida | Valor |
|---|---|
| Build da imagem (`docker compose build`) | 2 min 32 s |
| Tamanho da imagem `energia-livre-airflow:3.3.2` | 1,1 GB |

### Execução agendada completa (3.6)

Todas as tasks em `success` ou `skipped` (sem arquivo novo nas fontes manuais).

| Task | Estado | Duração |
|---|---|---|
| `ccee_ha_arquivo_novo`, `inmet_ha_arquivo_novo` | success | ~4 s |
| `ccee_ingestao`, `inmet_ingestao`, `ccee_registrar_estado`, `inmet_registrar_estado` | skipped | 0 |
| `ons_ingestao` | success | 4 min 22 s |
| `freshness_ons` | success | 11 s |
| `dbt_run` | success | 37 s |
| `dbt_test` | success | 1 min 28 s (PASS=173, WARN=1, ERROR=0) |
| `freshness_manuais` (em paralelo ao `dbt_test`) | success | 8 s |
| `pipeline_ok` | success | ~1 s |
| **Total, do início ao `pipeline_ok`** | success | **6 min 40 s** |

O `warn` é `fct_clima_horario_completude_estacao_por_ano`, já conhecido (as 10 estações do INMET).

**Onde o tempo vai (`ons_ingestao`, carga de 250,4 s):**

| Etapa | Tempo | Parcela |
|---|---|---|
| Download dos 27 arquivos | 47,7 s | 19% |
| GCS | 9,1 s | 4% |
| BigQuery (27 jobs, raw recarregado inteiro) | **193,5 s** | **77%** |

### Bronze por hash dentro da DAG (3.4 em produção)

| Medida | Antes (carga full, Sprint 1) | Depois (DAG, bronze por hash) |
|---|---|---|
| Arquivos pulados por hash igual | — | 26 de 27 |
| **MB gravados no GCS** | **40,9** | **2,47 (−94%)** |
| Linhas recarregadas no raw do BigQuery | 938.296 | **938.296 (sem mudança)** |

O raw continua recarregando as 938.296 linhas inteiras: é o gargalo da DAG (77% da carga do ONS) e o
"antes" da Sprint 4.

### Falha proposital (3.7)

| Medida | Valor |
|---|---|
| `ons_ingestao` | 3 min 52 s |
| `dbt_test` | `failed`, sem retentativa (`try_number` 1) |
| `pipeline_ok` | `upstream_failed` |
| Alerta no Discord | 1 mensagem, com task, execução e link do log |
| **Do início da execução até a falha detectada** | **~5 min 47 s** |

Limitação do alerta: o texto do erro é só "Bash command failed", sem os nomes dos testes do dbt que
falharam (backlog no arquivo de sprints).

### Bytes no BigQuery por execução (`scripts.medir_bytes_bigquery`)

Janelas sem sobreposição: 21:57 a 22:05 UTC (completa) e 22:12 a 22:18 UTC (falha).

| Origem | Jobs | Processados | Faturados |
|---|---|---|---|
| dbt (`run` e `test`) | 194 | 1.557,9 MB | **2.965,4 MB** |
| outros (validação do raw) | 1 | 65,0 MB | 66,1 MB |
| **Total** | 195 | **1.622,9 MB** | **3.031,4 MB** |

A execução da falha deu exatamente os mesmos números, o que é esperado: o SQL e o tamanho das tabelas
são os mesmos, e o teste proposital devolve 0 linhas sem a variável.

**Leitura:** o faturado é quase 2× o processado (1,87×) por causa do **piso de 10 MiB por job**: 194 jobs ×
10 MiB ≈ 1,9 GB. Os testes dominam o custo faturado (ver `decisoes.md`, "Piso de faturamento").

| Projeção (não medida; 30 execuções × 3,03 GB) | Valor |
|---|---|
| Faturado por mês | ~90 GB |
| Parcela do 1 TB gratuito de consultas | ~9% |
| Custo | R$ 0 |

---

## Sprint 4, Parte A: ingestão incremental (tarefas 4.1 a 4.4)

Medido em 07/10/2026 (UTC), na produção, com o medidor de bytes **corrigido** (o job pai de um `SCRIPT` não
entra na soma e os filhos herdam a classificação do pai; ver `decisoes.md`, "`fct_carga_horaria` continua `table`").
O "antes" é o da Sprint 3 (execução agendada de 06/10/2026), conferido de novo no INFORMATION_SCHEMA com o medidor
corrigido: 195 jobs sem nenhum `SCRIPT`, o mesmo resultado. Os arquivos citados ficam em `data/logs/` (a pasta é
ignorada pelo git, então os números ficam registrados aqui).

### Antes × depois, com a origem de cada número

| Medida | Antes | Depois | Variação | Origem |
|---|---|---|---|---|
| DAG, do início ao fim (execução normal, com ingestão) | 6 min 40 s | **1 min 33 s** | -77% | antes: Sprint 3 (agendada de 06/10); depois: `passo8_normal_resumo.txt` |
| Task `ons_ingestao` | 4 min 22 s | **20 s** | -93% | idem |
| Linhas recarregadas no raw por dia | 938.296 | **6.336** (3 meses) | -99,3% | `passo6_7_ingestao_dia.log` |
| Load jobs do ONS por execução | 27 | **3** | -89% | idem |
| MB baixados por dia | 40,9 (27 arquivos) | **1,2** (1 arquivo) | -97% | idem |
| Conferência dos anos fechados (26 anos) | não existia | **2,4 s** por HEAD em paralelo (16,7 s em série) | n/a | `passo6_7_ingestao_dia.log` ("ETag: ... 2.4 s"); o 16,7 s é do terminal (o log antigo não imprimia o tempo) |
| Carga full do raw (2000 a hoje, 27 arquivos) | ~275 s (275,5 e 292,2 s; BigQuery 189 a 204 s) | **94 s** na produção (89,2 s na verificação, BigQuery 36,8 s) | -66% | `passo3_e_tempo.log`, `passo2_1_full.log`; antes: Sprint 1 (`metricas.md`, "ONS ... carga full ingênua") |
| Backfill de 6 meses por decorador, concorrência 1 e 8 | 45 s | **17 s** | -62% | `passo2_3_tempo_c1.log` e `c8.log` |
| Backfill de 2021-01 a 2026-10 (70 meses) | n/a | **~125 s**: ingestão 74 s (66,9 s de carga) + dbt 51 s | n/a | `passo6_7_resumo.log` |
| dbt, execução da DAG (36 jobs, com freshness) | 194 jobs, 1.557,9 MB processados, 2.965,4 MB faturados | **36 jobs, 284,8 MB, 504,4 MB** | -81% jobs, -82% proc., **-83% fat.** | `passo8_normal_bytes.log` |
| Total faturado por execução (dbt + validações da ingestão) | 3.031,4 MB | **525,3 MB** | -83% | idem |
| Projeção mensal (30 execuções, sem arquivo manual) | ~90,9 GB (9,1% do 1 TB gratuito) | **~15,8 GB (1,6%)** | -83% | ver "Custo mensal projetado" |
| Idempotência (a janela do dia 2 vezes) | n/a | **5.152 grupos iguais, 0 diferenças** | n/a | `passo6_7_comparar_dia1_dia2.log` |
| Testes (`pytest`) | 224 | ****444**** | n/a | `uv run pytest` |

### Execuções da DAG (passo 8)

| Execução | Estado | DAG | `ons_ingestao` | dbt (jobs, MB proc., MB fat.) | Total fat. |
|---|---|---|---|---|---|
| normal | success | 1 min 33 s | 20 s | 36, 284,8, 504,4 | 525,3 MB |
| backfill pela conf (2026-07 a 2026-08) | success | 1 min 15 s | 11 s | 36, 285,6, 504,4 | 514,9 MB |
| falha proposital | `dbt_test` failed (sem retentativa), `pipeline_ok` upstream_failed, alerta no Discord | 1 min 22 s | 18 s | 36, 284,8, 504,4 | 525,3 MB |

Por task (execução normal): `parametros_execucao` 4 s, `ons_ingestao` 20 s, `freshness_ons` 10 s, `dbt_run` 36 s, `dbt_test` 20 s
(27 testes; antes 1 min 28 s com 174), `freshness_manuais` 10 s. A medição "agendada" do `subir` foi descartada: era a execução de
06/10 da Sprint 3 comparada com ela mesma (+0%); o script foi corrigido.

### dbt por cenário (produção; `passo4b_resumo.log`, `passo6_7_resumo.log`)

| Cenário | Jobs | Processado | Faturado | Tempo |
|---|---|---|---|---|
| **antes** (06/10, `run` + `test` + freshness) | 194 | 1.557,9 MB | 2.965,4 MB | DAG 6 min 40 s |
| completa (`run` + `test` de tudo, sem freshness) | 192 | 1.348,6 MB | 2.753,6 MB | 92 s |
| dia comum (ONS), `run` + `test` (3 testes vieram do cache) | 32 | 183,6 MB | 375,4 MB | 45 s |
| dia comum com `dbt build` | 32 | 183,6 MB | 375,4 MB | 43 s |
| **dia comum real** (ingestão antes: o cache não vale), só o dbt | 32 | 240,7 MB | **440,4 MB** | 68 s e 65 s (com a ingestão) |
| dia + arquivo novo do INMET | 90 | 1.213,0 MB | 1.779,4 MB | 64 s |
| dia + arquivo novo da CCEE | 85 | 250,8 MB | 919,6 MB | 59 s |
| backfill 2021-01 a 2026-10 (dbt) | 32 | 298,7 MB | 469,8 MB | 51 s |

**De onde vem o ganho:** a execução completa foi de 2.965,4 para 2.753,6 MB (-7,1%), mas só -72,3 MB (-2,4%) são do incremental (o
`stg_ons`); -75,5 MB são cache de consultas (3 testes só do raw do ONS, que não mudava) e -64,0 MB são o escopo (o "antes" tinha 4 jobs
de freshness). O que reduziu o custo foi a **seleção por fonte**: dia comum de 375,4 MB (440,4 MB sem o cache; 504,4 MB com a freshness
da DAG), -83%. Os testes são o custo que sobra: 27 testes do dia = 351,3 MB faturados, 79,8% do dbt do dia, idênticos no dia e no
backfill (o backfill de 70 meses custa só +6,7% no dbt, e toda a diferença está nos modelos, +29,4 MB).

### dbt incremental × `table` por modelo (checkpoint 4, `passo4_bytes_corrigido.log`)

| Modelo | Materialização | Jobs | Processado | Faturado | Tempo do modelo |
|---|---|---|---|---|---|
| `stg_ons__curva_carga` | `table` | 1 | 102,9 MB | 103,8 MB | 8,0 s |
| `stg_ons__curva_carga` | incremental (janela de 3 meses) | 3 (CTAS tmp 10,49 + MERGE 20,97 + DROP) | 1,7 a 2,3 MB | **31,5 MB** (-69,7%) | 6,6 a 7,8 s |
| `fct_carga_horaria` | **`table`** (escolhida) | 1 | 25,8 MB | **26,2 MB** | 7,3 s |
| `fct_carga_horaria` | incremental (alternável por var) | 3 | 0,3 a 0,5 MB | 31,5 MB (+20,2%) | 7,2 a 8,1 s |

O medidor antigo mostrava "10,5 MB" para os dois incrementais (o MERGE, job filho, caía no balde "outros"); o total sempre estava
certo (31,5 MB). Provas de correção: `EXCEPT DISTINCT` 0 e 0 e 1.288 de 1.288 grupos (mês × submercado) iguais ao build full, nas
duas rodadas de cada modelo.

### Revisões do ONS por idade do dado (três versões do arquivo de 2026, 02/10 a 06/10)

| Idade | Horas que mudaram, 02/10 -> 06/10 (madrugada) | Maior diferença | Horas que mudaram, 06/10 (madrugada -> noite) | Maior diferença |
|---|---|---|---|---|
| 0 a 2 dias | 87,2% | 0,52% | 52,1% | **93,8%** (NE, valor provisório substituído) |
| 3 a 6 dias | 36,2% | 0,16% | 31,0% | 0,008% |
| 7 a 13 dias | 8,3% | 0,05% | 8,8% | 0,001% |
| 14 a 27 dias | 1,6% | 0,06% | 0% | 0 |
| 28 dias ou mais | 0 | ruído de 7e-12 | 0 | 0 |

### Custo mensal projetado (estimativa; a frequência dos arquivos manuais é premissa: foram baixados uma vez, em 02/10)

Dia comum medido pela DAG: 525,3 MB (dbt 504,4 + validações 20,9). Dia com INMET: +1.404,0 MB; com CCEE: +544,2 MB (diferenças dos cenários
acima contra os 375,4 MB do dia comum).

| Cenário | GB/mês | % do 1 TB gratuito |
|---|---|---|
| antes: 30 × 3.031,4 MB | 90,9 | 9,1% |
| 30 dias comuns, sem arquivo manual | **15,8** | 1,6% |
| + 1 arquivo do INMET e 1 da CCEE por mês | 17,7 | 1,8% |
| + 4 de cada por mês | 23,6 | 2,4% |

Nos quatro casos o custo continua R$ 0, dentro do teto de R$ 10/mês.

## Sprint 4, Parte B: série mensal, baseline e validação temporal (tarefas 4.5 e 4.6)

Medido em 07/10/2026 (UTC). Os resultados dos baselines estão em `docs/resultados/` (CSV e `.meta.json`, versionados); a
reconciliação do ajuste está em `data/logs/passo2_conferir.log` (a pasta é ignorada pelo git, então os números ficam aqui).
Duas medidas da seção 1 (o perfil horário de 28 dias e a diferença diária API − curva) vêm de consultas exploratórias que
não foram versionadas; o que o repositório reproduz é a reconciliação mensal (`scripts/conferir_carga_mensal.py`) e os
resultados dos baselines (`python -m ml.avaliar`).

### 1. O degrau da definição da carga (SE/CO e demais submercados)

**MMGD, 01/05/2023.** A documentação do ONS diz 29/04/2023; no dado a diferença entre a curva e a carga líquida da API é +22 MWmed em
29/04, −176 em 30/04 e **+867 em 01/05**. Duas medidas independentes do tamanho:

| Submercado | Salto da curva − líquida da API (média de 4 semanas antes e depois) | % da carga | Perfil horário (28 dias, menos 5 anos normais): média / madrugada / meio-dia, em pontos logarítmicos |
|---|---|---|---|
| SE/CO | −59 → +1.235 = **+1.294 MWmed** | 3,3% | +4,3 / −0,1 / **+12,0** |
| S | −128 → +609 = +737 | 6,3% | +6,9 / +1,1 / +19,2 |
| NE | +253 → +550 = +297 | 2,6% | +7,1 / +2,1 / +18,7 |
| N | +204 → +237 = +33 | 0,5% | +4,0 / +0,9 / +10,9 |

O salto está no meio-dia e não na madrugada: é a assinatura da geração solar, o que separa o degrau de crescimento real. A medida do perfil
horário superestima o N (+16% ao ano em 2023, crescimento real misturado); a da API não. **A MMGD continua crescendo depois do degrau**: a
média anual da MMGD da API no SE/CO é 157 MWmed em 2019 (desde 15/02), 322 (2020), 631 (2021), 1.128 (2022), 2.172 (2023), 2.966 (2024), 3.995 (2025) e
4.350 (2026, até 07/10). A diferença curva − líquida passa de 1.240 MWmed em mai/2023 para ~2.850 em nov/2023.

**Usinas não despachadas (tipo III), 01/03/2021.** A diferença carga líquida da API − curva do SE cai de ~1.490 MWmed em 28/02/2021 para ~300 a 400 a
partir de 03/03. É maior que o degrau da MMGD. Média por ano dos meses `medido` (2018-01 a 2021-02), em MWmed e % da carga:

| | 2018 | 2019 | 2020 |
|---|---|---|---|
| SE/CO | 2.351 (6,56%) | 2.370 (6,51%) | 2.293 (6,50%) |
| S | 282 (2,54%) | 271 (2,39%) | 295 (2,68%) |
| NE | 463 (4,48%) | 433 (4,09%) | 559 (5,38%) |
| N | 69 (1,31%) | 62 (1,12%) | 60 (1,11%) |

Antes de 2018 a API não tem dado. Pela Carga Mensal do ONS (que inclui o tipo III desde jan/2015), o vão no SE/CO é **estável em nível e sazonal**: 2.138
MWmed em 2015, 2.148 em 2016, 2.057 em 2017 (6,1%, 6,1% e 5,8% da curva) e 2.403 em 2018; vai de ~800 a 900 em janeiro a ~3.300 em junho. Começa de repente
em jan/2015 (919 contra 0 em dez/2014). A decisão sobre o histórico anterior a 2018 fica para a Sprint 5.

### 2. O ajuste (`fct_carga_mensal`, seed `ajuste_definicao_carga`)

| Item | Valor |
|---|---|
| Seed | 304 linhas (4 submercados × 76 meses, 2018-01 a 2024-04), consulta de 07/10/2026; 443.912 registros semi-horários baixados em 2 min 2 s |
| Mart | 1.288 linhas, 21,6 MiB; sem partição |
| Fator `r` (fração da MMGD da API que a curva traz, 12 meses após a quebra) | SE 0,868, S 0,806, NE 0,846, N 0,846; no SE varia de 0,69 (mai/23) a 0,99 (dez/23) |
| Ruído pós-incorporação (σ da diferença mensal em 2022; limiar = 3σ) | SE 127 (380), S 165 (495), NE 95 (285), N 60 (179) MWmed |
| Transição do tipo III | só o SE/CO: mar, abr e mai/2021 (+393, +769 e +741 MWmed); fim em jun/2021 |
| MMGD ajustada, média anual do SE/CO (com `r`) | 129 (2019, fev a dez), 280, 547, 978 e 1.667 (2023, jan a abr) MWmed |
| Diferença entre `r = 1` e `r` | +20, +43, +83, +149 e +255 MWmed (2019 a 2023) |

**Salto da variação anual na quebra** (pontos percentuais, mês da quebra menos o mês anterior; o ruído normal no SE/CO é mediana 2,1 e p90 6,3):

| | Quebra de 2023: original → ajustada | Quebra de 2021: original → ajustada |
|---|---|---|
| SE/CO | 7,5 → 3,6 | 7,3 → 3,8 |
| S | 5,5 → 0,4 | 5,7 → 2,6 |
| NE | 8,0 → 3,2 | 6,5 → 2,8 |
| N | 2,9 → −1,2 | 6,2 → 4,4 |

O ajuste reduz o salto à metade, não o zera. O de 2021 mistura o rebote da pandemia (base de mar/2020 baixa) e por isso é um critério ruim sozinho; a variação
anual do SE/CO no pico (abr–mai/2021) cai de 19,5% e 22,0% (original) para 13,1% e 13,0% (ajustada).

### 3. Cobertura, lacunas e mês incompleto

| Medida | Resultado |
|---|---|
| Falsos "meses incompletos" do primeiro teste | **81** (80 = os 20 fevereiros de 2000 a 2019 × 4 submercados, onde o dia de 25 horas do fim do horário de verão fazia o calendário contar 1 hora a mais que o ONS publica; 1 = N em 2015-04, 24 linhas ausentes) |
| Meses fechados com cobertura < 100% | 12 submercado-mês: 2013-12 (96,77%), 2014-02 (96,43%) e 2015-04 (96,67%), nos 4 submercados |
| Meses fechados abaixo do limiar de 95% | **0** (com 97% seriam 12) |
| Mês incompleto | 4 (o corrente, out/2026, com 120 de 744 horas = 16,1%) |
| `mes_utilizavel` | 1.284 de 1.288 |
| Média nos meses com lacuna | igual à soma/horas válidas em todas as 1.288 linhas (diferença máxima 1,2e-10 MWmed); dividir pelas horas esperadas daria −3,2% em 2013-12 e −3,3% em 2015-04 |

Viés da média mensal do SE/CO ao retirar dias seguidos de um mês (todos os meses de 2000 a 2026):

| Dias faltando | Mediana | p99 | Máximo |
|---|---|---|---|
| 1 | 0,18% | 0,63% | 0,89% |
| 2 | 0,35% | 1,07% | 1,68% |
| 3 | 0,45% | 1,43% | 2,18% |

### 4. Custo e testes

| Medida | Resultado |
|---|---|
| `passo2_carga_mensal.sh` completo (seed + mart + 37 testes + reconciliação) | dbt: 39 jobs, 41,4 MB processados e 450,9 MB faturados; total com as consultas de apoio 524,3 MB faturados |
| Testes do dbt | 37 de 37 passam (22 do mart, 15 do seed); o de aviso `fct_carga_mensal_lacunas_so_as_conhecidas` sem linhas |
| Testes do projeto no dbt | 211 no total, 149 em alguma seleção por fonte, **62 fora** (47 antes; +15 do seed); os 22 do mart entram na seleção do ONS |
| Cada execução de `ml.avaliar` | 2 consultas, ~30 KB processados, 20 MiB faturados (piso de 10 MiB por consulta) |
| pytest | 508 testes |

### 5. Baselines no desenvolvimento (alvos 2012 a 2019, SE/CO)

Origem móvel com janela crescente (desde 2000), horizontes de 1 a 12, só `mes_utilizavel`. Erro = previsto − real: viés positivo é previsão acima do real. Série original,
todas as origens (96 alvos por horizonte):

| h | Ingênuo MAPE % | MAE | Viés MWmed | Viés % | Crescimento MAPE % | MAE | Viés MWmed | Viés % |
|---|---|---|---|---|---|---|---|---|
| 1 | 2,92 | 1.063 | −330 | −0,83 | 3,04 | 1.099 | +71 | +0,28 |
| 2 | 2,92 | 1.063 | −330 | −0,83 | 3,17 | 1.147 | +78 | +0,30 |
| 3 | 2,92 | 1.063 | −330 | −0,83 | 3,20 | 1.155 | +81 | +0,31 |
| 4 | 2,92 | 1.063 | −330 | −0,83 | 3,23 | 1.163 | +84 | +0,32 |
| 5 | 2,92 | 1.063 | −330 | −0,83 | 3,35 | 1.203 | +89 | +0,34 |
| 6 | 2,92 | 1.063 | −330 | −0,83 | 3,41 | 1.225 | +94 | +0,36 |
| 7 | 2,92 | 1.063 | −330 | −0,83 | 3,41 | 1.224 | +99 | +0,37 |
| 8 | 2,92 | 1.063 | −330 | −0,83 | 3,43 | 1.235 | +106 | +0,39 |
| 9 | 2,92 | 1.063 | −330 | −0,83 | 3,52 | 1.270 | +117 | +0,43 |
| 10 | 2,92 | 1.063 | −330 | −0,83 | 3,62 | 1.307 | +128 | +0,46 |
| 11 | 2,92 | 1.063 | −330 | −0,83 | 3,63 | 1.310 | +139 | +0,49 |
| 12 | 2,92 | 1.063 | −330 | −0,83 | 3,61 | 1.302 | +155 | +0,53 |
| **geral** | 2,92 | 1.063 | −330 | −0,83 | 3,39 | 1.220 | +103 | +0,38 |

O sazonal ingênuo tem o **mesmo erro em todos os horizontes** (a previsão de um alvo é o mesmo mês do ano anterior, qualquer que seja a origem); o de crescimento piora com o
horizonte (3,04% em h = 1 a 3,61% em h = 12) e fica acima do ingênuo em todos. Em compensação o viés dele é quase zero (+0,38%), e o do ingênuo é −0,83%.

Todas as séries (n = pares previsão-real):

| Série | Baseline | n | MAPE % | MAE MWmed | Viés MWmed | Viés % |
|---|---|---|---|---|---|---|
| original | sazonal_ingenuo | 1152 | 2,92 | 1.063 | −330 | −0,83 |
| original | sazonal_crescimento | 1152 | 3,39 | 1.220 | +103 | +0,38 |
| ajustada | sazonal_ingenuo | 144 | 3,05 | 1.243 | −806 | −1,94 |
| original_nos_pares_da_ajustada | sazonal_ingenuo | 144 | 3,06 | 1.175 | −668 | −1,68 |

A ajustada só existe a partir de 2018, então só há alvos em 2019 (12 alvos) e só o ingênuo (o de crescimento pede 24 meses de série ajustada). Dentro de 2019 as duas séries são
consistentes entre si e a diferença é pequena (3,05% contra 3,06%).

Origem em dezembro (a decisão do contrato; 8 anos × 12 horizontes na original):

| Série | Baseline | n | MAPE % | MAE MWmed | Viés MWmed | Viés % |
|---|---|---|---|---|---|---|
| original | sazonal_ingenuo | 96 | 2,92 | 1.063 | −330 | −0,83 |
| original | sazonal_crescimento | 96 | 3,85 | 1.386 | +95 | +0,36 |
| ajustada | sazonal_ingenuo | 12 | 3,05 | 1.243 | −806 | −1,94 |
| original_nos_pares_da_ajustada | sazonal_ingenuo | 12 | 3,06 | 1.175 | −668 | −1,68 |

Erro do ano inteiro (média dos 12 meses previstos contra a média dos 12 reais, origem em dezembro), em % e em MWmed:

| Série / baseline | 2012 | 2013 | 2014 | 2015 | 2016 | 2017 | 2018 | 2019 | Erro absoluto médio |
|---|---|---|---|---|---|---|---|---|---|
| original / sazonal_ingenuo | −2,41% (−854) | +2,18% (+753) | −4,55% (−1.652) | +0,95% (+341) | +0,90% (+319) | −1,42% (−513) | −1,00% (−364) | −1,80% (−668) | 1,90% |
| original / sazonal_crescimento | +1,24% (+440) | +4,70% (+1.628) | −6,58% (−2.389) | +5,76% (+2.071) | −0,05% (−18) | −2,29% (−829) | +0,43% (+156) | −0,81% (−301) | 2,73% |
| ajustada / sazonal_ingenuo | n/d | n/d | n/d | n/d | n/d | n/d | n/d | −2,03% (−806) | 2,03% |

**Estresse de 2020** (pandemia; 12 alvos, à parte, fora da escolha de modelos):

| Série | Baseline | n | MAPE % | MAE MWmed | Viés MWmed | Viés % |
|---|---|---|---|---|---|---|
| original | sazonal_ingenuo | 144 | 5,32 | 1.856 | +851 | +2,70 |
| original | sazonal_crescimento | 144 | 6,87 | 2.422 | +1.073 | +3,34 |
| ajustada | sazonal_ingenuo | 144 | 4,49 | 1.686 | +768 | +2,23 |
| ajustada | sazonal_crescimento | 78 | 4,69 | 1.799 | −124 | −0,04 |
| original_nos_pares_da_ajustada | sazonal_ingenuo | 144 | 5,32 | 1.856 | +851 | +2,70 |
| original_nos_pares_da_ajustada | sazonal_crescimento | 78 | 5,73 | 2.052 | −382 | −0,65 |

### 6. Teste final (alvos 2021 a 2025, SE/CO) — rodado UMA vez em 07/10/2026

Código de referência: commit provisório `4bc1a17` (árvore limpa antes da execução). O `.meta.json` mostra `arvore_com_mudancas: true` por um artefato (o
`git status` rodava depois de gravar os próprios CSVs; corrigido no código depois). Para conferir que o código é o mesmo mesmo que o commit provisório seja substituído,
os hashes de conteúdo (`git hash-object`) no momento da execução: `ml/validacao.py` ec38c732b3dd, `ml/baselines.py` 2254ee62ea10, `ml/metricas.py` a5d2ed764286,
`dbt/models/marts/fct_carga_mensal.sql` f314243ba152, `dbt/seeds/ajuste_definicao_carga.csv` 00162a808a94. Só `ml/avaliar.py` mudou depois (o metadado).

**Por horizonte, série original** (todas as origens, 60 alvos por horizonte):

| h | Ingênuo MAPE % | MAE | Viés MWmed | Viés % | Crescimento MAPE % | MAE | Viés MWmed | Viés % |
|---|---|---|---|---|---|---|---|---|
| 1 | 5,61 | 2.381 | −1.591 | −3,71 | 5,62 | 2.357 | +148 | +0,39 |
| 2 | 5,61 | 2.381 | −1.591 | −3,71 | 6,20 | 2.602 | +152 | +0,40 |
| 3 | 5,61 | 2.381 | −1.591 | −3,71 | 6,65 | 2.789 | +158 | +0,40 |
| 4 | 5,61 | 2.381 | −1.591 | −3,71 | 7,01 | 2.940 | +159 | +0,40 |
| 5 | 5,61 | 2.381 | −1.591 | −3,71 | 7,37 | 3.095 | +151 | +0,38 |
| 6 | 5,61 | 2.381 | −1.591 | −3,71 | 7,65 | 3.211 | +134 | +0,33 |
| 7 | 5,61 | 2.381 | −1.591 | −3,71 | 7,90 | 3.318 | +110 | +0,27 |
| 8 | 5,61 | 2.381 | −1.591 | −3,71 | 8,11 | 3.401 | +81 | +0,21 |
| 9 | 5,61 | 2.381 | −1.591 | −3,71 | 8,20 | 3.431 | +49 | +0,14 |
| 10 | 5,61 | 2.381 | −1.591 | −3,71 | 8,20 | 3.432 | +13 | +0,06 |
| 11 | 5,61 | 2.381 | −1.591 | −3,71 | 8,35 | 3.490 | −28 | −0,02 |
| 12 | 5,61 | 2.381 | −1.591 | −3,71 | 8,46 | 3.538 | −65 | −0,10 |
| **geral** | 5,61 | 2.381 | −1.591 | −3,71 | 7,48 | 3.134 | +89 | +0,24 |

**Por horizonte, série ajustada:**

| h | Ingênuo MAPE % | MAE | Viés MWmed | Viés % | Crescimento MAPE % | MAE | Viés MWmed | Viés % |
|---|---|---|---|---|---|---|---|---|
| 1 | 4,30 | 1.858 | −1.077 | −2,43 | 4,31 | 1.834 | +105 | +0,31 |
| 2 | 4,30 | 1.858 | −1.077 | −2,43 | 4,65 | 1.981 | +103 | +0,31 |
| 3 | 4,30 | 1.858 | −1.077 | −2,43 | 4,80 | 2.047 | +104 | +0,30 |
| 4 | 4,30 | 1.858 | −1.077 | −2,43 | 4,94 | 2.108 | +103 | +0,29 |
| 5 | 4,30 | 1.858 | −1.077 | −2,43 | 5,20 | 2.217 | +92 | +0,26 |
| 6 | 4,30 | 1.858 | −1.077 | −2,43 | 5,25 | 2.240 | +75 | +0,21 |
| 7 | 4,30 | 1.858 | −1.077 | −2,43 | 5,28 | 2.254 | +50 | +0,15 |
| 8 | 4,30 | 1.858 | −1.077 | −2,43 | 5,48 | 2.336 | +22 | +0,09 |
| 9 | 4,30 | 1.858 | −1.077 | −2,43 | 5,54 | 2.355 | −9 | +0,02 |
| 10 | 4,30 | 1.858 | −1.077 | −2,43 | 5,45 | 2.320 | −40 | −0,05 |
| 11 | 4,30 | 1.858 | −1.077 | −2,43 | 5,53 | 2.352 | −73 | −0,12 |
| 12 | 4,30 | 1.858 | −1.077 | −2,43 | 5,66 | 2.407 | −99 | −0,17 |
| **geral** | 4,30 | 1.858 | −1.077 | −2,43 | 5,18 | 2.204 | +36 | +0,13 |

**Origem em dezembro** (a decisão do contrato; 5 anos × 12 horizontes = 60 pares):

| Série | Baseline | n | MAPE % | MAE MWmed | Viés MWmed | Viés % |
|---|---|---|---|---|---|---|
| original | sazonal_ingenuo | 60 | 5,61 | 2.381 | −1.591 | −3,71 |
| original | sazonal_crescimento | 60 | 6,93 | 2.879 | −24 | −0,04 |
| ajustada | sazonal_ingenuo | 60 | 4,30 | 1.858 | −1.077 | −2,43 |
| ajustada | sazonal_crescimento | 60 | 4,72 | 2.004 | −67 | −0,12 |
| original_nos_pares_da_ajustada | sazonal_ingenuo | 60 | 5,61 | 2.381 | −1.591 | −3,71 |
| original_nos_pares_da_ajustada | sazonal_crescimento | 60 | 6,93 | 2.879 | −24 | −0,04 |

**Erro do ano inteiro** (origem em dezembro), em % e em MWmed:

| Série / baseline | 2021 | 2022 | 2023 | 2024 | 2025 | Erro absoluto médio |
|---|---|---|---|---|---|---|
| original / sazonal_ingenuo | −7,34% (−2.877) | −1,26% (−501) | −5,25% (−2.198) | −5,80% (−2.579) | +0,44% (+197) | 4,02% |
| original / sazonal_crescimento | −9,46% (−3.709) | +6,56% (+2.604) | −4,04% (−1.691) | −0,58% (−259) | +6,63% (+2.934) | 5,45% |
| ajustada / sazonal_ingenuo | −3,03% (−1.214) | −1,40% (−569) | −4,18% (−1.776) | −4,55% (−2.023) | +0,44% (+197) | 2,72% |
| ajustada / sazonal_crescimento | −4,91% (−1.968) | +1,68% (+683) | −2,82% (−1.199) | −0,38% (−170) | +5,23% (+2.316) | 3,01% |

**Viés por ano-alvo** (sazonal ingênuo, todas as origens). A comparação do viés de 2021 é o resultado a destacar: o ajuste leva o viés do ano de **−7,39% (−2.877
MWmed) para −2,98% (−1.214 MWmed)** e o MAPE de 7,99% para 4,80%:

| Ano-alvo | Original: viés MWmed | viés % | MAPE % | Ajustada: viés MWmed | viés % | MAPE % |
|---|---|---|---|---|---|---|
| 2021 | −2.877 | −7,39 | 7,99 | −1.214 | −2,98 | 4,80 |
| 2022 | −501 | −1,16 | 2,91 | −569 | −1,34 | 2,56 |
| 2023 | −2.198 | −4,93 | 6,53 | −1.776 | −3,96 | 4,74 |
| 2024 | −2.579 | −5,75 | 7,11 | −2.023 | −4,55 | 5,91 |
| 2025 | +197 | +0,68 | 3,52 | +197 | +0,68 | 3,52 |

2021 mês a mês (erro % do ingênuo; é o mesmo em qualquer horizonte):

| Mês de 2021 | 01 | 02 | 03 | 04 | 05 | 06 | 07 | 08 | 09 | 10 | 11 | 12 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| original (erro %) | −3,2 | −3,2 | −9,6 | −16,3 | −18,0 | −13,2 | −7,8 | −9,0 | −5,2 | +3,6 | −5,4 | −1,5 |
| ajustada (erro %) | −3,4 | −3,2 | −6,6 | −11,6 | −11,5 | −5,4 | −0,3 | −2,5 | +0,3 | +9,4 | −2,1 | +1,2 |

Leitura, com o que os números permitem afirmar:
- **O ajuste ajuda onde há quebra de definição.** O MAPE geral do ingênuo cai de 5,61% para 4,30% e o viés de −3,71% para −2,43%; o ganho vem de 2021, 2023 e 2024
  (os anos com base de antes de uma quebra). Em 2025 as duas séries são idênticas, porque a base (2024) já está na definição nova; em 2022 o MAPE melhora (2,91% → 2,56%) mas o
  viés piora um pouco (−1,16% → −1,34%).
- **Resta viés negativo.** O ingênuo prevê abaixo do real em 4 dos 5 anos (a carga cresce e ele não vê o crescimento): −2,43% na ajustada, −1.077 MWmed. O ajuste não remove
  o crescimento real nem o rebote da pandemia em 2021.
- **O de crescimento não vence o ingênuo no MAPE** (7,48% contra 5,61% na original; 5,18% contra 4,30% na ajustada), mas tem viés ~0 (+0,24% e +0,13%). O erro dele cresce
  com o horizonte (5,62% em h = 1 a 8,46% em h = 12 na original). No erro anual de dezembro ele erra mais que o ingênuo em 3 dos 5 anos (−9,5% em 2021, +6,6% em 2022 e +6,6% em 2025 na original) e menos em 2023 e 2024 (−4,0% e −0,6%).
- **Do desenvolvimento ao teste final o MAPE do ingênuo quase dobra** (2,92% → 5,61% na original): o período 2021–2025 atravessa as duas quebras e a recuperação da pandemia.
- **Out/2021:** o erro da ajustada (+9,4%) é bem diferente do da original (+3,6%) nesse único mês. É compatível com a anomalia sem causa conhecida do SE/CO (`fontes.md`): o valor
  da curva em out/2021 está ~972 MWmed abaixo da carga da API, e a série ajustada não corrige esse mês. Não é uma conclusão, só a coerência entre os dois fatos.

### O que medir depois (Sprint 5 em diante)

O MAPE do modelo linear e do LightGBM contra estes números, no mesmo protocolo e só depois do desenvolvimento; a escolha do tratamento do histórico anterior a 2018; e o
mesmo teste final com o modelo escolhido (uma vez).

## Sprint 5, Parte A: candidatos no desenvolvimento (Checkpoint A)

Medido em 08/10/2026. Alvos 2012-01 a 2019-12, série `original`, origem móvel com janela de 72 meses, h = 1..12, 1.152 pares por candidato (todas as 107 origens), as mesmas do baseline. Resultados completos em `docs/resultados/candidatos_desenvolvimento_original_*` (resumo, por horizonte, erro anual, previsões com o erro por origem e horizonte, e `.meta.json` com os hashes do código). O teste final **não** foi rodado.

| Candidato | MAPE % | MAE MWmed | Viés % | MAPE h=1 | MAPE h=12 | Dif. vs ingênuo (pp) | EP da dif. (pp) | Anos melhores (de 8) | Erro anual dez. (abs, %) | MAPE do pior ano % | Tempo de modelo |
|---|---|---|---|---|---|---|---|---|---|---|---|
| comb. ETS+SARIMA+regressão | **2,66** | 961 | +0,45 | 2,22 | 2,77 | **+0,255** | 0,27 | 6 | 1,82 | 3,80 | 77 s |
| ETS | 2,71 | 988 | −0,42 | 2,25 | 2,62 | +0,206 | 0,21 | 6 | **1,67** | 3,76 | 13 s |
| comb. ETS+SARIMA | 2,80 | 1.015 | +0,01 | 2,26 | 2,86 | +0,116 | 0,19 | 6 | 2,12 | 3,81 | 77 s |
| **sazonal ingênuo** (baseline) | 2,92 | 1.063 | −0,83 | 2,92 | 2,92 | — | — | — | 1,90 | 4,47 | — |
| regressão | 3,04 | 1.085 | +1,32 | 2,70 | 3,40 | −0,122 | 0,44 | 4 | 1,89 | 4,85 | 0,3 s |
| SARIMA | 3,04 | 1.097 | +0,45 | 2,34 | 3,34 | −0,124 | 0,21 | 3 | 2,75 | 4,03 | 64 s |
| LightGBM | 3,45 | 1.246 | +0,29 | 3,36 | 3,37 | −0,528 | 0,21 | 2 | 2,99 | 4,55 | 2 s |

Dif. = MAPE do ingênuo − MAPE do candidato nos mesmos pares (positivo = candidato melhor); EP por bootstrap em blocos de ano-alvo (semente 0, 2.000 réplicas). O ingênuo reproduz os números da Sprint 4B (2,92%, viés −0,83%, erro anual 1,90%), o que confere o protocolo.

**Pela regra congelada, vence a média ETS+SARIMA+regressão, por 0,005 pp**: a diferença de 0,2553 pp passa o limiar de 0,25 pp e 6 de 8 anos passam o corte de 5. É uma vitória estatisticamente marginal (a diferença é menor que 1 EP). ETS sozinho (+0,206 pp) não chega ao limiar. Nenhum candidato elegível empatou com o vencedor (o ETS fica a 0,05 pp de MAPE, mas não é elegível). Leitura:
- A média das três famílias tem **MAPE menor em 6 de 8 anos que o ingênuo** e **viés +0,45%** (o ingênuo tem −0,83%): o viés mudou de sinal e diminuiu em módulo, mas continua não nulo.
- O MAPE da média das três sobe de 2,22% (h=1) para 2,77% (h=12) e fica abaixo dos 2,92% do ingênuo em todos os horizontes.
- Na origem de dezembro (96 pares): ingênuo 2,92%, ETS 2,64%, média das três 2,81%, SARIMA 3,44%, LightGBM 4,01%.
- LightGBM é o pior: com 72 meses sobram ~6 anos de informação independente, como previsto.
- Tempo de toda a avaliação: 66 s com 4 processos (estimativa antes de rodar: 1,4 min sequencial). Reproduzível: ets, regressão e LightGBM recalculados do zero deram previsões idênticas.

### Reconstrução do tipo III e fct_carga_mensal (dbt)
`dbt seed` (192 linhas) + `dbt run fct_carga_mensal` (1,3 mil linhas, 21,6 MiB processados, 4,2 s) + 32 testes do modelo e do seed: **PASS=32** (dois testes novos: reconstrução só onde deve e conferência com a API em 2018). Pytest: 541 passaram.

### O que medir depois
Ver o Checkpoint B abaixo (já medido). Resta, no Checkpoint C, a tabela `fct_previsao_carga` e a task da DAG.

## Sprint 5, Parte A: teste final do vencedor (Checkpoint B)

Rodado **uma vez por série** em 08/10/2026 (01:46 UTC), só a média ETS+SARIMA+regressão e o ingênuo, com `--liberar-teste-final` (o CLI recusa qualquer outro candidato). Regra registrada antes de rodar, no `decisoes.md` e no `.meta.json`: *a Sprint 6 usa essa média independentemente do resultado; o teste final reporta desempenho, não seleciona*. Ressalva também registrada: a vitória no desenvolvimento foi de 0,255 pp, menor que 1 erro-padrão (0,27 pp). Alvos 2021-01 a 2025-12; treino com janela de 72 meses; código de referência `d293dce` com árvore sem commit (hashes de conteúdo no `.meta.json`).

**Atenção ao número de pares.** A série ajustada reconstruída começa em 2015-01, então a janela de 72 meses só existe a partir da origem dez/2020: o modelo tem **654 dos 720 pares** (em 2021 só 78 dos 144, os de horizonte curto). O ingênuo é mostrado em todos os pares (720) e **nos mesmos 654**. A origem de dezembro tem os 12 horizontes em todos os anos. Na série original (que vem desde 2000) são 720 pares.

| Série | Candidato | Pares | MAPE % | MAE MWmed | Viés MWmed | Viés % | Dif. vs ingênuo (pp, mesmos pares) | EP (pp) | Anos melhores (de 5) | Erro anual dez. (abs, %) | MAPE dez. % |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **ajustada (principal)** | média ETS+SARIMA+regressão | 654 | **3,11** | 1.361 | −384 | −0,76 | **+1,06** | 0,45 | 4 | 1,33 | 2,53 |
| ajustada | ingênuo, mesmos pares | 654 | 4,17 | 1.817 | −981 | −2,17 | — | — | — | 2,72 | 4,30 |
| ajustada | ingênuo, todos | 720 | 4,30 | 1.858 | −1.077 | −2,43 | — | — | — | 2,72 | 4,30 |
| original (comparação) | média ETS+SARIMA+regressão | 720 | 4,08 | 1.723 | −651 | −1,49 | +1,54 | 0,75 | 4 | 2,57 | 3,76 |
| original | ingênuo | 720 | 5,61 | 2.381 | −1.591 | −3,71 | — | — | — | 4,02 | 5,61 |
O ingênuo reproduz os números da Sprint 4B (4,30% / −2,43% na ajustada, 5,61% / −3,71% na original). O erro-padrão é por bootstrap em blocos de ano-alvo (semente 0): **só 5 anos**, então a precisão é pequena; a diferença é de 2,4 EP na ajustada e 2,1 na original, mas 4 de 5 anos não é prova de nada.

MAPE % por horizonte (ajustada, todas as origens): média das três 2,33 (h=1), 2,62, 2,76, 2,79, 2,92, 3,12, 3,34, 3,39, 3,40, 3,61, 3,61, **3,83 (h=12)**; ingênuo nos mesmos pares 4,17 em média (4,0 a 4,3 em cada horizonte). Na série original: 2,72 (h=1) a 5,03 (h=12) contra 5,61. A vantagem encolhe com o horizonte (em h=12, 3,83 contra 4,12).

Erro do ano inteiro na origem de dezembro (previsto menos real, % e MWmed), ajustada:
| | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---|---|---|---|---|
| média ETS+SARIMA+regressão | +0,46% (+183) | −0,45% (−185) | **−3,80% (−1.613)** | +1,17% (+519) | +0,76% (+335) |
| ingênuo | −3,03% (−1.214) | −1,40% (−569) | −4,18% (−1.776) | −4,55% (−2.023) | +0,44% (+197) |
Na original: modelo −3,28%, −0,62%, −5,88%, +1,68%, +1,39% e ingênuo −7,34%, −1,26%, −5,25%, −5,80%, +0,44%. **Em 2023 o modelo não ajuda** (−3,8% na ajustada; na original é pior que o ingênuo, −5,88% contra −5,25%): é o ano em que a carga cresce 5,5% e a MMGD entra na curva.

### Análise de erros (5.3)
`python -m ml.analise_erros` (só lê os resultados; arquivos `analise_teste_final_*`). Série ajustada, erro = previsto − real.
- **O viés do ingênuo foi corrigido só em parte.** Geral: −2,43% (−2,17% nos mesmos pares) → −0,76%. Por ano (todas as origens), média ETS+SARIMA+regressão contra ingênuo: 2021 +1,08% (−1,28%), 2022 −0,25% (−1,34%), 2023 **−3,23%** (−3,96%), 2024 **−2,51%** (−4,55%), 2025 +1,94% (+0,68%). O modelo ainda subestima 2023 e 2024 (os anos de crescimento forte) e passa a superestimar 2021 e 2025. O sinal do viés depende da origem: em 2024 é −2,5% com todas as origens e +1,2% na de dezembro.
- **Por mês-calendário do alvo (viés %):** fevereiro −3,44 e março −3,50 são os piores (ingênuo −4,32 e −3,27); os demais meses ficam entre −1,4 e +0,9. MAPE maior em setembro (4,52) e outubro (4,05). Não investiguei a causa de fev/mar (os dias úteis efetivos já descontam o Carnaval); fica como observação, não como conclusão.
- **Por horizonte:** o MAPE sobe de 2,33% (h=1) para 3,83% (h=12), como previsto, e o ingênuo é constante (~4,2%).
- **Temperatura (INMET, 2021+, 60 meses-alvo; anomalia = temperatura do mês menos a média do mesmo mês-calendário em 2021–2025, portanto dentro da amostra):** o erro médio de cada mês-alvo cai **3,68 pontos percentuais por °C** de anomalia (correlação −0,76, R² 0,57); no ingênuo, −3,99 (R² 0,40); em h=12 (49 meses), −4,48 (R² 0,61). Mês mais quente que o normal → carga acima da previsão (erro mais negativo). O coeficiente é consistente com os 3,5%/°C medidos sobre a própria carga (`decisoes.md`) e mostra que **a anomalia de temperatura sozinha responde por R² de 0,57 do erro mensal**, e ela não se conhece 12 meses antes. Sem causalidade a provar: 60 meses, anomalia calculada na mesma amostra.
- **Out/2021 (pendência 17):** erro de **+8,26%** no modelo e +9,37% no ingênuo, nos 10 horizontes que existem para esse alvo (8,0% a 8,8%). O MAPE de 2021 do modelo cai de 1,89% para 0,95% sem esse mês (ingênuo, mesmos pares: 4,14% → 3,36%). Na série original o erro do mês é +4,09% (modelo) e +3,60% (ingênuo). A anomalia da curva (~972 MWmed, 2,4% do mês) explica só uma parte de um erro de 8%; a causa continua em aberto e **a pendência 17 segue pendente** (verificar com o ONS).

### Intervalos de previsão
Quantis empíricos do erro em log, log(real/previsto), do **desenvolvimento** (96 pares por horizonte, 2012–2019), aplicados ao teste final (`quantis_erro_desenvolvimento_*`, `analise_teste_final_*_intervalos_*`). Intervalo de 95% por horizonte: de [−4,7%, +5,8%] em h=1 a [−7,0%, +5,8%] em h=12 sobre a previsão; largura média 13,5% (95%) e 8,1% (80%).
| Série / variante | Cobertura de 80% (nominal) | Cobertura de 95% (nominal) | Fora do 95%: acima do teto / abaixo do piso |
|---|---|---|---|
| ajustada, quantis por horizonte | **70,2%** | **87,8%** | 56 / 24 (de 654) |
| ajustada, todos os horizontes juntos | 70,8% | 90,5% | 42 / 20 |
| original, por horizonte | 57,1% | 80,6% | 111 / 29 (de 720) |
Por ano (ajustada, por horizonte), cobertura de 80%: 85,9% (2021), 89,6% (2022), **61,1%** (2023), **56,9%** (2024), 64,6% (2025); de 95%: 87,2%, 97,9%, 79,9%, 87,5%, 86,1%. Por horizonte a cobertura de 80% cai de 71,7% (h=1) para 61,2% (h=12).
Leitura: **os intervalos calibrados no desenvolvimento são estreitos demais para 2021–2025** (80% nominal vira 70%; 95% vira 88%), quase sempre porque a carga real fica **acima** do intervalo em 2023–2024 (a MMGD e o crescimento). A ressalva de precisão: são 5 anos, os 12 horizontes de um mesmo mês-alvo compartilham o mesmo erro e a cobertura por ano varia de 57% a 90%; os 654 pares **não** são 654 observações independentes, então a diferença entre 70% e 80% não tem teste formal confiável. Para a Parte B isso pesa: usar só o erro do desenvolvimento subestima a incerteza; na produção convém calibrar com desenvolvimento e teste final juntos (13 anos de alvos) e olhar a cobertura por regime.

### Erros por origem (insumo da Parte B)
`erros_por_origem_{desenvolvimento_original,teste_final_reconstruida,teste_final_original}.csv`: uma linha por origem com o erro % dos horizontes 1 a 12 (`erro_pct_h01..h12`) e a marca `horizontes_completos`. Origens completas: 2012-01 a 2018-12 no desenvolvimento e dez/2020 a dez/2024 no teste final da ajustada. A unidade de reamostragem da Parte B é a origem inteira (preserva a correlação entre meses). Os mesmos erros, por par, estão em `candidatos_*_previsoes.csv`.

### O que medir depois
Checkpoint C: tempo da task mensal na DAG, bytes lidos e gravados, e o MAPE das previsões já gravadas em `fct_previsao_carga`.

### RESSALVAS do teste final (leia junto com o resultado)
Resultado: **3,11% contra 4,17% do ingênuo nos mesmos pares** (−1,06 pp, 2,4 EP), viés −0,76% contra −2,17%, erro anual de dezembro 1,33% contra 2,72%.
1. **Parte da vantagem vem do ingênuo piorar em 2021–2025** (2,92% → 4,30%): a vantagem foi de 0,26 pp no desenvolvimento e de 1,06 pp aqui.
2. **2023 continua com −3,8%** de erro anual em dezembro (e 2024 com −2,5% de viés com todas as origens).
3. **O modelo perde em 2025** (3,72% contra 3,52%).
4. **Os intervalos ficaram estreitos**: 70% de cobertura para 80% nominal e 88% para 95%.
Mais: 5 anos de teste, 654 dos 720 pares, e vitória de 0,255 pp no desenvolvimento, menor que 1 EP (0,27).

## Sprint 5, Parte A: previsão em produção (Checkpoint C)

Medido em 08/10/2026. **O que foi medido sem gravar na nuvem** (a validação com gravação é `scripts/passo_sprint5_c.sh`, a rodar por você; os números dela entram aqui depois):
- **Testes:** 578 no pytest (`tests/test_ml_candidatos.py`, `test_ml_intervalos.py`, `test_ml_previsao.py`, a DAG com as duas tasks novas e a imagem), ruff limpo.
- **SQL no motor do BigQuery, sem criar nada persistente:** os dois `MERGE` e as 15 conferências de `scripts/conferir_previsao.py` foram executados duas vezes sobre **tabelas temporárias de sessão** (com as 12 previsões da origem 2026-09 e os 1.806 erros): 12 e 1.806 linhas depois da 2ª execução (idempotente), MAPE de 2,6624% (desenvolvimento) e 3,1148% (teste final), 15 PASS. O DDL (`CREATE TABLE IF NOT EXISTS ... OPTIONS`) foi validado por dry-run (0 bytes). O `MERGE` real contra as tabelas de produção e a task no Airflow ainda não rodaram.
- **`ml.previsao verificar` e `gerar --dry-run` na nuvem (só leitura):** ~5 s, 2 consultas de ~10 MiB faturados; primeira previsão de produção (origem 2026-09, não gravada): 44.921 MWmed em 2026-10 [42.805; 48.298] e 44.836 em 2027-09 [41.816; 48.825].
- **Custo esperado na DAG:** nos ~29 dias sem mês novo, `previsao_ha_mes_novo` custa 1 consulta (~10 MiB faturados, ~5 s); no dia do mês novo, `previsao_mensal` faz ~4 consultas + 2 load jobs (não cobrados), ~40 MiB faturados.
- **Imagem:** `ldd` dos binários do grupo `ml` mostra só glibc, `libgcc_s`, `libstdc++` e `libz`; rebuild necessário. Sem `lightgbm` na imagem.
- **Medido na DAG (veja a seção abaixo):** `previsao_mensal` 22 s e `previsao_ha_mes_novo` 6 s no `dag-gerar`. O tempo do rebuild da imagem não foi registrado.

### O que medir depois
Sprint 6: o backtest com a calibração crescente; a cobertura dos intervalos de 80% e 95% de produção conforme os erros realizados forem entrando em `fct_erro_previsao_carga`.

## Sprint 5, Parte A: estabilidade da série de entrada (arredondamento na origem)

Medido em 08/10/2026. Detalhe e causa em `docs/decisoes.md`.
- **Antes:** o mesmo `AVG` sobre a carga horária, 4 rodadas sem cache: 3 a 5 de 322 meses diferentes bit a bit por rodada (até 7,3e-12 MWmed). Dois builds do mart diferiam em 64 dos 141 meses de treino (máx. 1,2e-10); o SARIMA transformava isso em 30 MWmed na soma de 12 meses (ETS 0,011; regressão 0), e a previsão combinada em +10 MWmed (0,002%).
- **Depois (`casas_decimais_carga` = 3):** 3 `dbt run` seguidos: **0 de 9.016 valores diferem bit a bit**; 6 rodadas sem cache do `ROUND(AVG(...), 3)`: **0 de 1.288** séries mensais diferem; 26 testes do mart PASS (a reconciliação com a horária, na tolerância de meio passo do arredondamento).
- **Desenvolvimento refeito com a série arredondada** (107 origens, 8.064 previsões): vencedor 2,6629% (antes 2,6624%), viés +0,449%, dif. contra o ingênuo 0,2548 pp (antes 0,2553; limiar 0,25), erro anual de dezembro 1,82%, 6 de 8 anos; maior deslocamento por horizonte 0,0044 pp de MAPE; cobertura no teste final 70,18% / 87,77% (iguais). SARIMA: 4,1% dos pares mudaram mais de 0,01% (máx. 0,32%), em 8 das 107 origens.
- **Previsão da origem 2026-09 com a entrada arredondada:** soma dos 12 meses 539.214,16 MWmed, idêntica nas duas execuções de agora; impressão da entrada `57ef0990dace` (141 meses, soma 5.717.834,076, último 44.516,808).
- **Testes:** 588 no pytest (comparador de impressões, impressão da entrada, ALTER, arredondamento).

### A DAG com a previsão mensal, medida (`dag-gerar`, 08/10/2026, `data/logs/sprint5c_dag_gerar2.log`)

Execução manual `manual__normal_20261008T035743` (03:57:47 a 03:59:41 UTC), no ramo em que fechou um mês novo (a previsão da origem 2026-09 foi apagada antes e a DAG a regerou): todas as tasks `success`, `previsao_ha_mes_novo` e `previsao_mensal` em `success`, `pipeline_ok` `success`, 0 falhas nas 15 conferências das tabelas.

| Medida | Sprint 3 (06/10) | Depois | Variação |
|---|---|---|---|
| DAG, do início ao fim | 6 min 40 s | **1 min 54 s** | −71% |
| task `ons_ingestao` | 4 min 22 s | **0 min 17 s** | −94% |
| jobs do dbt | 194 | **63** | −68% |
| dbt, MB processados | 1.557,9 | **326,4** | −79% |
| dbt, MB faturados | 2.965,4 | **871,4** | −71% |
| total faturado (dbt + validações) | 3.031,4 | **944,8** | −69% |

Contra a Sprint 4, Parte A (1 min 33 s, `ons_ingestao` 20 s, 36 jobs do dbt, 284,8 MB processados, 504,4 MB faturados, 525,3 MB no total): **+21 s** na DAG, explicados pela `previsao_mensal` (22 s) e pelo mart mensal que entrou na seleção do ONS (63 jobs do dbt contra 36); `ons_ingestao` 3 s mais rápida. Contra a 4A: jobs **+75%** (36 → 63), faturado do dbt **+73%** (504,4 → 871,4 MB; +367,0 MB) e processado **~+15%** (284,8 → 326,4 MB; +41,6 MB), e +419,5 MB no total faturado. A alta do faturado vem quase toda do piso de 10 MiB do BigQuery por job: 27 jobs novos × 10 MiB ≈ 283 MB, cerca de 77% dos +367 MB. Não medi a atribuição fina entre o mart, os testes dele e a previsão.

Tempo por task: `ons_ingestao` 17 s, `freshness_ons` 8 s, `dbt_run` 27 s, `dbt_test` 29 s, `freshness_manuais` 10 s (em paralelo ao `dbt_test`), `previsao_ha_mes_novo` 6 s, `previsao_mensal` 22 s; as fontes manuais ficaram `skipped`.

**Idempotência e entrada igual:** antes e depois do apagar-e-regerar, a impressão da entrada é a mesma (`57ef0990dace`, 141 meses, último valor 44.516,808), a previsão soma 539.214,2 MWmed e os erros somam 1,06123773 nos dois lados (comparador: "mesma entrada e mesma saída"). É a prova de que, com a série arredondada a 1 kW, o resultado é reproduzível entre uma execução no host e outra dentro da DAG.

**Custo mensal (estimativa):** 944,8 MB × 30 dias = **~28 GB por mês, cerca de 2,8% do 1 TB gratuito** (R$ 0). É um teto: o dbt (ingestão, `dbt run`, `dbt test` e freshness) roda **todo dia** e responde por quase todo esse custo; o que muda nos ~29 dias sem mês novo é só a `previsao_mensal`, que fica `skipped` (a `previsao_ha_mes_novo` roda e custa ~10 MiB faturados). O teto, portanto, quase não cai nesses dias; o custo da previsão em si é pequeno (~40 MiB no dia do mês novo). A frequência dos arquivos manuais do INMET e da CCEE continua sendo premissa minha, como na Sprint 4.


## Sprint 5, Parte B: curva de consumo (5.5) e medidas antes dos cenários (5.6 e 5.7)

Medido em 08/10/2026. Curva: `marts.fct_consumo_horario` (59,3 mil linhas, 2020-01-01 em diante, só dias locais completos) e `marts.fct_pld_ponderado_mensal` (70 linhas, 2021-01 a 2026-10).

### Reconciliação da curva
| Conferência | Resultado |
|---|---|
| Consumo médio 2020-01 a 2025-12 (72 meses, 2.192 dias) | **100,000000 MWh/mês** (`k` = 3,2752385e-6, congelado) |
| Em MWm | **0,136861** (7.200 MWh ÷ 52.608 h); o "~0,137" do premissas é essa conta arredondada |
| Curva ÷ k contra `carga_ajustada_mwmed` do SE, 81 meses completos | diferença máxima **4,99996e-4 MWmed (0,5 kW)**, dentro da tolerância de 1 kW (o arredondamento do mart) |
| Série reconstruída = ajustada de 2018 em diante | 105 meses fechados, 0 diferenças |
| Testes do dbt (curva + PLD ponderado) | 25 de 25 passam; suíte pytest: 593 passam (588 + 5 novos) |

### PLD ponderado pelo consumo contra o PLD médio simples (SE, meses completos)
Razão ponderado/simples: média 1,0011, mínimo 0,931, máximo 1,088; desvio absoluto médio **1,6%**; 20 de 69 meses fora de ±2%. Média de 2021–2026 (ponderada pelo consumo): **R$ 159,59** contra **R$ 160,80** (−0,75%).
| Ano | Razão média | Mín. | Máx. | PLDp médio | PLD simples médio |
|---|---|---|---|---|---|
| 2021 | 1,0156 | 1,0014 | 1,0496 | 282,97 | 279,61 |
| 2022 | 1,0030 | 1,0000 | 1,0178 | 59,19 | 58,99 |
| 2023 | 1,0127 | 1,0000 | 1,0591 | 73,19 | 72,17 |
| 2024 | 1,0134 | 0,9993 | 1,0883 | 129,62 | 127,87 |
| 2025 | 0,9796 | 0,9572 | 1,0048 | 217,96 | 223,46 |
| 2026 (até set) | 0,9760 | 0,9308 | 1,0488 | 208,93 | 215,57 |
Leitura: o perfil de consumo muda o preço em ~1,6% ao mês, em média, e pode inverter de sinal entre anos (2025–26 abaixo de 1; a causa não foi investigada). Não é desprezível para o `P_t` de um contrato com spread de R$ 20, mas é pequeno contra a variação do PLD entre anos.

### Forma mensal contra o COMÉRCIO da CCEE (só indicador; unidade pendente)
2025: correlação de **0,975** entre o consumo mensal da curva e o consumo do ramo COMÉRCIO (ACL), diferença máxima de 2,9% no índice mês/média do ano. A forma é plausível; não calibra nada.

### Correlação entre o erro de previsão, a carga e o PLD do SE (antes de assumir independência)
`log_razao` = ln(real/previsto) (confirmado no código e coberto por teste; `erro_mwmed` é previsto − real, sinal oposto). PLD mensal: média simples das horas (2021+) ou semanal por patamar ponderado por horas (até 2020).
| Par | n | Pearson [IC 95%] | Spearman |
|---|---|---|---|
| `log_razao` h=1 × ln(PLD), 2021–2025 (PLD horário) | 60 | −0,25 [−0,48; 0,00] | −0,15 |
| `log_razao` h=1 × ln(PLD), 2012–2025 | 156 | **−0,20** [−0,35; −0,05] | −0,21 |
| `log_razao` h=12 × ln(PLD), 2012–2025 | 145 | −0,13 [−0,29; +0,03] | −0,11 |
| `log_razao` médio (h=1..12) × ln(PLD), 2012–2025 | 156 | −0,20 [−0,35; −0,05] | −0,19 |
| Carga mensal × PLD (nível), 2015–2025 | 141 | −0,17 [−0,32; 0,00] | −0,16 |
| Δ12 ln(carga) × Δ12 ln(PLD), 2016–2025 | 129 | +0,09 [−0,09; +0,26] | +0,06 |
| Resíduo de ln(carga) (tendência + mês) × ln(PLD), 2015–2025 | 141 | +0,09 [−0,07; +0,26] | +0,07 |
Leitura: a dependência é **fraca** (|r| ≈ 0,1 a 0,25) e com sinal negativo no erro (mês com PLD alto tende a ter consumo abaixo do previsto). O IC é otimista: os erros de origens vizinhas se sobrepõem e o n efetivo é menor. Tirar a tendência e a sazonalidade da carga leva a correlação a ~0. Não prova independência, mas não a contradiz com força; fica como premissa nas limitações.

### PLD mensal do SE em 2001–2020 contra o piso e o teto de 2021–2026 (insumo da decisão da 5.7; nada implementado)
235 meses (jun/2001 a dez/2020), média dos 3 patamares ponderada por horas. Mediana nominal por ano (R$/MWh): 2001 579,6 · 2002 12,4 · 2003 12,3 · 2004 18,6 · 2005 29,2 · 2006 63,5 · 2007 78,9 · 2008 104,8 · 2009 34,9 · 2010 70,0 · 2011 25,9 · 2012 153,2 · 2013 264,9 · **2014 754,0** · 2015 308,0 · 2016 80,6 · 2017 326,8 · 2018 245,8 · 2019 224,3 · 2020 108,4.
Meses abaixo do piso do ano-limite (de 235): 2021 → **86**, 2022 → 91, 2023 → 97, 2024 → 94, 2025 → 92, 2026 → 91. Acima do teto **horário**: 0 em todos. Acima do teto **estrutural**: 13, 11, 8, 7, 6 e 5 (2021 a 2026), quase todos em 2001 e 2014.
Por ano histórico, meses abaixo do piso (limites de 2022): 2002–2005 e 2011, os 12 meses; 2009, 10; 2006, 4; 2007, 5; 2010, 5; 2016, 4; 2012, 2; 2008 e 2020, 1; 2001, 2013–2015 e 2017–2019, 0. A contagem varia pouco com o ano do piso (86 a 97). O cálculo foi feito com scripts avulsos de análise (não versionados) sobre `fct_pld_semanal`; se a decisão da 5.7 usar esses números, o script entra no repositório.

### Cenários de consumo (5.6): cobertura e estabilidade do CVaR95
Medido em 08/10/2026 com `scripts/avaliar_cenarios_consumo.py` (N = 2.000 cenários por origem; 60 origens do teste final, 654 pares). Cenários com calibração **crescente** (vetores com último mês-alvo `<= origem`) contra o método anterior (quantis fixos do desenvolvimento). A coluna "anterior" reproduz os 70,2% e 87,8% de `metricas.md` (Sprint 5, Parte A).
| h | n | cenários 80% | cenários 95% | anterior 80% | anterior 95% |
|---|---|---|---|---|---|
| 1 | 60 | 73,3 | 91,7 | 71,7 | 88,3 |
| 2 | 59 | 76,3 | 91,5 | 76,3 | 89,8 |
| 3 | 58 | 81,0 | 93,1 | 82,8 | 89,7 |
| 4 | 57 | 70,2 | 94,7 | 71,9 | 94,7 |
| 5 | 56 | 75,0 | 91,1 | 76,8 | 91,1 |
| 6 | 55 | 70,9 | 90,9 | 72,7 | 89,1 |
| 7 | 54 | 66,7 | 87,0 | 66,7 | 88,9 |
| 8 | 53 | 66,0 | 86,8 | 66,0 | 84,9 |
| 9 | 52 | 63,5 | 88,5 | 63,5 | 88,5 |
| 10 | 51 | 60,8 | 90,2 | 64,7 | 90,2 |
| 11 | 50 | 62,0 | 84,0 | 64,0 | 80,0 |
| 12 | 49 | 59,2 | 83,7 | 61,2 | 75,5 |
| **todos** | **654** | **69,1** | **89,6** | **70,2** | **87,8** |
Leitura: a calibração crescente **não melhora o intervalo de 80%** (69,1% contra 70,2%, nominal 80%) e melhora pouco o de 95% (89,6% contra 87,8%, nominal 95%). A melhora aparece nos horizontes longos de 95% (h=12: 83,7% contra 75,5%), mas o 80% de h=12 fica em 59,2%. O ganho de ser "sem vazamento" é de honestidade, não de cobertura: os erros de 2021–2025 são maiores que os de 2012–2019 e os cenários das primeiras origens só conhecem os de 2012–2019. Com 49 a 60 pares por horizonte, a precisão de cada célula é de ±6 a ±7 pp.

**Estabilidade do CVaR95 do consumo anual** (cauda alta: média dos 5% maiores consumos de 12 meses, em MWh do caso base; **proxy**: o CVaR95 do custo precisa do modelo de custo, 6.1/6.2). 30 sementes por N; desvio-padrão e viés relativos ao CVaR95 **exato** do conjunto de vetores conhecidos (o limite da reamostragem).
| Origem | Vetores | CVaR95 exato (MWh) | dp% N=1.000 | dp% N=2.000 | dp% N=5.000 | viés% N=1.000 / 2.000 / 5.000 |
|---|---|---|---|---|---|---|
| 2020-12 | 85 | 1.186,18 | 0,06 | 0,04 | 0,03 | −0,01 / 0,00 / 0,00 |
| 2021-12 | 86 | 1.192,02 | 0,05 | 0,04 | 0,02 | −0,01 / −0,01 / −0,01 |
| 2022-12 | 98 | 1.201,88 | 0,06 | 0,03 | 0,02 | −0,01 / 0,00 / 0,00 |
| 2023-12 | 110 | 1.331,57 | 0,12 | 0,07 | 0,04 | −0,02 / −0,01 / 0,00 |
| 2024-12 | 122 | 1.371,63 | 0,15 | 0,11 | 0,06 | −0,02 / −0,04 / −0,02 |
| **Média** | | | **0,09** | **0,06** | **0,04** | −0,02 / −0,01 / 0,00 |
Leitura: o erro de amostragem da reamostragem é desprezível já com N=1.000 (0,09%). **Isso não mede a incerteza real:** o conjunto exato tem só 85 a 122 vetores, sobrepostos (origens mensais), ou cerca de 8 a 11 anos independentes; o CVaR "exato" carrega esse erro de estimação, que N não reduz. Os vetores por origem são menos que os estimados antes (96 a 133), porque os erros do desenvolvimento só têm alvos a partir de 2012-01. O N será decidido com o PLD, que é a fonte de ruído de amostragem maior.

### PIT do consumo anual realizado nos cenários (5.6, N = 2.000, 5 origens de decisão)
Consumo anual do caso base (100 MWh/mês), em MWh. PIT = fração dos cenários com consumo anual `<=` o realizado; um modelo calibrado dá valores espalhados em torno de 0,5. A origem é dezembro do ano anterior à decisão (2022-12 decide 2023). Medido com `scripts/avaliar_cenarios_consumo.py`.
| Origem (ano decidido) | Previsto | p10 | p50 | p90 | Realizado | Realizado/p50 − 1 | PIT |
|---|---|---|---|---|---|---|---|
| 2020-12 (2021) | 1.155,28 | 1.117,89 | 1.153,70 | 1.178,86 | 1.149,91 | −0,33% | 0,480 |
| 2021-12 (2022) | 1.161,02 | 1.125,20 | 1.159,55 | 1.185,89 | 1.166,38 | +0,59% | 0,599 |
| 2022-12 (2023) | 1.171,05 | 1.135,11 | 1.169,84 | 1.194,83 | 1.217,32 | **+4,06%** | **1,000** |
| 2023-12 (2024) | 1.293,94 | 1.254,29 | 1.294,05 | 1.320,30 | 1.278,96 | −1,17% | 0,288 |
| 2024-12 (2025) | 1.279,21 | 1.247,47 | 1.282,21 | 1.318,29 | 1.268,89 | −1,04% | 0,304 |
Leitura: quatro anos caem dentro da faixa de 80% (PIT de 0,29 a 0,60) e **2023 fica acima de todos os 2.000 cenários** (PIT 1,000), o ano da quebra da MMGD em que o modelo errou o ano em −3,8% (`decisoes.md`, ressalva 2 do teste final). Com 5 pontos não se testa uniformidade; o que o PIT mostra é a mesma coisa que a cobertura por horizonte: a cauda alta é subestimada num ano de quebra, e o intervalo de 80% é estreito. 2023 e 2024 (PIT de 0,29 e 0,30) têm previsão um pouco acima do realizado.

### Detector de piso do PLD por ano (5.7; só leitura, nada implementado além do detector)
Critério (`ml/piso_pld.py`, `scripts/detectar_piso_pld.py`): o menor valor do ano é o piso se aparecer em pelo menos **3 blocos distintos** (semanas no PLD semanal 2002–2020, dias locais no PLD horário 2021–2026), tolerância de R$ 0,005. A semana é atribuída ao ano do seu dia do meio. Entre parênteses, o mínimo observado quando o piso não foi detectado. "Conhecido" = o que há no repositório ou foi achado em busca em 08/10/2026 (2012 e 2017–2018 ainda não informados).

| Ano | Fonte | Piso detectado | Repetições | Blocos | Observações | Status | Menor valor repetido | Conhecido | Fonte do conhecido | Diferença |
|---|---|---|---|---|---|---|---|---|---|---|
| 2002 | semanal | 4.00 | 13 | 5 | 165 | detectado | 4.00 | - | - | - |
| 2003 | semanal | 4.00 | 33 | 11 | 162 | detectado | 4.00 | - | - | - |
| 2004 | semanal | (17.58) | 3 | 1 | 156 | repetido_acima | 18.59 | - | - | - |
| 2005 | semanal | 18.33 | 57 | 19 | 156 | detectado | 18.33 | - | - | - |
| 2006 | semanal | 16.92 | 18 | 6 | 156 | detectado | 16.92 | - | - | - |
| 2007 | semanal | 17.59 | 36 | 12 | 156 | detectado | 17.59 | - | - | - |
| 2008 | semanal | (15.47) | 4 | 2 | 159 | minimo_unico | - | - | - | - |
| 2009 | semanal | 16.31 | 70 | 24 | 156 | detectado | 16.31 | - | - | - |
| 2010 | semanal | 12.80 | 30 | 12 | 156 | detectado | 12.80 | - | - | - |
| 2011 | semanal | 12.08 | 23 | 9 | 156 | detectado | 12.08 | - | - | - |
| 2012 | semanal | 12.20 | 7 | 3 | 156 | detectado | 12.20 | - | - | - |
| 2013 | semanal | (94.30) | 1 | 1 | 159 | minimo_unico | - | - | - | - |
| 2014 | semanal | (237.76) | 1 | 1 | 156 | repetido_acima | 822.83 | - | - | - |
| 2015 | semanal | (48.15) | 1 | 1 | 159 | repetido_acima | 388.48 | - | - | - |
| 2016 | semanal | 30.25 | 23 | 9 | 162 | detectado | 30.25 | - | - | - |
| 2017 | semanal | 33.68 | 3 | 3 | 156 | detectado | 33.68 | - | - | - |
| 2018 | semanal | (40.16) | 3 | 1 | 156 | repetido_acima | 505.18 | - | - | - |
| 2019 | semanal | (42.35) | 6 | 2 | 159 | minimo_unico | - | 42.35 | busca: CanalEnergia (PLD_min 2019) | - |
| 2020 | semanal | 39.68 | 17 | 7 | 156 | detectado | 39.68 | 39.68 | busca: Abraceel/CanalEnergia (PLD mínimo 2020) | +0.00 |
| 2021 | horário | 49.77 | 226 | 26 | 8760 | detectado | 49.77 | 49.77 | seed pld_limites (não confirmada) | +0.00 |
| 2022 | horário | 55.70 | 6917 | 298 | 8760 | detectado | 55.70 | 55.7 | seed pld_limites (não confirmada) | +0.00 |
| 2023 | horário | 69.04 | 8611 | 365 | 8760 | detectado | 69.04 | 69.04 | seed pld_limites (não confirmada) | +0.00 |
| 2024 | horário | 61.07 | 5588 | 251 | 8784 | detectado | 61.07 | 61.07 | seed pld_limites (não confirmada) | +0.00 |
| 2025 | horário | 58.60 | 2028 | 216 | 8760 | detectado | 58.60 | 58.6 | seed pld_limites (não confirmada) | +0.00 |
| 2026 | horário | 57.31 | 1578 | 211 | 6600 | detectado | 57.31 | 57.31 | seed pld_limites (não confirmada) | +0.00 |

Sensibilidade ao número mínimo de blocos (anos com piso detectado):
- mínimo de 2 blocos: 20 de 25 anos
- mínimo de 3 blocos: 18 de 25 anos
- mínimo de 5 blocos: 16 de 25 anos

Casos não detectados (7 de 25 anos): **2004** (17,58 em uma semana, depois 18,59 em 47 semanas: o piso mudou perto do início do ano), **2008** (15,47 em 2 semanas), **2013, 2014 e 2015** (o mercado ficou acima do piso o ano todo: mínimos de 94,30, 237,76 e 48,15), **2018** (40,16 em 1 semana) e **2019** (42,35, igual ao conhecido, em 2 semanas seguidas). Com mínimo de 2 blocos entram 2008 e 2019. A semana que começa em 2005-12-31 vale o piso de 2006 (16,92): atribuir a semana pelo início erraria 2005 e 2006.

## Sprint 5, Parte B: cenários de PLD (5.7), histórico transformado e bootstrap
Medido em 08/10/2026 com `scripts/avaliar_cenarios_pld.py` (saída completa em `data/logs/avaliar_cenarios_pld.md`). PLD mensal do SE: média dos 3 patamares do semanal ponderada pelas horas até 2020; PLD ponderado pelo consumo de 2021 em diante. Transformação aprovada: `PLD_alvo = PLD_orig − piso_orig + piso_alvo`, limitada a `[piso_alvo, teto_estrutural_alvo]`. Pisos: detectado (mínimo de 3 blocos), exceção da seed `pld_piso_excecoes` (2004 e 2019) ou interpolação linear (2008, 2013, 2014, 2015, 2018).

### Histórico transformado contra o realizado (antes do bootstrap)
Piso por ano usado na transformação (2002-2020):
2002: 4.00 (detectado), 2003: 4.00 (detectado), 2004: 18.59 (excecao), 2005: 18.33 (detectado), 2006: 16.92 (detectado), 2007: 17.59 (detectado), 2008: 16.95 (interpolado), 2009: 16.31 (detectado), 2010: 12.80 (detectado), 2011: 12.08 (detectado), 2012: 12.20 (detectado), 2013: 16.71 (interpolado), 2014: 21.23 (interpolado), 2015: 25.74 (interpolado), 2016: 30.25 (detectado), 2017: 33.68 (detectado), 2018: 38.02 (interpolado), 2019: 42.35 (excecao), 2020: 39.68 (detectado)

"No piso" = valor mensal a até R$ 0,005 do piso do ano-alvo; "no teto" = a partir do teto estrutural menos R$ 0,005 (no realizado inclui o PLD ponderado que passa um pouco do estrutural, como em 2021).
| Conjunto | Meses | No piso | ≤ 1,05×piso | No teto | Média | Desvio | p10 | p50 | p90 |
|---|---|---|---|---|---|---|---|---|---|
| histórico 2002-2020 → faixa 2021 | 228 | 10.1% | 15.4% | 4.4% | 181.5 | 154.3 | 49.8 | 125.1 | 433.3 |
| realizado 2021 | 12 | 0.0% | 0.0% | 16.7% | 283.0 | 197.6 | 90.9 | 237.1 | 584.1 |
| histórico 2002-2021 → faixa 2022 | 240 | 9.6% | 14.6% | 3.3% | 194.7 | 163.8 | 55.8 | 132.5 | 453.4 |
| realizado 2022 | 12 | 58.3% | 75.0% | 0.0% | 59.2 | 7.0 | 55.7 | 55.7 | 66.3 |
| histórico 2002-2022 → faixa 2023 | 252 | 11.9% | 17.9% | 3.2% | 202.4 | 164.7 | 69.0 | 138.8 | 459.8 |
| realizado 2023 | 12 | 66.7% | 66.7% | 0.0% | 73.2 | 7.0 | 69.0 | 69.0 | 83.4 |
| histórico 2002-2023 → faixa 2024 | 264 | 14.4% | 19.7% | 3.0% | 189.8 | 166.9 | 61.1 | 118.2 | 436.1 |
| realizado 2024 | 12 | 25.0% | 41.7% | 0.0% | 129.6 | 132.5 | 61.1 | 66.4 | 289.2 |
| histórico 2002-2024 → faixa 2025 | 276 | 14.9% | 20.7% | 2.5% | 185.7 | 169.3 | 58.6 | 111.0 | 430.3 |
| realizado 2025 | 12 | 0.0% | 8.3% | 0.0% | 218.0 | 74.2 | 104.9 | 234.2 | 274.7 |
| **realizado 2021-2025** | 60 | 30.0% | 38.3% | 3.3% | 152.6 | 138.1 | 55.7 | 77.5 | 308.9 |

Contraste, histórico 2002-2020 SEM transformar (nominal): média 161.1, desvio 184.3, p10/p50/p90 16.6/92.2/413.8; no piso do seu próprio ano: 10.1%.

Leitura: o histórico transformado é **mais caro e mais disperso** que o realizado de 2021–2025 (média 182 a 202 contra 152,6; p50 111 a 139 contra 77,5) e tem **menos massa no piso** (10% a 15% dos meses contra 30%; 58% a 67% em 2022 e 2023). Os anos de 2002–2020 têm poucos meses no regime de piso prolongado de 2022–2024. É a diferença de regime que a transformação não corrige: ela só leva o piso e o prêmio nominal ao ano-alvo.

### Bootstrap simples contra blocos de 12 meses (N = 2.000)
PIT = fração dos cenários com PLD médio anual `<=` o realizado (PLD ponderado pelo consumo, média dos 12 meses ponderada pelas horas). Var. histórica = variância (n−1) do PLD anual dos anos-calendário completos do histórico, transformados na faixa do ano-alvo.
| Origem (ano) | Método | Realizado | p10 | p50 | p90 | PIT | Var. cenários | Var. histórica | Razão | Meses no piso (cenários) | no piso (hist. transf.) | no piso (realizado) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2020-12 (2021) | simples | 283.9 | 126.1 | 178.6 | 242.4 | 0.981 | 2051 | 17537 | 0.12 | 10.0% | 10.1% | 0.0% |
| 2020-12 (2021) | blocos | 283.9 | 59.1 | 129.8 | 314.8 | 0.746 | 16707 | 17537 | 0.95 | 10.5% | 10.1% | 0.0% |
| 2021-12 (2022) | simples | 59.3 | 136.9 | 194.3 | 256.9 | 0.000 | 2202 | 18992 | 0.12 | 9.4% | 9.6% | 58.3% |
| 2021-12 (2022) | blocos | 59.3 | 65.0 | 174.4 | 317.8 | 0.051 | 17512 | 18992 | 0.92 | 9.9% | 9.6% | 58.3% |
| 2022-12 (2023) | simples | 73.2 | 143.7 | 197.6 | 264.7 | 0.000 | 2302 | 19621 | 0.12 | 11.8% | 11.9% | 66.7% |
| 2022-12 (2023) | blocos | 73.2 | 78.4 | 149.0 | 360.4 | 0.093 | 20663 | 19621 | 1.05 | 11.8% | 11.9% | 66.7% |
| 2023-12 (2024) | simples | 129.9 | 131.7 | 186.4 | 254.4 | 0.095 | 2264 | 20596 | 0.11 | 14.1% | 14.4% | 25.0% |
| 2023-12 (2024) | blocos | 129.9 | 65.2 | 140.9 | 323.5 | 0.499 | 19556 | 20596 | 0.95 | 14.7% | 14.4% | 25.0% |
| 2024-12 (2025) | simples | 218.8 | 125.3 | 181.9 | 251.7 | 0.760 | 2391 | 20886 | 0.11 | 15.1% | 14.9% | 0.0% |
| 2024-12 (2025) | blocos | 218.8 | 62.7 | 127.6 | 320.7 | 0.707 | 19347 | 20886 | 0.93 | 15.1% | 14.9% | 0.0% |

Leitura: (1) **o simples subestima a variância do PLD anual em ~9×** (razão de 0,11 a 0,12, o esperado para 12 meses sorteados de forma independente), e os blocos a reproduzem (0,92 a 1,05); (2) o realizado de 2022 e 2023 (R$ 59 e 73) fica **abaixo de todos** os cenários do simples (PIT 0,000) e na cauda baixa dos blocos (PIT 0,051 e 0,093); 2021 fica acima de 98% do simples (PIT 0,981) e dentro dos blocos (0,746); (3) a fração de meses no piso dos cenários (9% a 15%) reproduz a do histórico, mas o realizado teve 58% a 67% em 2022–2023: **os cenários subestimam o regime de piso prolongado**, o que afeta mais a sobra vendida barata (contrato demais). Com 5 pontos não se testa uniformidade.

### Sensibilidade do piso nas lacunas (2008, 2013, 2014, 2015, 2018)
| Ano | Interpolado | Vizinho baixo | Vizinho alto |
|---|---|---|---|
| 2008 | 16.95 | 16.31 | 17.59 |
| 2013 | 16.71 | 12.20 | 30.25 |
| 2014 | 21.23 | 12.20 | 30.25 |
| 2015 | 25.74 | 12.20 | 30.25 |
| 2018 | 38.02 | 33.68 | 42.35 |

| Origem (ano) | Método | Média base | Média baixo (Δ%) | Média alto (Δ%) | p95 base | p95 baixo (Δ%) | p95 alto (Δ%) |
|---|---|---|---|---|---|---|---|
| 2020-12 (2021) | simples | 182.26 | 183.55 (+0.71%) | 180.98 (-0.70%) | 263.39 | 265.16 (+0.67%) | 261.63 (-0.67%) |
| 2020-12 (2021) | blocos | 179.14 | 180.45 (+0.73%) | 177.88 (-0.70%) | 557.67 | 559.18 (+0.27%) | 556.16 (-0.27%) |
| 2021-12 (2022) | simples | 196.30 | 197.62 (+0.68%) | 194.97 (-0.68%) | 281.65 | 283.65 (+0.71%) | 280.04 (-0.57%) |
| 2021-12 (2022) | blocos | 195.28 | 196.72 (+0.74%) | 193.94 (-0.69%) | 347.04 | 347.04 (+0.00%) | 347.04 (+0.00%) |
| 2022-12 (2023) | simples | 202.43 | 203.65 (+0.60%) | 201.19 (-0.61%) | 290.51 | 292.68 (+0.75%) | 288.18 (-0.80%) |
| 2022-12 (2023) | blocos | 208.03 | 209.27 (+0.60%) | 206.80 (-0.59%) | 638.29 | 641.33 (+0.48%) | 635.24 (-0.48%) |
| 2023-12 (2024) | simples | 190.21 | 191.38 (+0.61%) | 189.02 (-0.63%) | 275.10 | 276.14 (+0.38%) | 273.77 (-0.48%) |
| 2023-12 (2024) | blocos | 190.76 | 191.96 (+0.63%) | 189.51 (-0.65%) | 351.88 | 351.88 (+0.00%) | 351.88 (+0.00%) |
| 2024-12 (2025) | simples | 185.71 | 186.84 (+0.61%) | 184.52 (-0.64%) | 274.17 | 276.13 (+0.72%) | 272.49 (-0.61%) |
| 2024-12 (2025) | blocos | 182.55 | 183.70 (+0.63%) | 181.42 (-0.62%) | 349.94 | 349.94 (+0.00%) | 349.94 (+0.00%) |

Leitura: trocar a interpolação pelo vizinho mais baixo ou mais alto muda a **média** do PLD anual em +0,6% a +0,75% (baixo) e −0,6% a −0,7% (alto), e o **p95** em até ±0,8%. O p95 dos blocos fica **exatamente igual** em algumas origens porque, com 20 a 23 blocos, o p95 é o valor de um ano histórico específico, que pode não ser um ano de lacuna. A escolha da interpolação é segura para o resultado.

### Gravação dos cenários (5.6 e 5.7): tempo, bytes faturados, memória e idempotência
Executado pelo usuário em 08/10/2026 (`python -m ml.cenarios gerar --n 2000`, logs em `data/logs/cenarios_gerar.log`, `cenarios_gerar_2.log` e `cenarios_contagem.log`). `execucao_id` **51cf99b073fe** nas duas execuções.
| Medida | 1ª execução | 2ª execução (mesmos insumos) |
|---|---|---|
| Tempo total (impresso pelo script) | **58,8 s** (relógio 1:00,63) | 54,8 s |
| CPU | 7,0 s de usuário + 1,3 s de sistema (13% de uso de CPU): **o resto é espera do BigQuery** | n/d |
| Pico de memória (RSS máximo) | **604.456 kB (~590 MiB)** | n/d |
| Leitura dos insumos (erros, PLD, limites) | 12,0 s | 7,3 s |
| Bytes faturados, `fct_cenario_consumo` | 20.971.520 (20 MiB) | 20.971.520 (20 MiB) |
| Bytes faturados, `fct_cenario_pld` | 20.971.520 (20 MiB) | **40.894.464 (39 MiB)** |
| Bytes faturados, `fct_cenario_execucao` | 20.971.520 (20 MiB) | 20.971.520 (20 MiB) |
| **Total faturado** | **62.914.560 (60,0 MiB)** | **82.837.504 (79,0 MiB)** |
Por tabela, 1ª execução (carga da temporária / MERGE, em s): consumo 12,0 / 4,5; PLD 11,8 / 6,0; execução 5,4 / 2,1. 2ª execução: consumo 13,7 / 4,3; PLD 12,0 / 5,0; execução 5,1 / 2,6. Cada tabela gasta ~1,7 s no DDL e na checagem de colunas (2 jobs por tabela, sem custo: `bytes_faturados = 0`).

**Causa da diferença de bytes (confirmada em `INFORMATION_SCHEMA.JOBS_BY_PROJECT`, sem supor):** os 3 jobs de MERGE de cada execução e os bytes que o BigQuery diz ter processado:
| Tabela | Job MERGE, 1ª execução (processados / faturados) | Job MERGE, 2ª execução (processados / faturados) | `numBytes` da tabela-destino |
|---|---|---|---|
| `fct_cenario_consumo` | 10.080.000 / 20.971.520 | 20.160.000 / 20.971.520 | 10.080.000 |
| `fct_cenario_pld` | 20.304.000 / 20.971.520 | **40.608.000 / 40.894.464** | 20.304.000 |
| `fct_cenario_execucao` | 1.308 / 20.971.520 | 2.616 / 20.971.520 | 1.308 |
- **O MERGE lê a tabela temporária e a tabela-destino inteira.** Na 1ª execução o destino está vazio e processa-se só a temporária (10,08 MB; 20,30 MB; 1.308 B); na 2ª o processado **dobra exatamente** (20,16; 40,61; 2.616), e esse acréscimo é igual ao `numBytes` do destino.
- **O faturamento tem piso de 10 MiB por tabela referenciada**: com o MERGE lendo duas tabelas, o piso é 20 MiB (20.971.520), o que esconde a duplicação em `fct_cenario_consumo` (19,2 MiB processados) e em `fct_cenario_execucao`. Só a de PLD passa do piso (38,7 MiB processados, faturados 39 MiB, arredondados para cima em MiB). A 1ª execução também fatura 20 MiB nas três (o piso, com a tabela vazia).
- **Backlog (não implementado):** particionar/clusterizar os fatos de cenário por `origem` e filtrar a `origem` no `ON` do MERGE, para ele ler só as partições das origens da execução. Ver o backlog da Sprint 5 em `docs/planejamento/`.
- **Projeção (não medida):** como cada `execucao_id` novo (N, semente, `k`, erros, PLD ou pisos diferentes) **acrescenta** ~30 MB e o MERGE lê o destino inteiro, o custo de cada nova execução cresce com o histórico gravado; com regeração só no fechamento do mês, o custo continua pequeno (79 MiB é 0,0075% de 1 TiB, a cota gratuita mensal), mas cresce até o filtro por origem existir.

**Idempotência:** a 2ª execução teve o mesmo `execucao_id` e a contagem das tabelas, conferida em `cenarios_contagem.log`, ficou em **144.000 linhas de consumo, 288.000 de PLD e 6 de execução** (as mesmas da 1ª): nenhuma duplicata, o MERGE só atualizou as linhas existentes.

**Regra de regeração:** os cenários dependem dos erros de previsão, do PLD e dos pisos, que só mudam quando fecha um mês. Eles **só são regerados quando um mês fecha**. Se entrarem na DAG, ficam **atrás da `previsao_ha_mes_novo`** (o ShortCircuit mensal da 5.4), nunca na execução diária: as outras 29 execuções do mês gerariam o mesmo `execucao_id` e pagariam ~79 MiB à toa.
