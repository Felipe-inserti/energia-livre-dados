"""Detector de piso do PLD por ano (5.7): o mínimo que se REPETE em vários blocos de tempo.

O piso do PLD é uma constante regulatória, fixa no ano civil. Quando ele limita o preço, o mercado
"bate no piso" várias vezes, em períodos separados. Um mínimo que aparece uma vez só (ou numa
sequência de horas de um mesmo dia) é um resultado de mercado, não o piso.

CRITÉRIO DE REPETIÇÃO (docs/decisoes.md): o menor valor do ano é o piso se aparecer em pelo menos
`MINIMO_BLOCOS` (3) blocos DISTINTOS de tempo, com tolerância de meio centavo.
- O bloco é a unidade de decisão independente: a SEMANA no PLD semanal (os 3 patamares de uma semana
  muitas vezes têm o mesmo preço, o que é um resultado só) e o DIA local no PLD horário (horas
  seguidas do mesmo dia no piso são, em geral, um evento só).
- Por que 3 e não 2: dois blocos no mesmo valor ainda cabem na coincidência; três separam o piso das
  coincidências a um centavo, que são raras. O número não vem de uma distribuição: é o mínimo
  conservador. A sensibilidade (2 e 5 blocos) acompanha a tabela do relatório.
- Ano em que o mínimo não se repete: o piso NÃO se detecta (o mercado ficou acima dele o ano todo,
  ou o piso mudou no meio do ano). O status diz qual caso aparece: `minimo_unico` ou
  `repetido_acima`.

Funções puras sobre listas de (bloco, valor).
"""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

MINIMO_BLOCOS = 3
TOLERANCIA = 0.005  # R$/MWh: os preços têm 2 casas decimais


@dataclass(frozen=True)
class PisoDetectado:
    ano: int
    minimo: float  # menor valor observado no ano
    repeticoes: int  # observações (patamares ou horas) iguais ao mínimo
    blocos: int  # semanas ou dias distintos com o mínimo
    observacoes: int
    status: str  # detectado | repetido_acima | minimo_unico
    menor_repetido: float | None  # menor valor que se repete em >= MINIMO_BLOCOS blocos
    piso: float | None  # o piso detectado (None se não detectado)


def _iguais(a: float, b: float) -> bool:
    return abs(a - b) <= TOLERANCIA


def _blocos_por_valor(obs: Sequence[tuple[object, float]]) -> dict[float, set]:
    """Agrupa os valores (arredondados a 2 casas) e junta o conjunto de blocos de cada um."""
    por_valor: dict[float, set] = defaultdict(set)
    for bloco, valor in obs:
        por_valor[round(valor, 2)].add(bloco)
    return por_valor


def detectar_piso(
    ano: int, observacoes: Iterable[tuple[object, float]], minimo_blocos: int = MINIMO_BLOCOS
) -> PisoDetectado:
    obs = list(observacoes)
    if not obs:
        raise ValueError(f"nenhuma observação em {ano}")
    minimo = min(v for _, v in obs)
    repeticoes = sum(1 for _, v in obs if _iguais(v, minimo))
    por_valor = _blocos_por_valor(obs)
    blocos = len(por_valor[round(minimo, 2)])
    repetidos = sorted(v for v, bl in por_valor.items() if len(bl) >= minimo_blocos)
    menor_repetido = repetidos[0] if repetidos else None
    if blocos >= minimo_blocos:
        status, piso = "detectado", round(minimo, 2)
    elif menor_repetido is not None:
        status, piso = "repetido_acima", None
    else:
        status, piso = "minimo_unico", None
    return PisoDetectado(
        ano, round(minimo, 2), repeticoes, blocos, len(obs), status, menor_repetido, piso
    )


def detectar_por_ano(
    observacoes_por_ano: dict[int, list[tuple[object, float]]], minimo_blocos: int = MINIMO_BLOCOS
) -> list[PisoDetectado]:
    return [detectar_piso(a, o, minimo_blocos) for a, o in sorted(observacoes_por_ano.items())]


# ---------------------------------------------------------------- pisos de todos os anos (5.7)

VARIANTES_DE_LACUNA = ("interpolado", "vizinho_baixo", "vizinho_alto")


def completar_pisos(
    detectados: dict[int, float],
    excecoes: dict[int, float],
    anos: Sequence[int],
    variante: str = "interpolado",
) -> dict[int, tuple[float, str]]:
    """Piso de cada ano de `anos` e de onde vem: (valor, origem).

    - `excecao`: ano da seed `pld_piso_excecoes` (vale mesmo se o detector achou outro valor);
    - `detectado`: piso detectado (mínimo de 3 blocos);
    - `interpolado`: ano sem piso, interpolação LINEAR entre os anos mais próximos com piso
      (detectado ou exceção) antes e depois;
    - `vizinho_baixo` / `vizinho_alto`: a mesma lacuna preenchida com o menor / o maior dos dois
      vizinhos (sensibilidade da interpolação).
    Um ano sem vizinho de um dos lados é erro: não se extrapola."""
    if variante not in VARIANTES_DE_LACUNA:
        raise ValueError(f"variante desconhecida: {variante!r}")
    conhecidos = {**detectados, **excecoes}
    saida: dict[int, tuple[float, str]] = {}
    for ano in anos:
        if ano in excecoes:
            saida[ano] = (excecoes[ano], "excecao")
        elif ano in detectados:
            saida[ano] = (detectados[ano], "detectado")
        else:
            antes = [a for a in conhecidos if a < ano]
            depois = [a for a in conhecidos if a > ano]
            if not antes or not depois:
                raise ValueError(f"piso de {ano}: sem ano com piso de um dos lados")
            a, b = max(antes), min(depois)
            pa, pb = conhecidos[a], conhecidos[b]
            if variante == "interpolado":
                valor = pa + (pb - pa) * (ano - a) / (b - a)
            else:
                valor = min(pa, pb) if variante == "vizinho_baixo" else max(pa, pb)
            saida[ano] = (round(valor, 4), variante)
    return saida
