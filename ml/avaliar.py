"""Avalia os baselines na validação temporal e grava os resultados em `docs/resultados/`.

    uv run --env-file .env python -m ml.avaliar --periodo desenvolvimento
    uv run --env-file .env python -m ml.avaliar --periodo estresse_2020

LÊ da nuvem (só leitura, com teto de bytes): a série mensal do SE/CO em `marts.fct_carga_mensal`,
filtrada em `mes_utilizavel`, e a data da consulta do seed do ajuste. NÃO grava na nuvem.

O TESTE FINAL (2021-2025) É USADO UMA VEZ, DEPOIS DE APROVADO O CHECKPOINT B. Por isso o CLI recusa
`--periodo teste_final` sem `--liberar-teste-final`, e cada período só carrega a série até o seu
último mês-alvo: rodar o desenvolvimento nem sequer lê 2020 em diante.

SÉRIES. `original` (a curva do ONS como veio) e `ajustada` (levada a uma definição só: tipo III e
MMGD). A ajustada só existe a partir de 2018, então só entra nos pares em que ela e a base existem;
`original_nos_pares_da_ajustada` é a original restrita aos MESMOS pares, para comparar sem trocar o
conjunto de meses.

SAÍDAS (prefixo `baseline_<periodo>`):
    _por_horizonte.csv   MAPE, MAE, viés por horizonte e geral; recortes `todas_as_origens` e
                         `origem_dezembro` (a decisão do contrato)
    _erro_anual.csv      erro do ano inteiro nas origens de dezembro
    _previsoes.csv       cada previsão (origem, horizonte, alvo, previsto, real, erro)
    .meta.json           data, commit de referência, parâmetros, séries e bytes lidos
"""

import argparse
import csv
import json
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

from ml.baselines import BASELINES
from ml.metricas import Registro, erro_anual, por_horizonte
from ml.validacao import (
    HORIZONTES,
    PERIODOS,
    Periodo,
    Serie,
    pares,
    serie_utilizavel,
    visao_na_origem,
)

RAIZ = Path(__file__).resolve().parents[1]
SAIDA_PADRAO = RAIZ / "docs" / "resultados"
SUBMERCADO = "SE"  # o submercado do supermercado (SE/CO); os outros não são avaliados
SERIES = {"original": "carga_original_mwmed", "ajustada": "carga_ajustada_mwmed"}
SERIE_COMPARACAO = "original_nos_pares_da_ajustada"
TETO_BYTES = 100 * 1024 * 1024
ORDEM_SERIES = (*SERIES, SERIE_COMPARACAO)
RECORTES = ("todas_as_origens", "origem_dezembro")


# ---------------------------------------------------------------- leitura (nuvem)


def sql_serie(periodo: Periodo) -> str:
    """A consulta da série. Corta no último mês-alvo: nada posterior ao período é lido."""
    return f"""
        SELECT mes, carga_original_mwmed, carga_ajustada_mwmed, mes_utilizavel
        FROM `marts.fct_carga_mensal`
        WHERE codigo_submercado = '{SUBMERCADO}' AND mes <= DATE '{periodo.alvo_fim}'
        ORDER BY mes"""


SQL_SEED = "SELECT MAX(consultado_em) AS consultado_em FROM `staging.ajuste_definicao_carga`"


def carregar_da_nuvem(periodo: Periodo) -> tuple[list[dict], dict]:
    from ingestion.common import gcp
    from ingestion.common.config import carregar_config

    cliente = gcp.cliente_bigquery(carregar_config())
    res = gcp.executar_consulta(cliente, sql_serie(periodo), max_bytes_faturados=TETO_BYTES)
    seed = gcp.executar_consulta(cliente, SQL_SEED, max_bytes_faturados=TETO_BYTES)
    info = {
        "bytes_processados": (res.bytes_processados or 0) + (seed.bytes_processados or 0),
        "bytes_faturados": (res.bytes_faturados or 0) + (seed.bytes_faturados or 0),
        "seed_consultado_em": str(seed.linhas[0]["consultado_em"]),
    }
    return [dict(linha.items()) for linha in res.linhas], info


# ---------------------------------------------------------------- avaliação (sem nuvem)


def gerar_registros(series: dict[str, Serie], periodo: Periodo) -> list[Registro]:
    """Uma previsão por (série, baseline, origem, horizonte) cujo alvo cai no período.

    A previsão só vê `visao_na_origem`. Um par sem valor real no alvo, sem valor na origem ou sem
    os meses que o baseline exige fica de fora (nada é preenchido ou interpolado).
    """
    registros: list[Registro] = []
    for nome, serie in series.items():
        visoes: dict[date, Serie] = {}
        for par in pares(periodo):
            real = serie.get(par.alvo)
            if real is None or par.origem not in serie:
                continue
            historico = visoes.setdefault(par.origem, visao_na_origem(serie, par.origem))
            for baseline, funcao in BASELINES.items():
                previsto = funcao(historico, par.origem, par.horizonte)
                if previsto is not None:
                    registros.append(
                        Registro(
                            nome, baseline, par.origem, par.horizonte, par.alvo, previsto, real
                        )
                    )
    return registros


def com_original_nos_pares_da_ajustada(registros: list[Registro]) -> list[Registro]:
    chaves = {(r.baseline, r.origem, r.horizonte) for r in registros if r.serie == "ajustada"}
    extra = [
        replace(r, serie=SERIE_COMPARACAO)
        for r in registros
        if r.serie == "original" and (r.baseline, r.origem, r.horizonte) in chaves
    ]
    return [*registros, *extra]


def _grupos(registros: list[Registro]):
    for serie in ORDEM_SERIES:
        for baseline in BASELINES:
            rs = [r for r in registros if r.serie == serie and r.baseline == baseline]
            if rs:
                yield serie, baseline, rs


def tabela_por_horizonte(registros: list[Registro]) -> list[dict]:
    linhas = []
    for serie, baseline, rs in _grupos(registros):
        for recorte in RECORTES:
            sub = rs if recorte == "todas_as_origens" else [r for r in rs if r.origem.month == 12]
            for linha in por_horizonte(sub):
                if linha["n"]:
                    linhas.append(
                        {"serie": serie, "baseline": baseline, "recorte": recorte, **linha}
                    )
    return linhas


def tabela_erro_anual(registros: list[Registro]) -> list[dict]:
    linhas = []
    for serie, baseline, rs in _grupos(registros):
        dezembro = [r for r in rs if r.origem.month == 12]
        linhas += [{"serie": serie, "baseline": baseline, **a} for a in erro_anual(dezembro)]
    return linhas


def tabela_previsoes(registros: list[Registro]) -> list[dict]:
    return [
        {
            "serie": r.serie,
            "baseline": r.baseline,
            "origem": r.origem.isoformat(),
            "horizonte": r.horizonte,
            "alvo": r.alvo.isoformat(),
            "previsto_mwmed": r.previsto,
            "real_mwmed": r.real,
            "erro_mwmed": r.erro,
            "erro_pct": 100 * r.erro / r.real,
        }
        for serie, baseline, rs in _grupos(registros)
        for r in sorted(rs, key=lambda x: (x.origem, x.horizonte))
    ]


# ---------------------------------------------------------------- gravação


def _formatar(valor):
    return round(valor, 4) if isinstance(valor, float) else valor


def gravar_csv(caminho: Path, linhas: list[dict]) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("w", newline="", encoding="utf-8") as f:
        escritor = csv.DictWriter(f, fieldnames=list(linhas[0]), lineterminator="\n")
        escritor.writeheader()
        escritor.writerows({k: _formatar(v) for k, v in linha.items()} for linha in linhas)


def referencia_git() -> dict:
    """Commit de referência (HEAD) e se a árvore tinha mudanças não commitadas.

    Os próprios resultados (`docs/resultados`) não contam: eles são gravados antes do meta, e
    contá-los faria toda execução parecer "com mudanças".
    """

    def git(*args):
        return subprocess.run(
            ["git", *args], cwd=RAIZ, capture_output=True, text=True, check=False
        ).stdout.strip()

    return {
        "commit": git("rev-parse", "HEAD"),
        "arvore_com_mudancas": bool(
            git("status", "--porcelain", "--", ".", ":(exclude)docs/resultados")
        ),
    }


def montar_meta(
    periodo: Periodo, series: dict[str, Serie], registros: list[Registro], info: dict
) -> dict:
    return {
        "gerado_em_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        **referencia_git(),
        "periodo": periodo.nome,
        "alvo_inicio": periodo.alvo_inicio.isoformat(),
        "alvo_fim": periodo.alvo_fim.isoformat(),
        "submercado": SUBMERCADO,
        "horizontes": [HORIZONTES[0], HORIZONTES[-1]],
        "baselines": list(BASELINES),
        "series": {
            nome: {
                "meses_utilizaveis": len(s),
                "primeiro": min(s).isoformat(),
                "ultimo": max(s).isoformat(),
            }
            for nome, s in series.items()
            if s
        },
        "pares_avaliados": {
            f"{serie}/{baseline}": len(rs) for serie, baseline, rs in _grupos(registros)
        },
        "definicoes": {
            "erro": "previsto - real (positivo = previu acima do real)",
            "mape_pct": "media de |erro| / real, em %",
            "vies_pct": "media de erro / real, em %",
            "origem_dezembro": "origens em dezembro: a decisao do contrato (Sprint 6)",
        },
        **info,
    }


def avaliar(periodo: Periodo, linhas: list[dict], info: dict, saida: Path) -> list[Registro]:
    series = {nome: serie_utilizavel(linhas, coluna) for nome, coluna in SERIES.items()}
    registros = com_original_nos_pares_da_ajustada(gerar_registros(series, periodo))
    prefixo = saida / f"baseline_{periodo.nome}"
    gravar_csv(Path(f"{prefixo}_por_horizonte.csv"), tabela_por_horizonte(registros))
    gravar_csv(Path(f"{prefixo}_erro_anual.csv"), tabela_erro_anual(registros))
    gravar_csv(Path(f"{prefixo}_previsoes.csv"), tabela_previsoes(registros))
    Path(f"{prefixo}.meta.json").write_text(
        json.dumps(montar_meta(periodo, series, registros, info), indent=2, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    return registros


def imprimir_resumo(registros: list[Registro]) -> None:
    print("\nserie / baseline / recorte (geral): n  MAPE%  MAE  vies(MWmed)  vies%")
    for linha in tabela_por_horizonte(registros):
        if linha["horizonte"] == "geral":
            print(
                f"{linha['serie']:>32} {linha['baseline']:>19} {linha['recorte']:>17}: "
                f"{linha['n']:4d} {linha['mape_pct']:6.2f} {linha['mae_mwmed']:8.0f} "
                f"{linha['vies_mwmed']:8.0f} {linha['vies_pct']:6.2f}"
            )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--periodo", required=True, choices=list(PERIODOS))
    ap.add_argument("--saida", type=Path, default=SAIDA_PADRAO)
    ap.add_argument(
        "--liberar-teste-final",
        action="store_true",
        help="OBRIGATÓRIO para o teste final, que só roda depois do Checkpoint B aprovado",
    )
    args = ap.parse_args(argv)
    periodo = PERIODOS[args.periodo]
    if periodo.final and not args.liberar_teste_final:
        print(
            "RECUSADO: o teste final (2021-2025) só roda uma vez, depois que o Checkpoint B for "
            "aprovado. Se for a hora, passe --liberar-teste-final.",
            file=sys.stderr,
        )
        return 2
    linhas, info = carregar_da_nuvem(periodo)
    registros = avaliar(periodo, linhas, info, args.saida)
    imprimir_resumo(registros)
    print(f"\nbytes processados: {info['bytes_processados']:,}; resultados em {args.saida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
