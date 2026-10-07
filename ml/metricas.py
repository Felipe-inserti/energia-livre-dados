"""Métricas da previsão mensal (tarefa 4.6), todas sobre pares (previsto, real) em MWmed.

    erro      = previsto - real            (positivo: previu ACIMA do real)
    MAPE      = média de |erro| / real, em %
    MAE       = média de |erro|, em MWmed
    viés      = média do erro com SINAL, em MWmed e em % (média de erro / real)

POR QUE O VIÉS. O contrato é decidido uma vez por ano: errar para cima (sobra energia contratada,
vendida ao PLD) e para baixo (falta energia, comprada ao PLD) custam diferente conforme o PLD
contra o preço do contrato. O MAPE e o MAE escondem o sinal; o viés o mostra.

ERRO ANUAL. Para a origem de dezembro (a decisão do contrato), compara-se a média dos 12 meses
previstos com a média dos 12 reais do ano: é o erro que importa ao volume contratado.
"""

from dataclasses import dataclass
from datetime import date

from ml.validacao import HORIZONTES


@dataclass(frozen=True)
class Registro:
    serie: str
    baseline: str
    origem: date
    horizonte: int
    alvo: date
    previsto: float
    real: float

    @property
    def erro(self) -> float:
        return self.previsto - self.real


def metricas(registros: list[Registro]) -> dict[str, float | int | None]:
    n = len(registros)
    if n == 0:
        return {"n": 0, "mape_pct": None, "mae_mwmed": None, "vies_mwmed": None, "vies_pct": None}
    return {
        "n": n,
        "mape_pct": 100 * sum(abs(r.erro) / r.real for r in registros) / n,
        "mae_mwmed": sum(abs(r.erro) for r in registros) / n,
        "vies_mwmed": sum(r.erro for r in registros) / n,
        "vies_pct": 100 * sum(r.erro / r.real for r in registros) / n,
    }


def por_horizonte(registros: list[Registro]) -> list[dict]:
    """Uma linha por horizonte (1..12) e uma `geral` (todos os pares juntos)."""
    linhas = [
        {"horizonte": h, **metricas([r for r in registros if r.horizonte == h])} for h in HORIZONTES
    ]
    return [*linhas, {"horizonte": "geral", **metricas(registros)}]


def erro_anual(registros: list[Registro]) -> list[dict]:
    """Erro do ano inteiro, por ano-alvo, só para anos em que os 12 meses têm previsão.

    Espera registros de UMA série, UM baseline e origens de dezembro (cada ano-alvo tem então um
    registro por horizonte). Compara a média dos 12 previstos com a média dos 12 reais.
    """
    por_ano: dict[int, list[Registro]] = {}
    for r in registros:
        por_ano.setdefault(r.alvo.year, []).append(r)
    linhas = []
    for ano, rs in sorted(por_ano.items()):
        if len(rs) != len(HORIZONTES) or {r.horizonte for r in rs} != set(HORIZONTES):
            continue
        previsto = sum(r.previsto for r in rs) / len(rs)
        real = sum(r.real for r in rs) / len(rs)
        linhas.append(
            {
                "ano": ano,
                "previsto_medio_mwmed": previsto,
                "real_medio_mwmed": real,
                "erro_mwmed": previsto - real,
                "erro_pct": 100 * (previsto - real) / real,
            }
        )
    return linhas
