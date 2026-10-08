"""Seed `ajuste_definicao_carga` e mart `fct_carga_mensal` (Sprint 4, Parte B): o que se confere sem
BigQuery. O seed versionado tem de bater com as regras do script que o gera, e as datas de quebra do
dbt (vars) com as do script; as consultas na nuvem ficam por conta dos testes do dbt."""

import csv
import re
from pathlib import Path

import pytest
import yaml

from scripts import baixar_mmgd_ons as gerador

RAIZ = Path(__file__).resolve().parents[1]
SEED = RAIZ / "dbt" / "seeds" / "ajuste_definicao_carga.csv"
SQL_MART = (RAIZ / "dbt" / "models" / "marts" / "fct_carga_mensal.sql").read_text()
VARS = yaml.safe_load((RAIZ / "dbt" / "dbt_project.yml").read_text())["vars"]


@pytest.fixture(scope="module")
def linhas():
    with SEED.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_o_seed_tem_as_colunas_do_script(linhas):
    assert tuple(linhas[0]) == gerador.COLUNAS


def test_o_seed_cobre_4_submercados_x_76_meses_sem_buraco(linhas):
    assert len(linhas) == 4 * 76
    for sm in ("SE", "S", "NE", "N"):
        meses = [r["mes"][:7] for r in linhas if r["codigo_submercado"] == sm]
        assert meses == sorted(meses) and meses[0] == "2018-01" and meses[-1] == "2024-04"
        assert len(set(meses)) == 76


def test_os_status_do_seed_seguem_as_regras_do_script(linhas):
    for r in linhas:
        mes = r["mes"][:7]
        assert r["status_tipo3"] == gerador.status_tipo3(mes), r
        esperado = gerador.status_mmgd(
            mes, int(r["api_intervalos"]), int(r["api_intervalos_sem_mmgd"])
        )
        assert r["status_mmgd"] == esperado, r


def test_global_fecha_com_liquida_mais_mmgd_e_mmgd_nao_negativa(linhas):
    for r in linhas:
        glob, liq, mm = (
            float(r[k]) for k in ("api_global_mwmed", "api_liquida_mwmed", "api_mmgd_mwmed")
        )
        assert glob - liq - mm == pytest.approx(0, abs=1e-3), r
        assert mm >= 0 and liq > 0


def test_o_seed_guarda_a_data_da_consulta(linhas):
    datas = {r["consultado_em"] for r in linhas}
    assert len(datas) == 1 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", datas.pop())


def test_a_mmgd_so_aparece_depois_de_2019_02_15(linhas):
    for r in linhas:
        if r["mes"] < "2019-02-01":
            assert float(r["api_mmgd_mwmed"]) == 0 and r["status_mmgd"] == "zero_por_premissa"


def test_as_quebras_do_dbt_sao_as_do_script():
    assert VARS["mes_quebra_tipo3"][:7] == gerador.PRIMEIRO_MES_COM_TIPO3_NA_CURVA
    assert VARS["mes_quebra_mmgd"][:7] == gerador.PRIMEIRO_MES_COM_MMGD_NA_CURVA
    assert VARS["inicio_api_carga"][:7] == gerador.INICIO_PADRAO


def test_a_regra_de_transicao_do_tipo3_e_unica_e_usa_as_vars():
    assert VARS["ruido_k_tipo3"] == 3 and VARS["ano_ruido_tipo3"] == 2022
    assert VARS["meses_ruido_para_encerrar"] == 2  # 1 mês de sorte dentro do ruído não encerra
    # a regra é uma só para os 4 submercados: nenhum SQL cita um submercado pelo nome
    assert not re.search(r"'(SE|S|NE|N)'", SQL_MART)
    assert "stddev_samp(dif)" in SQL_MART and "abs(d.dif) <= r.limiar" in SQL_MART
    # o fim é o 1º mês que abre uma sequência de N meses dentro do ruído; depois, zero sem voltar
    assert "min(mes) as fim_transicao" in SQL_MART
    assert "range(1, var('meses_ruido_para_encerrar'))" in SQL_MART and "lead(dentro" in SQL_MART
    assert "medido_transicao" in SQL_MART
    # o ano do ruído é depois da transição e antes da MMGD na curva
    assert (
        VARS["mes_quebra_tipo3"][:4] <= str(VARS["ano_ruido_tipo3"]) < VARS["mes_quebra_mmgd"][:4]
    )


def test_o_mart_so_usa_vars_que_existem():
    for nome in re.findall(r'var\("(\w+)"\)', SQL_MART):
        assert nome in VARS, nome


def test_o_mart_nao_e_particionado():
    # ~1.300 linhas: partição só adicionaria custo (mesmo critério da fct_pld_semanal)
    assert "partition_by" not in SQL_MART and "cluster_by" not in SQL_MART


def test_o_sh_roda_o_seed_o_mart_e_os_testes_com_tee():
    sh = (RAIZ / "scripts" / "passo2_carga_mensal.sh").read_text()
    for trecho in ("dbt seed", "dbt run", "dbt test", "tee "):
        assert trecho in sh or trecho in sh.replace("$DBT ", "dbt ")
    assert "ajuste_definicao_carga" in sh and "fct_carga_mensal" in sh
    assert "data/logs/passo2" in sh


def test_a_cobertura_minima_aceita_um_dia_faltando_e_recusa_dois():
    limiar = VARS["cobertura_minima"]
    for dias in (28, 29, 30, 31):
        assert (dias - 1) / dias >= limiar, dias  # 1 dia faltando passa (96,4% a 96,8%)
        assert (dias - 2) / dias < limiar, dias  # 2 dias faltando não passa (93,1% a 93,5%)


def test_as_lacunas_conhecidas_sao_meses_fechados_e_ordenados():
    meses = VARS["meses_com_lacuna_conhecida"]
    assert meses == ["2013-12-01", "2014-02-01", "2015-04-01"]
    assert all(m.endswith("-01") for m in meses)


def test_o_mart_define_mes_incompleto_pela_data_e_conta_horas_locais():
    # a causa dos 81 falsos "meses incompletos" (todo fevereiro de 2000 a 2019, mais as lacunas)
    assert "current_date('America/Sao_Paulo')" in SQL_MART
    assert "count(distinct unix_date(data_local) * 24 + hora_local)" in SQL_MART
    assert "horas_com_linha < g.horas_esperadas" not in SQL_MART
    assert "safe_divide(m.horas_validas, g.horas_esperadas)" in SQL_MART


def test_os_testes_novos_do_mart_existem_e_o_antigo_saiu():
    testes = {p.stem for p in (RAIZ / "dbt" / "tests").glob("*.sql")}
    assert {
        "fct_carga_mensal_mes_incompleto_e_o_mes_corrente",
        "fct_carga_mensal_cobertura_dos_meses_fechados",
        "fct_carga_mensal_lacunas_so_as_conhecidas",
    } <= testes
    assert "fct_carga_mensal_so_o_ultimo_mes_e_incompleto" not in testes


def test_a_sequencia_de_n_meses_e_gerada_pelo_jinja_para_qualquer_n():
    """O SQL compilado com N = 1, 2 e 3 tem N - 1 `lead` (N = 1 é a regra antiga, de 1 mês)."""
    import jinja2

    trecho = SQL_MART[
        SQL_MART.index("seguidos as (") : SQL_MART.index("-- primeiro mês que encerra")
    ]
    for n in (1, 2, 3):
        saida = jinja2.Template(trecho).render(var=lambda nome, _n=n: _n)
        assert saida.count("lead(dentro") == n - 1, n


# ------------------------------------------------ reconstrução do tipo III (Sprint 5)

SEED_CM = RAIZ / "dbt" / "seeds" / "carga_mensal_ons.csv"


def test_o_seed_da_carga_mensal_cobre_4_submercados_x_48_meses_positivos():
    from scripts import baixar_carga_mensal_ons as gerador

    with SEED_CM.open(encoding="utf-8") as f:
        linhas = list(csv.DictReader(f))
    assert tuple(linhas[0]) == gerador.COLUNAS and len(linhas) == 4 * 48
    for sm in ("SE", "S", "NE", "N"):
        meses = [r["mes"][:7] for r in linhas if r["codigo_submercado"] == sm]
        assert meses[0] == "2015-01" and meses[-1] == "2018-12" and meses == sorted(set(meses))
    assert all(float(r["carga_mensal_ons_mwmed"]) > 0 for r in linhas)  # nada dos zeros de 2026


def test_o_gerador_recorta_a_janela_e_recusa_zero():
    from scripts import baixar_carga_mensal_ons as gerador

    texto = (
        "id_subsistema;nom_subsistema;din_instante;val_cargaenergiamwmed\n"
        "SE;Sudeste;2015-01-31;41386.7386\nN ;Norte;2015-01-31;5126.1369\n"
        "SE;Sudeste;2014-12-31;36000.0\nSE;Sudeste;2026-09-30;0\n"
    )
    linhas = gerador.montar_linhas(texto, "2015-01", "2018-12", "2026-10-08")
    assert [(r["mes"], r["codigo_submercado"]) for r in linhas] == [
        ("2015-01-01", "N"),
        ("2015-01-01", "SE"),
    ]  # o espaço do "N " sai, 2014 e 2026 ficam fora da janela
    with pytest.raises(ValueError):
        gerador.montar_linhas(texto, "2015-01", "2026-12", "2026-10-08")  # zero dentro da janela


def test_o_mart_so_reconstrui_na_janela_e_nao_cita_submercado():
    assert VARS["inicio_reconstrucao_tipo3"] == "2015-01-01"
    assert "reconstruido_carga_mensal" in SQL_MART and "ref('carga_mensal_ons')" in SQL_MART
    assert not re.search(r"'(SE|S|NE|N)'", SQL_MART)


def test_o_mart_arredonda_a_carga_na_origem_para_a_serie_ser_estavel():
    assert VARS["casas_decimais_carga"] == 3
    assert "round(avg(carga_mwmed)" in SQL_MART  # a origem do ruído do AVG paralelo
    for coluna in (
        "carga_ajustada_mwmed",
        "carga_ajustada_r1_mwmed",
        "carga_ajustada_reconstruida_mwmed",
        "ajuste_tipo3_reconstruido_mwmed",
    ):
        i = SQL_MART.index(f"as {coluna}") if f"as {coluna}" in SQL_MART else SQL_MART.index(coluna)
        assert "round(" in SQL_MART[max(0, i - 400) : i + 40], coluna
    teste = (RAIZ / "dbt" / "tests" / "fct_carga_mensal_reconcilia_com_horaria.sql").read_text()
    assert "casas_decimais_carga" in teste and "1e-6" not in teste.split("--")[-1]
