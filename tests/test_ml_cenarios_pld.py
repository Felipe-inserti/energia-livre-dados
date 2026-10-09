"""Cenários de PLD (5.7): pisos, transformação, bootstrap, vazamento e faixa."""

import random
from datetime import UTC, date, datetime

import pytest

from ml.cenarios_pld import (
    blocos_de_12,
    bootstrap,
    historico_ate,
    limites_do_ano,
    mensal_do_semanal,
    meses_alvo,
    pld_anual,
    transformar,
)
from ml.piso_pld import completar_pisos
from ml.validacao import meses_entre

LIMITES = {a: (50.0 + a - 2021, 600.0 + 10 * (a - 2021)) for a in range(2021, 2027)}  # piso, teto


def serie_sintetica(fim=date(2024, 12, 1)):
    rng = random.Random(1)
    return {m: 20.0 + 400 * rng.random() for m in meses_entre(date(2002, 1, 1), fim)}


def pisos_sinteticos():
    p = {a: 10.0 + (a - 2002) for a in range(2002, 2021)}
    p.update({a: LIMITES[a][0] for a in LIMITES})
    return p


# ------------------------------------------------------------------ pisos


def test_completar_pisos_interpola_linear_e_usa_excecao_e_detectado():
    det = {2012: 12.0, 2016: 28.0, 2017: 30.0}
    r = completar_pisos(det, {}, range(2012, 2018))
    assert r[2012] == (12.0, "detectado")
    assert r[2013] == (16.0, "interpolado") and r[2014] == (20.0, "interpolado")
    assert r[2015] == (24.0, "interpolado")
    assert r[2016] == (28.0, "detectado")
    ex = completar_pisos(det, {2013: 99.0}, range(2012, 2018))
    assert ex[2013] == (99.0, "excecao")
    # 2014 agora interpola entre 2013 (99) e 2016 (28): 99 + (28-99)/3
    assert ex[2014][0] == pytest.approx(99.0 + (28.0 - 99.0) / 3)


def test_completar_pisos_vizinho_baixo_e_alto_e_sem_extrapolar():
    det = {2012: 12.0, 2016: 28.0}
    assert completar_pisos(det, {}, [2014], "vizinho_baixo")[2014] == (12.0, "vizinho_baixo")
    assert completar_pisos(det, {}, [2014], "vizinho_alto")[2014] == (28.0, "vizinho_alto")
    with pytest.raises(ValueError):
        completar_pisos(det, {}, [2018])  # sem ano com piso depois
    with pytest.raises(ValueError):
        completar_pisos(det, {}, [2014], "outra")


# ------------------------------------------------------------------ histórico mensal


def test_mensal_do_semanal_pondera_pelas_horas_de_cada_mes_local():
    utc = UTC
    # semana de 29/01 00:00 local a 05/02 00:00 local (UTC-3): 72 h de janeiro e 96 h de fevereiro
    semanas = [
        (datetime(2020, 1, 29, 3, tzinfo=utc), datetime(2020, 2, 5, 3, tzinfo=utc), 100.0),
        (datetime(2020, 2, 5, 3, tzinfo=utc), datetime(2020, 2, 12, 3, tzinfo=utc), 200.0),
    ]
    m = mensal_do_semanal(semanas)
    assert m[date(2020, 1, 1)] == pytest.approx(100.0)
    assert m[date(2020, 2, 1)] == pytest.approx((96 * 100 + 168 * 200) / 264)


# ------------------------------------------------------------------ transformação


def test_transformar_desloca_pelo_piso_e_limita_a_faixa_do_alvo():
    pisos, lim = pisos_sinteticos(), LIMITES
    piso23, teto23 = lim[2023]
    # no piso do ano de origem -> no piso do alvo
    assert transformar(pisos[2005], date(2005, 3, 1), date(2023, 3, 1), pisos, lim) == piso23
    # prêmio de 100 acima do piso de origem -> 100 acima do piso do alvo
    assert transformar(pisos[2005] + 100, date(2005, 3, 1), date(2023, 3, 1), pisos, lim) == (
        pytest.approx(piso23 + 100)
    )
    # prêmio gigante: limitado ao teto estrutural do alvo
    assert transformar(5000.0, date(2005, 3, 1), date(2023, 3, 1), pisos, lim) == teto23
    # valor abaixo do piso de origem (não deveria ocorrer): sobe ao piso do alvo
    assert transformar(pisos[2005] - 3, date(2005, 3, 1), date(2023, 3, 1), pisos, lim) == piso23


def test_limites_do_ano_alem_da_tabela_repete_o_ultimo_e_avisa():
    assert limites_do_ano(LIMITES, 2022) == (*LIMITES[2022], False)
    assert limites_do_ano(LIMITES, 2027) == (*LIMITES[2026], True)
    with pytest.raises(ValueError):
        limites_do_ano(LIMITES, 2019)


# ------------------------------------------------------------------ bootstrap


@pytest.mark.parametrize("metodo", ["simples", "blocos"])
def test_bootstrap_e_reprodutivel_e_n_menor_e_prefixo(metodo):
    t = date(2020, 12, 1)
    h = historico_ate(serie_sintetica(), t)
    p = pisos_sinteticos()
    a = bootstrap(metodo, h, t, 40, 3, p, LIMITES)
    assert a == bootstrap(metodo, h, t, 40, 3, p, LIMITES)
    assert bootstrap(metodo, h, t, 15, 3, p, LIMITES) == a[:15]
    assert a != bootstrap(metodo, h, t, 40, 4, p, LIMITES)


def test_simples_e_blocos_sorteiam_de_forma_diferente():
    t = date(2020, 12, 1)
    h = historico_ate(serie_sintetica(), t)
    s = bootstrap("simples", h, t, 20, 0, pisos_sinteticos(), LIMITES)
    b = bootstrap("blocos", h, t, 20, 0, pisos_sinteticos(), LIMITES)
    assert s != b


def test_sem_vazamento_alterar_o_pld_depois_de_t_nao_muda_os_cenarios():
    t = date(2020, 12, 1)
    serie = serie_sintetica()
    sujo = {m: (9999.0 if m > t else v) for m, v in serie.items()}
    p = pisos_sinteticos()
    for metodo in ("simples", "blocos"):
        limpo = bootstrap(metodo, historico_ate(serie, t), t, 60, 2, p, LIMITES)
        assert limpo == bootstrap(metodo, historico_ate(sujo, t), t, 60, 2, p, LIMITES)
    # o próprio bootstrap recusa um histórico com meses depois da origem
    with pytest.raises(ValueError):
        bootstrap("simples", serie, t, 5, 0, p, LIMITES)


@pytest.mark.parametrize("metodo", ["simples", "blocos"])
def test_todo_valor_fica_entre_o_piso_e_o_teto_estrutural_do_ano_alvo(metodo):
    p = pisos_sinteticos()
    for t in (date(2020, 12, 1), date(2022, 12, 1), date(2024, 12, 1)):
        h = historico_ate(serie_sintetica(), t)
        alvos = meses_alvo(t)
        for cenario in bootstrap(metodo, h, t, 200, 0, p, LIMITES):
            for (_, v), alvo in zip(cenario, alvos, strict=True):
                piso, teto, _ = limites_do_ano(LIMITES, alvo.year)
                assert piso <= v <= teto


def test_blocos_sao_janelas_de_12_meses_do_mesmo_mes_do_calendario():
    t = date(2020, 12, 1)
    h = historico_ate(serie_sintetica(), t)
    janelas = blocos_de_12(h, date(2021, 1, 1))
    assert len(janelas) == 19 and janelas[0][0] == date(2002, 1, 1)  # 2002 a 2020
    for cenario in bootstrap("blocos", h, t, 30, 0, pisos_sinteticos(), LIMITES):
        meses = [m for m, _ in cenario]
        assert meses in janelas
        assert [m.month for m in meses] == list(range(1, 13))  # sazonalidade preservada
    # origem fora de dezembro: janelas começam no mês seguinte à origem
    t2 = date(2024, 9, 1)
    janelas2 = blocos_de_12(historico_ate(serie_sintetica(), t2), date(2024, 10, 1))
    assert all(j[0].month == 10 for j in janelas2) and janelas2[-1][-1] <= t2


def test_blocos_preservam_a_variancia_anual_e_o_simples_a_reduz():
    """Com nível persistente por ano, o bootstrap simples subestima a variância do PLD anual."""
    rng = random.Random(7)
    serie = {}
    for ano in range(2002, 2021):
        nivel = 50 + 300 * rng.random()  # nível do ano (regime persistente)
        for m in range(1, 13):
            serie[date(ano, m, 1)] = nivel + 5 * rng.random()
    t = date(2020, 12, 1)
    h = historico_ate(serie, t)
    p = {a: 1.0 for a in range(2002, 2027)}
    lim = {a: (1.0, 10_000.0) for a in range(2021, 2027)}
    alvos = meses_alvo(t)

    def variancia(metodo):
        anuais = [
            pld_anual([v for _, v in c], alvos) for c in bootstrap(metodo, h, t, 1500, 0, p, lim)
        ]
        media = sum(anuais) / len(anuais)
        return sum((x - media) ** 2 for x in anuais) / len(anuais)

    assert variancia("blocos") > 5 * variancia("simples")


def test_pld_anual_pondera_pelas_horas():
    meses = meses_alvo(date(2020, 12, 1))  # 2021: fevereiro tem 28 dias
    valores = [100.0] * 12
    assert pld_anual(valores, meses) == pytest.approx(100.0)
    valores[1] = 200.0  # só fevereiro
    assert pld_anual(valores, meses) == pytest.approx(100 + 100 * 672 / 8760)
