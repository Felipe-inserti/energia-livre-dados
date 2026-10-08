"""Apaga a previsão de PRODUÇÃO da última origem em `marts.fct_previsao_carga` (grava na nuvem).

    uv run --env-file .env python -m scripts.apagar_ultima_previsao --confirmo

Serve só para o teste opcional `passo_sprint5_c.sh dag-gerar`: com a origem apagada, a próxima
execução da DAG tem de considerar que fechou um mês novo e regerar as 12 linhas. Recusa rodar sem
`--confirmo`, mexe só nas linhas de produção da versão atual do modelo e não toca nos erros.
"""

import argparse
import sys

from ingestion.common import gcp
from ingestion.common.config import carregar_config
from ml.registro import MODELO_VERSAO

TABELA = "marts.fct_previsao_carga"


def sql_apagar() -> str:
    filtro = f"modelo_versao = '{MODELO_VERSAO}' AND tipo = 'producao'"
    return (
        f"DELETE FROM `{TABELA}` WHERE {filtro} "
        f"AND origem = (SELECT MAX(origem) FROM `{TABELA}` WHERE {filtro})"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--confirmo", action="store_true", help="obrigatório: é uma escrita")
    args = ap.parse_args(argv)
    if not args.confirmo:
        print(
            "RECUSADO: passe --confirmo (apaga a previsão da última origem de produção)",
            file=sys.stderr,
        )
        return 2
    cliente = gcp.cliente_bigquery(carregar_config())
    gcp.executar_consulta(cliente, sql_apagar(), max_bytes_faturados=100 * 1024 * 1024)
    print("previsão da última origem de produção apagada")
    return 0


if __name__ == "__main__":
    sys.exit(main())
