"""Confere `marts.fct_previsao_carga` e `marts.fct_erro_previsao_carga` na nuvem (só leitura).

    uv run --env-file .env python -m scripts.conferir_previsao [--impressao]

Cada checagem imprime PASS ou FAIL e o programa sai com 1 se alguma falhar. `--impressao` só
imprime a impressão digital das duas tabelas (contagem e somas) e sai: serve para provar que
reexecutar a geração não muda nada.
"""

import argparse
import sys

from ingestion.common import gcp
from ingestion.common.config import carregar_config
from ml.registro import MODELO_VERSAO

TETO = 100 * 1024 * 1024
V = f"modelo_versao = '{MODELO_VERSAO}'"
# MAPE do vencedor registrado em docs/metricas.md (3 casas de folga: 0,01 pp)
MAPE_DESENVOLVIMENTO, MAPE_TESTE_FINAL = 2.66, 3.11


def um(gcp_, cliente, sql):
    return gcp_.executar_consulta(cliente, sql, max_bytes_faturados=TETO).linhas[0]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--impressao", action="store_true")
    args = ap.parse_args(argv)
    cliente = gcp.cliente_bigquery(carregar_config())

    if args.impressao:
        sql_prev = """SELECT COUNT(*) n, ROUND(SUM(previsao_mwmed), 1) soma,
            MAX(origem) origem{extra}
            FROM `marts.fct_previsao_carga` WHERE {V}"""
        extra = ", MAX(entrada_hash) entrada_hash, MAX(entrada_ultimo_mwmed) entrada_ultimo"
        try:
            r = um(gcp, cliente, sql_prev.format(extra=extra, V=V))
        except Exception:  # noqa: BLE001 - tabela criada antes da impressão da entrada: sem as colunas
            r = {
                **um(gcp, cliente, sql_prev.format(extra="", V=V)),
                "entrada_hash": None,
                "entrada_ultimo": None,
            }
        e = um(
            gcp,
            cliente,
            f"""SELECT COUNT(*) n, ROUND(SUM(log_razao), 9) soma
            FROM `marts.fct_erro_previsao_carga` WHERE {V}""",
        )
        print(
            f"previsao n={r['n']} soma={r['soma']} origem={r['origem']} "
            f"entrada_hash={r['entrada_hash']} entrada_ultimo={r['entrada_ultimo']} "
            f"| erros n={e['n']} soma={e['soma']}"
        )
        return 0

    falhas = 0

    def checar(nome, ok, detalhe=""):
        nonlocal falhas
        falhas += 0 if ok else 1
        print(
            f"{'PASS' if ok else 'FAIL'}  {nome}{'  -> ' + str(detalhe) if detalhe != '' else ''}"
        )

    q = lambda sql: um(gcp, cliente, sql)  # noqa: E731
    r = q(f"""SELECT COUNT(*) n, COUNT(DISTINCT origem) origens,
        COUNT(DISTINCT CONCAT(modelo_versao, tipo, CAST(origem AS STRING),
            CAST(horizonte AS STRING))) chaves,
        COUNTIF(mes_alvo != DATE_ADD(origem, INTERVAL horizonte MONTH)) alvo_errado,
        COUNTIF(NOT (p025_mwmed < p10_mwmed AND p10_mwmed < p90_mwmed
            AND p90_mwmed < p975_mwmed)) fora_de_ordem,
        COUNTIF(previsao_mwmed <= 0 OR p025_mwmed <= 0) nao_positivos,
        COUNTIF(parametros_hash IS NULL OR codigo_hash IS NULL OR commit IS NULL
            OR gerado_em IS NULL) sem_proveniencia,
        COUNTIF(commit = 'desconhecido') commit_desconhecido,
        COUNT(DISTINCT horizonte) horizontes
        FROM `marts.fct_previsao_carga` WHERE {V}""")
    checar(
        "previsão: 12 linhas por origem",
        r["n"] == 12 * r["origens"] and r["origens"] >= 1,
        f"{r['n']} linhas, {r['origens']} origem(ns)",
    )
    checar("previsão: chave natural única", r["chaves"] == r["n"])
    checar("previsão: horizontes 1..12", r["horizontes"] == 12)
    checar("previsão: mês-alvo = origem + horizonte meses", r["alvo_errado"] == 0)
    checar("previsão: p025 < p10 < p90 < p975", r["fora_de_ordem"] == 0)
    checar("previsão: valores positivos", r["nao_positivos"] == 0)
    checar("previsão: proveniência completa", r["sem_proveniencia"] == 0)
    checar("previsão: commit conhecido", r["commit_desconhecido"] == 0)

    e = q(f"""SELECT COUNT(*) n,
        COUNT(DISTINCT CONCAT(modelo_versao, periodo, CAST(origem AS STRING),
            CAST(horizonte AS STRING))) chaves,
        COUNTIF(periodo = 'desenvolvimento') n_dev, COUNTIF(periodo = 'teste_final') n_teste,
        AVG(IF(periodo = 'desenvolvimento', ABS(erro_pct), NULL)) mape_dev,
        AVG(IF(periodo = 'teste_final', ABS(erro_pct), NULL)) mape_teste,
        COUNTIF(ABS(log_razao - LN(real_mwmed / previsto_mwmed)) > 1e-9) log_inconsistente,
        COUNTIF(ABS(erro_mwmed - (previsto_mwmed - real_mwmed)) > 1e-6) erro_inconsistente,
        COUNTIF(ultimo_mes_alvo_da_origem != DATE_ADD(origem, INTERVAL 12 MONTH)) ultimo_alvo_errado
        FROM `marts.fct_erro_previsao_carga` WHERE {V}""")
    checar("erros: chave natural única", e["chaves"] == e["n"], f"{e['n']} linhas")
    checar(
        "erros: 1.152 do desenvolvimento e 654 do teste final",
        (e["n_dev"], e["n_teste"]) == (1152, 654),
        (e["n_dev"], e["n_teste"]),
    )
    checar(
        f"erros: MAPE do desenvolvimento = {MAPE_DESENVOLVIMENTO}%",
        abs(e["mape_dev"] - MAPE_DESENVOLVIMENTO) < 0.01,
        round(e["mape_dev"], 4),
    )
    checar(
        f"erros: MAPE do teste final = {MAPE_TESTE_FINAL}%",
        abs(e["mape_teste"] - MAPE_TESTE_FINAL) < 0.01,
        round(e["mape_teste"], 4),
    )
    checar(
        "erros: log_razao e erro_mwmed coerentes",
        e["log_inconsistente"] == 0 and e["erro_inconsistente"] == 0,
    )
    checar("erros: último mês-alvo da origem = origem + 12", e["ultimo_alvo_errado"] == 0)

    c = q(f"""SELECT COUNT(*) n FROM `marts.fct_previsao_carga` p
        JOIN `marts.fct_carga_mensal` m ON m.mes = p.origem AND m.codigo_submercado = 'SE'
        WHERE p.{V} AND m.mes_utilizavel AND m.cobertura >= 0.999""")
    checar("previsão: a origem é um mês completo da série", c["n"] >= 12)
    print("\nFALHAS:", falhas)
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
