"""`scripts/medir_bytes_bigquery.py`: jobs de SCRIPT (o MERGE do insert_overwrite) não podem ser
contados em dobro nem ficar de fora do balde do dbt. A consulta roda na nuvem; aqui se confere a
regra no texto do SQL e, com um simulador em Python, o efeito dela sobre o caso real medido."""

import re

from scripts import medir_bytes_bigquery as m

SQL = m.SQL.format(regiao="us-central1", desde="2026-10-07T03:04:00", ate="2026-10-07T03:04:18")


def test_o_job_pai_do_script_nao_entra_na_soma():
    assert "statement_type != 'SCRIPT'" in SQL


def test_o_filho_herda_a_classificacao_do_pai_que_carrega_o_comentario_do_dbt():
    assert "LEFT JOIN jobs AS p ON j.parent_job_id = p.job_id" in SQL
    assert "COALESCE(p.query, j.query)" in SQL


def test_a_janela_do_pai_e_mais_larga_que_a_dos_filhos():
    # o pai nasce antes dos filhos: sem folga, um filho no início da janela ficaria órfão
    assert "TIMESTAMP_SUB(TIMESTAMP('2026-10-07T03:04:00'), INTERVAL 1 HOUR)" in SQL
    assert "WHERE j.creation_time >= TIMESTAMP('2026-10-07T03:04:00')" in SQL


def simular(jobs: list[dict]) -> dict[str, tuple[int, float]]:
    """A mesma regra do SQL, em Python: (jobs, MB faturados) por balde."""
    por_id = {j["id"]: j for j in jobs}
    saida: dict[str, tuple[int, float]] = {}
    for j in jobs:
        if j["tipo"] == "SCRIPT":
            continue
        pai = por_id.get(j.get("pai"))
        consulta = (pai or j)["query"]
        balde = "dbt" if re.search(r'"app": ?"dbt"', consulta) else "outros"
        n, fat = saida.get(balde, (0, 0.0))
        saida[balde] = (n + 1, round(fat + j["fat"], 2))
    return saida


# os jobs de uma execução incremental real (checkpoint 4, 07/10/2026 03:04)
INCREMENTAL = [
    {
        "id": "a",
        "tipo": "CREATE_TABLE_AS_SELECT",
        "query": '/* {"app": "dbt"} */ create ...',
        "fat": 10.49,
    },
    {
        "id": "b",
        "tipo": "SCRIPT",
        "query": '/* {"app": "dbt"} */ merge ...; drop ...',
        "fat": 20.97,
    },
    {"id": "c", "tipo": "MERGE", "pai": "b", "query": "merge into ...", "fat": 20.97},
    {"id": "d", "tipo": "DROP_TABLE", "pai": "b", "query": "drop table ...", "fat": 0.0},
]


def test_execucao_incremental_real_soma_31_5_mb_todos_no_balde_do_dbt():
    assert simular(INCREMENTAL) == {"dbt": (3, 31.46)}  # CTAS + MERGE + DROP; o pai não conta


def test_sem_a_heranca_o_merge_cairia_em_outros_que_foi_o_erro_do_checkpoint_4():
    sem_heranca = [{**j, "pai": None} for j in INCREMENTAL]
    assert simular(sem_heranca) == {"dbt": (1, 10.49), "outros": (2, 20.97)}
