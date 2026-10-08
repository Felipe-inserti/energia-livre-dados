"""Candidatos da Sprint 5: sem vazamento de futuro, determinismo, calendário, choque da COVID e
critério de escolha. Séries sintéticas (nada de nuvem)."""

import math
from datetime import date

import numpy as np
import pandas as pd
import pytest

from ml import preparo
from ml.avaliar_candidatos import diferenca_contra_ingenuo, main
from ml.escolha import escolher
from ml.features import calendario, pascoa
from ml.metricas import Registro
from ml.modelos import ets, lgbm, media_de, regressao, sarima
from ml.registro import BASES, CANDIDATOS, COMBINACOES
from ml.validacao import meses_entre, somar_meses

ORIGEM = date(2018, 12, 1)
HS = [1, 6, 12]


def serie_sintetica(inicio=date(2008, 1, 1), fim=date(2019, 12, 1), semente=1):
    """Carga com tendência, sazonalidade e ruído (reprodutível)."""
    rng = np.random.default_rng(semente)
    s = {}
    for i, m in enumerate(meses_entre(inicio, fim)):
        sazonal = 1 + 0.06 * math.sin(2 * math.pi * (m.month - 3) / 12)
        s[m] = 30000 * (1.002**i) * sazonal * (1 + rng.normal(0, 0.01))
    return s


def adulterar_futuro(serie, origem):
    return {m: (v * 10 if m > origem else v) for m, v in serie.items()}


MODELOS = {
    "ets": ets,
    "sarima": sarima,
    "regressao": regressao,
    "lgbm": lgbm,
    "comb": media_de(ets, sarima, regressao),
}


@pytest.mark.parametrize("nome", list(MODELOS))
def test_o_futuro_adulterado_nao_muda_a_previsao(nome):
    """Entrega a série INTEIRA (com o futuro x10) ao modelo: a previsão tem de ser a mesma."""
    s = serie_sintetica()
    limpa = MODELOS[nome](s, ORIGEM, HS)
    suja = MODELOS[nome](adulterar_futuro(s, ORIGEM), ORIGEM, HS)
    assert limpa and limpa == pytest.approx(suja, rel=0, abs=0)


def test_o_teste_de_vazamento_pega_um_modelo_que_le_o_alvo():
    """Mutação: um 'modelo' que lê o valor do alvo tem de ser pego pela mesma checagem."""

    def trapaceiro(historico, origem, horizontes):
        return {h: historico.get(somar_meses(origem, h), 0.0) for h in horizontes}

    s = serie_sintetica()
    assert trapaceiro(s, ORIGEM, HS) != trapaceiro(adulterar_futuro(s, ORIGEM), ORIGEM, HS)


@pytest.mark.parametrize("nome", ["lgbm", "ets", "regressao"])
def test_previsao_reproduzivel(nome):
    s = serie_sintetica()
    assert MODELOS[nome](s, ORIGEM, HS) == MODELOS[nome](s, ORIGEM, HS)


@pytest.mark.parametrize("nome", list(MODELOS))
def test_previsoes_sao_positivas_e_na_escala_da_serie(nome):
    s = serie_sintetica()
    for v in MODELOS[nome](s, ORIGEM, [1, 12]).values():
        assert 0.5 * s[ORIGEM] < v < 2 * s[ORIGEM]


def test_historia_curta_levanta_erro_e_nao_inventa():
    curta = serie_sintetica(inicio=date(2017, 1, 1))  # 24 meses
    with pytest.raises(ValueError):
        ets(curta, date(2018, 12, 1), HS)


def test_o_registro_tem_a_grade_fechada():
    assert set(BASES) == {"regressao", "ets", "sarima", "lgbm"}
    assert set(COMBINACOES) == {"comb_ets_sarima", "comb_ets_sarima_regressao"}
    assert preparo.JANELA_MESES == 72  # só 72: 120 incluiria 2011-2014, sem reconstrução
    for c in COMBINACOES.values():
        assert set(c.componentes) <= set(BASES)
    assert len({c.complexidade for c in CANDIDATOS.values()}) == len(CANDIDATOS)


# ---------------------------------------------------------------- calendário


def test_pascoa_e_dias_uteis_efetivos():
    assert pascoa(2019) == date(2019, 4, 21) and pascoa(2024) == date(2024, 3, 31)
    # mar/2019: 21 dias úteis, menos segunda e terça de Carnaval (4 e 5/3)
    assert calendario(date(2019, 3, 1)) == {"ndias": 31, "uteis": 21, "uteis_efetivos": 19}
    # jun/2019: Corpus Christi em 20/6 (quinta) sai dos dias úteis efetivos
    jun = calendario(date(2019, 6, 1))
    assert jun["uteis_efetivos"] == jun["uteis"] - 1
    assert calendario(date(2019, 2, 1))["ndias"] == 28
    assert calendario(date(2020, 2, 1))["ndias"] == 29


def test_calendario_so_depende_da_data():
    import inspect

    assert list(inspect.signature(calendario).parameters) == ["mes"]


# ---------------------------------------------------------------- choque da COVID

EVENTO = (date(2014, 3, 1), date(2014, 12, 1))
CHOQUE = {4: -0.13, 5: -0.11, 6: -0.04, 7: -0.015}


def serie_com_choque():
    s = serie_sintetica(date(2008, 1, 1), date(2019, 12, 1))
    for m in list(s):
        if m.year == 2014 and m.month in CHOQUE:
            s[m] *= 1 + CHOQUE[m.month]
    return s


def test_a_regra_sinaliza_so_os_meses_que_fogem_do_normal():
    s = serie_com_choque()
    marcados = preparo.meses_de_choque(s, date(2015, 6, 1), EVENTO)
    assert date(2014, 4, 1) in marcados and date(2014, 5, 1) in marcados
    assert all(m.year == 2014 and 3 <= m.month <= 12 for m in marcados)
    assert date(2014, 10, 1) not in marcados and date(2014, 12, 1) not in marcados


def test_a_regra_nao_olha_meses_depois_da_origem():
    s = serie_com_choque()
    # origem em abr/2014: maio ainda não existe para o modelo, mesmo que a série tenha o mês
    assert preparo.meses_de_choque(s, date(2014, 4, 1), EVENTO) == [date(2014, 4, 1)]
    assert preparo.meses_de_choque(s, date(2014, 2, 1), EVENTO) == []


def test_a_imputacao_troca_so_os_sinalizados_e_nao_depende_do_futuro():
    s = serie_com_choque()
    origem = date(2015, 6, 1)
    visivel = {m: v for m, v in s.items() if m <= origem}
    saida, marcados = preparo.imputar_choque(visivel, origem, EVENTO)
    assert marcados and all(saida[m] != s[m] for m in marcados)
    assert all(saida[m] == s[m] for m in s if m <= origem and m not in marcados)
    # o valor imputado é o do ano anterior x crescimento, perto do que a série teria sem o choque
    contrafactual = serie_sintetica(date(2008, 1, 1), date(2019, 12, 1))
    for m in marcados:
        assert saida[m] == pytest.approx(contrafactual[m], rel=0.06)
    sujo = adulterar_futuro(s, origem)
    limpo = preparo.preparar(s, origem, evento=EVENTO)
    assert preparo.preparar(sujo, origem, evento=EVENTO) == limpo


def test_preparar_devolve_72_meses_terminando_na_origem():
    s = serie_sintetica()
    p = preparo.preparar(s, ORIGEM)
    assert len(p) == 72 and max(p) == ORIGEM and min(p) == somar_meses(ORIGEM, -71)


def test_janela_com_buraco_levanta_erro():
    s = serie_sintetica()
    del s[date(2017, 5, 1)]
    with pytest.raises(ValueError):
        preparo.preparar(s, ORIGEM)


# ---------------------------------------------------------------- critério de escolha


def linha(nome, mape, vies=0.0, dez=1.0, pior=5.0, dif=1.0, anos=7, compl=1):
    return {
        "candidato": nome,
        "mape_pct": mape,
        "vies_pct": vies,
        "erro_anual_dez_abs_pct": dez,
        "mape_pior_ano_pct": pior,
        "diferenca_mape_vs_ingenuo_pp": dif,
        "anos_melhores_que_ingenuo": anos,
        "complexidade": compl,
    }


def test_sem_elegivel_vence_o_ingenuo():
    ingenuo = linha("sazonal_ingenuo", 2.92, dif=0, anos=0)
    r = escolher([ingenuo, linha("ets", 2.80, dif=0.12, anos=6)])
    assert r["vencedor"] == "sazonal_ingenuo" and r["elegiveis"] == []
    r = escolher([linha("ets", 2.2, dif=0.7, anos=4)])  # bate por muito, mas só em 4 de 8 anos
    assert r["vencedor"] == "sazonal_ingenuo"


def test_o_limiar_e_estrito():
    assert escolher([linha("ets", 2.67, dif=0.25)])["vencedor"] == "sazonal_ingenuo"
    assert escolher([linha("ets", 2.67, dif=0.2501)])["vencedor"] == "ets"


def test_melhor_mape_vence_quando_nao_ha_empate():
    r = escolher([linha("ets", 2.5, dif=0.42), linha("sarima", 2.0, dif=0.92, compl=3)])
    assert r["vencedor"] == "sarima" and r["empate"] == ["sarima"]


def test_desempate_por_vies_depois_erro_anual_depois_pior_ano_depois_simplicidade():
    base = [linha("ets", 2.40, vies=-0.9, compl=2), linha("sarima", 2.30, vies=0.2, compl=3)]
    assert escolher(base)["vencedor"] == "sarima"  # menor |viés|
    iguais = [linha("ets", 2.40, dez=0.8, compl=2), linha("sarima", 2.30, dez=1.2, compl=3)]
    assert escolher(iguais)["vencedor"] == "ets"  # menor erro anual de dezembro
    pior = [linha("ets", 2.40, pior=4.0, compl=2), linha("sarima", 2.30, pior=5.0, compl=3)]
    assert escolher(pior)["vencedor"] == "ets"  # menor pior ano
    simples = [linha("ets", 2.40, compl=2), linha("regressao", 2.30, compl=1)]
    assert escolher(simples)["vencedor"] == "regressao"  # mais simples


def test_fora_do_empate_nao_entra_no_desempate():
    lento = linha("lgbm", 2.0, vies=-2.0, compl=6)
    r = escolher([lento, linha("regressao", 2.4, vies=0.0, compl=1)])
    # a regressão está 0,4 pp acima do melhor MAPE: fora do grupo de empate
    assert r["vencedor"] == "lgbm" and r["empate"] == ["lgbm"]


# ---------------------------------------------------------------- avaliação


def reg(serie, nome, o, h, prev, real):
    return Registro(serie, nome, o, h, somar_meses(o, h), prev, real)


def test_diferenca_contra_o_ingenuo():
    ing = [
        reg("s", "sazonal_ingenuo", date(2012, 1, 1), 1, 110, 100),
        reg("s", "sazonal_ingenuo", date(2013, 1, 1), 1, 120, 100),
    ]
    igual = diferenca_contra_ingenuo(ing, ing)
    assert igual["diferenca_mape_vs_ingenuo_pp"] == 0 and igual["anos_melhores_que_ingenuo"] == 0
    melhor = [
        reg("s", "x", date(2012, 1, 1), 1, 105, 100),
        reg("s", "x", date(2013, 1, 1), 1, 105, 100),
    ]
    d = diferenca_contra_ingenuo(melhor, ing)
    assert d["diferenca_mape_vs_ingenuo_pp"] == pytest.approx(10.0)  # (10+20)/2 - 5
    assert d["anos_melhores_que_ingenuo"] == 2 and d["anos"] == 2


def test_o_teste_final_exige_a_liberacao(capsys):
    assert main(["--periodo", "teste_final"]) == 2
    assert "RECUSADO" in capsys.readouterr().err


def test_o_teste_final_so_aceita_o_vencedor_pre_registrado(capsys):
    from ml.registro import CANDIDATO_DO_TESTE_FINAL, REGRA_SPRINT_6

    assert CANDIDATO_DO_TESTE_FINAL == "comb_ets_sarima_regressao"
    assert main(["--periodo", "teste_final", "--liberar-teste-final", "--candidatos", "ets"]) == 2
    assert "pré-registrado" in capsys.readouterr().err
    assert "independentemente do resultado do teste final" in REGRA_SPRINT_6


# ---------------------------------------------------------------- análise de erros e intervalos


def previsoes_sinteticas(erros_log, horizonte=1):
    """Previsões 100 com real = 100 * exp(erro_log): o quantil do erro é conhecido."""
    return pd.DataFrame(
        {
            "candidato": "x",
            "origem": pd.Timestamp("2020-01-01"),
            "horizonte": horizonte,
            "alvo": pd.Timestamp("2021-01-01"),
            "previsto_mwmed": 100.0,
            "real_mwmed": [100 * math.exp(e) for e in erros_log],
        }
    )


def test_quantis_e_cobertura_dos_intervalos():
    from ml.analise_erros import aplicar_intervalos, cobertura, quantis_do_erro

    rng = np.random.default_rng(0)
    dev = previsoes_sinteticas(rng.normal(0, 0.03, 4000))
    q = quantis_do_erro(dev, "x", por_horizonte=False)
    assert q.horizonte.iloc[0] == "todos" and q.q975.iloc[0] == pytest.approx(0.06, abs=0.006)
    teste = previsoes_sinteticas(rng.normal(0, 0.03, 4000))
    cob = cobertura(aplicar_intervalos(teste, q, "x"))
    assert cob.cobertura80_pct.iloc[0] == pytest.approx(80, abs=2.5)
    assert cob.cobertura95_pct.iloc[0] == pytest.approx(95, abs=1.5)
    # um teste deslocado para cima sai do intervalo pelo teto, não pelo piso
    alto = cobertura(aplicar_intervalos(previsoes_sinteticas(rng.normal(0.08, 0.03, 500)), q, "x"))
    assert (
        alto.cobertura95_pct.iloc[0] < 50
        and alto.acima_do_teto95.iloc[0] > alto.abaixo_do_piso95.iloc[0]
    )


def test_erros_por_origem_tem_um_vetor_de_12_por_origem():
    from ml.analise_erros import erros_por_origem

    linhas = [
        {
            "candidato": "x",
            "origem": pd.Timestamp("2020-12-01"),
            "horizonte": h,
            "erro_pct": float(h),
        }
        for h in range(1, 13)
    ] + [{"candidato": "x", "origem": pd.Timestamp("2021-01-01"), "horizonte": 1, "erro_pct": 9.0}]
    w = erros_por_origem(pd.DataFrame(linhas), "x")
    assert list(w.horizontes_completos) == [True, False]
    assert w.filter(like="erro_pct_h").shape == (2, 12)
