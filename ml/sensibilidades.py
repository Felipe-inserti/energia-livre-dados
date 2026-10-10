"""Sensibilidades da 6.4 (Sprint 6, Parte B): 13 execuções, cada uma uma vez, sobre o caso base.

    uv run python -m ml.sensibilidades todas --so-travas   # só confere as travas, não calcula
    uv run python -m ml.sensibilidades todas               # o lote: cada sens_id roda UMA vez
    uv run python -m ml.sensibilidades resumo              # tabelas lado a lado

Plano pré-registrado: `docs/planejamento/plano_sprint6b.md` (commit `PREREGISTRO_6B`). A linha de
comando só aceita os `sens_id` do REGISTRO (o mesmo bloco JSON da seção 1 do plano; um teste os
compara) e nenhum parâmetro livre. Uma variável por vez em relação ao caso base, sem combinações.

TRAVAS (qualquer falha aborta ANTES de calcular):
1. `PREREGISTRO_6B` é ancestral do HEAD e já está numa referência remota (foi enviado ao GitHub);
2. árvore do git limpa, checada UMA vez no início do lote (as saídas do próprio lote a sujam);
3. dados conferidos: cenários congelados contra `ml/congelado_6a.json`, os três conjuntos novos
   contra `ml/congelado_6b_<sens_id>.json`, e os parquets do realizado contra o `manifest.json`;
4. o caso base está intacto: o hash dos três CSV dele é o registrado no log dele;
5. rodada única por `sens_id`: log PRÓPRIO append-only
   (`docs/resultados/sensibilidades_execucoes.jsonl`;
   o log do caso base nunca é aberto para escrita). Uma `sens_id` já no log não roda de novo; o lote
   que cai no meio, quando chamado outra vez, executa só as que faltam (retomada, não repetição);
6. saídas `sens_<sens_id>_*` nunca são sobrescritas; saída sem linha no log aborta.

Os cálculos são os do caso base (`ml.backtest.executar`, sem alterá-lo): só mudam os parâmetros do
registro. As saídas levam o `sens_id` no nome e nunca tocam `backtest_caso_base_*`.
"""

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from ml import backtest as bt
from ml.backtest import ErroDeTrava, Resultado
from ml.cenarios_consumo import hash_curto
from ml.cenarios_sens import (
    DIR_6B,
    caminho_congelado,
    carregar_conjunto,
    dados_do_conjunto,
    verificar_congelado_6b,
)
from ml.otimizacao import (
    DIR_DADOS,
    EXECUCAO_CONGELADA,
    Dados,
    ErroDeCongelamento,
    carregar_dados,
    ler_congelado,
    verificar_congelamento,
)

PREREGISTRO_6B = "4c02987d0270dd91639cdc410d801fe550710af9"
RAIZ = bt.RAIZ
RESULTADOS = bt.RESULTADOS
LOG = RESULTADOS / "sensibilidades_execucoes.jsonl"
LOG_CASO_BASE = bt.LOG
PREFIXO = "sens"
SAIDAS = ("mensal", "anual", "economia")

# O registro: idêntico ao bloco JSON da seção 1 do plano (teste confere).
REGISTRO: tuple[dict, ...] = (
    {"sens_id": "f00", "muda": {"f": 0.0}, "cenarios": "congelados"},
    {"sens_id": "f05", "muda": {"f": 0.05}, "cenarios": "congelados"},
    {"sens_id": "f15", "muda": {"f": 0.15}, "cenarios": "congelados"},
    {"sens_id": "spread00", "muda": {"spread": 0.0}, "cenarios": "congelados"},
    {"sens_id": "spread40", "muda": {"spread": 40.0}, "cenarios": "congelados"},
    {"sens_id": "lam00", "muda": {"lambda": 0.0}, "cenarios": "congelados"},
    {"sens_id": "lam10", "muda": {"lambda": 1.0}, "cenarios": "congelados"},
    {"sens_id": "alfa90", "muda": {"alfa": 0.9}, "cenarios": "congelados"},
    {"sens_id": "rmax120", "muda": {"r_max": 1.2}, "cenarios": "congelados"},
    {"sens_id": "pldsimples", "muda": {"metodo_pld": "simples"}, "cenarios": "congelados"},
    {"sens_id": "disp125", "muda": {"dispersao": 1.25}, "cenarios": "novos"},
    {"sens_id": "disp150", "muda": {"dispersao": 1.5}, "cenarios": "novos"},
    {"sens_id": "clip", "muda": {"transformacao_pld": "clip"}, "cenarios": "novos"},
)
IDS = tuple(s["sens_id"] for s in REGISTRO)
# Parâmetros que a avaliação recebe (`ml.backtest.executar`); os demais são dos cenários.
PARAMETROS_DA_AVALIACAO = {
    "f": "f",
    "spread": "spread",
    "lambda": "lam",
    "alfa": "alfa",
    "r_max": "r_max",
    "metodo_pld": "metodo",
}
# Onde ingênua e pontual são idênticas ao caso base (plano, seção 3) e onde também o ex-ante
INVARIANTES_INGENUA_PONTUAL = frozenset(
    {"lam00", "lam10", "alfa90", "rmax120", "pldsimples", "disp125", "disp150", "clip"}
)
INVARIANTES_EX_ANTE = frozenset({"lam00", "lam10", "rmax120"})


# ---------------------------------------------------------------- registro e critérios


def buscar(sens_id: str) -> dict:
    for s in REGISTRO:
        if s["sens_id"] == sens_id:
            return s
    raise ErroDeTrava(f"sens_id fora do registro pré-registrado: {sens_id!r}")


def criterios_do_caso_base() -> dict:
    """Os critérios do caso base, com os parâmetros que só as sensibilidades variam explícitos."""
    return {
        **bt.criterios(),
        "r_max": None,
        "dispersao": 1.0,
        "transformacao_pld": "deslocamento",
    }


# Nome no registro (o do plano) -> nome no critério do caso base
CHAVE_DO_CRITERIO = {"spread": "spread_rs_mwh"}


def criterios(sens: dict, execucao_id: str = EXECUCAO_CONGELADA) -> dict:
    c = criterios_do_caso_base()
    c.update({CHAVE_DO_CRITERIO.get(k, k): v for k, v in sens["muda"].items()})
    c["execucao_id"] = execucao_id
    return c


def diferencas(sens_id: str, execucao_id: str) -> dict:
    """{parâmetro: [caso base, sensibilidade]} (o `execucao_id` não conta: deriva dos cenários)."""
    base, nova = criterios_do_caso_base(), criterios(buscar(sens_id), execucao_id)
    nome = {v: k for k, v in CHAVE_DO_CRITERIO.items()}
    return {
        nome.get(k, k): [base[k], nova[k]]
        for k in nova
        if k != "execucao_id" and base[k] != nova[k]
    }


def hash_da_configuracao(sens_id: str, crit: dict) -> str:
    return hashlib.sha256(
        json.dumps({"sens_id": sens_id, **crit}, sort_keys=True).encode()
    ).hexdigest()[:16]


def parametros_da_avaliacao(sens: dict) -> dict:
    return {
        PARAMETROS_DA_AVALIACAO[k]: v
        for k, v in sens["muda"].items()
        if k in PARAMETROS_DA_AVALIACAO
    }


# ---------------------------------------------------------------- travas


def conferir_git_6b(git=bt._git_real, preregistro: str = PREREGISTRO_6B) -> str:
    """Travas 1 e 2: pré-registro ancestral do HEAD, enviado ao remoto, árvore limpa."""
    head = bt.conferir_git(git, preregistro)
    rc, remotos = git("branch", "-r", "--contains", preregistro)
    if rc != 0 or not remotos.strip():
        raise ErroDeTrava(
            f"o pré-registro {preregistro[:10]} não está em nenhuma referência remota (push?)"
        )
    return head


def _sha(caminho: Path) -> str:
    return hashlib.sha256(caminho.read_bytes()).hexdigest()[:16]


def conferir_realizado(diretorio: Path = DIR_DADOS) -> dict:
    """Os parquets lidos são os do caso base (hash do `manifest.json`). Devolve o manifesto."""
    manifesto = json.loads((diretorio / "manifest.json").read_text())
    for nome, esperado in manifesto["hash_dos_arquivos"].items():
        atual = _sha(diretorio / f"{nome}.parquet")
        if atual != esperado:
            raise ErroDeTrava(
                f"{nome}.parquet difere do manifesto do caso base ({atual} contra {esperado})"
            )
    return manifesto


def conferir_caso_base_intacto(
    resultados: Path = RESULTADOS, log_base: Path = LOG_CASO_BASE
) -> str:
    """Trava 4: o hash dos CSV do caso base é o do log dele. Devolve o hash do log do caso base."""
    entradas = [
        e for e in bt.ler_log(log_base) if e.get("evento") == "caso_base" and e.get("numero") == 1
    ]
    if len(entradas) != 1:
        raise ErroDeTrava("o log do caso base não tem a execução nº 1")
    for nome, esperado in entradas[0]["saidas"].items():
        caminho = resultados / nome
        if not caminho.exists() or _sha(caminho) != esperado:
            raise ErroDeTrava(f"o arquivo do caso base {nome} não é o registrado no log")
    return _sha(log_base)


def saidas_de(sens_id: str, resultados: Path = RESULTADOS) -> dict[str, Path]:
    return {k: resultados / f"{PREFIXO}_{sens_id}_{k}.csv" for k in SAIDAS}


def entradas_do_log(log: list[dict], sens_id: str, config_hash: str) -> list[dict]:
    return [
        e
        for e in log
        if e.get("evento") == "sensibilidade"
        and e.get("sens_id") == sens_id
        and e.get("config_hash") == config_hash
    ]


def conferir_rodada_unica(log: list[dict], sens_id: str, config_hash: str) -> None:
    """Trava 5: uma `sens_id` com esta configuração já no log não roda de novo."""
    if entradas_do_log(log, sens_id, config_hash):
        raise ErroDeTrava(
            f"{sens_id} já foi executada (log); sem repetição nesta Parte (seria uma v2)"
        )


def conferir_saidas_livres(sens_id: str, resultados: Path = RESULTADOS) -> None:
    """Trava 6: nenhuma saída `sens_<sens_id>_*` existe."""
    existentes = [c.name for c in saidas_de(sens_id, resultados).values() if c.exists()]
    if existentes:
        raise ErroDeTrava(f"saída sem linha no log, não sobrescrita: {', '.join(existentes)}")


# ---------------------------------------------------------------- dados de cada sensibilidade


def dados_da_sensibilidade(
    sens: dict, base: Dados, diretorio_6b: Path = DIR_6B
) -> tuple[Dados, str, dict]:
    """(dados, execucao_id, congelado). Congelados: já conferidos contra `congelado_6a.json`.
    Novos: o conjunto em disco é conferido contra `congelado_6b_<sens_id>.json`."""
    if sens["cenarios"] == "congelados":
        congelado = ler_congelado()
        return base, EXECUCAO_CONGELADA, congelado
    sens_id = sens["sens_id"]
    caminho = caminho_congelado(sens_id)
    if not caminho.exists() or not (diretorio_6b / sens_id / "execucao.parquet").exists():
        raise ErroDeTrava(
            f"{sens_id}: faltam os cenários novos ou o congelado ({caminho.name}); "
            "rode `python -m ml.cenarios_sens gerar` e commite o congelado"
        )
    conjunto = carregar_conjunto(sens_id, diretorio_6b)
    congelado = json.loads(caminho.read_text())
    try:
        verificar_congelado_6b(conjunto, base, congelado)
    except ErroDeCongelamento as erro:
        raise ErroDeTrava(str(erro)) from erro
    return dados_do_conjunto(base, conjunto), conjunto.execucao_id, congelado


# ---------------------------------------------------------------- execução


def executar_sensibilidade(sens: dict, dados: Dados) -> Resultado:
    """A avaliação do caso base com os parâmetros do registro (função pura dos dados)."""
    return bt.executar(dados, **parametros_da_avaliacao(sens))


def _com_identidade(df: pd.DataFrame, sens_id: str, config_hash: str) -> pd.DataFrame:
    df = df.copy()
    df.insert(0, "config_hash", config_hash)
    df.insert(0, "sens_id", sens_id)
    return df


def gravar_saidas(
    res: Resultado, sens_id: str, config_hash: str, resultados: Path
) -> dict[str, Path]:
    """Escreve num nome temporário e renomeia; nunca sobrescreve."""
    conferir_saidas_livres(sens_id, resultados)
    resultados.mkdir(parents=True, exist_ok=True)
    destinos = saidas_de(sens_id, resultados)
    for chave, destino in destinos.items():
        tmp = destino.with_suffix(".csv.tmp")
        _com_identidade(getattr(res, chave), sens_id, config_hash).to_csv(
            tmp, index=False, float_format="%.6f"
        )
        tmp.rename(destino)
    return destinos


def rodar_sensibilidade(
    sens: dict,
    dados: Dados,
    execucao_id: str,
    congelado: dict,
    head: str,
    manifesto: dict | None,
    hash_log_base: str,
    log: Path = LOG,
    resultados: Path = RESULTADOS,
    agora=lambda: datetime.now(UTC),
) -> Resultado:
    """Roda UMA sensibilidade: trava de repetição, cálculo, saídas, e o log por último."""
    sens_id = sens["sens_id"]
    crit = criterios(sens, execucao_id)
    config = hash_da_configuracao(sens_id, crit)
    entradas = bt.ler_log(log)
    conferir_rodada_unica(entradas, sens_id, config)
    conferir_saidas_livres(sens_id, resultados)
    res = executar_sensibilidade(sens, dados)
    destinos = gravar_saidas(res, sens_id, config, resultados)
    bt.acrescentar_log(
        {
            "evento": "sensibilidade",
            "sens_id": sens_id,
            "quando_utc": agora().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "head": head,
            "preregistro": PREREGISTRO_6B,
            "config_hash": config,
            "criterios": crit,
            "muda": diferencas(sens_id, execucao_id),
            "execucao_id": execucao_id,
            "impressao_dos_cenarios": hash_curto(congelado["origens"]),
            "hash_log_caso_base": hash_log_base,
            "entradas": manifesto,
            "saidas": {c.name: _sha(c) for c in destinos.values()},
        },
        log,
    )
    return res


def rodar_lote(
    so_travas: bool = False,
    git=bt._git_real,
    diretorio: Path = DIR_DADOS,
    diretorio_6b: Path = DIR_6B,
    resultados: Path = RESULTADOS,
    log: Path = LOG,
    log_base: Path = LOG_CASO_BASE,
    agora=lambda: datetime.now(UTC),
) -> int:
    head = conferir_git_6b(git)
    manifesto = conferir_realizado(diretorio)
    base = carregar_dados(diretorio)
    try:
        verificar_congelamento(base, ler_congelado())
    except ErroDeCongelamento as erro:
        raise ErroDeTrava(
            f"a leitura congelada não bate com ml/congelado_6a.json: {erro}"
        ) from erro
    hash_log_base = conferir_caso_base_intacto(resultados, log_base)
    entradas = bt.ler_log(log)
    preparadas, pendentes, feitas = {}, [], []
    for sens in REGISTRO:
        dados, id_, congelado = dados_da_sensibilidade(sens, base, diretorio_6b)
        preparadas[sens["sens_id"]] = (dados, id_, congelado)
        config = hash_da_configuracao(sens["sens_id"], criterios(sens, id_))
        if entradas_do_log(entradas, sens["sens_id"], config):
            if any(not c.exists() for c in saidas_de(sens["sens_id"], resultados).values()):
                raise ErroDeTrava(f"{sens['sens_id']} está no log, mas falta uma saída")
            feitas.append(sens["sens_id"])
        else:
            conferir_saidas_livres(sens["sens_id"], resultados)
            pendentes.append(sens)
    print(
        f"travas ok: HEAD {head[:10]}, pré-registro {PREREGISTRO_6B[:10]}; "
        f"{len(feitas)} já executadas, {len(pendentes)} a executar de {len(REGISTRO)}"
    )
    if so_travas:
        for s in pendentes:
            d = diferencas(s["sens_id"], preparadas[s["sens_id"]][1])
            print(f"  {s['sens_id']}: muda {d}; cenários {preparadas[s['sens_id']][1]}")
        print("--so-travas: nada calculado")
        return 0
    for sens in pendentes:
        dados, id_, congelado = preparadas[sens["sens_id"]]
        res = rodar_sensibilidade(
            sens, dados, id_, congelado, head, manifesto, hash_log_base, log, resultados, agora
        )
        e = res.economia.set_index("recorte").loc[bt.RECORTE_COMPLETO]
        print(
            f"{sens['sens_id']}: valor da previsão R$ {e['valor_previsao_rs']:,.2f}; "
            f"valor da otimização R$ {e['valor_otimizacao_rs']:,.2f}; "
            f"economia total R$ {e['economia_total_rs']:,.2f} ({e['economia_total_pct']:.3f}%)"
        )
    print(f"\nsaídas em {bt._rel(resultados)}; log: {bt._rel(log)}")
    return 0


# ---------------------------------------------------------------- resumo (função pura das saídas)

RECORTES_RESUMO = (bt.RECORTE_COMPLETO, bt.RECORTE_SEM_2021)
BANDA_F = (("f00", 0.0), ("f05", 0.05), ("caso_base", 0.10), ("f15", 0.15))
COLUNAS_VALOR = (
    "valor_previsao_rs",
    "valor_previsao_pct",
    "valor_otimizacao_rs",
    "valor_otimizacao_pct",
    "economia_total_rs",
    "economia_total_pct",
)


def ler_saidas(resultados: Path = RESULTADOS) -> dict[str, dict[str, pd.DataFrame]]:
    """{sens_id: {anual, economia, mensal}}, com `caso_base` primeiro (arquivos do caso base)."""
    saida = {"caso_base": {k: pd.read_csv(resultados / f"{bt.PREFIXO}_{k}.csv") for k in SAIDAS}}
    for sens_id in IDS:
        saida[sens_id] = {k: pd.read_csv(c) for k, c in saidas_de(sens_id, resultados).items()}
    return saida


def descricao_do_parametro(sens_id: str) -> str:
    if sens_id == "caso_base":
        return "caso base"
    return ", ".join(f"{k}={v}" for k, v in buscar(sens_id)["muda"].items())


def _anos(anual: pd.DataFrame) -> list[int]:
    return sorted(int(a) for a in anual["ano"].unique())


def _r_otimizada(anual: pd.DataFrame) -> dict[int, float]:
    o = anual[anual["estrategia"] == "otimizada"].set_index("ano")
    return {int(a): float(o.loc[a, "razao_v_pontual"]) for a in o.index}


def tabela_resumo(saidas: dict) -> pd.DataFrame:
    linhas = []
    for sens_id, t in saidas.items():
        e = t["economia"].set_index(t["economia"]["recorte"].astype(str))
        r = _r_otimizada(t["anual"])
        for recorte in RECORTES_RESUMO:
            x = e.loc[recorte]
            linhas.append(
                {
                    "sens_id": sens_id,
                    "parametro": descricao_do_parametro(sens_id),
                    "recorte": recorte,
                    **{c: float(x[c]) for c in COLUNAS_VALOR},
                    "pior_ano_otimizada": int(x["pior_ano_otimizada"]),
                    "pior_economia_otimizada_pct": float(x["pior_economia_otimizada_pct"]),
                    "descoberto_otimizada_mwh": float(x["descoberto_otimizada_mwh"]),
                    "sobrando_otimizada_mwh": float(x["sobrando_otimizada_mwh"]),
                    **{f"r_{a}": r[a] for a in _anos(t["anual"])},
                }
            )
    return pd.DataFrame(linhas)


def tabela_por_ano(saidas: dict) -> pd.DataFrame:
    linhas = []
    for sens_id, t in saidas.items():
        e = t["economia"].set_index(t["economia"]["recorte"].astype(str))
        o = t["anual"][t["anual"]["estrategia"] == "otimizada"].set_index("ano")
        for a in _anos(t["anual"]):
            linhas.append(
                {
                    "sens_id": sens_id,
                    "ano": a,
                    "valor_previsao_rs": float(e.loc[str(a), "valor_previsao_rs"]),
                    "valor_otimizacao_rs": float(e.loc[str(a), "valor_otimizacao_rs"]),
                    "r_otimizada": float(o.loc[a, "razao_v_pontual"]),
                    "v_otimizada_mwm": float(o.loc[a, "v_mwm"]),
                    "meses_fora_otimizada": int(o.loc[a, "meses_fora_da_faixa"]),
                    "cobertura_abaixo_de_100_otimizada": bool(o.loc[a, "cobertura_abaixo_de_100"]),
                }
            )
    return pd.DataFrame(linhas)


def tabela_banda_f(saidas: dict) -> pd.DataFrame:
    linhas = []
    for sens_id, f in BANDA_F:
        t = saidas[sens_id]
        e = t["economia"].set_index(t["economia"]["recorte"].astype(str))
        a = t["anual"]
        r_min, r_max = 1 / (1 + f), 1 / (1 - f)
        todos = _anos(a)
        for recorte in [*map(str, todos), *RECORTES_RESUMO]:
            anos = (
                [int(recorte)]
                if recorte.isdigit()
                else (todos if recorte == bt.RECORTE_COMPLETO else [x for x in todos if x != 2021])
            )
            sel = a[a["ano"].isin(anos)]
            linha = {
                "f": f,
                "sens_id": sens_id,
                "recorte": recorte,
                "limite_r_min": r_min,
                "limite_r_max": r_max,
            }
            linha.update({c: float(e.loc[recorte, c]) for c in COLUNAS_VALOR})
            for est in bt.ESTRATEGIAS:
                x = sel[sel["estrategia"] == est]
                linha[f"descoberto_{est}_mwh"] = float(x["descoberto_mwh"].sum())
                linha[f"sobrando_{est}_mwh"] = float(x["sobrando_mwh"].sum())
                linha[f"meses_fora_{est}"] = int(x["meses_fora_da_faixa"].sum())
            o = sel[sel["estrategia"] == "otimizada"]
            linha["r_otimizada"] = (
                float(o["razao_v_pontual"].iloc[0]) if recorte.isdigit() else np.nan
            )
            linhas.append(linha)
    return pd.DataFrame(linhas)


def tabela_invariancias(saidas: dict, tol: float = 1e-5) -> pd.DataFrame:
    """Para cada sensibilidade, o que permanece idêntico ao caso base (seção 3 do plano)."""
    base = saidas["caso_base"]["anual"].set_index(["ano", "estrategia"]).sort_index()
    ex_ante = ["esperado_ex_ante_rs", "cvar_ex_ante_rs", "pit_custo_realizado"]
    linhas = []
    for sens_id in IDS:
        a = saidas[sens_id]["anual"].set_index(["ano", "estrategia"]).sort_index()
        linha = {"sens_id": sens_id}
        for est in ("ingenua", "pontual"):
            b, n = base.xs(est, level="estrategia"), a.xs(est, level="estrategia")
            linha[f"{est}_custo_igual"] = bool(
                np.allclose(b["custo_rs"], n["custo_rs"], rtol=0, atol=tol)
            )
            linha[f"{est}_v_igual"] = bool(np.allclose(b["v_mwm"], n["v_mwm"], rtol=0, atol=1e-6))
            linha[f"{est}_exposicao_igual"] = bool(
                np.allclose(
                    b[["descoberto_mwh", "sobrando_mwh"]],
                    n[["descoberto_mwh", "sobrando_mwh"]],
                    rtol=0,
                    atol=tol,
                )
            )
            linha[f"{est}_ex_ante_igual"] = bool(
                np.allclose(b[ex_ante], n[ex_ante], rtol=0, atol=tol)
            )
        b, n = base.xs("otimizada", level="estrategia"), a.xs("otimizada", level="estrategia")
        iguais = [
            int(y)
            for y in b.index
            if abs(b.loc[y, "razao_v_pontual"] - n.loc[y, "razao_v_pontual"]) <= 1e-6
        ]
        linha["otimizada_anos_r_igual"] = " ".join(map(str, iguais))
        linha["otimizada_n_anos_r_igual"] = len(iguais)
        linha["otimizada_custo_igual_onde_r_igual"] = bool(
            iguais
            and np.allclose(b.loc[iguais, "custo_rs"], n.loc[iguais, "custo_rs"], rtol=0, atol=tol)
        )
        linhas.append(linha)
    return pd.DataFrame(linhas)


def gerar_resumos(resultados: Path = RESULTADOS) -> dict[str, Path]:
    """Exige as 13 sensibilidades no log; escreve as quatro tabelas (regeráveis, nunca tocam as
    saídas individuais nem o caso base)."""
    log = bt.ler_log(resultados / LOG.name)
    feitas = {e["sens_id"] for e in log if e.get("evento") == "sensibilidade"}
    if feitas != set(IDS):
        raise ErroDeTrava(f"faltam sensibilidades no log: {sorted(set(IDS) - feitas)}")
    saidas = ler_saidas(resultados)
    tabelas = {
        "sens_resumo.csv": tabela_resumo(saidas),
        "sens_resumo_por_ano.csv": tabela_por_ano(saidas),
        "sens_banda_f.csv": tabela_banda_f(saidas),
        "sens_invariancias.csv": tabela_invariancias(saidas),
    }
    caminhos = {}
    for nome, df in tabelas.items():
        caminhos[nome] = resultados / nome
        df.to_csv(caminhos[nome], index=False, float_format="%.6f")
    return caminhos


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="comando", required=True)
    t = sub.add_parser("todas", help="o lote das 13 sensibilidades (cada uma, uma vez)")
    t.add_argument("--so-travas", action="store_true", help="confere as travas e não calcula")
    sub.add_parser("resumo", help="tabelas lado a lado, a partir das saídas já gravadas")
    a = ap.parse_args(argv)
    try:
        if a.comando == "todas":
            return rodar_lote(so_travas=a.so_travas)
        for nome, caminho in gerar_resumos().items():
            print(f"{nome}: {bt._rel(caminho)}")
        return 0
    except ErroDeTrava as erro:
        print(f"ABORTADO, nada foi calculado: {erro}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
