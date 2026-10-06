"""DAG diária do pipeline: ingestão, freshness, dbt run e dbt test (Sprint 3, tarefas 3.6 e 3.7).

    ons_ingestao ----------------------------.
    ccee_ha_arquivo_novo -> ccee_ingestao -> ccee_registrar_estado --|
    inmet_ha_arquivo_novo -> inmet_ingestao -> inmet_registrar_estado -'
                                                                      v
                          freshness_ons -> dbt_run -> dbt_test -> pipeline_ok
                                              `-> freshness_manuais (só avisa)

O ONS é automático e roda todo dia. CCEE e INMET são baixados à mão: só rodam quando há arquivo novo
na pasta manual (ingestion/orquestracao.py). Tudo é idempotente: a carga do ONS é full no raw e por
hash no bronze, o dbt reconstrói as tabelas, e o estado dos arquivos manuais só avança depois de a
carga dar certo. Ingestão e dbt rodam no venv do projeto (/opt/projeto-venv), separado do Python do
Airflow (decisão em docs/decisoes.md).

Para provar o alerta: disparar com a configuração {"falha_proposital": true}.
"""

from datetime import timedelta

import pendulum
from airflow.providers.standard.operators.bash import BashOperator
from airflow.providers.standard.operators.empty import EmptyOperator
from airflow.providers.standard.operators.python import PythonOperator, ShortCircuitOperator
from airflow.sdk import DAG, Param
from airflow.task.trigger_rule import TriggerRule

from ingestion import orquestracao as orq

PROJETO = "/opt/projeto"
PYTHON = "/opt/projeto-venv/bin/python"
DBT = "/opt/projeto-venv/bin/dbt --no-use-colors"
DBT_ARGS = "--project-dir dbt --profiles-dir dbt"

# Retentativas por tipo de falha: a rede e os portais falham de forma transitória (vale tentar de
# novo, com espera); dado ruim não melhora sozinho (repetir o teste só gasta bytes), então os
# testes e a freshness não repetem.
RETENTATIVAS_INGESTAO = {"retries": 2, "retry_delay": timedelta(minutes=5)}
RETENTATIVAS_DBT_RUN = {"retries": 1, "retry_delay": timedelta(minutes=2)}
SEM_RETENTATIVA = {"retries": 0}

with DAG(
    dag_id="energia_livre_diaria",
    description="ONS (diário) e CCEE/INMET (se houver arquivo novo) -> dbt run -> dbt test",
    # 21:00 UTC (18:00 em Brasília): depois da publicação das 19:00 UTC do ONS, com 2 h de folga
    schedule="0 21 * * *",
    start_date=pendulum.datetime(2026, 10, 1, tz="UTC"),
    catchup=False,  # um dia perdido não vira fila de dias: a próxima carga full o recupera
    max_active_runs=1,
    dagrun_timeout=timedelta(hours=1),
    default_args={"on_failure_callback": orq.alertar_falha, "owner": "felipe"},
    params={"falha_proposital": Param(False, type="boolean")},
    tags=["energia-livre", "sprint3"],
) as dag:
    ons_ingestao = BashOperator(
        task_id="ons_ingestao",
        bash_command=f"{PYTHON} -m ingestion.ons --sem-medicao",
        cwd=PROJETO,
        execution_timeout=timedelta(minutes=20),
        **RETENTATIVAS_INGESTAO,
    )

    pontas_da_ingestao = [ons_ingestao]
    for fonte, modulo in (("ccee", "ingestion.ccee"), ("inmet", "ingestion.inmet")):
        pasta, padrao = orq.FONTES_MANUAIS[fonte]
        estado = orq.PASTA_ESTADO / f"{fonte}.json"
        # ignore_downstream_trigger_rules=False: pular a fonte manual só pula as tasks dela; o dbt
        # roda mesmo assim (trigger_rule NONE_FAILED, mais abaixo)
        ha_novo = ShortCircuitOperator(
            task_id=f"{fonte}_ha_arquivo_novo",
            python_callable=orq.ha_arquivo_novo,
            op_args=[pasta, padrao, estado],
            ignore_downstream_trigger_rules=False,
        )
        ingestao = BashOperator(
            task_id=f"{fonte}_ingestao",
            bash_command=f"{PYTHON} -m {modulo}",
            cwd=PROJETO,
            execution_timeout=timedelta(minutes=20),
            **RETENTATIVAS_INGESTAO,
        )
        registrar = PythonOperator(
            task_id=f"{fonte}_registrar_estado",
            python_callable=orq.registrar_estado,
            op_args=[pasta, padrao, estado],
        )
        ha_novo >> ingestao >> registrar
        pontas_da_ingestao.append(registrar)

    freshness_ons = BashOperator(
        task_id="freshness_ons",
        bash_command=f"{DBT} source freshness --select source:raw.ons_curva_carga {DBT_ARGS}",
        cwd=PROJETO,
        trigger_rule=TriggerRule.NONE_FAILED,
        **SEM_RETENTATIVA,
    )
    dbt_run = BashOperator(
        task_id="dbt_run",
        bash_command=f"{DBT} run {DBT_ARGS}",
        cwd=PROJETO,
        execution_timeout=timedelta(minutes=15),
        **RETENTATIVAS_DBT_RUN,
    )
    dbt_test = BashOperator(
        task_id="dbt_test",
        bash_command=f"{DBT} test {DBT_ARGS}",
        cwd=PROJETO,
        append_env=True,
        env={
            "FORCAR_FALHA": (
                "{{ 'true' if (dag_run.conf or {}).get('falha_proposital', "
                "params.falha_proposital) else 'false' }}"
            )
        },
        execution_timeout=timedelta(minutes=15),
        **SEM_RETENTATIVA,
    )
    # Só avisa: as fontes manuais não têm error_after, então o comando nunca sai com erro
    freshness_manuais = BashOperator(
        task_id="freshness_manuais",
        bash_command=f"{DBT} source freshness --exclude source:raw.ons_curva_carga {DBT_ARGS}",
        cwd=PROJETO,
        **SEM_RETENTATIVA,
    )
    # Ponto de encontro do que vier depois do dbt (previsão e otimização, Sprint 5)
    pipeline_ok = EmptyOperator(task_id="pipeline_ok")

    pontas_da_ingestao >> freshness_ons >> dbt_run >> [dbt_test, freshness_manuais]
    dbt_test >> pipeline_ok
