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

AZUL = vis.PETROLEO  # (as páginas de Previsão, Saúde e Panorama ainda usam estes nomes)
CINZA = vis.CINZA
CORES_ESTRATEGIA = {
    "ingenua": vis.CINZA_CLARO,
    "pontual": vis.CINZA_ESCURO,
    "otimizada": vis.PETROLEO,
}
ALTURA = 320

# o Altair/Vega não aceita `formatLocale` pelo st.altair_chart: troca a vírgula de milhar por ponto
_MILHAR_BR = "replace(format(datum.value, ',.0f'), regexp(',', 'g'), '.')"


def eixo_reais(titulo: str) -> alt.Axis:
    return alt.Axis(title=titulo, labelExpr=_MILHAR_BR)


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
SERIE_F0 = "Efeito do volume sob o diferencial de preço (não é previsão)"


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


_ESCALA_BANDA = alt.Scale(
    domain=[SERIE_PREVISAO, SERIE_OTIMIZACAO, SERIE_F0],
    range=[vis.CINZA, vis.PETROLEO, vis.CINZA],
)


def _camadas_da_banda(
    d: pd.DataFrame, com_rotulos: bool, legenda: bool = True, largura: int | None = None
) -> alt.LayerChart:
    x = alt.X(
        "banda:Q",
        title="Banda (± do consumo previsto)",
        scale=alt.Scale(domain=[-1, 16], nice=False),
        axis=alt.Axis(values=[0, 5, 10, 15], labelExpr="datum.value + '%'"),
    )
    cor = alt.Color(
        "serie:N",
        scale=_ESCALA_BANDA,
        legend=alt.Legend(title=None, orient="bottom", columns=1, labelLimit=520)
        if legenda
        else None,
    )
    y = alt.Y("valor_rs:Q", axis=eixo_reais("R$ de custo evitado"))
    linhas = alt.Chart(d).mark_line(strokeWidth=2.5).encode(x=x, y=y, color=cor, detail="serie:N")
    pontos = (
        alt.Chart(d)
        .mark_point(size=90, strokeWidth=2)
        .encode(
            x=x,
            y=y,
            stroke=cor,
            # em banda 0% o ponto da previsão é vazado: não é valor da previsão
            fill=alt.condition(alt.datum.serie == SERIE_F0, alt.value("white"), cor),
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
        axis=eixo_reais("Valor da otimização em 5 anos (R$)"),
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


def carga(df: pd.DataFrame) -> alt.Chart:
    longo = df.melt(
        id_vars="mes",
        value_vars=["carga_original_mwmed", "carga_ajustada_reconstruida_mwmed"],
        var_name="serie",
        value_name="mwmed",
    )
    longo["serie"] = longo["serie"].map(
        {
            "carga_original_mwmed": "original (ONS)",
            "carga_ajustada_reconstruida_mwmed": "reconstruída",
        }
    )
    return (
        alt.Chart(longo)
        .mark_line()
        .encode(
            x=alt.X("mes:T", title=None),
            y=alt.Y("mwmed:Q", title="Carga SE/CO (MWmed)", scale=alt.Scale(zero=False)),
            color=alt.Color("serie:N", legend=alt.Legend(title=None, orient="bottom")),
            tooltip=["mes:T", "serie:N", "mwmed:Q"],
        )
        .properties(height=ALTURA)
    )


def pld(df: pd.DataFrame) -> alt.Chart:
    base = alt.Chart(df).encode(x=alt.X("mes:T", title=None))
    linha = base.mark_line(color=AZUL).encode(
        y=alt.Y("pld_rs_mwh:Q", title="PLD mensal do SE (R$/MWh)", scale=alt.Scale(zero=True)),
        tooltip=["mes:T", "pld_rs_mwh:Q", "fonte:N"],
    )
    piso = base.mark_line(color=CINZA, strokeDash=[4, 3]).encode(y="piso_rs_mwh:Q")
    teto = base.mark_line(color=CINZA, strokeDash=[4, 3]).encode(y="teto_estrutural_rs_mwh:Q")
    return (linha + piso + teto).properties(height=ALTURA)


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


def real_x_previsto(df: pd.DataFrame) -> alt.Chart:
    """`df`: alvo, serie ('real', 'modelo', 'ingênuo sazonal') e mwmed."""
    return (
        alt.Chart(df)
        .mark_line(point=True)
        .encode(
            x=alt.X("alvo:T", title=None),
            y=alt.Y("mwmed:Q", title="Carga SE/CO (MWmed)", scale=alt.Scale(zero=False)),
            color=alt.Color("serie:N", legend=alt.Legend(title=None, orient="bottom")),
            tooltip=["alvo:T", "serie:N", "mwmed:Q"],
        )
        .properties(height=ALTURA)
    )


def mape(df: pd.DataFrame) -> alt.Chart:
    return (
        alt.Chart(df)
        .mark_bar()
        .encode(
            x=alt.X("ano:O", title="Ano"),
            xOffset="rotulo:N",
            y=alt.Y("mape_pct:Q", title="MAPE (%)", scale=alt.Scale(zero=True)),
            color=alt.Color("rotulo:N", legend=alt.Legend(title=None, orient="bottom")),
            tooltip=["ano:O", "rotulo:N", "mape_pct:Q"],
        )
        .properties(height=ALTURA // 1.3)
    )


def cobertura_por_horizonte(df: pd.DataFrame) -> alt.Chart:
    """`df`: valor (horizonte), cobertura80_pct, cobertura95_pct; linhas de referência nominais."""
    longo = df.melt(
        id_vars="valor",
        value_vars=["cobertura80_pct", "cobertura95_pct"],
        var_name="nivel",
        value_name="cobertura",
    )
    longo["nivel"] = longo["nivel"].map(
        {"cobertura80_pct": "observada (nominal 80%)", "cobertura95_pct": "observada (nominal 95%)"}
    )
    nominal = pd.DataFrame({"y": [80, 95]})
    ref = alt.Chart(nominal).mark_rule(color=CINZA, strokeDash=[4, 3]).encode(y="y:Q")
    linhas = (
        alt.Chart(longo)
        .mark_line(point=True)
        .encode(
            x=alt.X("valor:O", title="Horizonte (meses à frente)"),
            y=alt.Y(
                "cobertura:Q", title="Cobertura observada (%)", scale=alt.Scale(domain=[50, 100])
            ),
            color=alt.Color("nivel:N", legend=alt.Legend(title=None, orient="bottom")),
            tooltip=["valor:O", "nivel:N", "cobertura:Q"],
        )
    )
    return (linhas + ref).properties(height=ALTURA // 1.3)


def previsao_producao(previsao: pd.DataFrame, historico: pd.DataFrame) -> alt.Chart:
    """Previsão de produção (12 meses) com as faixas NOMINAIS de 80% e 95% e a carga realizada."""
    base = alt.Chart(previsao).encode(x=alt.X("mes_alvo:T", title=None))
    f95 = base.mark_area(opacity=0.15, color=AZUL).encode(
        y=alt.Y("p025_mwmed:Q", scale=alt.Scale(zero=False), title="Carga SE/CO (MWmed)"),
        y2="p975_mwmed:Q",
    )
    f80 = base.mark_area(opacity=0.30, color=AZUL).encode(y="p10_mwmed:Q", y2="p90_mwmed:Q")
    centro = base.mark_line(color=AZUL).encode(
        y="previsao_mwmed:Q", tooltip=["mes_alvo:T", "previsao_mwmed:Q"]
    )
    real = (
        alt.Chart(historico)
        .mark_line(color=CINZA)
        .encode(
            x="mes:T",
            y="carga_ajustada_reconstruida_mwmed:Q",
            tooltip=["mes:T", "carga_ajustada_reconstruida_mwmed:Q"],
        )
    )
    return (real + f95 + f80 + centro).properties(height=ALTURA)


# ---------------------------------------------------------------- saúde


def duracao_das_tasks(df: pd.DataFrame) -> alt.Chart:
    """Duração (s) de cada task da última execução; só `failed` ganha cor de alerta."""
    d = df.assign(falhou=df["estado_task"] == "failed")
    return (
        alt.Chart(d)
        .mark_bar()
        .encode(
            y=alt.Y("task_id:N", sort="-x", title=None),
            x=alt.X("duracao_task_s:Q", title="Duração (s)", scale=alt.Scale(zero=True)),
            color=alt.condition(alt.datum.falhou, alt.value(vis.AMBAR), alt.value(vis.PETROLEO)),
            tooltip=["task_id:N", "estado_task:N", "duracao_task_s:Q"],
        )
        .properties(height=ALTURA)
    )
