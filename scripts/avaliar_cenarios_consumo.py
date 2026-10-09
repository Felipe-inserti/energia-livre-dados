"""Avalia os cenários de consumo da 5.6 (só leitura): cobertura por horizonte e CVaR95.

    uv run --env-file .env python -m scripts.avaliar_cenarios_consumo [--n 2000] [--sementes 30]

1. COBERTURA. Para cada uma das 60 origens do teste final (2020-12 a 2025-11), sorteia `n` cenários
   com os vetores conhecidos na origem (calibração CRESCENTE: mês-alvo <= origem) e vê quantas vezes
   o valor REALIZADO de cada horizonte cai no intervalo central de 80% (p10 a p90) e de 95% (p2,5 a
   p97,5) dos cenários. Compara com o método anterior: quantis fixos do desenvolvimento no
   teste final (70% e 88% no total; aqui, por horizonte).
2. ESTABILIDADE DO CVaR95. Proxy do risco da decisão: o CVaR95 do CONSUMO ANUAL (5% maiores
   consumos de 12 meses) das 5 origens de dezembro. O CVaR95 do CUSTO depende do modelo de custo
   (tarefa 6.1) e só sai na 6.2. O valor "exato" é o do conjunto discreto de vetores (o limite de
   N -> infinito da reamostragem). Para cada N, repete o sorteio com várias sementes e mostra o
   desvio-padrão e o viés relativos ao exato.
"""

import argparse
import statistics
import sys
from datetime import date

import numpy as np

from ingestion.common import gcp
from ingestion.common.config import carregar_config
from ml.cenarios_consumo import (
    consumo_anual_de_cada_vetor,
    consumo_mwh,
    cvar_superior,
    k_do_dbt,
    sortear,
)
from ml.intervalos import Erro, quantis_por_horizonte, vetores_completos_ate
from ml.registro import MODELO_VERSAO
from ml.validacao import HORIZONTES, somar_meses

TETO = 200 * 1024 * 1024
NIVEIS = {"80%": (10, 90), "95%": (2.5, 97.5)}


def ler(cliente):
    sql = f"""SELECT periodo, origem, horizonte, mes_alvo, previsto_mwmed, real_mwmed, log_razao
        FROM `marts.fct_erro_previsao_carga` WHERE modelo_versao = '{MODELO_VERSAO}'"""
    return gcp.executar_consulta(cliente, sql, max_bytes_faturados=TETO).linhas


def cobertura(linhas, n: int) -> dict:
    erros = [
        Erro(r["origem"], int(r["horizonte"]), r["mes_alvo"], float(r["log_razao"])) for r in linhas
    ]
    erros_dev = [e for e, r in zip(erros, linhas, strict=True) if r["periodo"] == "desenvolvimento"]
    teste = [r for r in linhas if r["periodo"] == "teste_final"]
    origens = sorted({r["origem"] for r in teste})
    por_origem = {o: {int(r["horizonte"]): r for r in teste if r["origem"] == o} for o in origens}
    q_dev = quantis_por_horizonte(erros_dev)  # método anterior: quantis fixos do desenvolvimento
    hits = {
        h: {"cenarios": {"80%": 0, "95%": 0}, "anterior": {"80%": 0, "95%": 0}, "n": 0}
        for h in HORIZONTES
    }
    for o in origens:
        sorteio = sortear(erros, o, n)
        mat = np.array([v for _, v in sorteio])  # n x 12
        for h, r in por_origem[o].items():
            prev, real = float(r["previsto_mwmed"]), float(r["real_mwmed"])
            col = prev * np.exp(mat[:, h - 1])
            hits[h]["n"] += 1
            for nome, (lo, hi) in NIVEIS.items():
                a, b = np.percentile(col, [lo, hi])
                hits[h]["cenarios"][nome] += int(a <= real <= b)
            ant = {"80%": ("p10", "p90"), "95%": ("p025", "p975")}
            for nome, (lo, hi) in ant.items():
                hits[h]["anterior"][nome] += int(
                    prev * np.exp(q_dev[h][lo]) <= real <= prev * np.exp(q_dev[h][hi])
                )
    return hits


def _pct(d):
    """Função (grupo, nível) -> percentual de acertos sobre d["n"]."""
    return lambda k, nm: 100 * d[k][nm] / d["n"]


def imprimir_cobertura(hits) -> None:
    print("\nCOBERTURA POR HORIZONTE (teste final, 60 origens, calibração crescente)")
    print("h   n  | cenários 80%  95% | anterior (dev fixo) 80%  95%")
    tot = {k: {"80%": 0, "95%": 0} for k in ("cenarios", "anterior")}
    ntot = 0
    for h in HORIZONTES:
        d = hits[h]
        ntot += d["n"]
        for k in tot:
            for nome in NIVEIS:
                tot[k][nome] += d[k][nome]
        f = _pct(d)
        print(
            f"{h:2d} {d['n']:3d}  |  {f('cenarios', '80%'):9.1f} {f('cenarios', '95%'):5.1f} |"
            f"  {f('anterior', '80%'):18.1f} {f('anterior', '95%'):5.1f}"
        )
    g = _pct({**tot, "n": ntot})
    print(
        f"todos {ntot:3d} |  {g('cenarios', '80%'):9.1f} {g('cenarios', '95%'):5.1f} |"
        f"  {g('anterior', '80%'):18.1f} {g('anterior', '95%'):5.1f}   (nominal 80 / 95)"
    )


def estabilidade(linhas, ns: list[int], n_sementes: int) -> None:
    k = k_do_dbt()
    erros = [
        Erro(r["origem"], int(r["horizonte"]), r["mes_alvo"], float(r["log_razao"])) for r in linhas
    ]
    prev = {}
    for r in linhas:
        if r["periodo"] == "teste_final":
            prev.setdefault(r["origem"], {})[int(r["horizonte"])] = float(r["previsto_mwmed"])
    decisao = [date(a, 12, 1) for a in range(2020, 2025)]
    print("\nESTABILIDADE DO CVaR95 DO CONSUMO ANUAL (cauda alta), por origem de decisão")
    print(f"{n_sementes} sementes por N; erro relativo ao CVaR95 exato do conjunto de vetores")
    cab = "origem  vetores  CVaR95 exato (MWh) | " + " | ".join(f"N={n:<5d} dp%  viés%" for n in ns)
    print(cab)
    medias = {n: [] for n in ns}
    for o in decisao:
        previstos = [prev[o][h] for h in HORIZONTES]
        vetores = vetores_completos_ate(erros, o)
        anual = consumo_anual_de_cada_vetor(previstos, vetores.values(), o, k)
        exato = cvar_superior(anual)
        por_idx = dict(zip(vetores.keys(), anual, strict=True))
        partes = []
        for n in ns:
            vals = []
            for s in range(n_sementes):
                sorteio = sortear(erros, o, n, semente=s)
                vals.append(cvar_superior([por_idx[origem_v] for origem_v, _ in sorteio]))
            dp = 100 * statistics.pstdev(vals) / exato
            vies = 100 * (statistics.mean(vals) / exato - 1)
            medias[n].append((dp, vies))
            partes.append(f"{dp:11.2f} {vies:+6.2f}")
        print(f"{o:%Y-%m}  {len(vetores):7d}  {exato:18.2f} | " + " | ".join(partes))
    resumo = []
    for n in ns:
        dp = statistics.mean(x[0] for x in medias[n])
        vies = statistics.mean(x[1] for x in medias[n])
        resumo.append(f"N={n}: dp {dp:.2f}%, viés {vies:+.2f}%")
    print("média das 5 origens: " + " | ".join(resumo))


def pit_anual(linhas, n: int) -> None:
    """Posição (PIT) do consumo anual REALIZADO nos cenários, nas 5 origens de dezembro.

    PIT = fração dos `n` cenários com consumo anual <= o realizado. Calibrado: perto de 0,5 em
    média e sem se agrupar nas pontas. Com 5 origens a leitura é só qualitativa."""
    k = k_do_dbt()
    erros = [
        Erro(r["origem"], int(r["horizonte"]), r["mes_alvo"], float(r["log_razao"])) for r in linhas
    ]
    teste = {}
    for r in linhas:
        if r["periodo"] == "teste_final":
            teste.setdefault(r["origem"], {})[int(r["horizonte"])] = r
    print("\nPIT DO CONSUMO ANUAL REALIZADO NOS CENÁRIOS (5 origens de decisão, N =", n, ")")
    print("origem   previsto  p10      p50      p90    realizado  real/p50-1   PIT")
    for a in range(2020, 2025):
        o = date(a, 12, 1)
        h2 = teste[o]
        previstos = [float(h2[h]["previsto_mwmed"]) for h in HORIZONTES]
        real = sum(
            consumo_mwh(float(h2[h]["real_mwmed"]), somar_meses(o, h), k) for h in HORIZONTES
        )
        vetores = vetores_completos_ate(erros, o)
        anual = dict(
            zip(
                vetores.keys(),
                consumo_anual_de_cada_vetor(previstos, vetores.values(), o, k),
                strict=True,
            )
        )
        tot = np.array([anual[origem_v] for origem_v, _ in sortear(erros, o, n)])
        ponto = consumo_anual_de_cada_vetor(previstos, [[0.0] * 12], o, k)[0]
        p10, p50, p90 = np.percentile(tot, [10, 50, 90])
        pit = float((tot <= real).mean())
        desvio = 100 * (real / p50 - 1)
        print(
            f"{o:%Y-%m}  {ponto:8.2f} {p10:8.2f} {p50:8.2f} {p90:8.2f} {real:10.2f}"
            f"  {desvio:+9.2f}%  {pit:5.3f}"
        )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--n", type=int, default=2000, help="cenários por origem na cobertura")
    ap.add_argument("--sementes", type=int, default=30)
    ap.add_argument("--ns", type=int, nargs="+", default=[1000, 2000, 5000])
    args = ap.parse_args(argv)
    linhas = ler(gcp.cliente_bigquery(carregar_config()))
    imprimir_cobertura(cobertura(linhas, args.n))
    estabilidade(linhas, args.ns, args.sementes)
    pit_anual(linhas, args.n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
