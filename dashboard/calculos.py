"""Cálculos e formatação do dashboard: funções puras sobre os DataFrames de `leitura.py`.

Sem Streamlit e sem leitura de arquivo. Os números que a tela mostra com ressalva (a concentração do
ganho em 2022 e 2025, a decomposição por ano, a tabela de f) saem daqui e são testados contra os
valores já publicados em `docs/metricas.md` e `docs/decisoes.md`.
"""

import pandas as pd

from dashboard.leitura import ESTRATEGIAS, ORDEM_SENSIBILIDADES, RECORTE_5_ANOS

ANOS = (2021, 2022, 2023, 2024, 2025)
ANOS_NAO_ELEGIVEIS = (
    2021,
    2022,
    2023,
)  # Portaria MME 465/2019 (premissas, seção 1): ainda não podia migrar
ANOS_DESTAQUE = (2022, 2025)  # onde o valor da otimização se concentrou
BANDA_DO_CASO_BASE = 0.10
ESPECULATIVAS = ("rmax120",)  # excluída do caso base (D13): rotulada, nunca escolhida


# ---------------------------------------------------------------- formatação (padrão brasileiro)


def numero(valor: float, casas: int = 2, sinal: bool = False) -> str:
    """1234.5 -> '1.234,50'. Com `sinal`, mostra '+' nos positivos e '−' (menos tipográfico)."""
    if valor is None or pd.isna(valor):
        return "—"
    texto = f"{abs(valor):,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if round(abs(valor), casas) == 0:
        return texto
    if valor < 0:
        return "−" + texto
    return ("+" + texto) if sinal else texto


def reais(valor: float, casas: int = 2, sinal: bool = False) -> str:
    texto = numero(valor, casas, sinal)
    if texto.startswith(("+", "−")):
        return f"{texto[0]}R$ {texto[1:]}"
    return f"R$ {texto}"


def percentual(valor: float, casas: int = 2, sinal: bool = False) -> str:
    return f"{numero(valor, casas, sinal)}%"


# ---------------------------------------------------------------- backtest


def _linha(economia: pd.DataFrame, sens_id: str, recorte: str) -> pd.Series:
    sel = economia[(economia["sens_id"] == sens_id) & (economia["recorte"].astype(str) == recorte)]
    if len(sel) != 1:
        raise ValueError(f"esperava 1 linha para {sens_id} / {recorte}, achei {len(sel)}")
    return sel.iloc[0]


def resultado(
    economia: pd.DataFrame, sens_id: str = "caso_base", recorte: str = RECORTE_5_ANOS
) -> dict:
    """Valor da previsão, da otimização e economia total (R$ e %) de um recorte."""
    x = _linha(economia, sens_id, recorte)
    campos = (
        "valor_previsao_rs",
        "valor_previsao_pct",
        "valor_otimizacao_rs",
        "valor_otimizacao_pct",
        "economia_total_rs",
        "economia_total_pct",
        "custo_ingenua_rs",
        "custo_pontual_rs",
        "custo_otimizada_rs",
    )
    return {c: float(x[c]) for c in campos}


def por_ano(
    economia: pd.DataFrame, anual: pd.DataFrame, sens_id: str = "caso_base"
) -> pd.DataFrame:
    """Uma linha por ano (2021 a 2025): valor da previsão e da otimização, r* e marcas."""
    ot = anual[(anual["sens_id"] == sens_id) & (anual["estrategia"] == "otimizada")].set_index(
        "ano"
    )
    linhas = []
    for ano in ANOS:
        x = _linha(economia, sens_id, str(ano))
        r = float(ot.loc[ano, "razao_v_pontual"])
        limites = (1 / (1 + BANDA_DO_CASO_BASE), 1 / (1 - BANDA_DO_CASO_BASE))
        linhas.append(
            {
                "ano": ano,
                "valor_previsao_rs": float(x["valor_previsao_rs"]),
                "valor_otimizacao_rs": float(x["valor_otimizacao_rs"]),
                "economia_total_rs": float(x["economia_total_rs"]),
                "economia_total_pct": float(x["economia_total_pct"]),
                "r_otimizada": r,
                "v_otimizada_mwm": float(ot.loc[ano, "v_mwm"]),
                "no_limite": bool(min(abs(r - limites[0]), abs(r - limites[1])) < 1e-4),
                "nao_elegivel": ano in ANOS_NAO_ELEGIVEIS,
                "cobertura_abaixo_de_100": bool(ot.loc[ano, "cobertura_abaixo_de_100"]),
                "rotulo": str(ano),  # o ano é sempre texto, nunca "2.021"
            }
        )
    return pd.DataFrame(linhas)


def concentracao(anos: pd.DataFrame, destaque: tuple[int, ...] = ANOS_DESTAQUE) -> dict:
    """Quanto do valor da otimização veio dos anos em destaque (2022 e 2025).

    Todos os agregados saem dos valores EXATOS e são arredondados uma vez, na hora de exibir (regra
    da página: nada é somado de valores já arredondados). Com os valores exatos, 2022 + 2025
    = R$ 9.202,62, 2023 + 2024 = −R$ 182,43 e o total = R$ 9.020,19; e 9.202,62 − 182,43 + 0,00 =
    9.020,19 ao centavo."""
    exatos = {
        int(a): float(v) for a, v in zip(anos["ano"], anos["valor_otimizacao_rs"], strict=True)
    }
    total = float(sum(exatos.values()))
    destacados = float(sum(exatos[a] for a in destaque))
    outros = {a: v for a, v in exatos.items() if a not in destaque}
    return {
        "anos_destaque": list(destaque),
        "soma_destacados_rs": destacados,
        "total_rs": total,
        "pct_do_total": 100.0 * destacados / total if total else float("nan"),
        "soma_outros_rs": float(sum(outros.values())),
        "outros": outros,
    }


def custos_por_ano(anual: pd.DataFrame, sens_id: str = "caso_base") -> pd.DataFrame:
    """Custo anual das 3 estratégias (linhas = ano, colunas = estratégia)."""
    x = anual[anual["sens_id"] == sens_id]
    return x.pivot(index="ano", columns="estrategia", values="custo_rs")[list(ESTRATEGIAS)]


def tabela_f(banda: pd.DataFrame, recorte: str = RECORTE_5_ANOS) -> pd.DataFrame:
    """Valor da previsão e da otimização em função de f, num recorte."""
    x = banda[banda["recorte"].astype(str) == recorte].sort_values("f")
    return x[
        ["f", "sens_id", "valor_previsao_rs", "valor_otimizacao_rs", "economia_total_rs"]
    ].reset_index(drop=True)


def tabela_f_por_ano(banda: pd.DataFrame) -> pd.DataFrame:
    x = banda[banda["recorte"].astype(str).isin([str(a) for a in ANOS])].copy()
    x["ano"] = x["recorte"].astype(int)
    return (
        x[["f", "ano", "valor_previsao_rs", "valor_otimizacao_rs", "r_otimizada"]]
        .sort_values(["f", "ano"])
        .reset_index(drop=True)
    )


def tabela_sensibilidades(sens: pd.DataFrame, recorte: str = RECORTE_5_ANOS) -> pd.DataFrame:
    """As 14 linhas (caso base + 13), NA ORDEM DO PLANO (nunca por economia), com a marca da
    especulativa."""
    x = sens[sens["recorte"].astype(str) == recorte].copy()
    x["especulacao_excluida"] = x["sens_id"].isin(ESPECULATIVAS)
    if list(x["sens_id"]) != list(ORDEM_SENSIBILIDADES):
        raise ValueError("as sensibilidades não estão na ordem do plano")
    return x.reset_index(drop=True)


# ---------------------------------------------------------------- prévia e série


def resumo_da_previa(previa: pd.DataFrame) -> dict:
    """Janela, preço e volumes da prévia (sem nenhum número de economia: não há realizado)."""
    if previa.empty:
        return {}
    p = previa.set_index("estrategia")
    return {
        "origem": previa["origem"].iloc[0],
        "execucao_id": str(previa["execucao_id"].iloc[0]),
        "tipo": previa["tipo"].iloc[0],
        "janela_inicio": previa["janela_inicio"].iloc[0],
        "janela_fim": previa["janela_fim"].iloc[0],
        "preco_rs_mwh": float(previa["preco_contrato_rs_mwh"].iloc[0]),
        "limites_assumidos": bool(previa["limites_assumidos"].iloc[0]),
        "v_mwm": {e: float(p.loc[e, "v_mwm"]) for e in p.index},
        "r": {e: float(p.loc[e, "razao_v_pontual"]) for e in p.index},
    }


def pld_esperado_da_origem(
    esperado: pd.DataFrame, execucao_id: str, origem, metodo: str = "blocos"
) -> float:
    """PLD esperado (R$/MWh) dos cenários que decidiram a `origem` (método do caso base: blocos)."""
    sel = esperado[
        (esperado["execucao_id"] == execucao_id)
        & (esperado["origem"] == pd.Timestamp(origem))
        & (esperado["metodo"] == metodo)
    ]
    if len(sel) != 1:
        raise ValueError(f"esperava 1 PLD esperado para {execucao_id}/{origem}, achei {len(sel)}")
    return float(sel["pld_esperado_rs_mwh"].iloc[0])


def esperado_x_contrato(
    anual: pd.DataFrame, esperado: pd.DataFrame, execucao_id: str, sens_id: str = "caso_base"
) -> pd.DataFrame:
    """Por ano decidido: preço do contrato `P_t`, PLD esperado dos cenários, a diferença e o r*."""
    ot = anual[(anual["sens_id"] == sens_id) & (anual["estrategia"] == "otimizada")].set_index(
        "ano"
    )
    linhas = []
    for ano in ANOS:
        e = pld_esperado_da_origem(esperado, execucao_id, pd.Timestamp(ano - 1, 12, 1))
        p = float(ot.loc[ano, "preco_contrato_rs_mwh"])
        linhas.append(
            {
                "ano": ano,
                "preco_contrato_rs_mwh": p,
                "pld_esperado_rs_mwh": e,
                "contrato_menos_esperado": p - e,
                "r_otimizada": float(ot.loc[ano, "razao_v_pontual"]),
            }
        )
    return pd.DataFrame(linhas)


def leitura_da_regra(preco: float, esperado: float, r: float) -> dict:
    """A frase da prévia: PLD esperado contra o contrato e o sentido da decisão (r contra 1).

    Só diz "contrata menos/mais" quando o sinal de `P − E[PLD]` e o de `r − 1` batem (a regra do
    backtest: contrato acima do esperado, contrata menos; abaixo, contrata mais); senão, descreve
    sem afirmar a causa."""
    base = f"PLD esperado {reais(esperado)}/MWh contra contrato de {reais(preco)}/MWh"
    r_txt = numero(r, 3)
    if abs(r - 1) < 1e-9:
        sentido, texto = "igual", f"{base} → contrata o mesmo que a previsão ({r_txt}× a previsão)"
    elif preco > esperado and r < 1:
        sentido, texto = "menos", f"{base} → contrata menos que a previsão ({r_txt}× a previsão)"
    elif preco < esperado and r > 1:
        sentido, texto = "mais", f"{base} → contrata mais que a previsão ({r_txt}× a previsão)"
    else:
        sentido, texto = (
            "indefinido",
            f"{base}; volume de {r_txt}× a previsão (o sinal da diferença não explica o volume)",
        )
    return {"sentido": sentido, "texto": texto, "diferenca_rs_mwh": preco - esperado}


def ate_o_mes(df: pd.DataFrame, ultimo: pd.Timestamp, coluna: str = "mes") -> pd.DataFrame:
    """Corta a série no último mês fechado (a rede de segurança do gráfico)."""
    return df[df[coluna] <= pd.Timestamp(ultimo)].reset_index(drop=True)


def mes_por_extenso(d) -> str:
    meses = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
    d = pd.Timestamp(d)
    return f"{meses[d.month - 1]}/{d.year}"


# ---------------------------------------------------------------- saúde


def resumo_dos_testes(testes: pd.DataFrame) -> dict:
    return {
        "testes": int(testes["testes"].sum()),
        "pass": int(testes["pass"].sum()),
        "warn": int(testes["warn"].sum()),
        "error": int(testes["error"].sum()),
    }


def ultima_execucao(execucoes: pd.DataFrame) -> pd.DataFrame:
    """As tasks da execução mais recente (pelo início)."""
    if execucoes.empty:
        return execucoes
    ultimo = execucoes["inicio_utc"].max()
    return execucoes[execucoes["inicio_utc"] == ultimo].reset_index(drop=True)


# ---------------------------------------------------------------- textos da Decisão (números)


def meses_fora_da_faixa(anual: pd.DataFrame, sens_id: str = "caso_base") -> tuple[int, int]:
    """Mínimo e máximo de meses por ano fora da faixa, da ingênua e da pontual."""
    x = anual[(anual["sens_id"] == sens_id) & anual["estrategia"].isin(["ingenua", "pontual"])]
    return int(x["meses_fora_da_faixa"].min()), int(x["meses_fora_da_faixa"].max())


def r_no_limite(anos: pd.DataFrame) -> tuple[int, str]:
    """(quantos anos com r* no limite da grade, descrição: '0,909 em 2022; 1,111 em 2023, ...')."""
    no_limite = anos[anos["no_limite"]]
    grupos: dict[float, list[int]] = {}
    for ano, r in zip(no_limite["ano"], no_limite["r_otimizada"], strict=True):
        grupos.setdefault(round(r, 3), []).append(int(ano))
    partes = []
    for r, lista in sorted(grupos.items()):
        if len(lista) == 1:
            anos_txt = str(lista[0])
        else:
            anos_txt = ", ".join(map(str, lista[:-1])) + f" e {lista[-1]}"
        partes.append(f"{numero(r, 3)} em {anos_txt}")
    return len(no_limite), "; ".join(partes)


def data_br(texto: str) -> str:
    """'2026-10-10T16:47:55Z' -> '10/10/2026'."""
    d = pd.Timestamp(texto)
    return f"{d.day:02d}/{d.month:02d}/{d.year}"


def hora_utc(texto: str) -> str:
    d = pd.Timestamp(texto)
    return f"{d.day:02d}/{d.month:02d}/{d.year} {d.hour:02d}:{d.minute:02d} UTC"
