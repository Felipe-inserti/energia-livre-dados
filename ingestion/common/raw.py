"""O que os extratores têm em comum: medições, carga no raw, validação pós-carga e resumo.

Cada extrator (ONS, CCEE, INMET) sabe de onde vêm os arquivos e como montar o CSV do raw; o resto
(cronometrar, carregar no BigQuery, conferir contagens, medir a consulta típica e imprimir o
resumo para o docs/metricas.md) fica aqui.
"""

import time
from dataclasses import dataclass, field

from google.cloud import bigquery

from ingestion.common import gcp
from ingestion.common.config import DATASET_RAW, Config
from ingestion.common.logs import obter_logger

log = obter_logger("ingestion.raw")

CONSULTA_VALIDACAO = """
SELECT {chaves},
       COUNT(*) AS linhas,
       COUNTIF({valor} IS NULL) AS nulos,
       COUNTIF({valor} = '') AS strings_vazias
FROM `{tabela}`
GROUP BY {chaves}
"""


@dataclass
class Medicoes:
    arquivos: int = 0
    bytes_origem: int = 0  # volume dos arquivos de origem (baixados ou lidos da pasta manual)
    linhas_csv: int = 0
    linhas_carregadas: int = 0
    t_origem: float = 0.0  # download ou leitura (e transformação)
    t_gcs: float = 0.0
    t_bigquery: float = 0.0
    por_arquivo: list[tuple[str, int, int]] = field(default_factory=list)  # nome, bytes, linhas
    # tabela -> chave -> (linhas, valores vazios na coluna de valor), para validar o raw
    esperado: dict[str, dict[tuple[str, ...], tuple[int, int]]] = field(default_factory=dict)

    @property
    def t_total(self) -> float:
        return self.t_origem + self.t_gcs + self.t_bigquery

    def registrar_arquivo(self, nome: str, tamanho: int, linhas: int) -> None:
        self.arquivos += 1
        self.bytes_origem += tamanho
        self.linhas_csv += linhas
        self.por_arquivo.append((nome, tamanho, linhas))

    def registrar_esperado(
        self, tabela: str, chave: tuple[str, ...], linhas: int, vazios: int
    ) -> None:
        self.esperado.setdefault(tabela, {})[chave] = (linhas, vazios)


class Carregador:
    """Carrega CSVs numa tabela do raw: o primeiro job trunca, os demais acrescentam."""

    def __init__(
        self,
        cliente: bigquery.Client,
        tabela_id: str,
        esquema: list[bigquery.SchemaField],
        medicoes: Medicoes,
    ):
        self.cliente = cliente
        self.tabela_id = tabela_id
        self.esquema = esquema
        self.medicoes = medicoes
        self._truncar = True

    def carregar(self, conteudo: bytes, linhas: int, rotulo: str) -> int:
        """Carrega o CSV e confere que o job carregou tantas linhas quanto o CSV tem."""
        t0 = time.perf_counter()
        carregadas = gcp.carregar_csv_no_bigquery(
            self.cliente, self.tabela_id, conteudo, self.esquema, truncar=self._truncar
        )
        self.medicoes.t_bigquery += time.perf_counter() - t0
        self._truncar = False
        if carregadas != linhas:
            raise RuntimeError(f"{rotulo}: o CSV tem {linhas} linhas e o job carregou {carregadas}")
        self.medicoes.linhas_carregadas += carregadas
        return carregadas


@dataclass(frozen=True)
class ConjuntoValidacao:
    tabela: str  # nome da tabela no dataset raw
    coluna_valor: str  # coluna em que se contam os vazios
    colunas_chave: tuple[str, ...] = ("_arquivo_origem",)  # agrupamento da conferência


def validar_raw(
    config: Config, medicoes: Medicoes, conjuntos: list[ConjuntoValidacao]
) -> list[str]:
    """Compara, por chave, as linhas e os vazios do raw com os dos CSVs. Devolve os problemas."""
    bq_cli = gcp.cliente_bigquery(config)
    problemas = []
    for conjunto in conjuntos:
        esperado = medicoes.esperado.get(conjunto.tabela, {})
        resultado = gcp.executar_consulta(
            bq_cli,
            CONSULTA_VALIDACAO.format(
                chaves=", ".join(conjunto.colunas_chave),
                valor=conjunto.coluna_valor,
                tabela=config.tabela(DATASET_RAW, conjunto.tabela),
            ),
        )
        no_raw = {tuple(r[c] for c in conjunto.colunas_chave): r for r in resultado.linhas}
        for chave, (linhas, vazios) in esperado.items():
            nome = " | ".join(chave)
            r = no_raw.get(chave)
            if r is None:
                problemas.append(f"{nome}: ausente em raw.{conjunto.tabela}")
                continue
            if r["linhas"] != linhas:
                problemas.append(f"{nome}: {r['linhas']} linhas no raw, {linhas} no CSV")
            if r["nulos"] + r["strings_vazias"] != vazios:
                problemas.append(
                    f"{nome}: {r['nulos']} NULL + {r['strings_vazias']} '' no raw, "
                    f"{vazios} vazios no CSV"
                )
        extras = sorted(set(no_raw) - set(esperado))
        if extras:
            problemas.append(
                f"raw.{conjunto.tabela}: registros que não vieram desta carga: {extras[:5]}"
            )
        log.info(
            "validação raw.%s: %d grupos, %d NULL, %d strings vazias",
            conjunto.tabela,
            len(no_raw),
            sum(r["nulos"] for r in no_raw.values()),
            sum(r["strings_vazias"] for r in no_raw.values()),
        )
    return problemas


def medir_consulta_tipica(config: Config, sql: str) -> dict[str, object]:
    """Dry-run (estimativa) e execução sem cache (medição de verdade) da consulta típica."""
    bq_cli = gcp.cliente_bigquery(config)
    estimativa = gcp.executar_consulta(bq_cli, sql, dry_run=True)
    real = gcp.executar_consulta(bq_cli, sql, usar_cache=False)
    return {
        "bytes_estimados": estimativa.bytes_processados,
        "bytes_processados": real.bytes_processados,
        "bytes_faturados": real.bytes_faturados,
        "cache": real.cache,
        "linhas": len(real.linhas),
    }


def imprimir_resumo(
    titulo: str,
    medicoes: Medicoes,
    consulta: dict | None,
    *,
    rotulo_volume: str,
    rotulo_origem: str,
    descricao_consulta: str,
    detalhe_arquivos: str = "",
    listar_arquivos: bool = False,
    linhas_esperadas_consulta: int = 24,
) -> None:
    """Imprime as medições no formato que se cola no docs/metricas.md."""
    print(f"\n=== Medições {titulo} (para docs/metricas.md) ===")
    print(f"arquivos: {medicoes.arquivos}{detalhe_arquivos}")
    print(f"{rotulo_volume}: {medicoes.bytes_origem / 1e6:.1f} MB")
    print(f"linhas nos CSVs: {medicoes.linhas_csv:,}")
    print(f"linhas carregadas: {medicoes.linhas_carregadas:,}")
    print(
        f"tempo total da carga: {medicoes.t_total:.1f} s "
        f"({rotulo_origem} {medicoes.t_origem:.1f} s, GCS {medicoes.t_gcs:.1f} s, "
        f"BigQuery {medicoes.t_bigquery:.1f} s)"
    )
    if listar_arquivos:
        print("linhas por arquivo:")
        for nome, tamanho, linhas in medicoes.por_arquivo:
            print(f"  {nome}: {linhas:,} linhas, {tamanho / 1e6:.2f} MB")
    if consulta:
        proc, fat = consulta["bytes_processados"], consulta["bytes_faturados"]
        print(f"consulta típica ({descricao_consulta}, tabela sem partição):")
        print(f"  estimativa do dry-run: {consulta['bytes_estimados']:,} bytes")
        print(f"  bytes processados: {proc:,} ({proc / 1e6:.1f} MB)")
        print(f"  bytes faturados: {fat:,} ({fat / 1e6:.1f} MB) | cache: {consulta['cache']}")
        print(f"  linhas devolvidas: {consulta['linhas']} (esperado: {linhas_esperadas_consulta})")
