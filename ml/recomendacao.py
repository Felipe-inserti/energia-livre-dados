"""`marts.fct_recomendacao_contrato` (6.5): volume por sensibilidade, origem e estratégia.

    uv run --env-file .env python -m ml.recomendacao gravar --dry-run   # monta e valida; não grava
    uv run --env-file .env python -m ml.recomendacao gravar             # MERGE idempotente
    uv run --env-file .env python -m ml.recomendacao producao --dry-run # origem mais recente
    uv run --env-file .env python -m ml.recomendacao producao           # grava só as 3 linhas dela

Plano: `docs/planejamento/plano_sprint6b.md`, seção 7 (decisões B12 e B13).
- **Chave natural:** (`sens_id`, `origem`, `estrategia`). Grão: uma decisão de volume.
- **`backtest`:** o caso base e as 13 sensibilidades (14 × 5 origens × 3 estratégias = 210 linhas),
  lidas dos CSV versionados e do log (0 byte de BigQuery); inclui o custo realizado e o PIT.
- **Produção:** só o caso base. Origem de **dezembro** gera `tipo = producao` (`ano_contrato` =
  ano da origem + 1; a janela é o ano-calendário). **Qualquer outra origem, como a 2026-09, gera
  `tipo = previa`**: janela móvel de 12 meses, `ano_contrato` nulo, nunca rotulada como o contrato
  de um ano-calendário. Sem custo realizado em nenhum dos dois.
- **`P` generalizado:** PLD médio simples ponderado pelas horas dos **12 meses fechados até a
  origem** + spread. Para uma origem de dezembro é exatamente "o ano `t−1`" do caso base (teste).
  A ingênua da prévia usa o consumo realizado dos mesmos 12 meses.
- `janela_inicio` e `janela_fim` são o primeiro dia do primeiro e do último mês da janela.

`producao` (Sprint 6, Parte C1): a cadeia mensal. Escolhe a **origem de produção mais recente que
tem previsão E cenários**, lê tudo do BigQuery (nada de parquet local), decide com o caso base e
grava **só as 3 linhas** dela (`tipo` = `producao` ou `previa`). Nunca escreve linhas de backtest: o
SQL só olha execuções de origens posteriores a 2024-12 e a validação recusa qualquer outra. Emite
**aviso de defasagem** quando a previsão mais recente não tem cenários, ou quando o último mês
fechado já passou da previsão.
"""

import argparse
import sys
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from ml import backtest as bt
from ml.cenarios import ORIGENS_DE_BACKTEST
from ml.cenarios_consumo import hash_curto, horas_do_mes, k_do_dbt
from ml.custo import SPREAD_PADRAO, preco_do_contrato, volume_medio_mwm
from ml.medida_bytes import ContaBytes
from ml.otimizacao import (
    ALFA,
    BANDA,
    DIR_DADOS,
    EXECUCAO_CONGELADA,
    LAMBDA,
    METODO_BASE,
    PASSO_R,
    Dados,
    avaliar,
    carregar_dados,
    matrizes_da_origem,
    otimizar,
    v_previsto_mwm,
)
from ml.registro import MODELO_VERSAO
from ml.sensibilidades import (
    IDS,
    LOG,
    RESULTADOS,
    buscar,
    criterios,
    criterios_do_caso_base,
    ler_saidas,
)
from ml.validacao import HORIZONTES, somar_meses

TABELA = "marts.fct_recomendacao_contrato"
CHAVE = ("sens_id", "origem", "estrategia")
ESQUEMA = [
    ("sens_id", "STRING"),
    ("origem", "DATE"),
    ("estrategia", "STRING"),
    ("tipo", "STRING"),
    ("ano_contrato", "INT64"),
    ("janela_inicio", "DATE"),
    ("janela_fim", "DATE"),
    ("v_mwm", "FLOAT64"),
    ("razao_v_pontual", "FLOAT64"),
    ("preco_contrato_rs_mwh", "FLOAT64"),
    ("banda_f", "FLOAT64"),
    ("spread_rs_mwh", "FLOAT64"),
    ("lambda", "FLOAT64"),
    ("alfa", "FLOAT64"),
    ("custo_esperado_rs", "FLOAT64"),
    ("cvar_rs", "FLOAT64"),
    ("objetivo_j_rs", "FLOAT64"),
    ("custo_realizado_rs", "FLOAT64"),
    ("descoberto_mwh", "FLOAT64"),
    ("sobrando_mwh", "FLOAT64"),
    ("meses_fora_da_faixa", "INT64"),
    ("pit_custo_realizado", "FLOAT64"),
    ("execucao_id", "STRING"),
    ("limites_assumidos", "BOOL"),
    ("config_hash", "STRING"),
    ("preregistro", "STRING"),
    ("commit", "STRING"),
    ("codigo_hash", "STRING"),
    ("gerado_em", "TIMESTAMP"),
]
COLUNAS = [n for n, _ in ESQUEMA]
ESTRATEGIAS = bt.ESTRATEGIAS
TIPOS = ("backtest", "producao", "previa")
COLUNAS_REALIZADO = (
    "custo_realizado_rs",
    "descoberto_mwh",
    "sobrando_mwh",
    "meses_fora_da_faixa",
    "pit_custo_realizado",
)
LINHAS_BACKTEST = (len(IDS) + 1) * 5 * len(ESTRATEGIAS)  # 210
CODIGO = ("ml/recomendacao.py", "ml/sensibilidades.py", "ml/otimizacao.py", "ml/custo.py")


# ---------------------------------------------------------------- P e V por janela de 12 meses


def janela_de_12_meses(origem: date) -> list[date]:
    """Os 12 meses fechados até a origem (o ano `t−1` quando a origem é dezembro)."""
    return [somar_meses(origem, k) for k in range(-11, 1)]


def pld_medio_12m(pld_mensal: pd.DataFrame, origem: date, pld_2020: float) -> float:
    """PLD médio simples das horas dos 12 meses até a origem, só com meses `<= origem`.

    Para uma origem de dezembro dá o mesmo que `ml.otimizacao.pld_medio_do_ano` (inclusive 2020,
    que vem do arquivo semanal). Exige os 12 meses completos."""
    if origem.month == 12 and origem.year == 2020:
        return float(pld_2020)
    meses = janela_de_12_meses(origem)
    m = pld_mensal[pld_mensal["mes"].isin(meses)].sort_values("mes")
    if m["mes"].tolist() != meses or not bool(m["mes_completo"].all()):
        raise ValueError(f"o PLD dos 12 meses até {origem} não está completo")
    horas = m["horas"].to_numpy(dtype=float)
    return float((m["pld_medio_simples_rs_mwh"].to_numpy(dtype=float) * horas).sum() / horas.sum())


def v_ingenua_12m(consumo_mensal: pd.DataFrame, origem: date) -> float:
    """Consumo médio (MWm) dos 12 meses até a origem: a ingênua de uma janela móvel."""
    meses = janela_de_12_meses(origem)
    c = consumo_mensal[consumo_mensal["mes"].isin(meses)].sort_values("mes")
    if c["mes"].tolist() != meses:
        raise ValueError(f"o consumo dos 12 meses até {origem} não está completo")
    horas = [horas_do_mes(m) for m in meses]
    if [int(h) for h in c["horas"]] != horas:
        raise ValueError(f"o consumo dos 12 meses até {origem} tem horas faltando")
    return volume_medio_mwm(c["consumo_mwh"].to_numpy(dtype=float), horas)


# ---------------------------------------------------------------- linhas do backtest


def _proveniencia(commit: str, codigo_hash: str, agora: datetime) -> dict:
    return {
        "commit": commit,
        "codigo_hash": codigo_hash,
        "gerado_em": agora.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def linhas_backtest(
    saidas: dict, ids_de_execucao: dict, cabecalhos: dict, prov: dict
) -> pd.DataFrame:
    """As 210 linhas do backtest. `saidas`: `ler_saidas`; `ids_de_execucao` e `cabecalhos` por
    `sens_id` (`config_hash`, `preregistro`, `commit` vêm do log)."""
    linhas = []
    for sens_id in ("caso_base", *IDS):
        crit = criterios_do_caso_base() if sens_id == "caso_base" else criterios(buscar(sens_id))
        anual = saidas[sens_id]["anual"]
        for r in anual.itertuples(index=False):
            ano = int(r.ano)
            linhas.append(
                {
                    "sens_id": sens_id,
                    "origem": date(ano - 1, 12, 1),
                    "estrategia": r.estrategia,
                    "tipo": "backtest",
                    "ano_contrato": ano,
                    "janela_inicio": date(ano, 1, 1),
                    "janela_fim": date(ano, 12, 1),
                    "v_mwm": float(r.v_mwm),
                    "razao_v_pontual": float(r.razao_v_pontual),
                    "preco_contrato_rs_mwh": float(r.preco_contrato_rs_mwh),
                    "banda_f": float(crit["f"]),
                    "spread_rs_mwh": float(crit["spread_rs_mwh"]),
                    "lambda": float(crit["lambda"]),
                    "alfa": float(crit["alfa"]),
                    "custo_esperado_rs": float(r.esperado_ex_ante_rs),
                    "cvar_rs": float(r.cvar_ex_ante_rs),
                    "objetivo_j_rs": float(
                        r.esperado_ex_ante_rs + crit["lambda"] * r.cvar_ex_ante_rs
                    ),
                    "custo_realizado_rs": float(r.custo_rs),
                    "descoberto_mwh": float(r.descoberto_mwh),
                    "sobrando_mwh": float(r.sobrando_mwh),
                    "meses_fora_da_faixa": int(r.meses_fora_da_faixa),
                    "pit_custo_realizado": float(r.pit_custo_realizado),
                    "execucao_id": ids_de_execucao[sens_id],
                    "limites_assumidos": False,
                    **cabecalhos[sens_id],
                    **prov,
                }
            )
    return pd.DataFrame(linhas, columns=COLUNAS)


def cabecalhos_do_log(log_sens: list[dict], log_base: list[dict]) -> tuple[dict, dict]:
    """({sens_id: execucao_id}, {sens_id: config_hash, preregistro}) a partir dos dois logs."""
    base = next(e for e in log_base if e.get("evento") == "caso_base" and e.get("numero") == 1)
    ids = {"caso_base": EXECUCAO_CONGELADA}
    cab = {"caso_base": {"config_hash": base["config_hash"], "preregistro": base["preregistro"]}}
    for e in log_sens:
        if e.get("evento") == "sensibilidade":
            ids[e["sens_id"]] = e["execucao_id"]
            cab[e["sens_id"]] = {"config_hash": e["config_hash"], "preregistro": e["preregistro"]}
    faltam = {"caso_base", *IDS} - set(ids)
    if faltam:
        raise ValueError(f"o log não tem: {sorted(faltam)}")
    return ids, cab


# ---------------------------------------------------------------- produção (caso base)


def linhas_producao(
    dados: Dados,
    origem: date,
    previsto_mwmed: list[float],
    consumo_mensal: pd.DataFrame,
    execucao_id: str,
    cabecalho: dict,
    prov: dict,
    f: float = BANDA,
    lam: float = LAMBDA,
    alfa: float = ALFA,
    spread: float = SPREAD_PADRAO,
    metodo: str = METODO_BASE,
) -> pd.DataFrame:
    """As 3 linhas (ingênua, pontual, otimizada) de uma origem de produção, só com o caso base.

    Origem de dezembro: `producao` (ano-calendário seguinte). Outra origem: `previa` (janela móvel,
    sem ano). Os cenários vêm da execução congelada; a previsão de produção, de `previsto_mwmed`."""
    ex = dados.execucao[dados.execucao["origem"] == origem]
    if len(ex) != 1:
        raise ValueError(f"a origem {origem} não está (ou está duplicada) na execução")
    n, k = int(ex["n_cenarios"].iloc[0]), float(ex["k_consumo"].iloc[0])
    consumo, pld, meses = matrizes_da_origem(
        dados.cenario_consumo, dados.cenario_pld, origem, metodo, n
    )
    horas = [horas_do_mes(m) for m in meses]
    prev = pd.DataFrame(
        {"origem": origem, "horizonte": list(HORIZONTES), "previsto_mwmed": list(previsto_mwmed)}
    )
    v_pont, _ = v_previsto_mwm(prev, origem, k)
    pld_dados = dados.pld_mensal[dados.pld_mensal["mes"] <= origem]
    preco = preco_do_contrato(pld_medio_12m(pld_dados, origem, dados.pld_2020), spread)
    ot = otimizar(consumo, pld, horas, v_pont, f, preco, lam, alfa, PASSO_R)
    volumes = {
        "ingenua": v_ingenua_12m(consumo_mensal[consumo_mensal["mes"] <= origem], origem),
        "pontual": v_pont,
        "otimizada": ot.r * v_pont,
    }
    dezembro = origem.month == 12
    linhas = []
    for e in ESTRATEGIAS:
        esperado, cvar, j = avaliar(consumo, pld, horas, volumes[e], f, preco, lam, alfa)
        linhas.append(
            {
                "sens_id": "caso_base",
                "origem": origem,
                "estrategia": e,
                "tipo": "producao" if dezembro else "previa",
                "ano_contrato": origem.year + 1 if dezembro else None,
                "janela_inicio": meses[0],
                "janela_fim": meses[-1],
                "v_mwm": volumes[e],
                "razao_v_pontual": volumes[e] / v_pont,
                "preco_contrato_rs_mwh": preco,
                "banda_f": f,
                "spread_rs_mwh": spread,
                "lambda": lam,
                "alfa": alfa,
                "custo_esperado_rs": esperado,
                "cvar_rs": cvar,
                "objetivo_j_rs": j,
                **{c: None for c in COLUNAS_REALIZADO},
                "execucao_id": execucao_id,
                "limites_assumidos": bool(ex["limites_assumidos"].iloc[0]),
                **cabecalho,
                **prov,
            }
        )
    return pd.DataFrame(linhas, columns=COLUNAS)


# ---------------------------------------------------------------- validação e carga


def validar(df: pd.DataFrame, com_backtest: bool = True) -> None:
    """Os testes da tabela, antes de gravar (chave, domínios, nulos coerentes, contagem)."""
    if df.duplicated(list(CHAVE)).any():
        raise ValueError("a chave (sens_id, origem, estrategia) tem duplicatas")
    if not set(df["estrategia"]) <= set(ESTRATEGIAS):
        raise ValueError("estratégia fora da lista")
    if not set(df["tipo"]) <= set(TIPOS):
        raise ValueError("tipo fora da lista")
    for c in COLUNAS:
        if c not in {"ano_contrato", *COLUNAS_REALIZADO} and df[c].isna().any():
            raise ValueError(f"nulo inesperado em {c}")
    bt_ = df["tipo"] == "backtest"
    if df.loc[bt_, list(COLUNAS_REALIZADO)].isna().any().any():
        raise ValueError("backtest sem custo realizado")
    if df.loc[~bt_, list(COLUNAS_REALIZADO)].notna().any().any():
        raise ValueError("custo realizado fora do backtest")
    if (df["ano_contrato"].isna() != (df["tipo"] == "previa")).any():
        raise ValueError("ano_contrato é nulo exatamente na prévia")
    if ((df["tipo"] == "producao") != df["origem"].map(lambda d: d.month == 12) & ~bt_).any():
        raise ValueError("só origem de dezembro gera produção")
    if com_backtest and int(bt_.sum()) != LINHAS_BACKTEST:
        raise ValueError(f"{int(bt_.sum())} linhas de backtest, esperadas {LINHAS_BACKTEST}")


def linhas_para_carga(df: pd.DataFrame) -> list[dict]:
    """Registros JSON (data em ISO, NaN e None como nulo, inteiros como int)."""
    registros = []
    for r in df.to_dict("records"):
        reg = {}
        for n, t in ESQUEMA:
            v = r[n]
            if v is None or (isinstance(v, float) and np.isnan(v)) or v is pd.NA:
                reg[n] = None
            elif t == "DATE":
                reg[n] = v.isoformat()
            elif t == "INT64":
                reg[n] = int(v)
            elif t == "BOOL":
                reg[n] = bool(v)
            else:
                reg[n] = v
        registros.append(reg)
    return registros


# ---------------------------------------------------------------- nuvem


def _sql_consumo_12m(origem: date) -> str:
    inicio = janela_de_12_meses(origem)[0]
    fim = somar_meses(origem, 1)
    return f"""SELECT DATE_TRUNC(data_local, MONTH) AS mes, SUM(consumo_mwh) AS consumo_mwh,
        COUNT(*) AS horas FROM `marts.fct_consumo_horario`
        WHERE data_local >= DATE '{inicio.isoformat()}' AND data_local < DATE '{fim.isoformat()}'
        GROUP BY mes ORDER BY mes"""


def montar(dry_run: bool, resultados: Path = RESULTADOS, agora=lambda: datetime.now(UTC)) -> int:
    from ml.cenarios import gravar_medido
    from ml.cenarios_consumo import previstos_de_producao
    from ml.otimizacao import _normalizar_datas
    from ml.previsao import _cliente, _consulta, hash_blob_git, ler_commit

    t0 = time.perf_counter()
    raiz = bt.RAIZ
    prov = _proveniencia(
        ler_commit(raiz),
        hash_curto({c: hash_blob_git(raiz / c) for c in CODIGO}),
        agora(),
    )
    log_sens, log_base = bt.ler_log(LOG), bt.ler_log(bt.LOG)
    ids, cab = cabecalhos_do_log(log_sens, log_base)
    backtest = linhas_backtest(ler_saidas(resultados), ids, cab, prov)
    gcp, cliente = _cliente()
    gcp = ContaBytes(gcp)
    origem, previstos = previstos_de_producao(gcp, cliente)
    consumo = _normalizar_datas(
        "consumo_mensal",
        pd.DataFrame(
            [dict(r.items()) for r in _consulta(gcp, cliente, _sql_consumo_12m(origem)).linhas]
        ),
    )
    dados = carregar_dados(DIR_DADOS)
    k_ok = abs(float(dados.execucao["k_consumo"].iloc[0]) - k_do_dbt()) < 1e-18
    if not k_ok:
        raise ValueError("o k do dbt difere do da execução congelada")
    producao = linhas_producao(
        dados, origem, previstos, consumo, EXECUCAO_CONGELADA, cab["caso_base"], prov
    )
    df = pd.concat([backtest, producao], ignore_index=True)
    validar(df)
    print(
        f"{len(backtest)} linhas de backtest + {len(producao)} de {producao['tipo'].iloc[0]} "
        f"(origem {origem:%Y-%m}, janela {producao['janela_inicio'].iloc[0]:%Y-%m} a "
        f"{producao['janela_fim'].iloc[0]:%Y-%m}); validação ok; {time.perf_counter() - t0:.1f}s"
    )
    print(
        producao[
            [
                "estrategia",
                "tipo",
                "v_mwm",
                "razao_v_pontual",
                "preco_contrato_rs_mwh",
                "custo_esperado_rs",
                "cvar_rs",
            ]
        ].to_string(index=False)
    )
    print(f"leitura do BigQuery: {gcp.linha(com_estimativa=dry_run)}")
    if dry_run:
        print(
            f"dry-run: nada gravado. A gravação seria 1 MERGE de {len(df)} linhas na tabela nova "
            "(ESTIMATIVA pelo piso de 10 MiB por tabela: ~20 MiB faturados, não medida)"
        )
        return 0
    m = gravar_medido(gcp, cliente, linhas_para_carga(df), TABELA, ESQUEMA, CHAVE)
    print(
        f"{m['tabela']}: {m['linhas']} linhas; carga {m['s_carga']:.1f}s, "
        f"MERGE {m['s_merge']:.1f}s, "
        f"{m['bytes_faturados']:,} bytes faturados".replace(",", ".")
    )
    return 0


# ------------------------------------------------------------ cadeia mensal: origem mais recente


class ErroDeProducao(RuntimeError):
    """A cadeia de produção não pode seguir (sem cenários, origem de backtest, linha errada)."""


def _indice_de_mes(d: date) -> int:
    return d.year * 12 + d.month


def escolher_origem(origens_previsao: list[date], execucoes: list[dict]) -> date:
    """A origem de produção mais recente que tem previsão **e** cenários, posterior ao backtest."""
    com_cenarios = {e["origem"] for e in execucoes}
    candidatas = sorted(
        o for o in set(origens_previsao) & com_cenarios if o > max(ORIGENS_DE_BACKTEST)
    )
    if not candidatas:
        raise ErroDeProducao(
            "nenhuma origem de produção tem previsão e cenários; rode "
            "`python -m ml.cenarios gerar-producao` para a origem mais recente"
        )
    return candidatas[-1]


def escolher_execucao(execucoes: list[dict], origem: date) -> str:
    """O `execucao_id` mais recente (por `gerado_em`; empate, o maior id) da origem."""
    da_origem = [e for e in execucoes if e["origem"] == origem]
    if not da_origem:
        raise ErroDeProducao(f"não há cenários gravados para a origem {origem:%Y-%m}")
    return max(da_origem, key=lambda e: (str(e["gerado_em"]), e["execucao_id"]))["execucao_id"]


def aviso_de_defasagem(
    origem_usada: date, ultima_previsao: date, ultimo_mes_fechado: date
) -> list[str]:
    """Avisos (vazio se tudo em dia): a prévia é da `origem_usada`; a previsão e o mês fechado podem
    estar à frente."""
    avisos = []
    if ultima_previsao > origem_usada:
        d = _indice_de_mes(ultima_previsao) - _indice_de_mes(origem_usada)
        avisos.append(
            f"AVISO DE DEFASAGEM: a previsão mais recente é de {ultima_previsao:%Y-%m}, mas não há "
            f"cenários para ela; a prévia é da origem {origem_usada:%Y-%m} ({d} mês(es) atrás). "
            "Rode `python -m ml.cenarios gerar-producao`."
        )
    if ultimo_mes_fechado > ultima_previsao:
        d = _indice_de_mes(ultimo_mes_fechado) - _indice_de_mes(ultima_previsao)
        avisos.append(
            f"AVISO DE DEFASAGEM: o último mês fechado é {ultimo_mes_fechado:%Y-%m}, mas a "
            f"previsão de produção mais recente é de {ultima_previsao:%Y-%m} ({d} mês(es) atrás). "
            "Rode `python -m ml.previsao gerar` (a DAG o faz quando o mês fecha)."
        )
    return avisos


def validar_somente_producao(df: pd.DataFrame) -> None:
    """Nenhuma linha de backtest: só o caso base, `producao`/`previa`, 3 estratégias, 1 origem."""
    if set(df["sens_id"]) != {"caso_base"}:
        raise ErroDeProducao("a cadeia de produção só escreve o caso base")
    if not set(df["tipo"]) <= {"producao", "previa"}:
        raise ErroDeProducao("a cadeia de produção não escreve linhas de backtest")
    if df["origem"].nunique() != 1 or len(df) != len(ESTRATEGIAS):
        raise ErroDeProducao("a cadeia de produção escreve exatamente 3 linhas de uma origem")
    if set(df["origem"]) & set(ORIGENS_DE_BACKTEST):
        raise ErroDeProducao("a origem é do backtest: nada é gravado")
    if sorted(df["estrategia"]) != sorted(ESTRATEGIAS):
        raise ErroDeProducao("faltam estratégias")


@dataclass(frozen=True)
class Inicio:
    origens_previsao: list[date]
    execucoes: list[dict]  # execucao_id, origem, gerado_em (só origens após o backtest)
    ultimo_mes_fechado: date


@dataclass(frozen=True)
class LeituraDaOrigem:
    dados: Dados
    previsto_mwmed: list[float]
    consumo_mensal: pd.DataFrame


def _linhas(gcp, cliente, sql: str) -> list[dict]:
    from ml.previsao import _consulta

    return [dict(r.items()) for r in _consulta(gcp, cliente, sql).linhas]


def ler_inicio(gcp, cliente) -> Inicio:
    """Origens com previsão, execuções de cenário posteriores ao backtest e o último mês fechado."""
    from ml.previsao import ler_serie

    origens = _linhas(
        gcp,
        cliente,
        f"SELECT DISTINCT origem FROM `marts.fct_previsao_carga` "
        f"WHERE modelo_versao = '{MODELO_VERSAO}' AND tipo = 'producao' ORDER BY origem",
    )
    # o filtro `origem > último mês do backtest` mantém as 5 origens do backtest fora da leitura
    fim_backtest = max(ORIGENS_DE_BACKTEST).isoformat()
    execucoes = _linhas(
        gcp,
        cliente,
        "SELECT execucao_id, origem, gerado_em FROM `marts.fct_cenario_execucao` "
        f"WHERE origem > DATE '{fim_backtest}'",
    )
    _, ultimo_fechado = ler_serie(gcp, cliente)
    return Inicio([r["origem"] for r in origens], execucoes, ultimo_fechado)


def ler_da_origem(gcp, cliente, origem: date, execucao_id: str) -> LeituraDaOrigem:
    from ml.otimizacao import _normalizar_datas, consultas

    filtro = f"execucao_id = '{execucao_id}' AND origem = DATE '{origem.isoformat()}'"
    execucao = _linhas(
        gcp,
        cliente,
        "SELECT origem, modelo_versao, n_cenarios, semente_base, calibracao, n_vetores_consumo, "
        "erros_hash, k_consumo, n_meses_pld, n_blocos_pld, pld_hash, pisos_hash, "
        f"limites_assumidos, codigo_hash FROM `marts.fct_cenario_execucao` WHERE {filtro}",
    )
    consumo = _linhas(
        gcp,
        cliente,
        "SELECT origem, cenario, horizonte, mes_alvo, consumo_mwh "
        f"FROM `marts.fct_cenario_consumo` WHERE {filtro}",
    )
    pld = _linhas(
        gcp,
        cliente,
        "SELECT origem, metodo, cenario, horizonte, mes_alvo, pld_rs_mwh "
        f"FROM `marts.fct_cenario_pld` WHERE {filtro} AND metodo = '{METODO_BASE}'",
    )
    previsao = _linhas(
        gcp,
        cliente,
        "SELECT horizonte, previsao_mwmed FROM `marts.fct_previsao_carga` "
        f"WHERE modelo_versao = '{MODELO_VERSAO}' AND tipo = 'producao' "
        f"AND origem = DATE '{origem.isoformat()}' ORDER BY horizonte",
    )
    if [r["horizonte"] for r in previsao] != list(HORIZONTES):
        raise ErroDeProducao(f"a previsão da origem {origem:%Y-%m} não tem os 12 horizontes")
    pld_mensal = _linhas(gcp, cliente, consultas()["pld_mensal"])
    consumo_mensal = _linhas(gcp, cliente, _sql_consumo_12m(origem))
    dados = Dados(
        execucao=_normalizar_datas("execucao", pd.DataFrame(execucao)),
        cenario_consumo=_normalizar_datas("cenario_consumo", pd.DataFrame(consumo)),
        cenario_pld=_normalizar_datas("cenario_pld", pd.DataFrame(pld)),
        previstos=pd.DataFrame(),
        pld_mensal=_normalizar_datas("pld_mensal", pd.DataFrame(pld_mensal)),
        pld_2020=0.0,
    )
    return LeituraDaOrigem(
        dados,
        [float(r["previsao_mwmed"]) for r in previsao],
        _normalizar_datas("consumo_mensal", pd.DataFrame(consumo_mensal)),
    )


def cabecalho_do_caso_base(log_base: Path | None = None) -> dict:
    """`config_hash` e `preregistro` do caso base (a prévia usa a regra dele), do log versionado."""
    entradas = bt.ler_log(log_base or bt.LOG)
    base = next(e for e in entradas if e.get("evento") == "caso_base" and e.get("numero") == 1)
    return {"config_hash": base["config_hash"], "preregistro": base["preregistro"]}


def producao(
    dry_run: bool,
    gcp=None,
    cliente=None,
    ler_o_inicio=ler_inicio,
    ler_a_origem=ler_da_origem,
    gravar=None,
    prov: dict | None = None,
    cabecalho: dict | None = None,
    agora=lambda: datetime.now(UTC),
) -> int:
    """A origem de produção mais recente com previsão e cenários: decide e grava 3 linhas."""
    t0 = time.perf_counter()
    if gcp is None:
        from ml.previsao import _cliente

        gcp, cliente = _cliente()
    gcp = ContaBytes(gcp)
    inicio = ler_o_inicio(gcp, cliente)
    origem = escolher_origem(inicio.origens_previsao, inicio.execucoes)
    execucao_id = escolher_execucao(inicio.execucoes, origem)
    ultima_previsao = max(inicio.origens_previsao)
    avisos = aviso_de_defasagem(origem, ultima_previsao, inicio.ultimo_mes_fechado)
    for a in avisos:
        print(a)
    leitura = ler_a_origem(gcp, cliente, origem, execucao_id)
    if prov is None:
        from ml.previsao import hash_blob_git, ler_commit

        prov = _proveniencia(
            ler_commit(bt.RAIZ),
            hash_curto({c: hash_blob_git(bt.RAIZ / c) for c in CODIGO}),
            agora(),
        )
    df = linhas_producao(
        leitura.dados,
        origem,
        leitura.previsto_mwmed,
        leitura.consumo_mensal,
        execucao_id,
        cabecalho or cabecalho_do_caso_base(),
        prov,
    )
    validar(df, com_backtest=False)
    validar_somente_producao(df)
    print(
        f"origem {origem:%Y-%m} ({df['tipo'].iloc[0]}), execucao_id {execucao_id}, janela "
        f"{df['janela_inicio'].iloc[0]:%Y-%m} a {df['janela_fim'].iloc[0]:%Y-%m}; "
        f"P = R$ {df['preco_contrato_rs_mwh'].iloc[0]:,.2f}/MWh; "
        f"limites assumidos: {bool(df['limites_assumidos'].iloc[0])}; "
        f"{time.perf_counter() - t0:.1f}s".replace(",", "X")
        .replace(".", ",")
        .replace("X", ".")
    )
    print(
        df[["estrategia", "v_mwm", "razao_v_pontual", "custo_esperado_rs", "cvar_rs"]].to_string(
            index=False
        )
    )
    print(f"leitura do BigQuery: {gcp.linha(com_estimativa=dry_run)}")
    if dry_run:
        print(
            "dry-run: nada gravado. A gravação seria 1 MERGE de 3 linhas "
            "(ESTIMATIVA pelo piso de 10 MiB por tabela: ~20 MiB faturados, não medida)"
        )
        return 0
    if gravar is None:
        from ml.cenarios import gravar_medido as gravar
    m = gravar(gcp, cliente, linhas_para_carga(df), TABELA, ESQUEMA, CHAVE)
    print(
        f"{m['tabela']}: {m['linhas']} linhas; carga {m['s_carga']:.1f}s, "
        f"MERGE {m['s_merge']:.1f}s, {m['bytes_faturados']:,} bytes faturados (job)".replace(
            ",", "."
        )
    )
    for a in avisos:
        print(a)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="comando", required=True)
    g = sub.add_parser("gravar", help="monta, valida e grava (MERGE)")
    g.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("producao", help="a origem de produção mais recente (cadeia mensal)")
    p.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    if a.comando == "producao":
        try:
            return producao(a.dry_run)
        except ErroDeProducao as erro:
            print(f"ABORTADO, nada foi gravado: {erro}", file=sys.stderr)
            return 2
    return montar(a.dry_run)


if __name__ == "__main__":
    sys.exit(main())
