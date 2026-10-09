# Sprints: Plataforma de Dados do Mercado Livre de Energia

Complemento do arquivo `planejamento-projeto-energia.md`. As fases do planejamento viraram 7 sprints. Cada sprint só começa quando a anterior está pronta.

| Sprint | Foco | Fases |
|---|---|---|
| 1 | Setup + ingestão ingênua | 0 e 1 |
| 2 | Modelagem com dbt | 2 |
| 3 | Qualidade de dados + Airflow | 3 e início da 4 |
| 4 | Ingestão incremental + baseline de previsão | fim da 4 e início da 5 |
| 5 | Modelo de previsão + cenários | fim da 5 e início da 6 |
| 6 | Backtest + dashboard | fim da 6 e 7 |
| 7 | Polimento e apresentação | 8 |

Se o ritmo apertar, a sprint leva mais tempo; não corte as medições.

---

## Rotina de cada sprint

- **Planejamento (início, 15 min):** criar uma issue no GitHub para cada tarefa da sprint e colocar no quadro (GitHub Projects: A fazer → Fazendo → Feito).
- **Desenvolvimento:** uma branch por tarefa, pull request para a `main`, mesmo trabalhando sozinho. Isso mostra fluxo profissional no histórico do repositório. Commits feitos sempre por mim, nunca pelo Claude Code.
- **Check (meio da sprint, 5 min):** o que foi feito, o que travou, se o objetivo da sprint ainda é realista.
- **Revisão (fim, 20 min):**
  - Atualizar `docs/metricas.md` com os números da sprint.
  - Registrar decisões em `docs/decisoes.md`.
  - Escrever 3 linhas em `docs/diario.md`: o que entreguei, o que aprendi, o que travou.
  - Mover o que não terminou para a próxima sprint.

Ao abrir uma conversa com o Claude, diga a sprint e a tarefa (ex.: "Sprint 1, tarefa 1.6").

---

## Sprint 1 — Setup e ingestão ingênua

**Objetivo:** ter dados reais de 2021 em diante no BigQuery, carregados da forma mais simples possível, e o "antes" medido.

**Tarefas**
- [x] 1.1 Criar repositório `energia-livre-dados` com a estrutura de pastas do planejamento, `.gitignore`, `README.md` inicial e licença.
- [x] 1.2 Configurar ambiente Python (uv), `pyproject.toml`, ruff para lint.
- [x] 1.3 Criar projeto no GCP, **alerta de orçamento**, bucket no GCS, datasets `raw`, `staging`, `marts` no BigQuery (região us-central1) e autenticação local sem arquivo de chave.
- [x] 1.4 Explorar os portais: baixar uma amostra de cada fonte (carga horária ONS, PLD horário CCEE, consumo por ramo CCEE, temperatura INMET). Anotar formato, granularidade, período e frequência em `docs/fontes.md`.
- [x] 1.5 Escrever `docs/premissas.md`: consumidor-exemplo, como será a curva de consumo e as regras simplificadas de contrato.
- [x] 1.6 Extrator ONS (carga horária): baixar tudo **desde 2000** (a previsão mensal precisa do histórico longo) → GCS → BigQuery `raw`.
- [x] 1.7 Extrator CCEE (PLD horário 2021 em diante, o arquivo semanal 2001–2020, de onde vem o preço de contrato de 2021, e o consumo por ramo de atividade de 2024 em diante), mesmo fluxo. O portal bloqueia downloads automáticos: histórico por download manual, atualização automática a testar.
- [x] 1.8 Extrator INMET (temperatura, 2021 em diante) para as estações que passam no critério de 95% (ver `docs/fontes.md`) + tabela de feriados desde 2000.
- [x] 1.9 Módulo `ingestion/common/` com cliente GCS/BigQuery e logging reaproveitáveis.
- [x] 1.10 Perfilar o arquivo PLD 2001–2020 (granularidade, ponderação por horas de 2020) e checar a série do ONS 2000–2025 (quebras na definição da carga, layout, fuso).

**Medir (o "antes")**
- Tempo da carga full de cada fonte (o ONS inclui 2000 em diante).
- Volume baixado.
- Dados lidos por uma consulta típica (ex.: carga média por hora do SE/CO em 2024), com tabela sem partição.

**Decisões a registrar:** região do GCP; autenticação sem chave; formato do bruto no GCS (CSV original vs. Parquet) e organização das pastas.

**Pronto quando:** as quatro fontes estão no BigQuery `raw` e a primeira linha de `docs/metricas.md` está preenchida.

**Estudar:** fundamentos de BigQuery (particionamento, custo por bytes lidos) e o glossário básico do setor (carga, PLD, submercado, MWm).

---

## Sprint 2 — Modelagem com dbt

**Objetivo:** transformar o bruto num modelo dimensional limpo, particionado e documentado.

**Tarefas**
- [x] 2.1 Instalar dbt-bigquery, configurar `profiles.yml` e `sources.yml` apontando para `raw`.
- [x] 2.2 Modelos de staging: tipos, nomes padronizados, **tudo em UTC**, deduplicação.
- [x] 2.3 `dim_tempo` (uma linha por hora UTC de 2000 a 2030, com hora local, feriado, tipo de dia, estação do ano e horário de ponta), `dim_submercado` e `dim_estacao` (as 37 estações do INMET, com o registro mais recente). A `dim_fonte` fica fora: depende da geração por fonte, que foi adiada.
- [x] 2.4 Modelos intermediate: a temperatura em dois passos (`int_clima_estado_horario`: média das estações por estado e hora, com imputação de até 3 h; `int_clima_submercado_horario`: média **simples** entre os estados, provisória até existirem os pesos da EPE) e a junção de carga, PLD e temperatura na mesma hora (`int_submercado_horario`, promovido a mart `fct_submercado_horario` na 2.8).
- [x] 2.5 Fatos, no dataset `marts`: `fct_carga_horaria`, `fct_pld_horario`, `fct_clima_horario` (grão estação x hora) e `fct_pld_semanal` (o PLD de 2001 a 2020, que dá o preço de contrato de 2021); `fct_reservatorios_diario` fica fora (item de corte). Testes de chave, `not_null` e `relationships` com as dimensões.
- [x] 2.6 Particionar os fatos horários **por mês** em `instante_utc` e clusterizar por submercado (clima: por UF e estação). **Os fatos incrementais ficam para a Sprint 4** (junto com a janela de segurança das revisões). Medir a consulta típica em **três pontos**: raw (STRING), tipada sem partição e fato particionado e clusterizado, comparando **bytes processados** (o faturado fica no piso de 10 MiB nesse volume), e um experimento que isola o efeito da partição do efeito do cluster.
- [x] 2.7 Descrever modelos e colunas no YAML e gerar `dbt docs`.
- [x] 2.8 Primeira análise exploratória em notebook: sazonalidade da carga, relação carga x temperatura, comportamento do PLD.

**Medir (o "depois")**
- Bytes **processados** pela mesma consulta típica da Sprint 1 nos três pontos (raw, tipado sem partição e fato particionado e clusterizado). O faturado fica no piso de 10 MiB, então o processado é a métrica de comparação.
- Tempo de `dbt run`.

**Decisão a registrar:** como tratar fuso horário e horário de verão; granularidade dos fatos; granularidade da partição (mensal) e adiamento dos fatos incrementais para a Sprint 4.

**Pronto quando:** `dbt run` gera todos os marts sem erro e a comparação de bytes lidos está em `docs/metricas.md`.

**Estudar:** modelagem dimensional (fato, dimensão, granularidade) e materializações do dbt (view, table, incremental).

---

## Sprint 3 — Qualidade de dados e Airflow

**Objetivo:** o pipeline detecta dado ruim sozinho e passa a rodar orquestrado.

**Tarefas**
- [x] 3.1 Testes genéricos do dbt: `not_null`, `unique`, `relationships` nas chaves.
- [x] 3.2 Testes de faixa: PLD entre piso e teto horário do ano (seed `pld_limites`), carga positiva (com exceções conhecidas), temperatura plausível e completude do INMET (warn).
- [x] 3.3 Freshness nas sources, pela data do conteúdo (fontes manuais só avisam).
- [x] 3.4 Investigar revisões retroativas do ONS: gravar o bronze só quando o hash mudar (versões em pasta separada), detectar e medir as revisões. O upsert pela chave natural e a carga incremental ficam na 4.1 e 4.2.
- [x] 3.5 Subir Airflow com docker-compose.
- [x] 3.6 Primeira DAG: extrair → carregar → `dbt run` → `dbt test`, rodando diariamente.
- [x] 3.7 Retentativas e alerta de falha (e-mail ou webhook do Discord).

**Backlog (registrado ao fechar a Parte B, não implementado):**
- Alerta do Discord: hoje mostra só "Bash command failed"; melhorar para incluir os nomes dos testes do dbt que falharam.
- Sprint 4: investigar a revisão do ONS de 06/10/2026 (328 valores, diferença máxima de 93,8%) e o custo faturado dos testes do dbt (`decisoes.md`, "Piso de faturamento"). **Feito na Sprint 4, Parte A:** a revisão de 93,8% é valor provisório do NE substituído (a causa dentro do ONS segue no backlog) e o custo dos testes foi revisitado (opções A e B só se o custo mensal chegar perto de 25% do gratuito).

**Medir**
- Quantos registros problemáticos os testes encontraram e de que tipo.
- Quantas revisões retroativas apareceram no histórico.

**Decisão a registrar:** estratégia para revisões retroativas (bronze por hash, versões em pasta separada).

**Pronto quando:** a DAG roda de ponta a ponta no Airflow e um teste que falha interrompe o pipeline e avisa.

**Estudar:** conceitos do Airflow (DAG, task, operator, schedule, retries) e testes no dbt.

---

## Sprint 4 — Ingestão incremental e baseline de previsão

**Objetivo:** pipeline eficiente e confiável + primeira previsão para servir de comparação.

**Tarefas**
- [x] 4.1 Converter os extratores para incremental: buscar só o período novo (com uma janela de segurança para revisões). Converter também os fatos grandes do dbt para incrementais (`microbatch` por mês, com a mesma janela). **Feito:** janela de 3 meses com guarda e autocorreção; raw particionado por mês e um load job por partição; staging do ONS incremental (`insert_overwrite` estático, não `microbatch`); o `fct_carga_horaria` ficou `table` porque o incremental faturava mais (31,5 contra 26,2 MB). Seleção do dbt por fonte e DAG nova.
- [x] 4.2 Garantir idempotência: reexecutar o mesmo dia não duplica nada. **Feito:** janela do dia 2 vezes (ingestão + dbt) dá 5.152 grupos iguais, 0 diferenças.
- [x] 4.3 Backfill parametrizado por intervalo de datas. **Feito:** `--desde/--ate AAAA-MM` na ingestão e `{"desde","ate"}` na configuração da DAG; 2021 a hoje em ~125 s.
- [x] 4.4 Testes Python (pytest) para as funções de ingestão. **Feito:** janela (todas as bordas e a virada de ano), partições, idempotência da lógica, HEAD/ETag, guarda, conf da DAG, macros do dbt e a DAG executada com um Airflow de mentira.
- [x] 4.5 Baseline ingênuo: mesmo mês do ano anterior (carga mensal do SE/CO, 12 meses à frente). **Feito:** `ml/baselines.py` com o sazonal ingênuo e o sazonal × crescimento de 12 meses; série mensal `fct_carga_mensal` (original e ajustada para uma definição só, com cobertura e `mes_utilizavel`); degrau da MMGD (01/05/2023) e do tipo III (01/03/2021) medidos pela API de Carga Verificada. Sazonal ingênuo: MAPE 2,92% no desenvolvimento (2012–2019) e 5,61% no teste final (2021–2025), 4,30% na série ajustada.
- [x] 4.6 Definir a validação temporal que todos os modelos vão usar: rolling origin mensal, horizonte de 12 meses, sempre só com informação anterior ao início de cada ano de decisão. **Feito:** `ml/validacao.py` (origem móvel, janela crescente, horizontes de 1 a 12, desenvolvimento 2012–2019, estresse 2020, teste final 2021–2025 usado uma vez), `ml/metricas.py` (MAPE, MAE, viés com sinal, erro anual e recorte da origem de dezembro) e `ml/avaliar.py`; resultados em `docs/resultados/`; testes de ausência de vazamento.

**Medir**
- Tempo da carga incremental vs. full da Sprint 1.
- Tempo do backfill completo (2021 até hoje).
- Idempotência: rodar duas vezes e comparar contagens.
- MAPE mensal do baseline no rolling origin (2021–2025). **Medido:** 5,61% (sazonal ingênuo, série original) e 4,30% (série ajustada); desenvolvimento 2012–2019: 2,92% (`docs/metricas.md`).

**Decisão a registrar:** tamanho da janela de segurança na carga incremental.

**Pronto quando:** a DAG diária roda incremental, o backfill funciona e o baseline tem erro medido.

**Concluída em 07/10/2026: Parte A (4.1 a 4.4, ingestão incremental) e Parte B (4.5 e 4.6, baseline e validação temporal).** Resultados em `docs/metricas.md` ("Sprint 4, Parte A" e "Sprint 4, Parte B"); decisões em `docs/decisoes.md`; resultados dos baselines em `docs/resultados/`.

**Backlog (registrado ao fechar a Parte A, não implementado):**
- Alerta do Discord: hoje mostra só "Bash command failed"; melhorar para incluir os nomes dos testes do dbt que falharam.
- Investigar a CAUSA, dentro do ONS, da revisão de 06/10 (o NE vem subestimado nos 2 a 3 últimos dias do arquivo e é preenchido depois; os dados mostram o quê, não o porquê).
- Opções A (agrupar testes) e B (testes pesados com menos frequência) do piso de faturamento: só se o custo mensal chegar perto de ~25% do 1 TB gratuito ou o número de testes dobrar (hoje 1,6%).
- Reavaliar o `fct_carga_horaria` incremental quando a reconstrução completa passar de ~31,5 MB faturados (o fato cresce ~3,7% ao ano: não antes de ~5 anos).
- Agendar a execução completa do dbt (`execucao_completa`) para rodar os 62 testes que nenhuma fonte seleciona (47 até a Sprint 4, Parte A; +15 do seed `ajuste_definicao_carga` na Parte B).
- Apagar `raw.ons_curva_carga_backup` e o dataset `verificacao_incremental` (os comandos foram passados no fechamento da Parte A).

**Backlog (registrado ao fechar a Parte B, não implementado):**
- Sprint 5: decidir o tratamento do histórico anterior a 2018, onde o tipo III não é medido (a série ajustada começa em 2018-01; `premissas.md`, pendência 16).
- Sprint 5: tratamento dos outliers de 2001–2002 e 2020 no treino; o teste final de 2021–2025 já foi usado, então a confirmação do modelo escolhido roda uma vez.
- Verificar com o ONS a anomalia de out/2021 no SE/CO (+972 MWmed da API acima da curva, sem causa conhecida) e se houve uma segunda fase da MMGD depois de mai/2023 (o fator `r` varia de 0,69 a 0,99).
- Se o ONS revisar a API, refazer o seed (`python -m scripts.baixar_mmgd_ons`, depois `bash scripts/passo2_carga_mensal.sh`).

**Estudar:** idempotência, upsert/MERGE no BigQuery e validação de séries temporais.

---

## Sprint 5 — Modelo de previsão e cenários

**Objetivo:** previsão melhor que o baseline e a base da otimização pronta.

**Tarefas**
- [x] 5.1 Features mensais: tendência, calendário (dias úteis, feriados, dias do mês) e defasagens de pelo menos 12 meses. Tratar os outliers de 2001–2002 (racionamento) e 2020 (pandemia) e registrar a escolha. **Feito:** `ml/features.py` (dias úteis efetivos, descontando Carnaval e Corpus Christi), `ml/preparo.py` (janela móvel de 72 meses, que deixa 2001–2002 de fora, e imputação dos meses de choque da COVID por uma regra de 2σ), tipo III de 2015–2017 reconstruído no dbt. As defasagens de 12 meses entram só no LightGBM (a sazonalidade do ETS, do SARIMA e da regressão vem da própria estrutura).
- [x] 5.2 Treinar uma regressão linear regularizada (o "antes") e o LightGBM como desafiante, com a mesma validação em rolling origin. **Feito:** além deles, ETS, SARIMA e duas médias, numa grade fechada e num critério definido antes de rodar. Desenvolvimento: média ETS+SARIMA+regressão 2,66% contra 2,92% do ingênuo (a regressão sozinha 3,04%, o LightGBM 3,45%); teste final (uma vez): 3,11% contra 4,17% na série ajustada, com as ressalvas de `docs/metricas.md`.
- [x] 5.3 Análise de erros: onde o modelo erra mais (meses atípicos, ondas de calor com a temperatura do INMET). **Feito:** por mês-calendário, ano e horizonte; o erro cai 3,7 pp por °C de anomalia de temperatura (R² 0,57, 60 meses); out/2021 (+8,3%) ainda sem explicação; intervalos com cobertura de 70% e 88%.
- [x] 5.4 Gravar previsões mensais no BigQuery (`fct_previsao_carga`) com versão do modelo; adicionar a etapa na DAG. **Feito no código e nos testes:** `ml/previsao.py`, as tabelas `fct_previsao_carga` e `fct_erro_previsao_carga` (MERGE idempotente, proveniência em toda linha) e a task mensal com ShortCircuit na DAG. **Validado na nuvem em 08/10/2026** com `scripts/passo_sprint5_c.sh` (`local`, `dag` e `dag-gerar`): 15 conferências das tabelas sem falha, DAG em 1 min 54 s com a `previsao_mensal` em 22 s, execução normal sem mês novo (`previsao_mensal` `skipped`) e com falha proposital (`upstream_failed` e um único alerta no Discord).
- [x] 5.5 Construir a curva de consumo do consumidor-exemplo: `k × carga média diária do SE/CO × perfil de loja` (conforme `docs/premissas.md`).
- [x] 5.6 Gerador de cenários de consumo (a partir da distribuição do erro mensal do rolling origin, sem usar dados futuros). **Feito no código e nos testes** (`ml/cenarios_consumo.py`, `scripts/avaliar_cenarios_consumo.py`); as tabelas aguardam a escolha de N.
- [ ] 5.7 Gerador de cenários de PLD (a partir do histórico, por reamostragem). **Feito no código e nos testes** (`ml/cenarios_pld.py`, `ml/cenarios.py`, `ml/piso_pld.py`, seed `pld_piso_excecoes`); as tabelas aguardam a execução (`python -m ml.cenarios gerar --n 2000`).
- [ ] 5.8 (Extra opcional) Previsão horária D+1 com LightGBM.

**Medir**
- MAPE mensal do modelo linear e do LightGBM vs. baseline, no mesmo rolling origin.
- Erro em meses atípicos e em ondas de calor.

**Decisão a registrar:** tratamento dos outliers 2001–2002 e 2020; como os cenários de PLD são gerados e por quê.

**Pronto quando:** o modelo supera o baseline no mesmo teste, as previsões mensais entram no pipeline e os cenários estão gerados.

**Backlog (registrado ao concluir as tarefas 5.1 a 5.4, não implementado):**
- Mart mensal só no fechamento do mês: o `fct_carga_mensal` e os ~26 testes dele rodam todo dia na seleção do ONS e respondem por boa parte do aumento de custo da Sprint 5 (27 jobs novos × 10 MiB ≈ 283 MB faturados por dia, ~8,5 GB por mês dos ~28 GB estimados). Reconstruí-lo só quando fecha um mês (ou toda semana) corta isso; o preço é o mês corrente ficar defasado e a revisão do ONS só aparecer no rebuild. Decidir junto com o dashboard (Sprint 6).
- Sensibilidade do SARIMA: 1e-10 de ruído na entrada mudou mais de 0,01% em 4,1% das previsões do SARIMA no desenvolvimento (8 das 107 origens, máximo 0,32%); o otimizador (L-BFGS com gradiente numérico) para em pontos diferentes numa verossimilhança plana. O arredondamento a 1 kW garante a reprodutibilidade, mas não a robustez. Opções: apertar a tolerância ou aumentar as iterações, começar do ajuste anterior, ou fixar os parâmetros. Mudar isso muda o modelo avaliado: seria uma versão nova (`v2`) com o desenvolvimento refeito.
- MERGE dos cenários lê o destino inteiro: `fct_cenario_consumo`, `fct_cenario_pld` e `fct_cenario_execucao` não têm partição, e o MERGE de cada execução processa a temporária mais a tabela-destino (confirmado em `INFORMATION_SCHEMA.JOBS_BY_PROJECT`: 20,30 MB na 1ª execução e 40,61 MB na 2ª, só no PLD; o piso de 10 MiB por tabela esconde o resto). Particionar/clusterizar por `origem` e filtrar a `origem` no `ON` do MERGE. O custo cresce com o histórico gravado (cada `execucao_id` novo acrescenta ~30 MB). Não implementado. Se os cenários entrarem na DAG, só atrás da `previsao_ha_mes_novo` (`docs/metricas.md`).
- Alerta do Discord com os nomes dos testes: a mensagem traz a task e o erro, mas não quais testes do dbt falharam; incluir os nomes (do `run_results.json` do dbt) dentro do limite de 1.900 caracteres.

**Estudar:** regressão regularizada e rolling origin para séries mensais, LightGBM como desafiante e noções de otimização sob incerteza (custo esperado, CVaR).

---

## Sprint 6 — Backtest e dashboard

**Objetivo:** produzir a métrica principal do projeto e mostrá-la.

**Tarefas**
- [ ] 6.1 Modelo de custo do contrato: volume em MWm, contrato modulado pela carga, banda de flexibilidade, liquidação da diferença pelo PLD ponderado pelo consumo e preço `P_t` = PLD médio do ano anterior + spread.
- [ ] 6.2 Otimização: volume que minimiza custo esperado + λ × CVaR95 sobre os cenários, com `V` limitado a `[1/(1+f), 120%]` do consumo previsto (λ = 0,5; o limite inferior vem da regra de lastro, ver `docs/premissas.md`, seção 4).
- [ ] 6.3 Backtest 2021–2025 comparando as três estratégias (ingênua, previsão pontual, otimizada). 2021–2023 são contrafactuais.
- [ ] 6.4 Análise de sensibilidade: spread do preço (0/20/40), λ (0/0,5/1) e banda de flexibilidade (±5%/±15%).
- [ ] 6.5 Gravar resultados em `fct_recomendacao_contrato`.
- [ ] 6.6 Dashboard (Streamlit): panorama do setor, previsão, decisão de contrato e saúde do pipeline.
- [ ] 6.7 Publicar o dashboard (ex.: Streamlit Community Cloud).
- [ ] 6.8 Na página "Decisão de contrato": acompanhamento diário do contrato vigente (consumo acumulado contra a banda, exposição estimada em R$ até o fim do ano e alerta de mês saindo da banda).

**Medir (métrica principal)** — relatório definido antes de ver os resultados
- Custo total ano a ano de cada estratégia, economia contra a ingênua em R$ e em %.
- Pior ano, CVaR95 do custo e exposição ao PLD (MWh descobertos ou sobrando) por estratégia.
- Reportar mesmo que a economia seja pequena ou negativa, e ler ano a ano.

**Decisão a registrar:** medida de risco (CVaR95, λ) e regra do preço de contrato (spread). O limite inferior de `V` pela regra de lastro já está decidido (a penalidade fica como extra).

**Pronto quando:** a tabela do backtest está em `docs/metricas.md` e o dashboard está no ar.

**Estudar:** regras básicas de contratação no ACL (flexibilidade, sazonalização, lastro e penalidade por insuficiência) para defender as simplificações.

---

## Sprint 7 — Polimento e apresentação

**Objetivo:** projeto pronto para mandar a recrutador.

**Tarefas**
- [ ] 7.1 `docker-compose up` sobe tudo; testar numa máquina ou ambiente limpo.
- [ ] 7.2 GitHub Actions: lint, pytest e `dbt test` a cada push.
- [ ] 7.3 Diagrama de arquitetura (`docs/arquitetura.png`).
- [ ] 7.4 README final com resultados no topo (estrutura da seção 11 do planejamento).
- [ ] 7.5 Revisar `docs/decisoes.md` (mínimo de 4 decisões bem escritas).
- [ ] 7.6 Gravar vídeo de 2 minutos: problema, arquitetura, resultado.
- [ ] 7.7 Escrever as linhas do currículo com os números reais.
- [ ] 7.8 Ensaiar 3 histórias de entrevista (problema → decisão → resultado) a partir das decisões registradas.
- [ ] 7.9 (Opcional) Terraform para a infraestrutura.

**Pronto quando:** todos os itens da "Definição de pronto" do planejamento estão marcados.

---

## Se atrasar

Ordem do que cortar primeiro, sem prejudicar o essencial:
1. Terraform.
2. `fct_reservatorios_diario`, geração por fonte e a `dim_fonte`.
3. Agregação da temperatura do INMET com pesos de consumo por estado (usar média simples entre estados).
4. Página "panorama do setor" do dashboard.
5. Análise de sensibilidade.

**Nunca cortar:** medições do "antes", testes de qualidade, idempotência, backtest e README com resultados.