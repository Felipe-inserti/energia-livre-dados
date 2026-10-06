# Registro de métricas

Nunca otimizar antes de medir a versão simples. Preencher "Antes" na versão ingênua e "Depois" após a melhoria.

| Nível | Métrica | Antes (versão simples) | Depois | Fase |
|---|---|---|---|---|
| Negócio | Custo anual de energia do consumidor-exemplo (backtest) | estratégia ingênua: R$ __ | estratégia otimizada: R$ __ | 6 |
| Negócio | Economia | — | R$ __ / __% | 6 |
| Negócio | Exposição ao PLD (MWh descobertos ou sobrando) | __ | __ | 6 |
| Ciência | MAPE mensal da previsão de carga (12 meses à frente, rolling origin) | baseline: __% | modelo: __% | 5 |
| Engenharia | Dados lidos por consulta típica (**bytes processados**) | 0,037 GB (ONS, raw STRING sem partição: 37,3 MB processados; 37,7 MB faturados) | tipado sem partição: 0,018 GB (18,3 MB); **fato particionado por mês e clusterizado: 0,0007 GB (0,74 MB processados, −98,0% contra o raw)**. O faturado cai para 10,5 MB, o piso de 10 MiB do BigQuery, então a métrica de comparação são os bytes processados | 1 → 2 |
| Engenharia | Tempo de carga diária | full: **9,3 min** (ONS 4,9 + CCEE 1,2 + INMET 3,1 + feriados 0,2; sem o tempo do download manual) | incremental: __ min | 1 → 4 |
| Engenharia | Tempo do backfill completo (2021–hoje) | — | __ min | 4 |
| Engenharia | Problemas de dados capturados pelos testes | — | **10 registros em 173 testes** (10 estações do INMET abaixo de 95% de horas válidas em 2026, `warn`), 0 `error`; mais 240 horas nulas e 20 horas inexistentes, já conhecidas e cobertas por exceções. Detalhe na seção "Sprint 3, Parte A" | 3 |
| Engenharia | MB gravados no GCS por execução da ingestão do ONS | full: **40,9 MB** (os 27 arquivos, toda vez) | por hash: **2,45 MB** na execução com revisão (−94,0%) e **0,00 MB** na seguinte (−100%) | 3 |
| Engenharia | Revisões retroativas do ONS | não medidas (o bronze era sobrescrito) | 1 de 27 arquivos mudou: 480 valores revisados (1,8% das linhas do arquivo), diferença máxima de 0,517% | 3 |
| Engenharia | Freshness do ONS | sem freshness | antes da carga `ERROR STALE` (120 h); depois, com os limites iniciais, `WARN` (48,8 h); com os limites calibrados (72 h e 120 h), `PASS` | 3 |
| Engenharia | Idempotência | — | 2 execuções → mesma contagem: sim/não | 4 |

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
