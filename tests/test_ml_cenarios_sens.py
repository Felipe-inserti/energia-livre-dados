"""Cenários novos da 6.4 (`disp125`, `disp150`, `clip`): dispersão, clip, ids, congelado, pureza."""

import random
from datetime import date

import numpy as np
import pandas as pd
import pytest
from test_ml_backtest import dados_sinteticos
from test_ml_cenarios_consumo import historico
from test_ml_cenarios_pld import LIMITES, serie_sintetica

from ml import cenarios_sens as cs
from ml.cenarios import DadosPld
from ml.cenarios_consumo import (
    consumo_mwh,
    esticar_erros,
    execucao_id,
    linhas_de_cenarios,
    sortear,
)
from ml.cenarios_pld import bootstrap, historico_ate, meses_alvo, transformar
from ml.intervalos import Erro, vetores_completos_ate
from ml.otimizacao import ErroDeCongelamento
from ml.validacao import HORIZONTES

K = 1e-5
N = 30
ORIGENS = [date(a, 12, 1) for a in range(2020, 2025)]


def erros_sinteticos():
    """Erros com viés e dispersão que variam com o mês-alvo (algum sinal em cada horizonte)."""
    rng = random.Random(7)
    return [
        Erro(e.origem, e.horizonte, e.alvo, e.log_razao + rng.gauss(0.01, 0.03))
        for e in historico(date(2010, 1, 1), date(2025, 12, 1))
    ]


def pld_sintetico():
    detectados = {a: 10.0 + (a - 2002) for a in range(2002, 2021)}
    return DadosPld(serie_sintetica(), detectados, {}, dict(LIMITES))


PREVISTOS = {o: {h: 15_000.0 + 10 * h for h in HORIZONTES} for o in ORIGENS}


@pytest.fixture(scope="module")
def erros():
    return erros_sinteticos()


@pytest.fixture(scope="module")
def conjuntos(erros):
    return {
        s: cs.gerar_conjunto(s, erros, PREVISTOS, pld_sintetico(), K, n=N, codigo_hash="x")
        for s in cs.CONJUNTOS_NOVOS
    }


# ---------------------------------------------------------------- dispersão


def test_esticar_erros_com_k_1_nao_toca_nos_valores():
    v = [[0.01 * h + 0.003 * i for h in range(12)] for i in range(9)]
    assert esticar_erros(v, 1.0) == v


def test_esticar_erros_preserva_a_media_do_horizonte_e_multiplica_o_desvio():
    rng = random.Random(1)
    v = [[rng.gauss(0.02, 0.03) for _ in range(12)] for _ in range(80)]
    a, b = np.array(v), np.array(esticar_erros(v, 1.5))
    assert np.allclose(b.mean(axis=0), a.mean(axis=0), atol=1e-12)  # o viés não muda
    assert np.allclose(b.std(axis=0), 1.5 * a.std(axis=0), rtol=1e-9)
    # o mesmo fator vale para os 12 horizontes de um vetor (a correlação entre meses é a mesma)
    assert np.allclose(b - a.mean(axis=0), 1.5 * (a - a.mean(axis=0)), atol=1e-12)


def test_esticar_erros_rejeita_dispersao_nao_positiva():
    with pytest.raises(ValueError):
        esticar_erros([[0.0] * 12], 0.0)


def test_sortear_com_dispersao_1_e_o_comportamento_anterior(erros):
    t = date(2019, 12, 1)
    assert sortear(erros, t, 40) == sortear(erros, t, 40, dispersao=1.0)


def test_dispersao_mantem_os_indices_sorteados_e_so_estica_os_vetores(erros):
    t = date(2019, 12, 1)
    base, esticado = sortear(erros, t, 60), sortear(erros, t, 60, dispersao=1.25)
    assert [o for o, _ in base] == [o for o, _ in esticado]  # mesmos vetores sorteados
    assert [v for _, v in base] != [v for _, v in esticado]
    pool = vetores_completos_ate(erros, t)
    media = np.array(list(pool.values())).mean(axis=0)
    for (_, v), (_, w) in zip(base, esticado, strict=True):
        assert np.allclose(np.array(w) - media, 1.25 * (np.array(v) - media), atol=1e-12)


def test_dispersao_nao_usa_erro_com_alvo_depois_da_origem(erros):
    t = date(2018, 12, 1)
    sujo = [Erro(e.origem, e.horizonte, e.alvo, 50.0) if e.alvo > t else e for e in erros]
    assert sortear(erros, t, 60, dispersao=1.5) == sortear(sujo, t, 60, dispersao=1.5)


# ---------------------------------------------------------------- clip


def test_transformar_clip_corta_o_nominal_sem_deslocar_o_piso():
    pisos = {a: 10.0 + (a - 2002) for a in range(2002, 2021)}
    piso, teto = LIMITES[2022]
    alvo = date(2022, 6, 1)
    origem = date(2005, 3, 1)
    assert transformar(300.0, origem, alvo, pisos, LIMITES, "clip") == 300.0
    assert transformar(300.0, origem, alvo, pisos, LIMITES) == 300.0 - pisos[2005] + piso
    assert transformar(5.0, origem, alvo, pisos, LIMITES, "clip") == piso  # abaixo do piso: piso
    assert transformar(1e6, origem, alvo, pisos, LIMITES, "clip") == teto
    with pytest.raises(ValueError):
        transformar(1.0, origem, alvo, pisos, LIMITES, "outra")


def test_bootstrap_clip_sorteia_os_mesmos_meses_e_respeita_a_faixa():
    dados = pld_sintetico()
    o = date(2022, 12, 1)
    hist, pisos = historico_ate(dados.serie, o), dados.pisos()
    for metodo in ("simples", "blocos"):
        base = bootstrap(metodo, hist, o, 40, 0, pisos, dados.limites)
        assert base == bootstrap(metodo, hist, o, 40, 0, pisos, dados.limites, "deslocamento")
        clip = bootstrap(metodo, hist, o, 40, 0, pisos, dados.limites, "clip")
        assert [[m for m, _ in c] for c in base] == [[m for m, _ in c] for c in clip]
        for c in clip:
            for (_, v), alvo in zip(c, meses_alvo(o), strict=True):
                piso, teto = dados.limites[alvo.year]
                assert piso <= v <= teto


# ---------------------------------------------------------------- id da execução


def test_extras_do_id_com_os_padroes_sao_os_do_caso_base_e_o_id_nao_muda():
    pld, pisos = {"2020-12-01": "a", "2021-12-01": "b"}, "p"
    legado = {"pld": pld, "pisos": pisos}  # a construção de `ml.cenarios.gerar`
    assert cs.extras_do_id(pld, pisos) == legado
    erros_hash = {date(2020, 12, 1): "e1", date(2021, 12, 1): "e2"}
    id_base = execucao_id(2000, 0, K, erros_hash, legado)
    assert (
        execucao_id(2000, 0, K, erros_hash, cs.extras_do_id(pld, pisos, 1.0, "deslocamento"))
        == id_base
    )
    outros = {
        execucao_id(2000, 0, K, erros_hash, cs.extras_do_id(pld, pisos, d, t))
        for d, t in ((1.25, "deslocamento"), (1.5, "deslocamento"), (1.0, "clip"))
    }
    assert len(outros | {id_base}) == 4


def test_extras_do_id_recusa_transformacao_desconhecida():
    with pytest.raises(ValueError):
        cs.extras_do_id({}, "p", 1.0, "outra")


# ---------------------------------------------------------------- os conjuntos


def test_os_tres_conjuntos_tem_ids_diferentes_e_o_formato_da_execucao(conjuntos):
    assert len({c.execucao_id for c in conjuntos.values()}) == 3
    for c in conjuntos.values():
        assert len(c.execucao) == 5 and sorted(c.execucao["origem"]) == ORIGENS
        assert len(c.cenario_consumo) == 5 * N * 12
        assert len(c.cenario_pld) == 5 * 2 * N * 12  # simples e blocos
        assert set(c.cenario_pld["metodo"]) == {"simples", "blocos"}
        assert list(c.cenario_consumo.columns) == [
            "origem", "cenario", "horizonte", "mes_alvo", "consumo_mwh",
        ]  # fmt: skip


def test_consumo_do_clip_e_o_do_caso_base_e_pld_da_dispersao_tambem(conjuntos, erros):
    ref = pd.DataFrame(
        [
            {"cenario": r["cenario"], "horizonte": r["horizonte"], "consumo_mwh": r["consumo_mwh"]}
            for o in ORIGENS
            for r in linhas_de_cenarios(
                "x", o, [PREVISTOS[o][h] for h in HORIZONTES], sortear(erros, o, N, 0), K
            )
            if o == ORIGENS[2]
        ]
    )
    c = conjuntos["clip"].cenario_consumo
    c = c[c["origem"] == ORIGENS[2]][["cenario", "horizonte", "consumo_mwh"]].reset_index(drop=True)
    pd.testing.assert_frame_equal(c, ref)
    dados = pld_sintetico()
    o = ORIGENS[2]
    ref_pld = [
        v
        for ciclo in bootstrap(
            "blocos", historico_ate(dados.serie, o), o, N, 0, dados.pisos(), dados.limites
        )
        for _, v in ciclo
    ]
    for s in ("disp125", "disp150"):
        p = conjuntos[s].cenario_pld
        p = p[(p["origem"] == o) & (p["metodo"] == "blocos")].sort_values(["cenario", "horizonte"])
        assert p["pld_rs_mwh"].tolist() == ref_pld
    p_clip = conjuntos["clip"].cenario_pld
    p_clip = p_clip[(p_clip["origem"] == o) & (p_clip["metodo"] == "blocos")]
    assert p_clip.sort_values(["cenario", "horizonte"])["pld_rs_mwh"].tolist() != ref_pld


def test_dispersao_aumenta_a_variancia_do_consumo_anual_e_mantem_a_media_quase_igual(conjuntos):
    def anual(c, o):
        x = c.cenario_consumo
        return x[x["origem"] == o].groupby("cenario")["consumo_mwh"].sum()

    o = ORIGENS[-1]
    base, d125, d150 = (
        anual(conjuntos["clip"], o),
        anual(conjuntos["disp125"], o),
        anual(conjuntos["disp150"], o),
    )
    assert base.std() < d125.std() < d150.std()
    assert d150.mean() == pytest.approx(base.mean(), rel=0.01)  # Jensen: efeito pequeno


def test_gerar_duas_vezes_da_o_mesmo_id_e_os_mesmos_dados(erros, conjuntos):
    de_novo = cs.gerar_conjunto(
        "disp125", erros, PREVISTOS, pld_sintetico(), K, n=N, codigo_hash="x"
    )
    a = conjuntos["disp125"]
    assert de_novo.execucao_id == a.execucao_id
    pd.testing.assert_frame_equal(de_novo.cenario_consumo, a.cenario_consumo)
    pd.testing.assert_frame_equal(de_novo.cenario_pld, a.cenario_pld)


def test_o_pld_nao_depende_da_ordem_em_que_os_conjuntos_sao_gerados(erros):
    a = cs.gerar_conjunto("disp150", erros, PREVISTOS, pld_sintetico(), K, n=N)
    cs.gerar_conjunto("clip", erros, PREVISTOS, pld_sintetico(), K, n=N)
    b = cs.gerar_conjunto("disp150", erros, PREVISTOS, pld_sintetico(), K, n=N)
    assert a.execucao_id == b.execucao_id


# ---------------------------------------------------------------- congelado e disco


def test_congelado_confere_e_acusa_qualquer_mudanca(conjuntos, tmp_path):
    base = dados_sinteticos()
    c = conjuntos["clip"]
    congelado = cs.montar_congelado_6b(c, base)
    cs.verificar_congelado_6b(c, base, congelado)
    alterado = c.cenario_consumo.copy()
    alterado.loc[0, "consumo_mwh"] += 1e-3
    with pytest.raises(ErroDeCongelamento, match="origens diferentes"):
        cs.verificar_congelado_6b(
            cs.Conjunto(c.sens_id, c.execucao_id, c.execucao, alterado, c.cenario_pld),
            base,
            congelado,
        )
    with pytest.raises(ErroDeCongelamento, match="outra execução"):
        cs.verificar_congelado_6b(conjuntos["disp125"], base, congelado)


def test_ida_e_volta_pelo_disco_preserva_o_congelado(conjuntos, tmp_path):
    base = dados_sinteticos()
    c = conjuntos["disp150"]
    congelado = cs.montar_congelado_6b(c, base)
    cs.salvar_conjunto(c, tmp_path)
    de_volta = cs.carregar_conjunto("disp150", tmp_path)
    assert de_volta.execucao_id == c.execucao_id
    cs.verificar_congelado_6b(de_volta, base, congelado)


def test_conferir_insumos_aborta_quando_o_insumo_difere_do_caso_base(erros):
    dados = pld_sintetico()
    insumos = cs.insumos_por_origem(erros, PREVISTOS, dados, ORIGENS)
    congelado = {
        "origens": {
            o.isoformat(): {
                "erros_hash": insumos["erros"][o],
                "pld_hash": insumos["pld"][o],
                "pisos_hash": insumos["pisos"],
            }
            for o in ORIGENS
        }
    }
    cs.conferir_insumos(insumos, congelado)
    congelado["origens"]["2022-12-01"]["pld_hash"] = "outro"
    with pytest.raises(ErroDeCongelamento, match="pareada"):
        cs.conferir_insumos(insumos, congelado)


def test_so_as_5_origens_do_backtest(conjuntos):
    assert all(
        o.month == 12 and 2020 <= o.year <= 2024 for o in conjuntos["clip"].execucao["origem"]
    )


def test_consumo_mwh_do_conjunto_usa_k_e_horas(conjuntos):
    c = conjuntos["clip"].cenario_consumo
    linha = c[(c["origem"] == ORIGENS[0]) & (c["horizonte"] == 1)].iloc[0]
    assert linha["consumo_mwh"] > 0
    assert consumo_mwh(1.0, date(2021, 1, 1), K) == pytest.approx(K * 744)


def test_pareamento_com_o_caso_base_confere_e_acusa_diferenca(erros, conjuntos, monkeypatch):
    monkeypatch.setitem(cs.CONJUNTOS_NOVOS, "base_sint", (1.0, "deslocamento"))
    base_c = cs.gerar_conjunto("base_sint", erros, PREVISTOS, pld_sintetico(), K, n=N)
    base = dados_sinteticos()
    congelado_6a = cs.montar_congelado_6b(base_c, base)
    for c in conjuntos.values():
        cs.conferir_pareamento(c, base, congelado_6a)
    mexido = conjuntos["clip"].cenario_consumo.copy()
    mexido.loc[5, "consumo_mwh"] *= 1.001
    ruim = cs.Conjunto(
        "clip", "x", conjuntos["clip"].execucao, mexido, conjuntos["clip"].cenario_pld
    )
    with pytest.raises(ErroDeCongelamento, match="consumo difere"):
        cs.conferir_pareamento(ruim, base, congelado_6a)
    pld = conjuntos["disp125"].cenario_pld.copy()
    pld.loc[3, "pld_rs_mwh"] += 1.0
    ruim = cs.Conjunto(
        "disp125", "x", conjuntos["disp125"].execucao, conjuntos["disp125"].cenario_consumo, pld
    )
    with pytest.raises(ErroDeCongelamento, match="PLD difere"):
        cs.conferir_pareamento(ruim, base, congelado_6a)
