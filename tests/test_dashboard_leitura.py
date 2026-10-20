"""Camada de dados do dashboard (`leitura.py`, `calculos.py`, `graficos.py`), testada sobre o
PRÓPRIO snapshot versionado (`dashboard/dados/`): nada de fixture sintética, nada de BigQuery."""

import ast
import json
import re
import shutil
from pathlib import Path

import pandas as pd
import pytest

from dashboard import calculos as cal
from dashboard import graficos as gr
from dashboard import leitura as lei
from dashboard import visual as vis
from ml import sensibilidades as sn

RAIZ = Path(__file__).resolve().parents[1]
DASH = RAIZ / "dashboard"


@pytest.fixture(scope="module")
def manifesto():
    return lei.manifesto()


# ---- leitura: os arquivos e os tipos


def test_a_ordem_das_sensibilidades_e_a_do_plano():
    assert lei.ORDEM_SENSIBILIDADES == ("caso_base", *sn.IDS)


def test_cada_leitor_devolve_as_linhas_do_manifesto(manifesto):
    n = {nome: info["linhas"] for nome, info in manifesto["arquivos"].items()}
    assert len(lei.carga_mensal(so_fechados=False)) == n["carga_mensal_se.csv"] == 322
    assert len(lei.pld_mensal()) == n["pld_mensal_se.csv"]
    assert len(lei.consumo_exemplo(so_completos=False)) == n["consumo_exemplo_mensal.csv"] == 82
    assert len(lei.previsoes_teste_final()) == n["previsoes_teste_final.csv"]
    assert len(lei.mape_por_ano()) == n["mape_por_ano.csv"] and len(lei.modelos_resumo()) == 3
    assert len(lei.backtest_economia()) == n["backtest_economia.csv"] == 98
    assert len(lei.backtest_anual()) == n["backtest_anual.csv"] == 210
    assert len(lei.backtest_mensal()) == n["backtest_mensal_caso_base.csv"] == 180
    assert len(lei.sensibilidades()) == n["sens_resumo.csv"]
    assert len(lei.sensibilidades_por_ano()) == n["sens_resumo_por_ano.csv"]
    assert len(lei.banda_f()) == n["sens_banda_f.csv"]
    assert len(lei.invariancias()) == 13 and len(lei.pre_registros()) == 14
    assert len(lei.recomendacao()) == n["recomendacao.csv"] == 213
    assert len(lei.erros_producao()) == n["erros_producao.csv"] == 0
    assert len(lei.frescor()) == 5


def test_tipos_prontos_para_uso():
    c = lei.carga_mensal()
    assert str(c["mes"].dtype).startswith("datetime64") and c["mes_utilizavel"].dtype == "boolean"
    r = lei.recomendacao()
    assert r["ano_contrato"].dtype == "Int64" and str(r["origem"].dtype).startswith("datetime64")
    assert r.loc[r["tipo"] == "backtest", "ano_contrato"].notna().all()
    assert r.loc[r["tipo"] == "previa", "ano_contrato"].isna().all()


# ---- meses incompletos


def test_a_carga_so_traz_meses_fechados_e_o_corrente_existe_no_arquivo(manifesto):
    fechados, todos = lei.carga_mensal(), lei.carga_mensal(so_fechados=False)
    assert fechados["mes"].max() == pd.Timestamp(manifesto["ultimo_mes_fechado"])
    assert todos["mes"].max() == pd.Timestamp("2026-10-01") and len(todos) == len(fechados) + 1
    assert fechados["mes_utilizavel"].astype(bool).all()
    assert manifesto["meses_incompletos"]["carga_mensal_se.csv"] == ["2026-10-01"]


def test_o_consumo_so_traz_meses_completos():
    completos, todos = lei.consumo_exemplo(), lei.consumo_exemplo(so_completos=False)
    assert completos["mes"].max() == pd.Timestamp("2026-09-01") and len(completos) == 81
    assert todos["mes"].max() == pd.Timestamp("2026-10-01") and todos.iloc[-1]["horas"] == 192
    assert completos["mes_completo"].astype(bool).all()


# ---- previsão e cobertura


def test_a_previsao_de_producao_e_a_da_origem_mais_recente():
    p = lei.previsao_producao()
    assert (
        len(p) == 12
        and p["origem"].nunique() == 1
        and p["origem"].iloc[0] == pd.Timestamp("2026-09-01")
    )
    assert p["mes_alvo"].min() == pd.Timestamp("2026-10-01") and p[
        "mes_alvo"
    ].max() == pd.Timestamp("2027-09-01")
    assert (p["p025_mwmed"] < p["p10_mwmed"]).all() and (p["p90_mwmed"] < p["p975_mwmed"]).all()


def test_a_cobertura_e_a_fora_da_amostra_70_2_e_87_8():
    c = lei.cobertura()
    assert (round(c["geral"]["cobertura80_pct"], 1), round(c["geral"]["cobertura95_pct"], 1)) == (
        70.2,
        87.8,
    )
    assert c["geral"]["n"] == 654
    assert (round(c["geral"]["cobertura80_pct"], 1), round(c["geral"]["cobertura95_pct"], 1)) != (
        70.8,
        90.5,
    )
    h = c["por_horizonte"]
    assert list(h["valor"]) == list(range(1, 13))
    assert (
        round(h.iloc[0]["cobertura80_pct"], 1) == 71.7
        and round(h.iloc[-1]["cobertura80_pct"], 1) == 61.2
    )
    assert list(c["por_ano"]["valor"]) == [2021, 2022, 2023, 2024, 2025]
    assert (
        c["fonte"].endswith("cobertura_por_horizonte.csv")
        and "só no desenvolvimento" in c["descricao"]
    )
    assert "5.6" in c["referencia"]


def test_modelo_contra_baseline():
    r = lei.modelos_resumo().set_index("candidato")
    assert round(r.loc["comb_ets_sarima_regressao", "mape_pct"], 2) == 3.11
    assert round(r.loc["sazonal_ingenuo_mesmos_pares", "mape_pct"], 2) == 4.17
    m = lei.mape_por_ano()
    assert m[m["candidato"] == "comb_ets_sarima_regressao"].set_index("ano").loc[
        2023, "mape_pct"
    ] == pytest.approx(4.0756)
    assert set(lei.previsoes_teste_final()["candidato"]) == {
        "comb_ets_sarima_regressao",
        "sazonal_ingenuo_mesmos_pares",
    }


# ---- decisão


def test_o_caso_base_tem_o_total_publicado():
    r = cal.resultado(lei.backtest_economia())
    assert r["valor_otimizacao_rs"] == pytest.approx(9020.19, abs=0.01)
    assert r["valor_previsao_rs"] == pytest.approx(-330.10, abs=0.01)
    assert r["economia_total_rs"] == pytest.approx(8690.10, abs=0.01)
    assert round(r["economia_total_pct"], 2) == 0.89 and round(r["valor_otimizacao_pct"], 2) == 0.92
    sem = cal.resultado(lei.backtest_economia(), recorte=lei.RECORTE_SEM_2021)
    assert round(sem["economia_total_pct"], 2) == 1.16


def test_as_sensibilidades_vem_na_ordem_do_plano_e_a_especulativa_e_marcada():
    t = cal.tabela_sensibilidades(lei.sensibilidades())
    assert list(t["sens_id"]) == list(lei.ORDEM_SENSIBILIDADES)
    assert list(t["sens_id"][t["especulacao_excluida"]]) == ["rmax120"]
    assert t.set_index("sens_id").loc["rmax120", "valor_otimizacao_rs"] == pytest.approx(
        18459.63, abs=0.01
    )
    # nunca ordenada por economia
    assert list(t["sens_id"]) != list(
        t.sort_values("economia_total_rs", ascending=False)["sens_id"]
    )


def test_valor_por_ano_do_caso_base_e_as_marcas():
    a = cal.por_ano(lei.backtest_economia(), lei.backtest_anual())
    assert list(a["ano"]) == [2021, 2022, 2023, 2024, 2025]
    assert [round(v, 2) for v in a["valor_otimizacao_rs"]] == [
        0.0,
        5843.24,
        -116.14,
        -66.28,
        3359.38,
    ]
    assert [round(v, 4) for v in a["r_otimizada"]] == [0.9841, 0.9091, 1.1111, 1.1111, 1.1111]
    assert list(a["no_limite"]) == [False, True, True, True, True]
    assert list(a["nao_elegivel"]) == [True, True, True, False, False]
    assert list(a["cobertura_abaixo_de_100"]) == [False, True, False, False, False]
    assert a.loc[0, "rotulo"] == "2021" and a.loc[4, "rotulo"] == "2025"  # o ano é texto


def test_a_concentracao_em_2022_e_2025():
    a = cal.por_ano(lei.backtest_economia(), lei.backtest_anual())
    c = cal.concentracao(a)
    assert c["soma_destacados_rs"] == pytest.approx(9202.61968, abs=1e-6)  # exibido 9.202,62
    assert c["total_rs"] == pytest.approx(9020.19, abs=0.01)
    assert c["pct_do_total"] == pytest.approx(102.0, abs=0.05)
    assert c["soma_outros_rs"] == pytest.approx(-182.425154, abs=1e-6)  # exato; exibido −182,43
    assert (
        c["outros"][2023] + c["outros"][2024] == pytest.approx(-182.425154, abs=1e-6)
        and c["outros"][2021] == 0
    )


def test_a_tabela_da_banda_f():
    t = cal.tabela_f(lei.banda_f())
    assert list(t["f"].round(2)) == [0.0, 0.05, 0.10, 0.15]
    assert [round(v, 2) for v in t["valor_otimizacao_rs"]] == [0.0, 7469.17, 9020.19, 9704.63]
    assert [round(v, 2) for v in t["valor_previsao_rs"]] == [3740.51, 1560.57, -330.10, 0.0]
    por_ano = cal.tabela_f_por_ano(lei.banda_f())
    assert len(por_ano) == 20
    f0 = por_ano[por_ano["f"] == 0]
    # f = 0: o sinal do "valor da previsão" segue o PLD do ano (negativo só em 2022)
    assert [v > 0 for v in f0["valor_previsao_rs"]] == [True, False, False, True, True]
    assert (f0["valor_otimizacao_rs"] == 0).all()


def test_custos_por_ano():
    c = cal.custos_por_ano(lei.backtest_anual())
    assert list(c.columns) == ["ingenua", "pontual", "otimizada"] and list(c.index) == [
        2021,
        2022,
        2023,
        2024,
        2025,
    ]
    assert c.loc[2021, "ingenua"] == pytest.approx(227692.52, abs=0.01)


def test_a_previa_atual():
    p = lei.previa_atual()
    assert list(p["estrategia"]) == ["ingenua", "pontual", "otimizada"] and set(p["tipo"]) == {
        "previa"
    }
    r = cal.resumo_da_previa(p)
    assert r["origem"] == pd.Timestamp("2026-09-01")
    assert (r["janela_inicio"], r["janela_fim"]) == (
        pd.Timestamp("2026-10-01"),
        pd.Timestamp("2027-09-01"),
    )
    assert r["preco_rs_mwh"] == pytest.approx(246.89, abs=0.01) and r["limites_assumidos"] is True
    assert round(r["r"]["otimizada"], 3) == 0.929 and r["r"]["pontual"] == 1.0
    assert len(lei.previas_anteriores()) == 0
    assert "custo_realizado_rs" not in r  # a prévia não tem economia


def test_os_pre_registros():
    p = lei.pre_registros()
    assert list(p["sens_id"]) == list(lei.ORDEM_SENSIBILIDADES)
    assert p.iloc[0]["preregistro"] == "02990fdf26529b59bd0aec5883f7ca7e9e2443d0"
    assert set(p.iloc[1:]["preregistro"]) == {"4c02987d0270dd91639cdc410d801fe550710af9"}
    assert p.iloc[0]["execucao_id"] == "51cf99b073fe" and json.loads(p.iloc[0]["muda"]) == {}


def test_as_invariancias_dizem_onde_a_ingenua_e_a_pontual_nao_mudam():
    i = lei.invariancias().set_index("sens_id")
    iguais = list(
        i.index[i["ingenua_custo_igual"].astype(bool) & i["pontual_custo_igual"].astype(bool)]
    )
    assert sorted(iguais) == sorted(
        ["lam00", "lam10", "alfa90", "rmax120", "pldsimples", "disp125", "disp150", "clip"]
    )


# ---- saúde


def test_saude():
    exe, st_exe = lei.saude_execucoes()
    assert st_exe["estado"] == "disponivel" and st_exe["execucoes"] == 11 and len(exe) == 160
    testes, st = lei.saude_testes()
    assert cal.resumo_dos_testes(testes) == {"testes": 250, "pass": 249, "warn": 1, "error": 0}
    assert st["comando"] == "test" and st["selecao"] == [] and st["n_resultados"] == 250
    ultima = cal.ultima_execucao(exe)
    assert ultima["inicio_utc"].nunique() == 1 and len(ultima) > 5
    assert {"fonte", "ultimo_dado"} <= set(lei.frescor().columns)


# ---- erros de leitura


def test_falta_de_arquivo_ou_coluna_da_mensagem_clara(tmp_path):
    with pytest.raises(lei.ErroDeLeitura, match="não tem o arquivo"):
        lei.carga_mensal(tmp_path)
    with pytest.raises(lei.ErroDeLeitura, match="manifest"):
        lei.manifesto(tmp_path)
    pasta = tmp_path / "d"
    shutil.copytree(lei.DADOS, pasta)
    (pasta / "mape_por_ano.csv").write_text("candidato,ano\nx,2021\n")
    with pytest.raises(lei.ErroDeLeitura, match="faltam as colunas"):
        lei.mape_por_ano(pasta)


# ---- formatação


def test_formatacao_brasileira():
    assert cal.reais(9020.194526) == "R$ 9.020,19" and cal.reais(-330.0965) == "−R$ 330,10"
    assert (
        cal.reais(8690.098, sinal=True) == "+R$ 8.690,10"
        and cal.reais(0.0, sinal=True) == "R$ 0,00"
    )
    assert (
        cal.percentual(0.921099) == "0,92%" and cal.percentual(-0.0337, 2, sinal=True) == "−0,03%"
    )
    assert cal.numero(1234567.891, 1) == "1.234.567,9"
    assert cal.mes_por_extenso("2026-09-01") == "set/2026"


# ---- gráficos


def conjuntos(grafico) -> list[list[dict]]:
    return list(grafico.to_dict(validate=True)["datasets"].values())


def maximo(grafico, campo: str) -> str:
    valores = [
        r[campo] for ds in conjuntos(grafico) for r in ds if campo in r and r[campo] is not None
    ]
    return max(valores)


def test_os_graficos_de_decisao_sao_validos_e_so_usam_cores_da_paleta():
    anos = cal.por_ano(lei.backtest_economia(), lei.backtest_anual())
    g = gr.ganho_por_ano(anos)
    spec = json.dumps(g.to_dict(validate=True))
    assert '"zero": true' in spec  # as barras começam em zero
    assert "2.021" not in spec and "contrafactual" not in spec  # o ano é texto
    pre = lei.pre_registros()
    d3 = cal.esperado_x_contrato(
        lei.backtest_anual(), lei.pld_esperado(), pre.iloc[0]["execucao_id"]
    )
    graficos = [
        g,
        gr.preco_x_esperado(d3),
        gr.banda_linhas(cal.tabela_f(lei.banda_f())),
        gr.banda_por_ano(cal.tabela_f_por_ano(lei.banda_f())),
    ]
    for gr_ in graficos:
        cores = set(re.findall(r'"#[0-9a-fA-F]{6}"', json.dumps(gr_.to_dict(validate=True))))
        assert {c.strip('"') for c in cores} <= vis.PALETA, cores


def test_nenhum_grafico_de_serie_mostra_o_mes_incompleto():
    assert maximo(gr.carga(lei.carga_mensal()), "mes").startswith("2026-09-01")
    assert maximo(gr.consumo(lei.consumo_exemplo()), "mes").startswith("2026-09-01")
    assert maximo(gr.pld(lei.pld_mensal()), "mes").startswith("2026-09-01")
    # sem o filtro (so_fechados=False) outubro apareceria: quem protege é a camada de dados
    assert maximo(gr.carga(lei.carga_mensal(so_fechados=False)), "mes").startswith("2026-10-01")
    cortado = cal.ate_o_mes(lei.carga_mensal(so_fechados=False), pd.Timestamp("2026-09-01"))
    assert maximo(gr.carga(cortado), "mes").startswith("2026-09-01")


def test_graficos_de_previsao_e_saude_sao_validos():
    gr.real_x_previsto(cal.previsto_de_dezembro(lei.previsoes_teste_final())).to_dict(validate=True)
    gr.erro_por_ano(cal.mape_por_ano_longo(lei.mape_por_ano())).to_dict(validate=True)
    gr.cobertura_por_horizonte(lei.cobertura()["por_horizonte"]).to_dict(validate=True)
    historia = cal.historia_recente(cal.ate_o_mes(lei.carga_mensal(), pd.Timestamp("2026-09-01")))
    g = gr.previsao_producao(lei.previsao_producao(), historia)
    assert maximo(g, "mes").startswith("2026-09-01") and len(historia) == 36
    exe, _ = lei.saude_execucoes()
    gr.duracao_das_tasks(cal.ultima_execucao(exe)).to_dict(validate=True)


# ---- higiene: só o snapshot, sem nuvem


MODULOS_DO_APP = ("leitura.py", "calculos.py", "graficos.py")


@pytest.mark.parametrize("nome", MODULOS_DO_APP)
def test_a_camada_de_dados_nao_importa_nuvem_nem_o_resto_do_projeto(nome):
    arvore = ast.parse((DASH / nome).read_text())
    importados = set()
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            importados |= {a.name.split(".")[0] for a in no.names}
        elif isinstance(no, ast.ImportFrom) and no.module:
            importados.add(no.module.split(".")[0])
    assert not importados & {"google", "ml", "ingestion", "dbt", "scripts"}, (nome, importados)
    assert "snapshot" not in {
        m
        for no in ast.walk(arvore)
        if isinstance(no, ast.ImportFrom)
        for m in [no.module or "", *[a.name for a in no.names]]
    }


@pytest.mark.parametrize("nome", MODULOS_DO_APP)
def test_nenhum_modulo_le_fora_de_dashboard_dados(nome):
    arvore = ast.parse((DASH / nome).read_text())
    docstrings = {
        id(n.body[0].value)
        for n in ast.walk(arvore)
        if isinstance(n, ast.Module | ast.FunctionDef | ast.ClassDef)
        and n.body
        and isinstance(n.body[0], ast.Expr)
        and isinstance(getattr(n.body[0], "value", None), ast.Constant)
    }
    for no in ast.walk(arvore):
        if isinstance(no, ast.Constant) and isinstance(no.value, str) and id(no) not in docstrings:
            assert "docs/" not in no.value and "resultados" not in no.value, (nome, no.value)


# ---- PLD esperado dos cenários contra o contrato


def test_a_frase_da_previa_compara_o_pld_esperado_com_o_contrato():
    menos = cal.leitura_da_regra(246.89, 188.58, 0.929)
    assert menos["sentido"] == "menos"
    assert menos["texto"] == (
        "PLD esperado R$ 188,58/MWh contra contrato de R$ 246,89/MWh "
        "→ contrata menos que a previsão (0,929× a previsão)"
    )
    assert menos["diferenca_rs_mwh"] == pytest.approx(58.31)
    mais = cal.leitura_da_regra(79.05, 208.03, 1.1111)
    assert mais["sentido"] == "mais" and "contrata mais que a previsão" in mais["texto"]
    assert cal.leitura_da_regra(100.0, 100.0, 1.0)["sentido"] == "igual"


def test_a_frase_nao_afirma_o_que_o_sinal_nao_explica():
    # contrato acima do esperado, mas r acima de 1: o sinal não explica; nada de "contrata menos"
    f = cal.leitura_da_regra(250.0, 190.0, 1.05)
    assert f["sentido"] == "indefinido" and "contrata menos" not in f["texto"]
    assert "o sinal da diferença não explica o volume" in f["texto"]


PUBLICADO_DECISOES = {
    2021: (198.03, 179.14),
    2022: (300.50, 195.28),
    2023: (79.05, 208.03),
    2024: (92.16, 190.76),
    2025: (148.16, 182.55),
}  # (P_t, PLD médio dos cenários em blocos), docs/decisoes.md


def _esperado_real():
    if not (lei.DADOS / "pld_esperado_cenarios.csv").exists():
        pytest.skip("regerar o snapshot (pld_esperado_cenarios.csv ainda não existe)")
    return lei.pld_esperado()


def test_o_pld_esperado_do_snapshot_bate_com_o_publicado_nas_decisoes():
    """`docs/decisoes.md` (ex-ante da 6.2): `P_t` e a média do PLD dos cenários (blocos)."""
    tabela = cal.esperado_x_contrato(lei.backtest_anual(), _esperado_real(), "51cf99b073fe")
    assert list(tabela["ano"]) == [2021, 2022, 2023, 2024, 2025]
    for _, linha in tabela.iterrows():
        p, e = PUBLICADO_DECISOES[int(linha["ano"])]
        assert linha["preco_contrato_rs_mwh"] == pytest.approx(p, abs=0.01)
        assert linha["pld_esperado_rs_mwh"] == pytest.approx(e, abs=0.01), linha["ano"]
    # o sentido do r* acompanha o sinal de P − E[PLD] nos 4 anos no limite (reversão à média)
    no_limite = tabela[tabela["ano"] != 2021]
    assert list(no_limite["contrato_menos_esperado"] > 0) == list(no_limite["r_otimizada"] < 1)


def test_a_previa_do_snapshot_diz_menos_que_a_previsao():
    esperado = _esperado_real()
    r = cal.resumo_da_previa(lei.previa_atual())
    e = cal.pld_esperado_da_origem(esperado, r["execucao_id"], r["origem"])
    frase = cal.leitura_da_regra(r["preco_rs_mwh"], e, r["r"]["otimizada"])
    assert frase["sentido"] == "menos" and e < r["preco_rs_mwh"]
    assert 180 < e < 195  # ~R$ 188,5 (média dos cenários de 2026-09 ponderada pelas horas)
    # as origens de backtest e a prévia vêm da mesma consulta
    assert set(esperado[esperado["metodo"] == "blocos"]["origem"].dt.strftime("%Y-%m")) >= {
        "2020-12",
        "2024-12",
        "2026-09",
    }


def test_pld_esperado_ausente_para_a_origem_da_erro():
    import pandas as pd

    vazio = pd.DataFrame(
        {
            "execucao_id": ["x"],
            "origem": [pd.Timestamp("2026-09-01")],
            "metodo": ["blocos"],
            "pld_esperado_rs_mwh": [1.0],
            "n_cenarios": [2000],
        }
    )
    with pytest.raises(ValueError, match="esperava 1 PLD esperado"):
        cal.pld_esperado_da_origem(vazio, "outro", "2026-09-01")
    assert cal.pld_esperado_da_origem(vazio, "x", "2026-09-01") == 1.0
