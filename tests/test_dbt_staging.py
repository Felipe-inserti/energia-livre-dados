"""Guardas dos modelos de staging (sem rede): nomes, testes e decisões de projeto."""

import datetime as dt
import re
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parent.parent
STAGING = RAIZ / "dbt" / "models" / "staging"
TESTES = RAIZ / "dbt" / "tests"

MODELOS = {
    "stg_ons__curva_carga",
    "stg_ccee__pld_horario",
    "stg_ccee__pld_semanal",
    "stg_ccee__consumo_ramo_atividade",
    "stg_inmet__estacoes_horario",
    "stg_feriados",
}


def modelos_yaml() -> list[dict]:
    return yaml.safe_load((STAGING / "_staging.yml").read_text())["models"]


def test_um_modelo_de_staging_para_cada_tabela_do_raw():
    arquivos = {p.stem for p in STAGING.glob("stg_*.sql")}
    assert arquivos == MODELOS
    assert {m["name"] for m in modelos_yaml()} == MODELOS


def test_todo_modelo_tem_descricao_e_teste_de_chave():
    for modelo in modelos_yaml():
        assert len(modelo["description"].strip()) > 40, modelo["name"]
        chaves = [t for t in modelo.get("data_tests", []) if isinstance(t, dict)]
        unicidade = [t for t in chaves if "dbt_utils.unique_combination_of_columns" in t]
        por_coluna = [c for c in modelo.get("columns", []) if "unique" in c.get("data_tests", [])]
        assert unicidade or por_coluna, f"{modelo['name']} sem teste de unicidade"


def test_modelos_que_nao_descartam_linhas_comparam_a_contagem_com_o_raw():
    esperados_com_contagem = {
        "stg_ccee__pld_horario",
        "stg_ccee__pld_semanal",
        "stg_ccee__consumo_ramo_atividade",
        "stg_inmet__estacoes_horario",
        "stg_feriados",
    }
    for modelo in modelos_yaml():
        testes = [next(iter(t)) for t in modelo.get("data_tests", []) if isinstance(t, dict)]
        if modelo["name"] in esperados_com_contagem:
            assert "dbt_utils.equal_rowcount" in testes, modelo["name"]


def test_staging_usa_cast_e_nao_safe_cast():
    """Decisão: valor mal formatado derruba o modelo em vez de virar NULL em silêncio."""
    for sql in [*STAGING.glob("stg_*.sql"), *(RAIZ / "dbt" / "macros").glob("*.sql")]:
        codigo = re.sub(r"\{#.*?#\}", "", sql.read_text(), flags=re.S)  # ignora comentários
        assert "safe_cast" not in codigo.lower(), sql.name


def test_preco_do_pld_e_numeric_e_nao_float():
    for nome in ("stg_ccee__pld_horario", "stg_ccee__pld_semanal"):
        sql = (STAGING / f"{nome}.sql").read_text()
        assert "as numeric" in sql and "pld_hora as float64" not in sql


def test_ons_converte_com_fuso_nomeado_e_nao_com_offset_fixo():
    sql = (STAGING / "stg_ons__curva_carga.sql").read_text()
    assert "'America/Sao_Paulo'" in sql
    assert not re.search(r"interval\s+3\s+hour|-03:00|\+ *3 *hour", sql, flags=re.I)


def test_ons_descarta_hora_inexistente_antes_da_deduplicacao():
    sql = (STAGING / "stg_ons__curva_carga.sql").read_text()
    posicao = {nome: sql.index(nome) for nome in ("horas_que_existem", "deduplicada")}
    assert posicao["horas_que_existem"] < posicao["deduplicada"]
    assert "datetime(instante_utc, 'America/Sao_Paulo') = instante_local" in sql


def test_horas_descartadas_conhecidas_sao_domingos_de_2014_a_2018():
    """As 5 datas do teste singular são os inícios do horário de verão (sempre num domingo)."""
    sql = (TESTES / "ons_descarta_so_horas_conhecidas.sql").read_text()
    datas = [
        dt.date.fromisoformat(d)
        for d in re.findall(r"datetime '(\d{4}-\d{2}-\d{2}) 00:00:00'", sql)
    ]
    assert [d.year for d in datas] == [2014, 2015, 2016, 2017, 2018]
    assert all(d.weekday() == 6 for d in datas)  # domingo
    assert all(d.month in (10, 11) for d in datas)  # início do horário de verão
