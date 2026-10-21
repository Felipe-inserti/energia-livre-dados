"""Página "Previsão de carga": o modelo contra o "Mesmo mês do ano anterior" no teste final.

Mesmo padrão da Decisão: estado, uma frase, três cartões (a ressalva ACIMA do número), o gráfico
principal e o segundo, os próximos 12 meses, limites curtos; tabelas e detalhes em expanders
fechados. Lê só `dashboard/dados/`; os textos vêm de `textos_previsao`. Meses incompletos ficam fora
de todos os gráficos (a camada de dados já os tira; `ate_o_mes` é a rede de segurança).
"""

from pathlib import Path

import pandas as pd
import streamlit as st

from dashboard import calculos as cal
from dashboard import graficos as gr
from dashboard import leitura as lei
from dashboard import textos_previsao as tx
from dashboard import visual as vis


@st.cache_data(show_spinner=False)
def _dados(diretorio: str) -> dict:
    d = Path(diretorio)
    return {
        "manifesto": lei.manifesto(d),
        "previsoes": lei.previsoes_teste_final(d),
        "mape": lei.mape_por_ano(d),
        "modelos": lei.modelos_resumo(d),
        "desenvolvimento": lei.desenvolvimento_resumo(d),
        "cobertura": lei.cobertura(d),
        "producao": lei.previsao_producao(d),
        "erros": lei.erros_producao(d),
        "carga": lei.carga_mensal(d),
    }


# ---------------------------------------------------------------- tabelas (todas em expanders)


def _tabela_modelos(modelos: pd.DataFrame) -> pd.DataFrame:
    nomes = {cal.CANDIDATO_MODELO: "Modelo", cal.CANDIDATO_COMPARACAO: vis.MESMO_MES}
    m = modelos[modelos["candidato"].isin(nomes)]
    return pd.DataFrame(
        {
            "Série": m["candidato"].map(nomes),
            "Erro médio (MAPE)": m["mape_pct"].map(lambda v: cal.percentual(v, 2)),
            "Viés": m["vies_pct"].map(lambda v: cal.percentual(v, 2, True)),
            "Erro médio em MWm": m["mae_mwmed"].map(lambda v: cal.numero(v, 0)),
            "Meses avaliados": m["n"].map(int),
        }
    )


def _tabela_ano(mape: pd.DataFrame, erros: pd.DataFrame) -> pd.DataFrame:
    d = cal.mape_por_ano_longo(mape).pivot(
        index="ano", columns="serie", values=["mape_pct", "vies_pct"]
    )
    e = erros.set_index("ano")
    return pd.DataFrame(
        {
            "Ano": [vis.ano(a) for a in d.index],
            "Erro médio, modelo": [cal.percentual(v, 2) for v in d[("mape_pct", "modelo")]],
            f"Erro médio, {vis.MESMO_MES}": [
                cal.percentual(v, 2) for v in d[("mape_pct", "comparacao")]
            ],
            "Viés, modelo": [cal.percentual(v, 2, True) for v in d[("vies_pct", "modelo")]],
            f"Viés, {vis.MESMO_MES}": [
                cal.percentual(v, 2, True) for v in d[("vies_pct", "comparacao")]
            ],
            "Ano inteiro previsto em dezembro, modelo": [
                cal.percentual(e.loc[a, "modelo_pct"], 2, True) for a in d.index
            ],
            f"Ano inteiro previsto em dezembro, {vis.MESMO_MES}": [
                cal.percentual(e.loc[a, "comparacao_pct"], 2, True) for a in d.index
            ],
        }
    )


def _tabela_cobertura(por_horizonte: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Meses à frente": por_horizonte["valor"],
            "Cobertura do intervalo de 80%": por_horizonte["cobertura80_pct"].map(
                lambda v: cal.percentual(v, 1)
            ),
            "Cobertura do intervalo de 95%": por_horizonte["cobertura95_pct"].map(
                lambda v: cal.percentual(v, 1)
            ),
        }
    )


def _tabela_producao(p: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Mês": p["mes_alvo"].map(cal.mes_por_extenso),
            "Previsão (MWm)": p["previsao_mwmed"].map(lambda v: cal.numero(v, 0)),
            "Faixa de 80% (MWm)": [
                f"{cal.numero(a, 0)} a {cal.numero(b, 0)}"
                for a, b in zip(p["p10_mwmed"], p["p90_mwmed"], strict=True)
            ],
            "Faixa de 95% (MWm)": [
                f"{cal.numero(a, 0)} a {cal.numero(b, 0)}"
                for a, b in zip(p["p025_mwmed"], p["p975_mwmed"], strict=True)
            ],
        }
    )


# ---------------------------------------------------------------- a página


def renderizar(diretorio: str | None = None) -> None:
    d = _dados(str(diretorio or lei.DADOS))
    man = d["manifesto"]
    teste = cal.resumo_teste_final(d["modelos"])
    dev = cal.resumo_desenvolvimento(d["desenvolvimento"])
    cobertura = d["cobertura"]["geral"]

    # ---- 0 e 1. estado e uma frase
    vis.cabecalho("Previsão de carga", man)
    vis.frase(tx.frase(teste, dev))

    # ---- 2. três cartões (a ressalva é a legenda acima do número)
    for coluna, c in zip(st.columns(3), tx.cartoes(teste, cobertura), strict=True):
        with coluna:
            vis.cartao(c["ressalva"], c["rotulo"], c["valor"], c["linhas"], c["ajuda"])

    # ---- 3. gráfico principal: real × previsto no teste final
    st.subheader("Real e previsto no teste final")
    erros_ano = cal.erro_anual_dezembro(d["previsoes"])
    st.caption(tx.legenda_real_x_previsto(erros_ano))
    st.altair_chart(gr.real_x_previsto(cal.previsto_de_dezembro(d["previsoes"])), width="stretch")

    # ---- 4. erro por ano, sem esconder onde o modelo perde
    st.subheader("Erro por ano")
    mape = cal.mape_por_ano_longo(d["mape"])
    st.caption(tx.legenda_erro_por_ano(mape, cal.anos_em_que_o_modelo_perde(d["mape"])))
    st.altair_chart(gr.erro_por_ano(mape), width="stretch")

    # ---- 5. próximos 12 meses
    st.subheader("Próximos 12 meses")
    vis.nota(tx.nota_da_producao(cobertura))
    ate = pd.Timestamp(man["ultimo_mes_fechado"]) if man.get("ultimo_mes_fechado") else None
    carga = d["carga"] if ate is None else cal.ate_o_mes(d["carga"], ate)
    st.altair_chart(
        gr.previsao_producao(d["producao"], cal.historia_recente(carga)), width="stretch"
    )
    st.caption(tx.legenda_das_faixas(cobertura))
    st.caption(tx.legenda_da_producao(d["producao"]), help=tx.glossario.TERMOS["MWm"])
    st.caption(tx.erros_de_producao(d["erros"]))

    # ---- 6. limites curtos, sempre visíveis
    vis.limitacoes(tx.TITULO_LIMITES, tx.limites(teste, dev))

    # ---- 7. detalhes (fechados)
    with st.expander("Ver valores", expanded=False):
        st.markdown("**Teste final, por série**")
        st.dataframe(_tabela_modelos(d["modelos"]), hide_index=True)
        st.markdown("**Por ano**")
        st.dataframe(_tabela_ano(d["mape"], erros_ano), hide_index=True)
        st.markdown("**Cobertura dos intervalos, por horizonte (fora da amostra)**")
        st.altair_chart(
            gr.cobertura_por_horizonte(d["cobertura"]["por_horizonte"]), width="stretch"
        )
        st.dataframe(_tabela_cobertura(d["cobertura"]["por_horizonte"]), hide_index=True)
        st.markdown("**Previsão dos próximos 12 meses**")
        st.dataframe(_tabela_producao(d["producao"]), hide_index=True)
    with st.expander("Sobre o modelo e a série", expanded=False):
        st.markdown(tx.sobre_o_modelo(dev), help=tx.glossario.TERMOS["MMGD"])

    # ---- 8. glossário e auditoria (fechados)
    vis.glossario(tx.GLOSSARIO)
    with vis.auditoria("Auditoria: fontes, calibração e nomes dos candidatos"):
        st.markdown(tx.auditoria(man))
        st.markdown("**Teste final, todos os candidatos**")
        st.dataframe(d["modelos"], hide_index=True)
        st.markdown("**Desenvolvimento (2012–2019)**")
        st.dataframe(d["desenvolvimento"], hide_index=True)
