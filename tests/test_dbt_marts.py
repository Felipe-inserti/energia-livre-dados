"""Guardas das dimensões (sem rede): calendário da ANEEL e coerência com os extratores e o YAML."""

import datetime as dt
import re
from pathlib import Path

import holidays
import yaml

from ingestion import inmet

RAIZ = Path(__file__).resolve().parent.parent
MARTS = RAIZ / "dbt" / "models" / "marts"
STAGING = RAIZ / "dbt" / "models" / "staging"
TESTES = RAIZ / "dbt" / "tests"


def sql(nome: str) -> str:
    return (MARTS / f"{nome}.sql").read_text()


def modelo_yaml(nome: str) -> dict:
    modelos = yaml.safe_load((MARTS / "_marts.yml").read_text())["models"]
    return next(m for m in modelos if m["name"] == nome)


def valores_aceitos(modelo: dict, coluna: str) -> list:
    col = next(c for c in modelo["columns"] if c["name"] == coluna)
    teste = next(t for t in col["data_tests"] if isinstance(t, dict) and "accepted_values" in t)
    return teste["accepted_values"]["arguments"]["values"]


def projeto() -> dict:
    return yaml.safe_load((RAIZ / "dbt" / "dbt_project.yml").read_text())


# ---------------------------------------------------------------- modelos


def test_tres_dimensoes_e_sem_dim_fonte():
    assert {p.stem for p in MARTS.glob("dim_*.sql")} == {
        "dim_tempo",
        "dim_submercado",
        "dim_estacao",
    }
    # dim_fonte depende da geração por fonte, que foi adiada (item de corte)
    assert not list(MARTS.glob("dim_fonte*"))


def test_marts_vao_para_o_dataset_marts():
    config = projeto()["models"]["energia_livre"]["marts"]
    assert config["+schema"] == "marts" and config["+materialized"] == "table"


def test_variaveis_do_calendario():
    v = projeto()["vars"]
    assert v["data_inicio_dim_tempo"] == "2000-01-01" and v["data_fim_dim_tempo"] == "2030-12-31"
    assert (v["hora_ponta_inicio"], v["horas_de_ponta"]) == (18, 3)  # 18h às 20h59
    assert v["limite_mudanca_estacao_m"] == 500


# ---------------------------------------------------------------- feriados da ANEEL


def test_carnaval_e_corpus_christi_derivam_da_sexta_feira_santa():
    """A dim_tempo deriva a terça de Carnaval (-45 dias) e o Corpus Christi (+62) da Sexta-feira
    Santa; aqui se confere a aritmética contra a biblioteca `holidays` nos 31 anos do calendário."""
    anos = range(2000, 2031)
    publicos = holidays.Brazil(years=anos, categories=("public",))
    todos = holidays.Brazil(years=anos, categories=("public", "optional"))
    for ano in anos:
        sexta = next(d for d, n in publicos.items() if d.year == ano and "Sexta-feira Santa" in n)
        carnaval = [
            d for d, n in todos.items() if d.year == ano and n == "Carnaval" and d.weekday() == 1
        ]
        corpus = [d for d, n in todos.items() if d.year == ano and n == "Corpus Christi"]
        assert carnaval == [sexta - dt.timedelta(days=45)], ano
        assert corpus == [sexta + dt.timedelta(days=62)], ano


def test_lista_da_aneel_tem_11_feriados_por_ano_e_10_em_2000():
    anos = range(2000, 2031)
    publicos = holidays.Brazil(years=anos, categories=("public",))
    for ano in anos:
        sexta = next(d for d, n in publicos.items() if d.year == ano and "Sexta-feira Santa" in n)
        aneel = {d for d, n in publicos.items() if d.year == ano and "Consciência Negra" not in n}
        aneel |= {sexta - dt.timedelta(days=45), sexta + dt.timedelta(days=62)}
        # em 2000 a Sexta-feira Santa caiu em 21 de abril, o dia de Tiradentes
        assert len(aneel) == (10 if ano == 2000 else 11), ano


def test_dim_tempo_usa_a_data_local_e_a_lista_da_aneel():
    codigo = re.sub(r"\{#.*?#\}", "", sql("dim_tempo"), flags=re.S)
    assert "f.data_feriado = c.data_local" in codigo  # o feriado vale na data LOCAL, não na UTC
    assert "a.data = c.data_local" in codigo
    assert "interval 45 day" in codigo and "interval 62 day" in codigo
    assert "Consciência Negra" in codigo  # excluída da lista da ANEEL
    assert "generate_timestamp_array" in codigo and "'America/Sao_Paulo'" in codigo
    assert "isodayofweek" not in codigo.lower()  # o EXTRACT do BigQuery não aceita ISODAYOFWEEK


def test_valores_do_yaml_batem_com_o_sql_da_dim_tempo():
    modelo = modelo_yaml("dim_tempo")
    codigo = sql("dim_tempo")
    for coluna in ("tipo_dia", "estacao_do_ano"):
        for valor in valores_aceitos(modelo, coluna):
            assert f"'{valor}'" in codigo, (coluna, valor)
    assert valores_aceitos(modelo, "deslocamento_utc_horas") == [-3, -2]


def test_accepted_values_numericos_sem_aspas():
    """O dbt coloca aspas nos valores por padrão e o BigQuery recusa `INT64 IN ('1')`."""
    texto = (MARTS / "_marts.yml").read_text()
    for lista in ("[-3, -2]", "[1, 2, 3, 4, 5, 6, 7]", "[0, 1, 2]"):
        trecho = texto.split(f"values: {lista}")[1][:60]
        assert "quote: false" in trecho, lista


def test_feriado_composto_e_horario_de_verao_tem_teste():
    composto = (TESTES / "dim_tempo_feriado_composto_desmembrado.sql").read_text()
    assert "2000-04-21" in composto and "Tiradentes" in composto and "Sexta-feira Santa" in composto
    verao = (TESTES / "dim_tempo_horario_de_verao_termina_em_2019.sql").read_text()
    assert "2019-02-17" in verao


# ---------------------------------------------------------------- dim_submercado


def test_dim_submercado_cobre_os_codigos_do_ons_e_os_nomes_da_ccee():
    modelo = modelo_yaml("dim_submercado")
    staging = yaml.safe_load((STAGING / "_staging.yml").read_text())["models"]
    por_nome = {m["name"]: m for m in staging}

    def aceitos(nome_modelo, coluna):
        col = next(c for c in por_nome[nome_modelo]["columns"] if c["name"] == coluna)
        teste = next(t for t in col["data_tests"] if isinstance(t, dict) and "accepted_values" in t)
        return set(teste["accepted_values"]["arguments"]["values"])

    assert set(valores_aceitos(modelo, "codigo_submercado")) == aceitos(
        "stg_ons__curva_carga", "id_subsistema"
    )
    assert set(valores_aceitos(modelo, "nome_ccee")) == aceitos(
        "stg_ccee__pld_horario", "submercado"
    )
    codigo = sql("dim_submercado")
    # o SE do ONS tem dois nomes (SUDESTE até 2025, SUDESTE/CENTRO-OESTE em 2026)
    assert "'SUDESTE/CENTRO-OESTE'" in codigo and "'SUDESTE'" in codigo and "'SE/CO'" in codigo


# ---------------------------------------------------------------- dim_estacao


def test_dim_estacao_e_testes_batem_com_a_lista_de_estacoes():
    assert len(inmet.ESTACOES) == 37
    assert "!= 37" in (TESTES / "dim_estacao_tem_as_37_estacoes.sql").read_text()
    ufs = {uf for uf, _ in inmet.ESTACOES.values()}
    assert set(valores_aceitos(modelo_yaml("dim_estacao"), "uf")) == ufs
    codigo = sql("dim_estacao")
    for uf in ufs:  # toda UF das estações tem uma região no CASE (senão `regiao` fica nula)
        assert f"'{uf}'" in codigo, uf


def test_estacoes_que_mudaram_de_lugar_estao_na_lista_e_o_teste_so_avisa():
    teste = (TESTES / "dim_estacao_mudancas_de_lugar_esperadas.sql").read_text()
    assert "severity='warn'" in teste
    esperadas = set(re.findall(r"'(A\d{3})'", teste))
    assert esperadas == {"A042", "A704"} and esperadas <= set(inmet.ESTACOES)


def test_dim_estacao_usa_o_registro_mais_recente_e_distancia_geografica():
    codigo = sql("dim_estacao")
    assert "order by instante_utc desc" in codigo and "order by instante_utc asc" in codigo
    assert "st_distance" in codigo and "st_geogpoint(" in codigo
    assert "var('limite_mudanca_estacao_m')" in codigo


# ---------------------------------------------------------------- relacionamentos


def test_todo_modelo_de_staging_tem_relationships_com_as_dimensoes():
    staging = yaml.safe_load((STAGING / "_staging.yml").read_text())["models"]
    destinos = set()
    for modelo in staging:
        rels = []
        for coluna in modelo.get("columns", []):
            for teste in coluna.get("data_tests", []):
                if isinstance(teste, dict) and "relationships" in teste:
                    rels.append(teste["relationships"]["arguments"]["to"])
        assert rels, f"{modelo['name']} sem relationships"
        destinos.update(rels)
    assert destinos == {"ref('dim_tempo')", "ref('dim_submercado')", "ref('dim_estacao')"}
