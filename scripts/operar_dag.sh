#!/usr/bin/env bash
# Opera e mede a DAG `energia_livre_diaria` no Airflow LOCAL (docker compose). Ferramenta permanente
# (Sprint 4, passo 8). As execuções da DAG GRAVAM NA PRODUÇÃO (partições do raw, bronze se o arquivo
# do ONS mudou, dbt em staging e marts), de forma idempotente. Um subcomando por vez:
#
#   bash scripts/operar_dag.sh subir               # sobe, confere import e fuso, ativa a DAG
#   bash scripts/operar_dag.sh normal              # execução manual normal
#   bash scripts/operar_dag.sh backfill [DESDE ATE]  # conf {"desde","ate"} (padrão: 2026-07 a 2026-08)
#   bash scripts/operar_dag.sh completa            # conf {"execucao_completa": true} (dbt sem seleção)
#   bash scripts/operar_dag.sh falha               # falha proposital: o alerta do Discord tem de chegar
#   bash scripts/operar_dag.sh medir [RUN_ID]      # resume uma execução (a última, se omitir)
#   bash scripts/operar_dag.sh parar               # docker compose down
#
# Cada execução termina com o resumo (tempo de cada task e bytes do dbt) contra o "antes" da Sprint 3:
# DAG 6 min 40 s, ons_ingestao 4 min 22 s, dbt 194 jobs, 1.557,9 MB processados e 2.965,4 MB faturados.
# Logs em data/logs/dag_*. Precisa do Airflow no ar (os scripts de manutenção do raw exigem o contrário).
set -Eeuo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
mkdir -p data/logs
set -a
. ./.env
set +a

L=data/logs/dag
DAG_ID=energia_livre_diaria

# nenhuma falha silenciosa: mostra o arquivo, a linha, o comando e o código
registrar_erro() { echo "### ERRO (código $1) em $2, linha $3: $4" >&2; }
trap 'registrar_erro "$?" "${BASH_SOURCE[0]##*/}" "$LINENO" "$BASH_COMMAND"' ERR

py() { uv run --env-file .env python -m "$@"; }
exigir_docker() {
    docker info >/dev/null 2>&1 || {
        echo "ABORTADO: o Docker não responde (abra o Docker Desktop e ligue a integração com o WSL)"
        exit 1
    }
}
af() { docker compose exec -T airflow-scheduler airflow "$@"; }
pg() { docker compose exec -T postgres psql -U airflow -d airflow -tA "$@"; }

estado_do_run() { pg -c "select state from dag_run where run_id='$1'" || true; }

aguardar_run() { # aguardar_run <run_id> [limite em segundos]
    local run_id="$1" limite="${2:-2400}" inicio estado
    inicio=$(date +%s)
    while :; do
        estado=$(estado_do_run "$run_id")
        case "$estado" in
            success | failed)
                echo "execução $run_id: $estado"
                return 0
                ;;
        esac
        if [ $(( $(date +%s) - inicio )) -ge "$limite" ]; then
            echo "TEMPO ESGOTADO esperando $run_id (estado: ${estado:-desconhecido})"
            exit 1
        fi
        sleep 15
    done
}

exigir_dag_livre() {
    local pausada ativas
    pausada=$(pg -c "select is_paused from dag where dag_id='$DAG_ID'" || true)
    if [ "$pausada" != "f" ]; then
        echo "ABORTADO: a DAG não está ativa (is_paused='${pausada:-?}'). Rode antes: bash scripts/operar_dag.sh subir"
        exit 1
    fi
    ativas=$(pg -c "select count(*) from dag_run where dag_id='$DAG_ID' and state in ('running','queued')" || true)
    if [ "${ativas:-0}" != "0" ]; then
        echo "ABORTADO: já há $ativas execução(ões) em andamento; espere terminar (a DAG aceita uma por vez)"
        exit 1
    fi
}

# Execução agendada que o Airflow criou DEPOIS do marco: só conta quem tem `id` maior que o maior `id`
# que existia antes de ativar a DAG. (Pegar "a última agendada" devolvia a execução ANTIGA da Sprint 3
# quando nenhuma nova era criada, e a comparava com ela mesma: +0%.) Devolve vazio se não houver.
maior_id_de_execucao() { pg -c "select coalesce(max(id),0) from dag_run" || echo 0; }
execucao_agendada_nova() { # execucao_agendada_nova <maior id de antes>
    pg -c "select run_id from dag_run where dag_id='$DAG_ID' and run_type='scheduled' and id > $1 order by id desc limit 1" || true
}

# resumo de uma execução: <run_id> <rotulo> [sucesso|falha]
medir_run() {
    local run_id="$1" rotulo="$2" esperado="${3:-sucesso}" dag inicio fim
    dag=$(pg -F '|' -c "select state, to_char(start_date at time zone 'UTC','YYYY-MM-DD\"T\"HH24:MI:SS'), to_char(end_date at time zone 'UTC','YYYY-MM-DD\"T\"HH24:MI:SS'), round(extract(epoch from end_date-start_date)::numeric,1) from dag_run where run_id='$run_id'")
    if [ -z "$dag" ]; then
        echo "ABORTADO: não existe a execução '$run_id'"
        exit 1
    fi
    pg -F '|' -c "select ti.task_id, ti.state, coalesce(ti.try_number,0), coalesce(round(ti.duration::numeric,1),0) from task_instance ti where ti.run_id='$run_id' order by ti.start_date nulls last" >"${L}_${rotulo}_tarefas.txt" || true
    inicio=$(echo "$dag" | cut -d'|' -f2)
    fim=$(echo "$dag" | cut -d'|' -f3)
    py scripts.medir_bytes_bigquery --desde "$inicio" --ate "$fim" >"${L}_${rotulo}_bytes.log" 2>&1
    py scripts.resumir_execucao_dag --rotulo "$rotulo" --dag "$dag" --tarefas "${L}_${rotulo}_tarefas.txt" --bytes "${L}_${rotulo}_bytes.log" --esperado "$esperado" | tee "${L}_${rotulo}_resumo.txt"
}

disparar() { # disparar <rotulo> <esperado> [json da configuração]
    local rotulo="$1" esperado="$2" conf="${3:-}" run_id
    exigir_docker
    exigir_dag_livre
    run_id="manual__${rotulo}_$(date -u +%Y%m%dT%H%M%S)"
    echo "disparando $run_id ${conf:+com a configuração $conf}"
    if [ -n "$conf" ]; then
        af dags trigger "$DAG_ID" --run-id "$run_id" --conf "$conf" >"${L}_${rotulo}_trigger.log" 2>&1
    else
        af dags trigger "$DAG_ID" --run-id "$run_id" >"${L}_${rotulo}_trigger.log" 2>&1
    fi
    echo "$run_id" >"${L}_${rotulo}_run_id.txt"
    sleep 5
    aguardar_run "$run_id"
    medir_run "$run_id" "$rotulo" "$esperado"
}

subcomando="${1:-}"
case "$subcomando" in
    subir)
        exigir_docker
        echo "##### 1) subindo o Airflow (docker compose up -d; sem rebuild se só o código mudou)"
        docker compose up -d >"${L}_subir.log" 2>&1 || { tail -20 "${L}_subir.log"; exit 1; }
        echo "##### 2) esperando o api-server ficar saudável"
        for _ in $(seq 1 24); do
            if [ "$(docker compose ps airflow-apiserver --format '{{.Health}}' || true)" = "healthy" ]; then
                break
            fi
            sleep 10
        done
        docker compose ps --format 'table {{.Service}}\t{{.State}}\t{{.Health}}'
        echo "##### 3) esperando o dag-processor ler a DAG"
        for _ in $(seq 1 24); do
            if af dags list 2>/dev/null | grep -q "$DAG_ID"; then
                break
            fi
            sleep 10
        done
        echo "##### 4) erros de importação da DAG (esperado: No data found)"
        af dags list-import-errors 2>&1 | tee "${L}_import.log"
        grep -q "No data found" "${L}_import.log" || { echo "ERRO: a DAG tem erro de importação"; exit 1; }
        echo "##### 5) pré-checagem DENTRO da imagem: o fuso e a janela da ingestão (o uv.lock só traz tzdata no Windows)"
        docker compose exec -T -w /opt/projeto airflow-scheduler /opt/projeto-venv/bin/python -c "
from zoneinfo import ZoneInfo
ZoneInfo('America/Sao_Paulo')
print('fuso America/Sao_Paulo disponível no container')" || {
            echo "ERRO: sem banco de fusos no container. Conserto: declarar 'tzdata' em pyproject.toml, 'uv lock' e 'docker compose build' (rebuild só neste caso)"
            exit 1
        }
        docker compose exec -T -w /opt/projeto airflow-scheduler /opt/projeto-venv/bin/python -m ingestion.janela --formato dbt-vars --data-referencia 2026-10-07 | cut -c1-110
        echo "##### 6) ativando a DAG (se o horário das 21:00 UTC já passou, o Airflow pode criar sozinho uma execução agendada)"
        marco=$(maior_id_de_execucao)
        af dags unpause "$DAG_ID" >"${L}_unpause.log" 2>&1 || true
        sleep 30
        agendada=$(execucao_agendada_nova "$marco")
        if [ -n "$agendada" ]; then
            echo "o Airflow criou a execução agendada $agendada (id maior que $marco): esperando e medindo"
            aguardar_run "$agendada"
            medir_run "$agendada" agendada sucesso
        else
            echo "nenhuma execução agendada NOVA foi criada (as anteriores a este 'subir' não contam): o próximo passo é 'normal'"
        fi
        echo "SUBIR OK"
        ;;
    normal)
        disparar normal sucesso
        echo "NORMAL OK"
        ;;
    backfill)
        desde="${2:-2026-07}"
        ate="${3:-2026-08}"
        padrao_mes='^[0-9]{4}-(0[1-9]|1[0-2])$'
        if ! [[ "$desde" =~ $padrao_mes && "$ate" =~ $padrao_mes ]]; then
            echo "ABORTADO: use meses no formato AAAA-MM (recebi desde='$desde' ate='$ate')"
            exit 2
        fi
        disparar backfill sucesso "{\"desde\":\"$desde\",\"ate\":\"$ate\"}"
        echo "BACKFILL OK"
        ;;
    completa)
        disparar completa sucesso '{"execucao_completa": true}'
        echo "COMPLETA OK"
        ;;
    falha)
        disparar falha falha '{"falha_proposital": true}'
        echo "O alerta no Discord é conferido por você: a mensagem 'Falha no pipeline energia_livre_diaria' (task dbt_test)."
        echo "Pelo log do Airflow (o callback imprime isso quando o webhook falha):"
        grep -rl "alerta no Discord não enviado" "airflow/logs/dag_id=$DAG_ID/run_id=$(cat "${L}_falha_run_id.txt")" 2>/dev/null \
            && echo "ATENÇÃO: o envio do alerta FALHOU (webhook vazio ou errado)" \
            || echo "o log não registra falha no envio do alerta (confira a chegada no Discord)"
        echo "FALHA OK"
        ;;
    medir)
        exigir_docker
        alvo="${2:-$(pg -c "select run_id from dag_run where dag_id='$DAG_ID' order by id desc limit 1")}"
        medir_run "$alvo" medida sucesso
        echo "MEDIR OK"
        ;;
    parar)
        exigir_docker
        docker compose down
        echo "PARAR OK"
        ;;
    *)
        echo "uso: operar_dag.sh subir | normal | backfill [DESDE ATE] | completa | falha | medir [RUN_ID] | parar"
        exit 2
        ;;
esac
