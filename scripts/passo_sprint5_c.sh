#!/usr/bin/env bash
# Sprint 5, Parte A, Checkpoint C: valida na nuvem a previsão mensal (`fct_previsao_carga`,
# `fct_erro_previsao_carga`) e a task da DAG. GRAVA NA NUVEM (marts: 2 tabelas novas, por MERGE;
# staging: 2 tabelas temporárias que o próprio código apaga). Idempotente. Da raiz do repositório:
#
#   bash scripts/passo_sprint5_c.sh local    # testes, verificar, dry-run, gerar, conferência, idempotência
#   bash scripts/passo_sprint5_c.sh dag      # rebuild, import no container, execução normal (sem mês novo) e com falha proposital
#   bash scripts/passo_sprint5_c.sh dag-gerar --confirmo  # OPCIONAL: apaga a última previsão e a DAG a regera (ramo 'mês novo')
#   bash scripts/passo_sprint5_c.sh conferir # só as checagens de SQL (as tabelas já existem)
#
# Logs em data/logs/sprint5c_*.log (tee). Ordem recomendada: `local`, depois `dag`.
set -Eeuo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
mkdir -p data/logs
set -a
. ./.env
set +a
registrar_erro() { echo "### ERRO (código $1) em ${BASH_SOURCE[0]##*/}, linha $2: $3" >&2; }
trap 'registrar_erro "$?" "$LINENO" "$BASH_COMMAND"' ERR

L=data/logs/sprint5c
py() { uv run --env-file .env python -m "$@"; }
INICIO=$(date -u +%Y-%m-%dT%H:%M:%S)

conferir() {
    echo "== conferência das tabelas (só leitura)"
    py scripts.conferir_previsao 2>&1 | tee "${L}_conferir.log"
}

case "${1:-}" in
    local)
        echo "== 1) ruff e pytest"
        uv run ruff check . 2>&1 | tee "${L}_ruff.log"
        uv run pytest -q 2>&1 | tee "${L}_pytest.log"
        echo "== 2) há mês novo? (esperado na primeira vez: código 0)"
        CODIGO=0; py ml.previsao verificar 2>&1 | tee "${L}_verificar_antes.log" || CODIGO=$?
        echo "código de saída do verificar: $CODIGO"
        echo "== 3) dry-run (lê e mostra; não grava)"
        py ml.previsao gerar --dry-run 2>&1 | tee "${L}_dry_run.log"
        echo "== 4) gerar (grava; MERGE idempotente)"
        py ml.previsao gerar 2>&1 | tee "${L}_gerar.log"
        conferir
        echo "== 5) idempotência: a impressão digital das tabelas não pode mudar"
        py scripts.conferir_previsao --impressao 2>&1 | tee "${L}_impressao_1.log"
        py ml.previsao gerar 2>&1 | tee "${L}_gerar_2.log"          # esperado: 'já gravada: nada a fazer'
        py ml.previsao gerar --forcar 2>&1 | tee "${L}_gerar_forcar.log"  # regrava a mesma origem
        py scripts.conferir_previsao --impressao 2>&1 | tee "${L}_impressao_2.log"
        # mesma entrada => saída idêntica (FAIL se não); entrada diferente => mostra a diferença e passa
        py scripts.comparar_impressoes "${L}_impressao_1.log" "${L}_impressao_2.log"
        echo "== 6) agora NÃO há mês novo (esperado: código 10)"
        CODIGO=0; py ml.previsao verificar 2>&1 | tee "${L}_verificar_depois.log" || CODIGO=$?
        echo "código de saída do verificar: $CODIGO"; [ "$CODIGO" = "10" ] || { echo "FAIL"; exit 1; }
        conferir
        echo "== bytes processados e faturados desde $INICIO (UTC)"
        py scripts.medir_bytes_bigquery --desde "$INICIO" 2>&1 | tee "${L}_bytes.log"
        ;;
    conferir)
        conferir
        ;;
    dag)
        docker info >/dev/null 2>&1 || { echo "ABORTADO: o Docker não responde"; exit 1; }
        echo "== 1) rebuild da imagem (obrigatório: o grupo ml entrou no uv.lock)"
        docker compose build 2>&1 | tee "${L}_build.log" | tail -5
        echo "== 2) subir e conferir a DAG"
        bash scripts/operar_dag.sh subir 2>&1 | tee "${L}_subir.log"
        echo "== 3) DENTRO da imagem: statsmodels e scikit-learn presentes, lightgbm AUSENTE"
        docker compose exec -T airflow-scheduler /opt/projeto-venv/bin/python -c "
import importlib.util as u
import statsmodels, sklearn
assert u.find_spec('lightgbm') is None, 'lightgbm não deveria estar na imagem'
print('ok: statsmodels', statsmodels.__version__, '| sklearn', sklearn.__version__, '| sem lightgbm')" 2>&1 | tee "${L}_imagem.log"
        echo "== 4) pré-condição: sem mês novo (o modo local já gravou a origem; esperado: código 10)"
        CODIGO=0
        docker compose exec -T -w /opt/projeto airflow-scheduler /opt/projeto-venv/bin/python -m ml.previsao verificar 2>&1 | tee "${L}_verificar_container.log" || CODIGO=$?
        echo "código de saída: $CODIGO"
        [ "$CODIGO" = "10" ] || { echo "ABORTADO: esperava 10 (origem já gravada). Rode antes: bash $0 local"; exit 1; }
        echo "== 5) a geração DENTRO da imagem (ADC montado, libs do grupo ml, commit lido do .git): gerar --forcar"
        py scripts.conferir_previsao --impressao 2>&1 | tee "${L}_dag_impressao_1.log"
        docker compose exec -T -w /opt/projeto airflow-scheduler /opt/projeto-venv/bin/python -m ml.previsao gerar --forcar 2>&1 | tee "${L}_gerar_container.log"
        py scripts.conferir_previsao --impressao 2>&1 | tee "${L}_dag_impressao_2.log"
        py scripts.comparar_impressoes "${L}_dag_impressao_1.log" "${L}_dag_impressao_2.log"

        FALHAS=0
        pg() { docker compose exec -T postgres psql -U airflow -d airflow -tA "$@"; }
        estado_task() { pg -c "select state from task_instance where run_id='$1' and task_id='$2'" | head -1; }
        estado_run() { pg -c "select state from dag_run where run_id='$1'" | head -1; }
        # exigir <run_id> <task|DAG> <estado esperado> [estados equivalentes aceitos, separados por espaço]
        exigir() {
            local run="$1" alvo="$2" esperado="$3" aceitos="${4:-}" obtido
            if [ "$alvo" = "DAG" ]; then obtido=$(estado_run "$run"); else obtido=$(estado_task "$run" "$alvo"); fi
            if [ -n "$obtido" ] && { [ "$obtido" = "$esperado" ] || { [ -n "$aceitos" ] && [[ " $aceitos " == *" $obtido "* ]]; }; }; then
                echo "PASS  $alvo = $obtido"
            else
                echo "FAIL  $alvo = '${obtido:-?}' (esperado $esperado${aceitos:+ ou $aceitos})"; FALHAS=$((FALHAS + 1))
            fi
        }
        logs_do_run() { echo "airflow/logs/dag_id=energia_livre_diaria/run_id=$1"; }

        echo "== 6) execução NORMAL sem mês novo"
        bash scripts/operar_dag.sh normal 2>&1 | tee "${L}_dag_normal.log" || true
        RUN=$(cat data/logs/dag_normal_run_id.txt)
        exigir "$RUN" DAG success
        exigir "$RUN" dbt_test success
        # o ShortCircuit que devolve False TERMINA em success (é ele quem pula a task seguinte)
        exigir "$RUN" previsao_ha_mes_novo success
        exigir "$RUN" previsao_mensal skipped
        exigir "$RUN" pipeline_ok success
        if grep -rq "sem mês novo" "$(logs_do_run "$RUN")" 2>/dev/null; then echo "PASS  o log do ShortCircuit diz 'sem mês novo'"; else echo "INFO  o log do ShortCircuit não foi achado em $(logs_do_run "$RUN") (confira na UI)"; fi

        echo "== 7) execução com FALHA PROPOSITAL {\"falha_proposital\": true}"
        bash scripts/operar_dag.sh falha 2>&1 | tee "${L}_dag_falha.log" || true
        RUN=$(cat data/logs/dag_falha_run_id.txt)
        exigir "$RUN" DAG failed
        exigir "$RUN" dbt_test failed
        exigir "$RUN" previsao_ha_mes_novo upstream_failed
        exigir "$RUN" previsao_mensal upstream_failed
        exigir "$RUN" pipeline_ok upstream_failed
        exigir "$RUN" freshness_manuais success   # só depende do dbt_run: o alerta é por task que falhou, não por task barrada
        ENVIADOS=$(grep -rh "alerta no Discord enviado" "$(logs_do_run "$RUN")" 2>/dev/null | wc -l || true)
        NAO_ENVIADOS=$(grep -rh "alerta no Discord não enviado\|DISCORD_WEBHOOK_URL vazia" "$(logs_do_run "$RUN")" 2>/dev/null | wc -l || true)
        echo "mensagens enviadas pelo callback (log das tasks): $ENVIADOS; falhas de envio: $NAO_ENVIADOS"
        if [ "$ENVIADOS" -ge 1 ] && [ "$NAO_ENVIADOS" -eq 0 ]; then
            echo "PASS  o alerta foi disparado (1 por task que FALHOU de vez: só o dbt_test; as barradas não alertam)"
        elif [ "$NAO_ENVIADOS" -gt 0 ]; then
            echo "FAIL  o envio do alerta falhou (webhook vazio ou errado)"; FALHAS=$((FALHAS + 1))
        else
            echo "FAIL  o log não prova o alerta; confira a mensagem 'Falha no pipeline energia_livre_diaria' (task dbt_test) no Discord"; FALHAS=$((FALHAS + 1))
        fi
        echo ">>> CONFIRA NO DISCORD: uma mensagem do dbt_test e NENHUMA de previsao_ha_mes_novo, previsao_mensal ou pipeline_ok."

        conferir
        echo "== resultado do modo dag: $FALHAS falha(s)"
        [ "$FALHAS" -eq 0 ] || exit 1
        ;;
    dag-gerar)
        # OPCIONAL, grava na produção: apaga as 12 linhas da última origem de PRODUÇÃO e deixa a DAG regerá-las,
        # para provar o ramo em que o ShortCircuit devolve True. Só roda com a confirmação explícita.
        [ "${2:-}" = "--confirmo" ] || { echo "uso: $0 dag-gerar --confirmo  (apaga e regrava a previsão da última origem)"; exit 2; }
        docker info >/dev/null 2>&1 || { echo "ABORTADO: o Docker não responde"; exit 1; }
        py scripts.conferir_previsao --impressao 2>&1 | tee "${L}_gerar_dag_impressao_1.log"
        py scripts.apagar_ultima_previsao --confirmo 2>&1 | tee "${L}_gerar_dag_apagou.log"
        bash scripts/operar_dag.sh normal 2>&1 | tee "${L}_gerar_dag.log" || true
        RUN=$(cat data/logs/dag_normal_run_id.txt)
        for par in "previsao_ha_mes_novo success" "previsao_mensal success" "pipeline_ok success"; do
            set -- $par
            obtido=$(docker compose exec -T postgres psql -U airflow -d airflow -tA -c "select state from task_instance where run_id='$RUN' and task_id='$1'" | head -1)
            [ "$obtido" = "$2" ] && echo "PASS  $1 = $obtido" || { echo "FAIL  $1 = '${obtido:-?}' (esperado $2)"; exit 1; }
        done
        py scripts.conferir_previsao --impressao 2>&1 | tee "${L}_gerar_dag_impressao_2.log"
        # a previsão gravada é um retrato da origem: com a MESMA entrada tem de sair idêntica; com entrada
        # diferente (a linha apagada foi gravada antes da impressão digital, ou o mart mudou) a diferença é mostrada
        py scripts.comparar_impressoes "${L}_gerar_dag_impressao_1.log" "${L}_gerar_dag_impressao_2.log"
        conferir
        ;;
    *)
        echo "uso: $0 local|dag|dag-gerar --confirmo|conferir"; exit 2 ;;
esac
