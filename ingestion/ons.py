"""Extrator da curva de carga horária do ONS: carga FULL, de propósito ingênua (o "antes").

    uv run python -m ingestion.ons [--ano-inicial 2000] [--ano-final 2026] [--sem-consulta]

Para cada ano, de 2000 até o ano atual (sempre tudo, sem incremental):
1. baixa o CSV (com retry);
2. grava o CSV ORIGINAL, sem alteração, no GCS: bronze/ons/curva_carga/ano=AAAA/;
3. carrega no BigQuery raw.ons_curva_carga (sem partição) com as colunas padronizadas, todas
   como STRING (a tipagem é do dbt), mais `_arquivo_origem` e `_carregado_em`.

Nulos e casos conhecidos (docs/fontes.md) entram como estão: o tratamento é do staging e dos
testes da Sprint 3. Ao final valida a carga contra os CSVs e mede a consulta típica.

Limitação assumida nesta versão: a carga por ano não é atômica (o primeiro ano trunca a tabela e
os demais acrescentam); se falhar no meio, a tabela fica parcial até a próxima execução.
"""

import argparse
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ingestion.common import gcp
from ingestion.common.config import DATASET_RAW, Config, carregar_config
from ingestion.common.csv_utils import transformar_csv
from ingestion.common.download import ArquivoNaoEncontrado, baixar_bytes
from ingestion.common.logs import obter_logger

log = obter_logger("ingestion.ons")

ANO_INICIAL = 2000  # primeiro ano publicado (1999 retorna 404)
URL_MODELO = (
    "https://ons-aws-prod-opendata.s3.amazonaws.com/dataset/curva-carga-ho/CURVA_CARGA_{ano}.csv"
)
NOME_TABELA = "ons_curva_carga"
COLUNAS_ESPERADAS = [
    "id_subsistema",
    "nom_subsistema",
    "din_instante",
    "val_cargaenergiahomwmed",
]
COLUNA_VALOR = "val_cargaenergiahomwmed"
TIPOS_EXTRAS = {"_arquivo_origem": "STRING", "_carregado_em": "TIMESTAMP"}

# "Carga média por hora do SE em 2024". As colunas são STRING no raw, então a data é comparada
# como texto ISO e o valor precisa de SAFE_CAST. Esta é a consulta do "antes".
CONSULTA_TIPICA = """
SELECT EXTRACT(HOUR FROM TIMESTAMP(din_instante)) AS hora,
       AVG(SAFE_CAST(val_cargaenergiahomwmed AS FLOAT64)) AS carga_media
FROM `{tabela}`
WHERE id_subsistema = 'SE'
  AND din_instante >= '2024-01-01' AND din_instante < '2025-01-01'
GROUP BY hora
ORDER BY hora
"""

CONSULTA_VALIDACAO = """
SELECT _arquivo_origem,
       COUNT(*) AS linhas,
       COUNTIF({valor} IS NULL) AS nulos,
       COUNTIF({valor} = '') AS strings_vazias
FROM `{tabela}`
GROUP BY _arquivo_origem
"""


def montar_url(ano: int) -> str:
    return URL_MODELO.format(ano=ano)


def nome_arquivo(ano: int) -> str:
    return f"CURVA_CARGA_{ano}.csv"


def caminho_gcs(ano: int) -> str:
    """Caminho do CSV original no bucket (camada bronze), sem o nome do bucket."""
    return f"bronze/ons/curva_carga/ano={ano}/{nome_arquivo(ano)}"


def anos_a_carregar(ano_inicial: int, ano_final: int) -> list[int]:
    if ano_inicial < ANO_INICIAL:
        raise ValueError(f"O ONS publica a partir de {ANO_INICIAL}, não de {ano_inicial}")
    if ano_final < ano_inicial:
        raise ValueError(f"ano_final ({ano_final}) menor que ano_inicial ({ano_inicial})")
    return list(range(ano_inicial, ano_final + 1))


def validar_colunas(colunas: list[str]) -> None:
    """O layout é o mesmo nos 26 anos (docs/fontes.md); se mudar, melhor parar do que carregar."""
    if colunas != COLUNAS_ESPERADAS:
        raise ValueError(f"Layout inesperado: {colunas}, esperado {COLUNAS_ESPERADAS}")


@dataclass
class Medicoes:
    arquivos: int = 0
    bytes_baixados: int = 0
    linhas_csv: int = 0
    linhas_carregadas: int = 0
    t_download: float = 0.0
    t_gcs: float = 0.0
    t_bigquery: float = 0.0
    # caminho no GCS -> (linhas, valores vazios na coluna de valor), para validar o raw
    esperado: dict[str, tuple[int, int]] = field(default_factory=dict)

    @property
    def t_total(self) -> float:
        return self.t_download + self.t_gcs + self.t_bigquery


def carregar_anos(anos: list[int], config: Config, ano_atual: int) -> tuple[Medicoes, list[str]]:
    storage_cli = gcp.cliente_storage(config)
    bq_cli = gcp.cliente_bigquery(config)
    tabela_id = config.tabela(DATASET_RAW, NOME_TABELA)
    carregado_em = datetime.now(UTC).isoformat(timespec="seconds")
    esquema = gcp.montar_esquema(COLUNAS_ESPERADAS, TIPOS_EXTRAS)
    medicoes = Medicoes()
    primeiro = True
    carregados: list[str] = []

    for ano in anos:
        url = montar_url(ano)
        t0 = time.perf_counter()
        try:
            original = baixar_bytes(url)
        except ArquivoNaoEncontrado:
            if (
                ano == ano_atual
            ):  # o arquivo do ano corrente pode ainda não existir (início de janeiro)
                log.warning("%d: arquivo ainda não publicado (404); ano ignorado", ano)
                continue
            raise
        medicoes.t_download += time.perf_counter() - t0
        medicoes.bytes_baixados += len(original)

        # bronze: os bytes originais, sem alteração
        t0 = time.perf_counter()
        caminho = caminho_gcs(ano)
        origem = gcp.enviar_para_gcs(storage_cli, config.bucket, caminho, original)
        medicoes.t_gcs += time.perf_counter() - t0

        # raw: colunas padronizadas + colunas de controle
        t0 = time.perf_counter()
        extras = {"_arquivo_origem": caminho, "_carregado_em": carregado_em}
        csv_raw = transformar_csv(original, extras)
        validar_colunas(csv_raw.colunas)
        linhas = gcp.carregar_csv_no_bigquery(
            bq_cli, tabela_id, csv_raw.conteudo, esquema, truncar=primeiro
        )
        medicoes.t_bigquery += time.perf_counter() - t0
        primeiro = False

        if linhas != csv_raw.linhas:
            raise RuntimeError(
                f"{ano}: o CSV tem {csv_raw.linhas} linhas e o job carregou {linhas}"
            )
        medicoes.arquivos += 1
        medicoes.linhas_csv += csv_raw.linhas
        medicoes.linhas_carregadas += linhas
        medicoes.esperado[caminho] = (csv_raw.linhas, csv_raw.vazios[COLUNA_VALOR])
        carregados.append(origem)
        log.info(
            "%d: %.2f MB baixados, %d linhas -> %s",
            ano,
            len(original) / 1e6,
            linhas,
            origem,
        )
    return medicoes, carregados


def validar_raw(config: Config, medicoes: Medicoes) -> list[str]:
    """Compara, por arquivo, as linhas e os vazios do raw com os dos CSVs. Devolve os problemas."""
    bq_cli = gcp.cliente_bigquery(config)
    tabela_id = config.tabela(DATASET_RAW, NOME_TABELA)
    resultado = gcp.executar_consulta(
        bq_cli, CONSULTA_VALIDACAO.format(tabela=tabela_id, valor=COLUNA_VALOR)
    )
    no_raw = {r["_arquivo_origem"]: r for r in resultado.linhas}
    problemas = []
    for caminho, (linhas, vazios) in medicoes.esperado.items():
        r = no_raw.get(caminho)
        if r is None:
            problemas.append(f"{caminho}: ausente no raw")
            continue
        if r["linhas"] != linhas:
            problemas.append(f"{caminho}: {r['linhas']} linhas no raw, {linhas} no CSV")
        if r["nulos"] + r["strings_vazias"] != vazios:
            problemas.append(
                f"{caminho}: {r['nulos']} NULL + {r['strings_vazias']} '' no raw, "
                f"{vazios} vazios no CSV"
            )
    extras = set(no_raw) - set(medicoes.esperado)
    if extras:
        problemas.append(f"arquivos no raw que não vieram desta execução: {sorted(extras)}")
    nulos = sum(r["nulos"] for r in no_raw.values())
    vazias = sum(r["strings_vazias"] for r in no_raw.values())
    log.info("validação: valores vazios no raw = %d NULL e %d strings vazias", nulos, vazias)
    return problemas


def medir_consulta_tipica(config: Config) -> dict[str, object]:
    bq_cli = gcp.cliente_bigquery(config)
    sql = CONSULTA_TIPICA.format(tabela=config.tabela(DATASET_RAW, NOME_TABELA))
    estimativa = gcp.executar_consulta(bq_cli, sql, dry_run=True)
    real = gcp.executar_consulta(bq_cli, sql, usar_cache=False)  # sem cache: mede de verdade
    return {
        "bytes_estimados": estimativa.bytes_processados,
        "bytes_processados": real.bytes_processados,
        "bytes_faturados": real.bytes_faturados,
        "cache": real.cache,
        "horas": len(real.linhas),
    }


def imprimir_resumo(medicoes: Medicoes, anos: list[int], consulta: dict | None) -> None:
    mb = medicoes.bytes_baixados / 1e6
    print("\n=== Medições da carga full do ONS (para docs/metricas.md) ===")
    print(f"arquivos: {medicoes.arquivos} (anos {anos[0]} a {anos[-1]})")
    print(f"volume baixado: {mb:.1f} MB")
    print(f"linhas nos CSVs: {medicoes.linhas_csv:,}")
    print(f"linhas carregadas: {medicoes.linhas_carregadas:,}")
    print(
        f"tempo total da carga: {medicoes.t_total:.1f} s "
        f"(download {medicoes.t_download:.1f} s, GCS {medicoes.t_gcs:.1f} s, "
        f"BigQuery {medicoes.t_bigquery:.1f} s)"
    )
    if consulta:
        proc, fat = consulta["bytes_processados"], consulta["bytes_faturados"]
        print("consulta típica (carga média por hora do SE em 2024, tabela sem partição):")
        print(f"  estimativa do dry-run: {consulta['bytes_estimados']:,} bytes")
        print(f"  bytes processados: {proc:,} ({proc / 1e6:.1f} MB)")
        print(f"  bytes faturados: {fat:,} ({fat / 1e6:.1f} MB) | cache: {consulta['cache']}")
        print(f"  linhas devolvidas: {consulta['horas']} (esperado: 24 horas)")


def main(argv: list[str] | None = None) -> int:
    ano_atual = datetime.now(UTC).year
    parser = argparse.ArgumentParser(description="Carga full da curva de carga do ONS")
    parser.add_argument("--ano-inicial", type=int, default=ANO_INICIAL)
    parser.add_argument("--ano-final", type=int, default=ano_atual)
    parser.add_argument(
        "--sem-consulta", action="store_true", help="não valida o raw nem mede a consulta típica"
    )
    args = parser.parse_args(argv)

    config = carregar_config()
    anos = anos_a_carregar(args.ano_inicial, args.ano_final)
    log.info("carga full do ONS: anos %d a %d, bucket %s", anos[0], anos[-1], config.bucket)

    medicoes, _ = carregar_anos(anos, config, ano_atual)
    consulta = None
    if not args.sem_consulta:
        problemas = validar_raw(config, medicoes)
        if problemas:
            for problema in problemas:
                log.error("validação: %s", problema)
            return 1
        log.info("validação do raw: ok (linhas e vazios batem com os CSVs)")
        consulta = medir_consulta_tipica(config)
    imprimir_resumo(medicoes, anos, consulta)
    return 0


if __name__ == "__main__":
    sys.exit(main())
