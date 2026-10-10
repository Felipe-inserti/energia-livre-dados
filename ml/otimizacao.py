"""Otimização do volume contratado (6.2) e leitura congelada dos cenários.

    uv run --env-file .env python -m ml.otimizacao ler --dry-run      # só estima os bytes
    uv run --env-file .env python -m ml.otimizacao ler --congelar     # 1ª leitura: grava os dados
    uv run --env-file .env python -m ml.otimizacao ler                # releitura: confere
    uv run python -m ml.otimizacao otimizar                           # só lê o disco, ex-ante

PROBLEMA (por origem `t`, dezembro do ano anterior). Escolher `V = r × V_pont` (MWm) para minimizar

    J(V) = E[custo(V)] + λ · CVaR_α[custo(V)]

sobre os N cenários conjuntos (cenário `s` de consumo pareado com o `s` de PLD; consumo e PLD são
independentes, decisão 9). `V_pont` é o consumo previsto médio do ano. O custo vem de `ml/custo.py`.

GRADE. `r ∈ [1/(1+f); 1/(1−f)]` (simétrica: a faixa contratada sempre contém a previsão),
passo 0,25%, com `r = 1` e os dois limites sempre incluídos. Com `f = 0` a grade é `[1]`.
O custo não é convexo em `V` (a energia entregue sobe, fica plana e volta a subir): busca em
grade, sem refinamento.

DESEMPATE. Onde `J` é plano (todos os cenários dentro da faixa), escolhe-se o `r` mais próximo de 1
entre os de `J` mínimo (tolerância relativa de 1e-9); persistindo o empate, o menor `r`.

SEM DADO REALIZADO. `decidir` só enxerga cenários, previstos e PLD de meses `<= origem`. O realizado
dos anos decididos fica em arquivos que a otimização não lê (a avaliação é da 6.3).

LEITURA CONGELADA. Filtra o `execucao_id` congelado, confere a execução e as impressões digitais por
origem contra `ml/congelado_6a.json` e falha se não baterem. Lê uma vez e grava parquet em
`data/cenarios_6a/` (fora do git); depois disso nada volta ao BigQuery.
"""

import argparse
import hashlib
import json
import sys
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from ml.cenarios_consumo import cvar_superior, horas_do_mes
from ml.custo import SPREAD_PADRAO, custo_anual, preco_do_contrato, volume_medio_mwm
from ml.registro import MODELO_VERSAO
from ml.validacao import HORIZONTES, somar_meses

RAIZ = Path(__file__).resolve().parents[1]
DIR_DADOS = RAIZ / "data" / "cenarios_6a"
ARQUIVO_CONGELADO = RAIZ / "ml" / "congelado_6a.json"
TETO_BYTES = 200 * 1024 * 1024
PISO_FATURADO = 10 * 1024 * 1024  # mínimo cobrado por tabela referenciada

# Critérios congelados (docs/decisoes.md, Sprint 6, Parte A; docs/planejamento/plano_sprint6a.md)
EXECUCAO_CONGELADA = "51cf99b073fe"
N_CENARIOS = 2000
SEMENTE = 0
METODO_BASE = "blocos"
LAMBDA = 0.5
ALFA = 0.95
BANDA = 0.10
PASSO_R = 0.0025
TOLERANCIA_EMPATE = 1e-9
ANOS_DECIDIDOS = range(2021, 2026)  # origens dez/2020 a dez/2024
# Linhas esperadas na execução congelada (metricas.md, idempotência da gravação)
LINHAS_ESPERADAS = {"consumo": 144_000, "pld": 288_000, "execucao": 6}

ARQUIVOS = (
    "execucao",
    "cenario_consumo",
    "cenario_pld",
    "previstos",
    "pld_mensal",
    "consumo_mensal",
    "pld_2020",
)
COLUNAS_DATA = {
    "execucao": ["origem"],
    "cenario_consumo": ["origem", "mes_alvo"],
    "cenario_pld": ["origem", "mes_alvo"],
    "previstos": ["origem"],
    "pld_mensal": ["mes"],
    "consumo_mensal": ["mes"],
}
# Dados que a OTIMIZAÇÃO usa (ex-ante) e dados só da AVALIAÇÃO (6.3)
EX_ANTE = ("execucao", "cenario_consumo", "cenario_pld", "previstos", "pld_mensal", "pld_2020")


class ErroDeCongelamento(RuntimeError):
    """Os dados lidos não são os congelados antes do backtest."""


# ---------------------------------------------------------------- grade e otimização


def limites_de_r(f: float, r_max: float | None = None) -> tuple[float, float]:
    """`[1/(1+f); 1/(1−f)]`. `r_max` só serve à sensibilidade (por exemplo, 1,2)."""
    if not 0 <= f < 1:
        raise ValueError(f"banda f deve estar em [0, 1): {f!r}")
    r_min = 1 / (1 + f)
    teto = 1 / (1 - f) if r_max is None else float(r_max)
    if teto < 1:
        raise ValueError("r_max deve ser pelo menos 1")
    return r_min, teto


def grade_de_r(f: float, passo: float = PASSO_R, r_max: float | None = None) -> np.ndarray:
    """Pontos de `r` de `passo` em `passo` entre os limites, mais `1` e os próprios limites."""
    if passo <= 0:
        raise ValueError("passo deve ser positivo")
    r_min, teto = limites_de_r(f, r_max)
    pontos = {r_min, 1.0, teto}
    k = 1
    while r_min + k * passo < teto - 1e-12:
        pontos.add(r_min + k * passo)
        k += 1
    return np.array(sorted({round(p, 12) for p in pontos}))


@dataclass(frozen=True)
class Otimizacao:
    grade: np.ndarray  # r
    esperados: np.ndarray  # E[custo] por r
    cvars: np.ndarray  # CVaR_α do custo por r
    objetivos: np.ndarray  # J por r
    indice: int  # posição de r*

    @property
    def r(self) -> float:
        return float(self.grade[self.indice])

    @property
    def j(self) -> float:
        return float(self.objetivos[self.indice])

    @property
    def esperado(self) -> float:
        return float(self.esperados[self.indice])

    @property
    def cvar(self) -> float:
        return float(self.cvars[self.indice])


def avaliar(
    consumo, pld, horas, v_mwm, f, preco, lam=LAMBDA, alfa=ALFA
) -> tuple[float, float, float]:
    """(E[custo], CVaR_α[custo], J) de um `V` sobre as matrizes cenários × 12 meses."""
    custos = custo_anual(consumo, v_mwm, horas, f, preco, pld)
    esperado = float(np.mean(custos))
    cvar = float(cvar_superior(custos.tolist(), alfa))
    return esperado, cvar, esperado + lam * cvar


def escolher_indice(grade: np.ndarray, objetivos: np.ndarray) -> int:
    """Índice do `J` mínimo; entre os empatados (tolerância relativa), o `r` mais próximo de 1 e,
    persistindo o empate, o menor `r`."""
    menor = float(objetivos.min())
    candidatos = np.flatnonzero(objetivos <= menor + TOLERANCIA_EMPATE * max(1.0, abs(menor)))
    return int(min(candidatos, key=lambda i: (abs(grade[i] - 1.0), grade[i])))


def otimizar(
    consumo,
    pld,
    horas,
    v_pont_mwm: float,
    f: float,
    preco: float,
    lam: float = LAMBDA,
    alfa: float = ALFA,
    passo: float = PASSO_R,
    r_max: float | None = None,
) -> Otimizacao:
    """Busca em grade do `r` que minimiza `J` (matrizes cenários × 12 meses)."""
    if lam < 0:
        raise ValueError("lambda não pode ser negativo")
    consumo, pld = np.asarray(consumo, dtype=float), np.asarray(pld, dtype=float)
    if consumo.shape != pld.shape or consumo.ndim != 2:
        raise ValueError("consumo e PLD devem ser matrizes cenários × meses do mesmo tamanho")
    if v_pont_mwm <= 0:
        raise ValueError("V_pont deve ser positivo")
    grade = grade_de_r(f, passo, r_max)
    medidas = np.array(
        [avaliar(consumo, pld, horas, r * v_pont_mwm, f, preco, lam, alfa) for r in grade]
    )
    objetivos = medidas[:, 2]
    return Otimizacao(
        grade, medidas[:, 0], medidas[:, 1], objetivos, escolher_indice(grade, objetivos)
    )


# ---------------------------------------------------------------- dados da origem


@dataclass(frozen=True)
class Dados:
    execucao: pd.DataFrame
    cenario_consumo: pd.DataFrame
    cenario_pld: pd.DataFrame
    previstos: pd.DataFrame
    pld_mensal: pd.DataFrame
    pld_2020: float  # PLD médio de 2020 do SE (semanal, ponderado pelas horas): 178,03
    consumo_mensal: pd.DataFrame | None = None  # realizado: só a avaliação (6.3) lê


def origens_de_decisao(dados: Dados) -> list[date]:
    """Dezembros de 2020 a 2024 que existem na execução congelada."""
    return sorted(o for o in dados.execucao["origem"] if o.month == 12 and 2020 <= o.year <= 2024)


def matrizes_da_origem(
    consumo: pd.DataFrame, pld: pd.DataFrame, origem: date, metodo: str, n: int
) -> tuple[np.ndarray, np.ndarray, list[date]]:
    """(consumo, PLD, meses-alvo): matrizes `n × 12` ordenadas por (cenário, horizonte), com as
    conferências de completude, de chave única e de que os meses-alvo são os 12 após a origem."""
    c = consumo[consumo["origem"] == origem]
    p = pld[(pld["origem"] == origem) & (pld["metodo"] == metodo)]
    meses = [somar_meses(origem, h) for h in HORIZONTES]
    esperado = [(s, h) for s in range(n) for h in HORIZONTES]
    saida = []
    for nome, tabela, valor in (("consumo", c, "consumo_mwh"), ("PLD", p, "pld_rs_mwh")):
        tabela = tabela.sort_values(["cenario", "horizonte"])
        chaves = list(zip(tabela["cenario"].tolist(), tabela["horizonte"].tolist(), strict=True))
        if chaves != esperado:
            raise ValueError(
                f"cenários de {nome} da origem {origem}: esperados {n}×12 pares únicos, "
                f"vieram {len(chaves)} linhas"
            )
        if tabela["mes_alvo"].tolist() != [meses[h - 1] for _, h in esperado]:
            raise ValueError(f"meses-alvo de {nome} da origem {origem} não são os 12 seguintes")
        valores = tabela[valor].to_numpy(dtype=float)
        if not np.all(np.isfinite(valores)):
            raise ValueError(f"valores não finitos em {nome} da origem {origem}")
        saida.append(valores.reshape(n, len(HORIZONTES)))
    return saida[0], saida[1], meses


def pld_medio_do_ano(pld_mensal: pd.DataFrame, origem: date, pld_2020: float) -> float:
    """PLD médio simples das horas do ano `t−1` (o ano da origem), só com meses `<= origem`.

    2020 vem do arquivo semanal; de 2021 em diante, `Σ(PLD simples do mês × horas) / Σ horas`, que é
    exatamente a média simples das horas do ano. Exige os 12 meses completos."""
    ano = origem.year
    if ano == 2020:
        return float(pld_2020)
    m = pld_mensal[(pld_mensal["mes"] <= origem) & (pld_mensal["mes"].map(lambda d: d.year) == ano)]
    if len(m) != 12 or not bool(m["mes_completo"].all()):
        raise ValueError(f"o PLD de {ano} não tem os 12 meses completos até {origem}")
    horas = m["horas"].to_numpy(dtype=float)
    return float((m["pld_medio_simples_rs_mwh"].to_numpy(dtype=float) * horas).sum() / horas.sum())


def v_previsto_mwm(previstos: pd.DataFrame, origem: date, k: float) -> tuple[float, list[float]]:
    """(V_pont em MWm, consumo previsto por mês em MWh): `k × previsto_mwmed × horas`."""
    p = previstos[previstos["origem"] == origem].sort_values("horizonte")
    if p["horizonte"].tolist() != list(HORIZONTES):
        raise ValueError(f"previsão da origem {origem} não tem os 12 horizontes")
    horas = [horas_do_mes(somar_meses(origem, h)) for h in HORIZONTES]
    consumo = [k * float(x) * h for x, h in zip(p["previsto_mwmed"], horas, strict=True)]
    return volume_medio_mwm(consumo, horas), consumo


@dataclass(frozen=True)
class Decisao:
    origem: date
    ano: int
    f: float
    preco: float
    v_pont_mwm: float
    otimizacao: Otimizacao

    @property
    def v_mwm(self) -> float:
        return self.otimizacao.r * self.v_pont_mwm


def decidir(
    origem: date,
    f: float,
    dados: Dados,
    lam: float = LAMBDA,
    alfa: float = ALFA,
    metodo: str = METODO_BASE,
    spread: float = SPREAD_PADRAO,
    passo: float = PASSO_R,
    r_max: float | None = None,
) -> Decisao:
    """Decisão da origem. Só usa cenários, previstos da origem e PLD de meses `<= origem`."""
    ex = dados.execucao[dados.execucao["origem"] == origem]
    if len(ex) != 1:
        raise ValueError(f"a origem {origem} não está (ou está duplicada) na execução")
    n, k = int(ex["n_cenarios"].iloc[0]), float(ex["k_consumo"].iloc[0])
    consumo, pld, meses = matrizes_da_origem(
        dados.cenario_consumo, dados.cenario_pld, origem, metodo, n
    )
    horas = [horas_do_mes(m) for m in meses]
    v_pont, _ = v_previsto_mwm(dados.previstos, origem, k)
    preco = preco_do_contrato(pld_medio_do_ano(dados.pld_mensal, origem, dados.pld_2020), spread)
    ot = otimizar(consumo, pld, horas, v_pont, f, preco, lam, alfa, passo, r_max)
    return Decisao(origem, origem.year + 1, f, preco, v_pont, ot)


# ---------------------------------------------------------------- congelamento


def impressao(df: pd.DataFrame, chaves: list[str], valor: str) -> str:
    """Impressão digital da tabela, independente da ordem das linhas (valores a 1e-9)."""
    d = df.sort_values(chaves)
    h = hashlib.sha256()
    for c in chaves:
        h.update("|".join(map(str, d[c].tolist())).encode())
    h.update(np.round(d[valor].to_numpy(dtype=float), 9).tobytes())
    return h.hexdigest()[:16]


CAMPOS_DA_EXECUCAO = (
    "erros_hash",
    "pld_hash",
    "pisos_hash",
    "codigo_hash",
    "n_vetores_consumo",
    "n_meses_pld",
    "n_blocos_pld",
)


def impressoes_da_origem(dados: Dados, origem: date) -> dict:
    ex = dados.execucao[dados.execucao["origem"] == origem].iloc[0]
    cons = dados.cenario_consumo[dados.cenario_consumo["origem"] == origem]
    pld = dados.cenario_pld[dados.cenario_pld["origem"] == origem]
    return {
        **{c: (ex[c].item() if hasattr(ex[c], "item") else ex[c]) for c in CAMPOS_DA_EXECUCAO},
        "impressao_consumo": impressao(cons, ["cenario", "horizonte"], "consumo_mwh"),
        "impressao_pld": {
            m: impressao(g, ["cenario", "horizonte"], "pld_rs_mwh")
            for m, g in pld.groupby("metodo")
        },
    }


def montar_congelado(dados: Dados) -> dict:
    ex = dados.execucao
    return {
        "execucao_id": EXECUCAO_CONGELADA,
        "modelo_versao": MODELO_VERSAO,
        "n_cenarios": int(ex["n_cenarios"].iloc[0]),
        "semente_base": int(ex["semente_base"].iloc[0]),
        "k_consumo": float(ex["k_consumo"].iloc[0]),
        "origens": {o.isoformat(): impressoes_da_origem(dados, o) for o in sorted(ex["origem"])},
    }


def verificar_estrutura(dados: Dados) -> None:
    """Conferências que não dependem do arquivo congelado (valem na 1ª leitura)."""
    ex = dados.execucao
    if len(ex) != LINHAS_ESPERADAS["execucao"] or ex["origem"].duplicated().any():
        raise ErroDeCongelamento(f"a execução tem {len(ex)} linhas (esperadas 6, sem repetição)")
    if set(ex["n_cenarios"]) != {N_CENARIOS} or set(ex["semente_base"]) != {SEMENTE}:
        raise ErroDeCongelamento("N ou semente diferentes dos congelados")
    if ex["k_consumo"].nunique() != 1 or ex["modelo_versao"].nunique() != 1:
        raise ErroDeCongelamento("k ou versão do modelo variam entre as origens")
    if len(dados.cenario_consumo) != LINHAS_ESPERADAS["consumo"]:
        raise ErroDeCongelamento(
            f"{len(dados.cenario_consumo)} linhas de consumo, esperadas 144.000"
        )
    if len(dados.cenario_pld) != LINHAS_ESPERADAS["pld"]:
        raise ErroDeCongelamento(f"{len(dados.cenario_pld)} linhas de PLD, esperadas 288.000")
    if abs(dados.pld_2020 - 178.03) > 0.005:
        raise ErroDeCongelamento(f"PLD médio de 2020 = {dados.pld_2020:.4f}, esperado 178,03")


def verificar_congelamento(dados: Dados, congelado: dict) -> None:
    """Falha se a execução, os hashes por origem ou as impressões dos cenários diferirem."""
    verificar_estrutura(dados)
    atual = montar_congelado(dados)
    if congelado.get("execucao_id") != EXECUCAO_CONGELADA:
        raise ErroDeCongelamento("o arquivo congelado não é da execução 51cf99b073fe")
    for campo in ("n_cenarios", "semente_base", "modelo_versao"):
        if atual[campo] != congelado[campo]:
            raise ErroDeCongelamento(f"{campo}: {atual[campo]!r} contra {congelado[campo]!r}")
    if abs(atual["k_consumo"] - congelado["k_consumo"]) > 1e-18:
        raise ErroDeCongelamento("k_consumo difere do congelado")
    if sorted(atual["origens"]) != sorted(congelado["origens"]):
        raise ErroDeCongelamento("as origens da execução diferem das congeladas")
    for origem, esperado in congelado["origens"].items():
        if atual["origens"][origem] != esperado:
            diferentes = sorted(
                c for c in esperado if atual["origens"][origem].get(c) != esperado[c]
            )
            raise ErroDeCongelamento(f"origem {origem}: difere em {', '.join(diferentes)}")


# ---------------------------------------------------------------- disco


def _normalizar_datas(nome: str, df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for c in COLUNAS_DATA.get(nome, []):
        df[c] = [pd.Timestamp(x).date() for x in df[c]]
    return df


def salvar_dados(tabelas: dict[str, pd.DataFrame], diretorio: Path = DIR_DADOS) -> dict[str, str]:
    diretorio.mkdir(parents=True, exist_ok=True)
    caminhos = {}
    for nome, df in tabelas.items():
        caminho = diretorio / f"{nome}.parquet"
        df.to_parquet(caminho, index=False)
        caminhos[nome] = hashlib.sha256(caminho.read_bytes()).hexdigest()[:16]
    return caminhos


def carregar_dados(diretorio: Path = DIR_DADOS, so_ex_ante: bool = False) -> Dados:
    """Lê os parquets. `so_ex_ante=True` não carrega o consumo realizado (a otimização não o vê)."""
    leitura = {}
    for nome in ARQUIVOS:
        if so_ex_ante and nome not in EX_ANTE:
            continue
        leitura[nome] = _normalizar_datas(nome, pd.read_parquet(diretorio / f"{nome}.parquet"))
    pld_2020 = float(leitura.pop("pld_2020")["pld_medio_2020"].iloc[0])
    return Dados(pld_2020=pld_2020, **leitura)


def ler_congelado(caminho: Path = ARQUIVO_CONGELADO) -> dict:
    if not caminho.exists():
        raise ErroDeCongelamento(
            f"{caminho.name} não existe: a primeira leitura deve usar --congelar"
        )
    return json.loads(caminho.read_text())


# ---------------------------------------------------------------- nuvem


def consultas(execucao_id: str = EXECUCAO_CONGELADA) -> dict[str, str]:
    """As 7 consultas da leitura. Tabelas de cenário: sempre filtradas pelo `execucao_id`."""
    filtro = f"execucao_id = '{execucao_id}'"
    return {
        "execucao": f"""SELECT origem, modelo_versao, n_cenarios, semente_base, calibracao,
            n_vetores_consumo, erros_hash, k_consumo, n_meses_pld, n_blocos_pld, pld_hash,
            pisos_hash, limites_assumidos, codigo_hash
            FROM `marts.fct_cenario_execucao` WHERE {filtro} ORDER BY origem""",
        "cenario_consumo": f"""SELECT origem, cenario, horizonte, mes_alvo, consumo_mwh
            FROM `marts.fct_cenario_consumo` WHERE {filtro}""",
        "cenario_pld": f"""SELECT origem, metodo, cenario, horizonte, mes_alvo, pld_rs_mwh
            FROM `marts.fct_cenario_pld` WHERE {filtro}""",
        "previstos": f"""SELECT origem, horizonte, previsto_mwmed
            FROM `marts.fct_erro_previsao_carga`
            WHERE modelo_versao = '{MODELO_VERSAO}' AND EXTRACT(MONTH FROM origem) = 12
              AND EXTRACT(YEAR FROM origem) BETWEEN 2020 AND 2024""",
        "pld_mensal": """SELECT mes, horas, horas_esperadas, mes_completo,
            CAST(pld_medio_simples_rs_mwh AS FLOAT64) AS pld_medio_simples_rs_mwh,
            CAST(pld_ponderado_rs_mwh AS FLOAT64) AS pld_ponderado_rs_mwh
            FROM `marts.fct_pld_ponderado_mensal` ORDER BY mes""",
        "consumo_mensal": """SELECT DATE_TRUNC(data_local, MONTH) AS mes,
            SUM(consumo_mwh) AS consumo_mwh, COUNT(*) AS horas
            FROM `marts.fct_consumo_horario`
            WHERE data_local BETWEEN DATE '2020-01-01' AND DATE '2025-12-31'
            GROUP BY mes ORDER BY mes""",
        "pld_2020": """WITH semanas AS (
              SELECT inicio_semana_utc, AVG(CAST(pld_rs_mwh AS FLOAT64)) AS pld,
                TIMESTAMP_DIFF(
                  LEAST(ANY_VALUE(fim_semana_utc), TIMESTAMP('2021-01-01', 'America/Sao_Paulo')),
                  GREATEST(inicio_semana_utc, TIMESTAMP('2020-01-01', 'America/Sao_Paulo')), HOUR
                ) AS horas
              FROM `marts.fct_pld_semanal`
              WHERE codigo_submercado = 'SE'
                AND fim_semana_utc > TIMESTAMP('2020-01-01', 'America/Sao_Paulo')
                AND inicio_semana_utc < TIMESTAMP('2021-01-01', 'America/Sao_Paulo')
              GROUP BY inicio_semana_utc)
            SELECT SUM(pld * horas) / SUM(horas) AS pld_medio_2020, SUM(horas) AS horas
            FROM semanas""",
    }


def _para_dataframe(linhas) -> pd.DataFrame:
    return pd.DataFrame([dict(r.items()) for r in linhas])


def ler(
    dry_run: bool,
    congelar: bool,
    diretorio: Path = DIR_DADOS,
    arquivo_congelado: Path = ARQUIVO_CONGELADO,
    gcp=None,
    cliente=None,
) -> int:
    if gcp is None:
        from ml.previsao import _cliente

        gcp, cliente = _cliente()
    sqls = consultas()
    if congelar and arquivo_congelado.exists() and not dry_run:
        raise ErroDeCongelamento(f"{arquivo_congelado.name} já existe: não se congela duas vezes")
    if not congelar and not dry_run:
        ler_congelado(arquivo_congelado)  # falha cedo, antes de gastar bytes

    inicio = time.perf_counter()
    medidas, tabelas = [], {}
    for nome, sql in sqls.items():
        t0 = time.perf_counter()
        r = gcp.executar_consulta(
            cliente, sql, max_bytes_faturados=TETO_BYTES, usar_cache=False, dry_run=dry_run
        )
        medidas.append(
            (nome, r.bytes_processados or 0, r.bytes_faturados, time.perf_counter() - t0)
        )
        if not dry_run:
            tabelas[nome] = _normalizar_datas(nome, _para_dataframe(r.linhas))
    print("consulta | bytes processados | faturados | s")
    for nome, proc, fat, s in medidas:
        piso = fat if fat is not None else max(proc, PISO_FATURADO)
        marca = "" if fat is not None else " (estimado: piso de 10 MiB por tabela)"
        print(f"{nome} | {proc:,} | {piso:,}{marca} | {s:.1f}".replace(",", "."))
    total_p = sum(m[1] for m in medidas)
    total_f = sum((m[2] if m[2] is not None else max(m[1], PISO_FATURADO)) for m in medidas)
    total = f"total: {total_p:,} processados; {total_f:,} faturados ({total_f / 1024**2:.1f} MiB)"
    print(total.replace(",", "."))
    if dry_run:
        print("dry-run: nada lido, nada gravado")
        return 0

    pld_2020 = tabelas.pop("pld_2020")
    if int(pld_2020["horas"].iloc[0]) != 8784:
        raise ErroDeCongelamento(
            f"2020 tem {pld_2020['horas'].iloc[0]} horas de PLD, esperadas 8.784"
        )
    dados = Dados(pld_2020=float(pld_2020["pld_medio_2020"].iloc[0]), **tabelas)
    if congelar:
        verificar_estrutura(dados)
        arquivo_congelado.write_text(
            json.dumps(montar_congelado(dados), indent=2, sort_keys=True) + "\n"
        )
        print(f"congelado em {arquivo_congelado.relative_to(RAIZ)} (commite este arquivo)")
    else:
        verificar_congelamento(dados, ler_congelado(arquivo_congelado))
        print("conferência com o congelado: ok")
    tabelas["pld_2020"] = pld_2020
    hashes = salvar_dados(tabelas, diretorio)
    (diretorio / "manifest.json").write_text(
        json.dumps(
            {
                "execucao_id": EXECUCAO_CONGELADA,
                "linhas": {n: len(t) for n, t in tabelas.items()},
                "hash_dos_arquivos": hashes,
                "bytes_processados": total_p,
                "bytes_faturados": total_f,
            },
            indent=2,
        )
        + "\n"
    )
    print(f"gravado em {diretorio.relative_to(RAIZ)}; tempo {time.perf_counter() - inicio:.1f}s")
    return 0


# ---------------------------------------------------------------- linha de comando


def otimizar_cli(f: float, lam: float, alfa: float, metodo: str, r_max: float | None) -> int:
    dados = carregar_dados(so_ex_ante=True)
    verificar_congelamento(dados, ler_congelado())
    print("origem | ano | P_t | V_pont (MWm) | r* | V* (MWm) | E[custo] | CVaR | J")
    linhas = []
    for origem in origens_de_decisao(dados):
        d = decidir(origem, f, dados, lam, alfa, metodo, r_max=r_max)
        o = d.otimizacao
        print(
            f"{origem:%Y-%m} | {d.ano} | {d.preco:.2f} | {d.v_pont_mwm:.6f} | {o.r:.4f} | "
            f"{d.v_mwm:.6f} | {o.esperado:,.0f} | {o.cvar:,.0f} | {o.j:,.0f}".replace(",", ".")
        )
        for r, e, c, j in zip(o.grade, o.esperados, o.cvars, o.objetivos, strict=True):
            linhas.append({"ano": d.ano, "r": r, "esperado": e, "cvar": c, "j": j})
    destino = DIR_DADOS / f"otimizacao_ex_ante_f{round(f * 100)}_{metodo}.csv"
    pd.DataFrame(linhas).to_csv(destino, index=False)
    print(f"curva J(r) em {destino.relative_to(RAIZ)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="comando", required=True)
    s = sub.add_parser("ler", help="lê o BigQuery uma vez e grava parquet")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--congelar", action="store_true", help="1ª leitura: grava ml/congelado_6a.json")
    o = sub.add_parser("otimizar", help="decisão ex-ante de cada origem, só com o disco")
    o.add_argument("--f", type=float, default=BANDA)
    o.add_argument("--lam", type=float, default=LAMBDA)
    o.add_argument("--alfa", type=float, default=ALFA)
    o.add_argument("--metodo", default=METODO_BASE, choices=("blocos", "simples"))
    o.add_argument("--r-max", type=float, default=None)
    a = ap.parse_args(argv)
    if a.comando == "ler":
        return ler(a.dry_run, a.congelar)
    return otimizar_cli(a.f, a.lam, a.alfa, a.metodo, a.r_max)


if __name__ == "__main__":
    sys.exit(main())
