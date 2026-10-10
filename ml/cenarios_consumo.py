"""Cenários de consumo (5.6): reamostragem de vetores completos de `log_razao` por origem.

Para a origem `t` (a decisão do contrato do ano seguinte), cada cenário `s` sorteia UM vetor de 12
erros entre os vetores completos CONHECIDOS em `t` (último mês-alvo `<= t`, regra crescente de
`ml/intervalos.py`) e aplica ao previsto da própria origem:

    carga_h(s)  = previsto_h × exp(e_h(s))                 (MWmed do SE/CO)
    consumo_h(s) = k × carga_h(s) × horas_do_mes_h          (MWh do supermercado)

A unidade do sorteio é a origem inteira, o que preserva a correlação entre os meses (um erro de
nível alto num mês vem com o erro dos vizinhos). A semente é derivada de (semente-base, origem):
cada origem tem a sua sequência, reprodutível, e os sorteios saem em sequência, então N=1.000 é
prefixo de N=2.000.

Em PRODUÇÃO a regra é a mesma, com `t` = a última origem: todos os erros com mês-alvo `<= t` já são
os erros disponíveis (desenvolvimento, teste final e produção juntos).

Premissa (docs/decisoes.md, decisão 9): consumo e PLD são sorteados de forma independente. Os
cenários só entram na DECISÃO do volume; o backtest avalia o custo com os valores realizados.

A geração e a gravação das três tabelas (consumo, PLD e execução) são de `ml/cenarios.py`
(`python -m ml.cenarios gerar`). Aqui ficam as funções puras e a leitura dos erros.
"""

import calendar
import hashlib
import json
import math
import random
from collections.abc import Iterable, Sequence
from datetime import date
from pathlib import Path

from ml.intervalos import Erro, semente_da_origem, vetores_completos_ate
from ml.registro import MODELO_VERSAO
from ml.validacao import HORIZONTES, somar_meses

RAIZ = Path(__file__).resolve().parents[1]
SEMENTE_BASE = 0
N_PADRAO = 2000
NIVEL_CVAR = 0.95
CENARIOS = "marts.fct_cenario_consumo"
TETO_BYTES = 200 * 1024 * 1024

ESQUEMA_CENARIOS = [
    ("execucao_id", "STRING"),
    ("origem", "DATE"),
    ("cenario", "INT64"),
    ("horizonte", "INT64"),
    ("mes_alvo", "DATE"),
    ("origem_amostrada", "DATE"),
    ("carga_mwmed", "FLOAT64"),
    ("consumo_mwh", "FLOAT64"),
]
CHAVE_CENARIOS = ("execucao_id", "origem", "cenario", "horizonte")


# ---------------------------------------------------------------- funções puras


def horas_do_mes(mes: date) -> int:
    """Horas do mês local. Sem horário de verão desde 2019 (a curva de consumo começa em 2020)."""
    return calendar.monthrange(mes.year, mes.month)[1] * 24


def esticar_erros(vetores: Sequence[Sequence[float]], dispersao: float) -> list[list[float]]:
    """`e' = m_h + k·(e − m_h)`, com `m_h` a média do horizonte `h` entre os vetores conhecidos.

    Estica só o desvio em torno da média de cada horizonte: o viés (`m_h`) não muda e o mesmo `k`
    vale para os 12 horizontes de um vetor (a correlação entre meses é preservada). Com `k = 1`
    devolve os vetores sem tocar nos valores (bit a bit)."""
    if dispersao <= 0:
        raise ValueError("a dispersão deve ser positiva")
    if dispersao == 1.0:
        return [list(v) for v in vetores]
    medias = [sum(v[h] for v in vetores) / len(vetores) for h in range(len(HORIZONTES))]
    return [[m + dispersao * (e - m) for m, e in zip(medias, v, strict=True)] for v in vetores]


def sortear(
    erros: Iterable[Erro],
    origem: date,
    n: int,
    semente: int = SEMENTE_BASE,
    dispersao: float = 1.0,
) -> list[tuple[date, list[float]]]:
    """`n` pares (origem do vetor sorteado, vetor de 12 erros) com vetores conhecidos em `origem`.

    Usa a mesma sequência de `reamostrar_origens(..., semente_por_origem=True)` (teste confere), mas
    devolve também de qual origem veio cada vetor, para a auditoria. `dispersao` (sensibilidade da
    6.4) estica os erros em torno da média de cada horizonte (`esticar_erros`); os índices sorteados
    são os mesmos para qualquer `dispersao`."""
    conhecidos = vetores_completos_ate(erros, origem)
    vetores = list(conhecidos.items())
    if not vetores:
        raise ValueError(f"nenhum vetor completo conhecido em {origem}")
    esticados = dict(
        zip(
            conhecidos,
            esticar_erros([conhecidos[o] for o in conhecidos], dispersao),
            strict=True,
        )
    )
    rng = random.Random(semente_da_origem(semente, origem))
    return [(o, list(esticados[o])) for o, _ in (rng.choice(vetores) for _ in range(n))]


def carga_do_cenario(previstos: Sequence[float], vetor: Sequence[float]) -> list[float]:
    """previsto_h × exp(e_h), h = 1..12 (MWmed)."""
    if len(previstos) != len(HORIZONTES) or len(vetor) != len(HORIZONTES):
        raise ValueError("são necessários 12 previstos e 12 erros")
    return [p * math.exp(e) for p, e in zip(previstos, vetor, strict=True)]


def consumo_mwh(carga_mwmed: float, mes: date, k: float) -> float:
    """Consumo do mês do supermercado: k × carga do SE/CO × horas (a curva tem média 1 por dia)."""
    return k * carga_mwmed * horas_do_mes(mes)


def consumo_anual_de_cada_vetor(
    previstos: Sequence[float], vetores: Iterable[Sequence[float]], origem: date, k: float
) -> list[float]:
    """Consumo dos 12 meses somado, um valor por vetor (insumo do CVaR exato)."""
    meses = [somar_meses(origem, h) for h in HORIZONTES]
    return [
        sum(
            consumo_mwh(c, m, k) for c, m in zip(carga_do_cenario(previstos, v), meses, strict=True)
        )
        for v in vetores
    ]


def cvar_superior(valores: Sequence[float], nivel: float = NIVEL_CVAR) -> float:
    """Média dos `1 − nivel` maiores valores (a cauda alta), com a fração do último valor tratada de
    forma exata: com M valores equiprováveis, é o CVaR do distribuição discreta."""
    if not 0 < nivel < 1:
        raise ValueError("nivel em (0, 1)")
    v = sorted(valores, reverse=True)
    massa = (1 - nivel) * len(v)
    inteiros = int(math.floor(massa + 1e-12))
    soma = sum(v[:inteiros])
    resto = massa - inteiros
    if resto > 1e-12 and inteiros < len(v):
        soma += resto * v[inteiros]
    return soma / massa


def hash_curto(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:12]


def hash_dos_erros(erros: Iterable[Erro], origem: date) -> str:
    """Impressão digital dos erros que a origem pode usar (alvo <= origem), a 1e-12."""
    usados = sorted(
        (e.origem.isoformat(), e.horizonte, round(e.log_razao, 12))
        for e in erros
        if e.alvo <= origem
    )
    return hash_curto(usados)


def execucao_id(
    n: int,
    semente: int,
    k: float,
    erros_por_origem: dict[date, str],
    extras: dict | None = None,
) -> str:
    """Identifica a execução: mesmo N, semente, k, erros (e `extras`, como a impressão do PLD e dos
    pisos) dão o mesmo id, e a gravação por MERGE é idempotente."""
    base = {
        "modelo": MODELO_VERSAO,
        "n": n,
        "semente": semente,
        "k": k,
        "erros": {o.isoformat(): h for o, h in erros_por_origem.items()},
    }
    if extras:
        base["extras"] = extras
    return hash_curto(base)


def linhas_de_cenarios(
    id_: str,
    origem: date,
    previstos: Sequence[float],
    sorteio: Sequence[tuple[date, Sequence[float]]],
    k: float,
) -> list[dict]:
    meses = [somar_meses(origem, h) for h in HORIZONTES]
    linhas = []
    for s, (amostrada, vetor) in enumerate(sorteio):
        for h, mes, carga in zip(
            HORIZONTES, meses, carga_do_cenario(previstos, vetor), strict=True
        ):
            linhas.append(
                {
                    "execucao_id": id_,
                    "origem": origem.isoformat(),
                    "cenario": s,
                    "horizonte": h,
                    "mes_alvo": mes.isoformat(),
                    "origem_amostrada": amostrada.isoformat(),
                    "carga_mwmed": carga,
                    "consumo_mwh": consumo_mwh(carga, mes, k),
                }
            )
    return linhas


# ---------------------------------------------------------------- nuvem


def k_do_dbt() -> float:
    import yaml

    cfg = yaml.safe_load((RAIZ / "dbt" / "dbt_project.yml").read_text())
    return float(cfg["vars"]["k_consumo"])


def ler_erros_e_previstos(gcp, cliente):
    """(erros, previstos): erros de todos os períodos; previstos[origem][h] dos que têm real."""
    from ml.previsao import _consulta

    sql = f"""SELECT origem, horizonte, mes_alvo, log_razao, previsto_mwmed
        FROM `marts.fct_erro_previsao_carga` WHERE modelo_versao = '{MODELO_VERSAO}'"""
    erros, previstos = [], {}
    for r in _consulta(gcp, cliente, sql).linhas:
        erros.append(Erro(r["origem"], int(r["horizonte"]), r["mes_alvo"], float(r["log_razao"])))
        previstos.setdefault(r["origem"], {})[int(r["horizonte"])] = float(r["previsto_mwmed"])
    return erros, previstos


def previstos_de_producao(gcp, cliente) -> tuple[date, list[float]]:
    from ml.previsao import _consulta

    sql = f"""SELECT origem, horizonte, previsao_mwmed FROM `marts.fct_previsao_carga`
        WHERE modelo_versao = '{MODELO_VERSAO}' AND tipo = 'producao'
          AND origem = (SELECT MAX(origem) FROM `marts.fct_previsao_carga`
                        WHERE modelo_versao = '{MODELO_VERSAO}' AND tipo = 'producao')"""
    linhas = _consulta(gcp, cliente, sql).linhas
    return linhas[0]["origem"], [
        float(r["previsao_mwmed"]) for r in sorted(linhas, key=lambda r: r["horizonte"])
    ]


def origens_de_decisao(previstos: dict[date, dict[int, float]]) -> list[date]:
    """Origens de dezembro com os 12 horizontes: 2020-12 a 2024-12 (backtest 2021-2025)."""
    return sorted(
        o
        for o, h in previstos.items()
        if o.month == 12 and set(h) == set(HORIZONTES) and o.year >= 2020
    )
