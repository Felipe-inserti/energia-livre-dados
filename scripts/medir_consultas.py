"""Mede a consulta típica de cada fonte em três pontos: raw (STRING), staging (tipado, sem partição)
e fato (particionada por mês e clusterizada).

    uv run python -m scripts.medir_consultas [--fonte ons|ccee|inmet|todas] [--isolar-cluster]

Pré-requisito: o `dbt run` do staging e dos marts já ter criado as tabelas. Para cada fonte roda a
MESMA pergunta nas três tabelas, com teto de bytes, dry-run e cache desligado, e compara os
resultados: se divergirem, algum modelo está errado (isso também testa a conversão de fuso).

A MÉTRICA DE COMPARAÇÃO É BYTES PROCESSADOS. O BigQuery fatura no mínimo 10 MiB por consulta, e com
este volume (18 a 366 MB por tabela) o faturado fica no piso depois da partição, escondendo o ganho.

Com `--isolar-cluster` roda também um experimento que separa o efeito da partição do efeito da
clusterização: cria cópias temporárias da fato (sem nada, só partição, só cluster), mede a mesma
consulta e apaga as cópias ao final.
"""

import argparse
import sys
from dataclasses import dataclass

from google.api_core.exceptions import NotFound

from ingestion import ccee, inmet, ons
from ingestion.common import gcp
from ingestion.common.config import DATASET_RAW, DATASET_STAGING, Config, carregar_config

DATASET_MARTS = "marts"
TOLERANCIA = 1e-6  # as médias do raw (FLOAT64/NUMERIC via CAST) e do staging podem diferir ao somar
PISO_FATURADO = 10 * 1024 * 1024  # o BigQuery fatura no mínimo 10 MiB por consulta


@dataclass(frozen=True)
class Par:
    nome: str
    descricao: str
    tabela_raw: str
    tabela_staging: str
    tabela_fato: str
    colunas_cluster: tuple[str, ...]  # clusterização do fato (para o experimento de isolamento)
    sql_raw: str  # com {tabela}
    sql_staging: str  # com {tabela}
    sql_fato: str  # com {tabela}


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

# O fato troca o nome das colunas (código do submercado) e tem a partição mensal em instante_utc,
# que o filtro de intervalo poda (o BigQuery avalia o TIMESTAMP(..., 'America/Sao_Paulo') antes).
SQL_FATO_ONS = SQL_STAGING_ONS.replace("id_subsistema", "codigo_submercado")

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

SQL_FATO_CCEE = SQL_STAGING_CCEE.replace("submercado = 'SUDESTE'", "codigo_submercado = 'SE'")

# INMET: já é UTC, então a hora e o ano são UTC nas três tabelas.
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

SQL_FATO_INMET = SQL_STAGING_INMET  # o fato tem as mesmas colunas (uf, instante_utc, temperatura_c)

PARES = {
    "ons": Par(
        "ONS",
        "carga média por hora do SE em 2024",
        ons.NOME_TABELA,
        "stg_ons__curva_carga",
        "fct_carga_horaria",
        ("codigo_submercado",),
        ons.CONSULTA_TIPICA,
        SQL_STAGING_ONS,
        SQL_FATO_ONS,
    ),
    "ccee": Par(
        "CCEE",
        "PLD médio por hora do SUDESTE em 2024",
        ccee.PLD_HORARIO.tabela,
        "stg_ccee__pld_horario",
        "fct_pld_horario",
        ("codigo_submercado",),
        ccee.CONSULTA_TIPICA,
        SQL_STAGING_CCEE,
        SQL_FATO_CCEE,
    ),
    "inmet": Par(
        "INMET",
        "temperatura média por hora (UTC) em SP em 2024",
        inmet.NOME_TABELA,
        "stg_inmet__estacoes_horario",
        "fct_clima_horario",
        ("uf", "estacao_codigo"),
        inmet.CONSULTA_TIPICA,
        SQL_STAGING_INMET,
        SQL_FATO_INMET,
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


def medir_par(bq, config: Config, par: Par) -> tuple[Medida, Medida, Medida]:
    raw = config.tabela(DATASET_RAW, par.tabela_raw)
    staging = config.tabela(DATASET_STAGING, par.tabela_staging)
    fato = config.tabela(DATASET_MARTS, par.tabela_fato)
    return (
        medir(bq, par.sql_raw.format(tabela=raw)),
        medir(bq, par.sql_staging.format(tabela=staging)),
        medir(bq, par.sql_fato.format(tabela=fato)),
    )


def linha_medida(rotulo: str, m: Medida) -> str:
    return (
        f"  {rotulo:28s} estimativa {m.estimado:>12,} | "
        f"processados {m.processado:>12,} ({m.processado / 1e6:6.2f} MB) | "
        f"faturados {m.faturado:>12,} ({m.faturado / 1e6:6.1f} MB)"
    )


def imprimir_par(par: Par, raw: Medida, staging: Medida, fato: Medida) -> bool:
    iguais = resultados_iguais(raw.pares, staging.pares) and resultados_iguais(
        staging.pares, fato.pares
    )
    print(f"\n{par.nome}: {par.descricao}")
    print(linha_medida("raw (STRING)", raw))
    print(linha_medida("staging (tipado)", staging))
    print(linha_medida("fato (particionada)", fato))
    print(
        "  efeito nos bytes PROCESSADOS: "
        f"tipagem {variacao_percentual(raw.processado, staging.processado):+.1f}% | "
        f"partição e cluster {variacao_percentual(staging.processado, fato.processado):+.1f}% "
        f"(contra o tipado) | total {variacao_percentual(raw.processado, fato.processado):+.1f}% "
        "(contra o raw)"
    )
    print(
        "  efeito nos bytes FATURADOS:   "
        f"tipagem {variacao_percentual(raw.faturado, staging.faturado):+.1f}% | "
        f"partição e cluster {variacao_percentual(staging.faturado, fato.faturado):+.1f}% | "
        f"total {variacao_percentual(raw.faturado, fato.faturado):+.1f}%"
    )
    print(
        "  resultados iguais nos três pontos: "
        f"{'sim' if iguais else 'NÃO'} ({len(raw.pares)} linhas)"
    )
    if fato.faturado == PISO_FATURADO:
        print(
            "  (o fato está no piso de 10 MiB faturado: a métrica de comparação são os bytes "
            "processados)"
        )
    return iguais


def info_fato(bq, config: Config, par: Par) -> str:
    """Partição, cluster e número de partições REAIS da tabela do fato (não o que o dbt pediu)."""
    tabela = config.tabela(DATASET_MARTS, par.tabela_fato)
    meta = bq.get_table(tabela)
    particao = meta.time_partitioning
    resultado = gcp.executar_consulta(
        bq,
        f"SELECT COUNT(*) AS n "
        f"FROM `{config.projeto}.{DATASET_MARTS}.INFORMATION_SCHEMA.PARTITIONS` "
        f"WHERE table_name = '{par.tabela_fato}'",
    )
    n = resultado.linhas[0]["n"]
    descricao = f"{particao.type_} em {particao.field}" if particao else "sem partição"
    return (
        f"  tabela {par.tabela_fato}: partição {descricao}; cluster {meta.clustering_fields}; "
        f"{n} partições; {meta.num_rows:,} linhas"
    )


# ------------------------------------------------------------------- isolamento do cluster

VARIANTES = {
    "sem_nada": "sem partição e sem cluster",
    "so_particao": "só partição (mensal)",
    "so_cluster": "só cluster",
}


def sql_variante(variante: str, origem: str, destino: str, cluster: tuple[str, ...]) -> str:
    """CREATE TABLE AS SELECT da cópia temporária do fato, com a partição e/ou o cluster pedidos."""
    clausulas = {
        "sem_nada": "",
        "so_particao": "PARTITION BY TIMESTAMP_TRUNC(instante_utc, MONTH)",
        "so_cluster": f"CLUSTER BY {', '.join(cluster)}",
    }[variante]
    return f"CREATE OR REPLACE TABLE `{destino}` {clausulas} AS SELECT * FROM `{origem}`"


def nome_temporario(par: Par, variante: str) -> str:
    return f"tmp_exp_{par.tabela_fato}_{variante}"


def isolar_cluster(bq, config: Config, par: Par, fato: Medida) -> dict[str, Medida]:
    """Mede a mesma consulta em cópias do fato sem partição/cluster, só partição e só cluster.

    As cópias são temporárias (dataset `staging`) e SEMPRE apagadas, mesmo se algo falhar.
    """
    origem = config.tabela(DATASET_MARTS, par.tabela_fato)
    criadas = []
    medidas: dict[str, Medida] = {}
    try:
        for variante in VARIANTES:
            destino = config.tabela(DATASET_STAGING, nome_temporario(par, variante))
            criadas.append(destino)
            gcp.executar_consulta(
                bq,
                sql_variante(variante, origem, destino, par.colunas_cluster),
                max_bytes_faturados=1024**3,
            )
            medidas[variante] = medir(bq, par.sql_fato.format(tabela=destino))
    finally:
        for destino in criadas:
            bq.delete_table(destino, not_found_ok=True)
    medidas["particao_e_cluster"] = fato
    return medidas


def imprimir_isolamento(par: Par, medidas: dict[str, Medida]) -> bool:
    rotulos = {**VARIANTES, "particao_e_cluster": "partição e cluster (o fato)"}
    print(f"\n{par.nome}: experimento de isolamento (cópias temporárias do fato, já apagadas)")
    for chave, rotulo in rotulos.items():
        print(linha_medida(rotulo, medidas[chave]))
    base = medidas["sem_nada"].processado
    print(
        "  efeito nos bytes PROCESSADOS, contra a cópia sem nada: "
        f"só partição {variacao_percentual(base, medidas['so_particao'].processado):+.1f}% | "
        f"só cluster {variacao_percentual(base, medidas['so_cluster'].processado):+.1f}% | "
        f"os dois {variacao_percentual(base, medidas['particao_e_cluster'].processado):+.1f}%"
    )
    so_particao = medidas["so_particao"].processado
    com_cluster = medidas["particao_e_cluster"].processado
    print(
        "  efeito do cluster por cima da partição: "
        f"{variacao_percentual(so_particao, com_cluster):+.1f}%"
    )
    iguais = all(resultados_iguais(medidas["sem_nada"].pares, m.pares) for m in medidas.values())
    print(f"  resultados iguais nas quatro tabelas: {'sim' if iguais else 'NÃO'}")
    return iguais


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Consulta típica: raw, staging e fato")
    parser.add_argument("--fonte", choices=[*PARES, "todas"], default="todas")
    parser.add_argument(
        "--isolar-cluster",
        action="store_true",
        help="experimento: separa o efeito da partição do efeito do cluster (cópias temporárias)",
    )
    args = parser.parse_args(argv)

    config = carregar_config()
    bq = gcp.cliente_bigquery(config)
    escolhidas = list(PARES.values()) if args.fonte == "todas" else [PARES[args.fonte]]
    print("=== Consulta típica: raw (STRING), staging (tipado) e fato (particionada) ===")
    print("Métrica de comparação: bytes PROCESSADOS (o faturado fica no piso de 10 MiB).")
    tudo_igual = True
    for par in escolhidas:
        try:
            raw, staging, fato = medir_par(bq, config, par)
        except NotFound as erro:
            print(f"\n{par.nome}: tabela não encontrada ({erro.message}). Rode o dbt run antes.")
            return 2
        tudo_igual &= imprimir_par(par, raw, staging, fato)
        print(info_fato(bq, config, par))
        if args.isolar_cluster:
            tudo_igual &= imprimir_isolamento(par, isolar_cluster(bq, config, par, fato))
    if not tudo_igual:
        print("\nATENÇÃO: algum ponto devolveu resultado diferente.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
