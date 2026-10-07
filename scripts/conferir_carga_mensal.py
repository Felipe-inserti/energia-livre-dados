"""Reconcilia o `fct_carga_mensal` (e o seed) com os números da investigação da Sprint 4, Parte B.

    uv run --env-file .env python -m scripts.conferir_carga_mensal

Só LEITURA, com teto de bytes. Imprime: o fator r, o ajuste de tipo III por ano, o ajuste de MMGD
por ano (com r e com r = 1), a variação anual do SE antes e depois do ajuste ao redor das duas
quebras e o tamanho do salto da variação anual por submercado. Se o ajuste funciona, o salto da
série AJUSTADA na quebra é bem menor que o da ORIGINAL.
"""

from ingestion.common import gcp
from ingestion.common.config import carregar_config

TETO = 50 * 1024 * 1024

CONSULTAS = {
    "r (fração da MMGD da API que a curva traz; 12 meses após 2023-05)": """
        SELECT codigo_submercado, ROUND(ANY_VALUE(ajuste_mmgd_fator_r), 3) AS r
        FROM `marts.fct_carga_mensal` GROUP BY 1 ORDER BY 1""",
    "ajuste de tipo III (MWmed): média por ano, meses 'medido' (2018-01 a 2021-02)": """
        SELECT codigo_submercado, EXTRACT(YEAR FROM mes) AS ano, COUNT(*) AS meses,
               ROUND(AVG(ajuste_tipo3_mwmed), 0) AS tipo3_mwmed,
               ROUND(AVG(ajuste_tipo3_mwmed / carga_original_mwmed) * 100, 2) AS pct_da_carga
        FROM `marts.fct_carga_mensal` WHERE ajuste_tipo3_status = 'medido'
        GROUP BY 1, 2 ORDER BY 1, 2""",
    "ajuste de MMGD (MWmed): média por ano, com r e com r = 1 (SE)": """
        SELECT EXTRACT(YEAR FROM mes) AS ano, COUNT(*) AS meses,
               ROUND(AVG(ajuste_mmgd_mwmed), 0) AS mmgd_r,
               ROUND(AVG(carga_ajustada_r1_mwmed - carga_ajustada_mwmed), 0) AS dif_r1_menos_r
        FROM `marts.fct_carga_mensal`
        WHERE codigo_submercado = 'SE' AND ajuste_mmgd_status IN ('medido', 'medido_parcial')
        GROUP BY 1 ORDER BY 1""",
    "variação anual do SE (%), original x ajustada, ao redor das quebras": """
        WITH v AS (
          SELECT mes, carga_original_mwmed AS o, carga_ajustada_mwmed AS a,
                 carga_ajustada_r1_mwmed AS a1,
                 LAG(carga_original_mwmed, 12) OVER (ORDER BY mes) AS o12,
                 LAG(carga_ajustada_mwmed, 12) OVER (ORDER BY mes) AS a12,
                 LAG(carga_ajustada_r1_mwmed, 12) OVER (ORDER BY mes) AS a112
          FROM `marts.fct_carga_mensal` WHERE codigo_submercado = 'SE')
        SELECT mes, ROUND((o / o12 - 1) * 100, 1) AS orig_pct,
               ROUND((a / a12 - 1) * 100, 1) AS ajust_pct,
               ROUND((a1 / a112 - 1) * 100, 1) AS ajust_r1_pct
        FROM v
        WHERE mes BETWEEN '2020-11-01' AND '2021-06-01'
           OR mes BETWEEN '2022-11-01' AND '2023-09-01'
        ORDER BY mes""",
    "salto da variação anual na quebra (p.p.): mai/23 - abr/23 e mar/21 - fev/21": """
        WITH v AS (
          SELECT codigo_submercado, mes,
                 carga_original_mwmed / LAG(carga_original_mwmed, 12) OVER w - 1 AS yo,
                 carga_ajustada_mwmed / LAG(carga_ajustada_mwmed, 12) OVER w - 1 AS ya
          FROM `marts.fct_carga_mensal`
          WINDOW w AS (PARTITION BY codigo_submercado ORDER BY mes))
        SELECT codigo_submercado,
               ROUND((MAX(IF(mes = '2023-05-01', yo, NULL))
                      - MAX(IF(mes = '2023-04-01', yo, NULL))) * 100, 1) AS salto_2023_original,
               ROUND((MAX(IF(mes = '2023-05-01', ya, NULL))
                      - MAX(IF(mes = '2023-04-01', ya, NULL))) * 100, 1) AS salto_2023_ajustada,
               ROUND((MAX(IF(mes = '2021-03-01', yo, NULL))
                      - MAX(IF(mes = '2021-02-01', yo, NULL))) * 100, 1) AS salto_2021_original,
               ROUND((MAX(IF(mes = '2021-03-01', ya, NULL))
                      - MAX(IF(mes = '2021-02-01', ya, NULL))) * 100, 1) AS salto_2021_ajustada
        FROM v GROUP BY 1 ORDER BY 1""",
    "meses incompletos ou com horas nulas": """
        SELECT codigo_submercado, mes, horas_esperadas, horas_com_linha, horas_validas,
               mes_incompleto
        FROM `marts.fct_carga_mensal`
        WHERE mes_incompleto OR horas_validas < horas_com_linha ORDER BY 1, 2""",
    "cobertura do mart": """
        SELECT codigo_submercado, MIN(mes) AS primeiro, MAX(mes) AS ultimo, COUNT(*) AS meses,
               COUNTIF(carga_ajustada_mwmed IS NOT NULL) AS meses_ajustados,
               MIN(IF(carga_ajustada_mwmed IS NOT NULL, mes, NULL)) AS primeiro_ajustado
        FROM `marts.fct_carga_mensal` GROUP BY 1 ORDER BY 1""",
}


def imprimir(titulo: str, linhas: list[dict]) -> None:
    print(f"\n== {titulo}")
    if not linhas:
        print("(sem linhas)")
        return
    colunas = list(linhas[0])
    celulas = [[str(linha[c]) for c in colunas] for linha in linhas]
    larguras = [max(len(c), *(len(r[i]) for r in celulas)) for i, c in enumerate(colunas)]
    print("  ".join(c.rjust(w) for c, w in zip(colunas, larguras, strict=True)))
    for r in celulas:
        print("  ".join(v.rjust(w) for v, w in zip(r, larguras, strict=True)))


def main() -> int:
    cliente = gcp.cliente_bigquery(carregar_config())
    total = 0
    for titulo, sql in CONSULTAS.items():
        res = gcp.executar_consulta(cliente, sql, max_bytes_faturados=TETO)
        total += res.bytes_processados or 0
        imprimir(titulo, [dict(linha.items()) for linha in res.linhas])
    print(f"\nbytes processados nas {len(CONSULTAS)} consultas: {total:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
