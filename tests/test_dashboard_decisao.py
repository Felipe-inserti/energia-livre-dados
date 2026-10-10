"""Página "Decisão de contrato" redesenhada (AppTest.from_function).

Mantém as regras da versão anterior (a ressalva vem ANTES do número; os hashes, o placar, f = 0
rotulado, a especulação rotulada, a prévia sem economia; as partes somam o total ao centavo ou o
texto explica) e acrescenta as do redesenho (`data/logs/relatorio_6c2_redesign.md`): orçamento de
palavras, `$` sempre escapado, nenhum jargão do código fora da auditoria e do glossário, só cores
da paleta, auditoria fechada.
"""

import json
import re
import shutil
import tomllib
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from dashboard import calculos as cal
from dashboard import leitura as lei
from dashboard import textos as tx
from dashboard import visual as vis

RAIZ = Path(__file__).resolve().parents[1]
H_BASE = "02990fdf26529b59bd0aec5883f7ca7e9e2443d0"
H_SENS = "4c02987d0270dd91639cdc410d801fe550710af9"
ORCAMENTO_DE_PALAVRAS = 600  # a página tinha 1.747 palavras visíveis antes do redesenho


def pagina(diretorio: str | None = None):
    from dashboard.paginas import decisao

    decisao.renderizar(diretorio)


def rodar(diretorio: Path | None = None) -> AppTest:
    at = AppTest.from_function(
        pagina, args=(str(diretorio) if diretorio else None,), default_timeout=90
    )
    at.run()
    return at


@pytest.fixture(scope="module")
def at():
    return rodar()


# ---------------------------------------------------------------- leitura da árvore da página


def achatar(bloco, saida=None):
    """Todos os elementos na ordem em que aparecem (entrando nos expanders e colunas)."""
    saida = [] if saida is None else saida
    for k in sorted(bloco.children):
        n = bloco.children[k]
        if getattr(n, "children", None):
            saida.append((n.type, n))
            achatar(n, saida)
        else:
            saida.append((n.type, n))
    return saida


def elementos(at):
    return achatar(at.main)


def spec(no) -> str:
    """O spec Vega-Lite de um gráfico, legível (o JSON do Streamlit escapa os acentos)."""
    return json.dumps(json.loads(no.proto.spec), ensure_ascii=False)


def dados_do_grafico(no, coluna: str | None = None) -> pd.DataFrame:
    """Os dados de um gráfico Altair (o Streamlit os manda em Arrow, fora do spec). Com várias
    camadas há vários conjuntos: devolve o maior que tem a `coluna`."""
    import pyarrow as pa

    todos = [pa.ipc.open_stream(ds.data.data).read_all().to_pandas() for ds in no.proto.datasets]
    candidatos = [d for d in todos if coluna is None or coluna in d.columns]
    return max(candidatos, key=len)


def texto(no) -> str:
    """O texto de um elemento; de um gráfico, o spec e os dados; de uma tabela, o CSV."""
    if hasattr(no, "proto") and hasattr(no.proto, "spec"):
        tudo = [spec(no)]
        for ds in no.proto.datasets:
            import pyarrow as pa

            tudo.append(pa.ipc.open_stream(ds.data.data).read_all().to_pandas().to_csv())
        return "\n".join(tudo)
    valor = getattr(no, "value", "")
    rotulo = getattr(no, "label", "") or ""  # métricas e expanders: o rótulo também é texto
    if isinstance(valor, str):
        return f"{rotulo}\n{valor}" if rotulo else valor
    if isinstance(valor, pd.DataFrame):
        return valor.to_csv() + " ".join(map(str, valor.columns))
    return rotulo


def indice(at, tipo: str, contem: str) -> int:
    for i, (t, no) in enumerate(elementos(at)):
        if t == tipo and contem in texto(no):
            return i
    raise AssertionError(f"não achei {tipo} com {contem!r}")


def indice_exp(at, comeca_com: str) -> int:
    return next(
        i
        for i, (t, no) in enumerate(elementos(at))
        if t == "expander" and no.label.startswith(comeca_com)
    )


def primeiro(at, tipo: str) -> int:
    return next(i for i, (t, _) in enumerate(elementos(at)) if t == tipo)


def expander(at, comeca_com: str):
    return next(
        no for t, no in elementos(at) if t == "expander" and no.label.startswith(comeca_com)
    )


def toda_a_tela(at) -> str:
    return "\n".join(texto(no) for _, no in elementos(at))


def antes_do_glossario(at) -> str:
    """Tudo que aparece fora do glossário e da auditoria (o glossário vem antes da auditoria)."""
    saida = []
    for t, no in elementos(at):
        if t == "expander" and no.label.startswith("Glossário"):
            break
        saida.append(texto(no))
    return "\n".join(saida)


def palavras(t: str) -> int:
    return len(re.findall(r"\S+", re.sub(r"[*`_#>]", "", t or "")))


def palavras_visiveis(bloco) -> int:
    """Prosa visível, sem tooltips e sem o que está dentro de expanders (fechados)."""
    total = 0
    for k in sorted(bloco.children):
        n = bloco.children[k]
        if n.type == "expander":
            continue
        if getattr(n, "children", None):
            total += palavras_visiveis(n)
        elif n.type in ("title", "subheader", "caption", "markdown", "info", "warning"):
            total += palavras(n.value)
        elif n.type == "metric":
            total += palavras(n.label) + palavras(n.value)
    return total


# ---------------------------------------------------------------- carrega e estrutura


def test_a_pagina_carrega_sem_excecao(at):
    assert not at.exception
    assert at.title[0].value == "Decisão de contrato"
    # 4 gráficos à vista + o detalhe por ano da banda, dentro do expander
    assert len(at.metric) == 3 and len(at.get("vega_lite_chart")) == 5


def test_a_ordem_da_piramide(at):
    ordem = [
        indice(at, "title", "Decisão de contrato"),
        indice(at, "info", "Em 5 anos simulados"),
        primeiro(at, "metric"),
        indice(at, "subheader", "Ganho da otimização por ano"),
        indice(at, "subheader", "Por que funcionou"),
        indice(at, "subheader", "A banda de flexibilidade"),
        indice(at, "subheader", "Sensibilidades"),
        indice(at, "subheader", "Prévia"),
        indice(at, "subheader", tx.TITULO_LIMITACOES),
        indice_exp(at, "Glossário"),
        indice_exp(at, "Auditoria"),
    ]
    assert ordem == sorted(ordem)
    assert elementos(at)[-1][0] != "vega_lite_chart"


def test_nao_ha_controle_de_recorte(at):
    assert len(at.toggle) == 0 and len(at.radio) == 0


# ---------------------------------------------------------------- cabeçalho e frase


def test_o_cabecalho_mostra_o_estado_e_os_dois_hashes_curtos_antes_dos_numeros(at):
    cab = at.caption[0].value
    assert "10/10/2026" in cab and "sem consulta ao vivo" in cab
    assert H_BASE[:7] in cab and H_SENS[:7] in cab and H_BASE not in cab
    assert "as expectativas que erraram estão reportadas" in cab
    assert indice(at, "caption", H_BASE[:7]) < primeiro(at, "metric")


def test_a_frase_diz_o_essencial_antes_dos_cartoes(at):
    i = indice(at, "info", "Em 5 anos simulados")
    frase = elementos(at)[i][1].value
    assert "0,9%" in frase and "R\\$ 8,7 mil" in frase and "previsão de consumo" in frase
    assert i < primeiro(at, "metric") and palavras(frase) <= 45


# ---------------------------------------------------------------- três cartões


def test_os_tres_cartoes_com_a_ressalva_antes_do_numero(at):
    c1, c2, c3 = list(at.metric)
    assert [c.label for c in at.metric] == [
        "Economia total",
        "Parte vinda de 2022 e 2025",
        "Valor da previsão",
    ]
    assert (c1.value, c2.value, c3.value) == ("R$ 8,7 mil", "102%", "≈ 0")
    # a ressalva é a legenda IMEDIATAMENTE acima do número, dentro do mesmo cartão
    nos = elementos(at)
    for metrica, ressalva in zip(
        at.metric,
        (
            f"5 anos simulados, {tx.CHAVES['cinco_anos']}",
            tx.CHAVES["concentracao"],
            "Com banda de ±10%",
        ),
        strict=True,
    ):
        i = next(n for n, (_, no) in enumerate(nos) if no is metrica)
        assert nos[i - 1][0] == "caption" and nos[i - 1][1].value == ressalva
    legendas = [c.value for c in at.caption]
    assert any(c.startswith("0,9% do custo · sem 2021: 1,2%") for c in legendas)
    assert any("R\\$ 9,2 mil de R\\$ 9,0 mil" in c and "−R\\$ 182" in c for c in legendas)
    assert any(f"−R\\$ 330 (−0,03%): {tx.CHAVES['previsao_zero']}" in c for c in legendas)
    assert any(c.startswith("sem 2021: −R\\$ 311 (−0,04%)") for c in legendas)


def test_os_cartoes_nao_tem_seta_nem_variacao_e_tem_ajuda(at):
    for m in at.metric:
        assert m.proto.delta == "" and m.proto.help
    assert "PLD" in tx.GLOSSARIO and "Ano anterior" in at.metric[0].proto.help


def test_os_cartoes_sao_o_valor_exato_arredondado_uma_vez(at):
    res = cal.resultado(lei.backtest_economia())
    assert vis.reais_curto(res["economia_total_rs"]) == "R$ 8,7 mil"
    assert vis.reais_curto(res["valor_previsao_rs"]) == "−R$ 330"
    assert vis.reais_curto(-182.43) == "−R$ 182" and vis.reais_curto(9202.62) == "R$ 9,2 mil"
    assert any(tx.NOTA_DOS_CARTOES == c.value for c in at.caption)


# ---------------------------------------------------------------- ganho por ano


def test_o_grafico_de_ganho_destaca_2022_e_2025_e_o_ano_e_texto(at):
    g = elementos(at)[indice(at, "vega_lite_chart", "ano_txt")][1]
    dados = dados_do_grafico(g, "destaque")
    barras = dados.drop_duplicates("ano_txt").set_index("ano_txt")
    assert list(barras.index) == ["2021", "2022", "2023", "2024", "2025"]
    assert list(barras["destaque"]) == [False, True, False, False, True]
    assert '"zero": true' in spec(g) and "2.021" not in toda_a_tela(at)
    legenda = next(c.value for c in at.caption if "Faixa cinza" in c.value)
    assert tx.CHAVES["simulado"] in legenda and tx.CHAVES["portaria"] in legenda
    assert "Portaria Normativa MME 50/2022" in legenda and "varejista" in legenda
    assert indice(at, "caption", "Faixa cinza") < indice(at, "vega_lite_chart", "ano_txt")


def test_os_numeros_por_ano_ficam_num_expander_com_centavos(at):
    e = expander(at, "Números por ano")
    assert not e.proto.expanded
    tabela = next(no.value for t, no in achatar(e) if t == "dataframe")
    assert list(tabela["Ano"]) == ["2021", "2022", "2023", "2024", "2025"]
    assert tabela["Valor da otimização"].iloc[1].startswith("+R$ 5.843,24")
    assert tabela["Valor da otimização"].iloc[2].startswith("−R$ 116,14")
    legenda = next(no.value for t, no in achatar(e) if t == "caption")
    for parte in ("R\\$ 9.202,62", "102,0%", "R\\$ 9.020,19", "−R\\$ 182,43", "R\\$ 0,00"):
        assert parte in legenda


# ---------------------------------------------------------------- por que funcionou


def test_por_que_funcionou_explica_a_regra_e_tem_a_ajuda_do_pld(at):
    i = indice(at, "markdown", tx.CHAVES["reversao"])
    md = elementos(at)[i][1]
    assert "PLD esperado pelos cenários" in md.value and "2022, 2025" in md.value
    assert "2023, 2024" in md.value and md.proto.help and "Preço de Liquidação" in md.proto.help
    assert palavras(md.value) <= 75
    g = elementos(at)[indice(at, "vega_lite_chart", "PLD esperado pelos cenários")][1]
    assert i < indice(at, "vega_lite_chart", "PLD esperado pelos cenários")
    assert list(dados_do_grafico(g)["ano_txt"].drop_duplicates()) == [
        "2021",
        "2022",
        "2023",
        "2024",
        "2025",
    ]


def test_a_tabela_do_pld_esperado_contra_o_contrato(at):
    e = expander(at, "Preço do contrato e PLD esperado")
    tabela = next(no.value for t, no in achatar(e) if t == "dataframe")
    assert list(tabela["Preço do contrato (R$/MWh)"]) == [
        "198,03",
        "300,50",
        "79,05",
        "92,16",
        "148,16",
    ]
    assert list(tabela["PLD esperado (R$/MWh)"]) == [
        "179,14",
        "195,28",
        "208,03",
        "190,76",
        "182,55",
    ]
    assert tabela["Contrato − esperado"].iloc[0] == "+18,89"
    assert tabela["Contrato − esperado"].iloc[2] == "−128,98"
    col = "Volume da Otimizada (× a previsão)"
    assert tabela[col].iloc[0].endswith("(meio da banda)")
    assert tabela[col].iloc[1].endswith("(mínimo)")
    assert all(x.endswith("(máximo)") for x in tabela[col].iloc[2:])


# ---------------------------------------------------------------- a banda


def test_a_ressalva_da_banda_vem_antes_do_grafico_e_o_grafico_e_de_linha(at):
    i = indice(at, "info", tx.CHAVES["sem_preco"])
    aviso = elementos(at)[i][1].value
    assert "teto" in aviso and "não uma estimativa" in aviso.replace("não é uma", "não uma")
    j = indice(at, "vega_lite_chart", "banda")
    assert i < j
    g = elementos(at)[j][1]
    s = spec(g)
    assert '"banda"' in s and '"type": "quantitative"' in s
    dados = dados_do_grafico(g)
    assert sorted(dados["banda"].unique()) == [0, 5, 10, 15]
    # a ordem das séries é a do eixo e das cores: previsão, otimização, e o efeito do volume
    ordem = json.loads(g.proto.spec)
    dominios = json.dumps(ordem, ensure_ascii=False)
    assert dominios.index("Valor da previsão") < dominios.index("Valor da otimização")
    texto_banda = elementos(at)[indice(at, "markdown", "Esperava-se mais valor da otimização")][
        1
    ].value
    assert tx.CHAVES["opcao"] in texto_banda and "refutada" in texto_banda
    assert "R\\$ 0 (banda de 0%)" in texto_banda and "R\\$ 9,7 mil (15%)" in texto_banda


def test_em_banda_zero_o_ponto_da_previsao_e_rotulado_como_efeito_do_volume(at):
    g = elementos(at)[indice(at, "vega_lite_chart", "banda")][1]
    dados = dados_do_grafico(g)
    zero = dados[dados["banda"] == 0]
    assert set(zero["serie"]) == {
        "Efeito do volume sob o diferencial de preço (não é previsão)",
        "Valor da otimização",
    }
    assert "Valor da previsão" not in set(zero["serie"])
    assert tx.CHAVES["f0"] in toda_a_tela(at)
    e = expander(at, "Detalhe da banda")
    nota = next(no.value for t, no in achatar(e) if t == "markdown")
    assert "−R\\$ 2.679,52" in nota and "+R\\$ 3.416,49" in nota and "+R\\$ 3.740,51" in nota
    assert "a precisão da previsão não entra" in nota and "apostas de sinais opostos" in nota
    tabela = next(no.value for t, no in achatar(e) if t == "dataframe")
    efeito = "Efeito do volume sob o diferencial de preço (só banda 0%)"
    zero_l = tabela[tabela["Banda"] == "0%"].iloc[0]
    assert zero_l["Valor da previsão (banda > 0)"] == "—" and zero_l[efeito] == "+R$ 3.740,51"
    dez = tabela[tabela["Banda"] == "10%"].iloc[0]
    assert dez[efeito] == "—" and dez["Valor da previsão (banda > 0)"] == "−R$ 330,10"
    assert list(tabela["Valor da otimização"]) == [
        "R$ 0,00",
        "R$ 7.469,17",
        "R$ 9.020,19",
        "R$ 9.704,63",
    ]


def test_o_detalhe_por_ano_da_banda_usa_o_mesmo_eixo(at):
    e = expander(at, "Detalhe da banda")
    graficos = [no for t, no in achatar(e) if t == "vega_lite_chart"]
    assert len(graficos) == 1
    s = spec(graficos[0])
    assert s.count('"banda"') >= 5 and '"type": "quantitative"' in s


# ---------------------------------------------------------------- sensibilidades


def test_as_sensibilidades_em_pontos_na_ordem_do_plano_e_sem_ranking(at):
    nota = elementos(at)[indice(at, "markdown", "Cada ponto muda")][1].value
    assert "uma variável por vez" in nota and tx.CHAVES["excluida"] in nota
    g = elementos(at)[indice(at, "vega_lite_chart", "Volume até 1,2× a previsão")][1]
    dados = dados_do_grafico(g, "rotulo")
    pontos = dados.drop_duplicates("rotulo")
    esperado = [tx.ROTULOS_SENSIBILIDADES[i] for i in lei.ORDEM_SENSIBILIDADES[1:]]
    assert len(pontos) == 13 and list(pontos["rotulo"]) == esperado
    assert list(pontos["rotulo"]) != list(pontos.sort_values("valor_otimizacao_rs")["rotulo"])
    assert list(pontos.loc[pontos["especulacao"], "rotulo"]) == [
        tx.ROTULOS_SENSIBILIDADES["rmax120"]
    ]
    assert f"{tx.CHAVES['especulacao']}, {tx.CHAVES['excluida']}" in toda_a_tela(at)
    base = dados_do_grafico(g, "x")  # a linha vertical do caso base
    assert round(float(base["x"].iloc[0]), 2) == 9020.19 and vis.AMBAR in spec(g)


def tabela_sens(at):
    e = expander(at, "Tabela completa das sensibilidades")
    return next(no.value for t, no in achatar(e) if t == "dataframe")


def test_a_tabela_das_sensibilidades_tem_14_linhas_na_ordem_e_a_nota_da_especulacao(at):
    t = tabela_sens(at)
    assert list(t["Variação"]) == [tx.ROTULOS_SENSIBILIDADES[i] for i in lei.ORDEM_SENSIBILIDADES]
    notas = t[t["Nota"] != ""]
    assert list(notas["Variação"]) == [tx.ROTULOS_SENSIBILIDADES["rmax120"]]
    assert notas["Nota"].iloc[0] == tx.NOTA_ESPECULATIVA
    assert t[t["Variação"] == "Caso base"]["Economia total, sem 2021"].iloc[0] == "+R$ 8.709,69"
    e = expander(at, "Tabela completa das sensibilidades")
    mds = [no.value for t_, no in achatar(e) if t_ == "markdown"]
    assert "não é ordenada por economia" in mds[0] and tx.NOTA_ARREDONDAMENTO in mds[0]
    aviso = mds[1]
    assert tx.CHAVES["excluida"] in aviso and "R\\$ 18.459,63" in aviso and "1,89%" in aviso
    assert "+R\\$ 9.690,73" in aviso and "+R\\$ 3.484,33" in aviso and "−R\\$ 558,67" in aviso
    assert "R\\$ 308 e R\\$ 487" in aviso and 'Não é "a melhor"' in aviso


# ---------------------------------------------------------------- prévia


def test_a_previa_e_um_alerta_unico_sem_economia(at):
    assert len(at.warning) == 1
    i = indice(at, "warning", tx.CHAVES["previa"])
    selo = elementos(at)[i][1].value
    assert selo.startswith(f"**{tx.CHAVES['previa']}: {tx.CHAVES['nao_e_a_decisao']}")
    assert "out/2026 a set/2027" in selo and "10/10/2026" in selo and "Sem economia" in selo
    assert "PLD esperado R\\$ 188,58/MWh contra contrato de R\\$ 246,89/MWh" in selo
    assert "contrata menos que a previsão (0,929× a previsão)" in selo
    assert tx.CHAVES["nao_garantia"] in selo and "0,1367 MWm" in selo and "0,1471 MWm" in selo
    assert "assumidos" in selo and "subestimam o regime de piso" in selo
    fim = indice(at, "subheader", tx.TITULO_LIMITACOES)
    bloco = [t for t, _ in elementos(at)[indice(at, "subheader", "Prévia") : fim]]
    assert "metric" not in bloco and "dataframe" not in bloco


def test_aviso_de_defasagem_do_manifesto_aparece_no_cabecalho(tmp_path):
    pasta = tmp_path / "dados"
    shutil.copytree(lei.DADOS, pasta)
    m = json.loads((pasta / "manifest.json").read_text())
    m["avisos_de_defasagem"] = [
        "AVISO DE DEFASAGEM: a previsão mais recente é de 2026-10, sem cenários."
    ]
    (pasta / "manifest.json").write_text(json.dumps(m))
    at = rodar(pasta)
    assert not at.exception
    assert indice(at, "warning", "AVISO DE DEFASAGEM") < primeiro(at, "metric")
    assert len(at.warning) == 2


def test_sem_previa_gravada_a_pagina_diz_isso_e_nao_quebra(tmp_path):
    pasta = tmp_path / "dados"
    shutil.copytree(lei.DADOS, pasta)
    r = pd.read_csv(pasta / "recomendacao.csv")
    r[r["tipo"] == "backtest"].to_csv(pasta / "recomendacao.csv", index=False)
    at = rodar(pasta)
    assert not at.exception
    assert any("Nenhuma prévia de produção foi gravada ainda" in i.value for i in at.info)
    assert not any(tx.CHAVES["previa"] in w.value for w in at.warning)


# ---------------------------------------------------------------- limitações, glossário, auditoria


def test_as_limitacoes_sao_5_itens_sempre_visiveis_com_o_lastro_primeiro(at):
    i = indice(at, "subheader", tx.TITULO_LIMITACOES)
    nos = elementos(at)
    assert nos[i + 1][0] == "markdown"  # direto abaixo do título, fora de qualquer expander
    corpo = nos[i + 1][1].value
    itens = re.findall(r"^\d\. ", corpo, flags=re.M)
    assert len(itens) == 5
    primeiro_item = corpo.splitlines()[0]
    assert tx.CHAVES["lastro"] in primeiro_item and "a confirmar na CCEE" in primeiro_item
    assert "piso" in primeiro_item and "teto" in primeiro_item
    assert tx.CHAVES["sem_preco"].replace("A flexibilidade", "A flexibilidade da banda") in corpo
    assert tx.CHAVES["cinco_anos"] in corpo and tx.CHAVES["portaria"] in corpo
    assert "subestimam o regime de piso prolongado" in corpo
    assert palavras(corpo) <= 120  # estimativa do relatório: ~80; medido: 114


def test_o_glossario_e_a_auditoria_estao_fechados_e_a_auditoria_e_a_ultima(at):
    glossario, auditoria = expander(at, "Glossário"), expander(at, "Auditoria")
    assert not glossario.proto.expanded and not auditoria.proto.expanded
    assert elementos(at)[-1][1] is not None
    assert indice_exp(at, "Glossário") < indice_exp(at, "Auditoria")
    for sigla in ("PLD", "MWm", "CVaR"):
        assert f"**{sigla}:**" in glossario.markdown[0].value
    assert "Contrafactual" in glossario.markdown[0].value


def test_a_auditoria_tem_hashes_placar_execucoes_e_invariancias(at):
    e = expander(at, "Auditoria")
    mds = [no.value for t, no in achatar(e) if t == "markdown"]
    info = mds[0]
    assert H_BASE in info and H_SENS in info and "51cf99b073fe" in info
    assert tx.CHAVES["uma_vez"] in info and tx.CHAVES["uma_vez_cada"] in info
    assert tx.CHAVES["placar"] in info and tx.CHAVES["h4"] in info and "docs/decisoes.md" in info
    tabelas = [no.value for t, no in achatar(e) if t == "dataframe"]
    pre = tabelas[0]
    assert len(pre) == 14 and list(pre["Execução"])[:2] == ["caso_base", "f00"]
    assert pre["Pré-registro"].iloc[0] == H_BASE and set(pre["Pré-registro"].iloc[1:]) == {H_SENS}
    assert any("5,36 MWh" in m and "6.8" in m for m in mds)
    assert len(tabelas) >= 3  # execuções, invariâncias e a prévia


# ---------------------------------------------------------------- frases-chave e posição


def test_toda_frase_chave_de_textos_py_aparece_na_pagina(at):
    tela = toda_a_tela(at)
    for nome, frase in tx.CHAVES.items():
        assert frase in tela, f"a página não mostra a frase-chave {nome!r}: {frase!r}"


def test_nenhum_numero_aparece_antes_da_ressalva_dele(at):
    nos = elementos(at)
    pos = {
        "cabecalho": indice(at, "caption", H_BASE[:7]),
        "frase": indice(at, "info", "Em 5 anos simulados"),
        "cartoes": primeiro(at, "metric"),
        "ganho": indice(at, "caption", "Faixa cinza"),
        "por_que": indice(at, "markdown", tx.CHAVES["reversao"]),
        "banda": indice(at, "info", tx.CHAVES["sem_preco"]),
        "sens": indice(at, "markdown", "Cada ponto muda"),
        "previa": indice(at, "warning", tx.CHAVES["previa"]),
    }
    assert list(pos.values()) == sorted(pos.values())
    # a ressalva do gráfico vem antes dele
    assert pos["ganho"] < indice(at, "vega_lite_chart", "ano_txt")
    assert pos["banda"] < indice(at, "vega_lite_chart", "banda")
    assert pos["sens"] < indice(at, "vega_lite_chart", "Volume até 1,2×")
    # nenhuma tabela e nenhum gráfico antes do cabeçalho e da frase
    assert nos[0][0] == "title"
    assert pos["frase"] < min(
        i for i, (t, _) in enumerate(nos) if t in ("dataframe", "vega_lite_chart")
    )


# ---------------------------------------------------------------- redesenho: orçamento e regras


def test_orcamento_de_palavras_e_de_caixas(at):
    visiveis = palavras_visiveis(at.main)
    assert visiveis <= ORCAMENTO_DE_PALAVRAS, visiveis  # antes: 1.747
    assert {t for t, _ in elementos(at)}.isdisjoint({"error", "success", "exception"})
    assert len(at.warning) <= 1  # âmbar: só a prévia
    assert len(at.info) <= 2 and len(at.subheader) <= 7
    # tabelas só dentro de expanders
    fora = [t for t, _ in _fora_dos_expanders(at.main)]
    assert "dataframe" not in fora


def _fora_dos_expanders(bloco, saida=None):
    saida = [] if saida is None else saida
    for k in sorted(bloco.children):
        n = bloco.children[k]
        if n.type == "expander":
            saida.append((n.type, n))
        elif getattr(n, "children", None):
            _fora_dos_expanders(n, saida)
        else:
            saida.append((n.type, n))
    return saida


SEM_ESCAPE = re.compile(r"(?<!\\)\$")


def test_nenhum_dolar_sem_escape_no_markdown(at):
    """O Streamlit trata o texto entre dois `$` como LaTeX: todo `R$` em Markdown leva `\\$`."""
    for t, no in elementos(at):
        if t in ("markdown", "caption", "info", "warning", "subheader", "title"):
            assert not SEM_ESCAPE.search(no.value), no.value[:120]
        elif t == "metric":
            assert not SEM_ESCAPE.search(no.label + (no.proto.help or ""))
        elif t == "expander":
            assert not SEM_ESCAPE.search(no.label)


def test_a_funcao_reais_escapa_o_dolar_so_quando_pedido():
    assert vis.reais(9020.19) == "R$ 9.020,19" and vis.reais(9020.19, md=True) == "R\\$ 9.020,19"
    assert vis.reais(-330.1, sinal=True, md=True) == "−R\\$ 330,10"
    assert vis.reais_curto(8690.1, md=True) == "R\\$ 8,7 mil" and vis.reais_curto(0.0) == "R$ 0"
    assert vis.ano(2021.0) == "2021"


JARGAO = (
    "P_t",
    "r*",
    "rmax120",
    "config_hash",
    "execucao_id",
    "f=0.0",
    "f00",
    "caso_base",
    "ex-ante",
    "E[PLD]",
    "CVaR95",
    "contrafactual",
    "ingênua",
    "pontual",
    "ingenua",
)


def test_nenhum_jargao_do_codigo_fora_da_auditoria_e_do_glossario(at):
    tela = antes_do_glossario(at)
    achados = [j for j in JARGAO if re.search(rf"(?<![\w*]){re.escape(j)}(?!\*)", tela)]
    assert not achados, achados
    # (as siglas inevitáveis PLD, MWm e CVaR ficam, com ajuda no ponto de uso e no glossário)
    assert "Contrafactual" in expander(at, "Glossário").markdown[0].value
    assert "contrafactual" not in toda_a_tela(at).replace("Contrafactual", "")


def test_so_as_cores_da_paleta_nos_graficos(at):
    for t, no in elementos(at):
        if t == "vega_lite_chart":
            cores = {c.lower() for c in re.findall(r"#[0-9a-fA-F]{6}", spec(no))}
            assert cores <= {c.lower() for c in vis.PALETA} | {"#ffffff"}, cores


def test_o_tema_esta_no_config_toml_com_a_paleta():
    cfg = tomllib.loads((RAIZ / ".streamlit" / "config.toml").read_text())
    tema = cfg["theme"]
    assert tema["primaryColor"] == vis.PETROLEO and tema["orangeColor"] == vis.AMBAR
    assert {c.lower() for c in tema["chartCategoricalColors"]} <= {c.lower() for c in vis.PALETA}
    assert cfg["browser"]["gatherUsageStats"] is False


# ---------------------------------------------------------------- o app que reúne as páginas


def test_o_app_com_navegacao_carrega_a_pagina_de_decisao():
    at = AppTest.from_file(str(RAIZ / "dashboard" / "app.py"), default_timeout=90)
    at.run()
    assert not at.exception
    assert at.title[0].value == "Decisão de contrato" and len(at.metric) == 3


def test_a_pagina_nao_le_nada_fora_do_snapshot(at):
    fonte = (RAIZ / "dashboard" / "paginas" / "decisao.py").read_text()
    assert "docs/" not in fonte.split('"""', 2)[2]
    assert "bigquery" not in fonte.lower()


# ---------------------------------------------------------------- partes e total, ao centavo

VALOR = re.compile(r"([+−-]?)R\\?\$ ([\d.]+),(\d{2})")


def centavos(texto_: str) -> int:
    """O primeiro valor em R$ de um texto, em centavos inteiros ('−R$ 182,43' -> -18243)."""
    m = VALOR.search(texto_)
    assert m, texto_
    v = int(m.group(2).replace(".", "")) * 100 + int(m.group(3))
    return -v if m.group(1) in ("−", "-") else v


def dentro(at, rotulo: str):
    e = expander(at, rotulo)
    return achatar(e)


def tabela_em(at, rotulo: str) -> pd.DataFrame:
    return next(no.value for t, no in dentro(at, rotulo) if t == "dataframe")


def legenda_apos_tabela(at, rotulo: str) -> str:
    nos = dentro(at, rotulo)
    i = next(n for n, (t, _) in enumerate(nos) if t == "dataframe")
    return nos[i + 1][1].value


def test_a_concentracao_soma_ao_centavo(at):
    """Aqui não há diferença de arredondamento: 9.202,62 − 182,43 + 0,00 = 9.020,19."""
    legenda = legenda_apos_tabela(at, "Números por ano")
    somam = centavos(re.search(r"2022 \+ 2025 = (\S+ \S+ \S+)", legenda).group(1))
    outros = centavos(re.search(r"2023 \+ 2024 = (\S+ \S+ \S+)", legenda).group(1))
    total = centavos(re.search(r"de (R\\\$ [\d.,]+)\)", legenda).group(1))
    assert (somam, outros, total) == (920262, -18243, 902019)
    assert somam + outros + 0 == total


def test_a_tabela_por_ano_soma_um_centavo_acima_do_total_e_a_legenda_explica(at):
    """9.020,19 − 330,10 = 8.690,09, mas o total exato é 8.690,10; e a soma dos 5 anos exibidos
    (9.020,20) difere do total (9.020,19): a nota de arredondamento está junto da tabela."""
    t = tabela_em(at, "Números por ano")
    assert sum(centavos(v) for v in t["Valor da otimização"]) == 902020
    assert tx.NOTA_ARREDONDAMENTO in legenda_apos_tabela(at, "Números por ano")
    for _, linha in t.iterrows():
        ing, pont, otim = (
            centavos(linha[f"Custo, {n}"]) for n in (vis.ANO_ANTERIOR, vis.PREVISAO, vis.OTIMIZADA)
        )
        assert abs((ing - pont) - centavos(linha["Valor da previsão"])) <= 1, linha["Ano"]
        assert abs((pont - otim) - centavos(linha["Valor da otimização"])) <= 1, linha["Ano"]


def test_a_tabela_da_banda_fecha_com_a_nota(at):
    t = tabela_em(at, "Detalhe da banda")
    efeito = "Efeito do volume sob o diferencial de preço (só banda 0%)"
    for _, linha in t.iterrows():
        previsao = (
            linha[efeito] if linha["Banda"] == "0%" else linha["Valor da previsão (banda > 0)"]
        )
        dif = (
            centavos(previsao)
            + centavos(linha["Valor da otimização"])
            - centavos(linha["Economia total"])
        )
        assert abs(dif) <= 1, linha["Banda"]
    assert legenda_apos_tabela(at, "Detalhe da banda") == tx.NOTA_ARREDONDAMENTO


def test_a_tabela_de_sensibilidades_fecha_ate_um_centavo_e_o_texto_acima_explica(at):
    for _, linha in tabela_sens(at).iterrows():
        soma = centavos(linha["Valor da previsão"]) + centavos(linha["Valor da otimização"])
        assert abs(soma - centavos(linha["Economia total"])) <= 1, linha["Variação"]
    assert tx.NOTA_ARREDONDAMENTO in tx.NOTA_SENSIBILIDADES_TABELA


def test_a_tabela_do_pld_esperado_fecha_ate_um_centavo_e_a_legenda_explica(at):
    """Contrato − esperado: em 2022 a conta dos valores exibidos dá 105,22 e o valor exato,
    arredondado uma vez, é 105,21; a legenda explica."""
    t = tabela_em(at, "Preço do contrato e PLD esperado")

    def c(txt):
        return round(
            float(txt.replace(".", "").replace(",", ".").replace("−", "-").replace("+", "")) * 100
        )

    dif = {
        linha["Ano"]: c(linha["Preço do contrato (R$/MWh)"])
        - c(linha["PLD esperado (R$/MWh)"])
        - c(linha["Contrato − esperado"])
        for _, linha in t.iterrows()
    }
    assert all(abs(v) <= 1 for v in dif.values()) and dif["2022"] == 1
    assert legenda_apos_tabela(at, "Preço do contrato e PLD esperado") == tx.LEGENDA_D3
    assert tx.NOTA_ARREDONDAMENTO in tx.LEGENDA_D3
