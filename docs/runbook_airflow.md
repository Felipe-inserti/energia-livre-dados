# Runbook do Airflow local (Sprint 3, Parte B; atualizado na Sprint 4, Parte A)

Como subir, rodar e parar o Airflow do projeto. Todos os comandos partem da **raiz do repositório**
(`/home/felipe/projetos/energia-livre-dados`). As decisões por trás de cada escolha estão em
`docs/decisoes.md` (seções "Airflow local", "Horário da DAG", "Retentativas e alerta" e "Arquivos
manuais").

Pré-requisitos: Docker Desktop aberto no Windows, com a integração com a sua distro do WSL ligada
(`docker --version` e `docker compose version` funcionam dentro do WSL), e `gcloud auth
application-default login` já feito (o arquivo
`~/.config/gcloud/application_default_credentials.json` precisa existir).

Convenção: os comandos gravam a saída em `data/logs/` com `tee`, para eu poder conferir os números.

**Desde a Sprint 4 a DAG roda a ingestão do ONS em modo janela (3 meses) e o dbt só do que mudou.** O dia a dia
(subir, rodar, medir, backfill, falha proposital) tem um script: `bash scripts/operar_dag.sh <subcomando>` (seção
"Operar a DAG pelo script", abaixo). Os passos numerados a seguir continuam valendo para a primeira instalação.
Operações do raw e do dbt fora da DAG (janela manual, backfill pela CLI, carga full, execução completa,
restauração do backup) estão em "Operações da ingestão incremental".

---

## Passo 0. Webhook do Discord e teste do alerta

Edite `airflow/.env` e preencha a linha `DISCORD_WEBHOOK_URL=` com a URL do webhook. Esse arquivo é
ignorado pelo git e nunca deve ser colado em chat, issue ou commit.

```bash
nano airflow/.env
```

Se o arquivo não existir, gere-o primeiro (não sobrescreve um existente):

```bash
uv run python -m scripts.gerar_env_airflow
```

Teste o alerta, sem subir nada:

```bash
uv run --env-file airflow/.env python -m ingestion.orquestracao testar-alerta
```

**Esperado:** a saída `mensagem enviada` e uma mensagem vermelha no canal do Discord com o texto
"Falha no pipeline `?`", a task `?` e o erro "teste do alerta (nenhuma falha de verdade)". Se der
`mensagem NÃO enviada`, a URL está vazia ou errada (o comando nunca imprime a URL).

---

## Passo 1. Estado inicial dos arquivos manuais

Registra que os arquivos que já estão em `data/manual/` foram carregados nas Sprints 1 e 2. Sem isso,
a primeira execução da DAG recarregaria os 536 MB do INMET.

```bash
uv run python -m ingestion.orquestracao registrar-estado ccee inmet
```

**Esperado:**

```
ccee: estado registrado com 10 arquivos
inmet: estado registrado com 6 arquivos
```

Os estados ficam em `data/estado/ccee.json` e `data/estado/inmet.json`.

---

## Passo 2. Build da imagem

```bash
{ time docker compose build; } 2>&1 | tee data/logs/airflow_build_3.5.log
```

```bash
docker image ls energia-livre-airflow
```

**Esperado:** na primeira vez baixa a imagem do Airflow (1 a 2 GB), instala as dependências do venv do
projeto (`uv sync --frozen`) e termina com `energia-livre-airflow:3.3.2`. Estimativa: 3 a 8 minutos.
Anote o tempo `real` que o `time` imprime no fim e o tamanho da imagem no `docker image ls`.

---

## Passo 3. Init: migrar o banco e instalar os pacotes do dbt

```bash
docker compose up airflow-init 2>&1 | tee data/logs/airflow_init_3.5.log
```

**Esperado:** o Postgres sobe e fica saudável, aparecem as linhas do `airflow db migrate`
(`Database migrating done!`), depois `Installing dbt-labs/dbt_utils` do `dbt deps`, e por fim
`airflow-init-1 exited with code 0`. Código diferente de 0 significa erro: mande o log.

---

## Passo 4. Subir os serviços e conferir

```bash
docker compose up -d 2>&1 | tee data/logs/airflow_up_3.5.log
```

```bash
sleep 60; docker compose ps 2>&1 | tee -a data/logs/airflow_up_3.5.log
```

```bash
docker compose exec airflow-scheduler airflow dags list-import-errors 2>&1 | tee data/logs/airflow_import_3.5.log
```

**Esperado:**

- `docker compose ps` mostra postgres, airflow-apiserver, airflow-scheduler e airflow-dag-processor em
  `Up`. O api-server passa a `healthy` em até 1 minuto. O `airflow-init` aparece como `Exited (0)`,
  o que é normal.
- A UI abre em http://localhost:8080 sem pedir login (veja "Abrir a UI" abaixo).
- `list-import-errors` responde `No data found`: a DAG importou sem erro.

---

## Passo 5. Ativar a DAG

```bash
docker compose exec airflow-scheduler airflow dags unpause energia_livre_diaria 2>&1 | tee data/logs/airflow_unpause_3.6.log
```

**Saída:** o comando imprime `is_paused=True`; é o estado **anterior** (o `unpause` acabou de
desativar a pausa), não o atual. Confira na UI ou na consulta abaixo.

**Atenção:** se o horário de hoje (21:00 UTC) já passou, o Airflow cria na hora a execução `scheduled`
daquele dia. Com `catchup=False`, o Airflow pode criar uma execução na hora, para o último horário de
21:00 UTC que ficou para trás. Se isso acontecer, essa é a sua primeira execução completa e você pode
pular o passo 6. Confira:

```bash
sleep 20; docker compose exec -T postgres psql -U airflow -d airflow -c "select run_id, state, run_type, start_date from dag_run order by start_date desc limit 3"
```

**Esperado:** uma linha `scheduled__...` em `running` (então siga para as durações do passo 6, sem
disparar de novo) ou nenhuma linha (então rode o passo 6).

---

## Passo 6. Execução manual completa

```bash
docker compose exec airflow-scheduler airflow dags trigger energia_livre_diaria 2>&1 | tee data/logs/airflow_trigger_3.6.log
```

Espere a execução terminar (confere o estado a cada 15 segundos):

```bash
until docker compose exec -T postgres psql -U airflow -d airflow -tAc "select state from dag_run order by start_date desc limit 1" | grep -qE "success|failed"; do sleep 15; done; echo terminou
```

Duração de cada task:

```bash
docker compose exec -T postgres psql -U airflow -d airflow -c "select ti.task_id, ti.state, ti.try_number as tentativa, round(ti.duration::numeric,1) as segundos from task_instance ti join dag_run dr on dr.dag_id=ti.dag_id and dr.run_id=ti.run_id where dr.run_id=(select run_id from dag_run order by start_date desc limit 1) order by ti.start_date" 2>&1 | tee data/logs/airflow_duracoes_3.6.log
```

Duração da DAG inteira (as últimas 3 execuções):

```bash
docker compose exec -T postgres psql -U airflow -d airflow -c "select run_id, state, round(extract(epoch from end_date-start_date)::numeric,1) as segundos from dag_run order by start_date desc limit 3" 2>&1 | tee -a data/logs/airflow_duracoes_3.6.log
```

**Esperado (Sprint 4, medido em 07/10/2026):** a execução termina em `success`, em torno de **1 min 33 s** (era 6 min 40 s na
Sprint 3: o arquivo antigo, de 06/10, está só no histórico do `docs/metricas.md`):

| Task | Estado | Duração aproximada |
|---|---|---|
| `parametros_execucao` | success | ~4 s (decide o modo e a data de referência) |
| `ons_ingestao` | success | ~20 s (janela de 3 meses: 1 arquivo, ~1,2 MB, 3 load jobs; confere 26 anos fechados por HEAD em ~2,4 s) |
| `ccee_ha_arquivo_novo`, `inmet_ha_arquivo_novo` | success | ~4 s |
| `ccee_ingestao`, `ccee_registrar_estado`, `inmet_ingestao`, `inmet_registrar_estado` | skipped | 0 |
| `selecao_dbt` | success | ~0 s (só o ONS no dia comum; mais INMET e/ou CCEE se houve arquivo novo) |
| `freshness_ons` | success | ~10 s |
| `dbt_run` | success | ~36 s (3 modelos do ONS) |
| `dbt_test` | success | ~20 s (27 testes, PASS=27; a seleção sempre inclui o teste do alerta) |
| `freshness_manuais` | success | ~10 s (em paralelo ao `dbt_test`) |
| `pipeline_ok` | success | 0 |

Se alguma coluna da consulta não existir nesta versão do Airflow, copie o erro e me mande.

---

## Passo 7 (opcional). Provar o ramo dos arquivos manuais

Muda a data de modificação de um arquivo da CCEE, o que faz a DAG recarregar a CCEE (~1,2 min). A
carga é full e idempotente, então não há efeito colateral.

```bash
touch data/manual/ccee/consumo_ramo_atividade_2026.csv
```

```bash
docker compose exec airflow-scheduler airflow dags trigger energia_livre_diaria 2>&1 | tee data/logs/airflow_trigger_ccee_3.6.log
```

**Esperado:** `ccee_ha_arquivo_novo`, `ccee_ingestao` e `ccee_registrar_estado` rodam (success), e as
três tasks do INMET ficam `skipped`. Use o mesmo `until ...` do passo 6 para esperar o fim, e a mesma
consulta de durações para ver os números.

---

## Passo 8. Teste de falha proposital

Espere a execução anterior terminar (a DAG tem `max_active_runs=1`).

```bash
docker compose exec airflow-scheduler airflow dags trigger energia_livre_diaria --conf '{"falha_proposital": true}' 2>&1 | tee data/logs/airflow_falha_3.7.log
```

```bash
until docker compose exec -T postgres psql -U airflow -d airflow -tAc "select state from dag_run order by start_date desc limit 1" | grep -qE "success|failed"; do sleep 15; done; echo terminou
```

```bash
docker compose exec -T postgres psql -U airflow -d airflow -c "select ti.task_id, ti.state, round(ti.duration::numeric,1) as segundos, ti.end_date from task_instance ti where ti.run_id=(select run_id from dag_run order by start_date desc limit 1) order by ti.start_date" 2>&1 | tee -a data/logs/airflow_falha_3.7.log
```

**Esperado:**

- a execução termina em `failed`;
- `dbt_test` em `failed`, sem nova tentativa (`try_number` 1), com `Got 1 result, configured to fail if != 0`
  no log;
- `pipeline_ok` em `upstream_failed`: a falha interrompeu o pipeline;
- `freshness_manuais` em `success`, porque depende só do `dbt_run`;
- **uma única mensagem** no Discord, referente à task `dbt_test`, chegando segundos depois do `end_date`
  dela (as tasks `upstream_failed` não avisam de novo).

Anote a hora em que a mensagem chegou no Discord para eu registrar a latência do alerta.

---

## Passo 9. Custo no BigQuery de uma execução

Use como `--desde` o horário de início (UTC) da execução do passo 6, que aparece na coluna `start_date`
da consulta do passo 5. Formato `AAAA-MM-DDTHH:MM:SS`.

```bash
uv run --env-file .env python -m scripts.medir_bytes_bigquery --desde AAAA-MM-DDTHH:MM:SS 2>&1 | tee data/logs/airflow_bytes_3.6.log
```

**Esperado (Sprint 4, execução normal de 07/10/2026):** o dbt, a freshness e as validações da ingestão:

```
dbt                                36 jobs (0 com erro) | processados     284.8 MB | faturados     504.4 MB
outros (ingestão, freshness)        2 jobs (0 com erro) | processados      11.0 MB | faturados      21.0 MB
total                            processados 295.8 MB | faturados 525.3 MB
```

(Na Sprint 3 eram 194 jobs, 1.557,9 MB processados e 2.965,4 MB faturados no dbt: o "antes" de `docs/metricas.md`.) O
`scripts/operar_dag.sh medir` faz esta conta por execução, com o intervalo de início e fim dela.

O faturado é quase o dobro do processado por causa do piso de 10 MiB por job. O
intervalo inclui a execução do passo 6 e as seguintes; para medir só uma execução, passe também `--ate`
com o horário de fim (sem ele, vale "agora"). A própria consulta lê cerca de 0,6 MB de metadados.

---

## Operar a DAG pelo script

`scripts/operar_dag.sh` sobe o Airflow e dispara, espera e mede as execuções. **As execuções gravam na produção**
(partições do `raw.ons_curva_carga`, o bronze se o arquivo do ONS mudou, e o dbt em `staging` e `marts`), de forma
idempotente. Um subcomando por vez:

```bash
bash scripts/operar_dag.sh subir
```

```bash
bash scripts/operar_dag.sh normal
```

```bash
bash scripts/operar_dag.sh backfill 2026-07 2026-08
```

```bash
bash scripts/operar_dag.sh falha
```

```bash
bash scripts/operar_dag.sh medir
```

```bash
bash scripts/operar_dag.sh parar
```

- `subir`: `docker compose up -d` (sem rebuild), espera o api-server, confere `airflow dags list-import-errors`
  (esperado: `No data found`), faz a **pré-checagem do fuso dentro da imagem** e ativa a DAG. Se o horário das 21:00 UTC
  já passou, o Airflow pode criar uma execução agendada na hora; o script só mede uma execução criada **depois** do
  `subir` (com `id` maior que o de antes de ativar a DAG), nunca uma antiga.
- `normal`, `backfill [DESDE ATE]` (padrão 2026-07 a 2026-08), `completa` (`execucao_completa`) e `falha`: disparam uma execução
  manual com `--run-id` próprio, esperam e imprimem o resumo: tempo de cada task e bytes do dbt contra o "antes" da
  Sprint 3 (DAG 6 min 40 s, `ons_ingestao` 4 min 22 s, dbt 194 jobs, 1.557,9 MB processados e 2.965,4 MB faturados). Os
  logs vão para `data/logs/dag_*`.
- `falha` espera `dbt_test` em `failed` sem retentativa, `pipeline_ok` em `upstream_failed` **e a mensagem no Discord**
  (a conferência do Discord é sua).
- `medir [RUN_ID]` resume uma execução que já existe (a última, se omitir).
- `parar`: `docker compose down` (mantém o histórico das execuções).

**Rebuild da imagem:** só quando mudar `pyproject.toml`, `uv.lock` ou o `Dockerfile`. Mudar `ingestion/`, `dbt/` ou a DAG
não exige nada (o repositório é montado em `/opt/projeto`). Se a pré-checagem do `subir` disser que não há banco de
fusos no container, declare `tzdata` no `pyproject.toml`, rode `uv lock` e `docker compose build` (o `uv.lock` só traz o
`tzdata` para Windows; até agora o fuso do sistema da imagem bastou).

### Configuração de uma execução manual

`airflow dags trigger energia_livre_diaria --conf '<json>'` (ou os campos do formulário na UI):

| Configuração | Efeito |
|---|---|
| `{"desde": "2026-07", "ate": "2026-08"}` | backfill dos meses, inclusive (AAAA-MM, os dois juntos; validados antes de virar linha de comando) |
| `{"execucao_completa": true}` | `dbt run` e `dbt test` **sem seleção**: roda também os 62 testes de calendário, seeds e dimensões estáticas que nenhuma fonte seleciona (convém de vez em quando e depois de mudar o código do dbt) |
| `{"falha_proposital": true}` | o `dbt_test` falha de propósito, para provar o alerta do Discord |

---

## Operações da ingestão incremental

Todas partem da raiz, com o `.env` carregado (`uv run --env-file .env`). A ingestão sempre loga, na primeira linha, o
**destino completo e o modo** (`janela`, `backfill` ou `full`).

**Janela manual** (a mesma que a DAG roda; a data de referência padrão é hoje em UTC, só na linha de comando):

```bash
uv run --env-file .env python -m ingestion.ons --sem-medicao --saida-vars data/logs/vars_janela.json 2>&1 | tee data/logs/ons_janela.log
```

Depois o dbt, com as vars que a ingestão gravou (sem elas o staging incremental **falha de propósito**):

```bash
uv run --env-file .env dbt run --select source:raw.ons_curva_carga+ --vars "$(cat data/logs/vars_janela.json)" --project-dir dbt --profiles-dir dbt
```

```bash
uv run --env-file .env dbt test --select source:raw.ons_curva_carga+ teste_alerta_falha_proposital --project-dir dbt --profiles-dir dbt
```

**Backfill pela linha de comando** (meses AAAA-MM, inclusive; concorrência 8 por padrão). Medido: 2021-01 a 2026-10 em ~125 s
(ingestão 74 s + dbt 51 s):

```bash
uv run --env-file .env python -m ingestion.ons --desde 2021-01 --ate 2026-10 --sem-medicao --saida-vars data/logs/vars_backfill.json 2>&1 | tee data/logs/ons_backfill.log
```

```bash
uv run --env-file .env dbt run --select source:raw.ons_curva_carga+ --vars "$(cat data/logs/vars_backfill.json)" --project-dir dbt --profiles-dir dbt
```

Se um mês falhar, a ingestão termina com erro e **lista os meses que falharam**; reexecutar é seguro (cada load job substitui a
sua partição, e os meses que já passaram ficam como estão).

**Carga full** (2000 até hoje; trunca a tabela particionada e recarrega os 27 anos, ~94 s). Use para reconstruir o raw ou
depois de uma restauração; depois reconstrua o staging, que **não precisa de vars** com `--full-refresh`:

```bash
uv run --env-file .env python -m ingestion.ons --full --sem-medicao 2>&1 | tee data/logs/ons_full.log
```

```bash
uv run --env-file .env dbt run --select stg_ons__curva_carga fct_carga_horaria fct_submercado_horario --full-refresh --project-dir dbt --profiles-dir dbt
```

**Execução completa do dbt** (os 62 testes que nenhuma fonte seleciona), pela DAG: `bash scripts/operar_dag.sh completa`; ou
pela linha de comando (precisa das vars da janela):

```bash
uv run --env-file .env dbt run --vars "$(cat data/logs/vars_janela.json)" --project-dir dbt --profiles-dir dbt && uv run --env-file .env dbt test --project-dir dbt --profiles-dir dbt
```

**Conferir a produção sem gravar nada** (retrato do raw, `stg_ons`, `fct_carga` e `fct_submercado` por mês × submercado, e a
comparação com um retrato anterior; só leitura, ~130 MB por retrato):

```bash
uv run --env-file .env python -m scripts.snapshot_producao snapshot --saida data/logs/retrato_agora.json
```

```bash
uv run --env-file .env python -m scripts.snapshot_producao comparar --a data/logs/retrato_antes.json --b data/logs/retrato_agora.json --informativo-desde 2026-01
```

Os meses a partir de `--informativo-desde` só informam quando o valor muda (o ONS revisa e acrescenta dados no ano corrente),
mas **perder linhas reprova**.

**Restaurar o raw a partir do backup** (só enquanto `raw.ons_curva_carga_backup` existir; ele é a tabela de antes da migração,
**sem partição**, de 07/10/2026). Isto volta ao estado antigo; o código novo recusa uma tabela sem partição (código 2), então
depois é preciso refazer a migração (`--full` cria a tabela particionada de novo):

```bash
bq --project_id="$GCP_PROJECT_ID" rm -f -t raw.ons_curva_carga
```

```bash
bq --project_id="$GCP_PROJECT_ID" cp -f raw.ons_curva_carga_backup raw.ons_curva_carga
```

Para refazer a migração do zero (a tabela de produção é trocada por uma particionada): faça a cópia de segurança, confira
o backup mês a mês, apague a tabela e rode a carga full acima. **Nunca** copie com `bq cp` entre uma tabela comum e uma
particionada (falha com "Failed to copy Non partitioned table to Column partitioned table: not supported", e o `bq`
escreve essa mensagem no stdout).

**Se uma execução falhar depois de o dbt apagar o staging** (o `--full-refresh` de uma tabela com outro particionamento faz
`drop` e `create`): a tabela é derivada do raw, então basta repetir o mesmo `--full-refresh`.

---

## Operação do dia a dia

### Abrir a UI

Abra http://localhost:8080 no navegador do Windows. Não há login: a porta só escuta em `127.0.0.1`
(`docker-compose.yml`). Na UI, clique em `energia_livre_diaria` para ver as execuções, o grafo das
tasks e o log de cada uma.

### Ver os logs de uma task

Pela UI: execução → clique na task → aba **Logs**.

Pelo terminal, os logs ficam em arquivos na sua máquina, em `airflow/logs/` (pasta ignorada pelo git):

```bash
ls airflow/logs
```

```bash
find airflow/logs -path "*task_id=dbt_test*" -name "*.log" | sort | tail -3
```

```bash
tail -n 60 "$(find airflow/logs -path '*task_id=dbt_test*' -name '*.log' | sort | tail -1)"
```

Troque `dbt_test` pelo nome da task (`ons_ingestao`, `dbt_run`, `freshness_ons`...). Os logs dos
serviços (scheduler, api-server) saem assim:

```bash
docker compose logs --tail 100 airflow-scheduler
```

```bash
docker compose logs --tail 100 airflow-apiserver
```

```bash
docker compose logs --tail 100 airflow-dag-processor
```

### Parar

Para os containers e remove-os, **mantendo** o banco do Airflow (histórico das execuções), que fica no
volume `postgres-dados`:

```bash
docker compose down
```

Para parar sem remover os containers (volta mais rápido):

```bash
docker compose stop
```

Para apagar tudo, inclusive o histórico das execuções (o próximo `up` recomeça do zero e exige rodar o
init de novo):

```bash
docker compose down --volumes
```

### Subir de novo depois de reiniciar o PC

1. Abra o Docker Desktop no Windows e espere o ícone indicar "Engine running".
2. No WSL, na raiz do repositório:

```bash
docker compose up -d
```

```bash
docker compose ps
```

Não precisa de novo build nem de novo init: a imagem e o banco foram mantidos. Só rode o passo 3
(`airflow-init`) de novo se tiver usado `down --volumes`, e o passo 2 (`build`) se mudar o `Dockerfile`,
o `pyproject.toml` ou o `uv.lock`. A DAG continua ativa (o estado "ativa" fica no banco). Se o PC
estiver desligado às 21:00 UTC, a execução daquele dia não acontece; a próxima execução recupera o que
faltou sozinha, porque a janela da ingestão é autocorretiva (começa no último mês que o raw tem e o dbt
reprocessa o mesmo intervalo; ver `docs/decisoes.md`, "Janela de segurança do incremental").

### Se a credencial do GCP expirar

Os erros de autenticação nas tasks (`DefaultCredentialsError` ou `invalid_grant` no log) se resolvem
renovando o ADC no WSL, sem mexer no container (o arquivo é montado do seu `~/.config/gcloud/`):

```bash
gcloud auth application-default login
```

O sintoma é a task falhar (ingestão ou `dbt`) com `DefaultCredentialsError`, `RefreshError`, `invalid_grant` ou
"Reauthentication is needed" no log. Depois de renovar, **limpe a task que falhou** (UI: Clear) ou dispare uma
execução nova; se o erro persistir, o container ainda enxerga o arquivo antigo (o arquivo é montado como um arquivo
só, e o `gcloud` pode tê-lo recriado): reinicie os serviços com `docker compose restart`. A ingestão e o dbt
usam o mesmo ADC (`GOOGLE_APPLICATION_CREDENTIALS=/run/gcp/adc.json`); como tudo é idempotente, repetir é seguro.
Fora do Airflow, os mesmos comandos pedem o mesmo `gcloud auth application-default login` no WSL.

### Rodar de novo uma task que falhou

Pela UI: clique na task → **Clear** (limpar). O Airflow a executa de novo, e as tasks seguintes também.
Como o pipeline é idempotente, repetir é seguro.

### Se o init falhar com `No module named 'airflow'` ou `uid not found: 1000`

O container roda com o seu uid (1000), que não existe no `/etc/passwd` da imagem. Quem cria o usuário
e exporta o `HOME=/home/airflow` é o `/entrypoint` da imagem, então **nenhum serviço do
`docker-compose.yml` pode ter `entrypoint:`** (o `airflow-init` usa `command: [bash, -c, ...]`). Teste,
sem subir nada:

```bash
docker compose run --rm --no-deps airflow-init bash -c 'echo "whoami=$(whoami) HOME=$HOME"; airflow version; airflow config list | head -3'
```

Esperado: `whoami=default HOME=/home/airflow`, a versão `3.3.2` e o início da configuração. Detalhes em
`docs/decisoes.md`, "Airflow local".
