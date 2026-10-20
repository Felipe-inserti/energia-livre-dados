"""Página "Decisão de contrato": o backtest pré-registrado, em pirâmide invertida.

`renderizar()` é só interface: lê o snapshot por `dashboard.leitura`, calcula por `calculos`,
desenha com `graficos` e `visual`; todo texto vem de `textos` (redesenho aprovado em
`data/logs/relatorio_6c2_redesign.md`). Ordem: estado, uma frase, três cartões, ganho por ano, por
que funcionou, a banda, sensibilidades, prévia, limitações, glossário e auditoria (fechados).
Cada ressalva fica ACIMA do número que ela qualifica; tabelas só dentro de expanders.
"""

from pathlib import Path

import pandas as pd
import streamlit as st

from dashboard import calculos as cal
from dashboard import graficos as gr
from dashboard import leitura as lei
from dashboard import textos as tx
from dashboard import visual as vis


@st.cache_data(show_spinner=False)
def _dados(diretorio: str) -> dict:
    d = Path(diretorio)
    return {
        "manifesto": lei.manifesto(d),
        "economia": lei.backtest_economia(d),
        "anual": lei.backtest_anual(d),
        "mensal": lei.backtest_mensal(d),
        "sens": lei.sensibilidades(d),
        "sens_ano": lei.sensibilidades_por_ano(d),
        "banda": lei.banda_f(d),
        "invariancias": lei.invariancias(d),
        "pre": lei.pre_registros(d),
        "previa": lei.previa_atual(d),
        "anteriores": lei.previas_anteriores(d),
        "esperado": lei.pld_esperado(d),
    }


# ---------------------------------------------------------------- tabelas (todas em expanders)


def _tabela_custos(anual: pd.DataFrame, economia: pd.DataFrame) -> pd.DataFrame:
    custos = cal.custos_por_ano(anual)
    linhas = []
    for ano in custos.index:
        x = economia[
            (economia["sens_id"] == "caso_base") & (economia["recorte"].astype(str) == str(ano))
        ].iloc[0]
        linhas.append(
            {
                "Ano": vis.ano(ano),
                f"Custo, {vis.ANO_ANTERIOR}": cal.reais(custos.loc[ano, "ingenua"]),
                f"Custo, {vis.PREVISAO}": cal.reais(custos.loc[ano, "pontual"]),
                f"Custo, {vis.OTIMIZADA}": cal.reais(custos.loc[ano, "otimizada"]),
                "Valor da previsão": f"{cal.reais(x['valor_previsao_rs'], sinal=True)} "
                f"({cal.percentual(x['valor_previsao_pct'], 2, sinal=True)})",
                "Valor da otimização": f"{cal.reais(x['valor_otimizacao_rs'], sinal=True)} "
                f"({cal.percentual(x['valor_otimizacao_pct'], 2, sinal=True)})",
            }
        )
    return pd.DataFrame(linhas)


def _tabela_d3(d3: pd.DataFrame) -> pd.DataFrame:
    def situacao(r, limite):
        return "meio da banda" if not limite else ("mínimo" if r < 1 else "máximo")

    return pd.DataFrame(
        {
            "Ano": d3["ano"].map(vis.ano),
            "Preço do contrato (R$/MWh)": d3["preco_contrato_rs_mwh"].map(cal.numero),
            "PLD esperado (R$/MWh)": d3["pld_esperado_rs_mwh"].map(cal.numero),
            "Contrato − esperado": d3["contrato_menos_esperado"].map(
                lambda v: cal.numero(v, 2, True)
            ),
            "Volume da Otimizada (× a previsão)": [
                f"{cal.numero(r, 3)}× ({situacao(r, lim)})"
                for r, lim in zip(d3["r_otimizada"], d3["no_limite"], strict=True)
            ],
        }
    )


def _tabela_f(t: pd.DataFrame) -> pd.DataFrame:
    zero = t["f"].round(6) == 0
    return pd.DataFrame(
        {
            "Banda": t["f"].map(lambda f: f"{round(f * 100)}%"),
            "Valor da previsão (banda > 0)": [
                "—" if z else cal.reais(v, sinal=True)
                for z, v in zip(zero, t["valor_previsao_rs"], strict=True)
            ],
            "Ganho por contratar acima ou abaixo da previsão (só banda 0%)": [
                cal.reais(v, sinal=True) if z else "—"
                for z, v in zip(zero, t["valor_previsao_rs"], strict=True)
            ],
            "Valor da otimização": t["valor_otimizacao_rs"].map(cal.reais),
            "Economia total": t["economia_total_rs"].map(lambda v: cal.reais(v, sinal=True)),
        }
    )


def _tabela_sens(t: pd.DataFrame, sem_2021: pd.DataFrame) -> pd.DataFrame:
    sem = sem_2021.set_index("sens_id")["economia_total_rs"]
    return pd.DataFrame(
        {
            "Variação": t["sens_id"].map(tx.ROTULOS_SENSIBILIDADES),
            "Valor da previsão": t["valor_previsao_rs"].map(lambda v: cal.reais(v, sinal=True)),
            "Valor da otimização": t["valor_otimizacao_rs"].map(lambda v: cal.reais(v, sinal=True)),
            "Economia total": t["economia_total_rs"].map(lambda v: cal.reais(v, sinal=True)),
            "Economia total, sem 2021": [cal.reais(sem[i], sinal=True) for i in t["sens_id"]],
            "Nota": [f"{tx.NOTA_ESPECULATIVA}" if e else "" for e in t["especulacao_excluida"]],
        }
    )


def _tabela_pre_registros(pre: pd.DataFrame) -> pd.DataFrame:
    return pre.rename(
        columns={
            "sens_id": "Execução",
            "quando_utc": "Quando (UTC)",
            "head": "Versão do código",
            "preregistro": "Pré-registro",
            "config_hash": "config_hash",
            "execucao_id": "Cenários (execucao_id)",
            "muda": "O que mudou",
        }
    )


def _tabela_previa(previa: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Estratégia": previa["estrategia"].map(vis.NOMES_DAS_ESTRATEGIAS),
            "Volume (MWm)": previa["v_mwm"].map(lambda v: cal.numero(v, 4)),
            "Volume (× a previsão)": previa["razao_v_pontual"].map(lambda v: cal.numero(v, 3)),
            "Preço do contrato (R$/MWh)": previa["preco_contrato_rs_mwh"].map(cal.numero),
            "Custo esperado (R$)": previa["custo_esperado_rs"].map(lambda v: cal.numero(v, 0)),
            "CVaR (R$)": previa["cvar_rs"].map(lambda v: cal.numero(v, 0)),
        }
    )


# ---------------------------------------------------------------- a página


def renderizar(diretorio: str | None = None) -> None:
    d = _dados(str(diretorio or lei.DADOS))
    man, pre = d["manifesto"], d["pre"]
    h_base, h_sens = pre.iloc[0]["preregistro"], pre.iloc[1]["preregistro"]

    # ---- 0. estado
    vis.cabecalho("Decisão de contrato", man, (h_base[:7], h_sens[:7]))

    # ---- 1. em uma frase
    res = cal.resultado(d["economia"])
    res_sem = cal.resultado(d["economia"], recorte=lei.RECORTE_SEM_2021)
    anos = cal.por_ano(d["economia"], d["anual"])
    conc = cal.concentracao(anos)
    vis.frase(tx.frase_principal(res))

    # ---- 2. três cartões (a ressalva é o rótulo, acima do número)
    meses = cal.meses_fora_da_faixa(d["anual"])
    for coluna, c in zip(st.columns(3), tx.cartoes(res, res_sem, conc, meses), strict=True):
        with coluna:
            vis.cartao(c["ressalva"], c["rotulo"], c["valor"], c["linhas"], c["ajuda"])
    st.caption(tx.NOTA_DOS_CARTOES)

    # ---- 3. ganho por ano
    st.subheader("Ganho da otimização por ano")
    st.caption(tx.LEGENDA_GANHO)
    st.altair_chart(gr.ganho_por_ano(anos), width="stretch")
    with st.expander("Números por ano, com centavos", expanded=False):
        st.dataframe(_tabela_custos(d["anual"], d["economia"]), hide_index=True)
        st.caption(tx.legenda_concentracao_exata(conc))

    # ---- 4. por que funcionou
    st.subheader("Por que funcionou")
    d3 = cal.esperado_x_contrato(d["anual"], d["esperado"], pre.iloc[0]["execucao_id"])
    d3 = d3.merge(anos[["ano", "no_limite"]], on="ano")
    n_limite, _ = cal.r_no_limite(anos)
    st.markdown(tx.por_que_funcionou(n_limite), help=tx.GLOSSARIO["PLD"])
    st.altair_chart(gr.preco_x_esperado(d3), width="stretch")
    with st.expander("Preço do contrato e PLD esperado, ano a ano", expanded=False):
        st.dataframe(_tabela_d3(d3), hide_index=True)
        st.caption(tx.LEGENDA_D3)

    # ---- 5. a banda
    st.subheader("A banda de flexibilidade")
    vis.nota(tx.RESSALVA_BANDA)
    tabela_f = cal.tabela_f(d["banda"])
    st.altair_chart(gr.banda_linhas(tabela_f), width="stretch")
    st.markdown(tx.texto_da_banda(tabela_f))
    with st.expander("Detalhe da banda, por ano e com centavos", expanded=False):
        sens_ano = d["sens_ano"]
        f0 = sens_ano[sens_ano["sens_id"] == "f00"].set_index("ano")["valor_previsao_rs"].to_dict()
        soma_f0 = float(tabela_f.loc[tabela_f["f"].round(6) == 0, "valor_previsao_rs"].iloc[0])
        st.markdown(tx.nota_f0({int(k): float(v) for k, v in f0.items()}, soma_f0))
        st.dataframe(_tabela_f(tabela_f), hide_index=True)
        st.caption(tx.NOTA_ARREDONDAMENTO)
        st.altair_chart(gr.banda_por_ano(cal.tabela_f_por_ano(d["banda"])), width="stretch")
        st.caption(f"Em banda de 0%, o ponto vazado é o {tx.ROTULO_F0}.")

    # ---- 6. sensibilidades
    st.subheader("Sensibilidades")
    st.markdown(tx.NOTA_SENSIBILIDADES)
    sens5 = cal.tabela_sensibilidades(d["sens"])
    base_rs = float(sens5.loc[sens5["sens_id"] == "caso_base", "valor_otimizacao_rs"].iloc[0])
    pontos = sens5[sens5["sens_id"] != "caso_base"].assign(
        rotulo=lambda x: x["sens_id"].map(tx.ROTULOS_SENSIBILIDADES),
        especulacao=lambda x: x["especulacao_excluida"],
        anotacao=lambda x: [
            f"{tx.NOTA_ESPECULATIVA}: {vis.reais_curto(v)}" for v in x["valor_otimizacao_rs"]
        ],
    )
    ordem = [tx.ROTULOS_SENSIBILIDADES[i] for i in pontos["sens_id"]]
    st.altair_chart(gr.sensibilidades_pontos(pontos, ordem, base_rs), width="stretch")
    with st.expander("Tabela completa das sensibilidades, com centavos", expanded=False):
        st.markdown(tx.NOTA_SENSIBILIDADES_TABELA)
        sens_sem = cal.tabela_sensibilidades(d["sens"], lei.RECORTE_SEM_2021)
        st.dataframe(_tabela_sens(sens5, sens_sem), hide_index=True)
        r120 = d["sens"][
            (d["sens"]["sens_id"] == "rmax120")
            & (d["sens"]["recorte"].astype(str) == lei.RECORTE_5_ANOS)
        ]
        por_ano_120 = (
            sens_ano[sens_ano["sens_id"] == "rmax120"]
            .set_index("ano")["valor_otimizacao_rs"]
            .to_dict()
        )
        mensal = d["mensal"]
        pld_2024 = mensal[
            (mensal["ano"] == 2024) & (mensal["estrategia"] == "otimizada")
        ].set_index("mes")["pld_ponderado_rs_mwh"]
        st.markdown(
            tx.rotulo_rmax120(
                r120.iloc[0].to_dict(),
                {int(k): float(v) for k, v in por_ano_120.items()},
                (float(pld_2024.loc[9]), float(pld_2024.loc[10])),
            )
        )

    # ---- 7. prévia
    st.subheader("Prévia dos próximos 12 meses")
    previa = d["previa"]
    if previa.empty:
        vis.nota("Nenhuma prévia de produção foi gravada ainda.")
    else:
        r = cal.resumo_da_previa(previa)
        esperado = cal.pld_esperado_da_origem(d["esperado"], r["execucao_id"], r["origem"])
        regra = cal.leitura_da_regra(r["preco_rs_mwh"], esperado, r["r"]["otimizada"])
        vis.alerta(
            tx.previa(
                cal.data_br(man["snapshot_gerado_em"]),
                cal.mes_por_extenso(r["janela_inicio"]),
                cal.mes_por_extenso(r["janela_fim"]),
                regra["texto"],
                r["v_mwm"]["otimizada"],
                r["v_mwm"]["pontual"],
                r["limites_assumidos"],
            )
        )

    # ---- 8. limitações (curtas, sempre visíveis, o lastro primeiro)
    vis.limitacoes(tx.TITULO_LIMITACOES, tx.LIMITACOES)

    # ---- 9. glossário e auditoria (fechados)
    vis.glossario(tx.GLOSSARIO)
    with vis.auditoria():
        st.markdown(tx.pre_registro(h_base, h_sens, pre.iloc[0]["execucao_id"], man["commit"]))
        st.dataframe(_tabela_pre_registros(pre), hide_index=True)
        st.markdown("**Onde o Ano anterior e a Previsão não mudam (invariâncias)**")
        st.dataframe(d["invariancias"], hide_index=True)
        if not previa.empty:
            st.markdown("**Volumes e custos esperados da prévia**")
            st.dataframe(_tabela_previa(previa), hide_index=True)
            if not d["anteriores"].empty:
                st.markdown("**Prévias anteriores**")
                st.dataframe(_tabela_previa(d["anteriores"]), hide_index=True)
        st.markdown(f"**Outras limitações.** {tx.LIMITACOES_EXTRAS}")
