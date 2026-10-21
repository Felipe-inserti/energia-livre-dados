"""Gráficos Altair do dashboard: funções puras `DataFrame -> alt.Chart`.

Regras (plano_sprint6c.md, seção 4, e o redesenho): barras de custo e de economia começam em ZERO;
sem eixo duplo; só as cores de `visual` (petróleo = Otimizada, cinza = comparações, âmbar = só
alerta); anos e eixos em formato brasileiro; valores sempre com o rótulo. Cada função recebe só o
DataFrame já filtrado (a camada de dados tira os meses incompletos) e o `chart.data` é inspecionável
em teste.
"""

import altair as alt
import pandas as pd

from dashboard import calculos as cal
from dashboard import visual as vis

AZUL = vis.PETROLEO  # (a página Panorama ainda usa estes nomes)
CINZA = vis.CINZA
CORES_ESTRATEGIA = {
    "ingenua": vis.CINZA_CLARO,
    "pontual": vis.CINZA_ESCURO,
    "otimizada": vis.PETROLEO,
}
ALTURA = 320

# o Altair/Vega não aceita `formatLocale` pelo st.altair_chart: troca a vírgula de milhar por ponto
_MILHAR_BR = "replace(format(datum.value, ',.0f'), regexp(',', 'g'), '.')"


def eixo_reais(titulo: str, marcas: int | None = None) -> alt.Axis:
    """Eixo em R$; `marcas` limita o número de marcas (dica ao Vega, que arredonda para valores
    redondos: sai no máximo esse número, nunca um eixo cheio de rótulos)."""
    if marcas is None:
        return alt.Axis(title=titulo, labelExpr=_MILHAR_BR)
    return alt.Axis(title=titulo, labelExpr=_MILHAR_BR, tickCount=marcas)


# ---------------------------------------------------------------- decisão


def ganho_por_ano(anos: pd.DataFrame) -> alt.Chart:
    """Valor da otimização por ano; 2022 e 2025 em petróleo, os demais em cinza; valor na barra;
    faixa de fundo nos anos em que o consumidor ainda não podia migrar (2021–2023)."""
    d = anos.assign(
        ano_txt=anos["ano"].map(vis.ano),
        destaque=anos["ano"].isin(cal.ANOS_DESTAQUE),
        valor_texto=anos["valor_otimizacao_rs"].map(lambda v: vis.reais(v, 0)),
        faixa="2021–2023: ainda não podia migrar",
    )
    teto = float(max(d["valor_otimizacao_rs"].max(), 0)) * 1.18
    piso = float(min(d["valor_otimizacao_rs"].min(), 0)) * 1.5
    escala = alt.Scale(domain=[piso, teto], zero=True)
    ordem = list(d["ano_txt"])
    x = alt.X("ano_txt:N", sort=ordem, title=None, axis=alt.Axis(labelAngle=0))
    faixa = (
        alt.Chart(d[d["nao_elegivel"]].assign(y0=piso, y1=teto))
        .mark_bar(color=vis.CINZA_CLARO, opacity=0.25, width={"band": 1})
        .encode(x=x, y=alt.Y("y0:Q", scale=escala), y2="y1:Q", tooltip=["faixa:N"])
    )
    barras = (
        alt.Chart(d)
        .mark_bar()
        .encode(
            x=x,
            y=alt.Y("valor_otimizacao_rs:Q", scale=escala, axis=eixo_reais("R$ de custo evitado")),
            color=alt.condition(alt.datum.destaque, alt.value(vis.PETROLEO), alt.value(vis.CINZA)),
            tooltip=[
                alt.Tooltip("ano_txt:N", title="Ano"),
                alt.Tooltip("valor_texto:N", title="Valor da otimização"),
            ],
        )
    )
    rotulos = [
        alt.Chart(d[sel])
        .mark_text(dy=dy, fontSize=12, color=vis.TEXTO)
        .encode(x=x, y="valor_otimizacao_rs:Q", text="valor_texto:N")
        for sel, dy in ((d["valor_otimizacao_rs"] >= 0, -8), (d["valor_otimizacao_rs"] < 0, 14))
    ]
    return (faixa + barras + rotulos[0] + rotulos[1]).properties(height=ALTURA)


def preco_x_esperado(d3: pd.DataFrame) -> alt.Chart:
    """Por ano, o preço do contrato e o PLD esperado pelos cenários, ligados por um traço."""
    d = d3.assign(ano_txt=d3["ano"].map(vis.ano))
    ordem = list(d["ano_txt"])
    x = alt.X("ano_txt:N", sort=ordem, title=None, axis=alt.Axis(labelAngle=0))
    ligacao = (
        alt.Chart(d)
        .mark_rule(color=vis.CINZA_CLARO, strokeWidth=3)
        .encode(x=x, y="preco_contrato_rs_mwh:Q", y2="pld_esperado_rs_mwh:Q")
    )
    pontos = (
        alt.Chart(d)
        .transform_fold(["preco_contrato_rs_mwh", "pld_esperado_rs_mwh"], as_=["serie_id", "valor"])
        .transform_calculate(
            serie="datum.serie_id == 'preco_contrato_rs_mwh' ? 'Preço do contrato' : "
            "'PLD esperado pelos cenários'"
        )
        .mark_point(filled=True, size=110, opacity=1)
        .encode(
            x=x,
            y=alt.Y(
                "valor:Q",
                scale=alt.Scale(zero=True),
                axis=alt.Axis(title="R$/MWh", labelExpr=_MILHAR_BR),
            ),
            color=alt.Color(
                "serie:N",
                scale=alt.Scale(
                    domain=["Preço do contrato", "PLD esperado pelos cenários"],
                    range=[vis.CINZA_ESCURO, vis.CINZA],
                ),
                legend=alt.Legend(title=None, orient="bottom", labelLimit=400),
            ),
            tooltip=[alt.Tooltip("ano_txt:N", title="Ano"), alt.Tooltip("valor:Q", format=",.2f")],
        )
    )
    return (ligacao + pontos).properties(height=ALTURA // 1.4)


SERIE_PREVISAO = "Valor da previsão"
SERIE_OTIMIZACAO = "Valor da otimização"
SERIE_F0 = "Ganho por contratar acima ou abaixo da previsão"


def _longo_da_banda(t: pd.DataFrame, extra: list[str] | None = None) -> pd.DataFrame:
    """Uma linha por (banda, série): em banda 0 a previsão NÃO é valor da previsão (o contrato é
    fixo e todo desvio vai ao PLD): vira a série 'efeito do volume', marcada à parte."""
    extra = extra or []
    linhas = []
    for _, r in t.iterrows():
        banda = round(float(r["f"]) * 100)
        base = {c: r[c] for c in extra}
        zero = banda == 0
        linhas.append(
            {
                **base,
                "banda": banda,
                "serie": SERIE_F0 if zero else SERIE_PREVISAO,
                "valor_rs": float(r["valor_previsao_rs"]),
            }
        )
        linhas.append(
            {
                **base,
                "banda": banda,
                "serie": SERIE_OTIMIZACAO,
                "valor_rs": float(r["valor_otimizacao_rs"]),
            }
        )
    d = pd.DataFrame(linhas)
    d["valor_texto"] = d["valor_rs"].map(lambda v: vis.reais_curto(v))
    return d


_SERIES_DA_BANDA = [SERIE_PREVISAO, SERIE_OTIMIZACAO, SERIE_F0]
_ESCALA_BANDA = alt.Scale(domain=_SERIES_DA_BANDA, range=[vis.CINZA, vis.PETROLEO, vis.CINZA])
# Preenchimento do ponto: só a série F0 é vazada (branca). É uma ESCALA própria (e não uma condição
# `alt.condition`) para a legenda também mostrar o símbolo vazado: a legenda só enxerga escalas.
_ESCALA_PREENCHIMENTO = alt.Scale(domain=_SERIES_DA_BANDA, range=[vis.CINZA, vis.PETROLEO, "white"])


def _camadas_da_banda(
    d: pd.DataFrame, com_rotulos: bool, legenda: bool = True, largura: int | None = None
) -> alt.LayerChart:
    x = alt.X(
        "banda:Q",
        title="Banda (± do consumo previsto)",
        scale=alt.Scale(domain=[-1, 16], nice=False),
        axis=alt.Axis(values=[0, 5, 10, 15], labelExpr="datum.value + '%'"),
    )
    legend = alt.Legend(title=None, orient="bottom", columns=1, labelLimit=520) if legenda else None
    cor = alt.Color("serie:N", scale=_ESCALA_BANDA, legend=legend)
    # a mesma legenda nos três canais (linha, contorno e preenchimento) funde num só símbolo
    preenchimento = alt.Fill("serie:N", scale=_ESCALA_PREENCHIMENTO, legend=legend)
    y = alt.Y("valor_rs:Q", axis=eixo_reais("R$ de custo evitado"))
    linhas = alt.Chart(d).mark_line(strokeWidth=2.5).encode(x=x, y=y, color=cor, detail="serie:N")
    pontos = (
        alt.Chart(d)
        .mark_point(size=90, strokeWidth=2)
        .encode(
            x=x,
            y=y,
            # em banda 0% o ponto da previsão é vazado (e a legenda também): não é valor da previsão
            stroke=cor,
            fill=preenchimento,
            tooltip=[
                alt.Tooltip("serie:N", title="Série"),
                alt.Tooltip("banda:Q", title="Banda (%)"),
                alt.Tooltip("valor_texto:N", title="Valor"),
            ],
        )
    )
    camadas = linhas + pontos
    if com_rotulos:
        rotulos = (
            alt.Chart(d)
            .mark_text(dy=-12, fontSize=11, color=vis.TEXTO)
            .encode(x=x, y=y, text="valor_texto:N")
        )
        camadas = camadas + rotulos
    return camadas.properties(width=largura) if largura else camadas


def banda_linhas(tabela_f: pd.DataFrame) -> alt.LayerChart:
    """UM gráfico: x = banda (0 a 15%), uma linha para o valor da previsão e outra para o da
    otimização. Em 0% o ponto da previsão é vazado e rotulado como efeito do volume."""
    return _camadas_da_banda(_longo_da_banda(tabela_f), com_rotulos=True).properties(height=ALTURA)


def banda_por_ano(por_ano: pd.DataFrame) -> alt.HConcatChart:
    """O mesmo gráfico, um painel por ano (detalhe, dentro de um expander); mesmo eixo: a banda."""
    d = _longo_da_banda(por_ano, extra=["ano"])
    anos = sorted(d["ano"].unique())
    paineis = [
        _camadas_da_banda(
            d[d["ano"] == a], com_rotulos=False, legenda=(a == anos[-1]), largura=150
        ).properties(height=190, title=vis.ano(a))
        for a in anos
    ]
    return alt.hconcat(*paineis).resolve_scale(y="shared")


MARCAS_SENSIBILIDADES = 6  # o eixo x tem rótulos largos (R$ 10.000); mais que isso se sobrepõe


def sensibilidades_pontos(sens: pd.DataFrame, ordem: list[str], base_rs: float) -> alt.LayerChart:
    """Gráfico de pontos: uma linha por variação (na ordem declarada, nunca por valor), o valor da
    otimização no eixo x e a linha vertical do caso base. A especulação é âmbar e vazada."""
    # só as colunas que o gráfico usa: os ids internos (sens_id, parametro) não vão ao navegador
    d = sens[["rotulo", "valor_otimizacao_rs", "especulacao", "anotacao"]].assign(
        valor_texto=sens["valor_otimizacao_rs"].map(lambda v: vis.reais_curto(v)),
    )
    y = alt.Y("rotulo:N", sort=ordem, title=None, axis=alt.Axis(labelLimit=330))
    x = alt.X(
        "valor_otimizacao_rs:Q",
        title="Valor da otimização em 5 anos (R$)",
        scale=alt.Scale(zero=True),
        axis=eixo_reais("Valor da otimização em 5 anos (R$)", marcas=MARCAS_SENSIBILIDADES),
    )
    linha_base = (
        alt.Chart(pd.DataFrame({"x": [base_rs], "texto": ["caso base"]}))
        .mark_rule(color=vis.CINZA_ESCURO, strokeDash=[5, 4])
        .encode(x="x:Q")
    )
    pontos = (
        alt.Chart(d)
        .mark_point(filled=True, size=110, opacity=1)
        .encode(
            x=x,
            y=y,
            color=alt.condition(
                alt.datum.especulacao, alt.value(vis.AMBAR), alt.value(vis.PETROLEO)
            ),
            fillOpacity=alt.condition(alt.datum.especulacao, alt.value(0), alt.value(1)),
            stroke=alt.condition(
                alt.datum.especulacao, alt.value(vis.AMBAR), alt.value(vis.PETROLEO)
            ),
            tooltip=[
                alt.Tooltip("rotulo:N", title="Variação"),
                alt.Tooltip("valor_texto:N", title="Valor da otimização"),
            ],
        )
    )
    normais = (
        alt.Chart(d[~d["especulacao"]])
        .mark_text(align="left", dx=10, fontSize=11, color=vis.TEXTO)
        .encode(x="valor_otimizacao_rs:Q", y=y, text="valor_texto:N")
    )
    especulativas = (
        alt.Chart(d[d["especulacao"]])
        .mark_text(align="right", dx=-12, fontSize=11, color=vis.AMBAR)
        .encode(x="valor_otimizacao_rs:Q", y=y, text="anotacao:N")
    )
    return (linha_base + pontos + normais + especulativas).properties(height=26 * len(d) + 40)


# ---------------------------------------------------------------- panorama


# um rótulo de ano a cada 2 anos: a série começa em 2000/2002 e rótulos de todo ano se sobrepõem
_EIXO_ANOS = alt.Axis(format="%Y", tickCount={"interval": "year", "step": 2}, labelOverlap=True)

SERIE_ORIGINAL = "Original (ONS)"
SERIE_RECONSTRUIDA = "Reconstruída"


def carga(df: pd.DataFrame, quebra: pd.Timestamp | None = None) -> alt.LayerChart:
    """Carga mensal do SE/CO: a série original do ONS e a reconstruída (mesma definição em todo o
    período). Com `quebra`, uma linha vertical marca o mês do degrau do tipo III, com o texto."""
    longo = df.melt(
        id_vars="mes",
        value_vars=["carga_original_mwmed", "carga_ajustada_reconstruida_mwmed"],
        var_name="serie",
        value_name="mwm",
    ).dropna(subset=["mwm"])
    longo["serie"] = longo["serie"].map(
        {
            "carga_original_mwmed": SERIE_ORIGINAL,
            "carga_ajustada_reconstruida_mwmed": SERIE_RECONSTRUIDA,
        }
    )
    linhas = (
        alt.Chart(longo)
        .mark_line()
        .encode(
            x=alt.X("mes:T", title=None, axis=_EIXO_ANOS),
            y=alt.Y("mwm:Q", title=None, scale=alt.Scale(zero=False), axis=eixo_mwm()),
            color=alt.Color(
                "serie:N",
                scale=alt.Scale(
                    domain=[SERIE_ORIGINAL, SERIE_RECONSTRUIDA], range=[vis.CINZA, vis.PETROLEO]
                ),
                legend=alt.Legend(title=None, orient="bottom"),
            ),
            tooltip=[
                alt.Tooltip("mes:T", title="Mês", format="%m/%Y"),
                alt.Tooltip("serie:N", title="Série"),
                alt.Tooltip("mwm:Q", title="MWm", format=",.0f"),
            ],
        )
    )
    if quebra is None:
        return linhas.properties(height=ALTURA)
    marca = pd.DataFrame(
        {
            "mes": [quebra],
            "texto": [f"quebra do tipo III ({cal.mes_por_extenso(quebra)})"],
        }
    )
    regra = alt.Chart(marca).mark_rule(color=vis.CINZA_ESCURO, strokeDash=[4, 3]).encode(x="mes:T")
    rotulo = (
        alt.Chart(marca)
        .mark_text(align="left", baseline="top", dx=5, dy=2, fontSize=11, color=vis.TEXTO)
        .encode(x="mes:T", y=alt.value(0), text="texto:N")
    )
    return (linhas + regra + rotulo).properties(height=ALTURA)


SERIE_PLD_SEMANAL = "PLD até 2020: semanal, agregado por mês"
SERIE_PLD_PONDERADO = "PLD de 2021 em diante: ponderado pelo consumo"
SERIE_PISO = "Piso do ano"
SERIE_TETO = "Teto estrutural do ano"


def pld(df: pd.DataFrame) -> alt.Chart:
    """PLD mensal do SE em R$/MWh, a partir de zero. São DUAS contas (semanal até dez/2020,
    ponderado pelo consumo depois), em cores diferentes e sem ligar uma à outra; o piso e o teto
    estrutural (só de 2021 em diante) vão tracejados."""
    nomes = {"semanal": SERIE_PLD_SEMANAL, "ponderado": SERIE_PLD_PONDERADO}
    pld_ = df.assign(serie=df["fonte"].map(nomes), valor=df["pld_rs_mwh"])
    piso = df.assign(serie=SERIE_PISO, valor=df["piso_rs_mwh"])
    teto = df.assign(serie=SERIE_TETO, valor=df["teto_estrutural_rs_mwh"])
    longo = pd.concat([pld_, piso, teto], ignore_index=True).dropna(subset=["valor"])
    longo = longo[["mes", "serie", "valor"]]
    dominio = [SERIE_PLD_SEMANAL, SERIE_PLD_PONDERADO, SERIE_PISO, SERIE_TETO]
    return (
        alt.Chart(longo)
        .mark_line()
        .encode(
            x=alt.X("mes:T", title=None, axis=_EIXO_ANOS),
            y=alt.Y("valor:Q", title="PLD mensal do SE (R$/MWh)", scale=alt.Scale(zero=True)),
            color=alt.Color(
                "serie:N",
                scale=alt.Scale(
                    domain=dominio,
                    range=[vis.CINZA_ESCURO, vis.PETROLEO, vis.CINZA, vis.CINZA],
                ),
                legend=alt.Legend(title=None, orient="bottom", columns=1, labelLimit=520),
            ),
            strokeDash=alt.StrokeDash(
                "serie:N",
                scale=alt.Scale(domain=dominio, range=[[1, 0], [1, 0], [4, 3], [4, 3]]),
                legend=alt.Legend(title=None, orient="bottom", columns=1, labelLimit=520),
            ),
            detail="serie:N",
            tooltip=[
                alt.Tooltip("mes:T", title="Mês", format="%m/%Y"),
                alt.Tooltip("serie:N", title="Série"),
                alt.Tooltip("valor:Q", title="R$/MWh", format=",.2f"),
            ],
        )
        .properties(height=ALTURA)
    )


def consumo(df: pd.DataFrame) -> alt.Chart:
    return (
        alt.Chart(df)
        .mark_bar(color=AZUL)
        .encode(
            x=alt.X("mes:T", title=None),
            y=alt.Y(
                "consumo_mwh:Q", title="Consumo do exemplo (MWh/mês)", scale=alt.Scale(zero=True)
            ),
            tooltip=["mes:T", "consumo_mwh:Q", "horas:Q"],
        )
        .properties(height=ALTURA // 1.5)
    )


# ---------------------------------------------------------------- previsão

NOME_REAL = "Carga real"
NOME_MODELO = "Modelo"
NOME_COMPARACAO = vis.MESMO_MES  # o modelo de comparação; NÃO é a estratégia "Ano anterior"
_ESCALA_PREVISAO = alt.Scale(
    domain=[NOME_REAL, NOME_MODELO, NOME_COMPARACAO],
    range=[vis.CINZA_ESCURO, vis.PETROLEO, vis.CINZA],
)


def eixo_mwm(titulo: str = "Carga SE/CO (MWm)") -> alt.Axis:
    return alt.Axis(title=titulo, labelExpr=_MILHAR_BR)


def real_x_previsto(previsto: pd.DataFrame) -> alt.Chart:
    """Carga real, modelo e comparação nos meses do teste final (previsões feitas em dezembro, 12
    meses à frente). Uma linha por ano: a previsão recomeça a cada dezembro."""
    nomes = {"real": NOME_REAL, "modelo": NOME_MODELO, "comparacao": NOME_COMPARACAO}
    d = previsto.melt(
        id_vars=["alvo", "ano"], value_vars=list(nomes), var_name="serie", value_name="mwm"
    )
    d["serie"] = d["serie"].map(nomes)
    return (
        alt.Chart(d)
        .mark_line(strokeWidth=2)
        .encode(
            x=alt.X("alvo:T", title=None, axis=alt.Axis(format="%Y", tickCount="year")),
            y=alt.Y("mwm:Q", scale=alt.Scale(zero=False), axis=eixo_mwm()),
            color=alt.Color(
                "serie:N",
                scale=_ESCALA_PREVISAO,
                legend=alt.Legend(title=None, orient="bottom", labelLimit=320),
            ),
            strokeDash=alt.condition(
                alt.datum.serie == NOME_COMPARACAO, alt.value([5, 3]), alt.value([1, 0])
            ),
            detail=alt.Detail("ano:N"),
            tooltip=[
                alt.Tooltip("alvo:T", title="Mês", format="%m/%Y"),
                alt.Tooltip("serie:N", title="Série"),
                alt.Tooltip("mwm:Q", title="MWm", format=",.0f"),
            ],
        )
        .properties(height=ALTURA)
    )


def erro_por_ano(mape: pd.DataFrame) -> alt.Chart:
    """MAPE de cada ano, modelo e comparação, com o valor na barra (o modelo perde em 2025)."""
    nomes = {"modelo": NOME_MODELO, "comparacao": NOME_COMPARACAO}
    d = mape.assign(
        ano_txt=mape["ano"].map(vis.ano),
        serie=mape["serie"].map(nomes),
        texto=mape["mape_pct"].map(lambda v: f"{cal.numero(v, 1)}%"),
    )
    ordem = list(dict.fromkeys(d["ano_txt"]))
    x = alt.X("ano_txt:N", sort=ordem, title=None, axis=alt.Axis(labelAngle=0))
    cor = alt.Color(
        "serie:N",
        scale=alt.Scale(domain=[NOME_MODELO, NOME_COMPARACAO], range=[vis.PETROLEO, vis.CINZA]),
        legend=alt.Legend(title=None, orient="bottom", labelLimit=320),
    )
    barras = (
        alt.Chart(d)
        .mark_bar()
        .encode(
            x=x,
            xOffset="serie:N",
            y=alt.Y(
                "mape_pct:Q", scale=alt.Scale(zero=True), axis=alt.Axis(title="Erro médio (%)")
            ),
            color=cor,
            tooltip=[
                alt.Tooltip("ano_txt:N", title="Ano"),
                alt.Tooltip("serie:N", title="Série"),
                alt.Tooltip("texto:N", title="Erro médio"),
            ],
        )
    )
    rotulos = (
        alt.Chart(d)
        .mark_text(dy=-6, fontSize=11, color=vis.TEXTO)
        .encode(x=x, xOffset="serie:N", y="mape_pct:Q", text="texto:N")
    )
    return (barras + rotulos).properties(height=ALTURA // 1.3)


def cobertura_por_horizonte(df: pd.DataFrame) -> alt.LayerChart:
    """`df`: valor (horizonte), cobertura80_pct e cobertura95_pct; tracejado = o prometido."""
    longo = df.melt(
        id_vars="valor",
        value_vars=["cobertura80_pct", "cobertura95_pct"],
        var_name="nivel",
        value_name="cobertura",
    )
    longo["nivel"] = longo["nivel"].map(
        {"cobertura80_pct": "intervalo de 80%", "cobertura95_pct": "intervalo de 95%"}
    )
    prometido = pd.DataFrame({"y": [80, 95]})
    ref = alt.Chart(prometido).mark_rule(color=vis.CINZA, strokeDash=[4, 3]).encode(y="y:Q")
    linhas = (
        alt.Chart(longo)
        .mark_line(point=True)
        .encode(
            x=alt.X("valor:O", title="Meses à frente", axis=alt.Axis(labelAngle=0)),
            y=alt.Y(
                "cobertura:Q",
                title="Cobertura observada (%) — tracejado: o prometido",
                scale=alt.Scale(domain=[50, 100]),
            ),
            color=alt.Color(
                "nivel:N",
                scale=alt.Scale(
                    domain=["intervalo de 80%", "intervalo de 95%"],
                    range=[vis.PETROLEO, vis.CINZA_ESCURO],
                ),
                legend=alt.Legend(title=None, orient="bottom"),
            ),
            tooltip=["valor:O", "nivel:N", alt.Tooltip("cobertura:Q", format=".1f")],
        )
    )
    return (linhas + ref).properties(height=ALTURA // 1.3)


def previsao_producao(previsao: pd.DataFrame, historia: pd.DataFrame) -> alt.LayerChart:
    """Os próximos 12 meses com as faixas de 80% e 95% e a carga ajustada dos últimos meses.

    Sem texto dentro do gráfico: o que cada faixa cobriu no teste final vem na legenda abaixo
    (`textos_previsao.legenda_das_faixas`), para nada ficar por cima das linhas."""
    # só as colunas que o gráfico usa (calibração e série ficam na auditoria)
    previsao = previsao[
        ["mes_alvo", "previsao_mwmed", "p025_mwmed", "p10_mwmed", "p90_mwmed", "p975_mwmed"]
    ]
    historia = historia[["mes", "carga_ajustada_reconstruida_mwmed"]]
    base = alt.Chart(previsao).encode(
        x=alt.X("mes_alvo:T", title=None, axis=alt.Axis(format="%m/%Y"))
    )
    f95 = base.mark_area(opacity=0.15, color=vis.PETROLEO).encode(
        y=alt.Y("p025_mwmed:Q", scale=alt.Scale(zero=False), axis=eixo_mwm()), y2="p975_mwmed:Q"
    )
    f80 = base.mark_area(opacity=0.30, color=vis.PETROLEO).encode(y="p10_mwmed:Q", y2="p90_mwmed:Q")
    centro = base.mark_line(color=vis.PETROLEO, strokeWidth=2.5).encode(
        y="previsao_mwmed:Q",
        tooltip=[
            alt.Tooltip("mes_alvo:T", title="Mês", format="%m/%Y"),
            alt.Tooltip("previsao_mwmed:Q", title="Previsão (MWm)", format=",.0f"),
        ],
    )
    real = (
        alt.Chart(historia)
        .mark_line(color=vis.CINZA_ESCURO)
        .encode(
            x="mes:T",
            y="carga_ajustada_reconstruida_mwmed:Q",
            tooltip=[
                alt.Tooltip("mes:T", title="Mês", format="%m/%Y"),
                alt.Tooltip(
                    "carga_ajustada_reconstruida_mwmed:Q", title="Real (MWm)", format=",.0f"
                ),
            ],
        )
    )
    return (real + f95 + f80 + centro).properties(height=ALTURA)


# ---------------------------------------------------------------- saúde


_TIPO_CURTO = {"scheduled": "ag.", "manual": "man."}  # no eixo; a legenda da página explica


def _rotulo_da_execucao(inicio: pd.Timestamp, tipo: str) -> str:
    """'06/10 21h57 · ag.': curto para as barras caberem sem esconder rótulo. Os minutos ficam
    porque há execuções manuais na mesma hora (um rótulo repetido fundiria duas barras)."""
    return (
        f"{inicio.day:02d}/{inicio.month:02d} {inicio.hour:02d}h{inicio.minute:02d}"
        f" · {_TIPO_CURTO.get(tipo, tipo)}"
    )


def duracao_das_execucoes(runs: pd.DataFrame, ausentes: list[pd.Timestamp]) -> alt.LayerChart:
    """Uma barra por execução da DAG, da mais antiga à mais recente, sempre a partir de zero.

    `runs` vem de `cal.marcar_falhas`. A falha se vê por símbolo e texto ("✕ falha"), não por cor
    nova: a barra fica cinza-escura. Cada horário agendado sem execução (`ausentes`) ocupa o seu
    lugar no eixo, sem barra, com o texto "sem execução registrada"."""
    d = runs.assign(
        rotulo=[
            _rotulo_da_execucao(t, r) for t, r in zip(runs["inicio"], runs["run_type"], strict=True)
        ],
        hora=runs["inicio"].dt.strftime("%d/%m/%Y %H:%M UTC"),
        duracao=[cal.duracao_texto(v) for v in runs["duracao_dag_s"]],
        marca_ausente="",
    )
    vazias = pd.DataFrame(
        {
            "inicio": ausentes,
            "rotulo": [_rotulo_da_execucao(t, "scheduled") for t in ausentes],
            "hora": [t.strftime("%d/%m/%Y %H:%M UTC") for t in ausentes],
            "duracao": "sem execução registrada",
            "duracao_dag_s": float("nan"),
            "falhou": False,
            "marca": "",
            "marca_ausente": "sem execução registrada",
        }
    )
    d = pd.concat([d, vazias], ignore_index=True).sort_values("inicio")
    d = d[["rotulo", "hora", "duracao", "duracao_dag_s", "falhou", "marca", "marca_ausente"]]
    ordem = list(d["rotulo"])
    # labelOverlap desligado: toda barra tem rótulo (o Vega esconderia alguns em tela estreita)
    x = alt.X(
        "rotulo:N",
        sort=ordem,
        title=None,
        axis=alt.Axis(labelAngle=-40, labelLimit=170, labelOverlap=False),
    )
    barras = (
        alt.Chart(d.dropna(subset=["duracao_dag_s"]))
        .mark_bar()
        .encode(
            x=x,
            y=alt.Y("duracao_dag_s:Q", title="Duração da execução (s)", scale=alt.Scale(zero=True)),
            color=alt.condition(
                alt.datum.falhou, alt.value(vis.CINZA_ESCURO), alt.value(vis.PETROLEO)
            ),
            tooltip=[
                alt.Tooltip("hora:N", title="Início"),
                alt.Tooltip("duracao:N", title="Duração"),
            ],
        )
    )
    falhas = (
        alt.Chart(d[d["falhou"]])
        .mark_text(dy=-8, fontSize=12, color=vis.TEXTO)
        .encode(x=x, y="duracao_dag_s:Q", text="marca:N")
    )
    faltas = (
        alt.Chart(d[d["marca_ausente"] != ""].assign(y=0.0))
        .mark_text(angle=270, align="left", dx=0, dy=0, fontSize=11, color=vis.CINZA_ESCURO)
        .encode(x=x, y=alt.Y("y:Q"), text="marca_ausente:N")
    )
    return (barras + falhas + faltas).properties(height=ALTURA)


def duracao_por_task(d: pd.DataFrame, ordem: list[str]) -> alt.Chart:
    """Um ponto por (execução, task), sempre a partir de zero. `d` vem de `cal.duracao_por_task`.
    Falha = cruz cinza-escura ("falha ✕", também no texto da legenda); sucesso = círculo
    petróleo."""
    dados = d.assign(hora=d["inicio"].dt.strftime("%d/%m/%Y %H:%M UTC"))[
        ["task_id", "hora", "resultado", "duracao_task_s"]
    ]
    dominio = ["sucesso", "falha ✕"]
    return (
        alt.Chart(dados)
        .mark_point(filled=True, size=90, opacity=0.9)
        .encode(
            y=alt.Y("task_id:N", sort=ordem, title=None),
            x=alt.X("duracao_task_s:Q", title="Duração (s)", scale=alt.Scale(zero=True)),
            shape=alt.Shape(
                "resultado:N",
                scale=alt.Scale(domain=dominio, range=["circle", "cross"]),
                legend=alt.Legend(title=None, orient="bottom"),
            ),
            color=alt.Color(
                "resultado:N",
                scale=alt.Scale(domain=dominio, range=[vis.PETROLEO, vis.CINZA_ESCURO]),
                legend=None,
            ),
            tooltip=[
                alt.Tooltip("task_id:N", title="Etapa"),
                alt.Tooltip("hora:N", title="Execução"),
                alt.Tooltip("duracao_task_s:Q", title="Duração (s)"),
            ],
        )
        .properties(height=26 * len(ordem) + 60)
    )
