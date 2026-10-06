"""Guardas dos testes de qualidade do dbt (Sprint 3): seed dos limites do PLD e freshness."""

import csv
from decimal import Decimal
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parent.parent
SEED = RAIZ / "dbt" / "seeds" / "pld_limites.csv"
FONTES = RAIZ / "dbt" / "models" / "staging" / "_sources.yml"
TESTES = RAIZ / "dbt" / "tests"

# Valores que o PLD horário de cada ano de fato atingiu como mínimo (docs/fontes.md): o piso do seed
# tem de ser igual a eles, e foi assim que os valores de fonte secundária foram conferidos.
MINIMO_OBSERVADO = {
    2021: "49.77",
    2022: "55.70",
    2023: "69.04",
    2024: "61.07",
    2025: "58.60",
    2026: "57.31",
}
FONTES_MANUAIS = {"ccee_pld_horario", "ccee_consumo_ramo_atividade", "inmet_estacoes_horario"}


def limites():
    with SEED.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_seed_cobre_2021_a_2026_sem_buraco_e_o_piso_bate_com_o_minimo_observado():
    linhas = limites()
    assert [int(x["ano"]) for x in linhas] == list(range(2021, 2027))
    for x in linhas:
        assert Decimal(x["pld_min"]) == Decimal(MINIMO_OBSERVADO[int(x["ano"])])


def test_seed_piso_menor_que_teto_estrutural_menor_que_teto_horario():
    for x in limites():
        assert (
            Decimal(x["pld_min"]) < Decimal(x["pld_max_estrutural"]) < Decimal(x["pld_max_horario"])
        )


def test_seed_nao_afirma_confirmacao_oficial_sem_ter_lido_o_documento():
    # Quando alguém ler o texto oficial de um ano, troca para true e ajusta este teste.
    assert all(x["confirmado_em_fonte_oficial"] == "false" for x in limites())


def test_fontes_manuais_so_avisam_e_o_ons_e_o_unico_que_pode_falhar():
    tabelas = {t["name"]: t for t in yaml.safe_load(FONTES.read_text())["sources"][0]["tables"]}
    for nome, tabela in tabelas.items():
        freshness = tabela.get("config", {}).get("freshness")
        if nome in FONTES_MANUAIS:
            assert freshness and "warn_after" in freshness and "error_after" not in freshness, nome
        elif nome == "ons_curva_carga":
            assert freshness["warn_after"] and freshness["error_after"]
        assert (freshness is None) or tabela["config"]["loaded_at_field"], nome


def test_teste_de_alerta_nao_devolve_linha_a_menos_que_a_variavel_peca():
    texto = (TESTES / "teste_alerta_falha_proposital.sql").read_text()
    assert "config(severity='error')" in texto
    assert "env_var('FORCAR_FALHA', 'false')" in texto  # o padrão tem de ser "não falhar"


def test_todo_teste_singular_novo_declara_a_severidade_de_proposito():
    novos = [
        "fct_pld_horario_dentro_dos_limites",
        "fct_carga_horaria_carga_positiva_e_plausivel",
        "fct_carga_horaria_nulos_so_nos_dias_conhecidos",
        "fct_carga_horaria_excecoes_de_nulos_ainda_existem",
        "fct_clima_horario_temperatura_plausivel",
        "fct_clima_horario_completude_estacao_por_ano",
    ]
    esperado = {n: "error" for n in novos}
    esperado["fct_carga_horaria_excecoes_de_nulos_ainda_existem"] = "warn"
    esperado["fct_clima_horario_completude_estacao_por_ano"] = "warn"
    for nome, severidade in esperado.items():
        texto = (TESTES / f"{nome}.sql").read_text()
        assert f"config(severity='{severidade}')" in texto, nome
