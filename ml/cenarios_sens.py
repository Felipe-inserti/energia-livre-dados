"""Cenários novos das sensibilidades da 6.4 (`disp125`, `disp150`, `clip`), gerados só em disco.

    uv run --env-file .env python -m ml.cenarios_sens gerar --dry-run   # lê, confere, conta
    uv run --env-file .env python -m ml.cenarios_sens gerar             # grava parquet + congelado

Plano: `docs/planejamento/plano_sprint6b.md` (seções 2.1, 2.5 e 6; decisões B1, B5, B6 e B7).
- Três `execucao_id` novos, gerados de **uma** leitura do BigQuery e **sem gravar** no BigQuery:
  `data/cenarios_6b/<sens_id>/{execucao,cenario_consumo,cenario_pld}.parquet` (fora do git) e
  `ml/congelado_6b_<sens_id>.json` (as impressões digitais, que você commita antes de rodar o lote).
- **Só as 5 origens do backtest** (dez/2020 a dez/2024): a origem de produção muda quando outubro
  fechar e não é usada na 6.4.
- **Trava de insumos:** antes de gerar, as impressões dos erros, do PLD e dos pisos de cada origem
  são conferidas contra `ml/congelado_6a.json`. Se os insumos mudaram, aborta: a comparação com o
  caso base deixaria de ser pareada.
- O consumo de `clip` e o PLD de `disp125`/`disp150` são os mesmos valores do caso base (mesma
  semente por origem, mesmos índices sorteados), sob outro `execucao_id`.
- Os parquets do realizado e da previsão não são regerados: vêm de `data/cenarios_6a/`.
"""

import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from ml.cenarios import carregar_dados_pld, impressao_do_pld, impressao_dos_pisos
from ml.cenarios_consumo import (
    N_PADRAO,
    SEMENTE_BASE,
    execucao_id,
    hash_curto,
    hash_dos_erros,
    k_do_dbt,
    ler_erros_e_previstos,
    linhas_de_cenarios,
    origens_de_decisao,
    sortear,
)
from ml.cenarios_pld import (
    TRANSFORMACOES,
    blocos_de_12,
    bootstrap,
    historico_ate,
    meses_alvo,
)
from ml.intervalos import vetores_completos_ate
from ml.otimizacao import Dados, ErroDeCongelamento, ler_congelado
from ml.registro import MODELO_VERSAO
from ml.validacao import HORIZONTES

RAIZ = Path(__file__).resolve().parents[1]
DIR_6B = RAIZ / "data" / "cenarios_6b"
PISO_FATURADO = 10 * 1024 * 1024
CODIGO = (
    "ml/cenarios_sens.py",
    "ml/cenarios.py",
    "ml/cenarios_consumo.py",
    "ml/cenarios_pld.py",
    "ml/piso_pld.py",
    "ml/intervalos.py",
)
# sens_id -> (dispersao, transformacao do PLD). O caso base é (1.0, "deslocamento").
CONJUNTOS_NOVOS = {
    "disp125": (1.25, "deslocamento"),
    "disp150": (1.5, "deslocamento"),
    "clip": (1.0, "clip"),
}
PADRAO = (1.0, "deslocamento")


def caminho_congelado(sens_id: str) -> Path:
    return RAIZ / "ml" / f"congelado_6b_{sens_id}.json"


def extras_do_id(
    pld_hash: dict[str, str],
    pisos_hash: str,
    dispersao: float = 1.0,
    transformacao: str = "deslocamento",
) -> dict:
    """Os `extras` do `execucao_id`. Com os padrões são **exatamente** os do caso base,
    então o id do caso base não muda; `dispersao` e `transformacao` entram só quando diferentes."""
    if transformacao not in TRANSFORMACOES:
        raise ValueError(f"transformação desconhecida: {transformacao!r}")
    extras = {"pld": dict(pld_hash), "pisos": pisos_hash}
    if dispersao != 1.0:
        extras["dispersao"] = dispersao
    if transformacao != "deslocamento":
        extras["transformacao"] = transformacao
    return extras


@dataclass(frozen=True)
class Conjunto:
    sens_id: str
    execucao_id: str
    execucao: pd.DataFrame
    cenario_consumo: pd.DataFrame
    cenario_pld: pd.DataFrame


def insumos_por_origem(erros, previstos, dados_pld, origens) -> dict:
    """Impressões digitais dos insumos de cada origem (iguais para os três conjuntos)."""
    pisos = dados_pld.pisos()
    return {
        "erros": {o: hash_dos_erros(erros, o) for o in origens},
        "pld": {o: impressao_do_pld(historico_ate(dados_pld.serie, o)) for o in origens},
        "pisos": impressao_dos_pisos(pisos, dados_pld.limites),
    }


def conferir_insumos(insumos: dict, congelado_6a: dict) -> None:
    """Os insumos de cada origem devem ser os do caso base (`ml/congelado_6a.json`)."""
    for o, h in insumos["erros"].items():
        esperado = congelado_6a["origens"].get(o.isoformat())
        if esperado is None:
            raise ErroDeCongelamento(f"a origem {o} não está no congelado do caso base")
        for campo, atual in (
            ("erros_hash", h),
            ("pld_hash", insumos["pld"][o]),
            ("pisos_hash", insumos["pisos"]),
        ):
            if esperado[campo] != atual:
                raise ErroDeCongelamento(
                    f"origem {o}: {campo} difere do caso base ({atual} contra {esperado[campo]}); "
                    "a comparação deixaria de ser pareada"
                )


def gerar_conjunto(
    sens_id: str,
    erros,
    previstos: dict,
    dados_pld,
    k: float,
    n: int = N_PADRAO,
    semente: int = SEMENTE_BASE,
    codigo_hash: str = "",
) -> Conjunto:
    """Gera o conjunto de cenários da sensibilidade (função pura dos insumos já lidos)."""
    dispersao, transformacao = CONJUNTOS_NOVOS[sens_id]
    erros = list(erros)
    origens = origens_de_decisao(previstos)
    insumos = insumos_por_origem(erros, previstos, dados_pld, origens)
    pisos = dados_pld.pisos()
    id_ = execucao_id(
        n,
        semente,
        k,
        insumos["erros"],
        extras_do_id(
            {o.isoformat(): h for o, h in insumos["pld"].items()},
            insumos["pisos"],
            dispersao,
            transformacao,
        ),
    )
    consumo, pld, execucoes = [], [], []
    for origem in origens:
        prev = [previstos[origem][h] for h in HORIZONTES]
        consumo += linhas_de_cenarios(
            id_, origem, prev, sortear(erros, origem, n, semente, dispersao), k
        )
        hist = historico_ate(dados_pld.serie, origem)
        for metodo in ("simples", "blocos"):
            for s, cenario in enumerate(
                bootstrap(metodo, hist, origem, n, semente, pisos, dados_pld.limites, transformacao)
            ):
                for h, alvo, (_, valor) in zip(
                    HORIZONTES, meses_alvo(origem), cenario, strict=True
                ):
                    pld.append(
                        {
                            "origem": origem,
                            "metodo": metodo,
                            "cenario": s,
                            "horizonte": h,
                            "mes_alvo": alvo,
                            "pld_rs_mwh": valor,
                        }
                    )
        execucoes.append(
            {
                "origem": origem,
                "modelo_versao": MODELO_VERSAO,
                "n_cenarios": n,
                "semente_base": semente,
                "calibracao": "crescente",
                "n_vetores_consumo": len(vetores_completos_ate(erros, origem)),
                "erros_hash": insumos["erros"][origem],
                "k_consumo": k,
                "n_meses_pld": len(hist),
                "n_blocos_pld": len(blocos_de_12(hist, meses_alvo(origem)[0])),
                "pld_hash": insumos["pld"][origem],
                "pisos_hash": insumos["pisos"],
                "limites_assumidos": False,
                "codigo_hash": codigo_hash,
            }
        )
    colunas = ["origem", "cenario", "horizonte", "mes_alvo", "consumo_mwh"]
    df_consumo = pd.DataFrame(consumo)
    df_consumo["origem"] = [date.fromisoformat(x) for x in df_consumo["origem"]]
    df_consumo["mes_alvo"] = [date.fromisoformat(x) for x in df_consumo["mes_alvo"]]
    return Conjunto(sens_id, id_, pd.DataFrame(execucoes), df_consumo[colunas], pd.DataFrame(pld))


def dados_do_conjunto(base: Dados, c: Conjunto) -> Dados:
    """Dados da avaliação: realizado e previstos do caso base; cenários do conjunto."""
    from dataclasses import replace

    return replace(
        base,
        execucao=c.execucao,
        cenario_consumo=c.cenario_consumo,
        cenario_pld=c.cenario_pld,
    )


def montar_congelado_6b(c: Conjunto, base: Dados) -> dict:
    from ml.otimizacao import impressoes_da_origem

    dados = dados_do_conjunto(base, c)
    ex = c.execucao
    return {
        "sens_id": c.sens_id,
        "execucao_id": c.execucao_id,
        "modelo_versao": MODELO_VERSAO,
        "n_cenarios": int(ex["n_cenarios"].iloc[0]),
        "semente_base": int(ex["semente_base"].iloc[0]),
        "k_consumo": float(ex["k_consumo"].iloc[0]),
        "origens": {o.isoformat(): impressoes_da_origem(dados, o) for o in sorted(ex["origem"])},
    }


def verificar_congelado_6b(c: Conjunto, base: Dados, congelado: dict) -> None:
    """Falha se o conjunto lido não é o congelado (id, N, semente, k, impressões por origem)."""
    atual = montar_congelado_6b(c, base)
    if congelado.get("sens_id") != c.sens_id or congelado.get("execucao_id") != c.execucao_id:
        raise ErroDeCongelamento(f"{c.sens_id}: o congelado é de outra execução")
    for campo in ("n_cenarios", "semente_base", "modelo_versao"):
        if atual[campo] != congelado[campo]:
            raise ErroDeCongelamento(f"{c.sens_id}: {campo} difere do congelado")
    if abs(atual["k_consumo"] - congelado["k_consumo"]) > 1e-18:
        raise ErroDeCongelamento(f"{c.sens_id}: k_consumo difere do congelado")
    if atual["origens"] != congelado["origens"]:
        diferentes = sorted(
            o for o in congelado["origens"] if atual["origens"].get(o) != congelado["origens"][o]
        )
        raise ErroDeCongelamento(f"{c.sens_id}: origens diferentes do congelado: {diferentes}")


def conferir_pareamento(c: Conjunto, base: Dados, congelado_6a: dict) -> None:
    """O que o plano diz de cada conjunto novo, conferido contra o caso base nas 5 origens:
    `clip` tem o **mesmo consumo** do caso base (dispersão 1) e `disp125`/`disp150` têm o **mesmo
    PLD** (transformação do caso base), valor a valor (impressão digital por origem)."""
    from ml.otimizacao import impressoes_da_origem

    dispersao, transformacao = CONJUNTOS_NOVOS[c.sens_id]
    dados = dados_do_conjunto(base, c)
    for o in sorted(c.execucao["origem"]):
        esperado = congelado_6a["origens"][o.isoformat()]
        atual = impressoes_da_origem(dados, o)
        if dispersao == 1.0 and atual["impressao_consumo"] != esperado["impressao_consumo"]:
            raise ErroDeCongelamento(f"{c.sens_id}, origem {o}: o consumo difere do caso base")
        if transformacao == "deslocamento" and atual["impressao_pld"] != esperado["impressao_pld"]:
            raise ErroDeCongelamento(f"{c.sens_id}, origem {o}: o PLD difere do caso base")


def carregar_conjunto(sens_id: str, diretorio: Path = DIR_6B) -> Conjunto:
    pasta = diretorio / sens_id
    execucao = pd.read_parquet(pasta / "execucao.parquet")
    consumo = pd.read_parquet(pasta / "cenario_consumo.parquet")
    pld = pd.read_parquet(pasta / "cenario_pld.parquet")
    for df, cols in (
        (execucao, ["origem"]),
        (consumo, ["origem", "mes_alvo"]),
        (pld, ["origem", "mes_alvo"]),
    ):
        for col in cols:
            df[col] = [pd.Timestamp(x).date() for x in df[col]]
    ids = json.loads((pasta / "id.json").read_text())
    return Conjunto(sens_id, ids["execucao_id"], execucao, consumo, pld)


def salvar_conjunto(c: Conjunto, diretorio: Path = DIR_6B) -> Path:
    pasta = diretorio / c.sens_id
    pasta.mkdir(parents=True, exist_ok=True)
    c.execucao.to_parquet(pasta / "execucao.parquet", index=False)
    c.cenario_consumo.to_parquet(pasta / "cenario_consumo.parquet", index=False)
    c.cenario_pld.to_parquet(pasta / "cenario_pld.parquet", index=False)
    (pasta / "id.json").write_text(json.dumps({"execucao_id": c.execucao_id}) + "\n")
    return pasta


# ---------------------------------------------------------------- nuvem (só leitura)


class _ContaBytes:
    """Envolve o módulo `gcp` e soma os bytes de cada consulta (faturado, ou o piso de 10 MiB)."""

    def __init__(self, gcp):
        self._gcp = gcp
        self.consultas: list[tuple[int, int]] = []

    def executar_consulta(self, cliente, sql, **kw):
        r = self._gcp.executar_consulta(cliente, sql, **kw)
        proc = r.bytes_processados or 0
        self.consultas.append((proc, r.bytes_faturados or max(proc, PISO_FATURADO)))
        return r

    def __getattr__(self, nome):
        return getattr(self._gcp, nome)


def gerar(dry_run: bool, diretorio: Path = DIR_6B) -> int:
    from ml.otimizacao import ARQUIVO_CONGELADO, DIR_DADOS, carregar_dados
    from ml.previsao import _cliente, hash_blob_git

    inicio = time.perf_counter()
    if not dry_run:
        existentes = [s for s in CONJUNTOS_NOVOS if caminho_congelado(s).exists()]
        if existentes:
            raise ErroDeCongelamento(f"já congelados, não se congela duas vezes: {existentes}")
    congelado_6a = ler_congelado(ARQUIVO_CONGELADO)
    base = carregar_dados(DIR_DADOS)
    gcp, cliente = _cliente()
    gcp = _ContaBytes(gcp)
    k = k_do_dbt()
    erros, previstos = ler_erros_e_previstos(gcp, cliente)
    dados_pld = carregar_dados_pld(gcp, cliente)
    origens = origens_de_decisao(previstos)
    conferir_insumos(insumos_por_origem(list(erros), previstos, dados_pld, origens), congelado_6a)
    print(f"insumos conferidos contra ml/congelado_6a.json em {len(origens)} origens")
    t_leitura = time.perf_counter() - inicio
    codigo = hash_curto({c: hash_blob_git(RAIZ / c) for c in CODIGO})
    conjuntos = []
    for sens_id in CONJUNTOS_NOVOS:
        t0 = time.perf_counter()
        c = gerar_conjunto(sens_id, erros, previstos, dados_pld, k, codigo_hash=codigo)
        conjuntos.append(c)
        print(
            f"{sens_id}: execucao_id {c.execucao_id}; {len(c.cenario_consumo)} linhas de consumo, "
            f"{len(c.cenario_pld)} de PLD, {len(c.execucao)} de execução; "
            f"{time.perf_counter() - t0:.1f}s"
        )
    for c in conjuntos:
        conferir_pareamento(c, base, congelado_6a)
    print("pareamento conferido: consumo do clip e PLD de disp125/disp150 iguais aos do caso base")
    ids = {c.execucao_id for c in conjuntos}
    if len(ids) != len(conjuntos) or "51cf99b073fe" in ids:
        raise ErroDeCongelamento("os ids novos colidem entre si ou com o caso base")
    proc = sum(p for p, _ in gcp.consultas)
    fat = sum(f for _, f in gcp.consultas)
    print(
        f"leitura do BigQuery: {len(gcp.consultas)} consultas, {proc:,} processados, "
        f"{fat:,} faturados ({fat / 1024**2:.1f} MiB); leitura {t_leitura:.1f}s; "
        f"total {time.perf_counter() - inicio:.1f}s".replace(",", ".")
    )
    if dry_run:
        print("dry-run: nada gravado (nem parquet, nem congelado)")
        return 0
    for c in conjuntos:
        salvar_conjunto(c, diretorio)
        recarregado = carregar_conjunto(c.sens_id, diretorio)
        congelado = montar_congelado_6b(recarregado, base)
        caminho_congelado(c.sens_id).write_text(
            json.dumps(congelado, indent=2, sort_keys=True) + "\n"
        )
        print(
            f"{c.sens_id}: parquet em {(diretorio / c.sens_id).relative_to(RAIZ)}; congelado em "
            f"{caminho_congelado(c.sens_id).relative_to(RAIZ)} (commite este arquivo)"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="comando", required=True)
    g = sub.add_parser("gerar", help="gera os 3 conjuntos de cenários em disco")
    g.add_argument("--dry-run", action="store_true", help="lê e confere; não grava nada")
    a = ap.parse_args(argv)
    try:
        return gerar(a.dry_run)
    except ErroDeCongelamento as erro:
        print(f"ABORTADO: {erro}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
