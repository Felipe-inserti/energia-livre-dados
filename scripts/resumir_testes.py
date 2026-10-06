"""Resume o `run_results.json` do dbt: quantos registros problemáticos cada teste pegou (3.2).

    uv run --env-file .env dbt test --project-dir dbt --profiles-dir dbt | tee data/logs/x.log
    uv run python scripts/resumir_testes.py [dbt/target/run_results.json]

O campo `failures` de cada teste é o número de linhas que a consulta do teste devolveu, ou seja, os
registros problemáticos. Não precisa de `--store-failures` (que criaria tabelas no BigQuery).
O tipo do teste vem do `manifest.json`: genérico (not_null, unique, relationships...) ou singular.
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

TARGET = Path(__file__).resolve().parent.parent / "dbt" / "target"


def tipo_do_teste(no: dict) -> str:
    return no.get("test_metadata", {}).get("name", "singular")


def resumir(resultados: dict, manifesto: dict) -> dict:
    por_tipo = defaultdict(lambda: {"testes": 0, "pass": 0, "warn": 0, "error": 0, "registros": 0})
    detalhes = []
    for r in resultados["results"]:
        no = manifesto["nodes"].get(r["unique_id"])
        if no is None or no["resource_type"] != "test":
            continue
        tipo = tipo_do_teste(no)
        falhas = int(r.get("failures") or 0)
        status = {"pass": "pass", "warn": "warn", "fail": "error", "error": "error"}.get(
            r["status"], r["status"]
        )
        linha = por_tipo[tipo]
        linha["testes"] += 1
        linha[status] = linha.get(status, 0) + 1
        linha["registros"] += falhas
        if falhas or status != "pass":
            detalhes.append((status, no["name"], falhas, r["execution_time"]))
    return {"por_tipo": dict(por_tipo), "detalhes": sorted(detalhes)}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    caminho = Path(argv[0]) if argv else TARGET / "run_results.json"
    resultados = json.loads(caminho.read_text())
    manifesto = json.loads((TARGET / "manifest.json").read_text())
    resumo = resumir(resultados, manifesto)
    print(f"{'tipo':32} {'testes':>6} {'pass':>5} {'warn':>5} {'error':>5} {'registros':>10}")
    for tipo, v in sorted(resumo["por_tipo"].items()):
        print(
            f"{tipo:32} {v['testes']:>6} {v['pass']:>5} {v['warn']:>5} {v['error']:>5} "
            f"{v['registros']:>10}"
        )
    total = sum(v["testes"] for v in resumo["por_tipo"].values())
    print(f"{'total':32} {total:>6}")
    print("\ntestes com aviso, erro ou registros problemáticos:")
    for status, nome, falhas, segundos in resumo["detalhes"]:
        print(f"  [{status}] {nome}: {falhas} registros ({segundos:.1f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
