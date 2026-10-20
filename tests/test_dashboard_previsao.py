"""Página "Previsão de carga" (AppTest.from_function): carrega, números do snapshot iguais aos
publicados no `docs/metricas.md`, ressalva acima do número, orçamento de palavras, `$` escapado,
jargão fora da auditoria, âmbar ausente, meses incompletos fora dos gráficos, nomes sem troca."""

import json
import re
import shutil
from pathlib import Path

import pandas as pd
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
    primeiro,
    spec,
    texto,
    toda_a_tela,
)
from streamlit.testing.v1 import AppTest

from dashboard import calculos as cal
from dashboard import glossario
from dashboard import leitura as lei
from dashboard import textos_previsao as tx
from dashboard import visual as vis

RAIZ = Path(__file__).resolve().parents[1]
ORCAMENTO_DE_PALAVRAS = 450
METRICAS = (RAIZ / "docs" / "metricas.md").read_text()


def pagina(diretorio: str | None = None):
    from dashboard.paginas import previsao

    previsao.renderizar(diretorio)


def rodar(diretorio: Path | None = None) -> AppTest:
    at = AppTest.from_function(
        pagina, args=(str(diretorio) if diretorio else None,), default_timeout=90
    )
    at.run()
    return at


@pytest.fixture(scope="module")
def at():
    return rodar()


# ---------------------------------------------------------------- números publicados

# os valores como estão no metricas.md (Sprint 5, "teste final" e "Intervalos de previsão")
PUBLICADO = {
    "mape_modelo": "3,11",
    "mape_comparacao": "4,17",
    "vies_modelo": "−0,76",
    "vies_comparacao": "−2,17",
    "pares": "654",
    "cobertura80": "70,2%",
    "cobertura95": "87,8%",
    "dev_modelo": "2,66",
    "dev_comparacao": "2,92",
    "erro_2023": "−3,80%",
    "perde_2025": "3,72% contra 3,52%",
}


def test_os_valores_esperados_estao_no_metricas_md():
    """O teste não inventa o que compara: cada número esperado consta do docs/metricas.md."""
    for nome, valor in PUBLICADO.items():
        assert valor in METRICAS, (nome, valor)


# ---------------------------------------------------------------- carrega e estrutura


def test_a_pagina_carrega_sem_excecao(at):
    assert not at.exception
    assert at.title[0].value == "Previsão de carga"
    assert len(at.metric) == 3
    assert len(at.get("vega_lite_chart")) == 4  # 3 à vista + a cobertura por horizonte, no expander


def test_a_ordem_da_piramide(at):
    ordem = [
        indice(at, "title", "Previsão de carga"),
        indice(at, "info", "No teste final"),
        primeiro(at, "metric"),
        indice(at, "subheader", "Real e previsto"),
        indice(at, "subheader", "Erro por ano"),
        indice(at, "subheader", "Próximos 12 meses"),
        indice(at, "subheader", tx.TITULO_LIMITES),
        indice_exp(at, "Ver valores"),
        indice_exp(at, "Sobre o modelo"),
        indice_exp(at, "Glossário"),
        indice_exp(at, "Auditoria"),
    ]
    assert ordem == sorted(ordem)


def test_o_cabecalho_diz_de_quando_sao_os_dados(at):
    assert "10/10/2026" in at.caption[0].value and "sem consulta ao vivo" in at.caption[0].value


# ---------------------------------------------------------------- frase e cartões


def test_a_frase_traz_os_numeros_do_teste_final_e_do_desenvolvimento(at):
    frase = at.info[0].value
    assert "2021–2025" in frase and tx.CHAVES["uma_vez"] in frase
    assert "**3,1%**" in frase and "**4,2%**" in frase and vis.MESMO_MES in frase
    assert "2012–2019" in frase and "2,66%" in frase and "2,92%" in frase
    assert "menos de um erro-padrão" in frase  # 0,255 pp contra EP 0,27 pp
    assert palavras(frase) <= 60


def test_os_cartoes_com_a_ressalva_na_legenda_logo_acima_do_numero(at):
    nos = elementos(at)
    esperado = [
        ("Teste final, 5 anos, 654 pares", "Erro médio (MAPE)", "3,1%"),
        ("Negativo: previsto abaixo do real", "Viés", "−0,8%"),
        (tx.CHAVES["estreitos"], "Cobertura dos intervalos", "70,2% e 87,8%"),
    ]
    for metrica, (ressalva, rotulo, valor) in zip(at.metric, esperado, strict=True):
        assert (metrica.label, metrica.value) == (rotulo, valor)
        i = next(n for n, (_, no) in enumerate(nos) if no is metrica)
        assert nos[i - 1][0] == "caption" and nos[i - 1][1].value == ressalva
        assert metrica.proto.delta == "" and metrica.proto.help  # sem seta e com ajuda
    legendas = [c.value for c in at.caption]
    assert f"contra 4,2% do {vis.MESMO_MES}" in legendas
    assert f"contra −2,2% do {vis.MESMO_MES}" in legendas
    cob = next(c for c in legendas if c.startswith("prometido: 80% e 95%"))
    assert tx.CHAVES["fora_da_amostra"] in cob and "só no desenvolvimento" in cob


def test_os_cartoes_batem_com_o_snapshot_e_com_o_publicado(at):
    t = cal.resumo_teste_final(lei.modelos_resumo())
    assert (
        round(t["modelo"]["mape_pct"], 2) == 3.11 and round(t["comparacao"]["mape_pct"], 2) == 4.17
    )
    assert round(t["modelo"]["vies_pct"], 2) == -0.76
    assert round(t["comparacao"]["vies_pct"], 2) == -2.17
    assert t["modelo"]["n"] == 654 == t["comparacao"]["n"]
    c = lei.cobertura()["geral"]
    assert (round(c["cobertura80_pct"], 1), round(c["cobertura95_pct"], 1)) == (70.2, 87.8)
    d = cal.resumo_desenvolvimento(lei.desenvolvimento_resumo())
    assert round(d["modelo_mape_pct"], 2) == 2.66 and round(d["comparacao_mape_pct"], 2) == 2.92
    assert d["diferenca_pp"] < d["ep_pp"]  # a vantagem do desenvolvimento é menor que 1 EP


def test_a_cobertura_exibida_nunca_e_a_que_ja_viu_o_teste(at):
    tela = toda_a_tela(at)
    assert "70,8%" not in tela and "90,5%" not in tela
    assert tx.CHAVES["mais_dados"] in at.info[1].value


# ---------------------------------------------------------------- gráficos


def grafico(at, contem: str):
    return elementos(at)[indice(at, "vega_lite_chart", contem)][1]


def test_real_x_previsto_usa_so_o_teste_final_e_as_previsoes_de_dezembro(at):
    g = grafico(at, "Carga real")
    d = dados_do_grafico(g, "serie")
    assert set(d["serie"]) == {"Carga real", "Modelo", vis.MESMO_MES}
    assert d["alvo"].min() == pd.Timestamp("2021-01-01") and d["alvo"].max() == pd.Timestamp(
        "2025-12-01"
    )
    assert len(d) == 3 * 60  # 5 anos × 12 meses × 3 séries
    legenda = at.caption[indice_legenda(at, "Previsões feitas em dezembro")]
    assert "2023" in legenda.value and "−3,8%" in legenda.value and "−4,2%" in legenda.value
    assert indice(at, "caption", "Previsões feitas em dezembro") < indice(
        at, "vega_lite_chart", "Carga real"
    )


def indice_legenda(at, contem: str) -> int:
    return next(i for i, c in enumerate(at.caption) if contem in c.value)


def test_o_erro_anual_de_dezembro_bate_com_o_publicado():
    e = cal.erro_anual_dezembro(lei.previsoes_teste_final()).set_index("ano")
    assert [round(v, 2) for v in e["modelo_pct"]] == [0.46, -0.45, -3.80, 1.17, 0.76]
    assert [round(v, 2) for v in e["comparacao_pct"]] == [-3.03, -1.40, -4.18, -4.55, 0.44]
    for trecho in ("+0,46%", "−0,45%", "−3,80%", "+1,17%", "+0,76%"):
        assert trecho.replace("+", "") in METRICAS or trecho in METRICAS


def test_o_erro_por_ano_nao_esconde_onde_o_modelo_perde(at):
    legenda = next(c.value for c in at.caption if tx.CHAVES["perde"] in c.value)
    assert "perde em 2025 (3,7% contra 3,5%)" in legenda
    assert PUBLICADO["perde_2025"] in METRICAS
    g = grafico(at, "Erro médio (%)")
    d = dados_do_grafico(g, "mape_pct")
    assert len(d) == 10 and set(d["ano_txt"]) == {"2021", "2022", "2023", "2024", "2025"}
    esperado = lei.mape_por_ano()
    esperado = esperado[
        esperado["candidato"].isin([cal.CANDIDATO_MODELO, cal.CANDIDATO_COMPARACAO])
    ]
    assert sorted(round(v, 4) for v in d["mape_pct"]) == sorted(
        round(v, 4) for v in esperado["mape_pct"]
    )
    assert '"zero": true' in spec(g)  # as barras começam em zero


def test_os_proximos_12_meses_com_a_ressalva_antes_e_sem_erro_realizado(at):
    i = indice(at, "info", tx.CHAVES["mais_dados"])
    g = indice(at, "vega_lite_chart", "p975_mwmed")
    assert i < g
    aviso = elementos(at)[i][1].value
    assert "70,2%" in aviso and "87,8%" in aviso and "fora da amostra" in aviso
    d = dados_do_grafico(elementos(at)[g][1], "p975_mwmed")
    assert len(d) == 12 and d["mes_alvo"].min() == pd.Timestamp("2026-10-01")
    assert any(c.value == f"{tx.CHAVES['sem_realizado']}." for c in at.caption)
    legenda = next(c for c in at.caption if c.value.startswith("Previsão feita em set/2026"))
    assert "44.921 MWm em out/2026" in legenda.value and legenda.proto.help  # ajuda do MWm


def test_com_erros_realizados_a_frase_muda(tmp_path):
    pasta = tmp_path / "dados"
    shutil.copytree(lei.DADOS, pasta)
    (pasta / "erros_producao.csv").write_text(
        "origem,horizonte,mes_alvo,previsto_mwmed,real_mwmed,erro_pct,serie\n"
        "2026-09-01,1,2026-10-01,44921.0,44000.0,2.09,carga_ajustada_reconstruida_mwmed\n"
    )
    at = rodar(pasta)
    assert not at.exception
    assert tx.CHAVES["sem_realizado"] not in toda_a_tela(at)
    assert any("1 previsões de produção já têm valor realizado" in c.value for c in at.caption)


def test_meses_incompletos_ficam_fora_de_todos_os_graficos(at):
    man = lei.manifesto()
    incompletos = {pd.Timestamp(m) for ms in man["meses_incompletos"].values() for m in ms}
    assert incompletos  # o snapshot de 10/10/2026 tem outubro incompleto
    fechado = pd.Timestamp(man["ultimo_mes_fechado"])
    for t, no in elementos(at):
        if t != "vega_lite_chart":
            continue
        for ds in no.proto.datasets:
            import pyarrow as pa

            d = pa.ipc.open_stream(ds.data.data).read_all().to_pandas()
            if "mes" in d.columns:  # a história real da carga
                assert d["mes"].max() <= fechado and not set(d["mes"]) & incompletos
            if "alvo" in d.columns:  # o teste final
                assert d["alvo"].max() <= pd.Timestamp("2025-12-01")


# ---------------------------------------------------------------- detalhes e limites


def test_os_limites_sao_curtos_e_sempre_visiveis(at):
    i = indice(at, "subheader", tx.TITULO_LIMITES)
    nos = elementos(at)
    assert nos[i + 1][0] == "markdown"
    corpo = nos[i + 1][1].value
    assert len(re.findall(r"^\d\. ", corpo, flags=re.M)) == 4
    assert "Só 5 anos de teste" in corpo and "2,3% em 1 mês, 3,8% em 12 meses" in corpo
    assert palavras(corpo) <= 125


def test_os_limites_dizem_que_parte_da_vantagem_vem_das_quebras_da_serie(at):
    """A vantagem sobre o "Mesmo mês do ano anterior" em parte vem de ele piorar (metricas.md,
    "Parte da vantagem vem do ingênuo piorar em 2021–2025": 0,255 pp no
    desenvolvimento (0,2548 no CSV) e 1,06 pp no teste final)."""
    i = indice(at, "subheader", tx.TITULO_LIMITES)
    corpo = elementos(at)[i + 1][1].value
    frase = next(linha for linha in corpo.splitlines() if "quebras de definição" in linha)
    assert "Parte da vantagem vem de o Mesmo mês do ano anterior piorar" in frase
    for numero in ("2,92%", "4,17%", "0,255", "1,06"):
        assert numero in frase, numero
        assert numero in METRICAS  # o número citado consta do metricas.md
    assert "Ano anterior" not in frase.replace("Mesmo mês do ano anterior", "")


# ---------------------------------------------------------------- cobertura por horizonte


def _tabela_do_metricas() -> dict[int, tuple[str, str, str]]:
    """h -> (n, 80%, 95%) da coluna "anterior" da tabela da 5.6 do metricas.md."""
    inicio = METRICAS.index("| h | n | cenários 80% | cenários 95% | anterior 80% | anterior 95% |")
    linhas = {}
    for linha in METRICAS[inicio:].splitlines()[2:]:
        celulas = [c.strip() for c in linha.strip("|").split("|")]
        if not celulas[0].isdigit():
            break
        linhas[int(celulas[0])] = (celulas[1], celulas[4], celulas[5])
    return linhas


def _virgula(v: float) -> str:
    return f"{v:.1f}".replace(".", ",")


def test_os_12_horizontes_do_csv_batem_com_a_tabela_do_metricas_md():
    """O CSV versionado confere, horizonte a horizonte, 80% e 95%, com a tabela do metricas.md."""
    esperado = _tabela_do_metricas()
    assert sorted(esperado) == list(range(1, 13))
    h = lei.cobertura()["por_horizonte"]
    assert list(h["valor"]) == list(range(1, 13))
    for linha in h.itertuples():
        n, c80, c95 = esperado[int(linha.valor)]
        assert (
            str(int(linha.n)),
            _virgula(linha.cobertura80_pct),
            _virgula(linha.cobertura95_pct),
        ) == (
            n,
            c80,
            c95,
        ), linha.valor
    geral = lei.cobertura()["geral"]
    assert (_virgula(geral["cobertura80_pct"]), _virgula(geral["cobertura95_pct"])) == (
        "70,2",
        "87,8",
    )


def test_a_tabela_do_expander_mostra_os_mesmos_12_horizontes(at):
    e = expander(at, "Ver valores")
    tabela = next(
        no.value for t, no in achatar(e) if t == "dataframe" and "Meses à frente" in no.value
    )
    esperado = _tabela_do_metricas()
    assert list(tabela["Meses à frente"]) == list(range(1, 13))
    assert [c.replace("%", "") for c in tabela["Cobertura do intervalo de 80%"]] == [
        esperado[h][1] for h in range(1, 13)
    ]
    assert [c.replace("%", "") for c in tabela["Cobertura do intervalo de 95%"]] == [
        esperado[h][2] for h in range(1, 13)
    ]


# ---------------------------------------------------------------- legenda na faixa


def test_a_faixa_de_80_e_a_de_95_dizem_quanto_cobriram_no_teste_final(at):
    g = elementos(at)[indice(at, "vega_lite_chart", "p975_mwmed")][1]
    textos = list(dados_do_grafico(g, "texto")["texto"])
    assert textos == [
        "faixa de 80%: cobre 70,2% no teste final, não 80%",
        "faixa de 95%: cobre 87,8% no teste final, não 95%",
    ]
    assert '"mark": {"type": "text"' in spec(g) or '"type": "text"' in spec(g)
    # nem a cobertura que já viu o teste nem a nominal aparecem como se fossem observadas
    assert "70,8" not in " ".join(textos) and "90,5" not in " ".join(textos)


def test_o_modelo_do_lightgbm_e_a_mmgd_ficam_no_expander_com_ajuda(at):
    e = expander(at, "Sobre o modelo")
    assert not e.proto.expanded
    md = next(no for t, no in achatar(e) if t == "markdown")
    assert "perdeu pelo critério congelado" in md.value and "3,45%" in md.value
    assert "2,92%" in md.value and tx.CHAVES["mmgd"] in md.value
    assert md.proto.help and "micro e minigeração" in md.proto.help


def test_as_tabelas_e_a_auditoria_ficam_em_expanders_fechados(at):
    for rotulo in ("Ver valores", "Sobre o modelo", "Glossário", "Auditoria"):
        assert not expander(at, rotulo).proto.expanded
    fora = [t for t, _ in antes_dos_expanders(at)]
    assert "dataframe" not in fora
    valores = expander(at, "Ver valores")
    tabelas = [no.value for t, no in achatar(valores) if t == "dataframe"]
    assert len(tabelas) == 4 and len(tabelas[1]) == 5
    assert tabelas[0]["Meses avaliados"].tolist() == [654, 654]
    assert tabelas[1]["Ano inteiro previsto em dezembro, modelo"].iloc[2] == "−3,80%"
    assert len(tabelas[2]) == 12 and len(tabelas[3]) == 12


def antes_dos_expanders(at):
    saida = []
    for t, no in elementos(at):
        if t == "expander":
            break
        saida.append((t, no))
    return saida


def test_a_auditoria_tem_fonte_calibracao_e_nomes_dos_candidatos(at):
    e = expander(at, "Auditoria")
    md = next(no.value for t, no in achatar(e) if t == "markdown")
    assert "analise_teste_final_reconstruida_cobertura_por_horizonte.csv" in md
    assert "desenvolvimento+teste_final" in md and cal.CANDIDATO_MODELO in md
    assert cal.CANDIDATO_COMPARACAO in md


# ---------------------------------------------------------------- regras do redesenho


def test_orcamento_de_palavras_e_de_caixas(at):
    visiveis = palavras_visiveis(at.main)
    assert visiveis <= ORCAMENTO_DE_PALAVRAS, visiveis
    assert len(at.warning) == 0  # âmbar só para prévia e especulação: a Previsão não tem
    assert len(at.info) <= 2 and len(at.subheader) <= 4
    assert not {t for t, _ in elementos(at)} & {"error", "success", "exception"}


def test_o_ambar_nao_aparece_nos_graficos(at):
    for t, no in elementos(at):
        if t == "vega_lite_chart":
            assert vis.AMBAR.lower() not in spec(no).lower()


SEM_ESCAPE = re.compile(r"(?<!\\)\$")


def test_nenhum_dolar_sem_escape(at):
    for t, no in elementos(at):
        if t in ("markdown", "caption", "info", "warning", "subheader", "title"):
            assert not SEM_ESCAPE.search(no.value), no.value[:100]
        elif t == "metric":
            assert not SEM_ESCAPE.search(no.label + (no.proto.help or ""))


JARGAO = (
    "comb_ets",
    "sazonal_ingenuo",
    "mape_pct",
    "mwmed",
    "MWmed",
    "desenvolvimento+teste_final",
    "ingênuo",
    "ingenuo",
    "pontual",
    "docs/",
    "manifest",
    "sha256",
    ".csv",
    "Ano anterior",  # a estratégia de contrato da Decisão: aqui o comparativo é outro
)


def textos_do_grafico(no) -> str:
    """O que o leitor VÊ de um gráfico: títulos e células de texto dos dados (não os nomes de campo,
    que ficam no JSON)."""
    import pyarrow as pa

    def titulos(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k in ("title", "text") and isinstance(v, str):
                    yield v
                else:
                    yield from titulos(v)
        elif isinstance(x, list):
            for v in x:
                yield from titulos(v)

    saida = list(titulos(json.loads(no.proto.spec)))
    for ds in no.proto.datasets:
        d = pa.ipc.open_stream(ds.data.data).read_all().to_pandas()
        for c in d.select_dtypes(include=["object", "string"]).columns:
            saida.extend(map(str, d[c].unique()))
    return "\n".join(saida)


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
    assert "MAPE" in at.metric[0].proto.help or "erro percentual" in at.metric[0].proto.help
    glossario_md = expander(at, "Glossário").markdown[0].value
    for sigla in ("MWm", "MAPE", "MMGD"):
        assert f"**{sigla}:**" in glossario_md
    assert all(k in glossario.TERMOS for k in tx.GLOSSARIO)


def test_nenhum_numero_aparece_antes_da_ressalva_dele(at):
    nos = elementos(at)
    primeiro_numero = min(
        i for i, (t, _) in enumerate(nos) if t in ("metric", "vega_lite_chart", "dataframe")
    )
    assert indice(at, "info", "No teste final") < primeiro_numero  # a frase vem antes de tudo
    assert nos[0][0] == "title"


def test_o_app_com_navegacao_tem_as_duas_paginas_e_carrega():
    fonte = (RAIZ / "dashboard" / "app.py").read_text()
    assert "decisao.renderizar" in fonte and "previsao.renderizar" in fonte
    app = AppTest.from_file(str(RAIZ / "dashboard" / "app.py"), default_timeout=90)
    app.run()
    assert not app.exception and app.title[0].value == "Decisão de contrato"
