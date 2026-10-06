# Runbook do Airflow local (Sprint 3, Parte B)

Como subir, rodar e parar o Airflow do projeto. Todos os comandos partem da **raiz do repositório**
(`/home/felipe/projetos/energia-livre-dados`). As decisões por trás de cada escolha estão em
`docs/decisoes.md` (seções "Airflow local", "Horário da DAG", "Retentativas e alerta" e "Arquivos
manuais").

Pré-requisitos: Docker Desktop aberto no Windows, com a integração com a sua distro do WSL ligada
(`docker --version` e `docker compose version` funcionam dentro do WSL), e `gcloud auth
application-default login` já feito (o arquivo
`~/.config/gcloud/application_default_credentials.json` precisa existir).

Convenção: os comandos gravam a saída em `data/logs/` com `tee`, para eu poder conferir os números.

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

**Esperado:** a execução termina em `success`, em torno de **6 min 40 s** (medido em 06/10/2026):

| Task | Estado | Duração aproximada |
|---|---|---|
| `ons_ingestao` | success | ~4 min 22 s (download 48 s, GCS 9 s, BigQuery 194 s; o bronze só grava o que mudou) |
| `ccee_ha_arquivo_novo`, `inmet_ha_arquivo_novo` | success | ~4 s |
| `ccee_ingestao`, `ccee_registrar_estado`, `inmet_ingestao`, `inmet_registrar_estado` | skipped | 0 |
| `freshness_ons` | success | ~11 s |
| `dbt_run` | success | ~37 s |
| `dbt_test` | success | ~1 min 28 s (PASS=173, WARN=1, ERROR=0; o `warn` é o das 10 estações do INMET) |
| `freshness_manuais` | success | ~8 s (em paralelo ao `dbt_test`) |
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

**Esperado (medido em 06/10/2026):** duas linhas e o total:

```
dbt                               194 jobs (0 com erro) | processados    1557.9 MB | faturados    2965.4 MB
outros (ingestão, freshness)        1 jobs (0 com erro) | processados      65.0 MB | faturados      66.1 MB
total                            processados 1622.9 MB | faturados 3031.4 MB
```

O faturado é quase o dobro do processado por causa do piso de 10 MiB por job (194 jobs do dbt). O
intervalo inclui a execução do passo 6 e as seguintes; para medir só uma execução, passe também `--ate`
com o horário de fim (sem ele, vale "agora"). A própria consulta lê cerca de 0,6 MB de metadados.

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
estiver desligado às 21:00 UTC, a execução daquele dia não acontece; a próxima carga full recupera o
que faltou (ver `docs/decisoes.md`, "Horário da DAG e a limitação do Airflow local").

### Se a credencial do GCP expirar

Os erros de autenticação nas tasks (`DefaultCredentialsError` ou `invalid_grant` no log) se resolvem
renovando o ADC no WSL, sem mexer no container (o arquivo é montado do seu `~/.config/gcloud/`):

```bash
gcloud auth application-default login
```

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
