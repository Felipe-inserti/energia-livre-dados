"""Clientes GCS e BigQuery (autenticação por ADC) e as operações usadas pelos extratores.

Proteção de custo: TODA consulta ao BigQuery passa por `executar_consulta`, que sempre define
`maximum_bytes_billed`. Se a consulta ultrapassar o limite, o BigQuery a recusa antes de cobrar.
Jobs de carga (`carregar_csv_no_bigquery`) não são cobrados e não usam esse limite.
"""

import base64
import hashlib
import io
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from google.api_core.exceptions import NotFound
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


def md5_base64(conteudo: bytes) -> str:
    """MD5 em base64, o mesmo formato de `blob.md5_hash` do GCS (para comparar sem baixar)."""
    return base64.b64encode(hashlib.md5(conteudo, usedforsecurity=False).digest()).decode()


def md5_base64_de_hex(hexadecimal: str) -> str:
    """MD5 em hexadecimal (como o ETag do S3) -> o mesmo MD5 em base64 (como `blob.md5_hash`)."""
    return base64.b64encode(bytes.fromhex(hexadecimal)).decode()


def buscar_objeto(cliente: storage.Client, bucket: str, caminho: str) -> storage.Blob | None:
    """O objeto (com metadados: md5, tamanho, data de gravação) ou None se não existir."""
    return cliente.bucket(bucket).get_blob(caminho)


def listar_objetos(cliente: storage.Client, bucket: str, prefixo: str) -> dict[str, storage.Blob]:
    """Todos os objetos sob o prefixo, com metadados (md5, tamanho), em UMA listagem.

    Serve para comparar o hash de muitos arquivos sem um `get_blob` por arquivo.
    """
    return {blob.name: blob for blob in cliente.list_blobs(bucket, prefix=prefixo)}


def copiar_objeto(cliente: storage.Client, bucket: str, origem: storage.Blob, destino: str) -> str:
    """Cópia dentro do bucket, feita no servidor (nada passa pela minha máquina)."""
    cliente.bucket(bucket).copy_blob(origem, cliente.bucket(bucket), destino)
    return f"gs://{bucket}/{destino}"


def enviar_arquivo_para_gcs(
    cliente: storage.Client,
    bucket: str,
    caminho: str,
    caminho_local: Path,
    *,
    tipo: str = "application/octet-stream",
) -> str:
    """Grava um arquivo local no GCS, em fluxo (sem ler tudo para a memória), com checksum."""
    blob = cliente.bucket(bucket).blob(caminho)
    blob.upload_from_filename(str(caminho_local), content_type=tipo, checksum="crc32c")
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
    particao: str | None = None,
    particionamento: bigquery.TimePartitioning | None = None,
) -> int:
    """Carrega um CSV (com cabeçalho) na tabela e devolve as linhas carregadas.

    `truncar=True` substitui o conteúdo (primeira carga de uma execução full); `False` acrescenta.
    `particao` (`AAAAMM`) carrega só naquela partição, pelo decorador `tabela$AAAAMM`: com
    `truncar=True` o job substitui APENAS aquela partição, de forma atômica. Todas as linhas do CSV
    precisam pertencer a ela, senão o BigQuery recusa o job (medido no spike da Sprint 4).
    `particionamento`: o particionamento esperado da tabela, para o truncate de tabela inteira.
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
    if particionamento is not None:
        configuracao.time_partitioning = particionamento
    destino = f"{tabela_id}${particao}" if particao else tabela_id
    job = cliente.load_table_from_file(io.BytesIO(conteudo), destino, job_config=configuracao)
    job.result()
    return int(job.output_rows or 0)


class TabelaIncompativel(Exception):
    """A tabela do raw existe, mas não é particionada por mês na coluna esperada."""


def particionamento_mensal(campo: str) -> bigquery.TimePartitioning:
    return bigquery.TimePartitioning(type_=bigquery.TimePartitioningType.MONTH, field=campo)


def garantir_tabela_particionada(
    cliente: bigquery.Client,
    tabela_id: str,
    esquema: list[bigquery.SchemaField],
    campo: str,
    *,
    criar: bool,
) -> str:
    """Confere que a tabela é particionada por mês em `campo`. Devolve "existente" ou "criada".

    NUNCA apaga nem recria uma tabela existente: se ela não for particionada como esperado, levanta
    `TabelaIncompativel` (a migração do raw de produção é um passo manual, com backup). Se não
    existir, cria (só quando `criar=True`, o caso da carga full).
    """
    try:
        tabela = cliente.get_table(tabela_id)
    except NotFound:
        if not criar:
            raise TabelaIncompativel(
                f"{tabela_id} não existe: carregue-a primeiro com --full"
            ) from None
        nova = bigquery.Table(tabela_id, schema=esquema)
        nova.time_partitioning = particionamento_mensal(campo)
        cliente.create_table(nova)
        return "criada"
    particao = tabela.time_partitioning
    if particao is None or particao.field != campo or particao.type_ != "MONTH":
        atual = "sem partição" if particao is None else f"{particao.type_} em {particao.field}"
        raise TabelaIncompativel(
            f"{tabela_id} está {atual}, e o esperado é MONTH em {campo}. Esta execução não altera "
            "a tabela: rode a migração (backup + recriação com --full)."
        )
    return "existente"


@dataclass(frozen=True)
class Trabalho:
    """Um load job: o CSV, as linhas que ele deve carregar e onde (partição `AAAAMM` ou tabela)."""

    conteudo: bytes
    linhas: int
    particao: str | None = None
    truncar: bool = True


class ErroCargaParcial(Exception):
    """Algum load job falhou: `falhas` (rótulo -> causa) e `ok` (os que passaram)."""

    def __init__(self, falhas: dict[str, str], ok: dict[str, int]):
        self.falhas, self.ok = falhas, ok
        lista = "; ".join(f"{k}: {v}" for k, v in sorted(falhas.items()))
        super().__init__(f"{len(falhas)} de {len(falhas) + len(ok)} cargas falharam: {lista}")


def carregar_em_paralelo(
    cliente: bigquery.Client,
    tabela_id: str,
    trabalhos: Mapping[str, Trabalho],
    esquema: list[bigquery.SchemaField],
    *,
    concorrencia: int = 8,
    carregar: Callable[..., int] = carregar_csv_no_bigquery,
) -> dict[str, int]:
    """Roda os load jobs com concorrência limitada e ESPERA TODOS; devolve rótulo -> linhas.

    Se algum falhar (inclusive por contagem de linhas diferente da esperada), levanta
    `ErroCargaParcial` listando os que falharam DEPOIS de os outros terminarem. Cada partição é
    atômica, mas entre partições não há atomicidade: uma falha deixa meses novos e antigos
    misturados. É aceitável porque reexecutar é seguro (cada job substitui a sua partição).
    """
    if concorrencia < 1:
        raise ValueError("a concorrência precisa ser pelo menos 1")

    def executar(rotulo: str) -> int:
        t = trabalhos[rotulo]
        carregadas = carregar(
            cliente, tabela_id, t.conteudo, esquema, truncar=t.truncar, particao=t.particao
        )
        if carregadas != t.linhas:
            raise RuntimeError(f"o CSV tem {t.linhas} linhas e o job carregou {carregadas}")
        return carregadas

    ok: dict[str, int] = {}
    falhas: dict[str, str] = {}
    if not trabalhos:
        return ok
    with ThreadPoolExecutor(max_workers=min(concorrencia, len(trabalhos))) as pool:
        futuros = {rotulo: pool.submit(executar, rotulo) for rotulo in sorted(trabalhos)}
        for rotulo, futuro in futuros.items():
            try:
                ok[rotulo] = futuro.result()
            except Exception as erro:  # noqa: BLE001 (qualquer falha vira item da lista)
                falhas[rotulo] = f"{type(erro).__name__}: {erro}"
    if falhas:
        raise ErroCargaParcial(falhas, ok)
    return ok


def listar_particoes(cliente: bigquery.Client, tabela_id: str) -> list[str]:
    """`partition_id` das partições da tabela (metadados: o job fatura só o piso de 10 MiB)."""
    projeto, dataset, tabela = tabela_id.split(".")
    resultado = executar_consulta(
        cliente,
        f"SELECT partition_id FROM `{projeto}.{dataset}.INFORMATION_SCHEMA.PARTITIONS` "
        f"WHERE table_name = '{tabela}' AND total_rows > 0",
        usar_cache=False,
    )
    return [linha["partition_id"] for linha in resultado.linhas]


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
