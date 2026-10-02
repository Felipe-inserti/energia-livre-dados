"""Guardas da documentação do dbt (sem rede): toda coluna declarada tem descrição e os blocos
`{{ doc() }}` usados existem. A conferência contra as colunas reais do BigQuery é o
scripts/verificar_docs.py (precisa do catálogo do `dbt docs generate`)."""

import re
from pathlib import Path

import yaml

from scripts.gerar_lineage import ler_grafo, posicoes

RAIZ = Path(__file__).resolve().parent.parent
MODELOS = RAIZ / "dbt" / "models"
YAMLS = sorted(MODELOS.glob("*/_*.yml"))
BLOCOS = set(re.findall(r"\{% docs (\w+) %\}", (MODELOS / "_docs.md").read_text()))


def descricoes():
    """(objeto, coluna, descrição) de cada coluna declarada nos modelos e nas fontes."""
    for caminho in YAMLS:
        dados = yaml.safe_load(caminho.read_text())
        objetos = list(dados.get("models", []))
        for fonte in dados.get("sources", []):
            objetos += fonte["tables"]
        for objeto in objetos:
            for coluna in objeto.get("columns", []):
                yield objeto["name"], coluna["name"], coluna.get("description", "")


def test_toda_coluna_declarada_e_todo_modelo_tem_descricao():
    for caminho in YAMLS:
        dados = yaml.safe_load(caminho.read_text())
        for objeto in list(dados.get("models", [])) + [
            t for f in dados.get("sources", []) for t in f["tables"]
        ]:
            assert objeto.get("description", "").strip(), f"{objeto['name']} sem descrição"
    sem = [f"{o}.{c}" for o, c, d in descricoes() if not d.strip()]
    assert not sem, f"colunas sem descrição: {sem}"


def test_os_blocos_de_documentacao_usados_existem_e_nenhum_sobra():
    usados = set()
    for caminho in YAMLS:
        usados |= set(re.findall(r'doc\("(\w+)"\)', caminho.read_text()))
    assert usados <= BLOCOS, f"blocos que não existem: {usados - BLOCOS}"
    assert BLOCOS <= usados, f"blocos sem uso: {BLOCOS - usados}"


def test_lineage_organiza_as_colunas_por_camada_sem_seta_para_tras():
    manifesto = {
        "nodes": {
            "model.p.stg_a": {
                "name": "stg_a",
                "resource_type": "model",
                "depends_on": {"nodes": ["source.p.raw.a"]},
            },
            "model.p.fct_b": {
                "name": "fct_b",
                "resource_type": "model",
                "depends_on": {"nodes": ["model.p.stg_a", "model.p.dim_c"]},
            },
            "model.p.dim_c": {
                "name": "dim_c",
                "resource_type": "model",
                "depends_on": {"nodes": []},
            },
        },
        "sources": {"source.p.raw.a": {"name": "a"}},
    }
    nomes, tipos, arestas = ler_grafo(manifesto)
    assert len(nomes) == 4 and len(arestas) == 3
    pos = posicoes(nomes, tipos, arestas)
    assert all(pos[pai][0] <= pos[filho][0] for pai, filho in arestas)
    colunas = {n: pos[u][0] for u, n in nomes.items()}
    assert colunas == {"a": 0, "stg_a": 1, "dim_c": 2, "fct_b": 4}  # a coluna vem do tipo
