"""Backtest 2021-2025 (6.3): três estratégias avaliadas com consumo e PLDp realizados, mês a mês.

    uv run python -m ml.backtest caso-base --so-travas     # só confere as travas, não calcula
    uv run python -m ml.backtest caso-base                 # roda o caso base congelado, uma vez

SÓ O CASO BASE CONGELADO (docs/planejamento/plano_sprint6a.md): f = 10%, λ = 0,5, α = 0,95, PLD em
blocos, N = 2.000, limites simétricos de r, passo de 0,25%, spread de R$ 20, execução de cenários
51cf99b073fe. A linha de comando não aceita outros parâmetros: as sensibilidades são da 6.4.

TRAVAS (qualquer falha aborta ANTES de calcular):
1. o commit de pré-registro é ancestral do HEAD;
2. a árvore do git está limpa (nada sem commit, nem arquivo novo);
3. os dados lidos (parquet de `data/cenarios_6a/`) batem com `ml/congelado_6a.json`;
4. o caso base ainda não foi executado (o log `docs/resultados/backtest_execucoes.jsonl` não tem
   execução com a mesma configuração); `--repetir` libera uma repetição, registrada como tal.

DECISÃO x AVALIAÇÃO. A decisão de cada ano (`volumes_ex_ante`) enxerga só cenários, previstos e
informação até a origem (PLD de meses `<= origem`, consumo de meses `<= origem`). A avaliação
(`custos_realizados`) usa só o consumo e o PLDp realizados do ano e os volumes já decididos. O
mesmo `P_t` vale para as três estratégias. As colunas "ex-ante" (CVaR, PIT) são relatório: usam os
cenários da decisão ao lado do custo realizado e não voltam à decisão.

SAÍDAS (nunca sobrescritas; uma repetição ganha outro sufixo):
`docs/resultados/backtest_caso_base[_execN]_{mensal,anual,economia}.csv` e uma linha nova no log
(append-only) com data e hora, hash do HEAD, hash do pré-registro e os critérios.
"""

import argparse
import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from ml.cenarios_consumo import cvar_superior, horas_do_mes
from ml.custo import SPREAD_PADRAO, custo_anual, custo_mensal, volume_medio_mwm
from ml.otimizacao import (
    ALFA,
    BANDA,
    DIR_DADOS,
    EXECUCAO_CONGELADA,
    LAMBDA,
    METODO_BASE,
    N_CENARIOS,
    PASSO_R,
    SEMENTE,
    Dados,
    ErroDeCongelamento,
    carregar_dados,
    decidir,
    ler_congelado,
    matrizes_da_origem,
    origens_de_decisao,
    verificar_congelamento,
)
from ml.registro import MODELO_VERSAO

RAIZ = Path(__file__).resolve().parents[1]
PREREGISTRO = "02990fdf26529b59bd0aec5883f7ca7e9e2443d0"
RESULTADOS = RAIZ / "docs" / "resultados"
LOG = RESULTADOS / "backtest_execucoes.jsonl"
PREFIXO = "backtest_caso_base"
ESTRATEGIAS = ("ingenua", "pontual", "otimizada")
TOLERANCIA_FAIXA = 1e-9  # MWh: abaixo disso o consumo está na borda, não fora da faixa
RECORTE_COMPLETO = "2021-2025"
RECORTE_SEM_2021 = "2022-2025"


class ErroDeTrava(RuntimeError):
    """Uma trava do pré-registro falhou: nada foi calculado."""


# ---------------------------------------------------------------- critérios e travas


def criterios() -> dict:
    """Os critérios congelados do caso base (plano, seção 4), como vão para o log."""
    return {
        "f": BANDA,
        "lambda": LAMBDA,
        "alfa": ALFA,
        "metodo_pld": METODO_BASE,
        "n_cenarios": N_CENARIOS,
        "semente_base": SEMENTE,
        "passo_r": PASSO_R,
        "limites_r": "[1/(1+f); 1/(1-f)]",
        "desempate": "r mais proximo de 1, depois o menor",
        "spread_rs_mwh": SPREAD_PADRAO,
        "preco": "PLD medio simples das horas do ano t-1 + spread; 2021 = semanal 2020 ponderado",
        "execucao_id": EXECUCAO_CONGELADA,
        "modelo_versao": MODELO_VERSAO,
        "anos": [2021, 2022, 2023, 2024, 2025],
        "estrategias": list(ESTRATEGIAS),
    }


def hash_dos_criterios(c: dict | None = None) -> str:
    c = criterios() if c is None else c
    return hashlib.sha256(json.dumps(c, sort_keys=True).encode()).hexdigest()[:16]


def _git_real(*args: str) -> tuple[int, str]:
    r = subprocess.run(["git", *args], cwd=RAIZ, capture_output=True, text=True)
    return r.returncode, r.stdout.strip()


def conferir_git(git=_git_real, preregistro: str = PREREGISTRO) -> str:
    """Trava 1 e 2: pré-registro ancestral do HEAD e árvore limpa. Devolve o hash do HEAD."""
    rc, _ = git("merge-base", "--is-ancestor", preregistro, "HEAD")
    if rc != 0:
        raise ErroDeTrava(f"o commit de pré-registro {preregistro[:10]} não é ancestral do HEAD")
    rc, sujo = git("status", "--porcelain", "-uall")
    if rc != 0:
        raise ErroDeTrava("não consegui ler o estado do git")
    if sujo:
        primeiras = "; ".join(sujo.splitlines()[:5])
        raise ErroDeTrava(f"a árvore do git não está limpa: {primeiras}")
    rc, head = git("rev-parse", "HEAD")
    if rc != 0 or not head:
        raise ErroDeTrava("não consegui ler o HEAD")
    return head


def ler_log(caminho: Path = LOG) -> list[dict]:
    if not caminho.exists():
        return []
    return [json.loads(x) for x in caminho.read_text().splitlines() if x.strip()]


def acrescentar_log(entrada: dict, caminho: Path = LOG) -> None:
    """Append-only: abre sempre em modo `a`; nunca reescreve o que já está lá."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entrada, sort_keys=True, ensure_ascii=False) + "\n")


def conferir_rodada_unica(log: list[dict], repetir: bool) -> int:
    """Trava 4. Devolve o número desta execução do caso base (1 = a primeira)."""
    anteriores = [
        e
        for e in log
        if e.get("evento") == "caso_base" and e.get("config_hash") == hash_dos_criterios()
    ]
    if anteriores and not repetir:
        raise ErroDeTrava(
            f"o caso base já foi executado {len(anteriores)} vez(es) (log); "
            "uma repetição exige --repetir e fica registrada"
        )
    return len(anteriores) + 1


# ---------------------------------------------------------------- decisão (só ex-ante)


def visao_ex_ante(dados: Dados, origem: date) -> Dados:
    """O que a decisão da origem pode ver: sem o consumo realizado e com o PLD só até a origem."""
    pld = dados.pld_mensal[dados.pld_mensal["mes"] <= origem]
    return replace(dados, pld_mensal=pld, consumo_mensal=None)


def v_ingenua(consumo_mensal: pd.DataFrame, origem: date) -> float:
    """Consumo realizado médio (MWm) do ano da origem (`t−1`), só com meses `<= origem`."""
    c = consumo_mensal[consumo_mensal["mes"] <= origem]
    c = c[c["mes"].map(lambda d: d.year) == origem.year].sort_values("mes")
    meses = [date(origem.year, m, 1) for m in range(1, 13)]
    if c["mes"].tolist() != meses:
        raise ValueError(f"o consumo de {origem.year} não tem os 12 meses até {origem}")
    horas = [horas_do_mes(m) for m in meses]
    if [int(h) for h in c["horas"]] != horas:
        raise ValueError(f"o consumo de {origem.year} tem horas faltando")
    return volume_medio_mwm(c["consumo_mwh"].to_numpy(dtype=float), horas)


def volumes_ex_ante(dados: Dados, origem: date, f: float, **opcoes):
    """({estratégia: V em MWm}, decisão): tudo com informação até a origem."""
    d = decidir(origem, f, visao_ex_ante(dados, origem), **opcoes)
    v = {
        "ingenua": v_ingenua(dados.consumo_mensal, origem),
        "pontual": d.v_pont_mwm,
        "otimizada": d.v_mwm,
    }
    return v, d


# ---------------------------------------------------------------- avaliação (só realizado)


def realizado_do_ano(dados: Dados, ano: int):
    """(consumo MWh, PLDp R$/MWh, horas) dos 12 meses do ano, do realizado."""
    meses = [date(ano, m, 1) for m in range(1, 13)]
    horas = [horas_do_mes(m) for m in meses]
    c = dados.consumo_mensal[dados.consumo_mensal["mes"].isin(meses)].sort_values("mes")
    p = dados.pld_mensal[dados.pld_mensal["mes"].isin(meses)].sort_values("mes")
    if c["mes"].tolist() != meses or p["mes"].tolist() != meses:
        raise ValueError(f"o realizado de {ano} não tem os 12 meses")
    if [int(h) for h in c["horas"]] != horas or not bool(p["mes_completo"].all()):
        raise ValueError(f"o realizado de {ano} tem meses incompletos")
    consumo = c["consumo_mwh"].to_numpy(dtype=float)
    if "consumo_mwh" in p and p["consumo_mwh"].notna().all():
        if not np.allclose(consumo, p["consumo_mwh"].to_numpy(dtype=float), rtol=1e-9, atol=0):
            raise ValueError(f"o consumo de {ano} difere entre a curva mensal e o PLD ponderado")
    return consumo, p["pld_ponderado_rs_mwh"].to_numpy(dtype=float), horas


def custos_realizados(consumo, pld, horas, f: float, preco: float, volumes: dict) -> dict:
    """{estratégia: CustoMensal} com o MESMO `preco` para as três."""
    return {e: custo_mensal(consumo, volumes[e], horas, f, preco, pld) for e in ESTRATEGIAS}


def metricas_ex_ante(vista: Dados, origem, volumes, f, preco, alfa, metodo, realizado_rs) -> dict:
    """CVaR_α, E e PIT do custo realizado nos cenários da decisão, por estratégia (só relatório)."""
    n = int(vista.execucao[vista.execucao["origem"] == origem]["n_cenarios"].iloc[0])
    consumo, pld, meses = matrizes_da_origem(
        vista.cenario_consumo, vista.cenario_pld, origem, metodo, n
    )
    horas = [horas_do_mes(m) for m in meses]
    saida = {}
    for e in ESTRATEGIAS:
        custos = custo_anual(consumo, volumes[e], horas, f, preco, pld)
        saida[e] = {
            "esperado_ex_ante_rs": float(np.mean(custos)),
            "cvar_ex_ante_rs": float(cvar_superior(custos.tolist(), alfa)),
            "pit_custo_realizado": float(np.mean(custos <= realizado_rs[e])),
        }
    return saida


# ---------------------------------------------------------------- relatório


@dataclass(frozen=True)
class Resultado:
    mensal: pd.DataFrame
    anual: pd.DataFrame
    economia: pd.DataFrame


def _pct(parte: float, base: float) -> float:
    return float("nan") if base == 0 else 100.0 * parte / base


def linha_economia(recorte: str, anos: list[int], por_ano: dict) -> dict:
    """Custos somados, valor da previsão, valor da otimização e exposição de um recorte de anos."""
    soma = {
        e: {k: sum(por_ano[a][e][k] for a in anos) for k in ("custo", "descoberto", "sobrando")}
        for e in ESTRATEGIAS
    }
    ing, pont, otim = (soma[e]["custo"] for e in ESTRATEGIAS)
    linha = {
        "recorte": recorte,
        "custo_ingenua_rs": ing,
        "custo_pontual_rs": pont,
        "custo_otimizada_rs": otim,
        "valor_previsao_rs": ing - pont,
        "valor_previsao_pct": _pct(ing - pont, ing),
        "valor_otimizacao_rs": pont - otim,
        "valor_otimizacao_pct": _pct(pont - otim, ing),
        "economia_total_rs": ing - otim,
        "economia_total_pct": _pct(ing - otim, ing),
    }
    for e in ESTRATEGIAS:
        linha[f"descoberto_{e}_mwh"] = soma[e]["descoberto"]
        linha[f"sobrando_{e}_mwh"] = soma[e]["sobrando"]
    for e in ("pontual", "otimizada"):  # pior ano: a menor economia contra a ingênua
        pcts = {
            a: _pct(
                por_ano[a]["ingenua"]["custo"] - por_ano[a][e]["custo"],
                por_ano[a]["ingenua"]["custo"],
            )
            for a in anos
        }
        pior = min(pcts, key=lambda a: (pcts[a], a))
        linha[f"pior_ano_{e}"] = pior
        linha[f"pior_economia_{e}_pct"] = pcts[pior]
    return linha


def executar(
    dados: Dados,
    f: float = BANDA,
    lam: float = LAMBDA,
    alfa: float = ALFA,
    metodo: str = METODO_BASE,
    spread: float = SPREAD_PADRAO,
    passo: float = PASSO_R,
    r_max: float | None = None,
) -> Resultado:
    """Decide cada ano só com o ex-ante e avalia só com o realizado. Função pura dos dados."""
    mensal, anual, por_ano = [], [], {}
    for origem in origens_de_decisao(dados):
        ano = origem.year + 1
        volumes, d = volumes_ex_ante(
            dados, origem, f, lam=lam, alfa=alfa, metodo=metodo, spread=spread, passo=passo,
            r_max=r_max,
        )  # fmt: skip
        consumo, pld, horas = realizado_do_ano(dados, ano)
        res = custos_realizados(consumo, pld, horas, f, d.preco, volumes)
        custo_rs = {e: float(res[e].custo.sum()) for e in ESTRATEGIAS}
        ex = metricas_ex_ante(
            visao_ex_ante(dados, origem), origem, volumes, f, d.preco, alfa, metodo, custo_rs
        )
        por_ano[ano] = {}
        for e in ESTRATEGIAS:
            r = res[e]
            fora = (r.descoberto_mwh > TOLERANCIA_FAIXA) | (r.sobrando_mwh > TOLERANCIA_FAIXA)
            por_ano[ano][e] = {
                "custo": custo_rs[e],
                "descoberto": float(r.descoberto_mwh.sum()),
                "sobrando": float(r.sobrando_mwh.sum()),
            }
            anual.append(
                {
                    "ano": ano,
                    "estrategia": e,
                    "v_mwm": volumes[e],
                    "razao_v_pontual": volumes[e] / volumes["pontual"],
                    "preco_contrato_rs_mwh": d.preco,
                    "custo_rs": custo_rs[e],
                    "descoberto_mwh": por_ano[ano][e]["descoberto"],
                    "sobrando_mwh": por_ano[ano][e]["sobrando"],
                    "meses_fora_da_faixa": int(fora.sum()),
                    "consumo_anual_mwh": float(consumo.sum()),
                    "teto_contratado_mwh": float(r.teto_mwh.sum()),
                    "cobertura_abaixo_de_100": bool(consumo.sum() > r.teto_mwh.sum()),
                    **ex[e],
                }
            )
            for i in range(12):
                mensal.append(
                    {
                        "ano": ano,
                        "mes": i + 1,
                        "estrategia": e,
                        "v_mwm": volumes[e],
                        "consumo_mwh": float(consumo[i]),
                        "contratado_mwh": float(r.contratado_mwh[i]),
                        "piso_mwh": float(r.piso_mwh[i]),
                        "teto_mwh": float(r.teto_mwh[i]),
                        "entregue_mwh": float(r.entregue_mwh[i]),
                        "preco_contrato_rs_mwh": d.preco,
                        "pld_ponderado_rs_mwh": float(pld[i]),
                        "custo_rs": float(r.custo[i]),
                        "descoberto_mwh": float(r.descoberto_mwh[i]),
                        "sobrando_mwh": float(r.sobrando_mwh[i]),
                        "fora_da_faixa": bool(fora[i]),
                    }
                )
    anos = sorted(por_ano)
    linhas = [linha_economia(str(a), [a], por_ano) for a in anos]
    linhas.append(linha_economia(RECORTE_COMPLETO, anos, por_ano))
    sem_2021 = [a for a in anos if a != 2021]
    if sem_2021:
        linhas.append(linha_economia(RECORTE_SEM_2021, sem_2021, por_ano))
    return Resultado(pd.DataFrame(mensal), pd.DataFrame(anual), pd.DataFrame(linhas))


# ---------------------------------------------------------------- execução do caso base


def nomes_das_saidas(resultados: Path, numero: int) -> dict[str, Path]:
    sufixo = "" if numero == 1 else f"_exec{numero}"
    caminhos = {
        k: resultados / f"{PREFIXO}{sufixo}_{k}.csv" for k in ("mensal", "anual", "economia")
    }
    existentes = [c.name for c in caminhos.values() if c.exists()]
    if existentes:
        raise ErroDeTrava(f"as saídas já existem e não são sobrescritas: {', '.join(existentes)}")
    return caminhos


def _rel(caminho: Path) -> Path:
    return caminho.relative_to(RAIZ) if caminho.is_relative_to(RAIZ) else caminho


def _sha(caminho: Path) -> str:
    return hashlib.sha256(caminho.read_bytes()).hexdigest()[:16]


def relatorio(res: Resultado) -> str:
    e = res.economia
    cols = [
        "recorte",
        "custo_ingenua_rs",
        "custo_pontual_rs",
        "custo_otimizada_rs",
        "valor_previsao_rs",
        "valor_previsao_pct",
        "valor_otimizacao_rs",
        "valor_otimizacao_pct",
        "economia_total_rs",
        "economia_total_pct",
    ]
    expo = [c for c in e.columns if c.startswith(("descoberto_", "sobrando_"))]
    pior = [c for c in e.columns if c.startswith("pior_")]
    fmt = {"float_format": lambda x: f"{x:,.2f}"}
    return "\n\n".join(
        [
            "CUSTO E ECONOMIA (R$; % sobre o custo da ingênua)\n"
            + e[cols].to_string(index=False, **fmt),
            "EXPOSIÇÃO (MWh)\n" + e[["recorte", *expo]].to_string(index=False, **fmt),
            "PIOR ANO CONTRA A INGÊNUA\n" + e[["recorte", *pior]].to_string(index=False, **fmt),
            "DECISÃO E RISCO EX-ANTE\n"
            + res.anual[
                [
                    "ano",
                    "estrategia",
                    "v_mwm",
                    "razao_v_pontual",
                    "preco_contrato_rs_mwh",
                    "custo_rs",
                    "cvar_ex_ante_rs",
                    "pit_custo_realizado",
                    "meses_fora_da_faixa",
                    "cobertura_abaixo_de_100",
                ]
            ].to_string(index=False, float_format=lambda x: f"{x:,.4f}"),
        ]
    )


def rodar_caso_base(
    repetir: bool = False,
    so_travas: bool = False,
    git=_git_real,
    diretorio: Path = DIR_DADOS,
    resultados: Path = RESULTADOS,
    log: Path = LOG,
    agora=lambda: datetime.now(UTC),
) -> int:
    head = conferir_git(git)
    dados = carregar_dados(diretorio)
    try:
        verificar_congelamento(dados, ler_congelado())
    except ErroDeCongelamento as erro:
        raise ErroDeTrava(
            f"a leitura congelada não bate com ml/congelado_6a.json: {erro}"
        ) from erro
    numero = conferir_rodada_unica(ler_log(log), repetir)
    saidas = nomes_das_saidas(resultados, numero)
    print(f"travas ok: HEAD {head[:10]}, pré-registro {PREREGISTRO[:10]}, execução nº {numero}")
    if so_travas:
        print("--so-travas: nada calculado")
        return 0

    res = executar(dados)
    resultados.mkdir(parents=True, exist_ok=True)
    for chave, caminho in saidas.items():
        getattr(res, chave).to_csv(caminho, index=False, float_format="%.6f")
    print(relatorio(res))
    manifest = diretorio / "manifest.json"
    acrescentar_log(
        {
            "evento": "caso_base",
            "quando_utc": agora().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "numero": numero,
            "repeticao": numero > 1,
            "head": head,
            "preregistro": PREREGISTRO,
            "config_hash": hash_dos_criterios(),
            "criterios": criterios(),
            "entradas": json.loads(manifest.read_text()) if manifest.exists() else None,
            "saidas": {c.name: _sha(c) for c in saidas.values()},
        },
        log,
    )
    print(f"\nsaídas em {_rel(resultados)}; log: {_rel(log)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="comando", required=True)
    c = sub.add_parser("caso-base", help="o caso base congelado (e nada mais)")
    c.add_argument("--so-travas", action="store_true", help="confere as travas e não calcula")
    c.add_argument("--repetir", action="store_true", help="libera uma repetição (registrada)")
    a = ap.parse_args(argv)
    try:
        return rodar_caso_base(repetir=a.repetir, so_travas=a.so_travas)
    except ErroDeTrava as erro:
        print(f"ABORTADO, nada foi calculado: {erro}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
