"""Confere que toda coluna que existe de verdade no BigQuery tem descrição no dbt.

Compara o catálogo (`dbt docs generate`, colunas reais das tabelas) com o manifesto (descrições dos
YAML, com os blocos `{{ doc() }}` já resolvidos). Falha (código 1) se faltar alguma, listando-as.

    uv run --env-file .env dbt docs generate --project-dir dbt --profiles-dir dbt
    uv run python scripts/verificar_docs.py
"""

import json
import sys
from pathlib import Path

TARGET = Path(__file__).resolve().parent.parent / "dbt" / "target"


def colunas_sem_descricao(catalogo: dict, manifesto: dict) -> tuple[int, list[str]]:
    """Devolve (total de colunas, 'objeto.coluna' de cada uma que não tem descrição)."""
    total, faltam = 0, []
    for secao, no_manifesto in (("nodes", "nodes"), ("sources", "sources")):
        for unique_id, objeto in sorted(catalogo[secao].items()):
            declaradas = manifesto[no_manifesto][unique_id]["columns"]
            for coluna in objeto["columns"]:
                total += 1
                descricao = declaradas.get(coluna.lower(), declaradas.get(coluna, {}))
                if not descricao.get("description", "").strip():
                    faltam.append(f"{unique_id.split('.')[-1]}.{coluna}")
    return total, faltam


def main() -> int:
    catalogo = json.loads((TARGET / "catalog.json").read_text())
    manifesto = json.loads((TARGET / "manifest.json").read_text())
    total, faltam = colunas_sem_descricao(catalogo, manifesto)
    print(f"{total - len(faltam)}/{total} colunas com descrição")
    for nome in faltam:
        print(f"  sem descrição: {nome}")
    return 1 if faltam else 0


if __name__ == "__main__":
    sys.exit(main())
