"""Análise de erros e intervalos do vencedor (Sprint 5, tarefas 5.3 e a base da 5.6).

    uv run --env-file .env python -m ml.analise_erros

Só LÊ os resultados já gravados em `docs/resultados/` (as previsões do desenvolvimento e do teste
final) e a temperatura mensal do SE/CO (uma consulta de ~10 MB, guardada em `data/modelos/`).
Não roda nenhum
modelo e não grava na nuvem: o teste final continua sendo usado uma vez.

1. ERROS por mês-calendário do alvo, por ano e por horizonte (candidato e ingênuo nos mesmos pares).
2. TEMPERATURA (2021+): relação do erro médio de cada mês-alvo com a anomalia de temperatura do mês
   (temperatura média do SE/CO menos a média do mesmo mês-calendário em 2021-2025: uma anomalia
   dentro da amostra, boa para diagnóstico e NÃO para previsão).
3. INTERVALOS: quantis empíricos do erro em log, log(real / previsto), do DESENVOLVIMENTO, por
   horizonte (10/90 para 80% e 2,5/97,5 para 95%), aplicados ao teste final, com a cobertura. Uma
   variante com os erros de todos os horizontes juntos serve de sensibilidade.
4. ERROS POR ORIGEM (vetor de 12 horizontes de cada origem), para os cenários de consumo da Parte B:
   a correlação entre meses fica preservada porque a origem é a unidade.
"""

import argparse
import csv
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from ml.avaliar import gravar_csv
from ml.registro import CANDIDATO_DO_TESTE_FINAL
from ml.validacao import HORIZONTES

RAIZ = Path(__file__).resolve().parents[1]
RES = RAIZ / "docs" / "resultados"
DADOS = RAIZ / "data" / "modelos"
QUANTIS = {"q025": 0.025, "q10": 0.10, "q50": 0.50, "q90": 0.90, "q975": 0.975}
INGENUO = "sazonal_ingenuo_mesmos_pares"
TETO_BYTES = 100 * 1024 * 1024


def ler_previsoes(periodo: str, serie: str) -> pd.DataFrame:
    df = pd.read_csv(
        RES / f"candidatos_{periodo}_{serie}_previsoes.csv", parse_dates=["origem", "alvo"]
    )
    df["ano"] = df.alvo.dt.year
    df["mes"] = df.alvo.dt.month
    return df


def resumir(df: pd.DataFrame, por: str) -> pd.DataFrame:
    """MAPE, viés % (com sinal) e n por grupo e candidato (erro = previsto - real)."""
    g = df.assign(ape=df.erro_pct.abs()).groupby(["candidato", por])
    return g.agg(
        n=("erro_pct", "size"), mape_pct=("ape", "mean"), vies_pct=("erro_pct", "mean")
    ).reset_index()


# ---------------------------------------------------------------- temperatura


def temperatura_mensal() -> pd.DataFrame:
    caminho = DADOS / "temperatura_mensal_se.csv"
    if not caminho.exists():
        from ingestion.common import gcp
        from ingestion.common.config import carregar_config

        sql = """SELECT DATE_TRUNC(DATE(instante_utc, 'America/Sao_Paulo'), MONTH) AS mes,
            AVG(temperatura_c) AS temp_media, COUNT(temperatura_c) AS horas_com_dado
            FROM `marts.fct_submercado_horario`
            WHERE codigo_submercado = 'SE' AND temperatura_c IS NOT NULL
            GROUP BY mes ORDER BY mes"""
        res = gcp.executar_consulta(
            gcp.cliente_bigquery(carregar_config()), sql, max_bytes_faturados=TETO_BYTES
        )
        caminho.parent.mkdir(parents=True, exist_ok=True)
        with caminho.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(["mes", "temp_media", "horas_com_dado"])
            for r in res.linhas:
                w.writerow([r["mes"], r["temp_media"], r["horas_com_dado"]])
    t = pd.read_csv(caminho, parse_dates=["mes"])
    # só meses com dado quase completo (a janela de INMET tem meses de borda)
    t = t[t.horas_com_dado > 0.9 * t.horas_com_dado.median()].copy()
    t = t[(t.mes >= "2021-01-01") & (t.mes <= "2025-12-01")]
    t["anomalia_c"] = t.temp_media - t.groupby(t.mes.dt.month).temp_media.transform("mean")
    return t


def erro_vs_temperatura(
    df: pd.DataFrame, temp: pd.DataFrame, candidato: str, h: int | None
) -> dict:
    """Erro médio de cada mês-alvo (todos os horizontes, ou só `h`) contra a anomalia do mês."""
    d = df[df.candidato == candidato]
    if h is not None:
        d = d[d.horizonte == h]
    m = d.groupby("alvo").erro_pct.mean().rename("erro_pct").reset_index()
    m = m.merge(temp, left_on="alvo", right_on="mes")
    x, y = m.anomalia_c.to_numpy(), m.erro_pct.to_numpy()
    if len(m) < 5:
        return {"candidato": candidato, "horizonte": h or "todos", "meses": len(m)}
    inclinacao, intercepto = np.polyfit(x, y, 1)
    return {
        "candidato": candidato,
        "horizonte": h or "todos",
        "meses": len(m),
        "correlacao": float(np.corrcoef(x, y)[0, 1]),
        "inclinacao_pct_por_c": float(inclinacao),
        "erro_pct_em_anomalia_zero": float(intercepto),
        "r2": float(np.corrcoef(x, y)[0, 1] ** 2),
    }


# ---------------------------------------------------------------- intervalos


def quantis_do_erro(dev: pd.DataFrame, candidato: str, por_horizonte: bool = True) -> pd.DataFrame:
    """Quantis de log(real / previsto) no desenvolvimento, por horizonte (ou todos juntos)."""
    d = dev[dev.candidato == candidato].copy()
    d["log_razao"] = np.log(d.real_mwmed / d.previsto_mwmed)
    linhas = []
    grupos = [(h, d[d.horizonte == h]) for h in HORIZONTES] if por_horizonte else [("todos", d)]
    for h, g in grupos:
        linhas.append(
            {"horizonte": h, "n": len(g)}
            | {k: float(g.log_razao.quantile(q)) for k, q in QUANTIS.items()}
        )
    return pd.DataFrame(linhas)


def aplicar_intervalos(teste: pd.DataFrame, quantis: pd.DataFrame, candidato: str) -> pd.DataFrame:
    t = teste[teste.candidato == candidato].copy()
    q = quantis.set_index("horizonte")
    chave = pd.Series(["todos"] * len(t), index=t.index) if "todos" in q.index else t.horizonte
    for k in ("q025", "q10", "q50", "q90", "q975"):
        t[k] = chave.map(q[k])
    t["lo95"] = t.previsto_mwmed * np.exp(t.q025)
    t["hi95"] = t.previsto_mwmed * np.exp(t.q975)
    t["lo80"] = t.previsto_mwmed * np.exp(t.q10)
    t["hi80"] = t.previsto_mwmed * np.exp(t.q90)
    t["dentro80"] = (t.real_mwmed >= t.lo80) & (t.real_mwmed <= t.hi80)
    t["dentro95"] = (t.real_mwmed >= t.lo95) & (t.real_mwmed <= t.hi95)
    t["largura80_pct"] = 100 * (t.hi80 - t.lo80) / t.previsto_mwmed
    t["largura95_pct"] = 100 * (t.hi95 - t.lo95) / t.previsto_mwmed
    return t


def cobertura(t: pd.DataFrame, por: str | None = None) -> pd.DataFrame:
    """Cobertura (% dos reais dentro do intervalo) e largura média, geral ou por horizonte/ano."""
    grupos = [("geral", t)] if por is None else list(t.groupby(por))
    linhas = [
        {
            "recorte": por or "geral",
            "valor": valor,
            "n": len(g),
            "cobertura80_pct": 100 * g.dentro80.mean(),
            "cobertura95_pct": 100 * g.dentro95.mean(),
            "largura80_pct": g.largura80_pct.mean(),
            "largura95_pct": g.largura95_pct.mean(),
            "abaixo_do_piso95": int((g.real_mwmed < g.lo95).sum()),
            "acima_do_teto95": int((g.real_mwmed > g.hi95).sum()),
        }
        for valor, g in grupos
    ]
    return pd.DataFrame(linhas)


def erros_por_origem(df: pd.DataFrame, candidato: str) -> pd.DataFrame:
    """Uma linha por origem com o erro % de cada horizonte (colunas h01..h12)."""
    d = df[df.candidato == candidato]
    w = d.pivot(index="origem", columns="horizonte", values="erro_pct")
    w = w.reindex(columns=list(HORIZONTES))
    w.columns = [f"erro_pct_h{h:02d}" for h in HORIZONTES]
    w.insert(0, "horizontes_completos", w.notna().all(axis=1))
    return w.reset_index()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--saida", type=Path, default=RES)
    args = ap.parse_args(argv)
    cand = CANDIDATO_DO_TESTE_FINAL
    dev = ler_previsoes("desenvolvimento", "original")
    saida = args.saida
    for serie in ("reconstruida", "original"):
        teste = ler_previsoes("teste_final", serie)
        nome = f"analise_teste_final_{serie}"
        # 1. erros por mês-calendário, ano e horizonte (candidato e ingênuo nos mesmos pares)
        base = teste[
            teste.candidato.isin([cand, INGENUO if serie == "reconstruida" else "sazonal_ingenuo"])
        ]
        for por, rotulo in (("mes", "mes_calendario"), ("ano", "ano"), ("horizonte", "horizonte")):
            gravar_csv(saida / f"{nome}_por_{rotulo}.csv", resumir(base, por).to_dict("records"))
        # 3. intervalos
        for variante, por_h in (("por_horizonte", True), ("pooled", False)):
            q = quantis_do_erro(dev, cand, por_h)
            gravar_csv(saida / f"quantis_erro_desenvolvimento_{variante}.csv", q.to_dict("records"))
            t = aplicar_intervalos(teste, q, cand)
            gravar_csv(
                saida / f"{nome}_intervalos_{variante}.csv",
                t.drop(columns=["ano", "mes"]).to_dict("records"),
            )
            linhas = [
                r
                for por in (None, "horizonte", "ano")
                for r in cobertura(t, por).to_dict("records")
            ]
            gravar_csv(saida / f"{nome}_cobertura_{variante}.csv", linhas)
        # 4. erros por origem
        for periodo, df in (("desenvolvimento", dev), ("teste_final", teste)):
            if periodo == "desenvolvimento" and serie != "original":
                continue
            gravar_csv(
                saida / f"erros_por_origem_{periodo}_{serie}.csv",
                erros_por_origem(df, cand).to_dict("records"),
            )
    # pendência 17: out/2021 (a curva do SE/CO fica ~972 MWmed abaixo da API nesse mês)
    for serie in ("reconstruida", "original"):
        t = ler_previsoes("teste_final", serie)
        out = t[(t.alvo == pd.Timestamp("2021-10-01"))][
            ["candidato", "origem", "horizonte", "previsto_mwmed", "real_mwmed", "erro_pct"]
        ]
        gravar_csv(saida / f"analise_teste_final_{serie}_out2021.csv", out.to_dict("records"))
        for c, g in t.groupby("candidato"):
            a21 = g[g.ano == 2021]
            sem = a21[a21.alvo != pd.Timestamp("2021-10-01")]
            print(
                f"[out/2021 {serie}] {c}: MAPE 2021 {a21.erro_pct.abs().mean():.2f}% "
                f"(sem out/2021: {sem.erro_pct.abs().mean():.2f}%); erro em out/2021: "
                f"{g[g.alvo == pd.Timestamp('2021-10-01')].erro_pct.mean():+.2f}%"
            )
    # 2. temperatura, na série principal
    temp = temperatura_mensal()
    teste = ler_previsoes("teste_final", "reconstruida")
    linhas = [
        erro_vs_temperatura(teste, temp, c, h) for c in (cand, INGENUO) for h in (None, 1, 12)
    ]
    gravar_csv(saida / "analise_teste_final_reconstruida_temperatura.csv", linhas)
    print(f"análise gravada em {saida} ({date.today()})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
