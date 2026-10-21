"""Textos da página Panorama do setor, no mesmo padrão das outras páginas: números do snapshot,
nunca digitados; `$` escapado; linguagem comum (siglas com ajuda e no glossário).

O que NÃO vem do snapshot e por isso tem fonte escrita e teste: a data da quebra do tipo III
(`calculos.QUEBRA_TIPO_III`, docs/metricas.md) e o que a série de PLD mistura (dois cálculos).
"""

import pandas as pd

from dashboard import calculos as cal
from dashboard import glossario
from dashboard import visual as vis

CHAVES = {
    "se_co": "Carga do SE/CO inteiro, não do consumidor-exemplo",
    "duas_contas": "duas contas diferentes",
    "reservatorios": "Reservatórios (EAR/ENA) não foram ingeridos; fora do escopo",
    "nao_ao_vivo": "não ao vivo",
}

GLOSSARIO = glossario.selecionar(
    "PLD", "PLD ponderado", "MWm", "SE/CO", "Tipo III", "Carga reconstruída", "MMGD"
)
TITULO_LIMITES = "O que este panorama não mostra"


def mes(d) -> str:
    return cal.mes_por_extenso(d)


def reais(v: float, casas: int = 2) -> str:
    return vis.reais(v, casas, md=True)


# ---------------------------------------------------------------- em uma frase


def frase(data: str, carga: dict, pld: dict) -> str:
    variacao = (
        ""
        if carga["variacao_pct"] is None
        else f" ({cal.percentual(carga['variacao_pct'], 1, True)} contra "
        f"{mes(carga['mes_anterior'])})"
    )
    limites = (
        ""
        if pld["piso"] is None
        else f", entre o piso de {reais(pld['piso'])} e o teto estrutural de {reais(pld['teto'])}"
    )
    return (
        f"No snapshot de {data}, a carga do SE/CO em {mes(carga['mes'])} foi de "
        f"**{cal.numero(carga['mwm'], 0)} MWm**{variacao} e o PLD mensal foi de "
        f"**{reais(pld['rs_mwh'])}/MWh**{limites}."
    )


# ---------------------------------------------------------------- cartões


def cartoes(carga: dict, pld: dict) -> list[dict]:
    anterior = (
        []
        if carga["mwm_anterior"] is None
        else [
            f"{cal.percentual(carga['variacao_pct'], 1, True)} contra {mes(carga['mes_anterior'])} "
            f"({cal.numero(carga['mwm_anterior'], 0)} MWm)"
        ]
    )
    limites = (
        []
        if pld["piso"] is None
        else [f"piso {reais(pld['piso'])} · teto estrutural {reais(pld['teto'])}, do ano"]
    )
    ressalva_pld = (
        "Ponderado pelo consumo do consumidor-exemplo (antes de 2021, o PLD semanal agregado)"
        if pld["fonte"] == "ponderado"
        else "PLD semanal agregado por mês, sem ponderar pelo consumo"
    )
    return [
        {
            "ressalva": CHAVES["se_co"],
            "rotulo": f"Carga em {mes(carga['mes'])}",
            "valor": f"{cal.numero(carga['mwm'], 0)} MWm",
            "linhas": anterior,
            "ajuda": glossario.TERMOS["MWm"],
        },
        {
            "ressalva": ressalva_pld,
            "rotulo": f"PLD em {mes(pld['mes'])}",
            "valor": f"{vis.reais(pld['rs_mwh'])}/MWh",
            "linhas": limites,
            "ajuda": f"{glossario.TERMOS['PLD']} {glossario.TERMOS['PLD ponderado']}",
        },
    ]


# ---------------------------------------------------------------- gráficos


def legenda_carga(ultimo_ajuste: pd.Timestamp) -> str:
    return (
        f"{CHAVES['se_co']}. A reconstruída tem a mesma definição em todo o período; a linha "
        f"vertical marca a quebra do tipo III ({mes(cal.QUEBRA_TIPO_III)}). As séries só "
        f"diferem até {mes(ultimo_ajuste)}; depois coincidem."
    )


def legenda_pld(ultimo_semanal: pd.Timestamp) -> str:
    return (
        f"São **{CHAVES['duas_contas']}**: o PLD semanal agregado por mês, até "
        f"{mes(ultimo_semanal)}, e o ponderado pelo consumo do consumidor-exemplo, de 2021 em "
        "diante; a série não é contínua. Piso e teto estrutural (tracejados) só existem de 2021 "
        "em diante."
    )


# ---------------------------------------------------------------- limites


def limites(data: str, meses_incompletos: list[str]) -> list[str]:
    itens = [
        f"**{CHAVES['reservatorios']}.**",
        "**Nada aqui é do consumidor-exemplo**: a carga é do SE/CO inteiro e o peso do PLD de "
        "2021 em diante é o consumo dele (sintético).",
        f"**É o estado de {data}**, {CHAVES['nao_ao_vivo']}.",
    ]
    if meses_incompletos:
        nomes = ", ".join(mes(m) for m in meses_incompletos)
        itens[-1] = itens[-1][:-1] + f"; {nomes} ainda não fechou e fica de fora."
    return itens


# ---------------------------------------------------------------- auditoria


def auditoria(manifesto: dict, carga: pd.DataFrame, pld: pd.DataFrame) -> str:
    arquivos = manifesto["arquivos"]
    incompletos = ", ".join(manifesto["meses_incompletos"].get("carga_mensal_se.csv", []))
    incompletos = incompletos or "nenhum"

    def fonte(nome: str) -> str:
        a = arquivos[nome]
        tabelas = ", ".join(f"`{f['tabela']}`" for f in a["fontes"])
        return f"`{nome}` ({a['linhas']} linhas, sha256 `{a['sha256'][:12]}`), de {tabelas}"

    return (
        f"**Fontes.** {fonte('carga_mensal_se.csv')}; {fonte('pld_mensal_se.csv')}. A página lê "
        f"só esses dois arquivos; mostra {len(carga)} meses de carga (fechados) e {len(pld)} de "
        "PLD.\n\n"
        "**Meses incompletos.** A carga do mês em andamento (cobertura abaixo de 100%) não entra "
        f"({incompletos}).\n\n"
        f"**Quebra do tipo III.** Marcada em {mes(cal.QUEBRA_TIPO_III)} "
        '(`docs/metricas.md`, "Usinas não despachadas (tipo III), 01/03/2021"); um teste confere, '
        "contra os dados, que a razão entre a reconstruída e a original (comparada com o mesmo "
        "mês de 2020) só cai de março em diante.\n\n"
        "**PLD.** `fonte` = `semanal` até dez/2020 (agregado pelo código dos cenários) e "
        "`ponderado` de 2021 em diante (`fct_pld_ponderado_mensal`); piso e teto estrutural vêm da "
        "seed `pld_limites`, só a partir de 2021, e nenhum deles é assumido "
        "(`limites_assumidos` = `False`)."
    )
