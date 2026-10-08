"""Prova que a série do `fct_carga_mensal` é idêntica BIT A BIT entre execuções (só leitura).

    uv run --env-file .env python -m scripts.provar_estabilidade_carga_mensal foto SAIDA.json
    uv run --env-file .env python -m scripts.provar_estabilidade_carga_mensal comparar A.json B.json
    uv run --env-file .env python -m scripts.provar_estabilidade_carga_mensal avg [N]

`foto` grava todas as colunas de carga (cada float como `float.hex`, sem perda). `comparar` confere
duas ou mais fotos bit a bit e sai com 1 se alguma diferir. `avg` repete N vezes (padrão 6, sem
cache) o `ROUND(AVG(carga), 3)` sobre a carga horária, a origem do ruído, e conta as séries mensais
que diferem entre as rodadas (sem arredondar eram 3 a 5 de 322 por rodada).
"""

import json
import sys

from ingestion.common import gcp
from ingestion.common.config import carregar_config

COLUNAS = (
    "carga_original_mwmed",
    "ajuste_tipo3_mwmed",
    "ajuste_mmgd_mwmed",
    "carga_ajustada_mwmed",
    "carga_ajustada_r1_mwmed",
    "ajuste_tipo3_reconstruido_mwmed",
    "carga_ajustada_reconstruida_mwmed",
)
TETO = 100 * 1024 * 1024


def foto() -> dict:
    cliente = gcp.cliente_bigquery(carregar_config())
    sql = f"""SELECT codigo_submercado, mes, {", ".join(COLUNAS)}
        FROM `marts.fct_carga_mensal` ORDER BY codigo_submercado, mes"""
    linhas = gcp.executar_consulta(cliente, sql, max_bytes_faturados=TETO, usar_cache=False).linhas
    return {
        f"{r['codigo_submercado']}|{r['mes']}": {
            c: (None if r[c] is None else float(r[c]).hex()) for c in COLUNAS
        }
        for r in linhas
    }


def diferencas(a: dict, b: dict) -> list[tuple[str, str, str, str]]:
    if set(a) != set(b):
        raise ValueError("as fotos não têm as mesmas linhas")
    return [(k, c, a[k][c], b[k][c]) for k in sorted(a) for c in COLUNAS if a[k][c] != b[k][c]]


def avg_arredondado(rodadas: int) -> int:
    cliente = gcp.cliente_bigquery(carregar_config())
    sql = """SELECT codigo_submercado,
        DATE_TRUNC(DATE(instante_utc, 'America/Sao_Paulo'), MONTH) mes,
        ROUND(AVG(carga_mwmed), 3) m FROM `marts.fct_carga_horaria` GROUP BY 1, 2"""
    todas = []
    for _ in range(rodadas):
        r = gcp.executar_consulta(cliente, sql, max_bytes_faturados=TETO, usar_cache=False)
        todas.append({(x["codigo_submercado"], x["mes"]): x["m"] for x in r.linhas})
    base = todas[0]
    total = 0
    for i, o in enumerate(todas[1:], 2):
        n = sum(1 for k in base if base[k] != o[k])
        total += n
        print(f"rodada {i} contra a 1: {n} de {len(base)} (submercado, mês) diferem bit a bit")
    print(
        f"{'PASS' if total == 0 else 'FAIL'}  {rodadas} rodadas, {len(base)} séries mensais, "
        f"{total} diferenças"
    )
    return 0 if total == 0 else 1


def main(argv: list[str]) -> int:
    comando, *args = argv or ["ajuda"]
    if comando == "foto" and len(args) == 1:
        dados = foto()
        with open(args[0], "w", encoding="utf-8") as f:
            json.dump(dados, f)
        print(f"foto de {len(dados)} linhas em {args[0]}")
        return 0
    if comando == "comparar" and len(args) >= 2:
        fotos = [json.load(open(a, encoding="utf-8")) for a in args]
        total = 0
        for i, f in enumerate(fotos[1:], 2):
            d = diferencas(fotos[0], f)
            total += len(d)
            print(
                f"foto {i} contra a 1: {len(d)} de {len(fotos[0]) * len(COLUNAS)} valores "
                "diferem bit a bit"
            )
            for k, c, x, y in d[:5]:
                print(f"   {k} {c}: {float.fromhex(x)!r} contra {float.fromhex(y)!r}")
        print(
            f"{'PASS' if total == 0 else 'FAIL'}  série idêntica bit a bit "
            f"entre {len(fotos)} execuções"
        )
        return 0 if total == 0 else 1
    if comando == "avg":
        return avg_arredondado(int(args[0]) if args else 6)
    print("uso: foto SAIDA.json | comparar A.json B.json [...] | avg [N]")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
