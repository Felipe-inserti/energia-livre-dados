"""Guardas dos fatos e dos intermediários (sem rede): partição, grãos, camadas e limites."""

import datetime as dt
import re
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parent.parent
DBT = RAIZ / "dbt"
MARTS = DBT / "models" / "marts"
INTERMEDIATE = DBT / "models" / "intermediate"
TESTES = DBT / "tests"

FATOS = {"fct_carga_horaria", "fct_pld_horario", "fct_clima_horario", "fct_pld_semanal"}
INTERMEDIARIOS = {
    "int_clima_estado_horario",
    "int_clima_submercado_horario",
    "int_submercado_horario",
}
PARTICIONADOS = {
    "fct_carga_horaria",
    "fct_pld_horario",
    "fct_clima_horario",
}  # + int_submercado_horario


def codigo(caminho: Path) -> str:
    """SQL sem os comentários {# ... #} (o que está escrito neles não conta como código)."""
    return re.sub(r"\{#.*?#\}", "", caminho.read_text(), flags=re.S)


def yaml_modelos(caminho: Path) -> dict[str, dict]:
    return {m["name"]: m for m in yaml.safe_load(caminho.read_text())["models"]}


# ---------------------------------------------------------------- modelos


def test_quatro_fatos_e_tres_intermediarios():
    assert {p.stem for p in MARTS.glob("fct_*.sql")} == FATOS
    assert {p.stem for p in INTERMEDIATE.glob("int_*.sql")} == INTERMEDIARIOS
    assert not list(MARTS.glob("dim_fonte*"))  # adiada com a geração por fonte


def test_intermediate_vai_para_o_dataset_staging():
    config = yaml.safe_load((DBT / "dbt_project.yml").read_text())["models"]["energia_livre"]
    assert config["intermediate"]["+schema"] == "staging"  # só existem raw, staging e marts
    assert config["intermediate"]["+materialized"] == "table"


def test_camadas_nao_se_invertem():
    """Os fatos não leem intermediários e os intermediários não leem fatos."""
    for fato in FATOS:
        assert "ref('int_" not in codigo(MARTS / f"{fato}.sql"), fato
    for inter in INTERMEDIARIOS:
        assert "ref('fct_" not in codigo(INTERMEDIATE / f"{inter}.sql"), inter


# ---------------------------------------------------------------- partição e cluster


def config_do_modelo(caminho: Path) -> str:
    m = re.search(r"\{\{\s*config\((.*?)\)\s*\}\}", codigo(caminho), flags=re.S)
    return m.group(1) if m else ""


def test_fatos_horarios_sao_particionados_por_mes_em_instante_utc():
    modelos = [MARTS / f"{f}.sql" for f in PARTICIONADOS] + [
        INTERMEDIATE / "int_submercado_horario.sql"
    ]
    for caminho in modelos:
        cfg = config_do_modelo(caminho)
        assert "'field': 'instante_utc'" in cfg, caminho.name
        assert "'data_type': 'timestamp'" in cfg, caminho.name
        assert "'granularity': 'month'" in cfg, caminho.name  # nunca diária (limites do BigQuery)
        assert "'granularity': 'day'" not in cfg, caminho.name
        assert "cluster_by=" in cfg, caminho.name


def test_clusterizacao_por_submercado_e_por_uf_e_estacao():
    assert "cluster_by=['codigo_submercado']" in config_do_modelo(MARTS / "fct_carga_horaria.sql")
    assert "cluster_by=['codigo_submercado']" in config_do_modelo(MARTS / "fct_pld_horario.sql")
    assert "cluster_by=['uf', 'estacao_codigo']" in config_do_modelo(
        MARTS / "fct_clima_horario.sql"
    )
    for caminho in [*MARTS.glob("fct_*.sql"), *INTERMEDIATE.glob("int_*.sql")]:
        cfg = config_do_modelo(caminho)
        if "cluster_by=" in cfg:
            colunas = re.search(r"cluster_by=\[(.*?)\]", cfg).group(1).split(",")
            assert len(colunas) <= 4  # limite do BigQuery: até 4 colunas de cluster


def test_pld_semanal_nao_e_particionado_e_nao_exige_filtro_de_particao():
    assert "partition_by" not in config_do_modelo(MARTS / "fct_pld_semanal.sql")
    for caminho in [*MARTS.glob("*.sql"), *INTERMEDIATE.glob("*.sql")]:
        # o `dbt test` varre tabelas inteiras: exigir filtro de partição quebraria os testes
        assert "require_partition_filter" not in codigo(caminho), caminho.name


def test_a_conta_dos_limites_de_particao_do_bigquery():
    """Por que mensal: o ONS desde 2000 passaria dos 10.000 partições diárias em 2027, e já passa
    dos 4.000 (por job, segundo fontes secundárias) hoje."""
    inicio, hoje = dt.date(2000, 1, 1), dt.date(2026, 10, 2)
    dias = (hoje - inicio).days + 1
    assert dias == 9772
    assert inicio + dt.timedelta(days=10_000) == dt.date(2027, 5, 19)  # 1º dia além do limite
    assert dias > 4_000  # uma carga diária completa já estouraria o limite por job
    meses = (hoje.year - inicio.year) * 12 + hoje.month - inicio.month + 1
    assert meses == 322  # mensal: longe de qualquer limite


# ---------------------------------------------------------------- grãos, chaves e testes


def test_todo_fato_tem_chave_unica_contagem_contra_o_staging_e_relationships():
    modelos = yaml_modelos(MARTS / "_marts.yml")
    for nome in FATOS:
        modelo = modelos[nome]
        testes = [next(iter(t)) for t in modelo["data_tests"]]
        assert "dbt_utils.unique_combination_of_columns" in testes, nome
        assert "dbt_utils.equal_rowcount" in testes, nome
        relacionamentos = [
            t["relationships"]["arguments"]["to"]
            for c in modelo["columns"]
            for t in c.get("data_tests", [])
            if isinstance(t, dict) and "relationships" in t
        ]
        assert len(relacionamentos) >= 2, nome


def test_chaves_dos_fatos():
    modelos = yaml_modelos(MARTS / "_marts.yml")

    def chave(nome):
        t = modelos[nome]["data_tests"][0]["dbt_utils.unique_combination_of_columns"]
        return t["arguments"]["combination_of_columns"]

    assert chave("fct_carga_horaria") == ["codigo_submercado", "instante_utc"]
    assert chave("fct_pld_horario") == ["codigo_submercado", "instante_utc"]
    assert chave("fct_clima_horario") == ["estacao_codigo", "instante_utc"]
    assert chave("fct_pld_semanal") == [
        "codigo_submercado",
        "inicio_semana_utc",
        "ordem_preco_na_semana",
    ]


def test_intermediarios_tem_chave_unica_e_relationships():
    modelos = yaml_modelos(INTERMEDIATE / "_intermediate.yml")
    assert set(modelos) == INTERMEDIARIOS
    for nome, modelo in modelos.items():
        testes = [next(iter(t)) for t in modelo["data_tests"]]
        assert "dbt_utils.unique_combination_of_columns" in testes, nome


def test_o_fato_de_clima_fica_no_grao_estacao_e_a_agregacao_nos_intermediarios():
    clima = codigo(MARTS / "fct_clima_horario.sql")
    assert "avg(" not in clima.lower() and "group by" not in clima.lower()  # sem agregação no fato
    assert "estacao_codigo" in clima and "uf," in clima
    estado = codigo(INTERMEDIATE / "int_clima_estado_horario.sql")
    assert (
        "avg(temperatura_c)" in estado and "last_value(temperatura_media_c ignore nulls)" in estado
    )
    assert "3 preceding and 1 preceding" in estado  # imputa só até 3 horas


def test_temperatura_do_submercado_e_media_simples_e_provisoria():
    texto = (INTERMEDIATE / "int_clima_submercado_horario.sql").read_text()
    assert "PROVISÓRIO" in texto and "pesos" in texto and "premissas.md" in texto
    assert "avg(temperatura_c)" in codigo(INTERMEDIATE / "int_clima_submercado_horario.sql")


def test_pld_entra_nos_fatos_pelo_codigo_do_ons_e_nao_pelo_nome_da_ccee():
    for nome in ("fct_pld_horario", "fct_pld_semanal"):
        assert "dim_submercado" in codigo(MARTS / f"{nome}.sql") and "nome_ccee" in codigo(
            MARTS / f"{nome}.sql"
        )


def test_o_teste_do_preco_de_2020_usa_o_valor_documentado():
    teste = (TESTES / "fct_pld_semanal_reproduz_o_preco_de_2020.sql").read_text()
    assert "178.03" in teste and "8784" in teste
    assert "178,03" in (RAIZ / "docs" / "premissas.md").read_text()  # o mesmo número da premissa


def test_testes_singulares_dos_fatos_existem():
    esperados = {
        "fct_clima_horario_uf_bate_com_dim_estacao",
        "fct_pld_semanal_reproduz_o_preco_de_2020",
        "int_submercado_horario_preserva_as_linhas_das_fontes",
        "int_clima_estado_horario_imputacao_so_quando_falta_dado",
        "int_clima_estado_horario_grade_completa",
    }
    assert esperados <= {p.stem for p in TESTES.glob("*.sql")}
