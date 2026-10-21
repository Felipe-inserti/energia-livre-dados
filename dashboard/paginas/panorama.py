"""Página "Panorama do setor" (versão mínima): a carga do SE/CO e o PLD mensal, em contexto.

Mesmo padrão das outras páginas: estado, uma frase, até dois cartões (a ressalva ACIMA do número),
dois gráficos, limites curtos; valores, glossário e auditoria em expanders fechados. Lê só
`carga_mensal_se.csv` e `pld_mensal_se.csv` de `dashboard/dados/`; os textos vêm de
`textos_panorama`. Sem controles. Os meses incompletos já ficam fora (camada de dados).
"""

from pathlib import Path

import pandas as pd
import streamlit as st

from dashboard import calculos as cal
from dashboard import graficos as gr
from dashboard import leitura as lei
from dashboard import textos_panorama as tx
from dashboard import visual as vis


@st.cache_data(show_spinner=False)
def _dados(diretorio: str) -> dict:
    d = Path(diretorio)
    return {
        "manifesto": lei.manifesto(d),
        "carga": lei.carga_mensal(d),
        "pld": lei.pld_mensal(d),
    }


# ---------------------------------------------------------------- tabelas (em expander)


def _tabela_carga(carga: pd.DataFrame) -> pd.DataFrame:
    c = carga.dropna(subset=["carga_ajustada_reconstruida_mwmed"]).tail(12)
    return pd.DataFrame(
        {
            "Mês": c["mes"].map(cal.mes_por_extenso),
            "Original (MWm)": c["carga_original_mwmed"].map(lambda v: cal.numero(v, 0)),
            "Reconstruída (MWm)": c["carga_ajustada_reconstruida_mwmed"].map(
                lambda v: cal.numero(v, 0)
            ),
        }
    )


def _tabela_pld(pld: pd.DataFrame) -> pd.DataFrame:
    p = pld.tail(12)
    return pd.DataFrame(
        {
            "Mês": p["mes"].map(cal.mes_por_extenso),
            "PLD (R$/MWh)": p["pld_rs_mwh"].map(lambda v: cal.numero(v, 2)),
            "Piso do ano (R$/MWh)": p["piso_rs_mwh"].map(lambda v: cal.numero(v, 2)),
            "Teto estrutural do ano (R$/MWh)": p["teto_estrutural_rs_mwh"].map(
                lambda v: cal.numero(v, 2)
            ),
        }
    )


# ---------------------------------------------------------------- a página


def renderizar(diretorio: str | None = None) -> None:
    d = _dados(str(diretorio or lei.DADOS))
    man, carga, pld = d["manifesto"], d["carga"], d["pld"]
    data = cal.data_br(man["snapshot_gerado_em"])
    ultima, ultimo = cal.ultima_carga(carga), cal.ultimo_pld(pld)

    # ---- 0 e 1. estado e uma frase
    vis.cabecalho("Panorama do setor", man)
    vis.frase(tx.frase(data, ultima, ultimo))

    # ---- 2. dois cartões (a ressalva é a legenda acima do número)
    for coluna, c in zip(st.columns(2), tx.cartoes(ultima, ultimo), strict=True):
        with coluna:
            vis.cartao(c["ressalva"], c["rotulo"], c["valor"], c["linhas"], c["ajuda"])

    # ---- 3. gráfico 1: carga mensal, original e reconstruída, com a quebra do tipo III
    st.subheader("Carga mensal do SE/CO")
    st.caption(tx.legenda_carga(cal.ultimo_mes_com_ajuste(carga)), help=tx.glossario.TERMOS["MWm"])
    st.altair_chart(gr.carga(carga, cal.QUEBRA_TIPO_III), width="stretch")

    # ---- 4. gráfico 2: PLD mensal com piso e teto
    st.subheader("PLD mensal do Sudeste")
    st.caption(tx.legenda_pld(cal.ultimo_mes_do_pld_semanal(pld)))
    st.altair_chart(gr.pld(pld), width="stretch")

    # ---- 5. limites curtos, sempre visíveis
    incompletos = man.get("meses_incompletos", {}).get("carga_mensal_se.csv", [])
    vis.limitacoes(tx.TITULO_LIMITES, tx.limites(data, incompletos))

    # ---- 6. detalhes (fechados)
    with st.expander("Ver valores", expanded=False):
        st.markdown("**Carga dos últimos 12 meses**")
        st.dataframe(_tabela_carga(carga), hide_index=True)
        st.markdown("**PLD dos últimos 12 meses**")
        st.dataframe(_tabela_pld(pld), hide_index=True)

    # ---- 7. glossário e auditoria (fechados)
    vis.glossario(tx.GLOSSARIO)
    with vis.auditoria("Auditoria: fontes, quebra e nomes dos arquivos"):
        st.markdown(tx.auditoria(man, carga, pld))
