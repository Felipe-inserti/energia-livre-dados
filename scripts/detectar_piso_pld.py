"""Detecta o piso do PLD de cada ano pelo valor mínimo que se repete (só leitura).

    uv run --env-file .env python -m scripts.detectar_piso_pld [--conhecidos x.csv] [--saida x.md]

2002-2020: PLD semanal (SE), bloco = semana; 2021-2026: PLD horário (SE), bloco = dia local. O
critério e a justificativa estão em `ml/piso_pld.py`. Compara com os valores conhecidos: os da seed
`pld_limites` (2021-2026) e os de `--conhecidos` (CSV `ano,piso,fonte`). Imprime a tabela com a
sensibilidade ao número mínimo de blocos (2, 3 e 5).
"""

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

from ingestion.common import gcp
from ingestion.common.config import carregar_config
from ml.piso_pld import detectar_por_ano

RAIZ = Path(__file__).resolve().parents[1]
TETO_BYTES = 100 * 1024 * 1024
# Ano da semana = ano do seu DIA DO MEIO (início + 3 dias). A semana que começa em 2005-12-31 tem o
# piso de 2006 (16,92); atribuir pelo início a jogaria no ano errado.
SQL_SEMANAL = """SELECT data_inicio_semana AS bloco,
    EXTRACT(YEAR FROM DATE_ADD(data_inicio_semana, INTERVAL 3 DAY)) AS ano,
    CAST(pld_rs_mwh AS FLOAT64) AS valor
    FROM `marts.fct_pld_semanal` WHERE codigo_submercado = 'SE'"""
SQL_HORARIO = """SELECT DATE(instante_utc, 'America/Sao_Paulo') AS bloco,
    EXTRACT(YEAR FROM DATE(instante_utc, 'America/Sao_Paulo')) AS ano,
    CAST(pld_rs_mwh AS FLOAT64) AS valor
    FROM `marts.fct_pld_horario` WHERE codigo_submercado = 'SE'"""
# Valores achados em fontes secundárias (busca de 08/10/2026), nunca no texto oficial.
CONHECIDOS_DA_BUSCA = {
    2019: (42.35, "busca: CanalEnergia (PLD_min 2019)"),
    2020: (39.68, "busca: Abraceel/CanalEnergia (PLD mínimo 2020)"),
}


def observacoes(cliente, sql: str) -> dict[int, list]:
    por_ano = defaultdict(list)
    for r in gcp.executar_consulta(cliente, sql, max_bytes_faturados=TETO_BYTES).linhas:
        por_ano[int(r["ano"])].append((r["bloco"], float(r["valor"])))
    return por_ano


def conhecidos(arquivo: str | None) -> dict[int, tuple[float, str]]:
    saida = dict(CONHECIDOS_DA_BUSCA)
    with (RAIZ / "dbt" / "seeds" / "pld_limites.csv").open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            saida[int(r["ano"])] = (float(r["pld_min"]), "seed pld_limites (não confirmada)")
    if arquivo:
        with open(arquivo, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                saida[int(r["ano"])] = (float(r["piso"]), r.get("fonte", arquivo))
    return saida


def tabela(cliente, arquivo: str | None) -> list[str]:
    semanal, horario = observacoes(cliente, SQL_SEMANAL), observacoes(cliente, SQL_HORARIO)
    semanal = {a: o for a, o in semanal.items() if 2002 <= a <= 2020}
    conh = conhecidos(arquivo)
    linhas = [
        "| Ano | Fonte | Piso detectado | Repetições | Blocos | Observações | Status | "
        "Menor valor repetido | Conhecido | Fonte do conhecido | Diferença |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for fonte, dados in (("semanal", semanal), ("horário", horario)):
        for r in detectar_por_ano(dados):
            c = conh.get(r.ano)
            dif = ""
            if c and r.piso is not None:
                dif = f"{r.piso - c[0]:+.2f}"
            piso = f"{r.piso:.2f}" if r.piso is not None else f"({r.minimo:.2f})"
            rep = f"{r.menor_repetido:.2f}" if r.menor_repetido is not None else "-"
            linhas.append(
                f"| {r.ano} | {fonte} | {piso} | {r.repeticoes} | {r.blocos} | {r.observacoes} | "
                f"{r.status} | {rep} | {c[0] if c else '-'} | {c[1] if c else '-'} | {dif or '-'} |"
            )
    linhas += ["", "Sensibilidade ao número mínimo de blocos (anos com piso detectado):"]
    for m in (2, 3, 5):
        n = sum(r.status == "detectado" for d in (semanal, horario) for r in detectar_por_ano(d, m))
        linhas.append(f"- mínimo de {m} blocos: {n} de {len(semanal) + len(horario)} anos")
    return linhas


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--conhecidos")
    ap.add_argument("--saida", help="grava a tabela em Markdown")
    args = ap.parse_args(argv)
    texto = "\n".join(tabela(gcp.cliente_bigquery(carregar_config()), args.conhecidos))
    print(texto)
    if args.saida:
        Path(args.saida).write_text(texto + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
