"""Avalia os cenários de PLD da 5.7 (só leitura): histórico transformado, bootstrap e pisos.

    uv run --env-file .env python -m scripts.avaliar_cenarios_pld [--n 2000] [--secao A B C]

A. HISTÓRICO TRANSFORMADO (antes do bootstrap). Para cada ano-alvo 2021-2025, o PLD mensal de 2002
   até dezembro do ano anterior, transformado na faixa do ano-alvo: fração de meses no piso e no
   teto, média, desvio-padrão e quantis, ao lado do PLD realizado (ponderado pelo consumo).
B. BOOTSTRAP. Para as 5 origens de dezembro e os dois métodos: posição (PIT) do PLD médio anual
   realizado, variância do PLD anual nos cenários contra a do histórico transformado, fração de
   meses no piso.
C. SENSIBILIDADE DA LACUNA. Refaz os cenários com o piso das lacunas (2008, 2013-2015, 2018) igual
   ao do vizinho mais baixo e ao do mais alto, e mostra a variação da média e do p95 do PLD anual.
"""

import argparse
import sys
from datetime import date

import numpy as np

from ingestion.common import gcp
from ingestion.common.config import carregar_config
from ml.cenarios import DadosPld, carregar_dados_pld
from ml.cenarios_pld import (
    METODOS,
    bootstrap,
    historico_ate,
    meses_alvo,
    pld_anual,
    transformar,
)

TOL = 0.005
PROXIMO_DO_PISO = 1.05
ORIGENS = [date(a, 12, 1) for a in range(2020, 2025)]


def estatisticas(valores, piso_de, teto_de) -> dict:
    """`valores`: lista de (mês-alvo, valor). Frações no piso/teto e momentos."""
    v = np.array([x for _, x in valores])
    no_piso = np.mean([x <= piso_de(m) + TOL for m, x in valores])
    perto = np.mean([x <= PROXIMO_DO_PISO * piso_de(m) for m, x in valores])
    no_teto = np.mean([x >= teto_de(m) - TOL for m, x in valores])
    p10, p50, p90 = np.percentile(v, [10, 50, 90])
    return {
        "n": len(v),
        "piso": no_piso,
        "perto": perto,
        "teto": no_teto,
        "media": v.mean(),
        "dp": v.std(ddof=1) if len(v) > 1 else float("nan"),
        "p10": p10,
        "p50": p50,
        "p90": p90,
    }


def linha(nome: str, e: dict) -> str:
    return (
        f"| {nome} | {e['n']} | {100 * e['piso']:.1f}% | {100 * e['perto']:.1f}% | "
        f"{100 * e['teto']:.1f}% | {e['media']:.1f} | {e['dp']:.1f} | "
        f"{e['p10']:.1f} | {e['p50']:.1f} | {e['p90']:.1f} |"
    )


CABECALHO = (
    "| Conjunto | Meses | No piso | ≤ 1,05×piso | No teto | Média | Desvio | p10 | p50 | p90 |\n"
    "|---|---|---|---|---|---|---|---|---|---|"
)


def secao_a(d: DadosPld) -> None:
    pisos = d.pisos()
    piso_de = lambda m: d.limites[m.year][0]  # noqa: E731
    teto_de = lambda m: d.limites[m.year][1]  # noqa: E731
    print("\n## A. Histórico transformado contra o realizado (R$/MWh)\n")
    print("Piso por ano usado na transformação (2002-2020):")
    print(
        ", ".join(
            f"{a}: {v:.2f} ({o})"
            for (a, v), o in zip(
                ((a, pisos[a]) for a in range(2002, 2021)),
                d.origem_dos_pisos().values(),
                strict=True,
            )
        )
    )
    print("\n" + CABECALHO)
    realizados_todos = []
    for ano in range(2021, 2026):
        origem = date(ano - 1, 12, 1)
        hist = historico_ate(d.serie, origem)
        alvo = lambda m, ano=ano: date(ano, m.month, 1)  # noqa: E731
        trans = [(alvo(m), transformar(v, m, alvo(m), pisos, d.limites)) for m, v in hist.items()]
        real = [(m, v) for m, v in d.serie.items() if m.year == ano]
        realizados_todos += real
        print(
            linha(f"histórico 2002-{ano - 1} → faixa {ano}", estatisticas(trans, piso_de, teto_de))
        )
        print(linha(f"realizado {ano}", estatisticas(real, piso_de, teto_de)))
    print(linha("**realizado 2021-2025**", estatisticas(realizados_todos, piso_de, teto_de)))
    bruto = [(m, v) for m, v in d.serie.items() if m < date(2021, 1, 1)]
    e = estatisticas(bruto, lambda m: pisos[m.year], lambda m: 1e9)
    print(
        f"\nContraste, histórico 2002-2020 SEM transformar (nominal): média {e['media']:.1f}, "
        f"desvio {e['dp']:.1f}, p10/p50/p90 {e['p10']:.1f}/{e['p50']:.1f}/{e['p90']:.1f}; "
        f"no piso do seu próprio ano: {100 * e['piso']:.1f}%."
    )


def anual_dos_cenarios(d, origem, metodo, n, pisos):
    alvos = meses_alvo(origem)
    hist = historico_ate(d.serie, origem)
    cen = bootstrap(metodo, hist, origem, n, 0, pisos, d.limites)
    return cen, np.array([pld_anual([v for _, v in c], alvos) for c in cen])


def anual_do_historico(d, origem, pisos):
    """PLD anual de cada ano-calendário completo do histórico, transformado na faixa do ano-alvo."""
    alvos = meses_alvo(origem)
    hist = historico_ate(d.serie, origem)
    anos = sorted({m.year for m in hist if all(date(m.year, k, 1) in hist for k in range(1, 13))})
    return np.array(
        [
            pld_anual(
                [
                    transformar(hist[date(a, k, 1)], date(a, k, 1), alvo, pisos, d.limites)
                    for k, alvo in zip(range(1, 13), alvos, strict=True)
                ],
                alvos,
            )
            for a in anos
        ]
    )


def realizado_anual(d, ano):
    meses = [date(ano, k, 1) for k in range(1, 13)]
    return pld_anual([d.serie[m] for m in meses], meses)


def secao_b(d: DadosPld, n: int) -> None:
    pisos = d.pisos()
    print(f"\n## B. Bootstrap (N = {n}): posição do PLD médio anual realizado, variância, piso\n")
    print(
        "| Origem (ano) | Método | Realizado | p10 | p50 | p90 | PIT | Var. cenários | "
        "Var. histórica | Razão | Meses no piso (cenários) | no piso (hist. transf.) | "
        "no piso (realizado) |"
    )
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for origem in ORIGENS:
        ano = origem.year + 1
        real = realizado_anual(d, ano)
        hist_anual = anual_do_historico(d, origem, pisos)
        var_hist = float(np.var(hist_anual, ddof=1))
        alvos = meses_alvo(origem)
        hist = historico_ate(d.serie, origem)
        trans = [transformar(v, m, alvos[0], pisos, d.limites) for m, v in hist.items()]
        f_hist = np.mean([x <= d.limites[ano][0] + TOL for x in trans])
        real_meses = [d.serie[date(ano, k, 1)] for k in range(1, 13)]
        f_real = np.mean([x <= d.limites[ano][0] + TOL for x in real_meses])
        for metodo in METODOS:
            cen, anual = anual_dos_cenarios(d, origem, metodo, n, pisos)
            todos = [v for c in cen for _, v in c]
            f_cen = np.mean([x <= d.limites[ano][0] + TOL for x in todos])
            p10, p50, p90 = np.percentile(anual, [10, 50, 90])
            pit = float((anual <= real).mean())
            var_cen = float(np.var(anual, ddof=1))
            print(
                f"| {origem:%Y-%m} ({ano}) | {metodo} | {real:.1f} | {p10:.1f} | {p50:.1f} | "
                f"{p90:.1f} | {pit:.3f} | {var_cen:.0f} | {var_hist:.0f} | "
                f"{var_cen / var_hist:.2f} | "
                f"{100 * f_cen:.1f}% | {100 * f_hist:.1f}% | {100 * f_real:.1f}% |"
            )


def secao_c(d: DadosPld, n: int) -> None:
    base = d.pisos()
    baixo, alto = d.pisos("vizinho_baixo"), d.pisos("vizinho_alto")
    lacunas = [a for a, o in d.origem_dos_pisos().items() if o == "interpolado"]
    print(f"\n## C. Sensibilidade do piso das lacunas {lacunas} (N = {n})\n")
    print("| Ano | Interpolado | Vizinho baixo | Vizinho alto |\n|---|---|---|---|")
    for a in lacunas:
        print(f"| {a} | {base[a]:.2f} | {baixo[a]:.2f} | {alto[a]:.2f} |")
    print(
        "\n| Origem (ano) | Método | Média base | Média baixo (Δ%) | Média alto (Δ%) | "
        "p95 base | p95 baixo (Δ%) | p95 alto (Δ%) |\n|---|---|---|---|---|---|---|---|"
    )
    for origem in ORIGENS:
        for metodo in METODOS:
            stats = {}
            for nome, pisos in (("base", base), ("baixo", baixo), ("alto", alto)):
                _, anual = anual_dos_cenarios(d, origem, metodo, n, pisos)
                stats[nome] = (float(anual.mean()), float(np.percentile(anual, 95)))
            celulas = [f"{stats['base'][0]:.2f}"]
            for i in (0, 1):
                if i == 1:
                    celulas.append(f"{stats['base'][1]:.2f}")
                for nome in ("baixo", "alto"):
                    delta = 100 * (stats[nome][i] / stats["base"][i] - 1)
                    celulas.append(f"{stats[nome][i]:.2f} ({delta:+.2f}%)")
            print(
                f"| {origem:%Y-%m} ({origem.year + 1}) | {metodo} | " + " | ".join(celulas) + " |"
            )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--n", type=int, default=2000)
    ap.add_argument("--secao", nargs="+", default=["A", "B", "C"], choices=["A", "B", "C"])
    args = ap.parse_args(argv)
    d = carregar_dados_pld(gcp, gcp.cliente_bigquery(carregar_config()))
    if "A" in args.secao:
        secao_a(d)
    if "B" in args.secao:
        secao_b(d, args.n)
    if "C" in args.secao:
        secao_c(d, args.n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
