# Plataforma de Dados do Mercado Livre de Energia

Planejamento completo do projeto de portfólio de Felipe Balzani (Sistemas de Informação, UNICAMP FT Limeira).
Objetivo final: conseguir estágio em engenharia de dados ou vaga de engenheiro de dados júnior.

---

## 0. Contexto para o Claude neste projeto

- Este é um projeto de portfólio para vagas de **estágio em engenharia de dados / engenheiro de dados júnior**, com uma camada de ciência de dados por cima.
- O foco não é só construir: é **medir impacto** (sempre antes vs. depois, sempre contra um baseline) e registrar decisões para contar em entrevista.
- Felipe é forte em Python e modelagem matemática; está aprendendo as ferramentas de engenharia de dados (Airflow, dbt, BigQuery, Docker, CI).
- Ele faz faculdade em paralelo, então o plano é por fases curtas com entregas concretas.
- Ao ajudar: explicar o porquê das decisões, sugerir o caminho simples primeiro (para gerar o "antes"), apontar o que medir em cada etapa e lembrar de registrar métricas e decisões nos arquivos do repositório.

---

## 1. O problema (a história do projeto)

Uma empresa no **mercado livre de energia (ACL)** precisa decidir com antecedência **quanto de energia contratar**.

- Se contrata **menos** do que consome, compra a diferença no mercado de curto prazo pelo **PLD**, que é muito volátil.
- Se contrata **mais**, a sobra é liquidada pelo PLD, muitas vezes com prejuízo.
- Errar o volume custa dinheiro e gera risco.

**O que a plataforma faz:** reúne dados públicos do setor elétrico, prevê o consumo e recomenda um volume de contrato que minimiza custo esperado e risco.

**Frase de abertura para entrevista:**
"Construí uma plataforma de dados que ajuda uma empresa no mercado livre de energia a decidir quanto contratar. Ela integra dados públicos do ONS, CCEE e INMET, prevê o consumo e, em backtest com preços reais de 2021 a 2025, reduziria o custo de energia em R$ X por ano em relação a uma estratégia ingênua."

**Contexto de mercado (por que isso importa agora):**
- Desde jan/2024, todo consumidor de alta e média tensão pode migrar para o mercado livre.
- A partir de 25/11/2027, comércio e indústria em baixa tensão também poderão migrar; demais consumidores a partir de 25/11/2028.
- Gestoras e comercializadoras (ex.: Clarke, Comerc, Voltera) já vendem previsão de consumo e recomendação de contratação. Ou seja: é um problema pelo qual empresas pagam.

---

## 2. Consumidor-exemplo (premissa do projeto)

Como o consumo de uma empresa específica não é público, o projeto usa um **consumidor hipotético**, documentado abertamente no README.

- **Perfil:** supermercado de porte médio, conectado em média tensão (Grupo A), submercado Sudeste/Centro-Oeste.
- **Curva de consumo:** derivada de dados públicos (consumo por ramo de atividade da CCEE, se disponível em granularidade horária; senão, perfil sintético: carga real do SE/CO (ONS) × perfil de loja com 40% de refrigeração constante e 60% de operação no horário de funcionamento; ver `docs/premissas.md`).
- **Extensão futura:** cenário de um comércio em baixa tensão que poderá migrar em nov/2027.

Toda premissa vai para `docs/premissas.md`. Ser transparente sobre premissas conta a favor em entrevista.

---

## 3. Stack

| Camada | Ferramenta | Por quê |
|---|---|---|
| Linguagem | Python 3.11+ | Base de tudo |
| Armazenamento bruto | Google Cloud Storage | Data lake (camada bronze) |
| Data warehouse | BigQuery | Muito pedido em vagas; tier gratuito |
| Transformação | dbt Core (dbt-bigquery) | Padrão de mercado para transformação em SQL |
| Orquestração | Apache Airflow (rodando local em Docker) | O orquestrador mais pedido em vagas no Brasil |
| Qualidade | testes do dbt + checagens em Python | Qualidade de dados é tema de entrevista |
| ML | pandas, scikit-learn, LightGBM | Previsão mensal de carga (regressão regularizada primeiro; LightGBM como desafiante) |
| Otimização | NumPy/SciPy (ou PuLP/cvxpy) | Escolha do volume de contrato por cenários |
| Dashboard | Streamlit (ou Looker Studio) | Mostrar o resultado |
| Infra | Docker, docker-compose | Rodar tudo com um comando |
| CI | GitHub Actions | Testes a cada push |
| IaC (opcional) | Terraform | Diferencial |

**Custo:** Airflow roda local (Cloud Composer é caro). GCS e BigQuery na região us-central1 para ficar no tier gratuito; tabelas particionadas e consultas bem feitas. Alerta de orçamento configurado no GCP desde o início.

---

## 4. Fontes de dados

| Fonte | Dados | Uso |
|---|---|---|
| ONS (dados abertos) | Carga horária por subsistema (histórico desde 2000), geração por fonte, nível de reservatórios (EAR), energia natural afluente (ENA) | Alvo da previsão mensal (SE/CO), base da curva do consumidor, contexto do setor |
| CCEE (dados abertos) | PLD horário por submercado (desde 2021; arquivo 2001–2020 para o preço de 2021), consumo por ramo de atividade (mensal, desde abr/2024) | Preço para o backtest; o consumo por ramo só checa a plausibilidade da curva |
| INMET | Temperatura horária de estações no Sudeste e Centro-Oeste (2021 em diante) | Análise de erro da previsão (ondas de calor) |
| Feriados | Calendário nacional (lib `holidays`), desde 2000 | Calendário da previsão mensal e da curva do consumidor |
| ANEEL | Limites de PLD (piso e teto por ano) | Testes de qualidade |

**Atenção:** os portais mudam formatos de vez em quando, e ONS/CCEE **revisam dados antigos**. Isso precisa ser tratado na ingestão (e vira uma boa história de entrevista).

---

## 5. Arquitetura

```
Fontes (ONS, CCEE, INMET, feriados)
        │  extratores Python (incrementais, idempotentes)
        ▼
GCS  ── bronze: arquivos brutos, particionados por fonte/data
        │  carga para BigQuery
        ▼
BigQuery
  ├─ raw          (espelho do bruto)
  ├─ staging      (dbt: tipos, nomes, fuso horário, deduplicação)
  ├─ intermediate (dbt: junções na granularidade horária)
  └─ marts        (dbt: modelo dimensional)
        │
        ├──► ML: previsão de carga  ──► tabela de previsões
        ├──► Otimização de contrato ──► tabela de recomendações
        ▼
Dashboard (Streamlit / Looker Studio)

Airflow orquestra tudo diariamente: extrair → carregar → dbt run → dbt test → prever → otimizar → atualizar.
GitHub Actions roda testes a cada push.
```

---

## 6. Modelo de dados (marts)

**Dimensões**
- `dim_tempo`: uma linha por hora UTC (2000 a 2030), com hora local, data, dia da semana, mês, ano, feriado (dois conceitos: calendário nacional e o da ANEEL), tipo de dia, estação do ano e horário de ponta.
- `dim_submercado`: SE/CO, S, NE, N, com a correspondência entre os códigos do ONS e os nomes da CCEE.
- `dim_estacao`: as estações do INMET selecionadas, com o registro mais recente dos metadados e a marca das que mudaram de lugar.
- `dim_fonte`: hidráulica, eólica, solar, térmica etc. **Adiada**: depende da geração por fonte, que é item de corte (ver "Se atrasar" nas sprints).

**Fatos**
- `fct_carga_horaria`: carga verificada por hora e submercado.
- `fct_pld_horario`: PLD por hora e submercado.
- `fct_geracao_horaria`: geração por fonte, hora e submercado.
- `fct_reservatorios_diario`: EAR e ENA por subsistema.
- `fct_clima_horario`: temperatura média por hora (estações agregadas).
- `fct_previsao_carga`: previsão vs. real, por versão do modelo.
- `fct_recomendacao_contrato`: volume recomendado, custo esperado e risco por estratégia.

**Boas práticas que serão demonstradas**
- Tabelas particionadas por data e clusterizadas por submercado.
- Modelos incrementais no dbt para os fatos grandes.
- Tudo em UTC no staging, conversão para horário local só na apresentação.

---

## 7. Fases do projeto

Cada fase termina com algo funcionando e com métricas registradas. As fases estão distribuídas em sprints no arquivo `sprints-projeto-energia.md`.

### Fase 0 — Preparação
- Criar repositório no GitHub com a estrutura da seção 9.
- Criar projeto no GCP, bucket no GCS, datasets no BigQuery e **alerta de orçamento**.
- Explorar os portais: baixar uma amostra de cada fonte, anotar formato, granularidade, período disponível e frequência de atualização.
- Escrever `docs/premissas.md` (consumidor-exemplo, regras de contrato) e `docs/fontes.md`.
- **Entregável:** repositório organizado + documento de fontes.

### Fase 1 — Ingestão batch "ingênua"
- Um extrator por fonte, salvando o bruto no GCS e carregando no BigQuery.
- **Primeira versão de propósito simples:** carga full (baixa tudo toda vez), tabelas sem partição.
- **MEDIR (o "antes"):** tempo da carga full, volume baixado, dados lidos por uma consulta típica no BigQuery.
- **Escopo dos dados:** ONS desde 2000 (a previsão mensal precisa do histórico longo), PLD horário de 2021 em diante (mais o arquivo 2001–2020, perfilado, de onde vem o preço de contrato de 2021) e INMET de 2021 em diante.
- **Entregável:** as quatro fontes no BigQuery.

### Fase 2 — Transformação e modelagem com dbt
- Projeto dbt com staging → intermediate → marts.
- Modelo dimensional da seção 6.
- Particionamento **mensal** e clusterização dos fatos horários (o ONS desde 2000 não cabe em partição diária: 9.772 dias, e o limite é de 10.000 partições por tabela e, segundo fontes secundárias, 4.000 por job). Os modelos incrementais ficam para a Fase 4, junto com a ingestão incremental e a janela de segurança para revisões.
- **MEDIR (o "depois"):** dados lidos pela mesma consulta típica após particionamento; tempo de execução do dbt.
- **Entregável:** marts prontos e documentação gerada pelo `dbt docs`.

### Fase 3 — Qualidade de dados
- Testes no dbt: `not_null`, `unique`, `relationships`, faixas válidas (PLD entre piso e teto do ano, carga positiva, temperatura plausível).
- Testes de freshness nas fontes.
- Tratamento de revisões retroativas (upsert por chave natural + data de publicação).
- **MEDIR:** quantos registros problemáticos os testes pegaram e de que tipo (duplicatas, nulos, revisões).
- **Entregável:** pipeline que para e avisa quando o dado está errado.

### Fase 4 — Orquestração e ingestão incremental
- Airflow em Docker; DAG diária com as etapas da seção 5.
- Converter a ingestão para **incremental e idempotente** (só busca o que é novo; reexecutar não duplica).
- Converter os fatos grandes do dbt para incrementais (estratégia `microbatch` por mês, `batch_size: month`, que se encaixa na partição mensal), com a mesma janela de segurança da ingestão.
- Backfill parametrizado por intervalo de datas.
- Retentativas, logs e alerta de falha (e-mail ou Discord).
- **MEDIR:** tempo da carga incremental vs. full; tempo do backfill completo; teste de idempotência (rodar duas vezes e comparar contagens).
- **Entregável:** pipeline rodando sozinho todo dia.

### Fase 5 — Previsão de carga
- **Alvo:** carga mensal do SE/CO, 12 meses à frente (o contrato é decidido uma vez por ano, antes do início do ano). Histórico do ONS desde 2000.
- **Baseline ingênuo:** mesmo mês do ano anterior.
- **Modelo:** regressão linear regularizada com tendência, calendário (dias úteis, feriados) e defasagens de pelo menos 12 meses. LightGBM entra como desafiante, com a mesma validação.
- **Validação:** backtest mensal em rolling origin, nunca aleatória e sempre só com informação anterior ao início de cada ano.
- **Outliers:** 2001–2002 (racionamento) e 2020 (pandemia) tratados explicitamente (excluir do treino ou variável indicadora) e registrados em `docs/decisoes.md`.
- Previsões gravadas no BigQuery com versão do modelo. O erro do rolling origin gera os cenários de consumo da Fase 6.
- **MEDIR:** MAPE mensal e erro absoluto do modelo vs. baseline no mesmo período de teste; erro em meses atípicos e em ondas de calor (com a temperatura do INMET).
- **Extra opcional:** previsão horária D+1 com LightGBM (temperatura e defasagens de curto prazo), só depois do resto.
- **Entregável:** previsão mensal automatizada + análise de erros.

### Fase 6 — Otimização de contrato e backtest
- **Curva do consumidor** (`docs/premissas.md`): `k × carga média diária do SE/CO (real) × perfil de loja`, com `k` único para todo o período.
- **Regras de contrato simplificadas** (documentadas em `docs/premissas.md`): volume anual `V` em MWm, contrato modulado pela carga, banda de flexibilidade de ±10% apurada por mês, diferenças liquidadas ao PLD ponderado pelo consumo. Preço `P_t` = PLD médio do ano anterior + spread de R$ 20/MWh (sensibilidade 0/20/40). A regra de lastro (cobertura de 100% do consumo) define o limite inferior de `V`; a penalidade por insuficiência não entra no custo (extra, ver seção 15).
- Cenários de consumo (a partir da distribuição do erro mensal do rolling origin) e de PLD (a partir do histórico).
- **Escolha de `V`** que minimiza custo esperado + λ × CVaR95, com `V` limitado a `[1/(1+f), 120%]` do consumo previsto (λ = 0,5; sensibilidade 0/0,5/1). O limite inferior vem da regra de lastro (Decreto 5.163/2004: cobertura de 100% da carga).
- **Backtest 2021–2025** com PLD real, comparando três estratégias (2021–2023 são contrafactuais: o consumidor não teria carga para migrar nesses anos):
  1. Ingênua: contratar a média do consumo do ano anterior.
  2. Previsão pontual: contratar o valor previsto.
  3. Otimizada: volume recomendado pelo modelo de cenários.
- **Relatório definido antes dos resultados:** custo total ano a ano, economia contra a ingênua, pior ano, CVaR e exposição ao PLD (MWh) por estratégia. Reportado mesmo que a economia seja pequena ou negativa, e lido ano a ano.
- **Entregável:** tabela de resultados do backtest. **Esta é a métrica principal do projeto.**

### Fase 7 — Dashboard
Quatro páginas:
1. **Panorama do setor:** carga, PLD e reservatórios ao longo do tempo.
2. **Previsão:** real vs. previsto, erro do modelo vs. baseline.
3. **Decisão de contrato:** volume recomendado, custo esperado por estratégia, distribuição de risco, resultado do backtest e **acompanhamento diário do contrato vigente**: consumo acumulado contra a banda, exposição estimada em R$ até o fim do ano e alerta de mês saindo da banda.
4. **Saúde do pipeline:** última atualização, testes passando/falhando, duração das execuções.
- **Entregável:** dashboard público (link no README).

### Fase 8 — Engenharia de software e apresentação
- `docker-compose up` sobe tudo.
- GitHub Actions: lint, testes Python e `dbt test` a cada push.
- Terraform (opcional).
- README final (estrutura na seção 11), diagrama de arquitetura, vídeo de 2 minutos.
- **Entregável:** projeto pronto para mandar a recrutador.

---

## 8. Registro de métricas (impacto)

Manter `docs/metricas.md` atualizado ao longo do projeto. Nunca otimizar antes de medir a versão simples.

| Nível | Métrica | Antes (versão simples) | Depois | Fase |
|---|---|---|---|---|
| Negócio | Custo anual de energia do consumidor-exemplo (backtest) | estratégia ingênua: R$ __ | estratégia otimizada: R$ __ | 6 |
| Negócio | Economia | — | R$ __ / __% | 6 |
| Negócio | Exposição ao PLD (MWh descobertos ou sobrando) | __ | __ | 6 |
| Ciência | MAPE mensal da previsão de carga (12 meses à frente, rolling origin) | baseline: __% | modelo: __% | 5 |
| Engenharia | Dados lidos por consulta típica | __ GB | __ GB | 1 → 2 |
| Engenharia | Tempo de carga diária | full: __ min | incremental: __ min | 1 → 4 |
| Engenharia | Tempo do backfill completo (2021–hoje) | — | __ min | 4 |
| Engenharia | Problemas de dados capturados pelos testes | — | __ registros (tipos: __) | 3 |
| Engenharia | Idempotência | — | 2 execuções → mesma contagem: sim/não | 4 |

---

## 9. Estrutura do repositório

```
energia-livre-dados/
├── README.md
├── CLAUDE.md
├── docker-compose.yml
├── .github/workflows/ci.yml
├── infra/                  # Terraform (opcional)
├── ingestion/              # extratores por fonte
│   ├── ons.py
│   ├── ccee.py
│   ├── inmet.py
│   └── common/             # cliente GCS/BigQuery, logging, retries
├── airflow/dags/
│   └── pipeline_diario.py
├── dbt/
│   ├── models/staging/
│   ├── models/intermediate/
│   ├── models/marts/
│   └── tests/
├── ml/
│   ├── features.py
│   ├── baseline.py
│   ├── train.py
│   └── predict.py
├── optimization/
│   ├── cenarios.py
│   ├── contrato.py
│   └── backtest.py
├── dashboard/app.py
├── tests/                  # testes Python
└── docs/
    ├── planejamento/       # este arquivo e as sprints
    ├── fontes.md
    ├── premissas.md
    ├── metricas.md
    ├── decisoes.md         # registro de decisões
    ├── diario.md
    └── arquitetura.png
```

---

## 10. Registro de decisões

Em `docs/decisoes.md`, cada decisão importante vira uma entrada curta. É daqui que saem as histórias de entrevista.

Modelo:
```
## Título da decisão
Contexto: qual problema apareceu.
Opções: A, B (e C).
Escolha: qual e por quê.
Resultado: o que mudou (com número, se houver).
```

Decisões que provavelmente vão aparecer:
- Região do GCP (us-central1 para ficar no tier gratuito).
- Autenticação local sem arquivo de chave (application-default login).
- Como tratar revisões retroativas do ONS/CCEE.
- Carga full vs. incremental.
- Como particionar e clusterizar as tabelas.
- Fuso horário e horário de verão em séries horárias.
- Por que validação temporal e não aleatória.
- Como gerar os cenários de PLD.
- Airflow local vs. Cloud Composer (custo).

---

## 11. README final (estrutura)

1. **Problema** em 3 linhas (seção 1).
2. **Resultados** logo no topo: economia no backtest, ganho de precisão, ganhos de engenharia.
3. Diagrama de arquitetura.
4. Fontes de dados e premissas (link para `docs/`).
5. Modelo de dados.
6. Como rodar (`docker-compose up`).
7. Decisões técnicas principais (resumo de `docs/decisoes.md`).
8. Limitações e próximos passos.
9. Links: dashboard e vídeo.

---

## 12. Como vai aparecer no currículo (preencher com os números reais)

- "Desenvolvi plataforma de dados do setor elétrico (Python, Airflow, dbt, BigQuery) integrando 4 fontes públicas, com ingestão incremental e idempotente que reduziu o tempo de carga de 9,3 (carga full) para __ min e, com tipagem e partição mensal no BigQuery, reduziu em 98% os bytes processados pela consulta típica do ONS (de 37,3 MB para 0,74 MB; o faturado cai de 37,7 MB para o piso de 10 MiB do BigQuery, então o ganho real aparece nos bytes processados)."
- "Implementei testes de qualidade de dados que capturaram __ registros inconsistentes, incluindo revisões retroativas das fontes."
- "Modelei previsão mensal de carga (12 meses à frente, validação em rolling origin), reduzindo o erro de __% (baseline sazonal) para __%, e otimização de contratação de energia que, em backtest 2021–2025 com preços reais, alterou o custo anual de um consumidor do mercado livre em R$ __ (__%)."

---

## 13. Riscos e como lidar

| Risco | Plano |
|---|---|
| Portal muda formato ou sai do ar | Extratores com validação de schema; guardar o bruto no GCS |
| Consumo por ramo da CCEE não disponível em granularidade horária | Perfil sintético documentado (seção 2) |
| Custo no GCP | Alerta de orçamento, região us-central1, tabelas particionadas, Airflow local |
| Escopo crescer demais | Seguir as fases; extras só depois da Fase 8 |
| Falta de tempo no semestre | Cada fase entrega algo utilizável sozinha; dá para pausar entre fases |
| Regras reais de contrato são complexas | Simplificação explícita em `docs/premissas.md` + análise de sensibilidade |

---

## 14. Definição de pronto

O projeto está pronto para mandar a recrutador quando:
- [ ] Pipeline roda diariamente sozinho, com testes e alertas.
- [ ] `docker-compose up` funciona numa máquina limpa.
- [ ] CI passando.
- [ ] Tabela de `docs/metricas.md` completa.
- [ ] Backtest com resultado em R$.
- [ ] Dashboard público.
- [ ] README com resultados no topo + vídeo de 2 minutos.
- [ ] Pelo menos 4 decisões documentadas em `docs/decisoes.md`.

---

## 15. Extras (só depois da Fase 8)

- Terraform para toda a infraestrutura.
- Cenário do comércio em baixa tensão (abertura de nov/2027).
- Data contracts / Great Expectations.
- Monitoramento de drift do modelo de previsão.
- Pequeno serviço de API (FastAPI) servindo a recomendação.
- Penalidade por insuficiência de lastro no modelo de custo do contrato (depende de confirmar a fórmula, a tolerância e o VR de 2021–2025 no Caderno de Regras nº 13 da CCEE).