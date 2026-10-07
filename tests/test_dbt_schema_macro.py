"""`generate_schema_name`: sem a var `dataset_verificacao` devolve EXATAMENTE os schemas (datasets)
de produção de hoje, para cada modelo e seed do projeto; com a var, tudo vai para o dataset de
verificação, e só para ele."""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import jinja2
import pytest

DBT = Path(__file__).resolve().parent.parent / "dbt"
MACRO = DBT / "macros" / "generate_schema_name.sql"

# O dataset de cada modelo e seed na PRODUÇÃO (os que existem no BigQuery em 07/10/2026; o seed e o
# mart da Sprint 4, Parte B, passam a existir com `scripts/passo2_carga_mensal.sh`). Escrito
# à mão de propósito: é o oráculo, independente do macro. Modelo novo obriga a atualizar a lista.
PRODUCAO = {
    "stg_ccee__consumo_ramo_atividade": "staging",
    "stg_ccee__pld_horario": "staging",
    "stg_ccee__pld_semanal": "staging",
    "stg_feriados": "staging",
    "stg_inmet__estacoes_horario": "staging",
    "stg_ons__curva_carga": "staging",
    "int_clima_estado_horario": "staging",
    "int_clima_submercado_horario": "staging",
    "pld_limites": "staging",  # seed
    "ajuste_definicao_carga": "staging",  # seed (Sprint 4, Parte B)
    "dim_estacao": "marts",
    "dim_submercado": "marts",
    "dim_tempo": "marts",
    "fct_carga_horaria": "marts",
    "fct_clima_horario": "marts",
    "fct_pld_horario": "marts",
    "fct_pld_semanal": "marts",
    "fct_submercado_horario": "marts",
    "fct_carga_mensal": "marts",
}


class _Erro(Exception):
    pass


def _erro(mensagem):
    raise _Erro(mensagem)


def renderizar(custom, variaveis: dict) -> str:
    """Renderiza o macro como o dbt: `target.schema` = staging (o dataset padrão do perfil)."""
    ambiente = jinja2.Environment()
    ambiente.globals.update(
        var=lambda nome, padrao=None: variaveis.get(nome, padrao),
        target=SimpleNamespace(schema="staging"),
        exceptions=SimpleNamespace(raise_compiler_error=_erro),
    )
    modelo = ambiente.from_string(MACRO.read_text() + "{{ generate_schema_name(custom, none) }}")
    return modelo.render(custom=custom).strip()


@pytest.mark.parametrize("custom", ["staging", "marts", " marts "])
def test_sem_a_var_o_macro_devolve_o_schema_configurado_do_modelo(custom):
    assert renderizar(custom, {}) == custom.strip()


def test_sem_schema_configurado_usa_o_dataset_do_perfil():
    assert renderizar(None, {}) == "staging"


@pytest.mark.parametrize("custom", ["staging", "marts", None])
def test_com_a_var_todo_modelo_vai_para_o_dataset_de_verificacao(custom):
    v = {"dataset_verificacao": "verificacao_incremental"}
    assert renderizar(custom, v) == "verificacao_incremental"


@pytest.mark.parametrize("ruim", ["marts", "staging", "raw", "outro", ""])
def test_a_var_com_qualquer_outro_dataset_e_recusada(ruim):
    # "" é falso para o Jinja mas NÃO é none: não pode desviar nem passar em silêncio
    with pytest.raises(_Erro, match="só aceita 'verificacao_incremental'"):
        renderizar("marts", {"dataset_verificacao": ruim})


# ---------------------------------------------------------------- com o dbt de verdade (parse)
SEM_DBT = pytest.mark.skipif(
    not (DBT / "dbt_packages").exists() or not shutil.which("dbt"),
    reason="precisa do dbt instalado e de `dbt deps`",
)


def parse(tmp_path: Path, vars_: dict | None):
    shutil.copy(DBT / "profiles.yml.example", tmp_path / "profiles.yml")
    comando = [
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
    ]
    if vars_ is not None:
        comando += ["--vars", json.dumps(vars_)]
    ambiente = {
        **os.environ,
        "GCP_PROJECT_ID": "projeto-de-teste",
        "BQ_LOCATION": "us-central1",
        "CLOUDSDK_CONFIG": str(tmp_path / "sem-gcloud"),
        "GOOGLE_APPLICATION_CREDENTIALS": str(tmp_path / "nao-existe.json"),
    }
    return subprocess.run(comando, capture_output=True, text=True, env=ambiente, timeout=180)


def schemas(tmp_path: Path) -> dict[str, str]:
    manifesto = json.loads((tmp_path / "target" / "manifest.json").read_text())
    return {
        no["name"]: no["schema"]
        for no in manifesto["nodes"].values()
        if no["resource_type"] in ("model", "seed")
    }


@SEM_DBT
def test_sem_a_var_cada_modelo_e_seed_cai_exatamente_no_dataset_de_producao(tmp_path):
    r = parse(tmp_path, None)
    assert r.returncode == 0, r.stdout[-1000:]
    assert schemas(tmp_path) == PRODUCAO


@SEM_DBT
def test_com_a_var_todos_os_modelos_vao_para_o_dataset_de_verificacao(tmp_path):
    r = parse(tmp_path, {"dataset_verificacao": "verificacao_incremental"})
    assert r.returncode == 0, r.stdout[-1000:]
    obtido = schemas(tmp_path)
    assert set(obtido) == set(PRODUCAO)
    assert set(obtido.values()) == {"verificacao_incremental"}


@SEM_DBT
def test_o_parse_com_a_var_apontando_para_producao_falha(tmp_path):
    r = parse(tmp_path, {"dataset_verificacao": "marts"})
    assert r.returncode != 0
    assert re.search(r"só aceita 'verificacao_incremental'", r.stdout + r.stderr)
