"""Otimização (6.2): grade, desempate, sintéticos, vazamento e congelamento."""

import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

from ml import otimizacao as ot
from ml.cenarios_consumo import cvar_superior, horas_do_mes
from ml.custo import custo_anual
from ml.otimizacao import (
    Dados,
    ErroDeCongelamento,
    avaliar,
    decidir,
    grade_de_r,
    limites_de_r,
    matrizes_da_origem,
    otimizar,
    pld_medio_do_ano,
)
from ml.validacao import HORIZONTES, somar_meses

F, P, N = 0.10, 200.0, 100
MESES = [somar_meses(date(2022, 12, 1), h) for h in HORIZONTES]
HORAS = [horas_do_mes(m) for m in MESES]
V_PONT = 0.14  # MWm
BASE = np.array(HORAS) * V_PONT  # consumo mensal igual à previsão, MWh


def cenarios_simetricos(baixo=0.8, alto=1.2, pld=300.0):
    """Metade dos cenários em `baixo` × previsão e metade em `alto` × previsão, nos 12 meses."""
    fator = np.where(np.arange(N) % 2 == 0, baixo, alto)[:, None]
    return fator * BASE[None, :], np.full((N, 12), pld)


# ---------------------------------------------------------------- grade


def test_limites_simetricos_e_banda_zero():
    assert limites_de_r(0.10) == pytest.approx((1 / 1.1, 1 / 0.9))
    assert limites_de_r(0.0) == (1.0, 1.0)
    assert limites_de_r(0.15, r_max=1.2)[1] == 1.2
    with pytest.raises(ValueError):
        limites_de_r(1.0)


def test_grade_contem_um_e_os_limites_com_passo_de_um_quarto_de_ponto():
    g = grade_de_r(0.10)
    r_min, r_max = limites_de_r(0.10)
    assert g[0] == pytest.approx(r_min) and g[-1] == pytest.approx(r_max)
    assert 1.0 in g
    assert np.all(np.diff(g) > 0) and len(set(g)) == len(g)
    assert np.diff(g)[1:-2].max() == pytest.approx(0.0025)
    assert 75 < len(g) < 90


def test_grade_sem_flexibilidade_tem_um_ponto():
    assert grade_de_r(0.0).tolist() == [1.0]


def test_grade_da_sensibilidade_de_r_max():
    g = grade_de_r(0.10, r_max=1.2)
    assert g[-1] == 1.2 and 1.0 in g and len(g) > len(grade_de_r(0.10))


# ---------------------------------------------------------------- sintéticos de resposta conhecida


@pytest.mark.parametrize("lam", [0.0, 0.5, 1.0])
def test_pld_acima_do_preco_leva_ao_limite_superior(lam):
    consumo, pld = cenarios_simetricos(pld=300.0)  # PLD 300 > P 200
    r = otimizar(consumo, pld, HORAS, V_PONT, F, P, lam).r
    assert r == pytest.approx(1 / (1 - F))


@pytest.mark.parametrize("lam", [0.0, 0.5, 1.0])
def test_pld_abaixo_do_preco_leva_ao_limite_inferior(lam):
    consumo, pld = cenarios_simetricos(pld=100.0)  # PLD 100 < P 200
    r = otimizar(consumo, pld, HORAS, V_PONT, F, P, lam).r
    assert r == pytest.approx(1 / (1 + F))


def test_pld_variavel_sempre_acima_do_preco_tambem_vai_ao_limite_superior():
    consumo, _ = cenarios_simetricos()
    pld = np.random.default_rng(3).uniform(250, 400, (N, 12))
    assert otimizar(consumo, pld, HORAS, V_PONT, F, P).r == pytest.approx(1 / (1 - F))


def test_j_plano_desempata_para_r_igual_a_um():
    # consumo exatamente igual à previsão: a previsão está na faixa em todo r da grade
    consumo = np.tile(BASE, (N, 1))
    for pld in (50.0, 200.0, 500.0):
        assert otimizar(consumo, np.full((N, 12), pld), HORAS, V_PONT, F, P).r == 1.0


def test_desempate_escolhe_o_ponto_mais_proximo_de_um_e_nao_o_menor():
    # C = 0,85 × previsão, PLD < P: o custo mínimo é o plano em que a faixa contém C
    # (r <= 0,85/0,9 = 0,9444); dentro dele, o ponto da grade mais próximo de 1.
    consumo = np.tile(0.85 * BASE, (N, 1))
    res = otimizar(consumo, np.full((N, 12), 100.0), HORAS, V_PONT, F, P)
    grade = grade_de_r(F)
    esperado = grade[grade <= 0.85 / 0.9 + 1e-12].max()
    assert res.r == pytest.approx(esperado)
    assert res.r > grade.min()  # não é o canto


def test_sem_flexibilidade_devolve_r_igual_a_um():
    consumo, pld = cenarios_simetricos()
    res = otimizar(consumo, pld, HORAS, V_PONT, 0.0, P)
    assert res.r == 1.0 and res.grade.tolist() == [1.0]


# ---------------------------------------------------------------- J da otimizada e força bruta


@pytest.mark.parametrize("f", [0.0, 0.05, 0.10, 0.15])
@pytest.mark.parametrize("lam", [0.0, 0.5, 1.0])
def test_j_da_otimizada_nao_supera_o_da_pontual_nos_proprios_cenarios(f, lam):
    rng = np.random.default_rng(42)
    consumo = BASE[None, :] * np.exp(rng.normal(0, 0.06, (N, 12)))
    pld = rng.uniform(40, 450, (N, 12))
    res = otimizar(consumo, pld, HORAS, V_PONT, f, P, lam)
    _, _, j_pont = avaliar(consumo, pld, HORAS, V_PONT, f, P, lam)
    assert res.j <= j_pont + 1e-9 * abs(j_pont)
    if lam == 0:  # só com λ = 0 a otimizada minimiza o próprio valor esperado
        assert res.esperado <= avaliar(consumo, pld, HORAS, V_PONT, f, P, 0)[0] + 1e-6


def test_otimo_confere_com_forca_bruta_independente():
    rng = np.random.default_rng(7)
    consumo = BASE[None, :] * np.exp(rng.normal(0, 0.08, (N, 12)))
    pld = rng.uniform(30, 500, (N, 12))
    res = otimizar(consumo, pld, HORAS, V_PONT, F, P, 0.5, 0.9)
    js = []
    for r in res.grade:
        custos = custo_anual(consumo, r * V_PONT, HORAS, F, P, pld)
        js.append(custos.mean() + 0.5 * cvar_superior(custos.tolist(), 0.9))
    assert res.j == pytest.approx(min(js))
    assert res.objetivos == pytest.approx(js)


def test_entradas_invalidas():
    consumo, pld = cenarios_simetricos()
    with pytest.raises(ValueError):
        otimizar(consumo, pld[:, :6], HORAS, V_PONT, F, P)
    with pytest.raises(ValueError):
        otimizar(consumo, pld, HORAS, 0.0, F, P)
    with pytest.raises(ValueError):
        otimizar(consumo, pld, HORAS, V_PONT, F, P, lam=-1)


# ---------------------------------------------------------------- dados sintéticos da origem


def dados_sinteticos(n=N, origens=(date(2021, 12, 1), date(2022, 12, 1))) -> Dados:
    rng = np.random.default_rng(11)
    exec_, cons, pld, prev = [], [], [], []
    for o in origens:
        meses = [somar_meses(o, h) for h in HORIZONTES]
        exec_.append(
            {
                "origem": o,
                "modelo_versao": "m",
                "n_cenarios": n,
                "semente_base": 0,
                "calibracao": "crescente",
                "n_vetores_consumo": 85,
                "erros_hash": f"e{o.year}",
                "k_consumo": 3.2752385e-6,
                "n_meses_pld": 240,
                "n_blocos_pld": 20,
                "pld_hash": f"p{o.year}",
                "pisos_hash": "pi",
                "limites_assumidos": False,
                "codigo_hash": "c",
            }
        )
        for h in HORIZONTES:
            prev.append({"origem": o, "horizonte": h, "previsto_mwmed": 45_000.0 + 100 * h})
        for s in range(n):
            f_ = np.exp(rng.normal(0, 0.05))
            for h, m in zip(HORIZONTES, meses, strict=True):
                base = 3.2752385e-6 * (45_000.0 + 100 * h) * horas_do_mes(m)
                cons.append(
                    {
                        "origem": o,
                        "cenario": s,
                        "horizonte": h,
                        "mes_alvo": m,
                        "consumo_mwh": base * f_,
                    }
                )
                for met in ("blocos", "simples"):
                    pld.append(
                        {
                            "origem": o,
                            "metodo": met,
                            "cenario": s,
                            "horizonte": h,
                            "mes_alvo": m,
                            "pld_rs_mwh": float(rng.uniform(60, 400)),
                        }
                    )
    meses_pld = [date(a, m, 1) for a in (2021, 2022) for m in range(1, 13)]
    pm = pd.DataFrame(
        {
            "mes": meses_pld,
            "horas": [horas_do_mes(m) for m in meses_pld],
            "horas_esperadas": [horas_do_mes(m) for m in meses_pld],
            "mes_completo": True,
            "pld_medio_simples_rs_mwh": [100.0 + i for i in range(24)],
            "pld_ponderado_rs_mwh": [101.0 + i for i in range(24)],
        }
    )
    return Dados(
        execucao=pd.DataFrame(exec_),
        cenario_consumo=pd.DataFrame(cons),
        cenario_pld=pd.DataFrame(pld),
        previstos=pd.DataFrame(prev),
        pld_mensal=pm,
        pld_2020=178.03,
    )


@pytest.fixture(scope="module")
def dados():
    return dados_sinteticos()


def test_preco_de_2021_usa_o_pld_de_2020_e_o_de_2023_a_media_horaria_de_2022(dados):
    assert pld_medio_do_ano(dados.pld_mensal, date(2020, 12, 1), 178.03) == 178.03
    m22 = dados.pld_mensal[dados.pld_mensal["mes"] >= date(2022, 1, 1)]
    esperado = np.average(m22["pld_medio_simples_rs_mwh"], weights=m22["horas"])
    assert pld_medio_do_ano(dados.pld_mensal, date(2022, 12, 1), 178.03) == pytest.approx(esperado)


def test_preco_exige_os_doze_meses_completos(dados):
    incompleto = dados.pld_mensal[dados.pld_mensal["mes"] != date(2022, 5, 1)]
    with pytest.raises(ValueError):
        pld_medio_do_ano(incompleto, date(2022, 12, 1), 178.03)


def test_matrizes_ordenam_e_conferem_completude(dados):
    c, p, meses = matrizes_da_origem(
        dados.cenario_consumo, dados.cenario_pld, date(2022, 12, 1), "blocos", N
    )
    assert c.shape == p.shape == (N, 12) and meses[0] == date(2023, 1, 1)
    with pytest.raises(ValueError):
        matrizes_da_origem(
            dados.cenario_consumo.iloc[:-1], dados.cenario_pld, date(2022, 12, 1), "blocos", N
        )
    errado = dados.cenario_pld.copy()
    errado.loc[errado.index[0], "mes_alvo"] = date(2030, 1, 1)
    with pytest.raises(ValueError):
        matrizes_da_origem(dados.cenario_consumo, errado, date(2021, 12, 1), "blocos", N)
    duplicado = pd.concat([dados.cenario_consumo, dados.cenario_consumo.iloc[:1]])
    with pytest.raises(ValueError):
        matrizes_da_origem(duplicado, dados.cenario_pld, date(2021, 12, 1), "blocos", N)


# ---------------------------------------------------------------- determinismo e vazamento


def resumo(d):
    o = d.otimizacao
    return (d.preco, d.v_pont_mwm, o.r, o.j, o.objetivos.tobytes())


def embaralhar(df, semente):
    return df.sample(frac=1.0, random_state=semente).reset_index(drop=True)


def test_determinismo_e_independencia_da_ordem_das_linhas(dados):
    o = date(2022, 12, 1)
    a = decidir(o, F, dados)
    assert resumo(a) == resumo(decidir(o, F, dados))
    misturado = Dados(
        execucao=dados.execucao,
        cenario_consumo=embaralhar(dados.cenario_consumo, 1),
        cenario_pld=embaralhar(dados.cenario_pld, 2),
        previstos=embaralhar(dados.previstos, 3),
        pld_mensal=embaralhar(dados.pld_mensal, 4),
        pld_2020=dados.pld_2020,
    )
    assert resumo(decidir(o, F, misturado)) == resumo(a)


def test_decisao_nao_depende_do_que_vem_depois_da_origem(dados):
    o = date(2021, 12, 1)
    base = decidir(o, F, dados)
    pm = dados.pld_mensal.copy()
    pm.loc[pm["mes"] > o, ["pld_medio_simples_rs_mwh", "pld_ponderado_rs_mwh"]] = 1e6
    outras = dados.cenario_consumo.copy()
    outras.loc[outras["origem"] != o, "consumo_mwh"] = 1e9
    outras_pld = dados.cenario_pld.copy()
    outras_pld.loc[outras_pld["origem"] != o, "pld_rs_mwh"] = 1e9
    prev = dados.previstos.copy()
    prev.loc[prev["origem"] != o, "previsto_mwmed"] = 1e9
    alterado = Dados(dados.execucao, outras, outras_pld, prev, pm, dados.pld_2020)
    assert resumo(decidir(o, F, alterado)) == resumo(base)


def test_decisao_so_com_meses_ate_a_origem_e_igual_a_com_todos(dados):
    o = date(2021, 12, 1)
    truncado = Dados(
        dados.execucao,
        dados.cenario_consumo,
        dados.cenario_pld,
        dados.previstos,
        dados.pld_mensal[dados.pld_mensal["mes"] <= o],
        dados.pld_2020,
    )
    assert resumo(decidir(o, F, truncado)) == resumo(decidir(o, F, dados))


def test_decidir_f_zero_e_sensibilidade_de_r_max(dados):
    o = date(2022, 12, 1)
    assert decidir(o, 0.0, dados).otimizacao.r == 1.0
    assert decidir(o, F, dados, r_max=1.2).otimizacao.grade[-1] == 1.2


def test_origem_fora_da_execucao_falha(dados):
    with pytest.raises(ValueError):
        decidir(date(2019, 12, 1), F, dados)


# ---------------------------------------------------------------- congelamento e disco


@pytest.fixture
def congelado(dados):
    return ot.montar_congelado(dados)


def dados_de_tamanho_congelado():
    """Dados sintéticos com as contagens do congelado: aceitos pela estrutura, N = 2.000."""
    return dados_sinteticos(
        n=ot.N_CENARIOS,
        origens=tuple(date(2020 + i, 12, 1) for i in range(5)) + (date(2026, 9, 1),),
    )


@pytest.fixture(scope="module")
def dados_grandes():
    return dados_de_tamanho_congelado()


def test_congelamento_aceita_os_mesmos_dados(dados_grandes):
    ot.verificar_congelamento(dados_grandes, ot.montar_congelado(dados_grandes))


def test_congelamento_recusa_cada_tipo_de_diferenca(dados_grandes):
    cong = ot.montar_congelado(dados_grandes)
    d = dados_grandes

    def com(execucao=None, consumo=None, pld=None):
        return Dados(
            execucao if execucao is not None else d.execucao,
            consumo if consumo is not None else d.cenario_consumo,
            pld if pld is not None else d.cenario_pld,
            d.previstos,
            d.pld_mensal,
            d.pld_2020,
        )

    ex = d.execucao.copy()
    ex.loc[0, "pld_hash"] = "outro"
    with pytest.raises(ErroDeCongelamento, match="pld_hash"):
        ot.verificar_congelamento(com(execucao=ex), cong)
    ex = d.execucao.copy()
    ex.loc[2, "erros_hash"] = "outro"
    with pytest.raises(ErroDeCongelamento, match="erros_hash"):
        ot.verificar_congelamento(com(execucao=ex), cong)
    ex = d.execucao.copy()
    ex["n_cenarios"] = 1000
    with pytest.raises(ErroDeCongelamento, match="N ou semente"):
        ot.verificar_congelamento(com(execucao=ex), cong)
    ex = d.execucao.copy()
    ex["k_consumo"] = 4e-6
    with pytest.raises(ErroDeCongelamento, match="k_consumo"):
        ot.verificar_congelamento(com(execucao=ex), cong)
    consumo = d.cenario_consumo.copy()
    consumo.loc[consumo.index[5], "consumo_mwh"] += 0.001
    with pytest.raises(ErroDeCongelamento, match="impressao_consumo"):
        ot.verificar_congelamento(com(consumo=consumo), cong)
    pld = d.cenario_pld.copy()
    pld.loc[pld.index[7], "pld_rs_mwh"] += 0.001
    with pytest.raises(ErroDeCongelamento, match="impressao_pld"):
        ot.verificar_congelamento(com(pld=pld), cong)
    with pytest.raises(ErroDeCongelamento, match="51cf99b073fe"):
        ot.verificar_congelamento(d, {**cong, "execucao_id": "outro"})
    with pytest.raises(ErroDeCongelamento, match="144.000"):
        ot.verificar_congelamento(com(consumo=d.cenario_consumo.iloc[:-1]), cong)


def test_impressao_nao_depende_da_ordem(dados):
    a = ot.impressao(dados.cenario_consumo, ["origem", "cenario", "horizonte"], "consumo_mwh")
    b = ot.impressao(
        embaralhar(dados.cenario_consumo, 9), ["origem", "cenario", "horizonte"], "consumo_mwh"
    )
    assert a == b


def test_parquet_ida_e_volta_preserva_a_decisao(dados, tmp_path):
    tabelas = {
        "execucao": dados.execucao,
        "cenario_consumo": dados.cenario_consumo,
        "cenario_pld": dados.cenario_pld,
        "previstos": dados.previstos,
        "pld_mensal": dados.pld_mensal,
        "consumo_mensal": pd.DataFrame(
            {"mes": [date(2021, 1, 1)], "consumo_mwh": [1.0], "horas": [744]}
        ),
        "pld_2020": pd.DataFrame({"pld_medio_2020": [178.03], "horas": [8784]}),
    }
    ot.salvar_dados(tabelas, tmp_path)
    lidos = ot.carregar_dados(tmp_path, so_ex_ante=True)
    assert lidos.consumo_mensal is None  # a otimização não carrega o realizado
    o = date(2022, 12, 1)
    assert resumo(decidir(o, F, lidos)) == resumo(decidir(o, F, dados))


def test_congelado_inexistente_falha(tmp_path):
    with pytest.raises(ErroDeCongelamento, match="--congelar"):
        ot.ler_congelado(tmp_path / "nao_existe.json")


# ---------------------------------------------------------------- consultas e dry-run


def test_consultas_dos_cenarios_filtram_o_execucao_id_congelado():
    sqls = ot.consultas()
    assert len(sqls) == 7
    for nome in ("execucao", "cenario_consumo", "cenario_pld"):
        assert "execucao_id = '51cf99b073fe'" in sqls[nome]
    assert all("marts." in s for s in sqls.values())


class GcpFalso:
    def __init__(self):
        self.chamadas = []

    def executar_consulta(self, cliente, sql, *, max_bytes_faturados, usar_cache, dry_run):
        from ingestion.common.gcp import ResultadoConsulta

        self.chamadas.append((sql, dry_run, max_bytes_faturados))
        return ResultadoConsulta([], 5_000_000, None, None)


def test_dry_run_so_estima_e_nao_grava(tmp_path, capsys):
    gcp = GcpFalso()
    rc = ot.ler(True, False, tmp_path / "d", tmp_path / "c.json", gcp=gcp, cliente=object())
    saida = capsys.readouterr().out
    assert rc == 0 and len(gcp.chamadas) == 7 and all(c[1] for c in gcp.chamadas)
    assert all(c[2] <= ot.TETO_BYTES for c in gcp.chamadas)
    assert "dry-run: nada lido" in saida and "piso de 10 MiB" in saida
    assert not (tmp_path / "d").exists() and not (tmp_path / "c.json").exists()


def test_leitura_real_sem_congelado_falha_antes_de_gastar_bytes(tmp_path):
    gcp = GcpFalso()
    with pytest.raises(ErroDeCongelamento):
        ot.ler(False, False, tmp_path / "d", tmp_path / "c.json", gcp=gcp, cliente=object())
    assert gcp.chamadas == []


def test_nao_congela_duas_vezes(tmp_path):
    arquivo = tmp_path / "c.json"
    arquivo.write_text(json.dumps({}))
    with pytest.raises(ErroDeCongelamento, match="já existe"):
        ot.ler(False, True, tmp_path / "d", arquivo, gcp=GcpFalso(), cliente=object())
