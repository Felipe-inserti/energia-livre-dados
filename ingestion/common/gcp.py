"""Clientes GCS e BigQuery (autenticação por ADC) e as operações usadas pelos extratores.

Proteção de custo: TODA consulta ao BigQuery passa por `executar_consulta`, que sempre define
`maximum_bytes_billed`. Se a consulta ultrapassar o limite, o BigQuery a recusa antes de cobrar.
Jobs de carga (`carregar_csv_no_bigquery`) não são cobrados e não usam esse limite.
"""

import io
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from google.cloud import bigquery, storage

from ingestion.common.config import Config

MAX_BYTES_PADRAO = 200 * 1024 * 1024  # 200 MiB por consulta


def cliente_storage(config: Config) -> storage.Client:
    return storage.Client(project=config.projeto)


def cliente_bigquery(config: Config) -> bigquery.Client:
    return bigquery.Client(project=config.projeto, location=config.localizacao)


def enviar_para_gcs(
    cliente: storage.Client,
    bucket: str,
    caminho: str,
    conteudo: bytes,
    *,
    tipo: str = "text/csv",
) -> str:
    """Grava os bytes no GCS exatamente como recebidos (com checksum) e devolve o `gs://`."""
    blob = cliente.bucket(bucket).blob(caminho)
    blob.upload_from_string(conteudo, content_type=tipo, checksum="crc32c")
    return f"gs://{bucket}/{caminho}"


def montar_esquema(
    colunas_fonte: Sequence[str], extras: dict[str, str]
) -> list[bigquery.SchemaField]:
    """Colunas da fonte como STRING (a tipagem é do dbt) + colunas extras com seus tipos."""
    return [
        *(bigquery.SchemaField(c, "STRING") for c in colunas_fonte),
        *(bigquery.SchemaField(nome, tipo) for nome, tipo in extras.items()),
    ]


def carregar_csv_no_bigquery(
    cliente: bigquery.Client,
    tabela_id: str,
    conteudo: bytes,
    esquema: list[bigquery.SchemaField],
    *,
    truncar: bool,
) -> int:
    """Carrega um CSV (com cabeçalho) na tabela e devolve as linhas carregadas.

    `truncar=True` substitui o conteúdo da tabela (primeira carga de uma execução full);
    `False` acrescenta.
    """
    configuracao = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.CSV,
        skip_leading_rows=1,
        schema=esquema,
        write_disposition=(
            bigquery.WriteDisposition.WRITE_TRUNCATE
            if truncar
            else bigquery.WriteDisposition.WRITE_APPEND
        ),
    )
    job = cliente.load_table_from_file(io.BytesIO(conteudo), tabela_id, job_config=configuracao)
    job.result()
    return int(job.output_rows or 0)


@dataclass(frozen=True)
class ResultadoConsulta:
    linhas: list[Any]
    bytes_processados: int | None
    bytes_faturados: int | None
    cache: bool | None


def executar_consulta(
    cliente: bigquery.Client,
    sql: str,
    *,
    max_bytes_faturados: int = MAX_BYTES_PADRAO,
    usar_cache: bool = True,
    dry_run: bool = False,
) -> ResultadoConsulta:
    """Única porta para consultas: sempre com `maximum_bytes_billed`.

    `dry_run=True` só estima os bytes (não executa nem cobra). `usar_cache=False` serve para
    medições, porque uma consulta atendida pelo cache reporta 0 bytes.
    """
    if max_bytes_faturados is None or max_bytes_faturados <= 0:
        raise ValueError("max_bytes_faturados deve ser um inteiro positivo")
    configuracao = bigquery.QueryJobConfig(
        maximum_bytes_billed=max_bytes_faturados,
        use_query_cache=usar_cache,
        dry_run=dry_run,
    )
    job = cliente.query(sql, job_config=configuracao)
    if dry_run:
        return ResultadoConsulta([], job.total_bytes_processed, None, None)
    linhas = list(job.result())
    return ResultadoConsulta(
        linhas, job.total_bytes_processed, job.total_bytes_billed, job.cache_hit
    )
