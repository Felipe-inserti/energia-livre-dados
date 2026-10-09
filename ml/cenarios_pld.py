"""Cenários de PLD (5.7): bootstrap simples e em blocos de 12 meses do PLD mensal do SE.

HISTÓRICO. PLD mensal do SE em R$/MWh: de 2002-01 a 2020-12, a média dos 3 patamares do PLD semanal
ponderada pelas horas de cada mês local; de 2021 em diante, o PLD ponderado pelo consumo do
supermercado (`fct_pld_ponderado_mensal`). 2001 fica de fora (racionamento, ano incompleto). Na
origem `t` só entram meses `<= t` (a mesma convenção do consumo: mês conhecido se `<= t`).

TRANSFORMAÇÃO (decisão do usuário, docs/decisoes.md): cada mês histórico do ano `a` vira um valor na
faixa do ano-alvo `y`:

    PLD_alvo = PLD_orig − piso(a) + piso(y),  limitado a [piso(y), teto_estrutural(y)]

Mantém a massa no piso (mês no piso vira mês no piso) e leva o prêmio acima do piso, em R$ nominais,
para o ano-alvo. Usa só o teto ESTRUTURAL (a média mensal é limitada por ele; o horário não entra).

MÉTODOS. `simples`: 12 meses sorteados com reposição de todo o histórico (o "antes"; perde
sazonalidade e persistência). `blocos`: um bloco de 12 meses consecutivos do histórico, começando no
mesmo mês do calendário que o primeiro mês-alvo (com origem em dezembro, são os anos-calendário
completos), o que preserva sazonalidade e persistência de regime. O sorteio é por bloco inteiro.

SEMENTE: derivada de (semente-base + deslocamento do método, origem); os sorteios saem em sequência,
então N menor é prefixo de N maior. Funções puras; a nuvem fica em `ml/cenarios.py`.
"""

import random
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from ml.intervalos import semente_da_origem
from ml.validacao import HORIZONTES, somar_meses

INICIO_HISTORICO = date(2002, 1, 1)
DESLOCAMENTO_DA_SEMENTE = {"simples": 0, "blocos": 1}
METODOS = tuple(DESLOCAMENTO_DA_SEMENTE)
FUSO = ZoneInfo("America/Sao_Paulo")


# ---------------------------------------------------------------- histórico mensal


def mensal_do_semanal(
    semanas: Sequence[tuple[datetime, datetime, float]],
) -> dict[date, float]:
    """PLD mensal (R$/MWh) das semanas: (início UTC, fim UTC, preço médio dos 3 patamares).

    Cada hora da semana vai para o mês LOCAL (America/Sao_Paulo) em que cai; o mês é a média
    ponderada pelas horas. Meses só parcialmente cobertos (pontas do arquivo) saem com o que há."""
    soma: dict[date, float] = {}
    horas: dict[date, int] = {}
    for inicio, fim, preco in semanas:
        t = inicio if inicio.tzinfo else inicio.replace(tzinfo=UTC)
        limite = fim if fim.tzinfo else fim.replace(tzinfo=UTC)
        while t < limite:
            local = t.astimezone(FUSO)
            mes = date(local.year, local.month, 1)
            soma[mes] = soma.get(mes, 0.0) + preco
            horas[mes] = horas.get(mes, 0) + 1
            t += timedelta(hours=1)
    return {m: soma[m] / horas[m] for m in sorted(soma)}


def historico_ate(
    serie: Mapping[date, float], t: date, inicio: date = INICIO_HISTORICO
) -> dict[date, float]:
    """Os meses `inicio <= mes <= t`: a informação disponível na origem `t`."""
    return {m: v for m, v in sorted(serie.items()) if inicio <= m <= t}


# ---------------------------------------------------------------- limites e transformação


def limites_do_ano(
    tabela: Mapping[int, tuple[float, float]], ano: int
) -> tuple[float, float, bool]:
    """(piso, teto estrutural, assumido) do ano-alvo. Ano além da tabela repete o último ano
    (`assumido=True`): o ANEEL só publica os limites de `y` em dezembro de `y − 1`."""
    if ano in tabela:
        return (*tabela[ano], False)
    ultimo = max(tabela)
    if ano < min(tabela) or ano < ultimo:
        raise ValueError(f"limites do ano {ano} indisponíveis")
    return (*tabela[ultimo], True)


def transformar(
    valor: float,
    mes_origem: date,
    mes_alvo: date,
    pisos: Mapping[int, float],
    limites: Mapping[int, tuple[float, float]],
) -> float:
    """PLD_orig − piso(ano orig) + piso(ano alvo), em [piso(alvo), teto estrutural(alvo)]."""
    piso_alvo, teto_alvo, _ = limites_do_ano(limites, mes_alvo.year)
    novo = valor - pisos[mes_origem.year] + piso_alvo
    return min(max(novo, piso_alvo), teto_alvo)


# ---------------------------------------------------------------- bootstrap


def meses_alvo(origem: date) -> list[date]:
    return [somar_meses(origem, h) for h in HORIZONTES]


def blocos_de_12(historico: Mapping[date, float], primeiro_mes_alvo: date) -> list[list[date]]:
    """Janelas de 12 meses consecutivos, completas, que começam no mesmo mês do calendário."""
    janelas = []
    for mes in sorted(historico):
        if mes.month != primeiro_mes_alvo.month:
            continue
        janela = [somar_meses(mes, k) for k in range(12)]
        if all(m in historico for m in janela):
            janelas.append(janela)
    return janelas


def _rng(semente: int, origem: date, metodo: str) -> random.Random:
    return random.Random(semente_da_origem(semente + DESLOCAMENTO_DA_SEMENTE[metodo], origem))


def bootstrap(
    metodo: str,
    historico: Mapping[date, float],
    origem: date,
    n: int,
    semente: int,
    pisos: Mapping[int, float],
    limites: Mapping[int, tuple[float, float]],
) -> list[list[tuple[date, float]]]:
    """`n` cenários; cada um é uma lista de 12 pares (mês histórico sorteado, PLD no ano-alvo).

    `historico` deve ser o de `historico_ate(serie, origem)`. Os meses-alvo são os 12 seguintes à
    origem; o mês histórico j-ésimo vai para o j-ésimo mês-alvo."""
    if metodo not in METODOS:
        raise ValueError(f"método desconhecido: {metodo!r}")
    if any(m > origem for m in historico):
        raise ValueError("o histórico tem meses depois da origem (vazamento)")
    alvos = meses_alvo(origem)
    rng = _rng(semente, origem, metodo)
    meses = sorted(historico)
    if metodo == "simples":
        if not meses:
            raise ValueError("histórico vazio")
        sorteios = [[rng.choice(meses) for _ in alvos] for _ in range(n)]
    else:
        janelas = blocos_de_12(historico, alvos[0])
        if not janelas:
            raise ValueError(f"nenhum bloco de 12 meses completo até {origem}")
        sorteios = [list(rng.choice(janelas)) for _ in range(n)]
    return [
        [
            (m, transformar(historico[m], m, alvo, pisos, limites))
            for m, alvo in zip(sorteio, alvos, strict=True)
        ]
        for sorteio in sorteios
    ]


def pld_anual(valores: Sequence[float], meses: Sequence[date]) -> float:
    """Média do PLD dos 12 meses ponderada pelas horas de cada mês (calendário local, sem horário
    de verão desde 2019)."""
    pesos = [_horas_do_mes(m) for m in meses]
    return sum(v * p for v, p in zip(valores, pesos, strict=True)) / sum(pesos)


def _horas_do_mes(mes: date) -> int:
    return (somar_meses(mes, 1) - mes).days * 24
