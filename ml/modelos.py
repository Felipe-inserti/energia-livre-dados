"""Modelos candidatos da previsão mensal (tarefa 5.2). Todos têm a MESMA assinatura dos baselines:

    prever(historico, origem, horizontes) -> {horizonte: previsão em MWmed}

e todos começam por `preparo.preparar`, que corta o histórico na origem (`visao_na_origem`), troca o
choque da COVID e fica com os últimos 72 meses. Quem prevê nunca vê um mês depois da origem, nem que
lhe entreguem a série inteira (há um teste que adultera o futuro). Um modelo que não converge ou não
tem 72 meses seguidos devolve {} e o par fica fora das métricas (nada é preenchido).

Famílias (grade FIXA em `registro.py`, definida antes de rodar):
- ETS: erro aditivo, 4 especificações (tendência nenhuma ou amortecida x sazonal aditiva ou
  multiplicativa), escolhida por AICc em cada origem (só informação até a origem).
- SARIMA em log: 4 especificações, escolhida por AICc em cada origem.
- Regressão ridge em log: tendência linear local + 11 dummies de mês + log dos dias úteis efetivos
  e do número de dias. A tendência é local porque a janela é de 72 meses.
- LightGBM: prevê log(y_t / y_{t-12}) a partir de horizonte, mês, crescimento recente e variação do
  calendário contra o mesmo mês do ano anterior (LightGBM não extrapola tendência, por isso o alvo é
  uma razão). Parâmetros fixos e semente fixa.
"""

import math
import warnings
from datetime import date

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from statsmodels.tsa.exponential_smoothing.ets import ETSModel
from statsmodels.tsa.statespace.sarimax import SARIMAX

from ml.features import calendario
from ml.preparo import preparar
from ml.validacao import Serie, somar_meses

ETS_GRADE = (
    {"trend": None, "damped": False, "seasonal": "mul"},
    {"trend": "add", "damped": True, "seasonal": "mul"},
    {"trend": None, "damped": False, "seasonal": "add"},
    {"trend": "add", "damped": True, "seasonal": "add"},
)
SARIMA_GRADE = (
    ((0, 1, 1), (0, 1, 1)),
    ((1, 1, 0), (0, 1, 1)),
    ((1, 1, 1), (0, 1, 1)),
    ((0, 1, 1), (1, 1, 0)),
)
REGRESSAO_ALPHA = (
    1.0  # a priori: encolhimento leve sobre colunas padronizadas (72 linhas, 14 colunas)
)
LGBM_PARAMS = {
    "n_estimators": 150,
    "learning_rate": 0.05,
    "num_leaves": 4,
    "min_child_samples": 30,
    "subsample": 0.8,
    "subsample_freq": 1,
    "colsample_bytree": 0.8,
    "reg_lambda": 5.0,
    "random_state": 0,
    "n_jobs": 1,
    "deterministic": True,
    "force_row_wise": True,
    "verbose": -1,
}


def _serie_pd(treino: Serie) -> pd.Series:
    meses = sorted(treino)
    return pd.Series([treino[m] for m in meses], index=pd.DatetimeIndex(meses, freq="MS"))


def _alvos(origem: date, horizontes) -> dict[int, date]:
    return {h: somar_meses(origem, h) for h in horizontes}


def ets(historico: Serie, origem: date, horizontes) -> dict[int, float]:
    y = _serie_pd(preparar(historico, origem))
    melhor = None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for g in ETS_GRADE:
            try:
                r = ETSModel(
                    y,
                    error="add",
                    trend=g["trend"],
                    damped_trend=g["damped"],
                    seasonal=g["seasonal"],
                    seasonal_periods=12,
                ).fit(disp=False, maxiter=200)
            except Exception:  # noqa: BLE001 - uma especificação que não converge sai da grade
                continue
            if melhor is None or r.aicc < melhor.aicc:
                melhor = r
    if melhor is None:
        return {}
    f = melhor.forecast(max(horizontes))
    return {h: float(f.iloc[h - 1]) for h in horizontes}


def sarima(historico: Serie, origem: date, horizontes) -> dict[int, float]:
    ly = np.log(_serie_pd(preparar(historico, origem)))
    melhor = None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for ordem, sazonal in SARIMA_GRADE:
            try:
                r = SARIMAX(
                    ly,
                    order=ordem,
                    seasonal_order=(*sazonal, 12),
                    enforce_stationarity=False,
                    enforce_invertibility=False,
                ).fit(disp=False, maxiter=100)
            except Exception:  # noqa: BLE001
                continue
            k = len(r.params)
            aicc = r.aic + 2 * k * (k + 1) / max(r.nobs - k - 1, 1)
            if melhor is None or aicc < melhor[0]:
                melhor = (aicc, r)
    if melhor is None:
        return {}
    f = melhor[1].forecast(max(horizontes))
    return {h: float(math.exp(f.iloc[h - 1])) for h in horizontes}


def _desenho_regressao(meses: list[date], t0: date) -> pd.DataFrame:
    linhas = []
    for m in meses:
        c = calendario(m)
        linha = {"t": ((m.year - t0.year) * 12 + (m.month - t0.month)) / 12.0}
        linha.update({f"m{k}": float(m.month == k) for k in range(2, 13)})
        linha["log_uteis"] = math.log(max(c["uteis_efetivos"], 1))
        linha["log_ndias"] = math.log(c["ndias"])
        linhas.append(linha)
    return pd.DataFrame(linhas)


def regressao(historico: Serie, origem: date, horizontes) -> dict[int, float]:
    treino = preparar(historico, origem)
    meses = sorted(treino)
    t0 = meses[-1]
    x = _desenho_regressao(meses, t0)
    media, dp = x.mean(), x.std().replace(0, 1)
    modelo = Ridge(alpha=REGRESSAO_ALPHA).fit(
        ((x - media) / dp).values, np.log([treino[m] for m in meses])
    )
    alvos = _alvos(origem, horizontes)
    xf = _desenho_regressao(list(alvos.values()), t0)
    p = np.exp(modelo.predict(((xf - media) / dp).values))
    return {h: float(v) for h, v in zip(alvos, p, strict=True)}


def _atributos_lgbm(y: Serie, origem: date, h: int) -> tuple[list[float], float]:
    alvo, base = somar_meses(origem, h), somar_meses(origem, h - 12)
    s12 = sum(y[somar_meses(origem, -i)] for i in range(12))
    a12 = sum(y[somar_meses(origem, -i)] for i in range(12, 24))
    s3 = sum(y[somar_meses(origem, -i)] for i in range(3))
    a3 = sum(y[somar_meses(origem, -i)] for i in range(12, 15))
    ca, cb = calendario(alvo), calendario(base)
    atributos = [
        h,
        alvo.month,
        math.log(s12 / a12),
        math.log(s3 / a3),
        math.log(ca["uteis_efetivos"] / cb["uteis_efetivos"]),
        math.log(ca["ndias"] / cb["ndias"]),
    ]
    return atributos, math.log(y[base])


def lgbm(historico: Serie, origem: date, horizontes) -> dict[int, float]:
    import lightgbm as lgb  # grupo `ml-exploracao`: fora da imagem do Airflow (import só aqui)

    y = preparar(historico, origem)
    meses = sorted(y)
    x, alvo_ = [], []
    # linhas de treino: toda (origem anterior, h) cujo alvo já é conhecido na origem real
    for o in meses[24:]:
        for h in range(1, 13):
            t = somar_meses(o, h)
            if t > origem or t not in y or somar_meses(t, -12) not in y:
                continue
            x.append(_atributos_lgbm(y, o, h)[0])
            alvo_.append(math.log(y[t] / y[somar_meses(t, -12)]))
    if len(x) < 30:
        return {}
    modelo = lgb.LGBMRegressor(**LGBM_PARAMS).fit(np.array(x), np.array(alvo_))
    saida = {}
    for h in horizontes:
        atributos, log_base = _atributos_lgbm(y, origem, h)
        saida[h] = float(math.exp(log_base + modelo.predict(np.array([atributos]))[0]))
    return saida


def media_de(*modelos):
    """Combinação simples: média das previsões dos modelos (só onde TODOS preveem)."""

    def combinado(historico: Serie, origem: date, horizontes) -> dict[int, float]:
        partes = [m(historico, origem, horizontes) for m in modelos]
        return {
            h: sum(p[h] for p in partes) / len(partes)
            for h in horizontes
            if all(h in p for p in partes)
        }

    return combinado
