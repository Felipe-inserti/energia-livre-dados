"""Camada de dados do dashboard: lê SÓ `dashboard/dados/` (o snapshot) e devolve DataFrames prontos.

Funções puras, sem Streamlit: cada uma recebe `diretorio` (padrão: a pasta do snapshot) e devolve
tipos já corretos (`mes` como data, números como float, booleanos como bool). Nenhuma lê `docs/`,
BigQuery ou rede; nenhuma importa `google`, `ml` ou `snapshot` (um teste confere).

Meses incompletos: `carga_mensal()` e `consumo_exemplo()` devolvem, por padrão, só os meses
FECHADOS (o mês corrente está no arquivo, marcado, e fica de fora do que a página mostra).
"""

import json
from pathlib import Path

import pandas as pd

DADOS = Path(__file__).resolve().parent / "dados"
# Ordem fixa das execuções (a do plano_sprint6b.md): a tabela nunca é ordenada por economia
ORDEM_SENSIBILIDADES = (
    "caso_base",
    "f00",
    "f05",
    "f15",
    "spread00",
    "spread40",
    "lam00",
    "lam10",
    "alfa90",
    "rmax120",
    "pldsimples",
    "disp125",
    "disp150",
    "clip",
)
ESTRATEGIAS = ("ingenua", "pontual", "otimizada")
RECORTE_5_ANOS = "2021-2025"
RECORTE_SEM_2021 = "2022-2025"


class ErroDeLeitura(RuntimeError):
    """O snapshot não tem o arquivo ou a coluna que a página precisa."""


def _bool(serie: pd.Series) -> pd.Series:
    """'True'/'False' (texto do CSV) para bool; vazio fica nulo (dtype `boolean`)."""
    mapa = {"True": True, "False": False, True: True, False: False}
    return serie.map(mapa).astype("boolean")


def _csv(
    nome: str,
    diretorio: Path = DADOS,
    colunas: tuple[str, ...] = (),
    datas: tuple[str, ...] = (),
    booleanos: tuple[str, ...] = (),
    inteiros: tuple[str, ...] = (),
    textos: tuple[str, ...] = (),
) -> pd.DataFrame:
    caminho = Path(diretorio) / nome
    if not caminho.exists():
        raise ErroDeLeitura(f"o snapshot não tem o arquivo {nome}")
    df = pd.read_csv(caminho, dtype={c: "string" for c in textos})
    faltam = [c for c in colunas if c not in df.columns]
    if faltam:
        raise ErroDeLeitura(f"{nome}: faltam as colunas {faltam}")
    for c in datas:
        df[c] = pd.to_datetime(df[c], utc=False)
    for c in booleanos:
        df[c] = _bool(df[c])
    for c in inteiros:
        df[c] = pd.to_numeric(df[c]).astype("Int64")
    return df


def manifesto(diretorio: Path = DADOS) -> dict:
    caminho = Path(diretorio) / "manifest.json"
    if not caminho.exists():
        raise ErroDeLeitura("o snapshot não tem o manifest.json")
    return json.loads(caminho.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- panorama


def carga_mensal(diretorio: Path = DADOS, so_fechados: bool = True) -> pd.DataFrame:
    df = _csv(
        "carga_mensal_se.csv",
        diretorio,
        ("mes", "carga_original_mwmed", "carga_ajustada_reconstruida_mwmed", "mes_utilizavel"),
        datas=("mes",),
        booleanos=("mes_utilizavel",),
    )
    return df[df["mes_utilizavel"].astype(bool)].reset_index(drop=True) if so_fechados else df


def pld_mensal(diretorio: Path = DADOS) -> pd.DataFrame:
    return _csv(
        "pld_mensal_se.csv",
        diretorio,
        ("mes", "pld_rs_mwh", "fonte", "piso_rs_mwh", "teto_estrutural_rs_mwh"),
        datas=("mes",),
        booleanos=("limites_assumidos",),
    )


def consumo_exemplo(diretorio: Path = DADOS, so_completos: bool = True) -> pd.DataFrame:
    df = _csv(
        "consumo_exemplo_mensal.csv",
        diretorio,
        ("mes", "consumo_mwh", "horas", "mes_completo"),
        datas=("mes",),
        booleanos=("mes_completo",),
    )
    return df[df["mes_completo"].astype(bool)].reset_index(drop=True) if so_completos else df


# ---------------------------------------------------------------- previsão


def previsao_producao(diretorio: Path = DADOS) -> pd.DataFrame:
    """A previsão de produção da origem MAIS RECENTE (12 meses, com as faixas)."""
    df = _csv(
        "previsao_producao.csv",
        diretorio,
        ("origem", "horizonte", "mes_alvo", "previsao_mwmed", "p025_mwmed", "p975_mwmed"),
        datas=("origem", "mes_alvo"),
    )
    return df[df["origem"] == df["origem"].max()].sort_values("horizonte").reset_index(drop=True)


def erros_producao(diretorio: Path = DADOS) -> pd.DataFrame:
    return _csv(
        "erros_producao.csv",
        diretorio,
        ("origem", "horizonte", "mes_alvo", "erro_pct"),
        datas=("origem", "mes_alvo"),
    )


def previsoes_teste_final(diretorio: Path = DADOS) -> pd.DataFrame:
    return _csv(
        "previsoes_teste_final.csv",
        diretorio,
        ("candidato", "origem", "horizonte", "alvo", "previsto_mwmed", "real_mwmed", "erro_pct"),
        datas=("origem", "alvo"),
    )


def mape_por_ano(diretorio: Path = DADOS) -> pd.DataFrame:
    return _csv("mape_por_ano.csv", diretorio, ("candidato", "ano", "n", "mape_pct", "vies_pct"))


def modelos_resumo(diretorio: Path = DADOS) -> pd.DataFrame:
    return _csv("modelos_resumo.csv", diretorio, ("candidato", "n", "mape_pct", "vies_pct"))


def desenvolvimento_resumo(diretorio: Path = DADOS) -> pd.DataFrame:
    """O desenvolvimento (2012–2019, série original): MAPE de cada candidato e o erro-padrão."""
    return _csv(
        "desenvolvimento_resumo.csv",
        diretorio,
        ("candidato", "mape_pct", "diferenca_mape_vs_ingenuo_pp", "ep_diferenca_pp"),
    )


def cobertura(diretorio: Path = DADOS) -> dict:
    """Cobertura FORA DA AMOSTRA (70,2% e 87,8%): {'geral', 'por_horizonte', 'por_ano', 'fonte'}."""
    df = _csv(
        "cobertura_fora_da_amostra.csv",
        diretorio,
        ("recorte", "valor", "n", "cobertura80_pct", "cobertura95_pct"),
        textos=("recorte", "valor"),
    )
    geral = df[df["recorte"] == "geral"].iloc[0]
    cob = manifesto(diretorio)["cobertura_exibida"]

    def parte(recorte):
        d = df[df["recorte"] == recorte].copy()
        d["valor"] = pd.to_numeric(d["valor"]).astype(int)
        return d.reset_index(drop=True)

    return {
        "geral": {
            "cobertura80_pct": float(geral["cobertura80_pct"]),
            "cobertura95_pct": float(geral["cobertura95_pct"]),
            "n": int(geral["n"]),
        },
        "por_horizonte": parte("horizonte"),
        "por_ano": parte("ano"),
        "fonte": cob["fonte"],
        "descricao": cob["descricao"],
        "referencia": cob["referencia"],
    }


# ---------------------------------------------------------------- decisão


def _ordenar(df: pd.DataFrame, coluna: str = "sens_id") -> pd.DataFrame:
    ordem = {s: i for i, s in enumerate(ORDEM_SENSIBILIDADES)}
    df = df.assign(_o=df[coluna].map(ordem))
    return df.sort_values("_o", kind="stable").drop(columns="_o").reset_index(drop=True)


def backtest_economia(diretorio: Path = DADOS) -> pd.DataFrame:
    df = _csv(
        "backtest_economia.csv",
        diretorio,
        ("sens_id", "recorte", "custo_ingenua_rs", "valor_previsao_rs", "valor_otimizacao_rs"),
        textos=("sens_id", "recorte"),
    )
    return _ordenar(df)


def backtest_anual(diretorio: Path = DADOS) -> pd.DataFrame:
    df = _csv(
        "backtest_anual.csv",
        diretorio,
        (
            "sens_id",
            "ano",
            "estrategia",
            "v_mwm",
            "razao_v_pontual",
            "custo_rs",
            "pit_custo_realizado",
        ),
        booleanos=("cobertura_abaixo_de_100",),
        textos=("sens_id", "estrategia"),
    )
    return _ordenar(df)


def backtest_mensal(diretorio: Path = DADOS) -> pd.DataFrame:
    return _csv(
        "backtest_mensal_caso_base.csv",
        diretorio,
        ("ano", "mes", "estrategia", "consumo_mwh", "pld_ponderado_rs_mwh", "sobrando_mwh"),
        booleanos=("fora_da_faixa",),
    )


def sensibilidades(diretorio: Path = DADOS) -> pd.DataFrame:
    df = _csv(
        "sens_resumo.csv",
        diretorio,
        ("sens_id", "parametro", "recorte", "valor_previsao_rs", "valor_otimizacao_rs", "r_2021"),
        textos=("sens_id", "parametro", "recorte"),
    )
    return _ordenar(df)


def sensibilidades_por_ano(diretorio: Path = DADOS) -> pd.DataFrame:
    df = _csv(
        "sens_resumo_por_ano.csv",
        diretorio,
        ("sens_id", "ano", "valor_previsao_rs", "valor_otimizacao_rs", "r_otimizada"),
        booleanos=("cobertura_abaixo_de_100_otimizada",),
        textos=("sens_id",),
    )
    return _ordenar(df)


def banda_f(diretorio: Path = DADOS) -> pd.DataFrame:
    return _csv(
        "sens_banda_f.csv",
        diretorio,
        ("f", "sens_id", "recorte", "valor_previsao_rs", "valor_otimizacao_rs", "r_otimizada"),
        textos=("sens_id", "recorte"),
    )


def invariancias(diretorio: Path = DADOS) -> pd.DataFrame:
    df = _csv(
        "sens_invariancias.csv",
        diretorio,
        ("sens_id", "ingenua_custo_igual", "pontual_custo_igual"),
        booleanos=("ingenua_custo_igual", "pontual_custo_igual", "ingenua_ex_ante_igual"),
        textos=("sens_id", "otimizada_anos_r_igual"),
    )
    return _ordenar(df)


def pre_registros(diretorio: Path = DADOS) -> pd.DataFrame:
    df = _csv(
        "pre_registros.csv",
        diretorio,
        ("sens_id", "quando_utc", "head", "preregistro", "config_hash", "execucao_id", "muda"),
        textos=("sens_id", "head", "preregistro", "config_hash", "execucao_id", "muda"),
    )
    return _ordenar(df)


def recomendacao(diretorio: Path = DADOS) -> pd.DataFrame:
    return _csv(
        "recomendacao.csv",
        diretorio,
        ("sens_id", "origem", "estrategia", "tipo", "v_mwm", "preco_contrato_rs_mwh"),
        datas=("origem", "janela_inicio", "janela_fim"),
        booleanos=("limites_assumidos",),
        inteiros=("ano_contrato",),
        textos=("sens_id", "estrategia", "tipo"),
    )


def previa_atual(diretorio: Path = DADOS) -> pd.DataFrame:
    """As 3 linhas (ingênua, pontual, otimizada) da prévia/recomendação de produção mais recente."""
    df = recomendacao(diretorio)
    df = df[(df["sens_id"] == "caso_base") & df["tipo"].isin(["previa", "producao"])]
    if df.empty:
        return df
    df = df[df["origem"] == df["origem"].max()]
    ordem = {e: i for i, e in enumerate(ESTRATEGIAS)}
    return (
        df.assign(_o=df["estrategia"].map(ordem))
        .sort_values("_o")
        .drop(columns="_o")
        .reset_index(drop=True)
    )


def previas_anteriores(diretorio: Path = DADOS) -> pd.DataFrame:
    df = recomendacao(diretorio)
    df = df[(df["sens_id"] == "caso_base") & df["tipo"].isin(["previa", "producao"])]
    return df[df["origem"] < df["origem"].max()].reset_index(drop=True) if not df.empty else df


def pld_esperado(diretorio: Path = DADOS) -> pd.DataFrame:
    """PLD esperado pelos cenários (R$/MWh, ponderado pelas horas), por execução, origem, método."""
    return _csv(
        "pld_esperado_cenarios.csv",
        diretorio,
        ("execucao_id", "origem", "metodo", "pld_esperado_rs_mwh", "n_cenarios"),
        datas=("origem",),
        textos=("execucao_id", "metodo"),
    )


# ---------------------------------------------------------------- saúde


def saude_execucoes(diretorio: Path = DADOS) -> tuple[pd.DataFrame, dict]:
    df = _csv(
        "saude_execucoes.csv", diretorio, ("run_id", "estado_dag", "task_id", "duracao_task_s")
    )
    return df, manifesto(diretorio)["saude"]["execucoes_da_dag"]


def saude_testes(diretorio: Path = DADOS) -> tuple[pd.DataFrame, dict]:
    df = _csv("saude_testes_dbt.csv", diretorio, ("tipo", "testes", "pass", "warn", "error"))
    return df, manifesto(diretorio)["saude"]["testes_dbt"]


def frescor(diretorio: Path = DADOS) -> pd.DataFrame:
    return _csv("frescor_fontes.csv", diretorio, ("fonte", "ultimo_dado", "idade_dias_no_snapshot"))
