"""Correlação entre o erro de previsão, a carga e o PLD do SE (só leitura).

    uv run --env-file .env python -m scripts.medir_correlacoes_pld

Reproduz a tabela de `docs/metricas.md` ("Correlação entre o erro de previsão, a carga e o PLD do
SE"). PLD mensal: média simples das horas (2021 em diante, `fct_pld_ponderado_mensal`) ou semanal
por patamar ponderado por horas (até 2020, `scripts.medir_pld_historico`). `log_razao` = ln(real /
previsto). O IC de 95% é de Fisher e é OTIMISTA: os erros de origens vizinhas se sobrepõem.
"""

import sys

import numpy as np
import pandas as pd
from scipy import stats

from ingestion.common import gcp
from ingestion.common.config import carregar_config
from ml.registro import MODELO_VERSAO
from scripts import medir_pld_historico

TETO = 100 * 1024 * 1024


def consulta(cliente, sql: str, datas: list[str]) -> pd.DataFrame:
    linhas = gcp.executar_consulta(cliente, sql, max_bytes_faturados=TETO).linhas
    df = pd.DataFrame([dict(r.items()) for r in linhas])
    for c in datas:
        df[c] = pd.to_datetime(df[c])
    return df


def relatar(nome: str, x, y) -> None:
    x, y = np.asarray(x, float), np.asarray(y, float)
    r = stats.pearsonr(x, y)[0]
    rho = stats.spearmanr(x, y)[0]
    z, se = np.arctanh(r), 1 / np.sqrt(len(x) - 3)
    lo, hi = np.tanh(z - 1.96 * se), np.tanh(z + 1.96 * se)
    print(f"{nome:62s} n={len(x):3d} pearson={r:+.3f} [{lo:+.2f},{hi:+.2f}] spearman={rho:+.3f}")


def residuo(s: pd.Series) -> pd.Series:
    """Resíduo de uma regressão em tendência linear e dummies de mês."""
    t = np.arange(len(s))
    X = np.column_stack(
        [np.ones(len(s)), t] + [(s.index.month == m).astype(float) for m in range(2, 13)]
    )
    beta = np.linalg.lstsq(X, s.values, rcond=None)[0]
    return pd.Series(s.values - X @ beta, index=s.index)


def main() -> int:
    cliente = gcp.cliente_bigquery(carregar_config())
    e = consulta(
        cliente,
        f"""SELECT periodo, origem, horizonte, mes_alvo, log_razao
            FROM `marts.fct_erro_previsao_carga` WHERE modelo_versao = '{MODELO_VERSAO}'""",
        ["origem", "mes_alvo"],
    )
    c = consulta(
        cliente,
        """SELECT mes, carga_ajustada_reconstruida_mwmed AS carga FROM `marts.fct_carga_mensal`
           WHERE codigo_submercado = 'SE' AND NOT mes_incompleto
             AND carga_ajustada_reconstruida_mwmed IS NOT NULL""",
        ["mes"],
    ).set_index("mes")["carga"]
    ph = consulta(
        cliente,
        """SELECT mes, pld_medio_simples_rs_mwh AS pld FROM `marts.fct_pld_ponderado_mensal`
           WHERE mes_completo""",
        ["mes"],
    ).set_index("mes")["pld"]
    ps = medir_pld_historico.pld_mensal_semanal(medir_pld_historico.carregar(cliente))["pld"]
    pld = pd.concat([ps[ps.index < "2021-01-01"], ph.astype(float)]).sort_index()

    for h in (1, 12):
        for periodo, rotulo in (("teste_final", "2021-2025 (PLD horário)"), (None, "2012-2025")):
            d = e[e["horizonte"] == h]
            if periodo:
                d = d[d["periodo"] == periodo]
            d = d.set_index("mes_alvo").join(pld.rename("pld"), how="inner").dropna()
            relatar(f"log_razao h={h} x ln(PLD), {rotulo}", d["log_razao"], np.log(d["pld"]))
    d = e.groupby("mes_alvo")["log_razao"].mean().to_frame().join(pld.rename("pld"), how="inner")
    relatar("log_razao médio (h=1..12) x ln(PLD), 2012-2025", d["log_razao"], np.log(d["pld"]))

    j = pd.concat([c.rename("carga"), pld.rename("pld")], axis=1, join="inner")
    j = j[j.index >= "2015-01-01"]
    relatar("carga mensal x PLD (nível), 2015-2025", j["carga"], j["pld"])
    d12 = np.log(j).diff(12).dropna()
    relatar("Δ12 ln(carga) x Δ12 ln(PLD), 2016-2025", d12["carga"], d12["pld"])
    relatar(
        "resíduo(ln carga ~ tendência+mês) x ln(PLD), 2015-2025",
        residuo(np.log(j["carga"])),
        np.log(j["pld"]),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
