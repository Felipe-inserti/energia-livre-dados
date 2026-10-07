"""Verificação do dbt incremental (Sprint 4, passo 4). Só toca o dataset `verificacao_incremental`.

    uv run python -m scripts.verificar_incremental comparar --a TABELA_REF --b TABELA \\
        --submercado id_subsistema [--valor carga_mwmed] [--excluir _carregado_em] [--detalhe arq]
    uv run python -m scripts.verificar_incremental apagar-particoes --tabela T --particoes AAAAMM,..

`comparar` prova que B (a tabela incremental) é IGUAL a A (a referência, de um build full):
- `EXCEPT DISTINCT` nos dois sentidos (A-B e B-A) sobre todas as colunas, menos as excluídas;
- contagem, valores não nulos e soma por mês UTC e submercado;
- linhas totais. Qualquer diferença lista só os grupos que diferem (a listagem completa vai para
  `--detalhe`). Toda consulta passa por `gcp.executar_consulta` (com `maximum_bytes_billed`) e a
  estimativa de bytes (dry-run) aparece no resumo.

`apagar-particoes` estraga de propósito as partições da janela, para o incremental ter o que
restaurar (um incremental que não muda nada comparado a um full pronto não provaria nada).
"""

import argparse
import sys
from pathlib import Path

from ingestion.common import gcp
from ingestion.common.config import carregar_config

DATASET = "verificacao_incremental"
TOLERANCIA_SOMA = 0.01
LIMITE_BYTES = 400 * 1024 * 1024  # o EXCEPT do staging lê as duas tabelas (~170 MB): teto explícito


def tabela_segura(config, nome: str) -> str:
    """`dataset.tabela` -> id completo, recusando qualquer dataset que não seja o de verificação."""
    dataset, _, tabela = nome.rpartition(".")
    if dataset != DATASET or not tabela:
        raise ValueError(f"Só o dataset {DATASET} é aceito aqui, não {nome!r}")
    return config.tabela(dataset, tabela)


def colunas_comuns(cliente, a: str, b: str, excluir: set[str]) -> list[str]:
    ca = [c.name for c in cliente.get_table(a).schema]
    cb = [c.name for c in cliente.get_table(b).schema]
    if sorted(ca) != sorted(cb):
        raise ValueError(f"As tabelas têm colunas diferentes: {sorted(set(ca) ^ set(cb))}")
    return [c for c in ca if c not in excluir]


def sql_except(a: str, b: str, colunas: list[str]) -> str:
    lista = ", ".join(colunas)
    return (
        f"select count(*) n from (select {lista} from `{a}` "
        f"except distinct select {lista} from `{b}`)"
    )


def sql_grupos(tabela: str, submercado: str, valor: str) -> str:
    return (
        f"select format_timestamp('%Y-%m', instante_utc) mes, {submercado} sub, count(*) n, "
        f"count({valor}) nao_nulos, round(sum({valor}), 3) soma from `{tabela}` group by 1, 2"
    )


def grupos_diferentes(a: dict, b: dict) -> tuple[list[str], int]:
    """Lista os grupos (mês, submercado) que diferem; devolve também quantos grupos existem."""
    diferentes = []
    for chave in sorted(set(a) | set(b)):
        if chave not in a or chave not in b:
            igual = False
        else:
            igual = (
                a[chave][:2] == b[chave][:2] and abs(a[chave][2] - b[chave][2]) <= TOLERANCIA_SOMA
            )
        if not igual:
            diferentes.append(f"{chave[0]} {chave[1]}: A {a.get(chave)} | B {b.get(chave)}")
    return diferentes, len(set(a) | set(b))


def comparar(
    ref: str, tabela: str, submercado: str, valor: str, excluir: set[str], detalhe: str | None
) -> bool:
    config = carregar_config()
    cli = gcp.cliente_bigquery(config)
    a, b = tabela_segura(config, ref), tabela_segura(config, tabela)
    colunas = colunas_comuns(cli, a, b, excluir)
    estimado = 0
    resultados = {}
    for rotulo, sql in (("A-B", sql_except(a, b, colunas)), ("B-A", sql_except(b, a, colunas))):
        estimado += gcp.executar_consulta(cli, sql, dry_run=True).bytes_processados or 0
        resultados[rotulo] = gcp.executar_consulta(
            cli, sql, usar_cache=False, max_bytes_faturados=LIMITE_BYTES
        ).linhas[0]["n"]

    def grupos(tabela_id: str) -> dict:
        linhas = gcp.executar_consulta(
            cli, sql_grupos(tabela_id, submercado, valor), usar_cache=False
        ).linhas
        return {
            (r["mes"], r["sub"]): (r["n"], r["nao_nulos"], float(r["soma"] or 0)) for r in linhas
        }

    ga, gb = grupos(a), grupos(b)
    diferentes, total = grupos_diferentes(ga, gb)
    linhas_a, linhas_b = sum(v[0] for v in ga.values()), sum(v[0] for v in gb.values())
    ok = resultados["A-B"] == 0 and resultados["B-A"] == 0 and not diferentes
    if detalhe:
        Path(detalhe).write_text(
            "\n".join(diferentes) + ("\n" if diferentes else ""), encoding="utf-8"
        )
    print(f"A (referência) = {ref} | B = {tabela} | colunas comparadas: {len(colunas)}")
    print(f"linhas: A {linhas_a:,} | B {linhas_b:,}")
    print(f"EXCEPT DISTINCT: A-B {resultados['A-B']} linhas | B-A {resultados['B-A']} linhas")
    print(
        f"grupos mês x submercado: {total} | iguais {total - len(diferentes)} | "
        f"diferentes {len(diferentes)}"
    )
    for linha in diferentes[:10]:
        print(f"  DIFERENTE {linha}")
    print(f"bytes estimados dos EXCEPT (dry-run): {estimado / 1e6:.1f} MB")
    print("IGUAIS" if ok else "ERRO: as tabelas diferem")
    return ok


def apagar_particoes(tabela: str, particoes: list[str]) -> None:
    config = carregar_config()
    cli = gcp.cliente_bigquery(config)
    alvo = tabela_segura(config, tabela)
    for particao in particoes:
        if not particao.isdigit() or len(particao) != 6:
            raise ValueError(f"Partição inválida: {particao!r} (use AAAAMM)")
        cli.delete_table(f"{alvo}${particao}", not_found_ok=True)
    print(f"partições apagadas de {tabela}: {', '.join(particoes)}")


def montar_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Verificação do dbt incremental")
    p.add_argument("comando", choices=["comparar", "apagar-particoes"])
    p.add_argument("--a", help="comparar: tabela de referência (dataset.tabela)")
    p.add_argument("--b", help="comparar: tabela incremental (dataset.tabela)")
    p.add_argument("--submercado", help="comparar: coluna do submercado")
    p.add_argument("--valor", default="carga_mwmed")
    p.add_argument(
        "--excluir", default="_carregado_em", help="colunas fora do EXCEPT, separadas por vírgula"
    )
    p.add_argument("--detalhe", help="comparar: arquivo com os grupos que diferem")
    p.add_argument("--tabela", help="apagar-particoes: dataset.tabela")
    p.add_argument("--particoes", help="apagar-particoes: AAAAMM separados por vírgula")
    return p


def main(argv: list[str]) -> int:
    p = montar_parser()
    args = p.parse_args(argv)
    if args.comando == "comparar":
        if not (args.a and args.b and args.submercado):
            p.error("comparar exige --a, --b e --submercado")
        excluir = {c for c in args.excluir.split(",") if c}
        return (
            0 if comparar(args.a, args.b, args.submercado, args.valor, excluir, args.detalhe) else 1
        )
    if not (args.tabela and args.particoes):
        p.error("apagar-particoes exige --tabela e --particoes")
    apagar_particoes(args.tabela, args.particoes.split(","))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
