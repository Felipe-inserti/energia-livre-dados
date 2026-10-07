"""Validação temporal de todos os modelos (tarefa 4.6): origem móvel, horizontes de 1 a 12 meses.

COMO FUNCIONA. Uma ORIGEM é o último mês cujo valor já se conhece. Dela se prevê cada um dos 12
meses seguintes (horizonte `h` = 1..12; o alvo é origem + h). A origem anda um mês de cada vez, e a
janela de treino CRESCE com ela: em cada origem o modelo vê a série inteira desde o início (2000)
até a origem, e nada depois. Isso é garantido por construção: quem prevê só recebe
`visao_na_origem`, nunca a série completa (o vazamento de futuro fica impossível, não só
improvável).

PERÍODOS. Cada período é um conjunto de ALVOS:
    desenvolvimento  2012-01 a 2019-12  escolhe-se modelo aqui
    estresse_2020    2020-01 a 2020-12  pandemia; reportado à parte, nunca misturado
    teste_final      2021-01 a 2025-12  usado UMA vez, no fim; alinhado ao backtest da Sprint 6
O teste final é protegido: o CLI recusa rodá-lo sem a opção explícita (`ml/avaliar.py`).

SÉRIE. Só entram meses UTILIZÁVEIS (`mes_utilizavel` do `fct_carga_mensal`: mês fechado com
cobertura suficiente). O mês corrente e qualquer mês sem cobertura somem da série: não são alvo
(sem valor real não há erro) nem treino (a previsão que dependeria deles não é feita).
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date

HORIZONTES = tuple(range(1, 13))

Serie = dict[date, float]  # primeiro dia do mês -> carga média do mês, em MWmed


@dataclass(frozen=True)
class Periodo:
    nome: str
    alvo_inicio: date  # primeiro dia do primeiro mês-alvo
    alvo_fim: date  # primeiro dia do último mês-alvo (inclusive)
    final: bool = False  # True: só roda com autorização explícita


PERIODOS: dict[str, Periodo] = {
    "desenvolvimento": Periodo("desenvolvimento", date(2012, 1, 1), date(2019, 12, 1)),
    "estresse_2020": Periodo("estresse_2020", date(2020, 1, 1), date(2020, 12, 1)),
    "teste_final": Periodo("teste_final", date(2021, 1, 1), date(2025, 12, 1), final=True),
}


@dataclass(frozen=True)
class Par:
    origem: date
    horizonte: int
    alvo: date


def somar_meses(mes: date, n: int) -> date:
    """O primeiro dia do mês `n` meses depois (ou antes, se `n` < 0) de `mes`."""
    indice = mes.year * 12 + (mes.month - 1) + n
    return date(indice // 12, indice % 12 + 1, 1)


def meses_entre(inicio: date, fim: date) -> list[date]:
    """Todos os meses de `inicio` a `fim`, inclusive."""
    saida, mes = [], inicio
    while mes <= fim:
        saida.append(mes)
        mes = somar_meses(mes, 1)
    return saida


def serie_utilizavel(linhas: Iterable[Mapping], coluna: str) -> Serie:
    """Série mês -> valor só com os meses utilizáveis e com valor (a ajustada começa em 2018)."""
    return {
        linha["mes"]: float(linha[coluna])
        for linha in linhas
        if linha["mes_utilizavel"] and linha[coluna] is not None
    }


def visao_na_origem(serie: Serie, origem: date) -> Serie:
    """O que se sabe na origem: a série até ela, inclusive. A ÚNICA coisa que um modelo recebe."""
    return {mes: valor for mes, valor in serie.items() if mes <= origem}


def pares(periodo: Periodo) -> list[Par]:
    """Todos os (origem, horizonte, alvo) com alvo no período, por origem e horizonte."""
    todos = [
        Par(somar_meses(alvo, -h), h, alvo)
        for alvo in meses_entre(periodo.alvo_inicio, periodo.alvo_fim)
        for h in HORIZONTES
    ]
    return sorted(todos, key=lambda p: (p.origem, p.horizonte))
