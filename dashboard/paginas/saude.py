"""Página "Saúde do pipeline": o estado do snapshot, não ao vivo.

Mesmo padrão da Decisão e da Previsão: estado, uma frase, três cartões (a ressalva ACIMA do número),
o gráfico das execuções e a linha da Sprint 4, limites curtos; tabelas, o gráfico por etapa, o
glossário e a auditoria em expanders fechados. Lê só `dashboard/dados/`; os textos vêm de
`textos_saude`. Sem controles.
"""

from pathlib import Path

import pandas as pd
import streamlit as st

from dashboard import calculos as cal
from dashboard import graficos as gr
from dashboard import leitura as lei
from dashboard import textos_saude as tx
from dashboard import visual as vis


@st.cache_data(show_spinner=False)
def _dados(diretorio: str) -> dict:
    d = Path(diretorio)
    execucoes, status_exe = lei.saude_execucoes(d)
    testes, status_dbt = lei.saude_testes(d)
    return {
        "manifesto": lei.manifesto(d),
        "execucoes": execucoes,
        "status_execucoes": status_exe,
        "testes": testes,
        "status_testes": status_dbt,
        "frescor": lei.frescor(d),
    }


# ---------------------------------------------------------------- tabelas (todas em expanders)


def _tabela_execucoes(runs: pd.DataFrame) -> pd.DataFrame:
    def observacao(r) -> str:
        if not r["falhou"]:
            return ""
        return (
            "falha proposital (teste do alerta)" if r["marca"].endswith("proposital") else "falha"
        )

    return pd.DataFrame(
        {
            "Início (UTC)": runs["inicio"].dt.strftime("%d/%m/%Y %H:%M"),
            "Tipo": runs["run_type"].map(lambda t: tx.TIPOS_DE_EXECUCAO.get(t, t)),
            "Estado": runs["estado_dag"].map(lambda e: tx.ESTADOS.get(e, e)),
            "Duração": runs["duracao_dag_s"].map(cal.duracao_texto),
            "Observação": runs.apply(observacao, axis=1),
        }
    )


def _tabela_testes(testes: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Tipo de teste": testes["tipo"].map(lambda t: tx.TIPOS_DE_TESTE.get(t, t)),
            "Testes": testes["testes"].map(int),
            "Passaram": testes["pass"].map(int),
            "Avisos": testes["warn"].map(int),
            "Erros": testes["error"].map(int),
        }
    )


def _tabela_frescor(frescor: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Fonte": frescor["fonte"],
            "Último dado": frescor["ultimo_dado"].map(cal.mes_por_extenso),
            "Dias desde o primeiro dia do mês": frescor["idade_dias_no_snapshot"].map(int),
        }
    )


def _tabela_estados(execucoes: pd.DataFrame) -> pd.DataFrame:
    por_estado = execucoes["estado_task"].value_counts()
    return pd.DataFrame(
        {
            "Estado da etapa": [tx.ESTADOS.get(e, e) for e in por_estado.index],
            "Etapas (todas as execuções)": por_estado.values,
        }
    )


# ---------------------------------------------------------------- a página


def renderizar(diretorio: str | None = None) -> None:
    d = _dados(str(diretorio or lei.DADOS))
    man = d["manifesto"]
    data = cal.data_br(man["snapshot_gerado_em"])
    execucoes = d["execucoes"]

    runs = ultima = None
    if d["status_execucoes"]["estado"] == "disponivel" and not execucoes.empty:
        runs = cal.marcar_falhas(cal.execucoes_por_run(execucoes), frozenset(tx.FALHAS_PROPOSITAIS))
        ultima = cal.resumo_da_ultima_execucao(runs, execucoes)
    dbt = (
        cal.resumo_do_dbt(d["testes"], d["status_testes"])
        if d["status_testes"]["estado"] == "disponivel"
        else None
    )
    fontes = cal.ultimo_mes_das_fontes(d["frescor"])
    dias_do_fim = cal.dias_desde_o_fim_do_mes(fontes["mes"], man["snapshot_gerado_em"])

    # ---- 0 e 1. estado e uma frase
    vis.cabecalho("Saúde do pipeline", man)
    vis.frase(tx.frase(data, ultima, dbt, fontes))

    # ---- 2. três cartões (a ressalva é a legenda acima do número) e a nota das fontes manuais
    for coluna, c in zip(st.columns(3), tx.cartoes(ultima, dbt, fontes, dias_do_fim), strict=True):
        with coluna:
            vis.cartao(c["ressalva"], c["rotulo"], c["valor"], c["linhas"], c["ajuda"])
    if ultima is not None:
        vis.nota(
            tx.nota_fontes_manuais(
                cal.estado_da_etapa(execucoes, ultima["run_id"], "freshness_manuais")
            )
        )

    # ---- 3. gráfico: duração das execuções (falhas e execução ausente visíveis)
    if runs is not None:
        st.subheader("Duração das execuções")
        ausentes = cal.execucoes_agendadas_ausentes(runs)
        propositais = int(runs["marca"].str.endswith("proposital").sum())
        st.caption(tx.legenda_execucoes(runs, ausentes, propositais))
        st.altair_chart(gr.duracao_das_execucoes(runs, ausentes), width="stretch")
        st.caption(tx.LINHA_SPRINT_4)

        # ---- 4. limites curtos, sempre visíveis
        vis.limitacoes(tx.TITULO_LIMITES, tx.limites(data, runs))

    # ---- 5. detalhes (fechados)
    with st.expander("Ver valores", expanded=False):
        if runs is not None:
            st.markdown("**Execuções da DAG**")
            st.dataframe(_tabela_execucoes(runs), hide_index=True)
            st.markdown("**Duração por etapa**")
            st.caption(tx.legenda_etapas())
            etapas = cal.tasks_relevantes(execucoes)
            por_etapa = cal.duracao_por_task(execucoes, etapas)
            por_etapa = por_etapa.assign(task_id=por_etapa["task_id"].map(tx.etapa))
            st.altair_chart(
                gr.duracao_por_task(por_etapa, [tx.etapa(e) for e in etapas]), width="stretch"
            )
            st.markdown("**Estado de cada etapa, em todas as execuções**")
            st.dataframe(_tabela_estados(execucoes), hide_index=True)
        if dbt is not None:
            st.markdown("**Testes do dbt, por tipo**")
            st.dataframe(_tabela_testes(d["testes"]), hide_index=True)
        st.markdown("**Último dado de cada fonte**")
        st.dataframe(_tabela_frescor(d["frescor"]), hide_index=True)

    # ---- 6. glossário e auditoria (fechados)
    vis.glossario(tx.GLOSSARIO)
    with vis.auditoria("Auditoria: fontes, inferências e identificação das execuções"):
        if runs is not None:
            st.markdown(tx.auditoria(man, runs, dbt, ultima))
            st.markdown("**Execuções, como estão no snapshot**")
            st.dataframe(execucoes, hide_index=True)
        elif dbt is not None:
            st.markdown(tx.auditoria(man, pd.DataFrame(columns=["run_type"]), dbt, None))
