from decimal import Decimal

import pytest

from scripts import medir_consultas as mc


def test_como_pares_aceita_row_dict_tupla_e_numeric():
    linhas = [{"hora": 0, "v": Decimal("61.07")}, (1, 62.5)]
    assert mc.como_pares(linhas) == [(0, 61.07), (1, 62.5)]


def test_resultados_iguais_com_tolerancia():
    a = [(0, 100.0), (1, 200.0)]
    assert mc.resultados_iguais(a, [(0, 100.0000001), (1, 200.0)])
    assert not mc.resultados_iguais(a, [(0, 100.5), (1, 200.0)])


def test_resultados_com_horas_diferentes_nao_sao_iguais():
    assert not mc.resultados_iguais([(0, 1.0)], [(1, 1.0)])
    assert not mc.resultados_iguais([(0, 1.0), (1, 2.0)], [(0, 1.0)])


def test_variacao_percentual():
    assert mc.variacao_percentual(200, 100) == -50.0
    assert mc.variacao_percentual(0, 5) == 0.0


def test_tres_fontes_com_consultas_em_pares():
    assert set(mc.PARES) == {"ons", "ccee", "inmet"}
    for par in mc.PARES.values():
        assert "{tabela}" in par.sql_raw and "{tabela}" in par.sql_staging
        assert par.tabela_staging.startswith("stg_")


def test_consultas_do_staging_respondem_a_mesma_pergunta_do_raw():
    ons_, ccee_, inmet_ = (mc.PARES[k] for k in ("ons", "ccee", "inmet"))
    # ONS e CCEE: hora e ano LOCAIS (horário de Brasília), como no raw
    for par in (ons_, ccee_):
        assert "AT TIME ZONE 'America/Sao_Paulo'" in par.sql_staging
        assert "TIMESTAMP('2024-01-01', 'America/Sao_Paulo')" in par.sql_staging
    assert "id_subsistema = 'SE'" in ons_.sql_staging and "'SE'" in ons_.sql_raw
    assert "'SUDESTE'" in ccee_.sql_staging and "'SUDESTE'" in ccee_.sql_raw
    # INMET: UTC nas duas tabelas
    assert "uf = 'SP'" in inmet_.sql_staging and "'SP'" in inmet_.sql_raw
    assert "America/Sao_Paulo" not in inmet_.sql_staging


def test_staging_nao_precisa_de_cast_na_consulta():
    for par in mc.PARES.values():
        assert "SAFE_CAST" not in par.sql_staging  # tipado: o ganho da 2.2 é justamente isso
        assert "SAFE_CAST" in par.sql_raw


def test_main_sem_tabela_devolve_2(monkeypatch, capsys):
    from google.api_core.exceptions import NotFound

    def falha(*args, **kwargs):
        raise NotFound("Not found: Table x")

    monkeypatch.setattr(mc, "carregar_config", lambda: mc.Config("p", "b", "l"))
    monkeypatch.setattr(mc.gcp, "cliente_bigquery", lambda c: object())
    monkeypatch.setattr(mc, "medir_par", falha)
    assert mc.main(["--fonte", "ons"]) == 2
    assert "Rode o dbt run" in capsys.readouterr().out


def test_imprimir_par_avisa_quando_os_dois_estao_no_piso(capsys):
    piso = 10 * 1024 * 1024
    raw = mc.Medida(5_000_000, 5_000_000, piso, [(0, 1.0)])
    stg = mc.Medida(3_000_000, 3_000_000, piso, [(0, 1.0)])
    assert mc.imprimir_par(mc.PARES["ccee"], raw, stg) is True
    saida = capsys.readouterr().out
    assert "-40.0%" in saida and "piso de 10 MiB" in saida and "resultados iguais: sim" in saida


@pytest.mark.parametrize("fonte", ["ons", "ccee", "inmet"])
def test_formatacao_das_consultas(fonte):
    par = mc.PARES[fonte]
    par.sql_raw.format(tabela="p.raw.t")
    par.sql_staging.format(tabela="p.staging.t")
