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

## Sprint 2, fechamento (02/10/2026)

- **Entreguei:** o projeto dbt completo sobre o raw: 6 modelos de staging, 3 dimensões, 2 intermediários e 5 fatos
  (os horários particionados por mês), com testes de chave, `relationships` e contagem contra a fonte;
  documentação de 200 de 200 colunas (modelos e fontes), conferida contra o BigQuery por
  `scripts/verificar_docs.py`; o lineage em `docs/figuras/lineage.png`, desenhado do manifesto do dbt; e o notebook
  `notebooks/01_exploracao.ipynb`, que lê só dos marts com teto de custo (82 MB processados nas 5 consultas) e tem
  5 gráficos com as minhas conclusões. A consulta típica do ONS caiu de 37,32 para 0,74 MB processados (−98,0%).
- **Aprendi:** (1) a partição mensal é o que reduz bytes; o cluster sozinho ajuda na tabela grande e quase não soma
  por cima de partições pequenas, e o faturado fica no piso de 10 MiB, então a métrica é bytes processados.
  (2) Fuso é onde o dado engana: hora inexistente do horário de verão vira o instante da hora seguinte, e só a
  conferência contra a fonte pegou isso. (3) Conferir o texto contra os dados vale tanto quanto conferir o código:
  dos números das minhas conclusões, dez estavam errados ou imprecisos (por exemplo, a queda do racionamento é de
  26% e não 22%, e o degrau da MMGD não aparece em mai/2023). E uma comparação entre inclinações de faixas
  diferentes parecia mostrar um efeito do ano que não existe: na mesma faixa, controlar o ano muda a inclinação
  carga x temperatura em ~5%. (4) A documentação por bloco reutilizável e a checagem de completude acharam 21 colunas
  do raw que ninguém tinha declarado.
- **Travou:** a camada do notebook: a temperatura agregada só existia num intermediário, e "ler só dos marts" pedia
  promovê-la a `fct_submercado_horario` (feito, e a tabela antiga precisou ser apagada à mão). Fatos incrementais
  ficaram para a Sprint 4, junto com a janela de segurança das revisões. Seguem abertos, sem bloquear a Sprint 3:
  o tratamento do degrau de 2023 da carga (decidir antes da Sprint 5), os pesos da EPE por estado para a
  temperatura, os pisos e tetos do PLD por ano na ANEEL (testes da Sprint 3) e a unidade do consumo por ramo.

## Sprint 3, Parte B: Airflow (06/10/2026)

- **Entreguei:** o Airflow local (compose com LocalExecutor, imagem de 1,1 GB, build de 2 min 32 s) e a DAG `energia_livre_diaria`: ONS, ramos opcionais da CCEE e do INMET (só quando a pasta muda), freshness, `dbt run`, `dbt test` e `pipeline_ok`. Execução agendada completa em 6 min 40 s. Retentativas só onde a falha é transitória e alerta no Discord; a falha proposital interrompeu o pipeline (`pipeline_ok` em `upstream_failed`) e o aviso chegou com task, execução e link, ~5 min 47 s depois do início.
- **Aprendi:** (1) o BigQuery fatura no mínimo 10 MiB por job: 194 jobs do dbt deram 2,97 GB faturados para 1,56 GB processados, então os testes dominam o custo faturado (projeção de ~90 GB/mês, ~9% do 1 TB gratuito, R$ 0). (2) O gargalo da DAG continua sendo o raw do ONS, que recarrega as 938.296 linhas (77% da carga), mesmo com o bronze gravando 94% menos no GCS. (3) `dags unpause` mostra o estado anterior e, se o horário do dia já passou, cria a execução `scheduled` na hora. (4) Medições idênticas entre duas execuções não são bug quando o SQL e as tabelas são os mesmos; conferi o filtro de tempo antes de confiar.
- **Travou:** o `airflow-init` falhou por o uid 1000 não existir no passwd da imagem (resolvido usando o entrypoint da imagem). Ficaram abertos, para a Sprint 4: a revisão do ONS de 06/10 (328 valores, diferença máxima de 93,8%, sem causa investigada), o custo dos testes (agrupar, rodar menos vezes ou incremental) e o alerta do Discord sem os nomes dos testes que falharam.

## Sprint 4, Parte A: ingestão incremental (07/10/2026)

- **Entreguei:** a ingestão do ONS incremental (raw particionado por mês local, um load job por partição, janela de 3 meses
  autocorretiva com guarda de revisão, HEAD/ETag dos anos fechados), o `stg_ons__curva_carga` incremental (`insert_overwrite`
  estático, janela vinda de um ponto único), a seleção do dbt por fonte e a DAG nova (backfill pela configuração, vars do dbt
  vindas da ingestão). A DAG caiu de 6 min 40 s para 1 min 33 s (`ons_ingestao`: 4 min 22 s para 20 s), os 194 jobs do dbt
  para 36 e o faturado de 2.965,4 para 504,4 MB (-83%); o backfill de 2021 a hoje leva ~125 s e a carga full, 94 s. Tudo é
  idempotente (5.152 grupos iguais depois de duas execuções) e a produção foi migrada com backup, conferência e ensaio.
- **Aprendi:** (1) **uma ferramenta de medição também erra, e o número errado era favorável:** o medidor de bytes mostrou 10,5 MB
  para um incremental que custa 31,5 MB (o `MERGE` é filho de um `SCRIPT` e não tinha o comentário do dbt), e quase decidi o `fct`
  com isso; o spike, medido por outro caminho, já dizia 31,5. (2) **O ganho de uma otimização precisa ser decomposto:** os -7% da
  execução completa eram só -2,4% do incremental, mais cache de consultas e uma freshness fora do cenário; o que reduziu o custo
  foi rodar só o que descende da fonte que mudou. (3) **A revisão do ONS depende da idade do dado, não do mês**, e as "5 linhas de
  agosto" eram ruído de ponto flutuante (7e-12), não revisão; os 93,8% eram valor provisório do NE nos 2 a 3 últimos dias. (4)
  **O dbt não substitui uma tabela por outra com partição diferente: apaga e recria** (e o `bq cp` falha escrevendo o erro no
  stdout, o que um `>/dev/null` engoliu). (5) Uma regra de cobertura vale mais que um teste de exemplo: a partição UTC sobrescrita
  precisa ser recomposta inteira, senão o `MERGE` apaga dado, e um teste que percorre todas as janelas de 4 anos com e sem horário
  de verão a garante.
- **Travou:** a medição "agendada" do `subir` comparou a execução de 06/10 com ela mesma (+0%; corrigida: só vale execução
  criada depois do `subir`); o `grep` sem resultado derrubou o backfill sob `pipefail` (corrigido em todos os scripts); e o Docker
  fechado impediu testar o fuso na imagem (a pré-checagem do `subir` cobre). Ficaram para a Parte B e o backlog: o baseline e a validação
  temporal (4.5 e 4.6), o alerta do Discord com os nomes dos testes que falharam, a causa do NE subestimado nos últimos dias do arquivo
  e as opções A e B do piso de faturamento, que passam a valer só se o custo mensal chegar perto de 25% do gratuito.

## Sprint 4, Parte B: baseline e validação temporal (07/10/2026)

- **Entreguei:** a série mensal `fct_carga_mensal` (original e ajustada para uma definição só, com cobertura e `mes_utilizavel`) a partir de um seed gerado da API de Carga
  Verificada do ONS; o pacote `ml/` (validação por origem móvel, dois baselines, MAPE/MAE/viés/erro anual); os resultados do desenvolvimento, do estresse de 2020 e do teste final
  (rodado uma vez) em `docs/resultados/`; 6 decisões, as métricas e as fontes novas. O sazonal ingênuo erra 2,92% no desenvolvimento e 5,61% no teste final (4,30% na série ajustada);
  o viés de 2021 vai de −7,39% para −2,98% com o ajuste.
- **Aprendi:** (1) **a quebra de definição da carga era maior do que a que eu ia tratar**: o tipo III de 2021 (~6,5% da carga) é quase o dobro do degrau da MMGD de 2023 (3,3%) e só apareceu
  porque a API permitia comparar com a curva; (2) o **perfil horário separa mudança de definição de crescimento real** (o salto está no meio-dia, não na madrugada); (3) a documentação diz
  29/04/2023 e o dado diz 01/05; (4) **um teste que falha pode estar certo sobre o sintoma e errado sobre a causa**: os 81 "meses incompletos" eram 80 fevereiros por causa do horário de verão
  e 1 lacuna real, e a lição foi separar "o mês não terminou" de "o mês tem cobertura menor"; (5) uma regra "1 mês de sorte dentro do ruído encerra" dependia de 13 MWmed, e 2 meses seguidos a
  estabilizou; (6) mutação em teste: entregar a série inteira aos baselines **não** vaza (eles só olham para trás), então a defesa que conta é a visão cortada; (7) escolhi o limiar de cobertura
  medindo o viés de dias faltantes, não por intuição.
- **Travou:** o `set -e` do script derrubou a reconciliação no primeiro teste que falhou (agora o script roda tudo e sai com o código dos testes); a CTE `dentro` colidiu com a coluna `dentro` no
  BigQuery; e o `git status` do meta contava os próprios resultados (corrigido; o do teste final não foi regravado de propósito). Ficou para a Sprint 5: o histórico anterior a 2018, os outliers
  no treino, a anomalia de out/2021 e a verificação com o ONS de uma segunda fase da MMGD.

