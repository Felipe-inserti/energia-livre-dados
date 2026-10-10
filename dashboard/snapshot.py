"""Snapshot do dashboard (Sprint 6, Parte C2): o ÚNICO módulo do dashboard que fala com o BigQuery.

    uv run --env-file .env python -m dashboard.snapshot gerar --dry-run   # lê, monta, imprime
    uv run --env-file .env python -m dashboard.snapshot gerar             # grava dados/

O app Streamlit só lê `dashboard/dados/` (CSV + `manifest.json`): sem BigQuery, sem credencial
(`docs/planejamento/plano_sprint6c.md`, seção 2; `docs/decisoes.md`, "Sprint 6, Parte C"). Regerado
uma vez por mês (`docs/runbook_mensal.md`, passo 4) e commitado.

DE ONDE VEM CADA ARQUIVO (o manifesto registra o tipo e as fontes de cada um):
- `bigquery`: 7 consultas em marts já agregados na granularidade da página (mensal, não horário);
  os bytes faturados vêm do JOB (`total_bytes_billed`; 0 se veio do cache), nunca do piso;
- `copia`: cópia byte a byte de `docs/resultados/` (o hash do destino é o da origem);
- `derivado`: montado dos CSV e logs de `docs/resultados/` (texto preservado, sem refazer conta);
- `local`: saúde do pipeline, lida na máquina (o `run_results.json` do dbt e as durações da DAG no
  banco de metadados do orquestrador). Se a fonte falta (Docker desligado, arquivo ausente), o
  arquivo sai só com o cabeçalho e o manifesto marca "indisponível no momento do snapshot": o
  snapshot inteiro não falha.

COBERTURA EXIBIDA: só a FORA DA AMOSTRA (70,2% e 87,8%; teste final com intervalos calibrados só no
desenvolvimento, quantis por horizonte), do CSV `analise_teste_final_reconstruida_cobertura_por_
horizonte.csv`. O arquivo `_pooled.csv` (70,8% e 90,5%, calibração que já viu o teste) é recusado.

Nada com caminho absoluto, credencial, URL de conexão, usuário, senha ou host entra nos arquivos.
O snapshot inteiro tem de ficar abaixo de 5 MB (`LIMITE_BYTES`), senão aborta.
"""

import argparse
import calendar
import csv
import hashlib
import io
import json
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd

from ml import backtest as bt
from ml import recomendacao as rc
from ml import sensibilidades as sn
from ml.cenarios import SQL_PONDERADO, SQL_SEMANAL, montar_dados_pld
from ml.cenarios_pld import limites_do_ano
from ml.medida_bytes import ContaBytes
from ml.registro import MODELO_VERSAO

RAIZ = Path(__file__).resolve().parents[1]
RESULTADOS = RAIZ / "docs" / "resultados"
DESTINO = RAIZ / "dashboard" / "dados"
LIMITE_BYTES = 5 * 1024 * 1024
TETO_BYTES = 200 * 1024 * 1024  # maximum_bytes_billed por consulta (o padrão do projeto)
SUBMERCADO = "SE"
DAG_ID = "energia_livre_diaria"
N_EXECUCOES = 30
INDISPONIVEL = "indisponível no momento do snapshot"
# Cobertura fora da amostra (5.6, coluna "anterior"): o que a página mostra
COBERTURA_FONTE = "analise_teste_final_reconstruida_cobertura_por_horizonte.csv"
COBERTURA_80, COBERTURA_95 = 70.2, 87.8


class ErroDeSnapshot(RuntimeError):
    """O snapshot não pode ser gerado (fonte errada, tamanho, inconsistência)."""


# ---------------------------------------------------------------- utilitários


def sha256(conteudo: bytes) -> str:
    return hashlib.sha256(conteudo).hexdigest()


def _valor(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, datetime):
        return v.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if v.tzinfo else v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return v


def para_csv(df: pd.DataFrame) -> bytes:
    """CSV determinístico (mesma entrada, mesmos bytes)."""
    df = df.apply(lambda col: col.map(_valor))
    return df.to_csv(index=False, lineterminator="\n").encode("utf-8")


def linhas_do_csv(conteudo: bytes) -> int:
    return max(len(conteudo.decode("utf-8").splitlines()) - 1, 0)


# ---------------------------------------------------------------- BigQuery (7 consultas)


class Consultas:
    """Executa as consultas pelo medidor e guarda, para cada uma, o que o JOB reportou."""

    def __init__(self, gcp, cliente):
        self.conta = ContaBytes(gcp)
        self.cliente = cliente
        self.registro: list[dict] = []

    def executar(self, nome: str, tabela: str, sql: str) -> list[dict]:
        i = len(self.conta.medidas)
        r = self.conta.executar_consulta(self.cliente, sql, max_bytes_faturados=TETO_BYTES)
        m = self.conta.medidas[i]
        self.registro.append(
            {
                "nome": nome,
                "tabela": tabela,
                "processados": m.processados,
                "faturados": m.faturados or 0,
                "cache_hit": bool(m.cache),
                "sql": " ".join(sql.split()),
            }
        )
        return [dict(x.items()) for x in r.linhas]


def sql_carga_mensal() -> str:
    return (
        "SELECT mes, carga_original_mwmed, carga_ajustada_reconstruida_mwmed, cobertura, "
        f"mes_utilizavel FROM `marts.fct_carga_mensal` WHERE codigo_submercado = '{SUBMERCADO}' "
        "ORDER BY mes"
    )


SQL_CONSUMO = (
    "SELECT DATE_TRUNC(data_local, MONTH) AS mes, SUM(consumo_mwh) AS consumo_mwh, "
    "COUNT(*) AS horas FROM `marts.fct_consumo_horario` GROUP BY mes ORDER BY mes"
)
SQL_PREVISAO = (
    "SELECT origem, horizonte, mes_alvo, previsao_mwmed, p025_mwmed, p10_mwmed, p50_mwmed, "
    "p90_mwmed, p975_mwmed, calibracao, n_erros_calibracao, serie, gerado_em "
    f"FROM `marts.fct_previsao_carga` WHERE modelo_versao = '{MODELO_VERSAO}' "
    "AND tipo = 'producao' ORDER BY origem, horizonte"
)
SQL_ERROS = (
    "SELECT origem, horizonte, mes_alvo, previsto_mwmed, real_mwmed, erro_pct, serie "
    f"FROM `marts.fct_erro_previsao_carga` WHERE modelo_versao = '{MODELO_VERSAO}' "
    "AND periodo = 'producao' ORDER BY origem, horizonte"
)
SQL_RECOMENDACAO = (
    "SELECT "
    + ", ".join(f"`{c}`" for c in rc.COLUNAS)
    + " FROM `marts.fct_recomendacao_contrato` ORDER BY sens_id, origem, estrategia"
)
COLUNAS_CARGA = [
    "mes",
    "carga_original_mwmed",
    "carga_ajustada_reconstruida_mwmed",
    "cobertura",
    "mes_utilizavel",
]
COLUNAS_PREVISAO = [
    "origem",
    "horizonte",
    "mes_alvo",
    "previsao_mwmed",
    "p025_mwmed",
    "p10_mwmed",
    "p50_mwmed",
    "p90_mwmed",
    "p975_mwmed",
    "calibracao",
    "n_erros_calibracao",
    "serie",
    "gerado_em",
]
COLUNAS_ERROS = [
    "origem",
    "horizonte",
    "mes_alvo",
    "previsto_mwmed",
    "real_mwmed",
    "erro_pct",
    "serie",
]


def _quadro(linhas: list[dict], colunas: list[str]) -> pd.DataFrame:
    return pd.DataFrame(linhas, columns=colunas)


def marcar_meses_completos(consumo: pd.DataFrame) -> pd.DataFrame:
    """Acrescenta `mes_completo`: as horas do mês na curva (`horas`) são as horas esperadas dele
    (dias × 24; sem horário de verão desde 2019). O último mês costuma estar incompleto: a página
    usa só os meses completos."""
    consumo = consumo.copy()
    consumo["mes_completo"] = [
        int(h) == calendar.monthrange(m.year, m.month)[1] * 24
        for m, h in zip(consumo["mes"], consumo["horas"], strict=True)
    ]
    return consumo


def ler_pld_mensal(q: Consultas) -> pd.DataFrame:
    """PLD mensal do SE: semanal até 2020 (agregado pelo código dos cenários) e ponderado de 2021
    em diante. Piso e teto estrutural da seed `pld_limites` (só de 2021; antes não há série)."""
    semanal = q.executar("pld_semanal", "marts.fct_pld_semanal", SQL_SEMANAL)
    ponderado = q.executar("pld_ponderado", "marts.fct_pld_ponderado_mensal", SQL_PONDERADO)
    dados = montar_dados_pld(semanal, ponderado)
    linhas = []
    for mes, valor in sorted(dados.serie.items()):
        piso = teto = assumido = None
        if mes.year >= min(dados.limites):
            piso, teto, assumido = limites_do_ano(dados.limites, mes.year)
        linhas.append(
            {
                "mes": mes,
                "pld_rs_mwh": valor,
                "fonte": "semanal" if mes < date(2021, 1, 1) else "ponderado",
                "piso_rs_mwh": piso,
                "teto_estrutural_rs_mwh": teto,
                "limites_assumidos": assumido,
            }
        )
    return pd.DataFrame(linhas)


# ---------------------------------------------------------------- saúde (local)


def psql_csv(sql: str, timeout: int = 30) -> str:
    """Roda a consulta no banco de metadados do orquestrador (via `docker compose exec`) e devolve
    o CSV. Qualquer falha vira `ErroDeFonte` sem repetir stderr (pode conter host e usuário)."""
    try:
        r = subprocess.run(
            [
                "docker",
                "compose",
                "exec",
                "-T",
                "postgres",
                "psql",
                "-U",
                "airflow",
                "-d",
                "airflow",
            ]
            + ["--csv", "-c", sql],
            cwd=RAIZ,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as erro:
        raise ErroDeFonte(type(erro).__name__) from None
    if r.returncode != 0:
        raise ErroDeFonte(f"código {r.returncode}")
    return r.stdout


class ErroDeFonte(RuntimeError):
    """Uma fonte local de saúde falhou; a mensagem NÃO vai para os arquivos."""


SQL_RUNS = (
    "select dr.run_id, dr.run_type, dr.state as estado_dag, "
    "to_char(dr.start_date at time zone 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') as inicio_utc, "
    "round(extract(epoch from (dr.end_date - dr.start_date))::numeric, 1) as duracao_dag_s "
    f"from dag_run dr where dr.dag_id = '{DAG_ID}' order by dr.start_date desc limit {N_EXECUCOES}"
)
SQL_TASKS = (
    "select ti.run_id, ti.task_id, ti.state as estado_task, ti.try_number as tentativas, "
    "round(ti.duration::numeric, 1) as duracao_task_s from task_instance ti "
    f"where ti.dag_id = '{DAG_ID}' and ti.run_id in (select run_id from dag_run "
    f"where dag_id = '{DAG_ID}' order by start_date desc limit {N_EXECUCOES}) "
    "order by ti.run_id, ti.start_date"
)
COLUNAS_EXECUCOES = [
    "run_id",
    "run_type",
    "estado_dag",
    "inicio_utc",
    "duracao_dag_s",
    "task_id",
    "estado_task",
    "tentativas",
    "duracao_task_s",
]


def ler_execucoes(executar_psql: Callable[[str], str] = psql_csv) -> tuple[pd.DataFrame, dict]:
    """(quadro, status). Sem a fonte: quadro só com o cabeçalho e status `indisponivel`."""
    try:
        runs = list(csv.DictReader(io.StringIO(executar_psql(SQL_RUNS))))
        tasks = list(csv.DictReader(io.StringIO(executar_psql(SQL_TASKS))))
    except Exception:  # noqa: BLE001 - qualquer falha da fonte local vira "indisponível"; a mensagem não é gravada
        return pd.DataFrame(columns=COLUNAS_EXECUCOES), {
            "estado": "indisponivel",
            "motivo": f"{INDISPONIVEL}: o banco de metadados do orquestrador não respondeu "
            "(Docker desligado ou serviço fora do ar)",
        }
    por_run = {}
    for t in tasks:
        por_run.setdefault(t["run_id"], []).append(t)
    linhas = []
    for r in runs:
        for t in por_run.get(r["run_id"]) or [{}]:
            linhas.append(
                {
                    **{c: r.get(c, "") for c in COLUNAS_EXECUCOES[:5]},
                    **{c: t.get(c, "") for c in COLUNAS_EXECUCOES[5:]},
                }
            )
    quadro = pd.DataFrame(linhas, columns=COLUNAS_EXECUCOES)
    inicios = [r["inicio_utc"] for r in runs if r.get("inicio_utc")]
    return quadro, {
        "estado": "disponivel",
        "execucoes": len(runs),
        "ultima_execucao_utc": max(inicios) if inicios else None,
    }


COLUNAS_TESTES = ["tipo", "testes", "pass", "warn", "error", "registros"]


def ler_testes_dbt(run_results: Path, manifesto: Path) -> tuple[pd.DataFrame, dict]:
    """Resumo por tipo de teste do `run_results.json` local. Sem o arquivo: indisponível."""
    try:
        resultados = json.loads(run_results.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return pd.DataFrame(columns=COLUNAS_TESTES), {
            "estado": "indisponivel",
            "motivo": f"{INDISPONIVEL}: o resultado do dbt test não existe nesta máquina",
        }
    try:
        nos = json.loads(manifesto.read_text(encoding="utf-8")).get("nodes", {})
    except (OSError, ValueError):
        nos = {}
    por_tipo: dict[str, dict] = {}
    for r in resultados.get("results", []):
        no = nos.get(r.get("unique_id"))
        if no is None and not str(r.get("unique_id", "")).startswith("test."):
            continue
        if no is not None and no.get("resource_type") != "test":
            continue
        tipo = (
            (no or {}).get("test_metadata", {}).get("name", "singular" if no else "sem_manifesto")
        )
        status = {"pass": "pass", "warn": "warn", "fail": "error", "error": "error"}.get(
            r.get("status"), "error"
        )
        linha = por_tipo.setdefault(
            tipo, {"tipo": tipo, "testes": 0, "pass": 0, "warn": 0, "error": 0, "registros": 0}
        )
        linha["testes"] += 1
        linha[status] += 1
        linha["registros"] += int(r.get("failures") or 0)
    quadro = pd.DataFrame(
        sorted(por_tipo.values(), key=lambda x: x["tipo"]), columns=COLUNAS_TESTES
    )
    args = resultados.get("args") or {}
    selecao = [s for s in (args.get("select") or []) if isinstance(s, str) and "/" not in s]
    return quadro, {
        "estado": "disponivel",
        "run_results_gerado_em": (resultados.get("metadata") or {}).get("generated_at"),
        "comando": args.get("which"),
        "selecao": selecao,
        "n_resultados": len(resultados.get("results", [])),
        "tempo_s": round(float(resultados.get("elapsed_time") or 0.0), 1),
        "aviso": "resultado do ÚLTIMO comando dbt desta máquina, que pode não ser o da DAG",
    }


# ---------------------------------------------------------------- resultados versionados


def _ler(caminho: Path) -> bytes:
    try:
        return caminho.read_bytes()
    except OSError as erro:
        raise ErroDeSnapshot(f"falta o arquivo versionado {caminho.name}") from erro


def conferir_cobertura(caminho: Path) -> dict:
    """Cobertura exibida = fora da amostra (70,2% e 87,8%); recusa o `_pooled` e qualquer outra."""
    if "pooled" in caminho.name or caminho.name != COBERTURA_FONTE:
        raise ErroDeSnapshot(
            f"a cobertura exibida vem só de {COBERTURA_FONTE} (fora da amostra); "
            f"{caminho.name} não é aceito"
        )
    geral = next(
        (
            r
            for r in csv.DictReader(io.StringIO(_ler(caminho).decode("utf-8")))
            if r["recorte"] == "geral"
        ),
        None,
    )
    if geral is None:
        raise ErroDeSnapshot("o arquivo de cobertura não tem a linha geral")
    c80, c95 = float(geral["cobertura80_pct"]), float(geral["cobertura95_pct"])
    if (round(c80, 1), round(c95, 1)) != (COBERTURA_80, COBERTURA_95):
        raise ErroDeSnapshot(
            f"cobertura {c80:.1f}% e {c95:.1f}% não é a fora da amostra "
            f"({COBERTURA_80}% e {COBERTURA_95}%)"
        )
    return {"cobertura80_pct": c80, "cobertura95_pct": c95, "n": int(geral["n"])}


def _empilhar(resultados: Path, sufixo: str, tirar: tuple[str, ...]) -> bytes:
    """Empilha o arquivo do caso base e os 13 das sensibilidades com a coluna `sens_id` na frente,
    preservando o TEXTO de cada valor (nada é reformatado)."""
    saida = io.StringIO()
    escritor = None
    base = f"{bt.PREFIXO}_{sufixo}.csv"
    nomes = [("caso_base", base), *[(i, f"sens_{i}_{sufixo}.csv") for i in sn.IDS]]
    colunas = None
    for sens_id, nome in nomes:
        leitor = csv.DictReader(io.StringIO(_ler(resultados / nome).decode("utf-8")))
        cols = [c for c in (leitor.fieldnames or []) if c not in tirar]
        if colunas is None:
            colunas = cols
            escritor = csv.writer(saida, lineterminator="\n")
            escritor.writerow(["sens_id", *colunas])
        elif cols != colunas:
            raise ErroDeSnapshot(f"{nome}: as colunas não são as do caso base")
        for linha in leitor:
            escritor.writerow([sens_id, *[linha[c] for c in colunas]])
    return saida.getvalue().encode("utf-8")


def pre_registros(resultados: Path) -> tuple[bytes, dict]:
    """(CSV, hashes). Uma linha por execução: o caso base e as 13 sensibilidades."""
    base = [
        e
        for e in bt.ler_log(resultados / "backtest_execucoes.jsonl")
        if e.get("evento") == "caso_base" and e.get("numero") == 1
    ]
    sens = {
        e["sens_id"]: e
        for e in bt.ler_log(resultados / "sensibilidades_execucoes.jsonl")
        if e.get("evento") == "sensibilidade"
    }
    if len(base) != 1 or set(sens) != set(sn.IDS):
        raise ErroDeSnapshot("os logs de execução não têm o caso base e as 13 sensibilidades")
    h_base = base[0]["preregistro"]
    h_sens = {e["preregistro"] for e in sens.values()}
    if len(h_sens) != 1:
        raise ErroDeSnapshot("as sensibilidades têm pré-registros diferentes")
    h_sens = h_sens.pop()
    if not h_base.startswith("02990fd") or not h_sens.startswith("4c02987"):
        raise ErroDeSnapshot(
            "os pré-registros não são 02990fd (caso base) e 4c02987 (sensibilidades)"
        )
    linhas = [
        {
            "sens_id": "caso_base",
            "quando_utc": base[0]["quando_utc"],
            "head": base[0]["head"],
            "preregistro": h_base,
            "config_hash": base[0]["config_hash"],
            "execucao_id": base[0]["criterios"]["execucao_id"],
            "muda": "{}",
        }
    ]
    for i in sn.IDS:
        e = sens[i]
        linhas.append(
            {
                "sens_id": i,
                "quando_utc": e["quando_utc"],
                "head": e["head"],
                "preregistro": e["preregistro"],
                "config_hash": e["config_hash"],
                "execucao_id": e["execucao_id"],
                "muda": json.dumps(e["muda"], sort_keys=True, ensure_ascii=False),
            }
        )
    return para_csv(pd.DataFrame(linhas)), {"caso_base": h_base, "sensibilidades": h_sens}


def previsoes_do_teste_final(resultados: Path) -> bytes:
    """Modelo e ingênuo sazonal (mesmos pares), do CSV versionado do teste final."""
    leitor = csv.DictReader(
        io.StringIO(_ler(resultados / "candidatos_teste_final_reconstruida_previsoes.csv").decode())
    )
    saida = io.StringIO()
    escritor = csv.writer(saida, lineterminator="\n")
    escritor.writerow(leitor.fieldnames)
    for linha in leitor:
        if linha["candidato"] in ("comb_ets_sarima_regressao", "sazonal_ingenuo_mesmos_pares"):
            escritor.writerow([linha[c] for c in leitor.fieldnames])
    return saida.getvalue().encode("utf-8")


# destino -> origem em docs/resultados (cópia byte a byte)
COPIAS = {
    "backtest_mensal_caso_base.csv": "backtest_caso_base_mensal.csv",
    "sens_resumo.csv": "sens_resumo.csv",
    "sens_resumo_por_ano.csv": "sens_resumo_por_ano.csv",
    "sens_banda_f.csv": "sens_banda_f.csv",
    "sens_invariancias.csv": "sens_invariancias.csv",
    "mape_por_ano.csv": "analise_teste_final_reconstruida_por_ano.csv",
    "modelos_resumo.csv": "candidatos_teste_final_reconstruida_resumo.csv",
    "cobertura_fora_da_amostra.csv": COBERTURA_FONTE,
}


@dataclass(frozen=True)
class Arquivo:
    nome: str
    conteudo: bytes
    tipo: str  # bigquery | copia | derivado | local
    fontes: tuple[dict, ...]

    @property
    def linhas(self) -> int:
        return linhas_do_csv(self.conteudo)


def _fonte_versionada(resultados: Path, nome: str) -> dict:
    return {"arquivo": f"docs/resultados/{nome}", "sha256": sha256(_ler(resultados / nome))}


def arquivos_versionados(resultados: Path) -> tuple[list[Arquivo], dict, dict]:
    """(arquivos, hashes dos pré-registros, cobertura exibida)."""
    cobertura = conferir_cobertura(resultados / COBERTURA_FONTE)
    arquivos = []
    for destino, origem in COPIAS.items():
        arquivos.append(
            Arquivo(
                destino,
                _ler(resultados / origem),
                "copia",
                (_fonte_versionada(resultados, origem),),
            )
        )
    empilhados = {
        "backtest_economia.csv": ("economia", ("config_hash",)),
        "backtest_anual.csv": ("anual", ("config_hash",)),
    }
    for destino, (sufixo, tirar) in empilhados.items():
        nomes = [f"{bt.PREFIXO}_{sufixo}.csv", *[f"sens_{i}_{sufixo}.csv" for i in sn.IDS]]
        arquivos.append(
            Arquivo(
                destino,
                _empilhar(resultados, sufixo, ("sens_id", *tirar)),
                "derivado",
                tuple(_fonte_versionada(resultados, n) for n in nomes),
            )
        )
    csv_pre, hashes = pre_registros(resultados)
    arquivos.append(
        Arquivo(
            "pre_registros.csv",
            csv_pre,
            "derivado",
            (
                _fonte_versionada(resultados, "backtest_execucoes.jsonl"),
                _fonte_versionada(resultados, "sensibilidades_execucoes.jsonl"),
            ),
        )
    )
    previsoes = "candidatos_teste_final_reconstruida_previsoes.csv"
    arquivos.append(
        Arquivo(
            "previsoes_teste_final.csv",
            previsoes_do_teste_final(resultados),
            "derivado",
            (_fonte_versionada(resultados, previsoes),),
        )
    )
    return arquivos, hashes, cobertura


# ---------------------------------------------------------------- montagem


def _data_maxima(df: pd.DataFrame, coluna: str, filtro=None) -> str | None:
    if filtro is not None:
        df = df[filtro(df)]
    return None if df.empty else _valor(max(df[coluna]))


def ultimos_dados(carga, pld, consumo, previsao, recomendacao, execucoes, testes) -> dict:
    """A data do último dado de cada fonte (para a página de saúde e para o aviso)."""
    return {
        "carga_mensal": _data_maxima(carga, "mes", lambda d: d["mes_utilizavel"].astype(bool)),
        "pld_mensal": _data_maxima(pld, "mes"),
        "consumo_exemplo": _data_maxima(consumo, "mes", lambda d: d["mes_completo"].astype(bool)),
        "previsao_producao_origem": _data_maxima(previsao, "origem"),
        "recomendacao_origem": _data_maxima(
            recomendacao, "origem", lambda d: d["tipo"].isin(["previa", "producao"])
        ),
        "backtest_ate": "2025-12-01",
        "execucao_da_dag_utc": execucoes.get("ultima_execucao_utc"),
        "dbt_test_utc": testes.get("run_results_gerado_em"),
    }


def ultimo_mes_fechado(carga: pd.DataFrame) -> date | None:
    from ml.previsao import ultima_origem_completa

    ok = carga[
        carga["mes_utilizavel"].astype(bool) & carga["carga_ajustada_reconstruida_mwmed"].notna()
    ]
    if ok.empty:
        return None
    linhas = [
        (date.fromisoformat(str(_valor(m))), float(v), float(c))
        for m, v, c in zip(
            ok["mes"], ok["carga_ajustada_reconstruida_mwmed"], ok["cobertura"], strict=True
        )
    ]
    return ultima_origem_completa(linhas)


def avisos_de_defasagem(previsao: pd.DataFrame, recomendacao: pd.DataFrame, fechado) -> list[str]:
    if previsao.empty or fechado is None:
        return []
    prev = date.fromisoformat(str(_valor(max(previsao["origem"]))))
    da_previa = recomendacao[recomendacao["tipo"].isin(["previa", "producao"])]
    if da_previa.empty:
        return [f"{INDISPONIVEL}: a recomendação de produção ainda não foi gravada"]
    usada = date.fromisoformat(str(_valor(max(da_previa["origem"]))))
    return rc.aviso_de_defasagem(usada, prev, fechado)


def meses_incompletos(carga: pd.DataFrame, consumo: pd.DataFrame, fechado) -> dict:
    """Meses que estão nos arquivos mas NÃO são dado fechado: o mês corrente da carga
    (`mes_utilizavel` falso depois do último mês fechado) e os meses incompletos da curva."""
    abertos = carga[~carga["mes_utilizavel"].astype(bool)]
    if fechado is not None:
        abertos = abertos[[date.fromisoformat(str(_valor(m))) > fechado for m in abertos["mes"]]]
    return {
        "carga_mensal_se.csv": [_valor(m) for m in abertos["mes"]],
        "consumo_exemplo_mensal.csv": [_valor(m) for m in consumo[~consumo["mes_completo"]]["mes"]],
    }


def montar_manifesto(
    agora: datetime,
    arquivos: list[Arquivo],
    consultas: list[dict],
    hashes_pre: dict,
    cobertura: dict,
    previsao: pd.DataFrame,
    carga,
    pld,
    consumo,
    recomendacao,
    saude_execucoes: dict,
    saude_testes: dict,
    commit: str,
) -> dict:
    fechado = ultimo_mes_fechado(carga)
    origem_producao = _data_maxima(previsao, "origem")
    previa = recomendacao[recomendacao["tipo"].isin(["previa", "producao"])]
    return {
        "snapshot_gerado_em": agora.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commit": commit,
        "origem_de_producao": origem_producao,
        "origem_da_previa": _data_maxima(previa, "origem"),
        "ultimo_mes_fechado": fechado.isoformat() if fechado else None,
        "avisos_de_defasagem": avisos_de_defasagem(previsao, recomendacao, fechado),
        "meses_incompletos": meses_incompletos(carga, consumo, fechado),
        "ultimo_dado_por_fonte": ultimos_dados(
            carga, pld, consumo, previsao, recomendacao, saude_execucoes, saude_testes
        ),
        "pre_registros": hashes_pre,
        "calibracao_dos_intervalos_de_producao": {
            "descricao": (
                "Intervalos da previsão de produção: quantis empíricos do erro do desenvolvimento "
                "(2012-2019) e do teste final (2021-2025), mais os erros de produção realizados. "
                "A calibração JÁ VIU o teste final; por isso não é cobertura fora da amostra."
            ),
            "valores_no_banco": sorted({str(x) for x in previsao["calibracao"].dropna().unique()}),
            "fonte": "marts.fct_previsao_carga, coluna calibracao",
        },
        "cobertura_exibida": {
            "descricao": (
                "Cobertura FORA DA AMOSTRA: teste final 2021-2025 (654 pares) com intervalos "
                "calibrados só no desenvolvimento (2012-2019), quantis por horizonte."
            ),
            "fonte": f"docs/resultados/{COBERTURA_FONTE}",
            "referencia": "docs/metricas.md, Sprint 5 (intervalos) e 5.6 (coluna anterior)",
            "nominal_80_pct": 80,
            "nominal_95_pct": 95,
            **cobertura,
        },
        "saude": {"execucoes_da_dag": saude_execucoes, "testes_dbt": saude_testes},
        "arquivos": {
            a.nome: {
                "tipo": a.tipo,
                "linhas": a.linhas,
                "bytes": len(a.conteudo),
                "sha256": sha256(a.conteudo),
                "fontes": list(a.fontes),
            }
            for a in sorted(arquivos, key=lambda x: x.nome)
        },
        "consultas": [{k: v for k, v in c.items() if k != "sql"} for c in consultas],
        "bytes_faturados_total": sum(c["faturados"] for c in consultas),
        "tamanho_total_bytes": sum(len(a.conteudo) for a in arquivos),
        "limite_bytes": LIMITE_BYTES,
    }


def conferir_tamanho(arquivos: list[Arquivo], manifesto: bytes = b"") -> int:
    total = sum(len(a.conteudo) for a in arquivos) + len(manifesto)
    if total > LIMITE_BYTES:
        raise ErroDeSnapshot(f"o snapshot tem {total:,} bytes, acima do limite de {LIMITE_BYTES:,}")
    return total


@dataclass(frozen=True)
class Snapshot:
    arquivos: list[Arquivo]
    manifesto: dict
    consultas: list[dict]

    def manifesto_bytes(self) -> bytes:
        return (
            json.dumps(self.manifesto, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        ).encode()


def montar_snapshot(
    gcp,
    cliente,
    resultados: Path = RESULTADOS,
    executar_psql: Callable[[str], str] = psql_csv,
    run_results: Path | None = None,
    dbt_manifest: Path | None = None,
    agora: datetime | None = None,
    commit: str = "",
) -> Snapshot:
    agora = agora or datetime.now(UTC)
    q = Consultas(gcp, cliente)
    carga = _quadro(
        q.executar("carga_mensal", "marts.fct_carga_mensal", sql_carga_mensal()), COLUNAS_CARGA
    )
    pld = ler_pld_mensal(q)
    consumo = marcar_meses_completos(
        _quadro(
            q.executar("consumo_exemplo", "marts.fct_consumo_horario", SQL_CONSUMO),
            ["mes", "consumo_mwh", "horas"],
        )
    )
    previsao = _quadro(
        q.executar("previsao_producao", "marts.fct_previsao_carga", SQL_PREVISAO), COLUNAS_PREVISAO
    )
    erros = _quadro(
        q.executar("erros_producao", "marts.fct_erro_previsao_carga", SQL_ERROS), COLUNAS_ERROS
    )
    recomendacao = _quadro(
        q.executar("recomendacao", "marts.fct_recomendacao_contrato", SQL_RECOMENDACAO), rc.COLUNAS
    )
    versionados, hashes_pre, cobertura = arquivos_versionados(resultados)
    execucoes, status_exec = ler_execucoes(executar_psql)
    base_dbt = RAIZ / "dbt" / "target"
    testes, status_testes = ler_testes_dbt(
        run_results or base_dbt / "run_results.json", dbt_manifest or base_dbt / "manifest.json"
    )
    tabelas = "marts."
    arquivos = [
        Arquivo(
            "carga_mensal_se.csv",
            para_csv(carga),
            "bigquery",
            ({"tabela": tabelas + "fct_carga_mensal"},),
        ),
        Arquivo(
            "pld_mensal_se.csv",
            para_csv(pld),
            "bigquery",
            (
                {"tabela": tabelas + "fct_pld_semanal"},
                {"tabela": tabelas + "fct_pld_ponderado_mensal"},
            ),
        ),
        Arquivo(
            "consumo_exemplo_mensal.csv",
            para_csv(consumo),
            "bigquery",
            ({"tabela": tabelas + "fct_consumo_horario"},),
        ),
        Arquivo(
            "previsao_producao.csv",
            para_csv(previsao),
            "bigquery",
            ({"tabela": tabelas + "fct_previsao_carga"},),
        ),
        Arquivo(
            "erros_producao.csv",
            para_csv(erros),
            "bigquery",
            ({"tabela": tabelas + "fct_erro_previsao_carga"},),
        ),
        Arquivo(
            "recomendacao.csv",
            para_csv(recomendacao),
            "bigquery",
            ({"tabela": tabelas + "fct_recomendacao_contrato"},),
        ),
        *versionados,
        Arquivo(
            "saude_execucoes.csv",
            para_csv(execucoes),
            "local",
            ({"fonte": "banco de metadados do orquestrador"},),
        ),
        Arquivo(
            "saude_testes_dbt.csv",
            para_csv(testes),
            "local",
            ({"fonte": "dbt/target/run_results.json"},),
        ),
    ]
    frescor = frescor_das_fontes(carga, pld, consumo, previsao, recomendacao, agora)
    arquivos.append(Arquivo("frescor_fontes.csv", para_csv(frescor), "derivado", ()))
    manifesto = montar_manifesto(
        agora,
        arquivos,
        q.registro,
        hashes_pre,
        cobertura,
        previsao,
        carga,
        pld,
        consumo,
        recomendacao,
        status_exec,
        status_testes,
        commit,
    )
    snap = Snapshot(arquivos, manifesto, q.registro)
    conferir_tamanho(arquivos, snap.manifesto_bytes())
    return snap


def frescor_das_fontes(
    carga, pld, consumo, previsao, recomendacao, agora: datetime
) -> pd.DataFrame:
    """Último dado e idade (dias) de cada fonte, calculados dos próprios arquivos do snapshot."""
    previa = recomendacao[recomendacao["tipo"].isin(["previa", "producao"])]
    fontes = [
        (
            "carga mensal (ONS)",
            _data_maxima(carga, "mes", lambda d: d["mes_utilizavel"].astype(bool)),
        ),
        ("PLD mensal (CCEE)", _data_maxima(pld, "mes")),
        (
            "consumo do consumidor-exemplo",
            _data_maxima(consumo, "mes", lambda d: d["mes_completo"].astype(bool)),
        ),
        ("previsão de produção (origem)", _data_maxima(previsao, "origem")),
        ("recomendação de contrato (origem)", _data_maxima(previa, "origem")),
    ]
    linhas = []
    for nome, ultimo in fontes:
        idade = (agora.date() - date.fromisoformat(ultimo)).days if ultimo else None
        linhas.append({"fonte": nome, "ultimo_dado": ultimo, "idade_dias_no_snapshot": idade})
    return pd.DataFrame(linhas)


# ---------------------------------------------------------------- gravação e linha de comando


def gravar(snap: Snapshot, destino: Path = DESTINO) -> list[str]:
    """Escreve os arquivos e o manifesto (por último); remove CSV antigos que saíram do conjunto."""
    destino.mkdir(parents=True, exist_ok=True)
    novos = {a.nome for a in snap.arquivos}
    removidos = []
    for antigo in destino.glob("*.csv"):
        if antigo.name not in novos:
            antigo.unlink()
            removidos.append(antigo.name)
    for a in snap.arquivos:
        (destino / a.nome).write_bytes(a.conteudo)
    (destino / "manifest.json").write_bytes(snap.manifesto_bytes())
    return removidos


def imprimir(snap: Snapshot, dry_run: bool, destino: Path) -> None:
    print("CONSULTAS (BigQuery):")
    for c in snap.consultas:
        print(f"- {c['nome']} ({c['tabela']}): {c['sql']}")
        print(
            f"    {c['processados']:,} bytes processados; {c['faturados']:,} faturados (job); "
            f"cache_hit = {c['cache_hit']}".replace(",", ".")
        )
    print("\nARQUIVOS (linhas lidas; bytes):")
    for a in snap.arquivos:
        print(
            f"- {a.nome:34s} {a.tipo:9s} {a.linhas:6d} linhas {len(a.conteudo):9,d} bytes".replace(
                ",", "."
            )
        )
    m = snap.manifesto
    total = m["tamanho_total_bytes"]
    print(
        f"\ntotal: {total:,} bytes ({total / 1024**2:.2f} MiB) contra o limite de "
        f"{LIMITE_BYTES / 1024**2:.0f} MiB; bytes faturados nas consultas: "
        f"{m['bytes_faturados_total']:,}".replace(",", ".")
    )
    print(
        f"origem de produção: {m['origem_de_producao']}; "
        f"origem da prévia: {m['origem_da_previa']}; "
        f"último mês fechado: {m['ultimo_mes_fechado']}"
    )
    for aviso in m["avisos_de_defasagem"]:
        print(aviso)
    print(f"pré-registros: {m['pre_registros']}")
    print(f"saúde (execuções da DAG): {m['saude']['execucoes_da_dag']['estado']}")
    print(f"saúde (testes do dbt): {m['saude']['testes_dbt']['estado']}")
    print(
        f"cobertura exibida (fora da amostra): {m['cobertura_exibida']['cobertura80_pct']:.1f}% e "
        f"{m['cobertura_exibida']['cobertura95_pct']:.1f}%"
    )
    if dry_run:
        print("\ndry-run: nada gravado (as consultas foram executadas; o dry-run só não escreve)")


def gerar(
    dry_run: bool,
    destino: Path = DESTINO,
    resultados: Path = RESULTADOS,
    gcp=None,
    cliente=None,
    **opcoes,
) -> int:
    if gcp is None:
        from ml.previsao import _cliente, ler_commit

        gcp, cliente = _cliente()
        opcoes.setdefault("commit", ler_commit(RAIZ))
    snap = montar_snapshot(gcp, cliente, resultados, **opcoes)
    imprimir(snap, dry_run, destino)
    if dry_run:
        return 0
    removidos = gravar(snap, destino)
    print(f"\ngravado em {destino.relative_to(RAIZ) if destino.is_relative_to(RAIZ) else destino}")
    if removidos:
        print(f"removidos do conjunto antigo: {', '.join(removidos)}")
    print("commite dashboard/dados/ (o Community Cloud reimplanta a cada push)")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="comando", required=True)
    g = sub.add_parser("gerar", help="lê as fontes e grava dashboard/dados/")
    g.add_argument("--dry-run", action="store_true", help="lê e imprime; não grava")
    a = ap.parse_args(argv)
    try:
        return gerar(a.dry_run)
    except ErroDeSnapshot as erro:
        print(f"ABORTADO, nada foi gravado: {erro}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
