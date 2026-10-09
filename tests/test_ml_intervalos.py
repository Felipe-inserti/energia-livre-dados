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
    semente_da_origem,
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


# ------------------------------------------------- definição do log_razao e semente por origem


def test_log_razao_e_ln_real_sobre_previsto():
    """log_razao = ln(real / previsto): positivo quando o real passa do previsto."""
    e = erro_de(date(2020, 12, 1), 3, previsto=100.0, real=110.0)
    assert e.log_razao == pytest.approx(math.log(1.1))
    assert e.log_razao > 0
    assert erro_de(date(2020, 12, 1), 3, 110.0, 100.0).log_razao == pytest.approx(-math.log(1.1))


def test_vetor_da_propria_origem_reproduz_o_real():
    """Aplicar o vetor de erros da origem ao previsto dela (previsto × exp(e)) dá o real."""
    origem = date(2022, 12, 1)
    previstos = {h: 40_000.0 + 137.0 * h for h in HORIZONTES}
    reais = {h: previstos[h] * (1 + 0.004 * ((-1) ** h) * h) for h in HORIZONTES}
    erros = [erro_de(origem, h, previstos[h], reais[h]) for h in HORIZONTES]
    vetor = vetores_completos_ate(erros, ultimo_alvo_do_vetor(origem))[origem]
    assert len(vetor) == len(HORIZONTES)
    for h, e in zip(HORIZONTES, vetor, strict=True):
        assert previstos[h] * math.exp(e) == pytest.approx(reais[h], rel=1e-12)


def test_linha_gravada_do_erro_reproduz_o_real_e_tem_sinal_oposto_ao_erro_em_mw():
    """`linha_de_erro`: previsto × exp(log_razao) = real; erro_mwmed = previsto − real."""
    from ml.previsao import linha_de_erro

    prov = {
        "modelo_versao": "v",
        "parametros_hash": "p",
        "codigo_hash": "c",
        "commit": "x",
        "gerado_em": "2026-10-08T00:00:00+00:00",
    }
    linha = linha_de_erro(
        "teste_final", date(2021, 12, 1), 5, 45_000.0, 46_350.0, "reconstruida", prov
    )
    assert linha["previsto_mwmed"] * math.exp(linha["log_razao"]) == pytest.approx(
        linha["real_mwmed"]
    )
    assert linha["erro_mwmed"] == pytest.approx(linha["previsto_mwmed"] - linha["real_mwmed"])
    assert (
        linha["erro_mwmed"] < 0 < linha["log_razao"]
    )  # previu baixo: erro em MW negativo, log_razao positivo


def test_semente_por_origem_nao_muda_o_padrao():
    """Sem o parâmetro novo, o resultado é o do `random.Random(semente)` de antes."""
    import random

    erros = historico_de_erros()
    t = date(2019, 12, 1)
    vetores = list(vetores_completos_ate(erros, t).values())
    rng = random.Random(7)
    esperado = [list(rng.choice(vetores)) for _ in range(25)]
    assert reamostrar_origens(erros, t, 25, semente=7) == esperado
    assert reamostrar_origens(erros, t, 25, semente=7, semente_por_origem=False) == esperado


def test_semente_por_origem_difere_entre_origens_e_e_reprodutivel():
    erros = historico_de_erros()
    t1, t2 = date(2018, 12, 1), date(2019, 12, 1)
    assert semente_da_origem(0, t1) == semente_da_origem(0, t1)
    assert semente_da_origem(0, t1) != semente_da_origem(0, t2)
    assert semente_da_origem(0, t1) != semente_da_origem(1, t1)
    a = reamostrar_origens(erros, t2, 40, semente=3, semente_por_origem=True)
    assert a == reamostrar_origens(erros, t2, 40, semente=3, semente_por_origem=True)
    assert a != reamostrar_origens(erros, t2, 40, semente=3)  # não é a sequência do modo padrão
    # prefixo: n=20 é o começo de n=40 (permite comparar N=1.000 com N=2.000 sem redesenhar)
    assert reamostrar_origens(erros, t2, 20, semente=3, semente_por_origem=True) == a[:20]
