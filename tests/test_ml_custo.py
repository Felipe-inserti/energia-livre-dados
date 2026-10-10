"""Modelo de custo (6.1): contas à mão, bordas, propriedades e preço do contrato."""

import numpy as np
import pytest

from ml.custo import (
    custo_anual,
    custo_mensal,
    faixa,
    preco_do_contrato,
    volume_medio_mwm,
)

# Mês de 30 dias (720 h), V = 0,15 MWm, f = 10%: V_m = 108, faixa [97,2; 118,8], P = 200.
F, V, H, P = 0.10, 0.15, 720, 200.0


def um_mes(c, pld, v=V, f=F, p=P, h=H):
    r = custo_mensal(c, v, h, f, p, pld)
    return {k: float(getattr(r, k)) for k in r.__dataclass_fields__}


def test_faixa_do_mes():
    v_m, a, b = faixa(V, H, F)
    assert (float(v_m), float(a), float(b)) == pytest.approx((108.0, 97.2, 118.8))


def test_consumo_acima_da_faixa_compra_o_excedente_pelo_pld():
    # E = 118,8; custo = 118,8 × 200 + 1,2 × 300 = 23.760 + 360
    r = um_mes(120, 300)
    assert r["entregue_mwh"] == pytest.approx(118.8)
    assert r["custo"] == pytest.approx(24_120.0)
    assert r["descoberto_mwh"] == pytest.approx(1.2)
    assert r["sobrando_mwh"] == 0.0


def test_consumo_abaixo_da_faixa_vende_a_sobra_pelo_pld():
    # E = 97,2; custo = 97,2 × 200 + (90 − 97,2) × 50 = 19.440 − 360
    r = um_mes(90, 50)
    assert r["entregue_mwh"] == pytest.approx(97.2)
    assert r["custo"] == pytest.approx(19_080.0)
    assert r["sobrando_mwh"] == pytest.approx(7.2)
    assert r["descoberto_mwh"] == 0.0


def test_consumo_dentro_da_faixa_nao_tem_exposicao():
    r = um_mes(100, 123)
    assert r["custo"] == pytest.approx(20_000.0)
    assert r["descoberto_mwh"] == 0.0 and r["sobrando_mwh"] == 0.0


def test_custo_anual_soma_os_meses_a_mao():
    # os três casos acima, como três meses de 720 h: 24.120 + 19.080 + 20.000
    total = custo_anual([120, 90, 100], V, [H] * 3, F, P, [300, 50, 123])
    assert float(total) == pytest.approx(63_200.0)


@pytest.mark.parametrize("c, esperado_e", [(97.2, 97.2), (118.8, 118.8)])
def test_consumo_exatamente_na_borda_nao_tem_exposicao(c, esperado_e):
    r = um_mes(c, 999)
    assert r["entregue_mwh"] == pytest.approx(esperado_e)
    assert r["descoberto_mwh"] == pytest.approx(0.0, abs=1e-9)
    assert r["sobrando_mwh"] == pytest.approx(0.0, abs=1e-9)
    assert r["custo"] == pytest.approx(c * P)


def test_sem_flexibilidade_entrega_sempre_o_contratado():
    # f = 0: E = V_m = 108. C = 120: 108 × 200 + 12 × 300 = 25.200; C = 90: 21.600 − 18 × 50
    assert um_mes(120, 300, f=0.0)["custo"] == pytest.approx(25_200.0)
    assert um_mes(90, 50, f=0.0)["custo"] == pytest.approx(20_700.0)


def test_sem_contrato_tudo_vai_ao_pld():
    r = um_mes(100, 123, v=0.0)
    assert r["custo"] == pytest.approx(100 * 123)
    assert r["descoberto_mwh"] == pytest.approx(100.0)


def test_se_o_preco_igual_ao_pld_o_custo_nao_depende_de_v():
    c = np.array([80.0, 100.0, 140.0])
    custos = [float(custo_anual(c, v, [H] * 3, F, P, P)) for v in (0.0, 0.05, 0.15, 0.4)]
    assert custos == pytest.approx([float(c.sum() * P)] * 4)


def test_dentro_da_faixa_o_custo_nao_depende_de_v():
    # C = 100 cabe na faixa para V entre 100/(1,1 × 720) e 100/(0,9 × 720)
    custos = [um_mes(100, 300, v=v)["custo"] for v in (0.1263, 0.14, 0.15, 0.1543)]
    assert custos == pytest.approx([100 * P] * 4)


def test_identidade_custo_igual_c_pld_mais_e_vezes_diferenca_de_precos():
    rng = np.random.default_rng(0)
    c = rng.uniform(60, 160, 50)
    pld = rng.uniform(50, 500, 50)
    r = custo_mensal(c, V, H, F, P, pld)
    assert r.custo == pytest.approx(c * pld + r.entregue_mwh * (P - pld))


def test_exposicao_fecha_com_o_consumo_e_a_energia_entregue():
    rng = np.random.default_rng(1)
    c = rng.uniform(60, 160, 200)
    r = custo_mensal(c, V, H, F, P, 100.0)
    assert (c - r.entregue_mwh) == pytest.approx(r.descoberto_mwh - r.sobrando_mwh)
    assert np.all(r.descoberto_mwh * r.sobrando_mwh == 0)


def test_homogeneidade_dobrar_consumo_e_volume_dobra_o_custo():
    c, pld = np.array([120.0, 90.0, 100.0]), np.array([300.0, 50.0, 123.0])
    um = custo_anual(c, V, [H] * 3, F, P, pld)
    dois = custo_anual(2 * c, 2 * V, [H] * 3, F, P, pld)
    assert float(dois) == pytest.approx(2 * float(um))
    assert float(dois) / float(2 * c.sum()) == pytest.approx(float(um) / float(c.sum()))


def test_matriz_de_cenarios_devolve_um_custo_por_cenario():
    c = np.array([[120.0, 90.0, 100.0], [100.0, 100.0, 100.0]])
    pld = np.array([[300.0, 50.0, 123.0], [10.0, 10.0, 10.0]])
    anual = custo_anual(c, V, [H] * 3, F, P, pld)
    assert anual.shape == (2,)
    assert anual == pytest.approx([63_200.0, 60_000.0])


def test_horas_diferentes_por_mes():
    # fevereiro de ano bissexto (696 h) e março (744 h): V_m = V × horas de cada mês
    v_m, _, _ = faixa(0.15, [696, 744], F)
    assert v_m == pytest.approx([104.4, 111.6])


@pytest.mark.parametrize("f", [-0.01, 1.0, 1.5])
def test_banda_invalida(f):
    with pytest.raises(ValueError):
        custo_mensal(100, V, H, f, P, 100)


def test_entradas_invalidas():
    with pytest.raises(ValueError):
        custo_mensal(-1, V, H, F, P, 100)
    with pytest.raises(ValueError):
        custo_mensal(100, -V, H, F, P, 100)
    with pytest.raises(ValueError):
        custo_mensal(100, V, 0, F, P, 100)


def test_preco_do_contrato_e_o_pld_do_ano_anterior_mais_o_spread():
    assert preco_do_contrato(178.03) == pytest.approx(198.03)  # P_2021 (premissas, seção 4)
    assert preco_do_contrato(100.0, spread=0) == 100.0
    assert preco_do_contrato(100.0, spread=40) == 140.0
    with pytest.raises(ValueError):
        preco_do_contrato(-1.0)


def test_volume_medio_pondera_pelas_horas():
    # 100 MWh em 744 h e 80 MWh em 672 h: 180 / 1416 MWm
    assert volume_medio_mwm([100, 80], [744, 672]) == pytest.approx(180 / 1416)
    with pytest.raises(ValueError):
        volume_medio_mwm([1, 2], [744])
