"""Gera o seed `dbt/seeds/carga_mensal_ons.csv` a partir da Carga Mensal do ONS (2015 a 2018).

    uv run python -m scripts.baixar_carga_mensal_ons [--desde 2015-01] [--ate 2018-12]

POR QUE EXISTE. A curva horária do ONS não traz as usinas não despachadas (tipo III) até fev/2021
e a API de Carga Verificada só as mede a partir de 2018 (docs/decisoes.md). A Carga Mensal do ONS
inclui o tipo III desde jan/2015, então `Carga Mensal - curva` mede o tipo III em 2015-2017 (antes
de 2015 a diferença é ~0, e o ajuste NÃO é inventado). Os meses de 2018 entram só para conferir:
é a sobreposição com a API, onde o tipo III é medido pelas duas fontes.

CUIDADOS (por isso a janela é fechada em 2018-12):
- os meses de 2026-08 a 2026-10 vêm com valor 0 (provisório, sem marca no dataset): nunca ler além
  da janela pedida, e recusar zero dentro dela;
- o ID do subsistema vem com espaço ("N "), e o separador é ponto e vírgula.

Não escreve na nuvem: só lê a URL pública (sem credenciais) e grava um CSV local.
"""

import argparse
import csv
import io
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import requests

URL = "https://ons-aws-prod-opendata.s3.amazonaws.com/dataset/carga_energia_me/CARGA_MENSAL.csv"
SEED = Path(__file__).resolve().parents[1] / "dbt" / "seeds" / "carga_mensal_ons.csv"
COLUNAS = ("mes", "codigo_submercado", "carga_mensal_ons_mwmed", "consultado_em")
SUBMERCADOS = {"SE", "S", "NE", "N"}


def montar_linhas(texto: str, desde: str, ate: str, consultado_em: str) -> list[dict]:
    """Linhas (mês, submercado) com `desde <= mês <= ate` (AAAA-MM); zero dentro da janela é
    erro."""
    leitor = csv.DictReader(io.StringIO(texto), delimiter=";")
    linhas = []
    for r in leitor:
        mes = r["din_instante"][:7]
        if not desde <= mes <= ate:
            continue
        sm = r["id_subsistema"].strip()
        if sm not in SUBMERCADOS:
            raise ValueError(f"subsistema desconhecido: {r['id_subsistema']!r}")
        valor = float(r["val_cargaenergiamwmed"])
        if valor <= 0:
            raise ValueError(f"carga mensal não positiva em {mes} {sm}: {valor}")
        linhas.append(
            {
                "mes": f"{mes}-01",
                "codigo_submercado": sm,
                "carga_mensal_ons_mwmed": f"{valor:.4f}",
                "consultado_em": consultado_em,
            }
        )
    return sorted(linhas, key=lambda x: (x["mes"], x["codigo_submercado"]))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--desde", default="2015-01")
    ap.add_argument("--ate", default="2018-12")
    ap.add_argument("--saida", type=Path, default=SEED)
    args = ap.parse_args(argv)
    resposta = requests.get(URL, timeout=60)
    resposta.raise_for_status()
    hoje = datetime.now(UTC).date().isoformat()
    linhas = montar_linhas(resposta.text, args.desde, args.ate, hoje)
    esperadas = 4 * (
        (int(args.ate[:4]) - int(args.desde[:4])) * 12 + int(args.ate[5:]) - int(args.desde[5:]) + 1
    )
    if len(linhas) != esperadas:
        print(f"ERRO: {len(linhas)} linhas, esperadas {esperadas}", file=sys.stderr)
        return 1
    args.saida.parent.mkdir(parents=True, exist_ok=True)
    with args.saida.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUNAS, lineterminator="\n")
        w.writeheader()
        w.writerows(linhas)
    print(f"{len(linhas)} linhas em {args.saida} (consulta de {date.fromisoformat(hoje)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
