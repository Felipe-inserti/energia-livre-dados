"""DAG diária do pipeline: ingestão incremental, freshness, dbt run e dbt test (Sprints 3 e 4).

    parametros_execucao -> ons_ingestao ------------------------------------.
    ccee_ha_arquivo_novo -> ccee_ingestao -> ccee_registrar_estado ---------|
    inmet_ha_arquivo_novo -> inmet_ingestao -> inmet_registrar_estado -------'
                                                                            v
        selecao_dbt -> freshness_ons -> dbt_run -> dbt_test -> pipeline_ok
                                                `-> freshness_manuais (só avisa)

O ONS é automático e roda todo dia, em modo JANELA: recarrega só o mês corrente e os dois
anteriores (ingestion/janela.py), baixa só o arquivo do ano, confere por HEAD se algum ano fechado
mudou no ONS e grava as vars do dbt (`--saida-vars`) com a janela de fato carregada. CCEE e INMET
são baixados à mão: só rodam quando há arquivo novo na pasta manual (ingestion/orquestracao.py). O
dbt roda só o que descende das fontes que mudaram (`selecao_dbt`): o ONS no dia comum, mais o INMET
e/ou a CCEE quando há arquivo novo. `dbt run` e `dbt test` ficam em tasks separadas por causa das
retentativas (docs/decisoes.md). Tudo é idempotente: cada load job substitui a sua partição do raw,
o dbt sobrescreve as partições da janela, e o estado dos arquivos manuais só avança depois de a
carga dar certo. Ingestão e dbt rodam no venv do projeto (/opt/projeto-venv), separado do Python do
Airflow.

Configuração da execução manual (`airflow dags trigger -c '<json>'` ou o formulário):
- `{"desde": "2026-07", "ate": "2026-08"}`: BACKFILL dos meses (AAAA-MM, inclusive, os dois juntos);
- `{"execucao_completa": true}`: dbt sem seleção (os 47 testes que nenhuma fonte seleciona);
- `{"falha_proposital": true}`: prova o alerta (o `dbt test` falha de propósito).
A data de referência da janela vem da execução (`data_interval_end`, com `logical_date` e
`run_after` de reserva), nunca do relógio: reexecutar um dia dá sempre a mesma janela.
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
# testes e a freshness não repetem. É a política da Sprint 3, mantida (docs/decisoes.md).
RETENTATIVAS_INGESTAO = {"retries": 2, "retry_delay": timedelta(minutes=5)}
RETENTATIVAS_DBT_RUN = {"retries": 1, "retry_delay": timedelta(minutes=2)}
SEM_RETENTATIVA = {"retries": 0}

# Resultados de uma task para outra (XCom). O texto que vira linha de comando é validado em
# ingestion/orquestracao.py (a configuração vem de quem dispara a execução).
PARAMETROS = "ti.xcom_pull(task_ids='parametros_execucao')"
SELECAO = "ti.xcom_pull(task_ids='selecao_dbt')"


def _parametros_da_execucao(**contexto):
    """Modo (janela ou backfill), data de referência e arquivo de vars desta execução."""
    execucao = contexto["dag_run"]
    return orq.parametros_da_execucao(
        data_interval_end=contexto.get("data_interval_end"),
        logical_date=contexto.get("logical_date"),
        run_after=getattr(execucao, "run_after", None),
        params={
            nome: contexto["params"][nome] for nome in contexto["params"]
        },  # valores resolvidos
        conf=dict(execucao.conf or {}),
        run_id=contexto["run_id"],
    )


def _selecao_dbt(ti, **contexto):
    """`--select` do dbt: o ONS sempre, mais as fontes manuais que tiveram arquivo novo."""
    novo = {
        fonte: bool(ti.xcom_pull(task_ids=f"{fonte}_ha_arquivo_novo", key="novo"))
        for fonte in ("ccee", "inmet")
    }
    completa = bool(ti.xcom_pull(task_ids="parametros_execucao")["completa"])
    return orq.selecao_da_execucao(novo["ccee"], novo["inmet"], completa)


with DAG(
    dag_id="energia_livre_diaria",
    description="ONS (janela diária) e CCEE/INMET (se houver arquivo novo) -> dbt run -> dbt test",
    # 21:00 UTC (18:00 em Brasília): depois da publicação das 19:00 UTC do ONS, com 2 h de folga
    schedule="0 21 * * *",
    start_date=pendulum.datetime(2026, 10, 1, tz="UTC"),
    # catchup=False: dias sem execução (máquina desligada) NÃO viram uma fila de execuções. Não faz
    # falta: a janela da ingestão é AUTOCORRETIVA (começa no menor entre "o mês da referência menos
    # 2" e o mês do último dado que o raw já tem, lido dos metadados de partição), então a próxima
    # execução recarrega sozinha o período que ficou sem rodar, de 1 dia ou de meses, e o dbt
    # reprocessa o mesmo intervalo. O backfill manual (`desde`/`ate`) cobre o resto.
    catchup=False,
    max_active_runs=1,
    dagrun_timeout=timedelta(hours=1),
    default_args={"on_failure_callback": orq.alertar_falha, "owner": "felipe"},
    params={
        "falha_proposital": Param(False, type="boolean"),
        "execucao_completa": Param(False, type="boolean"),
        "desde": Param(None, type=["null", "string"]),
        "ate": Param(None, type=["null", "string"]),
    },
    tags=["energia-livre", "sprint4"],
) as dag:
    parametros_execucao = PythonOperator(
        task_id="parametros_execucao",
        python_callable=_parametros_da_execucao,
        **SEM_RETENTATIVA,
    )

    ons_ingestao = BashOperator(
        task_id="ons_ingestao",
        bash_command=(
            f"{PYTHON} -m ingestion.ons --sem-medicao "
            "--saida-vars {{ " + PARAMETROS + "['arquivo_vars'] }} "
            "{{ " + PARAMETROS + "['argumentos_ons'] }}"
        ),
        cwd=PROJETO,
        execution_timeout=timedelta(minutes=20),
        **RETENTATIVAS_INGESTAO,
    )
    parametros_execucao >> ons_ingestao

    pontas_da_ingestao = [ons_ingestao]
    for fonte, modulo in (("ccee", "ingestion.ccee"), ("inmet", "ingestion.inmet")):
        pasta, padrao = orq.FONTES_MANUAIS[fonte]
        estado = orq.PASTA_ESTADO / f"{fonte}.json"
        # ignore_downstream_trigger_rules=False: pular a fonte manual só pula as tasks dela; o dbt
        # roda mesmo assim (trigger_rule NONE_FAILED, mais abaixo). O resultado também vai para o
        # XCom (chave `novo`) e decide a seleção do dbt.
        ha_novo = ShortCircuitOperator(
            task_id=f"{fonte}_ha_arquivo_novo",
            python_callable=orq.checar_arquivo_novo,
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

    selecao_dbt = PythonOperator(
        task_id="selecao_dbt",
        python_callable=_selecao_dbt,
        trigger_rule=TriggerRule.NONE_FAILED,
        **SEM_RETENTATIVA,
    )
    freshness_ons = BashOperator(
        task_id="freshness_ons",
        bash_command=f"{DBT} source freshness --select source:raw.ons_curva_carga {DBT_ARGS}",
        cwd=PROJETO,
        trigger_rule=TriggerRule.NONE_FAILED,
        **SEM_RETENTATIVA,
    )
    # As vars da janela vêm do `--saida-vars` da ingestão desta execução: a janela de fato carregada
    # (a diária, a autocorretiva, o backfill, ou ampliada por um ano recarregado). Sem elas o
    # staging incremental falha de propósito.
    dbt_run = BashOperator(
        task_id="dbt_run",
        bash_command=(
            f"{DBT} run {{{{ {SELECAO}['run'] }}}} "
            f"--vars \"$(cat {{{{ {PARAMETROS}['arquivo_vars'] }}}})\" {DBT_ARGS}"
        ),
        cwd=PROJETO,
        execution_timeout=timedelta(minutes=15),
        **RETENTATIVAS_DBT_RUN,
    )
    dbt_test = BashOperator(
        task_id="dbt_test",
        bash_command=f"{DBT} test {{{{ {SELECAO}['test'] }}}} {DBT_ARGS}",
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

    pontas_da_ingestao >> selecao_dbt >> freshness_ons >> dbt_run >> [dbt_test, freshness_manuais]
    dbt_test >> pipeline_ok
