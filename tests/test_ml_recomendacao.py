"""`fct_recomendacao_contrato` (6.5): esquema, chave, P por janela, prévia e produção, carga."""

from dataclasses import replace
from datetime import UTC, date, datetime

import numpy as np
import pandas as pd
import pytest
from test_ml_backtest import dados_sinteticos

from ml import backtest as bt
from ml import recomendacao as rc
from ml import sensibilidades as sn
from ml.cenarios_consumo import horas_do_mes
from ml.otimizacao import pld_medio_do_ano
from ml.validacao import HORIZONTES, somar_meses

AGORA = datetime(2026, 10, 11, tzinfo=UTC)
PROV = {"commit": "c" * 40, "codigo_hash": "h", "gerado_em": "2026-10-11T00:00:00Z"}
CAB = {"config_hash": "0" * 16, "preregistro": sn.PREREGISTRO_6B}


@pytest.fixture(scope="module")
def dados():
    d = dados_sinteticos()
    return replace(d, execucao=d.execucao.assign(limites_assumidos=False))


@pytest.fixture(scope="module")
def saidas(dados, tmp_path_factory):
    pasta = tmp_path_factory.mktemp("res")
    base = bt.executar(dados)
    for k in sn.SAIDAS:
        getattr(base, k).to_csv(pasta / f"{bt.PREFIXO}_{k}.csv", index=False, float_format="%.6f")
    for s in sn.REGISTRO:
        res = sn.executar_sensibilidade(s, dados)
        for k in sn.SAIDAS:
            getattr(res, k).to_csv(
                pasta / f"sens_{s['sens_id']}_{k}.csv", index=False, float_format="%.6f"
            )
    return sn.ler_saidas(pasta)


@pytest.fixture(scope="module")
def backtest(saidas):
    ids = {"caso_base": sn.EXECUCAO_CONGELADA, **{i: "id" + i for i in sn.IDS}}
    cab = {k: CAB for k in ids}
    return rc.linhas_backtest(saidas, ids, cab, PROV)


# ---------------------------------------------------------------- esquema e chave


def test_esquema_e_chave():
    nomes = [n for n, _ in rc.ESQUEMA]
    assert nomes == rc.COLUNAS and len(set(nomes)) == len(nomes)
    assert set(rc.CHAVE) <= set(nomes) and rc.CHAVE == ("sens_id", "origem", "estrategia")
    assert rc.TABELA == "marts.fct_recomendacao_contrato"
    tipos = dict(rc.ESQUEMA)
    assert (
        tipos["origem"] == "DATE"
        and tipos["ano_contrato"] == "INT64"
        and tipos["limites_assumidos"] == "BOOL"
    )


def test_o_numero_esperado_de_linhas_de_backtest_e_210():
    assert rc.LINHAS_BACKTEST == 14 * 5 * 3 == 210


# ---------------------------------------------------------------- backtest


def test_backtest_tem_caso_base_e_as_13_sensibilidades(backtest):
    assert set(backtest["sens_id"]) == {"caso_base", *sn.IDS}
    assert len(backtest) == 14 * 2 * 3  # a base sintética tem 2 anos
    assert (backtest["tipo"] == "backtest").all() and not backtest.duplicated(list(rc.CHAVE)).any()
    rc.validar(backtest, com_backtest=False)


def test_backtest_origem_de_dezembro_e_janela_do_ano_calendario(backtest):
    r = backtest[(backtest["sens_id"] == "caso_base") & (backtest["ano_contrato"] == 2022)].iloc[0]
    assert r["origem"] == date(2021, 12, 1)
    assert (r["janela_inicio"], r["janela_fim"]) == (date(2022, 1, 1), date(2022, 12, 1))
    assert not r["limites_assumidos"]


def test_backtest_traz_os_parametros_de_cada_sensibilidade(backtest):
    def p(s, c):
        return backtest[backtest["sens_id"] == s][c].iloc[0]

    assert (p("caso_base", "banda_f"), p("f05", "banda_f"), p("f00", "banda_f")) == (
        0.10,
        0.05,
        0.0,
    )
    assert (p("spread40", "spread_rs_mwh"), p("spread00", "spread_rs_mwh")) == (40.0, 0.0)
    assert (p("lam10", "lambda"), p("caso_base", "lambda")) == (1.0, 0.5)
    assert (p("alfa90", "alfa"), p("caso_base", "alfa")) == (0.90, 0.95)


def test_objetivo_j_e_esperado_mais_lambda_cvar(backtest):
    j = backtest["custo_esperado_rs"] + backtest["lambda"] * backtest["cvar_rs"]
    assert np.allclose(j, backtest["objetivo_j_rs"])


def test_o_caso_base_nao_e_substituido_pela_sensibilidade(backtest):
    c = backtest[backtest["sens_id"] == "caso_base"]
    f00 = backtest[backtest["sens_id"] == "f00"]
    assert len(c) == len(f00) and c["execucao_id"].iloc[0] == sn.EXECUCAO_CONGELADA
    assert not np.allclose(c["custo_realizado_rs"], f00["custo_realizado_rs"])


def test_cabecalhos_do_log_exige_as_13_e_o_caso_base():
    base = [{"evento": "caso_base", "numero": 1, "config_hash": "b", "preregistro": "p"}]
    sens = [
        {
            "evento": "sensibilidade",
            "sens_id": s,
            "execucao_id": "i",
            "config_hash": "c",
            "preregistro": "q",
        }
        for s in sn.IDS
    ]
    ids, cab = rc.cabecalhos_do_log(sens, base)
    assert ids["caso_base"] == sn.EXECUCAO_CONGELADA and cab["f00"]["preregistro"] == "q"
    with pytest.raises(ValueError, match="o log não tem"):
        rc.cabecalhos_do_log(sens[:-1], base)


# ---------------------------------------------------------------- P e V por janela


@pytest.mark.parametrize("origem", [date(2020, 12, 1), date(2021, 12, 1)])
def test_p_da_janela_de_12_meses_e_igual_ao_do_ano_nas_origens_de_dezembro(dados, origem):
    a = rc.pld_medio_12m(dados.pld_mensal, origem, dados.pld_2020)
    assert a == pytest.approx(pld_medio_do_ano(dados.pld_mensal, origem, dados.pld_2020), rel=1e-12)


def test_v_ingenua_da_janela_e_igual_a_do_backtest_nas_origens_de_dezembro(dados):
    o = date(2021, 12, 1)
    assert rc.v_ingenua_12m(dados.consumo_mensal, o) == pytest.approx(
        bt.v_ingenua(dados.consumo_mensal, o)
    )


def test_p_da_janela_movel_usa_so_os_12_meses_ate_a_origem(dados):
    o = date(2022, 6, 1)
    esperado = dados.pld_mensal[dados.pld_mensal["mes"].between(date(2021, 7, 1), o)]
    assert len(esperado) == 12
    muda = dados.pld_mensal.copy()
    muda.loc[muda["mes"] > o, "pld_medio_simples_rs_mwh"] = 1e6  # o futuro não entra
    muda.loc[muda["mes"] < date(2021, 7, 1), "pld_medio_simples_rs_mwh"] = (
        1e6  # nem o passado velho
    )
    assert rc.pld_medio_12m(muda, o, 0.0) == pytest.approx(100.0)
    with pytest.raises(ValueError, match="não está completo"):
        rc.pld_medio_12m(dados.pld_mensal[dados.pld_mensal["mes"] != date(2022, 1, 1)], o, 0.0)


# ---------------------------------------------------------------- produção e prévia


def com_origem(dados, antiga, nova):
    """Move as linhas da origem `antiga` para `nova` (mês-alvo recalculado)."""
    meses = {h: somar_meses(nova, h) for h in HORIZONTES}
    ex = dados.execucao.assign(
        origem=lambda d: d["origem"].map(lambda o: nova if o == antiga else o)
    )

    def mover(df):
        df = df.copy()
        sel = df["origem"] == antiga
        df.loc[sel, "mes_alvo"] = df.loc[sel, "horizonte"].map(meses)
        df.loc[sel, "origem"] = nova
        return df

    return replace(
        dados,
        execucao=ex,
        cenario_consumo=mover(dados.cenario_consumo),
        cenario_pld=mover(dados.cenario_pld),
    )


PREVISTO = [15_000.0] * 12


def test_origem_de_dezembro_gera_producao_com_ano_calendario(dados):
    df = rc.linhas_producao(
        dados, date(2021, 12, 1), PREVISTO, dados.consumo_mensal, "id", CAB, PROV
    )
    assert set(df["tipo"]) == {"producao"} and set(df["ano_contrato"]) == {2022}
    assert (df["janela_inicio"].iloc[0], df["janela_fim"].iloc[0]) == (
        date(2022, 1, 1),
        date(2022, 12, 1),
    )
    assert df[list(rc.COLUNAS_REALIZADO)].isna().all().all()
    assert df["estrategia"].tolist() == list(bt.ESTRATEGIAS)
    rc.validar(df, com_backtest=False)


def test_outra_origem_gera_previa_sem_ano_e_sem_custo_realizado(dados):
    o = date(2022, 6, 1)
    movido = com_origem(dados, date(2021, 12, 1), o)
    df = rc.linhas_producao(movido, o, PREVISTO, dados.consumo_mensal, "id", CAB, PROV)
    assert set(df["tipo"]) == {"previa"} and df["ano_contrato"].isna().all()
    assert (df["janela_inicio"].iloc[0], df["janela_fim"].iloc[0]) == (
        date(2022, 7, 1),
        date(2023, 6, 1),
    )
    assert df[list(rc.COLUNAS_REALIZADO)].isna().all().all()
    assert (df["sens_id"] == "caso_base").all()
    rc.validar(df, com_backtest=False)


def test_previa_usa_p_e_ingenua_da_janela_movel(dados):
    o = date(2022, 6, 1)
    movido = com_origem(dados, date(2021, 12, 1), o)
    df = rc.linhas_producao(movido, o, PREVISTO, dados.consumo_mensal, "id", CAB, PROV).set_index(
        "estrategia"
    )
    assert df["preco_contrato_rs_mwh"].nunique() == 1
    assert df["preco_contrato_rs_mwh"].iloc[0] == pytest.approx(100.0 + 20.0)
    janela = rc.janela_de_12_meses(o)
    consumo = dados.consumo_mensal.set_index("mes").loc[janela, "consumo_mwh"].sum()
    assert df.loc["ingenua", "v_mwm"] == pytest.approx(
        consumo / sum(horas_do_mes(m) for m in janela)
    )
    assert df.loc["pontual", "razao_v_pontual"] == 1.0


def test_producao_so_com_o_caso_base_e_decisao_igual_a_do_backtest_na_origem_de_dezembro(
    dados, saidas
):
    """A mesma origem de dezembro pela rota da produção dá o V do backtest (mesmo P e grade)."""
    df = rc.linhas_producao(
        dados, date(2020, 12, 1), [15_000.0] * 12, dados.consumo_mensal, "id", CAB, PROV
    )
    a = saidas["caso_base"]["anual"]
    a = a[a["ano"] == 2021].set_index("estrategia")
    for e in ("pontual", "otimizada"):
        assert df.set_index("estrategia").loc[e, "v_mwm"] == pytest.approx(
            a.loc[e, "v_mwm"], abs=1e-6
        )


# ---------------------------------------------------------------- validação e carga


def test_validar_acusa_chave_duplicada_tipo_e_nulos_incoerentes(backtest):
    with pytest.raises(ValueError, match="duplicatas"):
        rc.validar(pd.concat([backtest, backtest.iloc[:1]]), com_backtest=False)
    with pytest.raises(ValueError, match="tipo fora"):
        rc.validar(backtest.assign(tipo="x"), com_backtest=False)
    sem_real = backtest.copy()
    sem_real.loc[sem_real.index[0], "custo_realizado_rs"] = np.nan
    with pytest.raises(ValueError, match="sem custo realizado"):
        rc.validar(sem_real, com_backtest=False)
    with pytest.raises(ValueError, match="ano_contrato"):
        rc.validar(backtest.assign(ano_contrato=np.nan), com_backtest=False)
    with pytest.raises(ValueError, match="esperadas 210"):
        rc.validar(backtest)


def test_validar_acusa_custo_realizado_na_producao(dados):
    df = rc.linhas_producao(
        dados, date(2021, 12, 1), PREVISTO, dados.consumo_mensal, "id", CAB, PROV
    )
    df.loc[0, "custo_realizado_rs"] = 1.0
    with pytest.raises(ValueError, match="fora do backtest"):
        rc.validar(df, com_backtest=False)


def test_validar_so_dezembro_gera_producao(dados):
    o = date(2022, 6, 1)
    df = rc.linhas_producao(
        com_origem(dados, date(2021, 12, 1), o), o, PREVISTO, dados.consumo_mensal, "id", CAB, PROV
    )
    with pytest.raises(ValueError):
        rc.validar(df.assign(tipo="producao", ano_contrato=2023), com_backtest=False)


def test_linhas_para_carga_tem_tipos_json(backtest, dados):
    prod = rc.linhas_producao(
        dados, date(2021, 12, 1), PREVISTO, dados.consumo_mensal, "id", CAB, PROV
    )
    df = pd.concat([backtest.iloc[:2], prod.iloc[:1]], ignore_index=True)
    regs = rc.linhas_para_carga(df)
    assert [list(r) for r in regs] == [rc.COLUNAS] * 3
    assert regs[0]["origem"] == "2020-12-01" and isinstance(regs[0]["ano_contrato"], int)
    assert isinstance(regs[0]["limites_assumidos"], bool)
    assert regs[2]["custo_realizado_rs"] is None and regs[2]["pit_custo_realizado"] is None
    assert all(r["gerado_em"] == PROV["gerado_em"] for r in regs)


def test_consulta_de_consumo_pega_os_12_meses_ate_a_origem():
    sql = rc._sql_consumo_12m(date(2026, 9, 1))
    assert "DATE '2025-10-01'" in sql and "< DATE '2026-10-01'" in sql
