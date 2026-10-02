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
from datetime import UTC, datetime

from ingestion.common import gcp
from ingestion.common.config import DATASET_RAW, Config, carregar_config
from ingestion.common.csv_utils import transformar_csv
from ingestion.common.download import ArquivoNaoEncontrado, baixar_bytes
from ingestion.common.logs import obter_logger
from ingestion.common.raw import (
    Carregador,
    ConjuntoValidacao,
    Medicoes,
    imprimir_resumo,
    medir_consulta_tipica,
    validar_raw,
)

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


def carregar_anos(anos: list[int], config: Config, ano_atual: int) -> Medicoes:
    storage_cli = gcp.cliente_storage(config)
    medicoes = Medicoes()
    carregador = Carregador(
        gcp.cliente_bigquery(config),
        config.tabela(DATASET_RAW, NOME_TABELA),
        gcp.montar_esquema(COLUNAS_ESPERADAS, TIPOS_EXTRAS),
        medicoes,
    )
    carregado_em = datetime.now(UTC).isoformat(timespec="seconds")

    for ano in anos:
        t0 = time.perf_counter()
        try:
            original = baixar_bytes(montar_url(ano))
        except ArquivoNaoEncontrado:
            if ano == ano_atual:  # o arquivo do ano corrente pode ainda não existir (janeiro)
                log.warning("%d: arquivo ainda não publicado (404); ano ignorado", ano)
                continue
            raise
        medicoes.t_origem += time.perf_counter() - t0

        # bronze: os bytes originais, sem alteração
        t0 = time.perf_counter()
        caminho = caminho_gcs(ano)
        origem = gcp.enviar_para_gcs(storage_cli, config.bucket, caminho, original)
        medicoes.t_gcs += time.perf_counter() - t0

        # raw: colunas padronizadas + colunas de controle
        extras = {"_arquivo_origem": caminho, "_carregado_em": carregado_em}
        csv_raw = transformar_csv(original, extras)
        validar_colunas(csv_raw.colunas)
        linhas = carregador.carregar(csv_raw.conteudo, csv_raw.linhas, str(ano))

        medicoes.registrar_arquivo(nome_arquivo(ano), len(original), linhas)
        medicoes.registrar_esperado(
            NOME_TABELA, (caminho,), csv_raw.linhas, csv_raw.vazios[COLUNA_VALOR]
        )
        log.info("%d: %.2f MB baixados, %d linhas -> %s", ano, len(original) / 1e6, linhas, origem)
    return medicoes


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

    medicoes = carregar_anos(anos, config, ano_atual)
    consulta = None
    if not args.sem_consulta:
        problemas = validar_raw(config, medicoes, [ConjuntoValidacao(NOME_TABELA, COLUNA_VALOR)])
        if problemas:
            for problema in problemas:
                log.error("validação: %s", problema)
            return 1
        log.info("validação do raw: ok (linhas e vazios batem com os CSVs)")
        sql = CONSULTA_TIPICA.format(tabela=config.tabela(DATASET_RAW, NOME_TABELA))
        consulta = medir_consulta_tipica(config, sql)
    imprimir_resumo(
        "da carga full do ONS",
        medicoes,
        consulta,
        rotulo_volume="volume baixado",
        rotulo_origem="download",
        descricao_consulta="carga média por hora do SE em 2024",
        detalhe_arquivos=f" (anos {anos[0]} a {anos[-1]})",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
