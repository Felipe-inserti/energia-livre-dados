"""Detector de piso do PLD: o mínimo que se repete em blocos distintos."""

import pytest

from ml.piso_pld import detectar_piso, detectar_por_ano


def semanas(*pares):
    """[(semana, valor), ...] para as semanas dadas, cada uma com 3 patamares iguais ou não."""
    return [(s, v) for s, valores in pares for v in valores]


def test_piso_que_se_repete_em_tres_semanas_e_detectado():
    obs = semanas(
        (1, (10.0, 10.0, 10.0)), (2, (10.0, 30.0, 40.0)), (3, (10.0, 20.0, 25.0)), (4, (50, 60, 70))
    )
    r = detectar_piso(2010, obs)
    assert (r.status, r.piso, r.blocos, r.repeticoes) == ("detectado", 10.0, 3, 5)


def test_tres_patamares_iguais_da_mesma_semana_sao_um_bloco_so():
    obs = semanas((1, (10.0, 10.0, 10.0)), (2, (50, 60, 70)), (3, (80, 90, 99)))
    r = detectar_piso(2013, obs)
    assert r.repeticoes == 3 and r.blocos == 1
    assert r.status == "minimo_unico" and r.piso is None


def test_horas_seguidas_do_mesmo_dia_contam_um_bloco():
    obs = [("2021-03-01", 49.77)] * 24 + [("2021-03-02", 100.0), ("2021-03-03", 120.0)]
    assert detectar_piso(2021, obs).blocos == 1
    mais = obs + [("2021-03-04", 49.77), ("2021-03-05", 49.77)]
    assert detectar_piso(2021, mais).status == "detectado"


def test_minimo_unico_abaixo_de_um_valor_que_se_repete_vira_repetido_acima():
    """Como 2004: um valor mais baixo numa semana (piso antigo) e outro, mais alto, em várias."""
    obs = semanas((1, (17.58,) * 3)) + [(s, 18.59) for s in range(2, 40)]
    r = detectar_piso(2004, obs)
    assert r.status == "repetido_acima" and r.piso is None
    assert r.minimo == 17.58 and r.menor_repetido == 18.59


def test_tolerancia_de_meio_centavo_e_parametro_de_blocos():
    obs = [(1, 10.0), (2, 10.004), (3, 9.996)]
    assert detectar_piso(2000, obs).blocos == 3  # 10,00 / 10,00 / 10,00 depois de arredondar
    obs2 = [(1, 10.0), (2, 10.0), (3, 20.0)]
    assert detectar_piso(2000, obs2).status == "minimo_unico"
    assert detectar_piso(2000, obs2, minimo_blocos=2).status == "detectado"


def test_sem_observacoes_recusa_e_por_ano_ordena():
    with pytest.raises(ValueError):
        detectar_piso(2000, [])
    r = detectar_por_ano({2011: [(1, 5.0)], 2010: [(1, 4.0)]})
    assert [x.ano for x in r] == [2010, 2011]
