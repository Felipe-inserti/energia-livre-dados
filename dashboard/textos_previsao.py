"""Textos da página de Previsão, no mesmo padrão da Decisão (`textos.py`): números do snapshot,
nunca digitados; `$` escapado; linguagem comum (siglas com ajuda e no glossário).

O modelo de comparação é o `MESMO_MES` ("Mesmo mês do ano anterior"); "Ano anterior" é a estratégia
de contrato da página Decisão e NUNCA aparece aqui fora do glossário (teste).
"""

from dashboard import calculos as cal
from dashboard import glossario
from dashboard import visual as vis

CHAVES = {
    "uma_vez": "usado uma única vez",
    "estreitos": "Intervalos mais estreitos que o prometido",
    "fora_da_amostra": "Fora da amostra",
    "mais_dados": "calibrados com mais dados",
    "sem_realizado": "Nenhuma previsão de produção ainda tem valor realizado",
    "perde": "perde em",
    "lightgbm": "LightGBM",
    "mmgd": "MMGD",
}

GLOSSARIO = glossario.selecionar(
    "MWm",
    "MAPE",
    "MMGD",
    "Viés",
    "Cobertura",
    "Modelo",
    "Mesmo mês do ano anterior",
    "Ano anterior",
)

TITULO_LIMITES = "O que este resultado não mostra"


def pct(v: float, casas: int = 1, sinal: bool = False) -> str:
    return vis.percentual(v, casas, sinal)


# ---------------------------------------------------------------- em uma frase


def frase(teste: dict, dev: dict) -> str:
    pequena = dev["diferenca_pp"] < dev["ep_pp"]
    vantagem = "pequena (menos de um erro-padrão)" if pequena else "de mais de um erro-padrão"
    return (
        f"No teste final (2021–2025, {CHAVES['uma_vez']}), o modelo errou em média "
        f"**{pct(teste['modelo']['mape_pct'])}** ao mês, contra "
        f"**{pct(teste['comparacao']['mape_pct'])}** do {vis.MESMO_MES}; no desenvolvimento "
        f"(2012–2019) a vantagem foi {vantagem}: {pct(dev['modelo_mape_pct'], 2)} contra "
        f"{pct(dev['comparacao_mape_pct'], 2)}."
    )


# ---------------------------------------------------------------- cartões


def cartoes(teste: dict, cobertura: dict) -> list[dict]:
    m, c = teste["modelo"], teste["comparacao"]
    return [
        {
            "ressalva": f"Teste final, 5 anos, {int(m['n'])} pares",
            "rotulo": "Erro médio (MAPE)",
            "valor": pct(m["mape_pct"]),
            "linhas": [f"contra {pct(c['mape_pct'])} do {vis.MESMO_MES}"],
            "ajuda": glossario.TERMOS["MAPE"],
        },
        {
            "ressalva": "Negativo: previsto abaixo do real",
            "rotulo": "Viés",
            "valor": pct(m["vies_pct"], 1, True),
            "linhas": [f"contra {pct(c['vies_pct'], 1, True)} do {vis.MESMO_MES}"],
            "ajuda": glossario.TERMOS["Viés"],
        },
        {
            "ressalva": CHAVES["estreitos"],
            "rotulo": "Cobertura dos intervalos",
            "valor": f"{pct(cobertura['cobertura80_pct'])} e {pct(cobertura['cobertura95_pct'])}",
            "linhas": [
                "prometido: 80% e 95%. "
                f"{CHAVES['fora_da_amostra']}: calibrados só no desenvolvimento (2012–2019)"
            ],
            "ajuda": glossario.TERMOS["Cobertura"],
        },
    ]


# ---------------------------------------------------------------- gráficos


def legenda_real_x_previsto(erros: "object") -> str:
    pior = erros.loc[erros["modelo_pct"].abs().idxmax()]
    return (
        "Previsões feitas em dezembro, 12 meses à frente. O pior ano do modelo foi "
        f"{int(pior['ano'])}: {pct(pior['modelo_pct'], 1, True)} no ano inteiro, contra "
        f"{pct(pior['comparacao_pct'], 1, True)} do {vis.MESMO_MES}."
    )


def legenda_erro_por_ano(mape: "object", anos_que_perde: list[int]) -> str:
    if not anos_que_perde:
        return "O modelo erra menos que o comparativo em todos os anos."
    d = mape.pivot(index="ano", columns="serie", values="mape_pct")
    partes = [
        f"{a} ({pct(d.loc[a, 'modelo'])} contra {pct(d.loc[a, 'comparacao'])})"
        for a in anos_que_perde
    ]
    return f"O modelo **{CHAVES['perde']} {', '.join(partes)}**; nos demais anos erra menos."


# ---------------------------------------------------------------- próximos 12 meses


def nota_da_producao(cobertura: dict) -> str:
    return (
        f"Os intervalos de produção são **{CHAVES['mais_dados']}** (incluem o teste final), então "
        "não se pode medir a cobertura com eles. A referência é a cobertura estimada fora da "
        f"amostra: {pct(cobertura['cobertura80_pct'])} e {pct(cobertura['cobertura95_pct'])}."
    )


def legenda_da_producao(previsao: "object") -> str:
    p = previsao
    primeiro, ultimo = p.iloc[0], p.iloc[-1]
    return (
        f"Previsão feita em {cal.mes_por_extenso(primeiro['origem'])}: de "
        f"{cal.numero(primeiro['previsao_mwmed'], 0)} MWm em "
        f"{cal.mes_por_extenso(primeiro['mes_alvo'])} a "
        f"{cal.numero(ultimo['previsao_mwmed'], 0)} MWm em "
        f"{cal.mes_por_extenso(ultimo['mes_alvo'])}. Faixa escura: 80%; clara: 95%."
    )


def erros_de_producao(erros: "object") -> str:
    if erros.empty:
        return f"{CHAVES['sem_realizado']}."
    return (
        f"{len(erros)} previsões de produção já têm valor realizado; erro médio absoluto de "
        f"{pct(erros['erro_pct'].abs().mean())}."
    )


# ---------------------------------------------------------------- limites e detalhes


def limites(teste: dict, dev: dict) -> list[str]:
    modelo, comparacao = teste["modelo"], teste["comparacao"]
    vantagem_teste = comparacao["mape_pct"] - modelo["mape_pct"]
    return [
        "**Só 5 anos de teste**, e os 12 horizontes de um mesmo mês erram juntos: a diferença "
        "entre 70% e 80% de cobertura não tem teste formal.",
        f"**O erro cresce com o horizonte**: {pct(modelo['mape_h1_pct'])} em 1 mês, "
        f"{pct(modelo['mape_h12_pct'])} em 12 meses.",
        "**A temperatura do mês** explica boa parte do erro e não se conhece 12 meses antes.",
        f"**Parte da vantagem vem de o {vis.MESMO_MES} piorar com as quebras de definição da "
        f"série**: o erro dele foi de {pct(dev['comparacao_mape_pct'], 2)} no desenvolvimento a "
        f"{pct(comparacao['mape_pct'], 2)} no teste final; a vantagem do modelo foi de "
        f"{cal.numero(dev['diferenca_pp'], 3)} ponto percentual no desenvolvimento e de "
        f"{cal.numero(vantagem_teste, 2)} no teste final.",
    ]


def sobre_o_modelo(dev: dict) -> str:
    return (
        f"O **{CHAVES['lightgbm']}** foi avaliado no desenvolvimento e perdeu pelo critério "
        f"congelado antes de rodar ({pct(dev['lightgbm_mape_pct'], 2)} contra "
        f"{pct(dev['comparacao_mape_pct'], 2)} do {vis.MESMO_MES}). A série de carga é ajustada "
        f"para mudanças de definição da carga ({CHAVES['mmgd']})."
    )


# ---------------------------------------------------------------- auditoria


def auditoria(manifesto: dict) -> str:
    cob, cal_prod = (
        manifesto["cobertura_exibida"],
        manifesto["calibracao_dos_intervalos_de_producao"],
    )
    return (
        f"**Cobertura exibida.** {cob['descricao']} Fonte: `{cob['fonte']}`; referência: "
        f"{cob['referencia']}. A cobertura calculada com uma calibração que já viu o teste "
        "não é exibida como cobertura.\n\n"
        f"**Intervalos de produção.** {cal_prod['descricao']} Valores no banco: "
        f"`{', '.join(cal_prod['valores_no_banco'])}`.\n\n"
        f"**Candidatos.** `{cal.CANDIDATO_MODELO}` (o modelo), "
        f"`{cal.CANDIDATO_COMPARACAO}` (mesmos "
        "pares do modelo) e `sazonal_ingenuo` (todos os pares)."
    )
