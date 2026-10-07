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
FROM `{tabela}`{filtro}
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
    # Escrita no bronze (só o ONS, desde a 3.4): gravar só o que mudou, por hash
    gcs_gravados: int = 0
    gcs_pulados: int = 0  # hash igual ao do objeto que já está no bucket
    gcs_versoes: int = 0  # versões antigas arquivadas porque o arquivo mudou
    gcs_bytes_gravados: int = 0
    gcs_bytes_versoes: int = 0
    revisoes: list[dict] = field(default_factory=list)  # resultado de ingestion.revisoes
    # Carga incremental do ONS (Sprint 4)
    jobs_bigquery: int = 0  # load jobs enviados ao BigQuery
    particoes_carregadas: list[str] = field(default_factory=list)  # `AAAAMM` recarregadas
    anos_recarregados: list[int] = field(default_factory=list)  # anos inteiros (ETag/guarda)
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
    dataset: str = DATASET_RAW  # dataset da tabela (a validação do incremental usa outro)
    filtro_sql: str = ""  # restringe a conferência (ex.: só as partições recarregadas)


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
                tabela=config.tabela(conjunto.dataset, conjunto.tabela),
                filtro=f"\nWHERE {conjunto.filtro_sql}" if conjunto.filtro_sql else "",
            ),
        )
        # str(): uma chave DATE (ex.: `_mes_referencia`) chega como `date` e é comparada como texto
        no_raw = {tuple(str(r[c]) for c in conjunto.colunas_chave): r for r in resultado.linhas}
        for chave, (linhas, vazios) in esperado.items():
            nome = " | ".join(chave)
            r = no_raw.get(chave)
            if r is None:
                problemas.append(f"{nome}: ausente em {conjunto.dataset}.{conjunto.tabela}")
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
                f"{conjunto.dataset}.{conjunto.tabela}: "
                f"registros que não vieram desta carga: {extras[:5]}"
            )
        log.info(
            "validação %s.%s: %d grupos, %d NULL, %d strings vazias",
            conjunto.dataset,
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
    if medicoes.jobs_bigquery:
        print(f"load jobs no BigQuery: {medicoes.jobs_bigquery}")
    if medicoes.particoes_carregadas:
        print(
            f"partições recarregadas: {len(medicoes.particoes_carregadas)} "
            f"({medicoes.particoes_carregadas[0]} a {medicoes.particoes_carregadas[-1]})"
        )
    if medicoes.anos_recarregados:
        print(f"anos recarregados por inteiro (ETag/guarda): {medicoes.anos_recarregados}")
    if medicoes.gcs_gravados + medicoes.gcs_pulados:
        print(
            f"GCS (bronze): {medicoes.gcs_gravados} arquivos gravados "
            f"({medicoes.gcs_bytes_gravados / 1e6:.2f} MB), "
            f"{medicoes.gcs_pulados} pulados por hash igual, "
            f"{medicoes.gcs_versoes} versões antigas arquivadas "
            f"({medicoes.gcs_bytes_versoes / 1e6:.2f} MB)"
        )
        total = medicoes.gcs_bytes_gravados + medicoes.gcs_bytes_versoes
        print(
            f"MB gravados no GCS nesta execução: {total / 1e6:.2f} "
            f"(a carga full anterior gravava {medicoes.bytes_origem / 1e6:.1f} MB)"
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
