"""PLD mensal do SE em 2001-2020 contra o piso e o teto de 2021-2026 (só leitura).

    uv run --env-file .env python -m scripts.medir_pld_historico [--saida mensal.csv]

Reproduz os números de `docs/metricas.md` ("PLD mensal do SE em 2001-2020 contra o piso e o teto"):
(1) o PLD mensal do SE é a média dos 3 patamares de cada semana, ponderada pelas horas da semana que
caem em cada mês local (aproximação UTC-3; a diferença do horário de verão é de 1 hora por semana na
virada); (2) mediana nominal por ano; (3) quantos meses ficam abaixo do piso e acima do teto
(horário e estrutural) de cada ano-limite da seed `pld_limites`, por ano histórico.
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from ingestion.common import gcp
from ingestion.common.config import carregar_config

RAIZ = Path(__file__).resolve().parents[1]
TETO_BYTES = 100 * 1024 * 1024
SQL = """SELECT inicio_semana_utc, fim_semana_utc, CAST(pld_rs_mwh AS FLOAT64) AS pld
         FROM `marts.fct_pld_semanal` WHERE codigo_submercado = 'SE'"""


def pld_mensal_semanal(semanal: pd.DataFrame) -> pd.DataFrame:
    """Colunas `horas` e `pld` por mês (índice = 1º dia do mês), até dez/2020."""
    sem = semanal.groupby(["inicio_semana_utc", "fim_semana_utc"], as_index=False).agg(
        pld=("pld", "mean"), n=("pld", "size")
    )
    assert (sem["n"] == 3).all(), "cada semana tem de ter 3 patamares"
    linhas = []
    for r in sem.itertuples():
        horas = pd.date_range(r.inicio_semana_utc, r.fim_semana_utc, freq="h", inclusive="left")
        meses = pd.Series((horas - pd.Timedelta(hours=3)).to_period("M")).value_counts()
        linhas += [(mes.to_timestamp(), c, r.pld) for mes, c in meses.items()]
    x = pd.DataFrame(linhas, columns=["mes", "h", "pld"])
    mensal = x.groupby("mes").apply(
        lambda g: pd.Series({"horas": g["h"].sum(), "pld": np.average(g["pld"], weights=g["h"])}),
        include_groups=False,
    )
    return mensal[mensal.index <= "2020-12-01"]


def carregar(cliente=None) -> pd.DataFrame:
    cliente = cliente or gcp.cliente_bigquery(carregar_config())
    linhas = gcp.executar_consulta(cliente, SQL, max_bytes_faturados=TETO_BYTES).linhas
    df = pd.DataFrame([dict(r.items()) for r in linhas])
    for c in ("inicio_semana_utc", "fim_semana_utc"):
        df[c] = pd.to_datetime(df[c]).dt.tz_localize(None)
    return df


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--saida", help="CSV do PLD mensal 2001-2020")
    args = ap.parse_args(argv)
    mensal = pld_mensal_semanal(carregar())
    if args.saida:
        mensal.to_csv(args.saida)
    print(f"meses: {len(mensal)} ({mensal.index.min():%Y-%m} a {mensal.index.max():%Y-%m})")
    mensal["ano"] = mensal.index.year
    print("\nMediana nominal do PLD mensal (SE) por ano (R$/MWh):")
    print(mensal.groupby("ano")["pld"].agg(["count", "median", "min", "max"]).round(2).to_string())
    lim = pd.read_csv(RAIZ / "dbt" / "seeds" / "pld_limites.csv").set_index("ano")
    print(
        "\nMeses abaixo do piso / acima do teto horário / acima do estrutural (de", len(mensal), ")"
    )
    for a, r in lim.iterrows():
        abaixo = int((mensal["pld"] < r["pld_min"]).sum())
        hor = int((mensal["pld"] > r["pld_max_horario"]).sum())
        est = int((mensal["pld"] > r["pld_max_estrutural"]).sum())
        print(
            f"{a}: piso {r['pld_min']}: {abaixo} | horário {r['pld_max_horario']}: {hor}"
            f" | estrutural {r['pld_max_estrutural']}: {est}"
        )
    print("\nMeses abaixo do piso de 2022, por ano histórico:")
    piso = lim.loc[2022, "pld_min"]
    print(mensal.groupby("ano")["pld"].apply(lambda s: int((s < piso).sum())).to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
