"""Intervalos de previsão a partir dos erros empíricos, e a regra de calibração SEM vazamento.

O erro de uma previsão é medido em log, `log(real / previsto)`: o intervalo é `previsto * exp(q)`,
sempre positivo e proporcional ao nível. Cada erro tem a origem, o horizonte e o mês-alvo; um erro
só é CONHECIDO quando o mês-alvo já passou.

DUAS REGRAS DE CALIBRAÇÃO (docs/decisoes.md, Parte B):
- PRODUÇÃO (previsões além dos dados): todos os erros disponíveis, do desenvolvimento e do teste
  final juntos (`modo="producao"`).
- BACKTEST da Sprint 6: calibração CRESCENTE no tempo (`modo="crescente"`). Na origem `t`, os
  quantis e a reamostragem usam só os erros cujo mês-alvo é `<= t` (um vetor de 12 erros só entra
  quando o ÚLTIMO mês-alvo dele, origem + 12 meses, é `<= t`). Usar os erros de 2023-2024 nos
  cenários da origem dez/2022 seria vazamento e deixaria a economia em R$ otimista.

Tudo aqui é função pura sobre listas de `Erro`; não lê nem grava nada.
"""

import math
import random
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from ml.validacao import HORIZONTES, somar_meses

NIVEIS = {"p025": 0.025, "p10": 0.10, "p50": 0.50, "p90": 0.90, "p975": 0.975}
MIN_ERROS_POR_HORIZONTE = 30  # com menos que isso o quantil de 2,5% / 97,5% não tem sentido


@dataclass(frozen=True)
class Erro:
    origem: date
    horizonte: int
    alvo: date
    log_razao: float  # log(real / previsto)


def erro_de(origem: date, horizonte: int, previsto: float, real: float) -> Erro:
    return Erro(origem, horizonte, somar_meses(origem, horizonte), math.log(real / previsto))


def ultimo_alvo_do_vetor(origem: date) -> date:
    """O último mês-alvo do vetor de 12 erros de uma origem."""
    return somar_meses(origem, max(HORIZONTES))


def erros_conhecidos_em(erros: Iterable[Erro], t: date) -> list[Erro]:
    """Os erros que já eram conhecidos na origem `t`: mês-alvo `<= t`."""
    return [e for e in erros if e.alvo <= t]


def vetores_completos_ate(erros: Iterable[Erro], t: date) -> dict[date, list[float]]:
    """origem -> [erro h=1, ..., h=12]; só origens com os 12 horizontes e último alvo `<= t`."""
    por_origem: dict[date, dict[int, float]] = {}
    for e in erros:
        por_origem.setdefault(e.origem, {})[e.horizonte] = e.log_razao
    return {
        o: [h_erros[h] for h in HORIZONTES]
        for o, h_erros in sorted(por_origem.items())
        if set(h_erros) == set(HORIZONTES) and ultimo_alvo_do_vetor(o) <= t
    }


def _quantil(valores: list[float], q: float) -> float:
    """Quantil por interpolação linear (o mesmo método do pandas/numpy padrão)."""
    v = sorted(valores)
    pos = q * (len(v) - 1)
    i = int(math.floor(pos))
    j = min(i + 1, len(v) - 1)
    return v[i] + (v[j] - v[i]) * (pos - i)


def quantis_por_horizonte(
    erros: Iterable[Erro], minimo: int = MIN_ERROS_POR_HORIZONTE
) -> dict[int, dict[str, float]]:
    """Quantis do erro em log por horizonte. Falha se algum horizonte tiver menos que `minimo`."""
    erros = list(erros)
    saida = {}
    for h in HORIZONTES:
        valores = [e.log_razao for e in erros if e.horizonte == h]
        if len(valores) < minimo:
            raise ValueError(f"horizonte {h}: {len(valores)} erros conhecidos, mínimo {minimo}")
        saida[h] = {nome: _quantil(valores, q) for nome, q in NIVEIS.items()}
    return saida


def calibrar(
    erros: Iterable[Erro], *, modo: str, origem: date | None = None
) -> dict[int, dict[str, float]]:
    """Quantis por horizonte. `modo`: "producao" (tudo) ou "crescente" (só alvo `<= origem`)."""
    if modo == "producao":
        return quantis_por_horizonte(erros)
    if modo == "crescente":
        if origem is None:
            raise ValueError("a calibração crescente exige a origem")
        return quantis_por_horizonte(erros_conhecidos_em(erros, origem))
    raise ValueError(f"modo desconhecido: {modo!r}")


def intervalo(previsto: float, quantis: dict[str, float]) -> dict[str, float]:
    """Previsão e limites em MWmed: `previsto * exp(q)` (p025/p975 = 95%, p10/p90 = 80%)."""
    return {nome: previsto * math.exp(q) for nome, q in quantis.items()}


def reamostrar_origens(
    erros: Iterable[Erro], origem: date, n: int, semente: int = 0
) -> list[list[float]]:
    """`n` vetores de 12 erros sorteados (com reposição) entre os vetores completos CONHECIDOS em
    `origem`. A unidade do sorteio é a origem inteira, o que preserva a correlação entre meses."""
    vetores = list(vetores_completos_ate(erros, origem).values())
    if not vetores:
        raise ValueError(f"nenhum vetor completo conhecido em {origem}")
    rng = random.Random(semente)
    return [list(rng.choice(vetores)) for _ in range(n)]
