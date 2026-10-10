"""Modelo de custo do contrato (6.1): custo mensal e anual, exposição e preço do contrato.

Regras de `docs/premissas.md`, seção 4. Para o mês `m`, com `f` a banda de flexibilidade:

    V_m     = V × horas_m                       (MWh contratados; V em MWm, plano nos meses)
    [a, b]  = [V_m (1 − f), V_m (1 + f)]        (faixa apurada por mês)
    E_m     = min(max(C_m, a), b)               (energia contratada efetivamente entregue)
    custo_m = E_m × P + (C_m − E_m) × PLDp_m    (a diferença é liquidada pelo PLD ponderado)

`C_m − E_m > 0` é compra do excedente pelo PLD ("descoberto"); `< 0` é venda da sobra pelo PLD
("sobrando"). Dentro da faixa o custo é `C_m × P` e não depende de `V`.

Funções puras e vetorizadas (numpy): os argumentos podem ser escalares, vetores de 12 meses ou
matrizes (cenários × meses); o mesmo código serve a um mês, ao realizado e à grade da otimização.
Nenhuma função lê dados: quem chama decide que informação entra (a convenção da origem fica fora).
"""

from dataclasses import dataclass

import numpy as np

SPREAD_PADRAO = 20.0  # R$/MWh, caso base (premissas.md, seção 4)
BANDA_PADRAO = 0.10


@dataclass(frozen=True)
class CustoMensal:
    """Resultado por mês (mesma forma dos argumentos, após o broadcast)."""

    contratado_mwh: np.ndarray  # V_m
    piso_mwh: np.ndarray  # a = V_m (1 − f)
    teto_mwh: np.ndarray  # b = V_m (1 + f)
    entregue_mwh: np.ndarray  # E_m
    custo: np.ndarray  # R$
    descoberto_mwh: np.ndarray  # max(C − b, 0): comprado pelo PLD acima da faixa
    sobrando_mwh: np.ndarray  # max(a − C, 0): vendido pelo PLD abaixo da faixa


def _checar_banda(f: float) -> None:
    if not 0 <= f < 1:
        raise ValueError(f"banda f deve estar em [0, 1): {f!r}")


def faixa(v_mwm, horas, f: float):
    """(V_m, a, b): energia contratada do mês e os limites da faixa de flexibilidade."""
    _checar_banda(f)
    v = np.asarray(v_mwm, dtype=float)
    h = np.asarray(horas, dtype=float)
    if np.any(v < 0):
        raise ValueError("V não pode ser negativo")
    if np.any(h <= 0):
        raise ValueError("horas do mês devem ser positivas")
    v_m = v * h
    return v_m, v_m * (1 - f), v_m * (1 + f)


def custo_mensal(consumo_mwh, v_mwm, horas, f: float, preco, pld_ponderado) -> CustoMensal:
    """Custo do mês: `E × P + (C − E) × PLDp`, e a exposição ao PLD (descoberto e sobrando).

    `consumo_mwh` e `pld_ponderado` são `C_m` e `PLDp_m` (R$/MWh); `preco` é `P_t`."""
    c = np.asarray(consumo_mwh, dtype=float)
    p = np.asarray(preco, dtype=float)
    pld = np.asarray(pld_ponderado, dtype=float)
    if np.any(c < 0):
        raise ValueError("consumo não pode ser negativo")
    v_m, a, b = faixa(v_mwm, horas, f)
    e = np.minimum(np.maximum(c, a), b)
    return CustoMensal(
        contratado_mwh=v_m,
        piso_mwh=a,
        teto_mwh=b,
        entregue_mwh=e,
        custo=e * p + (c - e) * pld,
        descoberto_mwh=np.maximum(c - b, 0.0),
        sobrando_mwh=np.maximum(a - c, 0.0),
    )


def custo_anual(consumo_mwh, v_mwm, horas, f: float, preco, pld_ponderado, eixo: int = -1):
    """Soma dos meses (último eixo por padrão): R$ do ano. Com matriz cenários × meses, um valor
    por cenário."""
    return custo_mensal(consumo_mwh, v_mwm, horas, f, preco, pld_ponderado).custo.sum(axis=eixo)


def preco_do_contrato(pld_medio_ano_anterior: float, spread: float = SPREAD_PADRAO) -> float:
    """`P_t` = PLD médio do ano `t−1` + spread (premissas, seção 4). Só informação de `t−1`: quem
    chama passa a média do ano anterior, nunca a do próprio ano."""
    if pld_medio_ano_anterior < 0:
        raise ValueError("PLD médio negativo")
    return float(pld_medio_ano_anterior) + float(spread)


def volume_medio_mwm(consumo_mwh, horas) -> float:
    """Consumo médio em MWm: `Σ C / Σ horas`. Dá o `V` da estratégia ingênua (consumo realizado do
    ano anterior) e da pontual (consumo previsto do ano)."""
    c = np.asarray(consumo_mwh, dtype=float)
    h = np.asarray(horas, dtype=float)
    if c.shape != h.shape or c.ndim != 1:
        raise ValueError("consumo e horas devem ser vetores do mesmo tamanho")
    if h.sum() <= 0:
        raise ValueError("horas somam zero")
    return float(c.sum() / h.sum())
