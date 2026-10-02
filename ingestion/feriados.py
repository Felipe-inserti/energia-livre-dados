"""Tabela de feriados nacionais (raw.feriados) a partir da biblioteca `holidays`.

    uv run python -m ingestion.feriados [--ano-inicial 2000] [--ano-final 2030]

Não há arquivo-fonte nem bronze: a "fonte" é a biblioteca, e o resultado depende da versão dela
(por exemplo, o Dia da Consciência Negra é feriado nacional só a partir de 2024). A versão fica
travada no uv.lock e é registrada no log. Só feriados nacionais (os estaduais e municipais não
são tratados, ver docs/premissas.md).

Duas coisas que o raw guarda como vieram e o staging trata:
- datas com mais de um feriado vêm numa linha só, com os nomes separados por "; "
  (ex.: 2000-04-21 = "Sexta-feira Santa; Tiradentes");
- `data` é texto ISO (AAAA-MM-DD), como as demais colunas do raw.

Carga full: um job que substitui a tabela inteira (TRUNCATE).
"""

import argparse
import csv
import io
import sys
import time
from datetime import UTC, datetime

import holidays

from ingestion.common import gcp
from ingestion.common.config import DATASET_RAW, Config, carregar_config
from ingestion.common.logs import obter_logger
from ingestion.common.raw import Carregador, Medicoes

log = obter_logger("ingestion.feriados")

ANO_INICIAL = 2000
ANO_FINAL = 2030
NOME_TABELA = "feriados"
COLUNAS = ["data", "nome"]
TIPOS_EXTRAS = {"_carregado_em": "TIMESTAMP"}

CONSULTA_VALIDACAO = """
SELECT COUNT(*) AS linhas,
       COUNT(DISTINCT `data`) AS datas,
       COUNTIF(`data` IS NULL OR nome IS NULL) AS nulos
FROM `{tabela}`
"""


def listar_feriados(ano_inicial: int, ano_final: int) -> list[tuple[str, str]]:
    """(data ISO, nome) dos feriados nacionais do Brasil, em ordem de data."""
    if ano_final < ano_inicial:
        raise ValueError(f"ano_final ({ano_final}) menor que ano_inicial ({ano_inicial})")
    brasil = holidays.Brazil(years=range(ano_inicial, ano_final + 1))
    return [(data.isoformat(), nome) for data, nome in sorted(brasil.items())]


def montar_csv(feriados: list[tuple[str, str]], carregado_em: str) -> bytes:
    """CSV (vírgula, com cabeçalho) com `data`, `nome` e `_carregado_em`."""
    saida = io.StringIO()
    escritor = csv.writer(saida, lineterminator="\n")
    escritor.writerow([*COLUNAS, "_carregado_em"])
    for data, nome in feriados:
        escritor.writerow([data, nome, carregado_em])
    return saida.getvalue().encode("utf-8")


def carregar(feriados: list[tuple[str, str]], config: Config) -> Medicoes:
    medicoes = Medicoes()
    carregador = Carregador(
        gcp.cliente_bigquery(config),
        config.tabela(DATASET_RAW, NOME_TABELA),
        gcp.montar_esquema(COLUNAS, TIPOS_EXTRAS),
        medicoes,
    )
    carregado_em = datetime.now(UTC).isoformat(timespec="seconds")
    conteudo = montar_csv(feriados, carregado_em)
    carregador.carregar(conteudo, len(feriados), NOME_TABELA)
    medicoes.registrar_arquivo(NOME_TABELA, len(conteudo), len(feriados))
    return medicoes


def validar(config: Config, esperadas: int) -> list[str]:
    """Confere a contagem de linhas, a unicidade das datas e a ausência de nulos."""
    resultado = gcp.executar_consulta(
        gcp.cliente_bigquery(config),
        CONSULTA_VALIDACAO.format(tabela=config.tabela(DATASET_RAW, NOME_TABELA)),
    )
    r = resultado.linhas[0]
    problemas = []
    if r["linhas"] != esperadas:
        problemas.append(f"{r['linhas']} linhas no raw, {esperadas} esperadas")
    if r["datas"] != r["linhas"]:
        problemas.append(f"{r['linhas']} linhas mas {r['datas']} datas distintas")
    if r["nulos"]:
        problemas.append(f"{r['nulos']} linhas com nulo")
    return problemas


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Carga dos feriados nacionais no raw")
    parser.add_argument("--ano-inicial", type=int, default=ANO_INICIAL)
    parser.add_argument("--ano-final", type=int, default=ANO_FINAL)
    args = parser.parse_args(argv)

    feriados = listar_feriados(args.ano_inicial, args.ano_final)
    config = carregar_config()
    log.info(
        "feriados %d a %d: %d linhas (biblioteca holidays %s)",
        args.ano_inicial,
        args.ano_final,
        len(feriados),
        holidays.__version__,
    )
    t0 = time.perf_counter()
    medicoes = carregar(feriados, config)
    problemas = validar(config, len(feriados))
    if problemas:
        for problema in problemas:
            log.error("validação: %s", problema)
        return 1
    juntos = sum(1 for _, nome in feriados if "; " in nome)
    log.info("validação do raw: ok (%d datas com mais de um feriado numa linha)", juntos)
    print("\n=== Carga dos feriados ===")
    print(f"linhas: {medicoes.linhas_carregadas} ({args.ano_inicial} a {args.ano_final})")
    print(f"biblioteca holidays: {holidays.__version__}")
    print(f"tempo: {time.perf_counter() - t0:.1f} s (BigQuery {medicoes.t_bigquery:.1f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
