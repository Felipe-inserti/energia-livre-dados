"""`fct_carga_horaria`: `table` por padrão (decisão da Sprint 4, ver docs/decisoes.md) e alternável
para `incremental` pela var `fct_carga_materializacao`, sem editar o modelo."""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

DBT = Path(__file__).resolve().parent.parent / "dbt"
MODELO = (DBT / "models" / "marts" / "fct_carga_horaria.sql").read_text()
SEM_DBT = pytest.mark.skipif(
    not (DBT / "dbt_packages").exists() or not shutil.which("dbt"),
    reason="precisa do dbt instalado e de `dbt deps`",
)


def test_o_padrao_do_projeto_e_table():
    projeto = yaml.safe_load((DBT / "dbt_project.yml").read_text())
    assert projeto["vars"]["fct_carga_materializacao"] == "table"


def test_o_modelo_le_a_var_com_padrao_table_e_documenta_a_decisao():
    assert "materialized=var('fct_carga_materializacao', 'table')" in MODELO
    assert "{fct_carga_materializacao: incremental}" in MODELO  # como alternar, no próprio modelo
    assert "docs/decisoes.md" in MODELO  # onde está o porquê


def test_o_ramo_incremental_filtra_pelo_mesmo_intervalo_da_lista_de_particoes():
    assert "partitions=janela_particoes()" in MODELO
    assert "where instante_utc >= timestamp('{{ janela.utc_inicio }}')" in MODELO
    assert "and instante_utc < timestamp('{{ janela.utc_fim }}')" in MODELO
    assert MODELO.count("is_incremental()") >= 2  # a janela e o filtro só valem no incremental


def materializacao(tmp_path: Path, vars_: dict | None) -> str:
    shutil.copy(DBT / "profiles.yml.example", tmp_path / "profiles.yml")
    comando = ["dbt", "parse", "--project-dir", str(DBT), "--profiles-dir", str(tmp_path)]
    comando += ["--target-path", str(tmp_path / "t"), "--log-path", str(tmp_path / "l")]
    if vars_ is not None:
        comando += ["--vars", json.dumps(vars_)]
    ambiente = {
        **os.environ,
        "GCP_PROJECT_ID": "projeto-de-teste",
        "BQ_LOCATION": "us-central1",
        "CLOUDSDK_CONFIG": str(tmp_path / "sem-gcloud"),
        "GOOGLE_APPLICATION_CREDENTIALS": str(tmp_path / "nao-existe.json"),
    }
    r = subprocess.run(comando, capture_output=True, text=True, env=ambiente, timeout=180)
    assert r.returncode == 0, r.stdout[-800:]
    manifesto = json.loads((tmp_path / "t" / "manifest.json").read_text())
    no = next(n for n in manifesto["nodes"].values() if n["name"] == "fct_carga_horaria")
    return no["config"]["materialized"]


@SEM_DBT
def test_sem_vars_o_fct_e_table_e_com_a_var_vira_incremental(tmp_path):
    assert materializacao(tmp_path, None) == "table"
    assert materializacao(tmp_path, {"fct_carga_materializacao": "table"}) == "table"
    assert materializacao(tmp_path, {"fct_carga_materializacao": "incremental"}) == "incremental"


@SEM_DBT
def test_o_staging_do_ons_e_sempre_incremental_independente_da_var(tmp_path):
    shutil.copy(DBT / "profiles.yml.example", tmp_path / "profiles.yml")
    texto = (DBT / "models" / "staging" / "stg_ons__curva_carga.sql").read_text()
    assert re.search(r"materialized='incremental'", texto)
    assert "fct_carga_materializacao" not in texto
