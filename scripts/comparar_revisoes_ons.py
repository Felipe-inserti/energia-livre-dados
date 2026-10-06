"""Mede as revisões do ONS SEM escrever na nuvem: baixa cada ano e compara com o bronze atual.

    uv run --env-file .env python -m scripts.comparar_revisoes_ons [--ano-inicial A] [--ano-final B]

Só lê (download do ONS e leitura do objeto no GCS). Cada ano vira uma linha em
`data/logs/revisoes_ons.jsonl` (origem `comparacao`) e uma linha no terminal. Serve à primeira
medição de revisões e a conferir o bronze depois: se o resultado for "idêntico" em todos os anos,
a próxima carga do ONS não vai gravar nada.
"""

import argparse
import sys
from datetime import UTC, datetime

from ingestion import ons, revisoes
from ingestion.common import gcp
from ingestion.common.config import carregar_config
from ingestion.common.download import ArquivoNaoEncontrado, baixar_bytes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compara o ONS de hoje com o bronze (só leitura)")
    parser.add_argument("--ano-inicial", type=int, default=ons.ANO_INICIAL)
    parser.add_argument("--ano-final", type=int, default=datetime.now(UTC).year)
    args = parser.parse_args(argv)

    config = carregar_config()
    cliente = gcp.cliente_storage(config)
    mudaram = 0
    for ano in ons.anos_a_carregar(args.ano_inicial, args.ano_final):
        try:
            novo = baixar_bytes(ons.montar_url(ano))
        except ArquivoNaoEncontrado:
            print(f"{ano}: ainda não publicado (404)")
            continue
        bronze = gcp.buscar_objeto(cliente, config.bucket, ons.caminho_gcs(ano))
        if bronze is None:
            print(f"{ano}: sem objeto no bronze")
            continue
        registro = revisoes.comparar_csv_ons(bronze.download_as_bytes(), novo, ano)
        revisoes.registrar(registro, origem="comparacao")
        mudaram += not registro["identico"]
        print(revisoes.resumir(registro))
    print(f"\nanos com revisão: {mudaram}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
