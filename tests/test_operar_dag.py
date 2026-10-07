"""`scripts/operar_dag.sh`: opera e mede a DAG no Airflow local. O que dá para provar sem Docker:
os subcomandos, a configuração de cada execução e as funções que decidem esperar, abortar ou
considerar uma execução agendada NOVA (com um `docker` falso que responde ao Postgres)."""

import os
import re
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "operar_dag.sh"
TEXTO = SCRIPT.read_text()


def linhas_executaveis() -> list[str]:
    juntas = TEXTO.replace("\\\n", " ")
    return [x.strip() for x in juntas.splitlines() if x.strip() and not x.strip().startswith("#")]


def test_sintaxe_e_tratamento_de_erro_sem_falha_silenciosa():
    r = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "set -Eeuo pipefail" in TEXTO and "### ERRO (código" in TEXTO
    assert re.search(r"trap '.*\$\?.*\$LINENO.*\$BASH_COMMAND.*' ERR", TEXTO)


def test_os_subcomandos_e_a_recusa_do_resto():
    for sub in ("subir", "normal", "backfill", "completa", "falha", "medir", "parar"):
        assert f"    {sub})" in TEXTO, sub
    assert "uso: operar_dag.sh subir | normal | backfill [DESDE ATE] | completa | falha" in TEXTO
    for sub in ("subir", "normal", "backfill", "completa", "falha", "medir", "parar"):
        assert re.search(rf'echo "{sub.upper()} OK"', TEXTO), sub


def test_as_configuracoes_de_cada_execucao():
    assert "disparar normal sucesso" in TEXTO
    assert 'disparar backfill sucesso "{\\"desde\\":\\"$desde\\",\\"ate\\":\\"$ate\\"}"' in TEXTO
    assert """disparar completa sucesso '{"execucao_completa": true}'""" in TEXTO
    assert """disparar falha falha '{"falha_proposital": true}'""" in TEXTO
    assert '--run-id "$run_id"' in TEXTO and '--conf "$conf"' in TEXTO


def test_o_backfill_valida_os_meses_antes_de_montar_o_json():
    assert "padrao_mes='^[0-9]{4}-(0[1-9]|1[0-2])$'" in TEXTO
    assert texto_antes("disparar backfill").count("padrao_mes") >= 1


def texto_antes(trecho: str) -> str:
    return TEXTO[: TEXTO.index(trecho)]


def test_subir_nao_reconstrui_confere_import_e_fuso_e_ativa_a_dag():
    assert "docker compose up -d" in TEXTO
    assert not [x for x in linhas_executaveis() if x.startswith("docker compose build")]
    assert 'grep -q "No data found"' in TEXTO and "af dags list-import-errors" in TEXTO
    assert "ZoneInfo('America/Sao_Paulo')" in TEXTO and "tzdata" in TEXTO
    assert "-m ingestion.janela --formato dbt-vars" in TEXTO
    assert 'af dags unpause "$DAG_ID"' in TEXTO


def test_o_script_nao_roda_dbt_nem_ingestao_diretamente_pois_isso_e_da_dag():
    for linha in linhas_executaveis():
        assert not re.search(r"\bdbt\b\s+(run|build|test)", linha), linha
        assert "ingestion.ons" not in linha, linha


def test_toda_busca_em_pipeline_tem_saida_segura_contra_nada_encontrado():
    for linha in linhas_executaveis():
        if "grep" in linha and not linha.startswith(("if ", "elif ")):
            em_pipe = "|" in linha.replace("||", "") or "$(" in linha
            assert not em_pipe or "||" in linha, linha


# ---- docker falso: responde às consultas do Postgres do Airflow ---------------------------
FALSO_DOCKER = """#!/usr/bin/env bash
sql="${*: -1}"
case "$sql" in
  *"select state from dag_run"*) echo "${FAKE_ESTADO:-}" ;;
  *"select is_paused"*) echo "${FAKE_PAUSADA:-f}" ;;
  *"select count(*)"*) echo "${FAKE_ATIVAS:-0}" ;;
  *"select coalesce(max(id),0)"*) echo "${FAKE_MAX_ID:-0}" ;;
  *"run_type='scheduled' and id >"*)
      corte=$(echo "$sql" | sed -E 's/.*id > ([0-9]+).*/\\1/')
      # FAKE_RUNS: "id:run_id id:run_id ..."; devolve o de maior id acima do corte
      for par in $FAKE_RUNS; do
          id=${par%%:*}; run=${par#*:}
          [ "$id" -gt "$corte" ] && echo "$id $run"
      done | sort -rn | head -1 | cut -d' ' -f2
      ;;
esac
"""


def funcoes() -> str:
    inicio = TEXTO.index("af() {")
    return TEXTO[inicio : TEXTO.index("# resumo de uma execução")]


def rodar(tmp_path, comando: str, **env):
    (tmp_path / "bin").mkdir(exist_ok=True)
    docker = tmp_path / "bin" / "docker"
    docker.write_text(FALSO_DOCKER)
    docker.chmod(0o755)
    codigo = f"DAG_ID=energia_livre_diaria\nset -Eeuo pipefail\n{funcoes()}\n{comando}\n"
    return subprocess.run(
        ["bash", "-c", codigo],
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": f"{tmp_path / 'bin'}:/usr/bin:/bin", **env},
    )


def test_aguardar_run_devolve_quando_termina_em_success_ou_failed(tmp_path):
    for estado in ("success", "failed"):
        r = rodar(tmp_path, "aguardar_run manual__x 30", FAKE_ESTADO=estado)
        assert r.returncode == 0 and f"execução manual__x: {estado}" in r.stdout


def test_aguardar_run_aborta_no_limite_em_vez_de_esperar_para_sempre(tmp_path):
    r = rodar(tmp_path, "aguardar_run manual__x 0", FAKE_ESTADO="running")
    assert r.returncode == 1 and "TEMPO ESGOTADO" in r.stdout and "running" in r.stdout


def test_nao_dispara_com_a_dag_pausada_nem_com_execucao_em_andamento(tmp_path):
    pausada = rodar(tmp_path, "exigir_dag_livre", FAKE_PAUSADA="t")
    assert pausada.returncode == 1 and "não está ativa" in pausada.stdout
    ocupada = rodar(tmp_path, "exigir_dag_livre", FAKE_ATIVAS="1")
    assert ocupada.returncode == 1 and "já há 1 execução" in ocupada.stdout
    livre = rodar(tmp_path, "exigir_dag_livre; echo LIVRE")
    assert livre.returncode == 0 and "LIVRE" in livre.stdout


def test_execucao_agendada_antiga_nao_conta_como_nova(tmp_path):
    """O bug do checkpoint 8: a "agendada" medida era a da Sprint 3 (06/10), que já estava no
    banco, e foi comparada com ela mesma (+0%). Só vale id MAIOR que o de antes do subir."""
    runs = "7:scheduled__2026-10-06T21:00:00+00:00"
    sem_nova = rodar(tmp_path, "execucao_agendada_nova 7", FAKE_RUNS=runs)
    assert sem_nova.returncode == 0 and sem_nova.stdout.strip() == ""
    com_nova = rodar(
        tmp_path,
        "execucao_agendada_nova 7",
        FAKE_RUNS=runs + " 8:scheduled__2026-10-07T21:00:00+00:00",
    )
    assert com_nova.stdout.strip() == "scheduled__2026-10-07T21:00:00+00:00"


def test_o_marco_e_o_maior_id_de_antes_de_ativar_a_dag(tmp_path):
    r = rodar(tmp_path, "maior_id_de_execucao", FAKE_MAX_ID="42")
    assert r.stdout.strip() == "42"
    # o subir captura o marco ANTES do unpause e consulta DEPOIS
    subir = TEXTO[TEXTO.index("    subir)") : TEXTO.index("    normal)")]
    assert subir.index("marco=$(maior_id_de_execucao)") < subir.index("af dags unpause")
    assert subir.index("af dags unpause") < subir.index('execucao_agendada_nova "$marco"')
    assert "agendada=$(pg" not in TEXTO  # a consulta antiga, que devolvia a última de qualquer data
