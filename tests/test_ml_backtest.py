"""Backtest (6.3): resultado à mão, decisão ex-ante, avaliação realizada, P_t único, travas."""

import json
from datetime import date

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from ml import backtest as bt
from ml.backtest import ErroDeTrava, executar, volumes_ex_ante
from ml.cenarios_consumo import horas_do_mes
from ml.otimizacao import Dados, ErroDeCongelamento
from ml.validacao import HORIZONTES, somar_meses

K = 1e-5  # k sintético: V_pont = K × 15.000 MWmed = 0,15 MWm
N = 4
ORIGENS = (date(2020, 12, 1), date(2021, 12, 1))


def meses_do_ano(ano):
    return [date(ano, m, 1) for m in range(1, 13)]


def taxa_realizada(ano):
    """Consumo realizado em MWm por mês: 0,15 sempre, exceto jan/2021 (0,20) e fev/2021 (0,10)."""
    t = {m: 0.15 for m in range(1, 13)}
    if ano == 2021:
        t[1], t[2] = 0.20, 0.10
    return t


def dados_sinteticos() -> Dados:
    execucao, previstos, cons, pld = [], [], [], []
    for o in ORIGENS:
        execucao.append(
            {"origem": o, "n_cenarios": N, "k_consumo": K, "semente_base": 0, "modelo_versao": "m"}
        )
        meses = [somar_meses(o, h) for h in HORIZONTES]
        for h in HORIZONTES:
            previstos.append({"origem": o, "horizonte": h, "previsto_mwmed": 15_000.0})
        for s in range(N):
            fator = 0.8 if s % 2 == 0 else 1.2  # cenários simétricos em torno da previsão
            for h, m in zip(HORIZONTES, meses, strict=True):
                cons.append(
                    {
                        "origem": o,
                        "cenario": s,
                        "horizonte": h,
                        "mes_alvo": m,
                        "consumo_mwh": fator * 0.15 * horas_do_mes(m),
                    }
                )
                for metodo in ("blocos", "simples"):
                    pld.append(
                        {
                            "origem": o,
                            "metodo": metodo,
                            "cenario": s,
                            "horizonte": h,
                            "mes_alvo": m,
                            "pld_rs_mwh": 300.0,  # acima de P_t: a otimizada vai ao limite superior
                        }
                    )
    pld_mensal, consumo_mensal = [], []
    for ano in (2020, 2021, 2022):
        for m in meses_do_ano(ano):
            h = horas_do_mes(m)
            if ano == 2020:
                c = 0.12 * h  # a ingênua de 2021 parte de 0,12 MWm
            else:
                c = taxa_realizada(ano)[m.month] * h
                pld_mensal.append(
                    {
                        "mes": m,
                        "horas": h,
                        "horas_esperadas": h,
                        "mes_completo": True,
                        "consumo_mwh": c,
                        "pld_medio_simples_rs_mwh": 100.0,  # P_2022 = 100 + 20
                        "pld_ponderado_rs_mwh": 250.0,
                    }
                )
            consumo_mensal.append({"mes": m, "consumo_mwh": c, "horas": h})
    return Dados(
        execucao=pd.DataFrame(execucao),
        cenario_consumo=pd.DataFrame(cons),
        cenario_pld=pd.DataFrame(pld),
        previstos=pd.DataFrame(previstos),
        pld_mensal=pd.DataFrame(pld_mensal),
        pld_2020=178.03,
        consumo_mensal=pd.DataFrame(consumo_mensal),
    )


@pytest.fixture(scope="module")
def dados():
    return dados_sinteticos()


@pytest.fixture(scope="module")
def res(dados):
    return executar(dados)


def custo(res, ano, estrategia):
    a = res.anual
    return float(a[(a["ano"] == ano) & (a["estrategia"] == estrategia)]["custo_rs"].iloc[0])


# ---------------------------------------------------------------- resultado calculado à mão
# V: ingênua 0,12 (consumo de 2020), pontual 0,15, otimizada 0,15/0,9 (limite superior, PLD > P_t).
# 2021, P = 198,03 e PLDp = 250: meses de 0,15 MWm (7.344 h), jan com 0,20 (744 h) e fev com
# 0,10 (672 h). 2022, P = 120: 0,15 MWm em todos os meses, dentro da faixa das três.


def test_custos_de_2021_a_mao(res):
    assert custo(res, 2021, "ingenua") == pytest.approx(270_144.22176, rel=1e-9)
    assert custo(res, 2021, "pontual") == pytest.approx(261_055.2924, rel=1e-9)
    assert custo(res, 2021, "otimizada") == pytest.approx(259_822.564, rel=1e-9)


def test_custos_de_2022_a_mao_dentro_da_faixa(res):
    for e in bt.ESTRATEGIAS:
        assert custo(res, 2022, e) == pytest.approx(157_680.0, rel=1e-9)


def test_volumes_a_mao(res):
    v = res.anual.set_index(["ano", "estrategia"])["v_mwm"]
    assert v[(2021, "ingenua")] == pytest.approx(0.12)
    assert v[(2021, "pontual")] == pytest.approx(0.15)
    assert v[(2021, "otimizada")] == pytest.approx(0.15 / 0.9)
    assert v[(2022, "ingenua")] == pytest.approx(1317.6 / 8760)  # consumo realizado de 2021
    assert v[(2022, "otimizada")] == pytest.approx(0.15 / 0.9)


def test_exposicao_de_2021_a_mao(res):
    e = res.anual.set_index(["ano", "estrategia"])
    esperado = {  # (descoberto, sobrando) em MWh
        "ingenua": (182.784, 5.376),
        "pontual": (26.04, 23.52),
        "otimizada": (12.4, 33.6),
    }
    for estrategia, (desc, sobra) in esperado.items():
        assert e.loc[(2021, estrategia), "descoberto_mwh"] == pytest.approx(desc)
        assert e.loc[(2021, estrategia), "sobrando_mwh"] == pytest.approx(sobra)
    assert e.loc[(2021, "ingenua"), "meses_fora_da_faixa"] == 12
    assert e.loc[(2021, "pontual"), "meses_fora_da_faixa"] == 2
    assert e.loc[(2021, "otimizada"), "meses_fora_da_faixa"] == 2  # a borda não conta como fora
    assert e.loc[(2021, "ingenua"), "cobertura_abaixo_de_100"]  # 1,1 × 0,12 × 8.760 < 1.317,6
    assert not e.loc[(2021, "pontual"), "cobertura_abaixo_de_100"]


def test_economia_e_decomposicao_a_mao(res):
    e = res.economia.set_index("recorte")
    a21 = e.loc["2021"]
    assert a21["valor_previsao_rs"] == pytest.approx(270_144.22176 - 261_055.2924)
    assert a21["valor_otimizacao_rs"] == pytest.approx(261_055.2924 - 259_822.564)
    assert a21["economia_total_rs"] == pytest.approx(270_144.22176 - 259_822.564)
    assert a21["economia_total_pct"] == pytest.approx(
        100 * (270_144.22176 - 259_822.564) / 270_144.22176
    )
    assert e.loc["2022", "economia_total_rs"] == pytest.approx(0.0, abs=1e-6)


def test_totais_com_e_sem_2021(res):
    e = res.economia.set_index("recorte")
    anos = e.loc[["2021", "2022"]]
    total = e.loc[bt.RECORTE_COMPLETO]
    for c in ("custo_ingenua_rs", "custo_pontual_rs", "custo_otimizada_rs", "valor_previsao_rs"):
        assert total[c] == pytest.approx(anos[c].sum())
    assert total["custo_ingenua_rs"] == pytest.approx(270_144.22176 + 157_680)
    sem = e.loc[bt.RECORTE_SEM_2021]
    assert sem["custo_ingenua_rs"] == pytest.approx(157_680)  # só 2022 neste conjunto
    assert sem["descoberto_ingenua_mwh"] == pytest.approx(0.0, abs=1e-6)
    for r in e.index:  # a decomposição fecha em todos os recortes
        assert e.loc[r, "valor_previsao_rs"] + e.loc[r, "valor_otimizacao_rs"] == pytest.approx(
            e.loc[r, "economia_total_rs"]
        )


def test_pior_ano_e_a_menor_economia_contra_a_ingenua(res):
    e = res.economia.set_index("recorte").loc[bt.RECORTE_COMPLETO]
    assert e["pior_ano_pontual"] == 2022  # 0% em 2022, contra +3,4% em 2021
    assert e["pior_economia_pontual_pct"] == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------- o mesmo P_t para as três


def test_mesmo_preco_para_as_tres_estrategias(res):
    a = res.anual
    for ano, esperado in ((2021, 198.03), (2022, 120.0)):
        precos = a[a["ano"] == ano]["preco_contrato_rs_mwh"]
        assert len(precos) == 3 and set(precos.round(9)) == {esperado}
    m = res.mensal
    assert m.groupby("ano")["preco_contrato_rs_mwh"].nunique().eq(1).all()


# ---------------------------------------------------------------- decisão só ex-ante


def mutilar_realizado(dados, ano_a_partir):
    """Troca por absurdos o consumo e o PLD realizados de `ano_a_partir` em diante."""
    cm = dados.consumo_mensal.copy()
    cm.loc[cm["mes"].map(lambda d: d.year) >= ano_a_partir, "consumo_mwh"] = 1e9
    pm = dados.pld_mensal.copy()
    ruim = pm["mes"].map(lambda d: d.year) >= ano_a_partir
    pm.loc[ruim, ["pld_medio_simples_rs_mwh", "pld_ponderado_rs_mwh", "consumo_mwh"]] = 1e9
    return Dados(
        dados.execucao,
        dados.cenario_consumo,
        dados.cenario_pld,
        dados.previstos,
        pm,
        dados.pld_2020,
        cm,
    )


@pytest.mark.parametrize("origem", ORIGENS)
def test_decisao_nao_depende_do_realizado_do_ano_decidido_nem_dos_seguintes(dados, origem):
    base, _ = volumes_ex_ante(dados, origem, 0.10)
    alterado, _ = volumes_ex_ante(mutilar_realizado(dados, origem.year + 1), origem, 0.10)
    assert alterado == base


def test_decisao_so_com_dados_truncados_na_origem_e_igual(dados):
    o = ORIGENS[1]
    truncado = Dados(
        dados.execucao,
        dados.cenario_consumo,
        dados.cenario_pld,
        dados.previstos,
        dados.pld_mensal[dados.pld_mensal["mes"] <= o],
        dados.pld_2020,
        dados.consumo_mensal[dados.consumo_mensal["mes"] <= o],
    )
    assert volumes_ex_ante(truncado, o, 0.10)[0] == volumes_ex_ante(dados, o, 0.10)[0]


def test_visao_ex_ante_nao_carrega_o_consumo_realizado(dados):
    v = bt.visao_ex_ante(dados, ORIGENS[0])
    assert v.consumo_mensal is None
    assert (v.pld_mensal["mes"] <= ORIGENS[0]).all() and v.pld_mensal.empty  # só há 2021 em diante


def test_ingenua_usa_so_o_ano_da_origem(dados):
    o = ORIGENS[1]  # decide 2022 com o consumo de 2021
    cm = dados.consumo_mensal.copy()
    cm.loc[cm["mes"].map(lambda d: d.year) != 2021, "consumo_mwh"] = 1e9
    assert bt.v_ingenua(cm, o) == pytest.approx(1317.6 / 8760)
    with pytest.raises(ValueError):
        bt.v_ingenua(cm[cm["mes"] != date(2021, 5, 1)], o)


# ---------------------------------------------------------------- avaliação só com o realizado


def test_custo_realizado_nao_depende_dos_cenarios_se_os_volumes_sao_os_mesmos(
    dados, res, monkeypatch
):
    fixos = {o: volumes_ex_ante(dados, o, 0.10) for o in ORIGENS}
    outros = Dados(
        dados.execucao,
        dados.cenario_consumo.assign(consumo_mwh=lambda d: d["consumo_mwh"] * 1.37),
        dados.cenario_pld.assign(pld_rs_mwh=123.0),
        dados.previstos,
        dados.pld_mensal,
        dados.pld_2020,
        dados.consumo_mensal,
    )
    monkeypatch.setattr(bt, "volumes_ex_ante", lambda d, o, f, **kw: fixos[o])
    r2 = executar(outros)
    assert_frame_equal(r2.mensal, res.mensal)  # tudo o que é realizado é idêntico
    colunas_realizadas = [
        "ano", "estrategia", "v_mwm", "custo_rs", "descoberto_mwh", "sobrando_mwh",
        "meses_fora_da_faixa", "consumo_anual_mwh",
    ]  # fmt: skip
    assert_frame_equal(r2.anual[colunas_realizadas], res.anual[colunas_realizadas])
    assert not np.allclose(
        r2.anual["cvar_ex_ante_rs"], res.anual["cvar_ex_ante_rs"]
    )  # só o relatório


def test_avaliacao_confere_com_o_custo_mensal_do_modelo(dados, res):
    from ml.custo import custo_mensal

    consumo, pld, horas = bt.realizado_do_ano(dados, 2021)
    direto = custo_mensal(consumo, 0.15, horas, 0.10, 198.03, pld).custo
    m = res.mensal
    sel = m[(m["ano"] == 2021) & (m["estrategia"] == "pontual")].sort_values("mes")
    assert sel["custo_rs"].to_numpy() == pytest.approx(direto)


def test_realizado_incompleto_ou_inconsistente_falha(dados):
    sem_mes = Dados(
        dados.execucao, dados.cenario_consumo, dados.cenario_pld, dados.previstos,
        dados.pld_mensal[dados.pld_mensal["mes"] != date(2021, 3, 1)], dados.pld_2020,
        dados.consumo_mensal,
    )  # fmt: skip
    with pytest.raises(ValueError):
        bt.realizado_do_ano(sem_mes, 2021)
    cm = dados.consumo_mensal.copy()
    cm.loc[cm["mes"] == date(2021, 3, 1), "consumo_mwh"] *= 1.01
    divergente = Dados(
        dados.execucao, dados.cenario_consumo, dados.cenario_pld, dados.previstos,
        dados.pld_mensal, dados.pld_2020, cm,
    )  # fmt: skip
    with pytest.raises(ValueError, match="difere"):
        bt.realizado_do_ano(divergente, 2021)


# ---------------------------------------------------------------- relatório do ex-ante


def test_metricas_ex_ante_sao_coerentes(res):
    a = res.anual
    assert (a["cvar_ex_ante_rs"] >= a["esperado_ex_ante_rs"] - 1e-9).all()
    assert a["pit_custo_realizado"].between(0, 1).all()


# ---------------------------------------------------------------- determinismo


def embaralhar(df, semente):
    return df.sample(frac=1.0, random_state=semente).reset_index(drop=True)


def test_determinismo(dados, res):
    r2 = executar(dados)
    for nome in ("mensal", "anual", "economia"):
        assert_frame_equal(getattr(r2, nome), getattr(res, nome))
    misturado = Dados(
        embaralhar(dados.execucao, 1),
        embaralhar(dados.cenario_consumo, 2),
        embaralhar(dados.cenario_pld, 3),
        embaralhar(dados.previstos, 4),
        embaralhar(dados.pld_mensal, 5),
        dados.pld_2020,
        embaralhar(dados.consumo_mensal, 6),
    )
    r3 = executar(misturado)
    for nome in ("mensal", "anual", "economia"):
        assert_frame_equal(getattr(r3, nome), getattr(res, nome))


# ---------------------------------------------------------------- travas


class GitFalso:
    def __init__(self, ancestral=True, sujo=""):
        self.ancestral, self.sujo, self.chamadas = ancestral, sujo, []

    def __call__(self, *args):
        self.chamadas.append(args)
        if args[0] == "merge-base":
            return (0 if self.ancestral else 1), ""
        if args[0] == "status":
            return 0, self.sujo
        return 0, "a" * 40


@pytest.fixture
def ambiente(tmp_path, monkeypatch, dados):
    """Caso base sobre dados sintéticos, com a leitura congelada e o cálculo observáveis."""
    chamadas = {"carregar": 0, "executar": 0}

    def carregar(*_a, **_k):
        chamadas["carregar"] += 1
        return dados

    original = bt.executar

    def executar_espiao(*a, **k):
        chamadas["executar"] += 1
        return original(*a, **k)

    monkeypatch.setattr(bt, "carregar_dados", carregar)
    monkeypatch.setattr(bt, "verificar_congelamento", lambda d, c: None)
    monkeypatch.setattr(bt, "ler_congelado", lambda *_: {})
    monkeypatch.setattr(bt, "executar", executar_espiao)
    pastas = {"resultados": tmp_path / "res", "log": tmp_path / "res" / "log.jsonl"}
    return chamadas, pastas, tmp_path


def rodar(ambiente, git=None, **kw):
    chamadas, pastas, tmp = ambiente
    agora = lambda: pd.Timestamp("2026-10-11T12:00:00Z")  # noqa: E731
    return bt.rodar_caso_base(
        git=git or GitFalso(), diretorio=tmp / "d", **pastas, agora=agora, **kw
    )


def test_trava_pre_registro_que_nao_e_ancestral_aborta_sem_calcular(ambiente):
    with pytest.raises(ErroDeTrava, match="ancestral"):
        rodar(ambiente, git=GitFalso(ancestral=False))
    assert ambiente[0] == {"carregar": 0, "executar": 0}
    assert not ambiente[1]["resultados"].exists()


def test_trava_arvore_suja_aborta_sem_calcular(ambiente):
    with pytest.raises(ErroDeTrava, match="não está limpa"):
        rodar(ambiente, git=GitFalso(sujo="?? ml/novo.py"))
    assert ambiente[0] == {"carregar": 0, "executar": 0}


def test_trava_congelamento_divergente_aborta_sem_calcular(ambiente, monkeypatch):
    def falha(*_):
        raise ErroDeCongelamento("pld_hash difere")

    monkeypatch.setattr(bt, "verificar_congelamento", falha)
    with pytest.raises(ErroDeTrava, match="congelado_6a"):
        rodar(ambiente)
    assert ambiente[0]["executar"] == 0 and not ambiente[1]["log"].exists()


def test_so_travas_nao_calcula_nem_grava(ambiente):
    assert rodar(ambiente, so_travas=True) == 0
    assert ambiente[0]["executar"] == 0
    assert not ambiente[1]["resultados"].exists()


def test_execucao_grava_tres_csv_e_uma_linha_de_log_com_a_proveniencia(ambiente):
    assert rodar(ambiente) == 0
    pastas = ambiente[1]
    nomes = sorted(p.name for p in pastas["resultados"].glob("*.csv"))
    assert nomes == [f"{bt.PREFIXO}_{k}.csv" for k in ("anual", "economia", "mensal")]
    (linha,) = bt.ler_log(pastas["log"])
    assert linha["evento"] == "caso_base" and linha["numero"] == 1 and not linha["repeticao"]
    assert linha["head"] == "a" * 40 and linha["preregistro"] == bt.PREREGISTRO
    assert linha["quando_utc"] == "2026-10-11T12:00:00Z"
    assert linha["criterios"] == bt.criterios() and linha["config_hash"] == bt.hash_dos_criterios()
    assert set(linha["saidas"]) == set(nomes)


def test_segunda_execucao_exige_repetir_e_acrescenta_sem_sobrescrever(ambiente):
    rodar(ambiente)
    pastas = ambiente[1]
    antes = pastas["log"].read_bytes()
    csv1 = {p.name: p.read_bytes() for p in pastas["resultados"].glob("*.csv")}
    with pytest.raises(ErroDeTrava, match="--repetir"):
        rodar(ambiente)
    assert pastas["log"].read_bytes() == antes  # abortou: o log não mudou
    rodar(ambiente, repetir=True)
    depois = pastas["log"].read_bytes()
    assert depois.startswith(antes) and len(depois) > len(antes)  # só acrescentou
    linhas = bt.ler_log(pastas["log"])
    assert [x["numero"] for x in linhas] == [1, 2] and linhas[1]["repeticao"]
    for nome, conteudo in csv1.items():  # as saídas da 1ª execução seguem intactas
        assert (pastas["resultados"] / nome).read_bytes() == conteudo
    assert (pastas["resultados"] / f"{bt.PREFIXO}_exec2_anual.csv").exists()


def test_saida_existente_nunca_e_sobrescrita(ambiente):
    pastas = ambiente[1]
    pastas["resultados"].mkdir(parents=True)
    alvo = pastas["resultados"] / f"{bt.PREFIXO}_mensal.csv"
    alvo.write_text("nao tocar")
    with pytest.raises(ErroDeTrava, match="não são sobrescritas"):
        rodar(ambiente)
    assert alvo.read_text() == "nao tocar" and ambiente[0]["executar"] == 0


def test_log_so_acrescenta(tmp_path):
    log = tmp_path / "l.jsonl"
    bt.acrescentar_log({"a": 1}, log)
    bt.acrescentar_log({"b": 2}, log)
    assert [json.loads(x) for x in log.read_text().splitlines()] == [{"a": 1}, {"b": 2}]


def test_cli_so_aceita_o_caso_base():
    with pytest.raises(SystemExit):
        bt.main(["caso-base", "--f", "0.2"])
    with pytest.raises(SystemExit):
        bt.main(["sensibilidade"])


def test_criterios_sao_os_congelados():
    c = bt.criterios()
    assert (c["f"], c["lambda"], c["alfa"], c["metodo_pld"], c["n_cenarios"]) == (
        0.10, 0.5, 0.95, "blocos", 2000,
    )  # fmt: skip
    assert c["spread_rs_mwh"] == 20.0 and c["execucao_id"] == "51cf99b073fe"
    assert c["anos"] == [2021, 2022, 2023, 2024, 2025]
    assert bt.PREREGISTRO == "02990fdf26529b59bd0aec5883f7ca7e9e2443d0"
