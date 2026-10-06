"""Auditoria da cobertura de testes do dbt (tarefa 3.1), a partir do `target/manifest.json`.

    uv run --env-file .env dbt parse --project-dir dbt --profiles-dir dbt
    uv run python scripts/auditar_testes.py

Lista, por modelo: se há teste de unicidade da chave, as colunas de chave sem `not_null` e as
colunas `*_utc`/`codigo_*`/`uf` sem `relationships` ou `accepted_values`, e as fontes sem teste.
É uma ajuda para achar lacunas, não um critério: o que falta de propósito (ex.: carga nula, que
tem exceções conhecidas) aparece na lista e a justificativa vai no YAML.
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

MANIFESTO = Path(__file__).resolve().parent.parent / "dbt" / "target" / "manifest.json"
UNICIDADE = {"unique", "unique_combination_of_columns"}
SUFIXOS_CHAVE = ("_utc",)
PREFIXOS_CHAVE = ("codigo_", "id_")


def tipo_do_teste(no: dict) -> str:
    return no.get("test_metadata", {}).get("name", "singular")


def colunas_do_teste(no: dict) -> list[str]:
    args = no.get("test_metadata", {}).get("kwargs", {})
    if "combination_of_columns" in args:
        return list(args["combination_of_columns"])
    nome = args.get("column_name") or no.get("column_name")
    return [nome] if nome else []


def auditar(manifesto: dict) -> dict[str, list[str]]:
    testes = defaultdict(lambda: defaultdict(set))  # alvo -> coluna -> tipos
    unicidade = defaultdict(bool)
    for no in manifesto["nodes"].values():
        if no["resource_type"] != "test" or not no.get("attached_node"):
            continue
        alvo = no["attached_node"]
        tipo = tipo_do_teste(no)
        if tipo in UNICIDADE:
            unicidade[alvo] = True
        for coluna in colunas_do_teste(no):
            testes[alvo][coluna].add(tipo)

    problemas: dict[str, list[str]] = {}
    for uid, no in manifesto["nodes"].items():
        if no["resource_type"] != "model":
            continue
        achados = []
        if not unicidade[uid] and not no["name"].startswith("int_"):
            achados.append("sem teste de unicidade")
        for coluna in no["columns"]:
            tipos = testes[uid][coluna]
            chave = coluna.endswith(SUFIXOS_CHAVE) or coluna.startswith(PREFIXOS_CHAVE)
            if chave and "not_null" not in tipos:
                achados.append(f"{coluna}: chave sem not_null")
            if (coluna.startswith("codigo_") or coluna == "uf") and not tipos & {
                "relationships",
                "accepted_values",
            }:
                achados.append(f"{coluna}: sem relationships nem accepted_values")
        if achados:
            problemas[no["name"]] = achados
    for uid, fonte in manifesto["sources"].items():
        if not any(
            no["resource_type"] == "test" and uid in no.get("depends_on", {}).get("nodes", [])
            for no in manifesto["nodes"].values()
        ):
            problemas.setdefault(f"source:{fonte['name']}", []).append("fonte sem nenhum teste")
    return problemas


def main() -> int:
    manifesto = json.loads(MANIFESTO.read_text())
    contagem = defaultdict(int)
    for no in manifesto["nodes"].values():
        if no["resource_type"] == "test":
            contagem[tipo_do_teste(no)] += 1
    print("testes por tipo:", dict(sorted(contagem.items())), "| total:", sum(contagem.values()))
    problemas = auditar(manifesto)
    for nome, achados in sorted(problemas.items()):
        print(f"\n{nome}")
        for a in achados:
            print(f"  - {a}")
    print(f"\n{len(problemas)} objetos com achados")
    return 0


if __name__ == "__main__":
    sys.exit(main())
