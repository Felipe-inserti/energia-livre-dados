"""Soma os bytes que o BigQuery processou e faturou num intervalo (custo de uma execução da DAG).

    uv run python -m scripts.medir_bytes_bigquery --desde 2026-10-06T21:00:00 [--ate ...]

Lê `INFORMATION_SCHEMA.JOBS_BY_USER` (metadados dos seus jobs, na região do projeto), com o teto de
bytes de `executar_consulta`. Separa os jobs do dbt (o dbt marca o SQL com um comentário
`{"app": "dbt"...}`) dos demais (validação do raw e freshness da ingestão). Jobs de carga não são
consultas e não entram: não são cobrados. O horário é UTC.
"""

import argparse
import sys
from datetime import UTC, datetime

from ingestion.common import gcp
from ingestion.common.config import carregar_config

SQL = """
WITH jobs AS (
  SELECT job_id, parent_job_id, statement_type, query, error_result,
         total_bytes_processed, total_bytes_billed, creation_time
  FROM `region-{regiao}`.INFORMATION_SCHEMA.JOBS_BY_USER
  WHERE job_type = 'QUERY'
    AND creation_time >= TIMESTAMP_SUB(TIMESTAMP('{desde}'), INTERVAL 1 HOUR)
    AND creation_time < TIMESTAMP('{ate}')
)
SELECT
  -- um job FILHO de um script (o MERGE do insert_overwrite) não carrega o comentário do dbt: ele
  -- herda a classificação do job pai, que carrega
  IF(REGEXP_CONTAINS(COALESCE(p.query, j.query), r'"app": ?"dbt"'),
     'dbt', 'outros (ingestão, freshness)') AS origem,
  COUNT(*) AS jobs,
  COUNTIF(j.error_result IS NOT NULL) AS com_erro,
  SUM(j.total_bytes_processed) AS bytes_processados,
  SUM(j.total_bytes_billed) AS bytes_faturados
FROM jobs AS j
LEFT JOIN jobs AS p ON j.parent_job_id = p.job_id
WHERE j.creation_time >= TIMESTAMP('{desde}')
  -- o job pai (SCRIPT) soma os filhos: contá-lo junto com eles contaria tudo em dobro
  AND (j.statement_type IS NULL OR j.statement_type != 'SCRIPT')
GROUP BY origem
ORDER BY origem
"""

SQL_LISTAR = """
SELECT FORMAT_TIMESTAMP('%H:%M:%S', creation_time) AS hora, statement_type AS tipo,
       IF(parent_job_id IS NULL, 'pai/único', 'filho') AS papel,
       IFNULL(destination_table.table_id, '-') AS destino,
       ROUND(total_bytes_processed / 1e6, 2) AS proc_mb,
       ROUND(total_bytes_billed / 1e6, 2) AS fat_mb,
       IF(statement_type = 'SCRIPT', 'NÃO soma (é a soma dos filhos)', 'soma') AS conta
FROM `region-{regiao}`.INFORMATION_SCHEMA.JOBS_BY_USER
WHERE job_type = 'QUERY'
  AND creation_time >= TIMESTAMP('{desde}') AND creation_time < TIMESTAMP('{ate}')
ORDER BY creation_time
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bytes do BigQuery num intervalo (UTC)")
    parser.add_argument("--desde", required=True, help="início, ex.: 2026-10-06T21:00:00")
    parser.add_argument("--ate", default=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S"))
    parser.add_argument(
        "--listar", action="store_true", help="mostra cada job (pai, filhos, bytes)"
    )
    args = parser.parse_args(argv)

    config = carregar_config()
    sql = SQL.format(regiao=config.localizacao.lower(), desde=args.desde, ate=args.ate)
    resultado = gcp.executar_consulta(gcp.cliente_bigquery(config), sql, usar_cache=False)
    print(f"intervalo (UTC): {args.desde} a {args.ate}")
    if args.listar:
        lista = SQL_LISTAR.format(regiao=config.localizacao.lower(), desde=args.desde, ate=args.ate)
        for j in gcp.executar_consulta(
            gcp.cliente_bigquery(config), lista, usar_cache=False
        ).linhas:
            print(
                f"  {j['hora']} {j['tipo']:<22} {j['papel']:<9} {j['destino'][:38]:<38} "
                f"proc {j['proc_mb']:>7} MB | fat {j['fat_mb']:>7} MB | {j['conta']}"
            )
    total_proc = total_fat = 0
    for linha in resultado.linhas:
        proc, fat = int(linha["bytes_processados"] or 0), int(linha["bytes_faturados"] or 0)
        total_proc, total_fat = total_proc + proc, total_fat + fat
        print(
            f"{linha['origem']:32} {linha['jobs']:>4} jobs ({linha['com_erro']} com erro) | "
            f"processados {proc / 1e6:>9.1f} MB | faturados {fat / 1e6:>9.1f} MB"
        )
    print(
        f"{'total':32} processados {total_proc / 1e6:.1f} MB | faturados {total_fat / 1e6:.1f} MB"
    )
    print(f"(a própria consulta leu {resultado.bytes_processados / 1e6:.1f} MB de metadados)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
