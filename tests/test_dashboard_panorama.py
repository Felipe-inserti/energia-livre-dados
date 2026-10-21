"""Página "Panorama do setor" (versão mínima): números conferidos contra os dois CSVs que ela lê,
ressalva acima do número, quebra do tipo III conferida contra os dados, orçamento de palavras,
paleta e jargão fora da auditoria."""

import csv
import json
import re
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pytest
from apptest_util import (
    achatar,
    dados_do_grafico,
    elementos,
    expander,
    indice,
    indice_exp,
    palavras,
    palavras_visiveis,
    spec,
    texto,
    textos_do_grafico,
)
from streamlit.testing.v1 import AppTest

from dashboard import calculos as cal
from dashboard import glossario
from dashboard import graficos as gr
from dashboard import leitura as lei
from dashboard import textos_panorama as tx
from dashboard import visual as vis

RAIZ = Path(__file__).resolve().parents[1]
DADOS = RAIZ / "dashboard" / "dados"
ORCAMENTO_DE_PALAVRAS = 300
METRICAS = (RAIZ / "docs" / "metricas.md").read_text()


def pagina(diretorio: str | None = None):
    from dashboard.paginas import panorama

    panorama.renderizar(diretorio)


def rodar(diretorio: Path | None = None) -> AppTest:
    at = AppTest.from_function(
        pagina, args=(str(diretorio) if diretorio else None,), default_timeout=90
    )
    at.run()
    return at


@pytest.fixture(scope="module")
def at():
    return rodar()


def linhas_csv(nome: str) -> list[dict]:
    with open(DADOS / nome, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def conjuntos(no) -> list[pd.DataFrame]:
    return [pa.ipc.open_stream(ds.data.data).read_all().to_pandas() for ds in no.proto.datasets]


# ---------------------------------------------------------------- números dos CSVs


def test_os_numeros_esperados_batem_com_os_csvs():
    """Lidos direto dos CSVs (sem passar pela camada de dados): set/2026 fechado, out/2026 não."""
    carga = linhas_csv("carga_mensal_se.csv")
    fechados = [r for r in carga if r["mes_utilizavel"] == "True"]
    assert len(carga) == 322 and len(fechados) == 321
    ultimo = fechados[-1]
    assert ultimo["mes"] == "2026-09-01"
    assert round(float(ultimo["carga_ajustada_reconstruida_mwmed"]), 3) == 44517.185
    set_2025 = next(r for r in carga if r["mes"] == "2025-09-01")
    base = float(set_2025["carga_ajustada_reconstruida_mwmed"])
    esperado = 100 * (44517.185 / base - 1)
    assert round(esperado, 1) == 3.9
    c = cal.ultima_carga(lei.carga_mensal())
    assert c["mes"] == pd.Timestamp("2026-09-01") and round(c["mwm"], 3) == 44517.185
    assert round(c["mwm_anterior"], 3) == round(base, 3)
    assert abs(c["variacao_pct"] - esperado) < 1e-9
    pld = linhas_csv("pld_mensal_se.csv")
    u = pld[-1]
    assert u["mes"] == "2026-09-01" and u["fonte"] == "ponderado"
    assert (round(float(u["pld_rs_mwh"]), 2), u["piso_rs_mwh"], u["teto_estrutural_rs_mwh"]) == (
        131.91,
        "57.31",
        "785.27",
    )
    p = cal.ultimo_pld(lei.pld_mensal())
    assert (round(p["rs_mwh"], 2), p["piso"], p["teto"], p["fonte"]) == (
        131.91,
        57.31,
        785.27,
        "ponderado",
    )


# ---------------------------------------------------------------- carrega e estrutura


def test_a_pagina_carrega_sem_excecao(at):
    assert not at.exception
    assert len(at.get("vega_lite_chart")) == 2 and len(at.metric) == 2


def test_a_ordem_da_piramide(at):
    nos = elementos(at)
    assert nos[0][0] == "title" and nos[0][1].value == "Panorama do setor"
    ordem = [
        indice(at, "info", "No snapshot de"),
        indice(at, "metric", "Carga em set/2026"),
        indice(at, "metric", "PLD em set/2026"),
        indice(at, "subheader", "Carga mensal do SE/CO"),
        indice(at, "subheader", "PLD mensal do Sudeste"),
        indice(at, "subheader", tx.TITULO_LIMITES),
        indice_exp(at, "Ver valores"),
        indice_exp(at, "Glossário"),
        indice_exp(at, "Auditoria"),
    ]
    assert ordem == sorted(ordem)


def test_o_cabecalho_diz_de_quando_sao_os_dados(at):
    assert "10/10/2026" in at.caption[0].value and "sem consulta ao vivo" in at.caption[0].value


# ---------------------------------------------------------------- frase e cartões


def test_a_frase_traz_os_numeros_do_snapshot(at):
    frase = at.info[0].value
    assert "No snapshot de 10/10/2026" in frase
    assert "carga do SE/CO em set/2026 foi de **44.517 MWm** (+3,9% contra set/2025)" in frase
    assert "PLD mensal foi de **R\\$ 131,91/MWh**" in frase
    assert "piso de R\\$ 57,31 e o teto estrutural de R\\$ 785,27" in frase
    assert palavras(frase) <= 60


def test_os_cartoes_com_a_ressalva_na_legenda_logo_acima_do_numero(at):
    assert [m.label for m in at.metric] == ["Carga em set/2026", "PLD em set/2026"]
    assert [m.value for m in at.metric] == ["44.517 MWm", "R$ 131,91/MWh"]
    nos = elementos(at)
    ressalvas = [
        "Carga do SE/CO inteiro, não do consumidor-exemplo",
        "Ponderado pelo consumo do consumidor-exemplo (antes de 2021, o PLD semanal agregado)",
    ]
    for metrica, ressalva in zip(at.metric, ressalvas, strict=True):
        i = next(n for n, (_, no) in enumerate(nos) if no is metrica)
        assert nos[i - 1][0] == "caption" and nos[i - 1][1].value == ressalva
    legendas = [c.value for c in at.caption]
    assert "+3,9% contra set/2025 (42.854 MWm)" in legendas
    assert "piso R\\$ 57,31 · teto estrutural R\\$ 785,27, do ano" in legendas


def test_a_ressalva_do_pld_muda_se_a_ultima_conta_for_a_semanal():
    carga = {
        "mes": pd.Timestamp("2020-12-01"),
        "mwm": 1.0,
        "mwm_anterior": None,
        "variacao_pct": None,
    }
    pld = {
        "mes": pd.Timestamp("2020-12-01"),
        "rs_mwh": 10.0,
        "piso": None,
        "teto": None,
        "fonte": "semanal",
    }
    c = tx.cartoes(carga, pld)
    assert c[1]["ressalva"] == "PLD semanal agregado por mês, sem ponderar pelo consumo"
    assert c[0]["linhas"] == [] and c[1]["linhas"] == []
    assert "entre o piso" not in tx.frase("01/01/2021", carga, pld)


# ---------------------------------------------------------------- as ressalvas, antes dos números


def test_as_ressalvas_do_bloco_vem_antes_do_grafico_de_cada_bloco(at):
    nos = elementos(at)
    graficos = [i for i, (t, _) in enumerate(nos) if t == "vega_lite_chart"]
    assert len(graficos) == 2
    carga_i = indice(
        at, "caption", "Carga do SE/CO inteiro, não do consumidor-exemplo. A reconstruída"
    )
    pld_i = indice(at, "caption", "duas contas diferentes")
    assert carga_i + 1 == graficos[0] and pld_i + 1 == graficos[1]  # a legenda é logo acima
    legenda_carga, legenda_pld = nos[carga_i][1].value, nos[pld_i][1].value
    assert tx.CHAVES["se_co"] in legenda_carga
    assert "quebra do tipo III (mar/2021)" in legenda_carga
    assert "As séries só diferem até abr/2023; depois coincidem." in legenda_carga
    assert "semanal agregado por mês, até dez/2020" in legenda_pld
    assert "ponderado pelo consumo do consumidor-exemplo, de 2021 em diante" in legenda_pld
    assert "a série não é contínua" in legenda_pld
    assert "Piso e teto estrutural (tracejados) só existem de 2021 em diante" in legenda_pld


def test_os_limites_dizem_que_reservatorios_ficam_de_fora(at):
    i = indice(at, "subheader", tx.TITULO_LIMITES)
    corpo = elementos(at)[i + 1][1].value
    assert len(re.findall(r"^\d\. ", corpo, flags=re.M)) == 3
    assert "Reservatórios (EAR/ENA) não foram ingeridos; fora do escopo." in corpo
    assert "Nada aqui é do consumidor-exemplo" in corpo
    assert "É o estado de 10/10/2026**, não ao vivo; out/2026 ainda não fechou" in corpo
    assert palavras(corpo) <= 70


def test_o_mes_incompleto_fica_fora_dos_dois_graficos(at):
    for t, no in elementos(at):
        if t != "vega_lite_chart":
            continue
        for d in conjuntos(no):
            if "mes" in d.columns:
                assert pd.to_datetime(d["mes"]).max() <= pd.Timestamp("2026-09-01")


# ---------------------------------------------------------------- os gráficos


def graficos(at):
    return [no for t, no in elementos(at) if t == "vega_lite_chart"]


def test_o_grafico_da_carga_tem_as_duas_series_e_a_quebra_do_tipo_iii(at):
    g = graficos(at)[0]
    d = dados_do_grafico(g, "serie")
    assert set(d["serie"]) == {gr.SERIE_ORIGINAL, gr.SERIE_RECONSTRUIDA}
    por_serie = d.groupby("serie")["mes"].agg(["min", "max", "count"])
    assert pd.to_datetime(por_serie.loc[gr.SERIE_ORIGINAL, "min"]) == pd.Timestamp("2000-01-01")
    assert pd.to_datetime(por_serie.loc[gr.SERIE_RECONSTRUIDA, "min"]) == pd.Timestamp("2015-01-01")
    assert por_serie.loc[gr.SERIE_ORIGINAL, "count"] == 321
    marca = next(x for x in conjuntos(g) if "texto" in x.columns)
    assert list(marca["texto"]) == ["quebra do tipo III (mar/2021)"]
    assert pd.to_datetime(marca["mes"].iloc[0]) == cal.QUEBRA_TIPO_III
    tipos = [
        c["mark"]["type"] if isinstance(c["mark"], dict) else c["mark"]
        for c in json.loads(g.proto.spec)["layer"]
    ]
    assert tipos == ["line", "rule", "text"]
    assert '"zero": false' in spec(g) or '"zero":false' in spec(g)  # linha de carga, não barra


def test_a_data_da_quebra_do_tipo_iii_bate_com_os_dados_e_com_o_metricas_md():
    """01/03/2021. A razão reconstruída/original é sazonal, então compara-se cada mês de 2021 com o
    MESMO mês de 2020: em jan e fev a razão não muda; de mar em diante cai (de 0,03 a 0,09)."""
    assert "01/03/2021" in METRICAS and "Usinas não despachadas (tipo III)" in METRICAS
    c = lei.carga_mensal().dropna(subset=["carga_ajustada_reconstruida_mwmed"]).set_index("mes")
    razao = c["carga_ajustada_reconstruida_mwmed"] / c["carga_original_mwmed"]
    queda = {
        m: razao[pd.Timestamp(2020, m, 1)] - razao[pd.Timestamp(2021, m, 1)] for m in range(1, 13)
    }
    assert abs(queda[1]) < 0.01 and abs(queda[2]) < 0.01
    assert all(queda[m] > 0.02 for m in range(3, 13))
    primeiro = min(m for m in range(1, 13) if queda[m] > 0.02)
    assert pd.Timestamp(2021, primeiro, 1) == cal.QUEBRA_TIPO_III


def test_as_series_de_carga_so_diferem_ate_o_ultimo_mes_com_ajuste():
    c = lei.carga_mensal().dropna(subset=["carga_ajustada_reconstruida_mwmed"])
    ultimo = cal.ultimo_mes_com_ajuste(lei.carga_mensal())
    assert ultimo == pd.Timestamp("2023-04-01")
    depois = c[c["mes"] > ultimo]
    assert (depois["carga_ajustada_reconstruida_mwmed"] == depois["carga_original_mwmed"]).all()


def test_o_grafico_do_pld_separa_as_duas_contas_e_so_tem_piso_e_teto_de_2021_em_diante(at):
    g = graficos(at)[1]
    d = dados_do_grafico(g, "serie")
    d["mes"] = pd.to_datetime(d["mes"])
    assert set(d["serie"]) == {
        gr.SERIE_PLD_SEMANAL,
        gr.SERIE_PLD_PONDERADO,
        gr.SERIE_PISO,
        gr.SERIE_TETO,
    }
    semanal = d[d["serie"] == gr.SERIE_PLD_SEMANAL]["mes"]
    ponderado = d[d["serie"] == gr.SERIE_PLD_PONDERADO]["mes"]
    assert semanal.min() == pd.Timestamp("2002-01-01") and semanal.max() == pd.Timestamp(
        "2020-12-01"
    )
    assert ponderado.min() == pd.Timestamp("2021-01-01") and ponderado.max() == pd.Timestamp(
        "2026-09-01"
    )
    limites = d[d["serie"].isin([gr.SERIE_PISO, gr.SERIE_TETO])]
    assert limites["mes"].min() == pd.Timestamp("2021-01-01")
    assert (
        d[d["serie"] == gr.SERIE_PISO]["valor"] < d[d["serie"] == gr.SERIE_TETO]["valor"].min()
    ).all()
    s = spec(g)
    assert '"zero": true' in s  # o PLD começa em zero
    assert '"strokeDash"' in s  # piso e teto tracejados


def test_os_valores_do_pld_no_grafico_batem_com_o_csv(at):
    g = graficos(at)[1]
    d = dados_do_grafico(g, "serie")
    d["mes"] = pd.to_datetime(d["mes"])
    csv_pld = {r["mes"]: float(r["pld_rs_mwh"]) for r in linhas_csv("pld_mensal_se.csv")}
    pontos = d[d["serie"].isin([gr.SERIE_PLD_SEMANAL, gr.SERIE_PLD_PONDERADO])]
    assert len(pontos) == len(csv_pld) == 297
    for r in pontos.itertuples():
        assert abs(r.valor - csv_pld[r.mes.strftime("%Y-%m-%d")]) < 1e-6
    # o CSV diz de onde vem cada mês: semanal até dez/2020, ponderado depois
    fontes = {r["mes"]: r["fonte"] for r in linhas_csv("pld_mensal_se.csv")}
    assert all(f == ("semanal" if m < "2021-01-01" else "ponderado") for m, f in fontes.items())
    assert {r["limites_assumidos"] for r in linhas_csv("pld_mensal_se.csv")} == {"", "False"}


def test_o_ultimo_mes_do_pld_semanal_vem_dos_dados():
    assert cal.ultimo_mes_do_pld_semanal(lei.pld_mensal()) == pd.Timestamp("2020-12-01")


# ---------------------------------------------------------------- tabelas, glossário e auditoria


def test_as_tabelas_ficam_em_expanders_fechados_e_batem_com_os_csvs(at):
    for rotulo in ("Ver valores", "Glossário", "Auditoria"):
        assert not expander(at, rotulo).proto.expanded
    fora = []
    for t, _ in elementos(at):
        if t == "expander":
            break
        fora.append(t)
    assert "dataframe" not in fora
    carga, pld = [no.value for t, no in achatar(expander(at, "Ver valores")) if t == "dataframe"]
    assert len(carga) == 12 and carga["Mês"].iloc[-1] == "set/2026"
    assert carga["Reconstruída (MWm)"].iloc[-1] == "44.517"
    assert len(pld) == 12 and pld["PLD (R$/MWh)"].iloc[-1] == "131,91"
    assert pld["Piso do ano (R$/MWh)"].iloc[-1] == "57,31"
    assert pld["Teto estrutural do ano (R$/MWh)"].iloc[-1] == "785,27"


def test_a_auditoria_tem_fontes_hashes_e_a_origem_da_quebra(at):
    md = next(no.value for t, no in achatar(expander(at, "Auditoria")) if t == "markdown")
    man = lei.manifesto()["arquivos"]
    for nome in ("carga_mensal_se.csv", "pld_mensal_se.csv"):
        assert nome in md and man[nome]["sha256"][:12] in md
    assert "marts.fct_carga_mensal" in md and "marts.fct_pld_ponderado_mensal" in md
    assert "2026-10-01" in md and "docs/metricas.md" in md and "01/03/2021" in md
    assert "limites_assumidos" in md


def test_a_pagina_so_le_os_dois_csvs_do_panorama():
    lidos = []
    original = lei._csv

    def espiao(nome, *a, **k):
        lidos.append(nome)
        return original(nome, *a, **k)

    lei._csv = espiao
    try:
        import streamlit as st

        st.cache_data.clear()
        rodar()
    finally:
        lei._csv = original
        st.cache_data.clear()
    assert sorted(set(lidos)) == ["carga_mensal_se.csv", "pld_mensal_se.csv"]


# ---------------------------------------------------------------- regras do redesenho


def test_orcamento_de_palavras_e_de_caixas(at):
    visiveis = palavras_visiveis(at.main)
    assert visiveis <= ORCAMENTO_DE_PALAVRAS, visiveis
    assert len(at.warning) == 0 and len(at.info) == 1  # só a frase; sem âmbar
    assert len(at.metric) <= 2 and len(at.subheader) <= 3
    assert not {t for t, _ in elementos(at)} & {"error", "success", "exception"}


def test_so_cores_da_paleta_e_nada_de_ambar_nos_graficos(at):
    paleta = {c.lower() for c in vis.PALETA}
    for no in graficos(at):
        cores = {c.lower() for c in re.findall(r"#[0-9a-fA-F]{6}", spec(no))}
        assert cores and cores <= paleta, cores
        assert vis.AMBAR.lower() not in cores


SEM_ESCAPE = re.compile(r"(?<!\\)\$")


def test_nenhum_dolar_sem_escape(at):
    for t, no in elementos(at):
        if t in ("markdown", "caption", "info", "warning", "subheader", "title"):
            assert not SEM_ESCAPE.search(no.value), no.value[:100]
        elif t == "metric":
            assert not SEM_ESCAPE.search(no.label + (no.proto.help or ""))


JARGAO = (
    "carga_original",
    "carga_ajustada",
    "reconstruida_mwmed",
    "pld_rs",
    "mwmed",
    "MWmed",
    "mes_utilizavel",
    "limites_assumidos",
    "fct_",
    "pld_limites",
    ".csv",
    "docs/",
    "manifest",
    "sha256",
    "ponderado`",
    "marts.",
)


def test_nenhum_jargao_fora_da_auditoria_e_do_glossario(at):
    visivel = []
    for t, no in elementos(at):
        if t == "expander" and no.label.startswith("Glossário"):
            break
        visivel.append(textos_do_grafico(no) if t == "vega_lite_chart" else texto(no))
    tela = "\n".join(visivel)
    achados = [j for j in JARGAO if j in tela]
    assert not achados, achados


def test_as_siglas_tem_ajuda_no_ponto_de_uso_e_no_glossario(at):
    assert "megawatt médio" in at.metric[0].proto.help
    assert "Preço de Liquidação" in at.metric[1].proto.help
    glossario_md = expander(at, "Glossário").markdown[0].value
    for termo in ("PLD", "PLD ponderado", "MWm", "SE/CO", "Tipo III", "Carga reconstruída"):
        assert f"**{termo}:**" in glossario_md
    assert all(k in glossario.TERMOS for k in tx.GLOSSARIO)


def test_nenhum_numero_aparece_antes_da_ressalva_dele(at):
    nos = elementos(at)
    primeiro_numero = min(
        i for i, (t, _) in enumerate(nos) if t in ("metric", "vega_lite_chart", "dataframe")
    )
    assert indice(at, "info", "No snapshot de") < primeiro_numero  # a frase vem antes de tudo
    for metrica in at.metric:
        i = next(n for n, (_, no) in enumerate(nos) if no is metrica)
        assert nos[i - 1][0] == "caption" and len(nos[i - 1][1].value) > 20


# ---------------------------------------------------------------- navegação


def test_o_app_tem_o_panorama_como_ultima_pagina_e_carrega():
    fonte = (RAIZ / "dashboard" / "app.py").read_text()
    nomes = ["decisao", "previsao", "saude", "panorama"]
    posicoes = [fonte.index(f"{n}.renderizar") for n in nomes]
    assert posicoes == sorted(posicoes)  # o Panorama vem depois das outras três
    assert 'title="Panorama do setor", url_path="panorama"' in fonte
    app = AppTest.from_file(str(RAIZ / "dashboard" / "app.py"), default_timeout=90)
    app.run()
    assert not app.exception and app.title[0].value == "Decisão de contrato"
