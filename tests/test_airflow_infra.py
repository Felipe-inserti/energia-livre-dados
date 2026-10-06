"""Guardas do Airflow local (Sprint 3), sem Docker: o compose não vaza segredo nem abre a porta."""

import re
import subprocess
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parent.parent
COMPOSE = yaml.safe_load((RAIZ / "docker-compose.yml").read_text())
DOCKERFILE = (RAIZ / "airflow" / "Dockerfile").read_text()
DAG = (RAIZ / "airflow" / "dags" / "energia_livre_diaria.py").read_text()


def test_executor_simples_sem_celery_nem_redis():
    comum = COMPOSE["x-airflow-comum"]
    assert comum["environment"]["AIRFLOW__CORE__EXECUTOR"] == "LocalExecutor"
    assert not {"redis", "airflow-worker", "flower"} & set(COMPOSE["services"])
    assert {"postgres", "airflow-init", "airflow-apiserver", "airflow-scheduler"} <= set(
        COMPOSE["services"]
    )


def test_nenhum_servico_sobrescreve_o_entrypoint_da_imagem():
    """O /entrypoint cria o usuário do uid 1000 no passwd e exporta o HOME; pulá-lo quebra tudo."""
    for nome, servico in COMPOSE["services"].items():
        assert "entrypoint" not in servico, nome
    assert COMPOSE["services"]["airflow-init"]["command"][0] == "bash"
    user = COMPOSE["x-airflow-comum"]["user"]
    assert user.endswith(":0")  # grupo 0: é ele que torna o /etc/passwd e o HOME graváveis
    assert "HOME" not in COMPOSE["x-airflow-comum"]["environment"]  # quem define é o entrypoint


def test_a_ui_so_escuta_em_localhost_porque_nao_tem_login():
    portas = COMPOSE["services"]["airflow-apiserver"]["ports"]
    assert portas == ["127.0.0.1:8080:8080"]


def test_credencial_do_gcp_vem_do_adc_montado_somente_leitura_e_nao_do_repositorio():
    volumes = COMPOSE["x-airflow-comum"]["volumes"]
    adc = [v for v in volumes if "application_default_credentials.json" in v]
    assert len(adc) == 1 and adc[0].endswith(":ro") and adc[0].startswith("${HOME}/")
    assert COMPOSE["x-airflow-comum"]["environment"]["GOOGLE_APPLICATION_CREDENTIALS"]
    arquivos = subprocess.run(
        ["git", "ls-files"], cwd=RAIZ, capture_output=True, text=True, check=True
    ).stdout.split()
    assert not [a for a in arquivos if a.endswith((".json", ".pem")) and "credential" in a.lower()]


def test_google_cloud_project_vem_do_gcp_project_id_nos_servicos_que_rodam_tasks():
    """Sem o projeto no ambiente, o google.auth avisa 'No project ID could be determined'."""
    for nome in ("airflow-init", "airflow-scheduler", "airflow-dag-processor"):
        ambiente = COMPOSE["services"][nome]["environment"]
        assert "${GCP_PROJECT_ID" in ambiente["GOOGLE_CLOUD_PROJECT"], nome


def test_segredos_ficam_em_arquivo_fora_do_git_e_o_compose_so_os_referencia():
    assert "airflow/.env" in COMPOSE["x-airflow-comum"]["env_file"]
    ignorados = subprocess.run(
        ["git", "check-ignore", "airflow/.env", "airflow/logs/qualquer.log"],
        cwd=RAIZ,
        capture_output=True,
        text=True,
    ).stdout.split()
    assert ignorados == ["airflow/.env", "airflow/logs/qualquer.log"]
    exemplo = (RAIZ / "airflow" / ".env.example").read_text()
    assert re.search(r"^DISCORD_WEBHOOK_URL=$", exemplo, re.M)  # vazio: o real não é versionado


def test_nenhum_arquivo_versionado_contem_url_de_webhook_do_discord():
    arquivos = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=RAIZ,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    for nome in arquivos:
        caminho = RAIZ / nome
        if caminho.suffix in {".py", ".yml", ".yaml", ".md", ".example", ".sql", ""}:
            texto = caminho.read_text(errors="ignore") if caminho.is_file() else ""
            assert not re.search(r"discord(app)?\.com/api/webhooks/\d+", texto), nome


def test_versao_do_airflow_esta_fixada_igual_no_compose_e_no_dockerfile():
    assert "apache/airflow:3.3.2-python3.12" in DOCKERFILE
    assert COMPOSE["x-airflow-comum"]["image"].endswith(":3.3.2")


def test_dbt_e_ingestao_rodam_no_venv_do_projeto_e_nao_no_python_do_airflow():
    assert "/opt/projeto-venv/bin/dbt" in DAG and "/opt/projeto-venv/bin/python" in DAG
    assert "uv sync --frozen" in DOCKERFILE  # as mesmas versões do uv.lock


def test_dag_idempotente_sem_catchup_e_no_horario_decidido():
    assert 'schedule="0 21 * * *"' in DAG  # 21:00 UTC = 18:00 em Brasília
    assert "catchup=False" in DAG and "max_active_runs=1" in DAG


def test_dbt_test_e_freshness_nao_repetem_e_a_ingestao_repete():
    assert 'SEM_RETENTATIVA = {"retries": 0}' in DAG
    assert re.search(r'RETENTATIVAS_INGESTAO = \{"retries": 2', DAG)
    dbt_test = DAG[DAG.index('task_id="dbt_test"') :].split("freshness_manuais")[0]
    assert "**SEM_RETENTATIVA" in dbt_test
