# Registro de métricas

Nunca otimizar antes de medir a versão simples. Preencher "Antes" na versão ingênua e "Depois" após a melhoria.

| Nível | Métrica | Antes (versão simples) | Depois | Fase |
|---|---|---|---|---|
| Negócio | Custo anual de energia do consumidor-exemplo (backtest) | estratégia ingênua: R$ __ | estratégia otimizada: R$ __ | 6 |
| Negócio | Economia | — | R$ __ / __% | 6 |
| Negócio | Exposição ao PLD (MWh descobertos ou sobrando) | __ | __ | 6 |
| Ciência | MAPE mensal da previsão de carga (12 meses à frente, rolling origin) | baseline: __% | modelo: __% | 5 |
| Engenharia | Dados lidos por consulta típica | 0,037 GB (ONS, raw STRING sem partição: 37,3 MB processados; 37,7 MB faturados) | passo intermediário (tipado, sem partição): **0,018 GB** (18,3 MB processados; 18,9 MB faturados); particionado e clusterizado: __ GB (tarefa 2.6) | 1 → 2 |
| Engenharia | Tempo de carga diária | full: **9,3 min** (ONS 4,9 + CCEE 1,2 + INMET 3,1 + feriados 0,2; sem o tempo do download manual) | incremental: __ min | 1 → 4 |
| Engenharia | Tempo do backfill completo (2021–hoje) | — | __ min | 4 |
| Engenharia | Problemas de dados capturados pelos testes | — | __ registros (tipos: __) | 3 |
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

