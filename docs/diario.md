# Diário

Três linhas por sprint (ou por bloco de tarefas): o que entreguei, o que aprendi, o que travou.

## Sprint 1, tarefas 1.1 a 1.4 (02/10/2026)

- **Entreguei:** estrutura de pastas da seção 9, ambiente Python com uv (3.12), `pyproject.toml`,
  ruff e pytest funcionando, LICENSE MIT, GCP configurado (orçamento, cota, bucket, datasets) e a
  exploração das quatro fontes: `docs/fontes.md`, `scripts/explorar_fontes.py` e
  `scripts/inmet_cmp.py`, mais 6 decisões novas em `docs/decisoes.md`.
- **Aprendi:** os dados abertos têm armadilhas que só aparecem olhando o dado, não a
  documentação: o layout do PLD da CCEE muda entre 2024 e 2025 (aspas, quebra de linha, zeros à
  esquerda), em 2022–2024 a maior parte das horas do PLD ficou no piso (até 98,3% em 2023), o
  consumo por ramo da CCEE é mensal e não horário, e a completude das estações do INMET varia
  de 0% a 100% de nulos e muda de um ano para o outro. Também aprendi a decidir fuso horário
  (UTC no staging, com `America/Sao_Paulo`) e a medir antes de concluir (por exemplo, escolher
  estações por completude e não por cidade).
- **Travou:** o portal da CCEE bloqueia downloads e a API por script (403), e a conexão ao INMET
  caiu no teste; baixei esses arquivos à mão e deixei a automação para a 1.7 e a 1.8, sem
  tentar burlar o bloqueio. Ficaram pendentes: fuso do ONS (dicionário de dados), piso e
  teto do PLD por ano (ANEEL), unidade do consumo por ramo e os pesos por estado da
  temperatura.

## Sprint 1, fechamento (02/10/2026)

- **Entreguei:** as quatro fontes no BigQuery `raw` mais os feriados (6 tabelas, 2,99 milhões de
  linhas, 584 MB no bronze do GCS), com extratores (`ingestion/ons.py`, `ccee.py`, `inmet.py`,
  `feriados.py`) sobre um módulo comum (`ingestion/common/`: GCS e BigQuery por ADC, retry,
  validação pós-carga, proteção de custo com `maximum_bytes_billed`), 111 testes sem rede,
  `docs/fontes.md`, `docs/premissas.md`, 14 decisões em `docs/decisoes.md` e o "antes" medido: carga
  full de 9,3 min e três consultas típicas (37,3 MB, 5,4 MB e 58,3 MB processados).
- **Aprendi:** (1) o custo da carga no BigQuery é por job, não por MB: cerca de 6,4 s fixos mais 34 s
  por milhão de linhas, e o INMET em blocos de ~43 MB carregou o dobro de linhas do ONS em 37% menos
  tempo; isso aponta o desenho do incremental da Sprint 4. (2) Tabelas pequenas esbarram no
  mínimo faturado de 10 MiB, então para elas se compara bytes processados e não faturados. (3) As
  fontes mudam por baixo: a carga do ONS passou a incluir a MMGD em 29/04/2023 (a página da curva
  horária não conta, a da carga diária sim), o ONS grava em horário local com horário de verão até
  2018, e o arquivo do ano corrente mudou em 75 minutos. (4) Um critério de seleção olha para trás:
  a lista de estações caiu de 72 para 37 ao passar de 2 para 5 anos, e 10 das 37 já degradaram em
  2026. (5) Validar contra a fonte (contar linhas e vazios por arquivo) deu confiança para
  refatorar: até os 69 bytes de diferença do ONS foram explicados, reproduzindo o número do BigQuery.
- **Travou:** o portal da CCEE bloqueia scripts e o do INMET não respondeu na minha rede, então esses
  arquivos entram por download manual (sem contornar bloqueio); a carga é full e sobrescreve o
  bronze, então não dá para ver o que o ONS revisou. Ficam abertas, sem bloquear a Sprint 2: o
  tratamento do degrau de 2023 da carga do ONS (decidir antes da Sprint 5), os pesos por estado
  da temperatura (fonte da EPE), o piso e o teto do PLD por ano na ANEEL (testes da Sprint 3) e o
  fuso do ONS no dicionário de dados.

