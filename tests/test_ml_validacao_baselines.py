"""`ml/validacao.py` e `ml/baselines.py`: pares da origem móvel, séries utilizáveis, as 2 regras."""

from datetime import date

import pytest

from ml import baselines as b
from ml import validacao as v


def serie_sintetica(inicio=date(2000, 1, 1), fim=date(2020, 12, 1)):
    """Tendência + sazonalidade, determinística: todo mês tem um valor diferente."""
    return {
        mes: 1000 + 3 * i + 80 * ((mes.month * 7) % 12)
        for i, mes in enumerate(v.meses_entre(inicio, fim))
    }


def test_somar_meses_atravessa_o_ano_nos_dois_sentidos():
    assert v.somar_meses(date(2019, 11, 1), 1) == date(2019, 12, 1)
    assert v.somar_meses(date(2019, 12, 1), 1) == date(2020, 1, 1)
    assert v.somar_meses(date(2020, 1, 1), -1) == date(2019, 12, 1)
    assert v.somar_meses(date(2020, 3, 1), -26) == date(2018, 1, 1)
    assert v.somar_meses(date(2020, 3, 1), 0) == date(2020, 3, 1)


def test_pares_do_desenvolvimento():
    ps = v.pares(v.PERIODOS["desenvolvimento"])
    assert len(ps) == 96 * 12  # 8 anos de alvos x 12 horizontes
    assert (ps[0].origem, ps[0].horizonte) == (date(2011, 1, 1), 12)  # 1ª origem prevê jan/2012
    assert max(p.origem for p in ps) == date(2019, 11, 1)  # a última origem prevê dez/2019, h = 1
    assert all(p.alvo == v.somar_meses(p.origem, p.horizonte) for p in ps)
    assert all(date(2012, 1, 1) <= p.alvo <= date(2019, 12, 1) for p in ps)
    assert {p.origem for p in ps if p.origem.month == 12} == {
        date(y, 12, 1) for y in range(2011, 2019)
    }


def test_periodos_nao_se_sobrepoem_e_so_o_teste_final_e_protegido():
    p = v.PERIODOS
    assert p["desenvolvimento"].alvo_fim < p["estresse_2020"].alvo_inicio
    assert p["estresse_2020"].alvo_fim < p["teste_final"].alvo_inicio
    assert (p["teste_final"].alvo_inicio, p["teste_final"].alvo_fim) == (
        date(2021, 1, 1),
        date(2025, 12, 1),
    )
    assert [x.nome for x in p.values() if x.final] == ["teste_final"]


def test_serie_utilizavel_ignora_mes_nao_utilizavel_e_valor_nulo():
    linhas = [
        {"mes": date(2026, 8, 1), "x": 10.0, "mes_utilizavel": True},
        {"mes": date(2026, 9, 1), "x": 11.0, "mes_utilizavel": True},
        {"mes": date(2026, 10, 1), "x": 12.0, "mes_utilizavel": False},  # mês corrente
        {"mes": date(2017, 1, 1), "x": None, "mes_utilizavel": True},  # ajustada antes de 2018
    ]
    assert v.serie_utilizavel(linhas, "x") == {date(2026, 8, 1): 10.0, date(2026, 9, 1): 11.0}


def test_visao_na_origem_corta_o_futuro_inclusive_a_propria_origem():
    s = serie_sintetica()
    visao = v.visao_na_origem(s, date(2015, 6, 1))
    assert max(visao) == date(2015, 6, 1) and min(visao) == date(2000, 1, 1)
    assert all(visao[m] == s[m] for m in visao)


# ---------------------------------------------------------------- baselines


def test_sazonal_ingenuo_e_o_mesmo_mes_do_ano_anterior():
    s = serie_sintetica()
    origem = date(2015, 6, 1)
    hist = v.visao_na_origem(s, origem)
    for h in v.HORIZONTES:
        alvo = v.somar_meses(origem, h)
        assert b.sazonal_ingenuo(hist, origem, h) == s[v.somar_meses(alvo, -12)]
    assert b.sazonal_ingenuo(hist, origem, 12) == s[origem]  # h = 12: o próprio mês da origem


def test_sazonal_ingenuo_nao_depende_da_origem():
    s = serie_sintetica()
    alvo = date(2016, 3, 1)
    previsoes = {
        b.sazonal_ingenuo(v.visao_na_origem(s, v.somar_meses(alvo, -h)), v.somar_meses(alvo, -h), h)
        for h in v.HORIZONTES
    }
    assert previsoes == {s[date(2015, 3, 1)]}


@pytest.mark.parametrize("h", [0, 13, -1])
def test_horizonte_fora_de_1_a_12_e_recusado(h):
    # h > 12 usaria um "mesmo mês do ano anterior" posterior à origem: vazamento de futuro
    with pytest.raises(ValueError):
        b.sazonal_ingenuo({}, date(2015, 6, 1), h)
    with pytest.raises(ValueError):
        b.sazonal_crescimento({}, date(2015, 6, 1), h)


def test_sazonal_crescimento_aplica_o_crescimento_dos_ultimos_12_meses():
    origem = date(2015, 12, 1)
    # 2014 vale 100 em todos os meses, 2015 vale 110: crescimento de 12 meses = 1,10
    hist = {
        m: (100.0 if m.year == 2014 else 110.0) for m in v.meses_entre(date(2014, 1, 1), origem)
    }
    assert b.sazonal_crescimento(hist, origem, 1) == pytest.approx(
        110.0 * 1.10
    )  # alvo 2016-01, base 2015-01


def test_sem_historico_suficiente_nao_ha_previsao():
    s = serie_sintetica()
    origem = date(2015, 6, 1)
    hist = v.visao_na_origem(s, origem)
    assert b.sazonal_ingenuo({}, origem, 3) is None
    del hist[date(2014, 9, 1)]  # a base do ingênuo para o alvo de set/2015 (h = 3)
    assert b.sazonal_ingenuo(hist, origem, 3) is None
    assert b.sazonal_crescimento(hist, origem, 3) is None
    hist = v.visao_na_origem(s, origem)
    del hist[date(2014, 8, 1)]  # um mês dentro dos 24 do crescimento, mas que não é a base
    assert b.sazonal_ingenuo(hist, origem, 3) == s[date(2014, 9, 1)]  # o ingênuo não precisa dele
    assert b.sazonal_crescimento(hist, origem, 3) is None  # o crescimento exige os 24
