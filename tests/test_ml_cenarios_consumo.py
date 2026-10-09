"""Cenários de consumo (5.6): sorteio sem vazamento, determinismo, escala e CVaR."""

import math
from datetime import date

import pytest

from ml.cenarios_consumo import (
    carga_do_cenario,
    consumo_anual_de_cada_vetor,
    consumo_mwh,
    cvar_superior,
    execucao_id,
    hash_dos_erros,
    horas_do_mes,
    linhas_de_cenarios,
    sortear,
)
from ml.intervalos import Erro, erro_de, reamostrar_origens, vetores_completos_ate
from ml.validacao import HORIZONTES, meses_entre, somar_meses


def historico(inicio=date(2010, 1, 1), fim=date(2019, 12, 1)):
    """Um erro por (origem, horizonte) com alvo em [inicio, fim]; o valor varia com o mês-alvo."""
    return [
        Erro(somar_meses(alvo, -h), h, alvo, 0.002 * (alvo.month - 6) + 0.0001 * h)
        for alvo in meses_entre(inicio, fim)
        for h in HORIZONTES
    ]


def test_sortear_usa_a_mesma_sequencia_de_reamostrar_origens_com_semente_por_origem():
    erros, t = historico(), date(2019, 12, 1)
    pares = sortear(erros, t, 50, semente=4)
    assert [v for _, v in pares] == reamostrar_origens(erros, t, 50, 4, semente_por_origem=True)
    conhecidos = vetores_completos_ate(erros, t)
    assert all(conhecidos[o] == v for o, v in pares)  # a origem informada é a do vetor


def test_sorteio_e_reprodutivel_e_n_menor_e_prefixo_do_maior():
    erros, t = historico(), date(2019, 12, 1)
    assert sortear(erros, t, 40) == sortear(erros, t, 40)
    assert sortear(erros, t, 20) == sortear(erros, t, 40)[:20]
    assert sortear(erros, t, 40, semente=1) != sortear(erros, t, 40, semente=2)


def test_sem_vazamento_erro_com_alvo_depois_da_origem_nao_muda_o_sorteio():
    t = date(2018, 12, 1)
    limpo = historico(fim=date(2019, 12, 1))
    sujo = [Erro(e.origem, e.horizonte, e.alvo, 100.0) if e.alvo > t else e for e in limpo]
    assert sortear(limpo, t, 60) == sortear(sujo, t, 60)
    # sanidade do teste: com a origem seguinte (que enxerga esses alvos) o sorteio muda
    assert sortear(limpo, date(2019, 12, 1), 60) != sortear(sujo, date(2019, 12, 1), 60)


def test_hash_dos_erros_ignora_alvos_posteriores_a_origem():
    t = date(2018, 12, 1)
    limpo = historico()
    sujo = [Erro(e.origem, e.horizonte, e.alvo, 5.0) if e.alvo > t else e for e in limpo]
    assert hash_dos_erros(limpo, t) == hash_dos_erros(sujo, t)
    assert hash_dos_erros(limpo, date(2019, 12, 1)) != hash_dos_erros(sujo, date(2019, 12, 1))


def test_vetor_da_propria_origem_reproduz_o_real_na_carga_do_cenario():
    origem = date(2022, 12, 1)
    previstos = [40_000.0 + 90.0 * h for h in HORIZONTES]
    reais = [p * (1 + 0.003 * ((-1) ** h) * h) for h, p in zip(HORIZONTES, previstos, strict=True)]
    vetor = [
        erro_de(origem, h, p, r).log_razao
        for h, p, r in zip(HORIZONTES, previstos, reais, strict=True)
    ]
    assert carga_do_cenario(previstos, vetor) == pytest.approx(reais, rel=1e-12)


def test_carga_do_cenario_exige_12_valores():
    with pytest.raises(ValueError):
        carga_do_cenario([1.0] * 11, [0.0] * 12)


def test_horas_do_mes_e_escala_do_consumo():
    assert horas_do_mes(date(2024, 2, 1)) == 696  # bissexto
    assert horas_do_mes(date(2025, 2, 1)) == 672
    assert horas_do_mes(date(2025, 1, 1)) == 744
    k = 3.2752385e-6
    # carga 40.000 MWmed em janeiro: ~97,5 MWh, na ordem dos 100 MWh/mês do caso base
    assert consumo_mwh(40_000.0, date(2025, 1, 1), k) == pytest.approx(k * 40_000 * 744)
    # k escala a curva por uma constante: dobrar k dobra o consumo e não muda a razão entre cenários
    assert consumo_mwh(40_000.0, date(2025, 1, 1), 2 * k) == pytest.approx(
        2 * consumo_mwh(40_000.0, date(2025, 1, 1), k)
    )


def test_erro_zero_devolve_o_previsto_e_consumo_anual_soma_os_12_meses():
    origem = date(2020, 12, 1)
    previstos = [40_000.0] * 12
    anual = consumo_anual_de_cada_vetor(previstos, [[0.0] * 12], origem, 1e-6)
    esperado = sum(1e-6 * 40_000.0 * horas_do_mes(somar_meses(origem, h)) for h in HORIZONTES)
    assert anual == [pytest.approx(esperado)]


def test_cvar_superior_exato_e_monotono():
    assert cvar_superior([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 0.8) == pytest.approx(9.5)  # 2 maiores
    assert cvar_superior(list(range(1, 21)), 0.95) == pytest.approx(20.0)  # 1 de 20
    # fração: 5% de 30 = 1,5 valores: 30 inteiro + metade do segundo (29) -> (30 + 0,5*29)/1,5
    assert cvar_superior(list(range(1, 31)), 0.95) == pytest.approx((30 + 0.5 * 29) / 1.5)
    assert cvar_superior([5.0] * 7, 0.95) == pytest.approx(5.0)
    assert cvar_superior(list(range(100)), 0.95) >= cvar_superior(list(range(100)), 0.5)
    with pytest.raises(ValueError):
        cvar_superior([1.0], 1.0)


def test_linhas_de_cenarios_tem_n_x_12_linhas_e_chave_unica():
    erros, t = historico(), date(2019, 12, 1)
    previstos = [40_000.0] * 12
    linhas = linhas_de_cenarios("x", t, previstos, sortear(erros, t, 7), 1e-6)
    assert len(linhas) == 7 * 12
    assert (
        len({(x["execucao_id"], x["origem"], x["cenario"], x["horizonte"]) for x in linhas}) == 84
    )
    assert {x["mes_alvo"] for x in linhas} == {somar_meses(t, h).isoformat() for h in HORIZONTES}


def test_execucao_id_depende_de_n_semente_k_e_dos_erros():
    base = execucao_id(2000, 0, 1e-6, {date(2020, 12, 1): "a"})
    assert base == execucao_id(2000, 0, 1e-6, {date(2020, 12, 1): "a"})
    assert base != execucao_id(1000, 0, 1e-6, {date(2020, 12, 1): "a"})
    assert base != execucao_id(2000, 1, 1e-6, {date(2020, 12, 1): "a"})
    assert base != execucao_id(2000, 0, 2e-6, {date(2020, 12, 1): "a"})
    assert base != execucao_id(2000, 0, 1e-6, {date(2020, 12, 1): "b"})


def test_sem_vetor_completo_recusa():
    with pytest.raises(ValueError):
        sortear([], date(2020, 12, 1), 10)
    assert math.isfinite(cvar_superior([1.0, 2.0, 3.0]))
