"""Mede a consulta típica de cada fonte no raw (STRING) e no staging (tipado, sem partição).

    uv run python -m scripts.medir_consultas [--fonte ons|ccee|inmet|todas]

Pré-requisito: o `dbt run` do staging já ter criado as tabelas. Para cada fonte roda a MESMA
pergunta nas duas tabelas, com teto de bytes, dry-run e cache desligado, e compara os resultados:
se divergirem, o staging está errado (isso também testa a conversão de fuso). Na tarefa 2.6 o
script ganha o terceiro ponto (tabela particionada e clusterizada), para separar o efeito da
tipagem do efeito da partição (ver docs/decisoes.md).
"""

import argparse
import sys
from dataclasses import dataclass

from google.api_core.exceptions import NotFound

from ingestion import ccee, inmet, ons
from ingestion.common import gcp
from ingestion.common.config import DATASET_RAW, DATASET_STAGING, Config, carregar_config

TOLERANCIA = 1e-6  # as médias do raw (FLOAT64/NUMERIC via CAST) e do staging podem diferir ao somar


@dataclass(frozen=True)
class Par:
    nome: str
    descricao: str
    tabela_raw: str
    tabela_staging: str
    sql_raw: str  # com {tabela}
    sql_staging: str  # com {tabela}


# ONS: a hora do dia é a LOCAL (como no raw), e o ano 2024 é o ano local (mesmas linhas do raw).
SQL_STAGING_ONS = """
SELECT EXTRACT(HOUR FROM instante_utc AT TIME ZONE 'America/Sao_Paulo') AS hora,
       AVG(carga_mwmed) AS carga_media
FROM `{tabela}`
WHERE id_subsistema = 'SE'
  AND instante_utc >= TIMESTAMP('2024-01-01', 'America/Sao_Paulo')
  AND instante_utc < TIMESTAMP('2025-01-01', 'America/Sao_Paulo')
GROUP BY hora
ORDER BY hora
"""

SQL_STAGING_CCEE = """
SELECT EXTRACT(HOUR FROM instante_utc AT TIME ZONE 'America/Sao_Paulo') AS hora,
       AVG(pld_rs_mwh) AS pld_medio
FROM `{tabela}`
WHERE submercado = 'SUDESTE'
  AND instante_utc >= TIMESTAMP('2024-01-01', 'America/Sao_Paulo')
  AND instante_utc < TIMESTAMP('2025-01-01', 'America/Sao_Paulo')
GROUP BY hora
ORDER BY hora
"""

# INMET: já é UTC, então a hora e o ano são UTC nas duas tabelas.
SQL_STAGING_INMET = """
SELECT EXTRACT(HOUR FROM instante_utc) AS hora_utc,
       AVG(temperatura_c) AS temp_media
FROM `{tabela}`
WHERE uf = 'SP'
  AND instante_utc >= TIMESTAMP '2024-01-01 00:00:00+00'
  AND instante_utc < TIMESTAMP '2025-01-01 00:00:00+00'
GROUP BY hora_utc
ORDER BY hora_utc
"""

PARES = {
    "ons": Par(
        "ONS",
        "carga média por hora do SE em 2024",
        ons.NOME_TABELA,
        "stg_ons__curva_carga",
        ons.CONSULTA_TIPICA,
        SQL_STAGING_ONS,
    ),
    "ccee": Par(
        "CCEE",
        "PLD médio por hora do SUDESTE em 2024",
        ccee.PLD_HORARIO.tabela,
        "stg_ccee__pld_horario",
        ccee.CONSULTA_TIPICA,
        SQL_STAGING_CCEE,
    ),
    "inmet": Par(
        "INMET",
        "temperatura média por hora (UTC) em SP em 2024",
        inmet.NOME_TABELA,
        "stg_inmet__estacoes_horario",
        inmet.CONSULTA_TIPICA,
        SQL_STAGING_INMET,
    ),
}


@dataclass(frozen=True)
class Medida:
    estimado: int
    processado: int
    faturado: int
    pares: list[tuple[int, float]]  # (hora, valor), para comparar os resultados


def como_pares(linhas) -> list[tuple[int, float]]:
    """(hora, valor) de cada linha; aceita Row do BigQuery, dict ou tupla; NUMERIC vira float."""
    pares = []
    for linha in linhas:
        valores = list(linha.values()) if hasattr(linha, "values") else list(linha)
        pares.append((int(valores[0]), float(valores[1])))
    return pares


def resultados_iguais(a: list[tuple[int, float]], b: list[tuple[int, float]]) -> bool:
    """Mesmas horas e valores iguais dentro da tolerância (absoluta ou relativa)."""
    if [h for h, _ in a] != [h for h, _ in b]:
        return False
    return all(
        abs(x - y) <= max(TOLERANCIA, 1e-9 * abs(x)) for (_, x), (_, y) in zip(a, b, strict=True)
    )


def variacao_percentual(antes: int, depois: int) -> float:
    return (depois / antes - 1) * 100 if antes else 0.0


def medir(bq, sql: str) -> Medida:
    estimativa = gcp.executar_consulta(bq, sql, dry_run=True)
    real = gcp.executar_consulta(bq, sql, usar_cache=False)  # sem cache: mede de verdade
    return Medida(
        estimativa.bytes_processados,
        real.bytes_processados,
        real.bytes_faturados,
        como_pares(real.linhas),
    )


def medir_par(bq, config: Config, par: Par) -> tuple[Medida, Medida]:
    raw = config.tabela(DATASET_RAW, par.tabela_raw)
    staging = config.tabela(DATASET_STAGING, par.tabela_staging)
    return medir(bq, par.sql_raw.format(tabela=raw)), medir(
        bq, par.sql_staging.format(tabela=staging)
    )


def imprimir_par(par: Par, raw: Medida, staging: Medida) -> bool:
    iguais = resultados_iguais(raw.pares, staging.pares)
    print(f"\n{par.nome}: {par.descricao}")
    for rotulo, m in (("raw (STRING)", raw), ("staging (tipado)", staging)):
        print(
            f"  {rotulo:17s} estimativa {m.estimado:>12,} | "
            f"processados {m.processado:>12,} ({m.processado / 1e6:6.1f} MB) | "
            f"faturados {m.faturado:>12,} ({m.faturado / 1e6:6.1f} MB)"
        )
    print(
        f"  efeito da tipagem: {variacao_percentual(raw.processado, staging.processado):+.1f}% "
        f"nos bytes processados, {variacao_percentual(raw.faturado, staging.faturado):+.1f}% "
        f"nos faturados | resultados iguais: {'sim' if iguais else 'NÃO'} ({len(raw.pares)} linhas)"
    )
    if staging.faturado == raw.faturado == 10 * 1024 * 1024:
        print("  (os dois estão no piso de 10 MiB faturado: compare os bytes processados)")
    return iguais


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Consulta típica: raw contra staging")
    parser.add_argument("--fonte", choices=[*PARES, "todas"], default="todas")
    args = parser.parse_args(argv)

    config = carregar_config()
    bq = gcp.cliente_bigquery(config)
    escolhidas = list(PARES.values()) if args.fonte == "todas" else [PARES[args.fonte]]
    print("=== Consulta típica: raw (STRING) contra staging (tipado, sem partição) ===")
    tudo_igual = True
    for par in escolhidas:
        try:
            raw, staging = medir_par(bq, config, par)
        except NotFound as erro:
            print(f"\n{par.nome}: tabela não encontrada ({erro.message}). Rode o dbt run antes.")
            return 2
        tudo_igual &= imprimir_par(par, raw, staging)
    if not tudo_igual:
        print("\nATENÇÃO: o staging devolveu resultado diferente do raw.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
