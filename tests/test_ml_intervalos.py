"""Calibração dos intervalos: a regra crescente não usa erro de mês-alvo posterior à origem."""

import math
from datetime import date

import pytest

from ml.intervalos import (
    Erro,
    calibrar,
    erro_de,
    erros_conhecidos_em,
    intervalo,
    quantis_por_horizonte,
    reamostrar_origens,
    ultimo_alvo_do_vetor,
    vetores_completos_ate,
)
from ml.validacao import HORIZONTES, meses_entre, somar_meses


def historico_de_erros(inicio=date(2010, 1, 1), fim=date(2019, 12, 1), valor=0.01):
    """Um erro por (origem, horizonte) com alvo em [inicio, fim]; o valor varia com o mês-alvo."""
    erros = []
    for alvo in meses_entre(inicio, fim):
        for h in HORIZONTES:
            erros.append(
                Erro(
                    somar_meses(alvo, -h),
                    h,
                    alvo,
                    valor * (1 + (alvo.month - 6) / 12 + (alvo.year - 2010) / 5),
                )
            )
    return erros


def test_o_erro_em_log_e_o_intervalo_volta_ao_real():
    e = erro_de(date(2020, 1, 1), 3, previsto=100.0, real=110.0)
    assert e.alvo == date(2020, 4, 1) and e.log_razao == pytest.approx(math.log(1.1))
    assert intervalo(100.0, {"p975": e.log_razao})["p975"] == pytest.approx(110.0)


def test_erros_conhecidos_em_t_tem_alvo_ate_t():
    erros = historico_de_erros()
    t = date(2015, 6, 1)
    conhecidos = erros_conhecidos_em(erros, t)
    assert conhecidos and max(e.alvo for e in conhecidos) == t
    assert len(conhecidos) < len(erros)


def test_vetor_completo_so_entra_quando_o_ultimo_alvo_e_ate_t():
    erros = historico_de_erros()
    t = date(2015, 6, 1)
    vetores = vetores_completos_ate(erros, t)
    assert vetores and all(ultimo_alvo_do_vetor(o) <= t for o in vetores)
    assert max(vetores) == somar_meses(
        t, -12
    )  # a origem dez/2022 só vê vetores de origens <= dez/2021
    assert all(len(v) == 12 for v in vetores.values())


def test_calibracao_crescente_nao_vaza_o_futuro():
    """Erros com alvo depois de `t` valem 100 (absurdos): não mexem nos quantis nem nos sorteios."""
    t = date(2015, 6, 1)
    limpo = historico_de_erros()
    sujo = [Erro(e.origem, e.horizonte, e.alvo, 100.0) if e.alvo > t else e for e in limpo]
    assert calibrar(limpo, modo="crescente", origem=t) == calibrar(sujo, modo="crescente", origem=t)
    assert reamostrar_origens(limpo, t, 50, semente=3) == reamostrar_origens(sujo, t, 50, semente=3)
    # e o modo de produção, que usa tudo, ENXERGA a diferença (a checagem pega o vazamento)
    assert calibrar(limpo, modo="producao") != calibrar(sujo, modo="producao")


def test_a_crescente_so_muda_quando_um_erro_novo_fica_conhecido():
    erros = historico_de_erros()
    q1 = calibrar(erros, modo="crescente", origem=date(2015, 6, 1))
    q2 = calibrar(erros, modo="crescente", origem=date(2018, 6, 1))
    assert q1 != q2


def test_quantis_exigem_um_minimo_de_erros_por_horizonte():
    poucos = historico_de_erros(date(2019, 1, 1), date(2019, 12, 1))  # 12 erros por horizonte
    with pytest.raises(ValueError, match="mínimo"):
        quantis_por_horizonte(poucos)
    assert set(quantis_por_horizonte(poucos, minimo=10)) == set(HORIZONTES)


def test_quantis_conferem_com_numpy():
    import numpy as np

    erros = historico_de_erros()
    q = quantis_por_horizonte(erros)
    valores = [e.log_razao for e in erros if e.horizonte == 5]
    assert q[5]["p975"] == pytest.approx(np.quantile(valores, 0.975))
    assert q[5]["p10"] == pytest.approx(np.quantile(valores, 0.10))


def test_reamostragem_e_reprodutivel_e_sorteia_origens_inteiras():
    erros = historico_de_erros()
    a = reamostrar_origens(erros, date(2019, 12, 1), 20, semente=1)
    assert a == reamostrar_origens(erros, date(2019, 12, 1), 20, semente=1)
    assert a != reamostrar_origens(erros, date(2019, 12, 1), 20, semente=2)
    existentes = {tuple(v) for v in vetores_completos_ate(erros, date(2019, 12, 1)).values()}
    assert all(tuple(v) in existentes for v in a)


def test_calibrar_recusa_modo_invalido_e_crescente_sem_origem():
    erros = historico_de_erros()
    with pytest.raises(ValueError):
        calibrar(erros, modo="outro")
    with pytest.raises(ValueError):
        calibrar(erros, modo="crescente")
