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
- [ ] 2.2 Modelos de staging: tipos, nomes padronizados, **tudo em UTC**, deduplicação.
- [ ] 2.3 `dim_tempo` (hora, dia da semana, feriado, estação, horário de ponta), `dim_submercado`, `dim_fonte`.
- [ ] 2.4 Modelos intermediate: carga + PLD + temperatura na mesma granularidade horária.
- [ ] 2.5 Fatos: `fct_carga_horaria`, `fct_pld_horario`, `fct_clima_horario` (e `fct_reservatorios_diario` se der tempo).
- [ ] 2.6 Particionar por data e clusterizar por submercado; fatos grandes como modelos incrementais. Medir a consulta típica em **três pontos**: raw (STRING, sem partição), a mesma tabela tipada sem partição e a tabela particionada e clusterizada, para separar o efeito da tipagem do efeito da partição (ver `docs/decisoes.md`).
- [ ] 2.7 Descrever modelos e colunas no YAML e gerar `dbt docs`.
- [ ] 2.8 Primeira análise exploratória em notebook: sazonalidade da carga, relação carga x temperatura, comportamento do PLD.

**Medir (o "depois")**
- Dados lidos pela mesma consulta típica da Sprint 1, agora no mart particionado e também no passo intermediário (tipado, sem partição).
- Tempo de `dbt run`.

**Decisão a registrar:** como tratar fuso horário e horário de verão; granularidade dos fatos.

**Pronto quando:** `dbt run` gera todos os marts sem erro e a comparação de bytes lidos está em `docs/metricas.md`.

**Estudar:** modelagem dimensional (fato, dimensão, granularidade) e materializações do dbt (view, table, incremental).

---

## Sprint 3 — Qualidade de dados e Airflow

**Objetivo:** o pipeline detecta dado ruim sozinho e passa a rodar orquestrado.

**Tarefas**
- [ ] 3.1 Testes genéricos do dbt: `not_null`, `unique`, `relationships` nas chaves.
- [ ] 3.2 Testes de faixa: PLD entre piso e teto do ano, carga positiva, temperatura plausível.
- [ ] 3.3 Freshness nas sources.
- [ ] 3.4 Investigar revisões retroativas do ONS/CCEE e implementar upsert por chave natural.
- [ ] 3.5 Subir Airflow com docker-compose.
- [ ] 3.6 Primeira DAG: extrair → carregar → `dbt run` → `dbt test`, rodando diariamente.
- [ ] 3.7 Retentativas e alerta de falha (e-mail ou webhook do Discord).

**Medir**
- Quantos registros problemáticos os testes encontraram e de que tipo.
- Quantas revisões retroativas apareceram no histórico.

**Decisão a registrar:** estratégia para revisões retroativas.

**Pronto quando:** a DAG roda de ponta a ponta no Airflow e um teste que falha interrompe o pipeline e avisa.

**Estudar:** conceitos do Airflow (DAG, task, operator, schedule, retries) e testes no dbt.

---

## Sprint 4 — Ingestão incremental e baseline de previsão

**Objetivo:** pipeline eficiente e confiável + primeira previsão para servir de comparação.

**Tarefas**
- [ ] 4.1 Converter os extratores para incremental: buscar só o período novo (com uma janela de segurança para revisões).
- [ ] 4.2 Garantir idempotência: reexecutar o mesmo dia não duplica nada.
- [ ] 4.3 Backfill parametrizado por intervalo de datas.
- [ ] 4.4 Testes Python (pytest) para as funções de ingestão.
- [ ] 4.5 Baseline ingênuo: mesmo mês do ano anterior (carga mensal do SE/CO, 12 meses à frente).
- [ ] 4.6 Definir a validação temporal que todos os modelos vão usar: rolling origin mensal, horizonte de 12 meses, sempre só com informação anterior ao início de cada ano de decisão.

**Medir**
- Tempo da carga incremental vs. full da Sprint 1.
- Tempo do backfill completo (2021 até hoje).
- Idempotência: rodar duas vezes e comparar contagens.
- MAPE mensal do baseline no rolling origin (2021–2025).

**Decisão a registrar:** tamanho da janela de segurança na carga incremental.

**Pronto quando:** a DAG diária roda incremental, o backfill funciona e o baseline tem erro medido.

**Estudar:** idempotência, upsert/MERGE no BigQuery e validação de séries temporais.

---

## Sprint 5 — Modelo de previsão e cenários

**Objetivo:** previsão melhor que o baseline e a base da otimização pronta.

**Tarefas**
- [ ] 5.1 Features mensais: tendência, calendário (dias úteis, feriados, dias do mês) e defasagens de pelo menos 12 meses. Tratar os outliers de 2001–2002 (racionamento) e 2020 (pandemia) e registrar a escolha.
- [ ] 5.2 Treinar uma regressão linear regularizada (o "antes") e o LightGBM como desafiante, com a mesma validação em rolling origin.
- [ ] 5.3 Análise de erros: onde o modelo erra mais (meses atípicos, ondas de calor com a temperatura do INMET).
- [ ] 5.4 Gravar previsões mensais no BigQuery (`fct_previsao_carga`) com versão do modelo; adicionar a etapa na DAG.
- [ ] 5.5 Construir a curva de consumo do consumidor-exemplo: `k × carga média diária do SE/CO × perfil de loja` (conforme `docs/premissas.md`).
- [ ] 5.6 Gerador de cenários de consumo (a partir da distribuição do erro mensal do rolling origin, sem usar dados futuros).
- [ ] 5.7 Gerador de cenários de PLD (a partir do histórico, por reamostragem).
- [ ] 5.8 (Extra opcional) Previsão horária D+1 com LightGBM.

**Medir**
- MAPE mensal do modelo linear e do LightGBM vs. baseline, no mesmo rolling origin.
- Erro em meses atípicos e em ondas de calor.

**Decisão a registrar:** tratamento dos outliers 2001–2002 e 2020; como os cenários de PLD são gerados e por quê.

**Pronto quando:** o modelo supera o baseline no mesmo teste, as previsões mensais entram no pipeline e os cenários estão gerados.

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
2. `fct_reservatorios_diario` e geração por fonte.
3. Agregação da temperatura do INMET com pesos de consumo por estado (usar média simples entre estados).
4. Página "panorama do setor" do dashboard.
5. Análise de sensibilidade.

**Nunca cortar:** medições do "antes", testes de qualidade, idempotência, backtest e README com resultados.