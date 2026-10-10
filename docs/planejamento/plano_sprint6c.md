# Plano da Sprint 6, Parte C (6.6 dashboard, 6.7 publicação, e o backlog da origem de produção)

Branch **`sprint6/parte-c1-origem-dinamica`** (C1; a branch foi criada a partir da `main` já com a Parte B mergeada e renomeada). A C2 (dashboard) terá **branch própria, criada depois do merge da C1**. Referências: `sprints-projeto-energia.md` (S), `planejamento-projeto-energia.md` (Fase 7, seção 14), `decisoes.md` (D), `metricas.md` (M), `plano_sprint6b.md` (B).

**Fora desta Parte:** a tarefa **6.8** (acompanhamento diário do contrato vigente) continua pendente. **Onde ela está no repositório:** `docs/planejamento/sprints-projeto-energia.md`, linha 204 ("- [ ] 6.8 Na página \"Decisão de contrato\": acompanhamento diário do contrato vigente (consumo acumulado contra a banda, exposição estimada em R$ até o fim do ano e alerta de mês saindo da banda)"), e `docs/planejamento/planejamento-projeto-energia.md`, linha 203 (Fase 7, página 3, "Decisão de contrato"). Ela existe nos dois; não criei nem alterei nada. Exige dado diário, e isso pesa na escolha da seção 2 (ver "Risco" lá).

## Aprovação e ajustes (11/10/2026), que valem sobre o texto abaixo

1. **Cadeia mensal manual aprovada**, sem DAG e sem rebuild agora (seção 1.3, opção A). **Snapshot em CSV no repositório aprovado**, regenerado **mensalmente** (seção 2, opção b).
2. **Duas partes:** **C1 = origem dinâmica** (esta branch, `sprint6/parte-c1-origem-dinamica`): `ml.cenarios gerar-producao` e `ml.recomendacao producao`, com testes. **C2 = dashboard**, em branch própria criada depois do merge da C1.
3. **Antes de tornar o repositório público: varredura de segredos no histórico inteiro** (ver "Varredura de segredos" abaixo). Nada é publicado antes dela.
4. **Cobertura na página de previsão (substitui o texto da seção 3.2):** usar **só a cobertura fora da amostra: 70,2% (nominal 80%) e 87,8% (nominal 95%)**, do teste final (654 pares) com intervalos calibrados **só no desenvolvimento** (quantis por horizonte; `docs/metricas.md`, tabela "Intervalos de previsão" da Sprint 5, Parte A, e a coluna "anterior" da tabela de cobertura da 5.6), com a **fonte escrita na tela**. Os **70,8% e 90,5%** do CSV `analise_teste_final_reconstruida_cobertura_pooled.csv` (quantis de todos os horizontes juntos) **não entram como cobertura**: a calibração de produção já viu o teste final. Os números por horizonte da 5.6 (de 71,7%/88,3% em h=1 a 61,2%/75,5% em h=12) entram numa tabela versionada em `dashboard/dados/` com a fonte, e um teste da C2 confere a tabela contra a do `metricas.md`.
5. **Saúde do pipeline sem mudar a DAG (substitui o mínimo da seção 3.4 e a decisão C11):** o `dashboard.snapshot` lê o `dbt/target/run_results.json` **local** e as durações do **Postgres do Airflow** e grava no snapshot; a página mostra **"estado em <data do snapshot>"**. Não há `cp` na DAG. Limite aceito: o `run_results.json` é o do **último comando dbt** rodado na máquina; o snapshot registra o `generated_at` desse arquivo, e a página mostra essa data junto, para que um `dbt run` manual posterior não passe por um teste da DAG.
6. **A 6.8 existe no planejamento** (linha 204 de `sprints-projeto-energia.md`); segue fora da Parte C.

### Varredura de segredos (proposta; **nada abaixo publica ou escreve**)
Medido hoje, só local: 80 commits; nenhum `.env` real nem chave no histórico (`.env.example` e `airflow/.env.example` têm valores vazios); `git log --all -S'private_key'` sem resultado; o ID do projeto GCP **nunca** apareceu no histórico; `.claude/settings.json` só tem `deny` de comandos git; `.gitignore` cobre `.env`, `data/`, `dbt/profiles.yml`, `*credentials*.json`, `service-account*.json`. Os commits têm dois e-mails de autor: um `noreply` do GitHub e `felipe.inserti@gmail.com`; fica público com o repositório (decisão sua).
Comando (rodar na raiz; o gitleaks lê o histórico de **todas** as referências, o `--redact` evita imprimir o segredo no terminal; a imagem é baixada do Docker Hub, e o container não tem rede para enviar nada além do `pull`):
```
docker run --rm -v "$PWD:/repo" zricethezav/gitleaks:latest detect --source /repo --log-opts="--all" --redact -v --report-format json --report-path /repo/data/logs/gitleaks.json 2>&1 | tee data/logs/gitleaks.log
```
Equivalente sem Docker (se o binário estiver instalado): `gitleaks detect --source . --log-opts="--all" --redact -v | tee data/logs/gitleaks.log`. Conferência complementar, sem ferramenta: `git log --all -p | grep -Ei "private_key|BEGIN (RSA|EC|OPENSSH)|AIza[0-9A-Za-z_-]{30,}|client_secret|refresh_token|ya29\\." | head`. **Critério:** zero achados, ou cada achado explicado e, se for segredo real, **revogado antes** de qualquer publicação (reescrever o histórico não basta se o repositório já foi clonado). O relatório JSON fica em `data/logs/` (ignorado pelo git).


**Medidas que usei para este plano** (só leitura; `INFORMATION_SCHEMA`/`__TABLES__` do BigQuery e os arquivos do repositório):

| Tabela em `marts` | Linhas | Bytes lógicos |
|---|---|---|
| `fct_carga_mensal` | 1.288 | 197.048 |
| `fct_erro_previsao_carga` | 1.806 | 373.842 |
| `fct_previsao_carga` | 12 | 3.792 |
| `fct_pld_semanal` | 12.312 | 732.564 |
| `fct_pld_ponderado_mensal` | 70 | 3.990 |
| `fct_consumo_horario` | 59.304 | 3.550.536 |
| `fct_recomendacao_contrato` | 213 | 67.750 |
| `fct_cenario_consumo` / `fct_cenario_pld` / `fct_cenario_execucao` | 144.000 / 288.000 / 6 | 10.080.000 / 20.304.000 / 1.308 |
| `fct_clima_horario` (maior) | 1.837.272 | 282.319.368 |

Tudo que o dashboard mostraria cabe em bem menos de 1 MB por página, mas **cada consulta a uma tabela fatura no mínimo 10 MiB** (piso). Os CSV de `docs/resultados/` (backtest, sensibilidades, intervalos, baselines) somam 3,0 MB, dos quais o backtest e as sensibilidades, 556 KB.

---

## 1. Origem de produção dinâmica (backlog da 6.5)

### 1.1 O problema, em termos do código atual
- `ml.recomendacao gravar` lê os cenários de `data/cenarios_6a/` (parquet local, execução congelada `51cf99b073fe`), que só tem a origem de produção **2026-09**. Quando a previsão de produção passar a ser 2026-10, a prévia falha.
- `ml.cenarios gerar` gera **todas** as origens (5 de backtest + a de produção) de uma vez e deriva **um** `execucao_id` do conjunto; regerar com uma origem nova mudaria o id e **não pode** tocar nas 5 origens de backtest (o caso base está congelado nesse id).
- A previsão de produção já é mensal e automática (`previsao_ha_mes_novo` → `previsao_mensal` na DAG).

### 1.2 Proposta: um `execucao_id` por origem de produção, e a cadeia mínima
Quando um mês fecha (por exemplo, out/2026 vira a origem 2026-10):

| Passo | Comando | O que faz | Bytes (estimativa; a medir) |
|---|---|---|---|
| 1. Previsão | `python -m ml.previsao gerar` (já na DAG) | grava as 12 previsões e os erros realizados da origem | já medido (22 s; M) |
| 2. Cenários **só da origem nova** | `python -m ml.cenarios gerar-producao` (novo) | lê erros, PLD e previsão; gera N = 2.000 cenários de **uma** origem; `execucao_id` = hash dos insumos **dessa** origem (n, semente, `k`, `erros_hash`, `pld_hash`, `pisos_hash` da origem); grava 3 tabelas por `MERGE` com 1/6 das linhas (24.000 de consumo, 48.000 de PLD, 1 de execução) | leitura ~4 tabelas × 10 MiB (piso); `MERGE` lê o destino: ~20 + ~23 + 20 MiB (hoje 10,1 e 20,3 MB, +5 MB por mês) |
| 3. Prévia | `python -m ml.recomendacao producao` (novo) | lê **do BigQuery** os cenários da origem (filtro `execucao_id` e `origem`), o PLD mensal (`fct_pld_ponderado_mensal`) e o consumo dos 12 meses, decide e grava 3 linhas em `fct_recomendacao_contrato` | ~5 tabelas × 10 MiB (piso) + 1 `MERGE` de ~20 MiB |

- **As 5 origens de backtest nunca são regravadas**: o comando de produção só escreve linhas da origem nova; o `gravar` atual (backtest, 210 linhas) fica como comando único, já executado, e a produção ganha o seu subcomando.
- **Reprodutibilidade:** o id depende só dos insumos da origem; rodar duas vezes o mesmo mês dá o mesmo id (idempotente, como hoje). O id de 2026-09 dentro da execução congelada fica como está (histórico); a partir de 2026-10 cada origem tem o seu.
- **Custo mensal da cadeia:** ~170 MiB faturados (passos 2 e 3, estimativa pelo piso, a medir com `ContaBytes`), ~0,016% de 1 TiB; o `MERGE` cresce ~5 MB por mês no destino (depois de 12 meses, +60 MB). O particionamento por origem passa a fazer sentido **só agora**: cada `execucao_id` de produção tem uma origem própria, e um filtro por `origem` no `ON` poderia podar. Fica no backlog; o número que justificaria é o `MERGE` passar de ~100 MiB por mês.
- **Origem de dezembro:** a primeira será 2026-12 (dezembro fechado em janeiro): `tipo = producao`, `ano_contrato = 2027`. Os limites do PLD de 2027 são **assumidos** (repetem 2026) até a seed `pld_limites` receber os da ANEEL; **essa atualização da seed é manual, todo dezembro**, e fica no runbook (o `limites_assumidos` do dashboard avisa quando for assumido).
- **Prévias antigas ficam** (a chave inclui a origem): o dashboard mostra a prévia mais recente e, em segundo plano, como a prévia mudou mês a mês (sem calcular economia: não há realizado).

### 1.3 DAG agora ou comando manual?
Opções: (A) comandos manuais mensais, em sequência, para os passos 2 e 3 (`ml.cenarios gerar-producao` e `ml.recomendacao producao`, cada um idempotente e com `--dry-run`); (B) duas tasks na DAG depois de `previsao_mensal` (`cenarios_producao`, `recomendacao_producao`), atrás do mesmo ShortCircuit.

**Recomendo (A) agora. [APROVADO em 11/10/2026]**
- **Por quê:** o dashboard público (seção 2) lê um **snapshot** que só muda quando eu o regenero e commito; automatizar a cadeia na DAG não atualiza o dashboard sozinho. O ganho da DAG seria o BigQuery ficar certo sem eu lembrar, e isso não aparece para quem vê o dashboard.
- **Rebuild da imagem:** a cadeia **não precisa de pyarrow** se ler e escrever só pelo BigQuery (sem parquet), e `pandas`, `numpy`, `scikit-learn` e `statsmodels` já estão no grupo `ml`. O rebuild do pyarrow segue sendo pendência separada (só serve a quem lê parquet). Se a Parte C optar pela DAG, o custo é o rebuild medido com `time` (tempo e tamanho da imagem antes e depois, como o backlog pede) mais o teste da DAG (`airflow dags test`); eu **não** o faço agora.
- **O que se perde:** (i) a prévia do BigQuery pode ficar até um mês atrás da previsão (a previsão é automática, a prévia não); (ii) esquecer o comando deixa a prévia velha. **Mitigação sem DAG:** o snapshot registra `ultimo_mes_fechado` (da previsão de produção) e a `origem_da_previa`; quando diferem, o dashboard mostra o aviso "a prévia é de <origem>; o último mês fechado é <mês>", visível acima do número. O estado errado nunca aparece como atual.
- **Quando migrar para (B):** se o comando for esquecido uma vez, ou quando a Sprint 7 (CI, DAG completa) for fechar o pipeline; já fica pronto como um único comando.

---

## 2. Acesso aos dados e custo (decisão central)

### 2.1 As opções

**(a) Streamlit lendo o BigQuery com `st.cache_data`.** O app roda no Community Cloud e consulta `marts`.
- **Credencial:** o Community Cloud não tem ADC. Exige uma **conta de serviço com chave JSON** nos *secrets* do Streamlit (hoje o projeto não tem nenhuma; D linhas 11–12 escolheram ADC justamente para não ter chave). Permissões mínimas: `roles/bigquery.dataViewer` **só no dataset `marts`** e `roles/bigquery.jobUser` no projeto (necessário para rodar consulta, e não dá para restringir a um dataset).
- **Custo no pior caso, com cache frio:** uma sessão que percorre as 4 páginas faz ~6 consultas em tabelas distintas (carga mensal, PLD, erros, previsão, recomendação, pipeline), cada uma no piso de 10 MiB: **~60 MiB por sessão fria**. 1.000 sessões frias: ~59 GiB; 10.000: ~586 GiB (0,57 TiB); ~17.900 sessões frias consomem 1 TiB (o gratuito do mês, que o pipeline já gasta ~28 GB). O `st.cache_data(ttl=...)` compartilha o resultado entre sessões do mesmo processo, então o caso frio é uma por reinício do app (o Community Cloud hiberna o app sem acesso por um prazo que não confirmei) e uma por expiração do `ttl`.
- **Pior caso real (cache furado):** se alguma consulta recebe parâmetro vindo do usuário (filtro de ano, sensibilidade), cada combinação nova é um *cache miss*: 10 MiB por interação. Um robô a 1.000 interações por dia dá ~10 GiB/dia (300 GiB/mês, dentro do gratuito); sem teto a conta só é limitada pela **cota diária do projeto de ~51 GiB/dia (D linha 18)**: 51 × 30 ≈ 1,49 TiB/mês, ~0,49 TiB pagos. Ao preço de tabela que conheço (**US$ 6,25 por TiB, a confirmar no console; câmbio não assumido**), ~US$ 3,1, **mais que o teto de R$ 10/mês provavelmente** (a conta depende do câmbio). Ou seja: **(a) pode estourar o teto**, e o alerta de orçamento só avisa, não bloqueia (D linha 16).
- **Mitigações da (a):** `maximum_bytes_billed` por consulta (por exemplo, 20 MiB: um bug ou uma consulta mal feita não custa mais que isso; já é o padrão do projeto via `gcp.executar_consulta`); consultas só com parâmetros fixos (nenhum valor do usuário entra no SQL, só filtro no pandas depois do cache); cota por usuário (a custom quota `QueryUsagePerUserPerDay` da conta de serviço, por exemplo 1 GiB/dia, **a confirmar que existe e funciona assim no projeto**); baixar a cota diária do projeto (isso também limita o pipeline). Cada mitigação é configuração de nuvem a manter.
- **Se a credencial vazar:** o atacante lê os dados do `marts` (dados públicos e derivados) e roda consultas por conta do projeto, limitado pela cota; não escreve (só `dataViewer`); revogação: apagar a chave (1 minuto) e criar outra. Risco real = custo e DoS da cota (a cota esgotada trava a DAG e o dbt).

**(b) Passo que publica um snapshot pequeno e o dashboard lê só ele.** Um comando local (`python -m dashboard.snapshot`, com o mesmo ADC de sempre) lê o BigQuery uma vez, grava CSV pequenos e um `manifest.json` em `dashboard/dados/` **no repositório**; o app lê esses arquivos (e os CSV já versionados de `docs/resultados/`). O deploy reinicia a cada push.
- **Credencial:** **nenhuma no app**. O app não importa `google.cloud`. O ADC fica só na minha máquina.
- **Custo no pior caso:** **R$ 0 de BigQuery, qualquer que seja o número de acessos**: o app não consulta. Custo de geração do snapshot: ~7 consultas × 10 MiB = ~70 MiB por regeneração (estimativa pelo piso), uma por mês (ou por dia, se quiser).
- **Se vazar:** não há o que vazar (sem segredo). Os arquivos do snapshot são dados públicos e resultados do projeto, e já estão no git.
- **Perde:** frescor. O dashboard só muda quando eu regero e commito (e o Community Cloud reimplanta). A "prévia ao vivo" vira "prévia do snapshot de <data>", sempre com a data visível. Dados do pipeline (última atualização, testes, duração) valem até o último snapshot.
- **Ganha:** (i) robustez de portfólio: o dashboard continua no ar mesmo se o projeto GCP for desativado ou o crédito acabar; (ii) o app sobe em segundos (CSV locais) e o tempo por página é determinístico; (iii) testes sem nuvem (seção 5); (iv) a decisão de D linha 97 ("revisitar o perfil dev/prod do dbt antes de publicar o dashboard, quando passa a haver consumo externo") **não precisa mudar nada**: o consumo externo não chega ao BigQuery.

**(c) Combinação:** snapshot para tudo e consulta ao vivo (conta de serviço, só leitura) só para a prévia e o estado do pipeline. Reúne o frescor da (a) para 2 telas, **com** a credencial da (a) e o custo reduzido (2 consultas por sessão fria ≈ 20 MiB; teto por `maximum_bytes_billed` e cota por usuário). Só vale se o frescor desses dois pontos fosse indispensável, e não é: a prévia muda uma vez por mês.

### 2.2 Recomendação: **(b), snapshot no repositório** [APROVADO em 11/10/2026; regenerado mensalmente]
- Mantém o teto de R$ 10 por construção (o app não custa nada) em vez de por configuração; nenhuma credencial na nuvem; a proteção contra abuso é a do próprio Community Cloud, não a minha cota.
- **Formato:** CSV pequenos (diffáveis no git) + `manifest.json` (data, commit, hashes dos arquivos, `ultimo_mes_fechado`, `origem_da_previa`, bytes lidos do job). Parquet fica descartado: o app não precisaria do pyarrow e o git guardaria binários.
- **Risco que fica (a decidir quando a 6.8 for planejada):** o acompanhamento diário do contrato vigente (6.8) exige dado diário; com snapshot no git isso vira um commit por dia, ruim. Se a 6.8 entrar, **migrar essa página para (c)**, com a conta de serviço e as mitigações da (a), e **só nela**. A Parte C não a inclui, e o plano da página de decisão deixa o lugar reservado.

---

## 3. As quatro páginas

Camada de dados lê `dashboard/dados/` (snapshot) e `docs/resultados/` (backtest e sensibilidades já versionados; fonte única, **sem cópia**). `manifest.json` registra o hash do que foi lido.

### 3.1 Panorama do setor
- **Reservatórios: não existem.** Não há `fct_reservatorios_diario` em `dbt/models/marts` e a ingestão do ONS não baixa EAR/ENA (nem em `ingestion/`). Está na lista "Se atrasar", item 2 (já cortado). **Não a crio.** A página escreve "Reservatórios (EAR/ENA) não foram ingeridos; fora do escopo".
- **Fontes (snapshot `panorama_mensal.csv`):** carga mensal do SE/CO (`marts.fct_carga_mensal`: original e reconstruída, MWmed, 1.288 linhas na tabela), PLD mensal do SE (2002–2020 a partir de `fct_pld_semanal`, 2021+ de `fct_pld_ponderado_mensal`) com o piso e o teto estrutural do ano (seed `pld_limites`).
- **Gráficos:** (1) carga mensal 2000 a hoje, com a série original e a reconstruída e o marcador da quebra do tipo III; (2) PLD mensal com piso/teto e a faixa dos meses no piso.
- **O que deixa claro:** a série de PLD **mistura** o semanal (2002–2020, média simples dos 3 patamares) e o ponderado pelo consumo (2021+) (limitação 3 de D 5.7); a carga é do **SE/CO inteiro**, não do consumidor-exemplo; e o consumidor-exemplo é sintético (100 MWh/mês, `k`).
- Primeira página a sair se atrasar (seção 8).

### 3.2 Previsão
- **Fontes:** `fct_erro_previsao_carga` (previsto, real e erro por origem e horizonte; períodos desenvolvimento, estresse 2020, teste final, produção), `fct_previsao_carga` (a previsão de produção, 12 meses, com `p025, p10, p50, p90, p975`) e os CSV versionados `baseline_*`, `candidatos_teste_final_*`, `analise_teste_final_*` de `docs/resultados/`.
- **Gráficos:** (1) real contra previsto do teste final (origem de dezembro, escolha do ano), com o ingênuo sazonal; (2) MAPE por ano, **modelo contra baseline** (3,11% contra 4,17% nos mesmos pares; 2023 é o pior ano do modelo, 4,08%); (3) a previsão de produção (12 meses) com as faixas; (4) **cobertura real dos intervalos** por horizonte e total.
- **Cobertura (ajustada em 11/10/2026; vale o bloco "Aprovação e ajustes"):** só a **fora da amostra, 70,2% (nominal 80%) e 87,8% (nominal 95%)**, teste final, intervalos calibrados só no desenvolvimento, com a **fonte escrita na tela**. Os 70,8% e 90,5% da calibração de produção **não aparecem como cobertura** (a calibração já viu o teste). Rótulo: "cobertura observada fora da amostra (nominal)"; a faixa de 80% é desenhada com a legenda "cobre 70,2% no teste final, não 80%".
- **O que deixa claro:** intervalos calibrados só com o desenvolvimento, estreitos no teste final; 2023 mal previsto (viés −3,2%); o teste final foi usado **uma vez** (D, regra de seleção); a vantagem sobre o ingênuo vem em parte de o ingênuo piorar com as quebras.

### 3.3 Decisão de contrato (a métrica principal)
- **Fontes:** `docs/resultados/backtest_caso_base_{anual,economia,mensal}.csv` e `backtest_execucoes.jsonl` (hash do pré-registro `02990fd`, HEAD, quando); `sens_*.csv`, `sens_resumo*.csv`, `sens_banda_f.csv`, `sens_invariancias.csv` e `sensibilidades_execucoes.jsonl` (pré-registro `4c02987`); `fct_recomendacao_contrato` (snapshot `recomendacao.csv`, a prévia e o histórico dela).
- **Blocos, nesta ordem:**
  1. **Faixa de ressalvas no topo, fora do rodapé** (seção 4).
  2. **Backtest pré-registrado:** custo e economia por ano e estratégia (com e sem 2021), pré-registro e hash visíveis ("executado uma vez em 10/10/2026, depois de `02990fd`").
  3. **Decomposição previsão × otimização:** barras empilhadas por ano (valor da previsão, valor da otimização), **R$ por ano**, não só o total.
  4. **Análise principal da banda f** (0, 5, 10, 15%): valor da previsão e da otimização em função de f, com a nota "o valor da otimização **cresce** com f" e "o valor da previsão com f = 0 é aposta de preço (sinal por ano)".
  5. **Sensibilidades:** tabela das 13 na **ordem fixa do plano, sem ranking**, com a coluna "o que mudou", e o `rmax120` com o rótulo **"especulação, excluída do caso base (D13)"** no mesmo peso visual das outras (sem cor de destaque, sem "melhor").
  6. **Prévia da origem de produção:** com o selo **"PRÉVIA (snapshot de <data>): janela móvel out/2026–set/2027, não é a decisão de 2027"**, o `P` generalizado, V das três estratégias, E[custo] e CVaR; **sem "economia esperada"** (não há realizado).
  7. **Limitações em texto** (lastro, flexibilidade sem preço, 5 anos sem significância, `P_t` defasado, cenários subestimam o regime de piso).
- Reserva o lugar da 6.8 (acompanhamento diário), vazio e rotulado "não implementado".

### 3.4 Saúde do pipeline
- **De onde vêm os dados hoje (verificado):**
  - **Duração das execuções:** o Postgres do Airflow (`task_instance.duration`, `dag_run`), lido com `docker compose exec -T postgres psql` (a mesma técnica de `docs/runbook_airflow.md` e de `scripts/resumir_execucao_dag.py`). Fica **fora do BigQuery**.
  - **Testes do dbt:** `dbt/target/run_results.json` (o último comando do dbt; `scripts/resumir_testes.py` já resume), que **é sobrescrito** por qualquer `dbt run/test` posterior.
  - **Frescor das fontes:** `dbt/target/sources.json` (freshness) e o `MAX` das datas dos marts.
  - Nada disso existe em tabela hoje.
- **Mínimo para registrar (APROVADO, sem mudar a DAG):** o `dashboard.snapshot` lê os últimos 30 `dag_run` e as durações das tasks do Postgres do Airflow, o `dbt/target/run_results.json` e o `sources.json` **locais**, e grava `saude.csv` e `saude_testes.csv`, com a data e hora de geração de cada arquivo lido; a página mostra "estado em <data do snapshot>". **Sem tabela nova no BigQuery e sem tocar a DAG.**
- **Gráficos:** última atualização por fonte (data do último dado e idade); resultado do último `dbt test` (pass/warn/error, tempo); duração das últimas 30 execuções da DAG por task, com as falhas visíveis.
- **O que deixa claro:** é o estado **do snapshot** (data e hora no topo), não ao vivo; o pipeline roda na minha máquina (LocalExecutor), então "execução ausente" pode ser máquina desligada, não falha; falhas registradas aparecem.

---

## 4. Honestidade na interface

**Regra:** toda ressalva que muda a leitura de um número aparece **no mesmo bloco do número**, acima do gráfico, nunca só no rodapé. O texto de cada ressalva vive num módulo único (`dashboard/textos.py`) e um teste confere que cada página o inclui nos primeiros elementos.

| Ressalva | Onde aparece |
|---|---|
| 5 anos, sem teste de significância; 2021–2023 contrafactuais | faixa no topo da página de Decisão (`st.warning`), e hachurado/rótulo "contrafactual" nas barras de 2021–2023 |
| A economia da otimizada é um **teto** (flexibilidade sem preço) e o valor da previsão é um **piso** (sem penalidade de lastro; regra a confirmar na CCEE) | faixa do topo, e na legenda de cada gráfico de economia |
| Ganho concentrado em 2022 e 2025 | **anotação no gráfico de economia por ano**: "2022 e 2025 somam R$ 9.202,62, 102% do valor da otimização de R$ 9.020,19; 2023 e 2024 somam −R$ 182,42" |
| Média de 5 anos nunca sozinha | o total só aparece ao lado da barra por ano; o seletor padrão é "por ano", não "total" |
| Otimização = aposta de `E[PLD]` contra `P_t` | texto ao lado da decomposição (decisões ex-ante da 6.2): "r\* no limite em 4 de 5 anos; o sinal vem de `E[PLD] − P_t`" e o r\* de cada ano marcado no gráfico |
| Sensibilidades: nada é "o melhor" | tabela na ordem do plano, sem ordenação por economia, sem destaque; `rmax120` rotulado "especulação excluída" |
| f = 0: o valor da previsão é aposta de preço | nota fixa ao lado do gráfico de f, com a identidade `(V_ing − V_pont)·Σ(P_t − PLDp)` |
| Prévia não é decisão | selo "PRÉVIA" na cor de aviso junto ao número, com a janela e a data do snapshot; aviso extra se a origem estiver atrasada |
| Cobertura dos intervalos: a real, não a nominal | legenda da faixa: "cobre 70,8%, não 80%" |
| Dados do pipeline não são ao vivo | data e hora do snapshot no topo de todas as páginas |

Contra a sugestão enganosa: eixos começam em zero nas barras de custo e de economia; **R$ e % lado a lado** (a economia é de décimos de % do custo, e o gráfico mostra a escala do custo, não só o delta); sem eixo duplo; sem cor que sugira "bom" ou "ruim" para a sensibilidade; sem linha de tendência nos 5 anos; incerteza mostrada onde existe (o PIT e o CVaR ex-ante ao lado do custo realizado, e "o custo de 2023 passou do CVaR95 nas três estratégias").

---

## 5. Estrutura e testes

```
dashboard/
  app.py            # entrada: st.navigation com as 4 páginas
  paginas/{panorama,previsao,decisao,saude}.py   # só interface: chamam dados, cálculos e gráficos
  dados.py          # leitura do snapshot e de docs/resultados (funções puras, sem streamlit)
  calculos.py       # concentração por ano, decomposição, tabela de f (funções puras)
  graficos.py       # DataFrame -> gráfico Altair (funções puras; testa-se o spec)
  textos.py         # as ressalvas, uma vez só
  snapshot.py       # ÚNICO módulo que fala com o BigQuery/Postgres (ADC); o app NÃO o importa
  dados/            # snapshot em CSV + manifest.json (versionado)
  requirements.txt  # só o que o app usa (streamlit, pandas, altair), versões fixas
```
- **Camada de dados × interface:** `dados.py`, `calculos.py` e `graficos.py` sem `streamlit`; as páginas só montam. O caminho do snapshot vem de um parâmetro (padrão `dashboard/dados/`), então os testes apontam para uma fixture.
- **Testes de dados (sem BigQuery, sem rede):** fixtures sintéticas pequenas em `tests/fixtures/dashboard/`; esquema e tipos de cada CSV; a leitura falha com mensagem clara se um arquivo ou coluna falta; `calculos` conferidos à mão (concentração 2022+2025 = 102% do total do caso base, decomposição soma ao total); `manifest.json` bate com os hashes.
- **Testes do snapshot** (`dashboard/snapshot.py`) com `gcp` e Postgres falsos (a mesma técnica de `test_ml_medida_bytes.py`): lê a consulta certa, grava os CSV esperados, reporta bytes **do job** com `ContaBytes`, nunca grava segredo.
- **`streamlit.testing.v1.AppTest`:** cada página carrega **sem exceção** com a fixture e com o snapshot real do repositório (`at.run()`; `assert not at.exception`); a página de Decisão tem a faixa de ressalvas nos primeiros elementos e o selo PRÉVIA; o panorama diz que não há reservatórios. A navegação multipágina no `AppTest` depende da versão do Streamlit (**a confirmar na versão fixada**); se não houver, cada página é uma função `renderizar()` testada com `AppTest.from_function`.
- **Teste de higiene:** o app não importa `google.*` nem lê variável de ambiente de credencial (varredura de imports em `dashboard/` exceto `snapshot.py`); nenhum arquivo do snapshot contém "private_key" nem `GOOGLE_APPLICATION_CREDENTIALS`.
- **Dependências:** novo grupo `dashboard` no `pyproject.toml`, incluído no `default-groups` para o `uv sync` rodar os testes, e **não** vai para a imagem do Airflow (o `Dockerfile` instala só `dbt` e `ml`).

---

## 6. Publicação (6.7)

Passos no **Streamlit Community Cloud** (os detalhes da interface eu **confirmo no deploy**; os nomes abaixo são os que conheço):
1. Repositório no GitHub com a branch `main` atualizada (o snapshot e os CSV de resultados dentro).
2. Em `share.streamlit.io`, **New app**: repositório, branch `main`, **arquivo principal `dashboard/app.py`**, e (em *Advanced settings*) a versão do Python (3.12).
3. **Dependências:** `dashboard/requirements.txt` (versões fixas; o Streamlit já traz o pyarrow). Se a plataforma ler o `pyproject.toml`/`uv.lock` em vez do `requirements.txt`, **confirmar** qual vale (não verifiquei).
4. **Secrets:** nenhum (opção (b)). A tela de secrets fica vazia; o teste de higiene garante que o app não os espera.
5. Subdomínio do app; conferir o carregamento frio e a hibernação (seção 7).
6. Reimplantação a cada push em `main`: o snapshot novo só vai ao ar com commit.

**Arquivos que o deploy precisa:** `dashboard/**` (app, módulos, `dados/`, `requirements.txt`), `docs/resultados/*.csv` e `*.jsonl` que o app lê, e o menor `.streamlit/config.toml` (tema, desligar a coleta de estatística de uso).

**README (resultados no topo, como a seção 11 do planejamento):** o link do dashboard; as 3 linhas de resultado com as ressalvas (economia de R$ 8.690,10, 0,89%, em 5 anos, concentrada em 2022 e 2025; valor da previsão ≈ 0 para f ≥ 10%); como rodar local (`uv run streamlit run dashboard/app.py`); como regenerar o snapshot (`uv run --env-file .env python -m dashboard.snapshot`); a cadeia mensal da seção 1; fontes e licenças dos dados (ONS, CCEE, INMET; **licença a verificar e citar**); e a nota de custo ("o dashboard não consulta o BigQuery").

---

## 7. O que medir

| Medida | Como | Onde registrar |
|---|---|---|
| Tempo de carregamento por página, **cache frio e quente** | `AppTest` local (`at.run()` com `st.cache_data.clear()` antes, e depois de novo), por página; e, no Community Cloud, 3 cargas frias (app reiniciado) e 3 quentes por página, com cronômetro do navegador; registrar a mediana e o pior | `metricas.md` |
| Bytes por acesso | do **app: 0 bytes de BigQuery** (conferido por não importar `google.*`); bytes transferidos ao navegador: tamanho dos CSV que cada página lê | `metricas.md` |
| Custo por mês para N acessos | BigQuery = R$ 0 para qualquer N na opção (b). Para comparar, a (a): ~60 MiB por sessão fria (cálculo, a medir com a mesma `ContaBytes`) × N: 1k = 59 GiB, 10k = 586 GiB, 17,9k = 1 TiB; pior caso sem cota ≈ 51 GiB/dia | `metricas.md`, rotulado "cálculo" |
| Custo do snapshot | bytes **do job** (`total_bytes_billed`, `cache_hit`) de cada regeneração, tempo e tamanho dos arquivos | `metricas.md` |
| Custo da cadeia mensal da seção 1 | bytes por passo, do job; `MERGE` por origem nova | `metricas.md` |
| Rebuild da imagem (só se a opção B da seção 1.3 for escolhida) | `time docker compose build`, tamanho antes e depois | `metricas.md` |

---

## 8. Ordem de corte se atrasar

Do planejamento ("Se atrasar", S): a ordem lá é Terraform, `fct_reservatorios_diario`/fontes, temperatura ponderada, **página "Panorama do setor"**, análise de sensibilidade. Dentro da Parte C:
1. **Panorama do setor** é a **primeira a sair** (a página não é a métrica principal e não tem reservatórios).
2. Dentro de Previsão: sai o seletor de ano e a tabela de cobertura por horizonte; ficam o gráfico de MAPE contra o baseline e a cobertura total.
3. Dentro de Saúde: ficam a última atualização e o resultado do último `dbt test`; sai o gráfico de duração por task.
4. **Não cortar:** a página de Decisão com as ressalvas, o hash do pré-registro e a análise de f; a publicação (6.7); a medição.
**Ordem de construção** (para o corte ser limpo): Decisão → Previsão → Saúde → Panorama; e um **deploy mínimo no primeiro dia** (página de Decisão com o snapshot) para descobrir cedo qualquer surpresa do Community Cloud.

---

## 9. Decisões para o `decisoes.md` (opções e recomendação)

| # | Decisão | Opções | Recomendação |
|---|---|---|---|
| C1 | Branches da Parte C | (a) uma branch; (b) duas | **(b) APROVADO:** C1 = origem dinâmica na branch atual, renomeada `sprint6/parte-c1-origem-dinamica`; C2 = dashboard em branch própria (`sprint6/parte-c2-dashboard`), criada depois do merge da C1 |
| C2 | Origem de produção dinâmica | (a) regerar todas as origens; (b) `execucao_id` por origem de produção, cenários só da origem nova | **(b)**: o caso base fica intocado e o custo mensal é pequeno |
| C3 | Cadeia mensal | (a) comandos manuais em sequência (`ml.cenarios gerar-producao`, depois `ml.recomendacao producao`); (b) tasks na DAG | **(a) APROVADO** (sem DAG e sem rebuild agora); (b) quando a Sprint 7 fechar a DAG, ou após um esquecimento. O dashboard avisa quando a prévia está atrás do último mês fechado |
| C4 | Onde ficam os cenários da origem de produção | (a) parquet local; (b) BigQuery (`fct_cenario_*`, uma execução por origem) | **(b)**: a cadeia precisa rodar fora da minha máquina quando entrar na DAG; custo ~63 MiB por mês de `MERGE` |
| C5 | Acesso do dashboard aos dados | (a) BigQuery ao vivo com cache; (b) snapshot no repositório; (c) combinação | **(b)**; (c) só para a 6.8, se ela entrar |
| C6 | Formato e lugar do snapshot | CSV em `dashboard/dados/` + `manifest.json`; parquet; GCS público | **CSV no repositório**: diffável, sem credencial, sem pyarrow no app |
| C7 | Resultados do backtest e das sensibilidades | (a) copiar para o snapshot; (b) ler direto de `docs/resultados/` | **(b)**: fonte única, o hash do pré-registro vem do log |
| C8 | Credencial | (a) conta de serviço nos secrets; (b) nenhuma no app | **(b)**; D linha 97 (perfil dev/prod do dbt) **não muda**: o consumo externo não passa pelo BigQuery |
| C9 | Biblioteca de gráficos | Altair (vem com o Streamlit); Plotly | **Altair**: declarativo, o spec é testável sem navegador |
| C10 | "Prévia ao vivo" | (a) consulta ao vivo; (b) "prévia do snapshot de <data>" | **(b)**, com o aviso de origem atrasada |
| C11 | Registro da saúde do pipeline | (a) tabela nova no BigQuery; (b) `cp` na DAG + `psql` no snapshot; (c) só o snapshot lendo o `run_results.json` local e o Postgres | **(c) APROVADO:** a DAG não muda; a página mostra "estado em <data do snapshot>" e a data do `run_results.json` lido |
| C12 | Cobertura dos intervalos na página | (a) a nominal; (b) a observada com a calibração de produção (70,8% e 90,5%); (c) a observada fora da amostra | **(c) APROVADO:** 70,2% (nominal 80%) e 87,8% (nominal 95%), calibrados só no desenvolvimento, com a fonte na tela; os 70,8%/90,5% não entram (a calibração já viu o teste) |
| C13 | Reservatórios | (a) criar a tabela; (b) dizer que não existem | **(b)** |
| C14 | Regras de honestidade da interface | só rodapé; ressalva no bloco do número, sem ranking | a segunda, com texto único e teste (seção 4) |
| C15 | Dependências | (a) `streamlit` no grupo padrão e na imagem do Airflow; (b) grupo `dashboard` fora da imagem, mais `dashboard/requirements.txt` pinado | **(b)** |
| C16 | 6.8 | (a) dentro da Parte C; (b) fora | **(b)**; se entrar, vira o único ponto com leitura ao vivo (opção (c)) |

**Pendências (11/10/2026):** C1, C3, C5, C11 e C12 **aprovadas**; snapshot mensal confirmado. Resta a **varredura de segredos antes de tornar o repositório público** (comando acima) e a decisão sobre o e-mail de autor `felipe.inserti@gmail.com` que o histórico expõe.
