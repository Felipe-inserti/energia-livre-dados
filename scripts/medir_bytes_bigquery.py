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
SELECT
  IF(REGEXP_CONTAINS(query, r'"app": ?"dbt"'), 'dbt', 'outros (ingestão, freshness)') AS origem,
  COUNT(*) AS jobs,
  COUNTIF(error_result IS NOT NULL) AS com_erro,
  SUM(total_bytes_processed) AS bytes_processados,
  SUM(total_bytes_billed) AS bytes_faturados
FROM `region-{regiao}`.INFORMATION_SCHEMA.JOBS_BY_USER
WHERE job_type = 'QUERY'
  AND creation_time >= TIMESTAMP('{desde}') AND creation_time < TIMESTAMP('{ate}')
  AND (statement_type IS NULL OR statement_type != 'SCRIPT')
GROUP BY origem
ORDER BY origem
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bytes do BigQuery num intervalo (UTC)")
    parser.add_argument("--desde", required=True, help="início, ex.: 2026-10-06T21:00:00")
    parser.add_argument("--ate", default=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S"))
    args = parser.parse_args(argv)

    config = carregar_config()
    sql = SQL.format(regiao=config.localizacao.lower(), desde=args.desde, ate=args.ate)
    resultado = gcp.executar_consulta(gcp.cliente_bigquery(config), sql, usar_cache=False)
    print(f"intervalo (UTC): {args.desde} a {args.ate}")
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
