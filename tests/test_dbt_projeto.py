"""Guardas do projeto dbt (sem rede): perfil seguro, fontes coerentes com os extratores e parse."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from ingestion import ccee, feriados, inmet, ons
from ingestion.common.config import DATASET_RAW

RAIZ = Path(__file__).resolve().parent.parent
DBT = RAIZ / "dbt"
GIB = 1024**3


def carregar(caminho: Path) -> dict:
    return yaml.safe_load(caminho.read_text())


def perfil_dev() -> dict:
    return carregar(DBT / "profiles.yml.example")["energia_livre"]["outputs"]["dev"]


def fonte_raw() -> dict:
    return carregar(DBT / "models" / "staging" / "_sources.yml")["sources"][0]


# ---------------------------------------------------------------- perfil


def test_perfil_usa_adc_e_nao_tem_chave():
    dev = perfil_dev()
    assert dev["type"] == "bigquery" and dev["method"] == "oauth"  # credenciais ADC
    proibidos = {"keyfile", "keyfile_json", "token", "refresh_token", "client_secret"}
    assert not proibidos & set(dev)
    assert "env_var('GCP_PROJECT_ID')" in dev["project"]  # projeto e região vêm do .env
    assert "env_var('BQ_LOCATION')" in dev["location"]


def test_perfil_limita_os_bytes_cobrados_por_job():
    """Guarda de custo do dbt (o teste de `.query(` da ingestão não alcança o dbt)."""
    teto = perfil_dev()["maximum_bytes_billed"]
    assert isinstance(teto, int) and 0 < teto <= GIB


def test_perfil_real_fica_fora_do_git_e_o_exemplo_nao():
    ignorados = (RAIZ / ".gitignore").read_text().splitlines()
    assert "dbt/profiles.yml" in ignorados
    assert "dbt/profiles.yml.example" not in ignorados


def test_projeto_aponta_para_um_perfil_que_existe():
    assert carregar(DBT / "dbt_project.yml")["profile"] in carregar(DBT / "profiles.yml.example")


def test_macro_de_schema_usa_o_nome_do_dataset_sem_prefixo():
    macro = (DBT / "macros" / "generate_schema_name.sql").read_text()
    assert "custom_schema_name | trim" in macro
    assert "target.schema }}_" not in macro  # sem o padrão "<perfil>_<schema>"


# ---------------------------------------------------------------- fontes


def test_fontes_sao_exatamente_as_tabelas_que_os_extratores_escrevem():
    esperadas = {
        ons.NOME_TABELA,
        inmet.NOME_TABELA,
        feriados.NOME_TABELA,
        *(c.tabela for c in ccee.CONJUNTOS),
    }
    fonte = fonte_raw()
    assert fonte["name"] == "raw" and fonte["schema"] == DATASET_RAW
    assert {t["name"] for t in fonte["tables"]} == esperadas
    assert len(esperadas) == 6


def test_toda_tabela_tem_descricao_e_metadados_da_fonte():
    for tabela in fonte_raw()["tables"]:
        assert len(tabela["description"].strip()) > 80, tabela["name"]
        meta = tabela["config"]["meta"]
        assert {"fonte", "granularidade", "fuso", "origem_dos_arquivos"} <= set(meta), tabela[
            "name"
        ]


def test_colunas_de_controle_estao_documentadas():
    for tabela in fonte_raw()["tables"]:
        colunas = {c["name"] for c in tabela["columns"]}
        assert "_carregado_em" in colunas, tabela["name"]
        if tabela["name"] != "feriados":  # os feriados não têm arquivo de origem
            assert "_arquivo_origem" in colunas, tabela["name"]


def test_colunas_documentadas_existem_nos_extratores():
    """As colunas descritas no _sources.yml têm de ser as que o raw realmente tem."""
    reais = {
        ons.NOME_TABELA: {*ons.COLUNAS_ESPERADAS, "_arquivo_origem", "_carregado_em"},
        inmet.NOME_TABELA: {*inmet.COLUNAS_ESPERADAS, *inmet.TIPOS_EXTRAS},
        feriados.NOME_TABELA: {*feriados.COLUNAS, "_carregado_em"},
    }
    for c in ccee.CONJUNTOS:
        reais[c.tabela] = {*c.colunas, "_arquivo_origem", "_carregado_em"}
    for tabela in fonte_raw()["tables"]:
        documentadas = {c["name"] for c in tabela["columns"]}
        assert documentadas <= reais[tabela["name"]], (
            tabela["name"],
            documentadas - reais[tabela["name"]],
        )


# ---------------------------------------------------------------- parse


@pytest.mark.skipif(
    not (DBT / "dbt_packages").exists() or not shutil.which("dbt"),
    reason="precisa do dbt instalado e de `dbt deps` (uv run dbt deps --project-dir dbt)",
)
def test_dbt_parse_compila_o_projeto_sem_nuvem_nem_credenciais(tmp_path):
    shutil.copy(DBT / "profiles.yml.example", tmp_path / "profiles.yml")
    ambiente = {
        **os.environ,
        "GCP_PROJECT_ID": "projeto-de-teste",
        "BQ_LOCATION": "us-central1",
        "CLOUDSDK_CONFIG": str(tmp_path / "sem-gcloud"),  # esconde a credencial ADC
        "GOOGLE_APPLICATION_CREDENTIALS": str(tmp_path / "nao-existe.json"),
    }
    resultado = subprocess.run(
        [
            "dbt",
            "parse",
            "--project-dir",
            str(DBT),
            "--profiles-dir",
            str(tmp_path),
            "--target-path",
            str(tmp_path / "target"),
            "--log-path",
            str(tmp_path / "logs"),
        ],
        capture_output=True,
        text=True,
        env=ambiente,
        timeout=180,
    )
    assert resultado.returncode == 0, resultado.stdout[-1500:] + resultado.stderr[-500:]
