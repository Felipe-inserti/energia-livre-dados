"""Baselines de previsão mensal (tarefa 4.5): sem treino, só regras sobre o histórico até a origem.

Cada função recebe SÓ o histórico visível na origem (`visao_na_origem`) e devolve a previsão do mês
`origem + horizonte`, ou None se faltar algum mês necessário (nesse caso não há previsão, e o par
fica fora das métricas em vez de ser preenchido).

1. sazonal_ingenuo: o mesmo mês do ano anterior, y[alvo - 12]. Para h <= 12 esse mês é sempre
   anterior à origem, então a previsão NÃO depende da origem: o erro é igual em todos os horizontes.
   Isso é propriedade do baseline, não defeito da validação, e há um teste que a garante.
2. sazonal_crescimento: o sazonal ingênuo vezes o crescimento dos últimos 12 meses conhecidos,
   G = soma(y[origem-11 .. origem]) / soma(y[origem-23 .. origem-12]). Depende da origem, então o
   erro varia com o horizonte, e serve para exercitar a tabela por horizonte.
"""

from datetime import date

from ml.validacao import HORIZONTES, Serie, somar_meses


def _checar_horizonte(horizonte: int) -> None:
    if horizonte not in HORIZONTES:
        # com h > 12 o "mesmo mês do ano anterior" estaria depois da origem: vazamento de futuro
        raise ValueError(f"horizonte {horizonte} fora de 1..12")


def sazonal_ingenuo(historico: Serie, origem: date, horizonte: int) -> float | None:
    _checar_horizonte(horizonte)
    return historico.get(somar_meses(origem, horizonte - 12))


def sazonal_crescimento(historico: Serie, origem: date, horizonte: int) -> float | None:
    base = sazonal_ingenuo(historico, origem, horizonte)
    if base is None:
        return None
    recentes = [historico.get(somar_meses(origem, -i)) for i in range(12)]
    anteriores = [historico.get(somar_meses(origem, -i)) for i in range(12, 24)]
    if any(v is None for v in (*recentes, *anteriores)):
        return None
    return base * sum(recentes) / sum(anteriores)


BASELINES = {
    "sazonal_ingenuo": sazonal_ingenuo,
    "sazonal_crescimento": sazonal_crescimento,
}
