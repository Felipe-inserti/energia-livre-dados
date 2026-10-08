"""O script de validação na nuvem da Sprint 5C: sintaxe e o que ele promete conferir (sem nuvem)."""

import subprocess
from pathlib import Path

import pytest

from scripts import apagar_ultima_previsao as ap

RAIZ = Path(__file__).resolve().parents[1]
SCRIPT = (RAIZ / "scripts" / "passo_sprint5_c.sh").read_text()


def test_o_script_tem_sintaxe_valida():
    assert (
        subprocess.run(["bash", "-n", str(RAIZ / "scripts" / "passo_sprint5_c.sh")]).returncode == 0
    )


def test_o_modo_dag_confere_o_dia_sem_mes_novo_e_a_falha_proposital():
    dag = SCRIPT.split("    dag)")[1].split("    dag-gerar)")[0]
    # execução normal sem mês novo: o ShortCircuit termina success e pula só a task seguinte
    assert 'exigir "$RUN" previsao_ha_mes_novo success' in dag
    assert 'exigir "$RUN" previsao_mensal skipped' in dag
    assert 'exigir "$RUN" pipeline_ok success' in dag
    # falha proposital: dbt_test falha, tudo que depende dele fica upstream_failed e o alerta sai
    assert "operar_dag.sh falha" in dag
    assert 'exigir "$RUN" dbt_test failed' in dag
    for task in ("previsao_ha_mes_novo", "previsao_mensal", "pipeline_ok"):
        assert f'exigir "$RUN" {task} upstream_failed' in dag
    assert "alerta no Discord enviado" in dag
    # só roda a DAG depois de provar que não há mês novo (senão o resultado esperado seria outro)
    assert dag.index('[ "$CODIGO" = "10" ]') < dag.index("operar_dag.sh normal")


def test_dag_gerar_exige_confirmacao_e_o_apagar_tambem(capsys):
    assert '[ "${2:-}" = "--confirmo" ]' in SCRIPT.split("    dag-gerar)")[1]
    assert ap.main([]) == 2 and "RECUSADO" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        ap.main(["--outra"])


def test_o_delete_so_toca_a_ultima_origem_de_producao_da_versao_atual():
    sql = ap.sql_apagar()
    assert sql.startswith("DELETE FROM `marts.fct_previsao_carga`")
    assert "tipo = 'producao'" in sql and "comb_ets_sarima_regressao_v1" in sql
    assert "SELECT MAX(origem)" in sql and "fct_erro_previsao_carga" not in sql
