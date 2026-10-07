"""A DAG `energia_livre_diaria` EXECUTADA com um Airflow de mentira (o Airflow só existe na imagem
do Docker): confere o grafo, as retentativas, os parâmetros e o texto REAL dos comandos, depois de
renderizar o Jinja com XComs simulados. O que o Airflow de verdade faz (agendar, importar) continua
a cargo do `airflow dags list-import-errors` do checkpoint 8."""

import enum
import importlib.util
import sys
import types
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import jinja2
import pytest

DAG_ARQUIVO = (
    Path(__file__).resolve().parent.parent / "airflow" / "dags" / "energia_livre_diaria.py"
)
ATUAL: list = []


class Tarefa:
    def __init__(self, task_id, **kw):
        self.task_id, self.kw = task_id, kw
        self.upstream: set[str] = set()
        self.downstream: set[str] = set()
        ATUAL[-1].tasks[task_id] = self

    def __rshift__(self, outro):
        for o in outro if isinstance(outro, list) else [outro]:
            self.downstream.add(o.task_id)
            o.upstream.add(self.task_id)
        return outro

    def __rrshift__(self, outro):  # [a, b] >> tarefa
        for o in outro:
            o >> self
        return self


class DAGFalsa:
    def __init__(self, **kw):
        self.kw, self.tasks = kw, {}

    def __enter__(self):
        ATUAL.append(self)
        return self

    def __exit__(self, *a):
        ATUAL.pop()


class ParamFalso:
    def __init__(self, padrao, **kw):
        self.padrao, self.kw = padrao, kw


class RegraFalsa(enum.Enum):
    NONE_FAILED = "none_failed"
    ALL_SUCCESS = "all_success"


def modulo(nome, **atributos):
    m = types.ModuleType(nome)
    m.__dict__.update(atributos)
    return m


@pytest.fixture
def dag(monkeypatch):
    ATUAL.clear()
    fakes = {
        "pendulum": modulo("pendulum", datetime=lambda *a, **k: ("datetime", a, k)),
        "airflow": modulo("airflow"),
        "airflow.providers": modulo("airflow.providers"),
        "airflow.providers.standard": modulo("airflow.providers.standard"),
        "airflow.providers.standard.operators": modulo("airflow.providers.standard.operators"),
        "airflow.providers.standard.operators.bash": modulo(
            "airflow.providers.standard.operators.bash", BashOperator=type("Bash", (Tarefa,), {})
        ),
        "airflow.providers.standard.operators.empty": modulo(
            "airflow.providers.standard.operators.empty", EmptyOperator=type("Empty", (Tarefa,), {})
        ),
        "airflow.providers.standard.operators.python": modulo(
            "airflow.providers.standard.operators.python",
            PythonOperator=type("Py", (Tarefa,), {}),
            ShortCircuitOperator=type("Curto", (Tarefa,), {}),
        ),
        "airflow.sdk": modulo("airflow.sdk", DAG=DAGFalsa, Param=ParamFalso),
        "airflow.task": modulo("airflow.task"),
        "airflow.task.trigger_rule": modulo("airflow.task.trigger_rule", TriggerRule=RegraFalsa),
    }
    for nome, falso in fakes.items():
        monkeypatch.setitem(sys.modules, nome, falso)
    spec = importlib.util.spec_from_file_location("dag_energia_livre", DAG_ARQUIVO)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.dag


def renderizar(texto, xcoms=None, **contexto):
    xcoms = xcoms or {}

    class Ti:
        def xcom_pull(self, task_ids, key=None):
            return xcoms[task_ids]

    return jinja2.Environment().from_string(texto).render(ti=Ti(), **contexto)


PARAMETROS = {
    "arquivo_vars": "data/estado/ons_vars_scheduled__2026-10-07.json",
    "argumentos_ons": "--data-referencia 2026-10-07",
}


# ---------------------------------------------------------------- grafo
TASKS = {
    "parametros_execucao",
    "ons_ingestao",
    "ccee_ha_arquivo_novo",
    "ccee_ingestao",
    "ccee_registrar_estado",
    "inmet_ha_arquivo_novo",
    "inmet_ingestao",
    "inmet_registrar_estado",
    "selecao_dbt",
    "freshness_ons",
    "dbt_run",
    "dbt_test",
    "freshness_manuais",
    "pipeline_ok",
}


def test_as_tasks_da_dag(dag):
    assert set(dag.tasks) == TASKS


def test_parametros_antes_da_ingestao_e_selecao_depois_de_toda_a_ingestao_e_antes_do_dbt(dag):
    t = dag.tasks
    assert t["ons_ingestao"].upstream == {"parametros_execucao"}
    assert t["selecao_dbt"].upstream == {
        "ons_ingestao",
        "ccee_registrar_estado",
        "inmet_registrar_estado",
    }
    assert t["freshness_ons"].upstream == {"selecao_dbt"}
    assert t["dbt_run"].upstream == {"freshness_ons"}


def test_run_e_test_sao_tasks_separadas_em_sequencia_e_o_pipeline_so_fecha_depois_do_test(dag):
    t = dag.tasks
    assert t["dbt_test"].upstream == {"dbt_run"} and t["freshness_manuais"].upstream == {"dbt_run"}
    assert t["pipeline_ok"].upstream == {"dbt_test"}
    assert "dbt_test" not in t["dbt_run"].kw.get("bash_command", "")


def test_fontes_manuais_pulam_so_as_tasks_dela_e_o_resultado_vai_para_o_xcom(dag):
    for fonte in ("ccee", "inmet"):
        curto = dag.tasks[f"{fonte}_ha_arquivo_novo"]
        assert curto.kw["python_callable"].__name__ == "checar_arquivo_novo"
        assert curto.kw["ignore_downstream_trigger_rules"] is False
        assert dag.tasks[f"{fonte}_ingestao"].upstream == {f"{fonte}_ha_arquivo_novo"}
        assert dag.tasks[f"{fonte}_registrar_estado"].upstream == {f"{fonte}_ingestao"}


def test_selecao_e_freshness_rodam_mesmo_com_fonte_manual_pulada(dag):
    assert dag.tasks["selecao_dbt"].kw["trigger_rule"] is RegraFalsa.NONE_FAILED
    assert dag.tasks["freshness_ons"].kw["trigger_rule"] is RegraFalsa.NONE_FAILED


# --------------------------------------------------------- retentativas (política da Sprint 3)
def test_politica_de_retentativas_da_sprint_3_foi_mantida(dag):
    t = {k: v.kw for k, v in dag.tasks.items()}
    for tarefa in ("ons_ingestao", "ccee_ingestao", "inmet_ingestao"):
        assert t[tarefa]["retries"] == 2 and t[tarefa]["retry_delay"] == timedelta(minutes=5)
    assert t["dbt_run"]["retries"] == 1 and t["dbt_run"]["retry_delay"] == timedelta(minutes=2)
    for tarefa in (
        "dbt_test",
        "freshness_ons",
        "freshness_manuais",
        "parametros_execucao",
        "selecao_dbt",
    ):
        assert t[tarefa]["retries"] == 0, tarefa  # dado ruim não melhora repetindo


# ---------------------------------------------------------------- agendamento e parâmetros
def test_agendamento_catchup_e_alerta_nao_mudaram(dag):
    kw = dag.kw
    assert kw["schedule"] == "0 21 * * *" and kw["catchup"] is False and kw["max_active_runs"] == 1
    assert kw["default_args"]["on_failure_callback"].__name__ == "alertar_falha"
    assert kw["dagrun_timeout"] == timedelta(hours=1)


def test_parametros_para_backfill_execucao_completa_e_falha_proposital(dag):
    params = dag.kw["params"]
    assert set(params) == {"falha_proposital", "execucao_completa", "desde", "ate"}
    assert params["desde"].padrao is None and params["ate"].padrao is None
    assert (
        params["falha_proposital"].padrao is False and params["execucao_completa"].padrao is False
    )


def test_o_comentario_do_catchup_explica_a_janela_autocorretiva():
    texto = DAG_ARQUIVO.read_text()
    assert "AUTOCORRETIVA" in texto and "catchup=False" in texto
    assert "recarrega sozinha o período que ficou sem rodar" in texto
    assert (
        "a próxima carga full o recupera" not in texto
    )  # o comentário antigo, que deixou de valer


# ---------------------------------------------------------------- os comandos, renderizados
def test_a_ingestao_do_dia_roda_em_modo_janela_com_a_data_da_execucao_e_grava_as_vars(dag):
    comando = renderizar(
        dag.tasks["ons_ingestao"].kw["bash_command"], {"parametros_execucao": PARAMETROS}
    )
    assert comando == (
        "/opt/projeto-venv/bin/python -m ingestion.ons --sem-medicao "
        "--saida-vars data/estado/ons_vars_scheduled__2026-10-07.json --data-referencia 2026-10-07"
    )
    assert "--full" not in comando


def test_a_ingestao_de_backfill_recebe_desde_e_ate_da_configuracao(dag):
    backfill = {**PARAMETROS, "argumentos_ons": "--desde 2026-07 --ate 2026-08"}
    comando = renderizar(
        dag.tasks["ons_ingestao"].kw["bash_command"], {"parametros_execucao": backfill}
    )
    assert comando.endswith("--desde 2026-07 --ate 2026-08") and "--data-referencia" not in comando


XCOMS_DIA = {
    "parametros_execucao": PARAMETROS,
    "selecao_dbt": {
        "run": "--select source:raw.ons_curva_carga+",
        "test": "--select source:raw.ons_curva_carga+ teste_alerta_falha_proposital",
    },
}


def test_dbt_run_usa_a_selecao_do_dia_e_as_vars_gravadas_pela_ingestao(dag):
    comando = renderizar(dag.tasks["dbt_run"].kw["bash_command"], XCOMS_DIA)
    assert comando == (
        "/opt/projeto-venv/bin/dbt --no-use-colors run --select source:raw.ons_curva_carga+ "
        '--vars "$(cat data/estado/ons_vars_scheduled__2026-10-07.json)" '
        "--project-dir dbt --profiles-dir dbt"
    )


def test_dbt_test_usa_a_selecao_de_teste_com_o_alerta_e_nunca_as_vars(dag):
    comando = renderizar(dag.tasks["dbt_test"].kw["bash_command"], XCOMS_DIA)
    assert comando == (
        "/opt/projeto-venv/bin/dbt --no-use-colors test --select source:raw.ons_curva_carga+ "
        "teste_alerta_falha_proposital --project-dir dbt --profiles-dir dbt"
    )
    assert "--vars" not in comando


def test_execucao_completa_roda_o_dbt_sem_select(dag):
    xcoms = {**XCOMS_DIA, "selecao_dbt": {"run": "", "test": ""}}
    run = renderizar(dag.tasks["dbt_run"].kw["bash_command"], xcoms)
    assert "--select" not in run and "--vars" in run  # as vars continuam: o stg é incremental
    assert "--select" not in renderizar(dag.tasks["dbt_test"].kw["bash_command"], xcoms)


@pytest.mark.parametrize(
    ("conf", "esperado"),
    [({}, "false"), ({"falha_proposital": True}, "true"), ({"falha_proposital": False}, "false")],
)
def test_falha_proposital_continua_chegando_ao_dbt_test_pela_configuracao(dag, conf, esperado):
    modelo = dag.tasks["dbt_test"].kw["env"]["FORCAR_FALHA"]
    contexto = {
        "dag_run": SimpleNamespace(conf=conf),
        "params": SimpleNamespace(falha_proposital=False),
    }
    assert renderizar(modelo, **contexto) == esperado


def test_o_teste_do_alerta_entra_na_selecao_do_dbt_test_sempre():
    from ingestion import orquestracao as orq

    for ccee in (False, True):
        for inmet in (False, True):
            assert "teste_alerta_falha_proposital" in orq.selecao_da_execucao(ccee, inmet)["test"]
