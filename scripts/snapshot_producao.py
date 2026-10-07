"""Retrato (snapshot) das tabelas de produção que o incremental do ONS reconstrói. SÓ LEITURA.

    uv run python -m scripts.snapshot_producao snapshot --saida arquivo.json
    uv run python -m scripts.snapshot_producao comparar --a antes.json --b depois.json

Guarda, por mês UTC e submercado: linhas, valores não nulos e soma de cada coluna de valor, para
`staging.stg_ons__curva_carga`, `marts.fct_carga_horaria` e `marts.fct_submercado_horario`. Serve
para provar que uma reconstrução (full-refresh) ou uma execução incremental deixou a produção com
os MESMOS números de antes. Toda consulta passa por `gcp.executar_consulta`.
"""

import argparse
import json
import sys
from pathlib import Path

from ingestion.common import gcp
from ingestion.common.config import carregar_config

MES_UTC = "format_timestamp('%Y-%m', instante_utc)"
MES_LOCAL_RAW = "format_date('%Y-%m', _mes_referencia)"
# tabela -> (coluna do submercado, expressões de valor, expressão do mês). O raw é agrupado pelo mês
# LOCAL (a partição dele); as demais pelo mês UTC (a partição delas).
TABELAS = {
    "raw.ons_curva_carga": (
        "id_subsistema",
        ["safe_cast(val_cargaenergiahomwmed as float64)"],
        MES_LOCAL_RAW,
    ),
    "staging.stg_ons__curva_carga": ("id_subsistema", ["carga_mwmed"], MES_UTC),
    "marts.fct_carga_horaria": ("codigo_submercado", ["carga_mwmed"], MES_UTC),
    "marts.fct_submercado_horario": (
        "codigo_submercado",
        ["carga_mwmed", "pld_rs_mwh", "temperatura_c"],
        MES_UTC,
    ),
}
TOLERANCIA_SOMA = 0.01


def sql_snapshot(
    tabela_id: str, submercado: str, valores: list[str], mes_sql: str = MES_UTC
) -> str:
    medidas = ", ".join(
        f"count({v}) nn_{i}, round(sum({v}), 3) soma_{i}" for i, v in enumerate(valores)
    )
    return (
        f"select {mes_sql} mes, {submercado} sub, count(*) n, "
        f"{medidas} from `{tabela_id}` group by 1, 2 order by 1, 2"
    )


def tirar_snapshot() -> dict:
    config = carregar_config()
    cli = gcp.cliente_bigquery(config)
    saida: dict = {}
    for tabela, (sub, valores, mes_sql) in TABELAS.items():
        dataset, _, nome = tabela.partition(".")
        sql = sql_snapshot(config.tabela(dataset, nome), sub, valores, mes_sql)
        grupos = {}
        for r in gcp.executar_consulta(cli, sql, usar_cache=False).linhas:
            medidas = [r["n"]]
            for i in range(len(valores)):
                medidas += [r[f"nn_{i}"], float(r[f"soma_{i}"] or 0)]
            grupos[f"{r['mes']}|{r['sub']}"] = medidas
        saida[tabela] = grupos
    return saida


def comparar_snapshots(a: dict, b: dict) -> tuple[list[str], dict[str, int]]:
    """Lista os grupos que diferem e devolve (diferenças, grupos por tabela)."""
    diferencas, totais = [], {}
    for tabela in sorted(set(a) | set(b)):
        ga, gb = a.get(tabela, {}), b.get(tabela, {})
        totais[tabela] = len(set(ga) | set(gb))
        for chave in sorted(set(ga) | set(gb)):
            va, vb = ga.get(chave), gb.get(chave)
            igual = (
                va is not None
                and vb is not None
                and len(va) == len(vb)
                and all(abs(x - y) <= TOLERANCIA_SOMA for x, y in zip(va, vb, strict=True))
            )
            if not igual:
                diferencas.append(f"{tabela} {chave}: antes {va} | depois {vb}")
    return diferencas, totais


def comparar_com_regras(
    a: dict, b: dict, informativo_desde: str | None = None, so_comuns: bool = False
) -> tuple[list[str], list[str], dict[str, int]]:
    """Compara dois retratos. Devolve (diferenças que reprovam, informativas, grupos por tabela).

    Grupos de mês >= `informativo_desde` (AAAA-MM) só informam quando o valor muda (o ONS revisa e
    acrescenta dados no ano corrente), MAS perder linhas reprova do mesmo jeito (o ONS só
    acrescenta): um grupo que existia e sumiu, ou com menos linhas. `so_comuns` ignora tabelas que
    só um dos retratos tem (ex.: o retrato do 4b ainda não tinha o raw).
    """
    tabelas = sorted(set(a) & set(b)) if so_comuns else sorted(set(a) | set(b))
    estritas, informativas, totais = [], [], {}
    for tabela in tabelas:
        ga, gb = a.get(tabela, {}), b.get(tabela, {})
        totais[tabela] = len(set(ga) | set(gb))
        for chave in sorted(set(ga) | set(gb)):
            va, vb = ga.get(chave), gb.get(chave)
            if (
                va is not None
                and vb is not None
                and len(va) == len(vb)
                and all(abs(x - y) <= TOLERANCIA_SOMA for x, y in zip(va, vb, strict=True))
            ):
                continue
            linha = f"{tabela} {chave}: antes {va} | depois {vb}"
            recente = informativo_desde is not None and chave.split("|")[0] >= informativo_desde
            perdeu = va is not None and (vb is None or vb[0] < va[0])
            (informativas if recente and not perdeu else estritas).append(linha)
    return estritas, informativas, totais


def montar_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Snapshot das tabelas do ONS em produção (leitura)")
    p.add_argument("comando", choices=["snapshot", "comparar"])
    p.add_argument("--saida", help="snapshot: arquivo JSON de saída")
    p.add_argument("--a", help="comparar: snapshot de referência (antes)")
    p.add_argument("--b", help="comparar: snapshot a conferir (depois)")
    p.add_argument(
        "--informativo-desde",
        help="comparar: meses >= AAAA-MM só informam se o valor mudar (perder linhas reprova)",
    )
    p.add_argument(
        "--so-comuns", action="store_true", help="comparar: só as tabelas que os dois retratos têm"
    )
    return p


def main(argv: list[str]) -> int:
    p = montar_parser()
    args = p.parse_args(argv)
    if args.comando == "snapshot":
        if not args.saida:
            p.error("snapshot exige --saida")
        dados = tirar_snapshot()
        Path(args.saida).write_text(json.dumps(dados), encoding="utf-8")
        linhas = {t: sum(g[0] for g in grupos.values()) for t, grupos in dados.items()}
        print(
            f"snapshot -> {args.saida}: "
            + " | ".join(f"{t} {n:,} linhas" for t, n in linhas.items())
        )
        return 0
    if not (args.a and args.b):
        p.error("comparar exige --a e --b")
    estritas, informativas, totais = comparar_com_regras(
        json.loads(Path(args.a).read_text()),
        json.loads(Path(args.b).read_text()),
        args.informativo_desde,
        args.so_comuns,
    )
    print(
        f"comparar snapshots: {sum(totais.values())} grupos (mês x submercado, "
        f"{len(totais)} tabelas) | diferentes (reprovam) {len(estritas)} "
        f"| informativos {len(informativas)}"
    )
    for linha in estritas[:10]:
        print(f"  DIFERENTE {linha}")
    for linha in informativas[:6]:
        print(f"  informativo {linha}")
    print("IGUAIS ao estado anterior" if not estritas else "ERRO: a produção mudou")
    return 0 if not estritas else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
