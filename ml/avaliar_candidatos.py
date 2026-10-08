"""Avalia os candidatos da Sprint 5 na validação temporal e grava os resultados.

    uv run --env-file .env python -m ml.avaliar_candidatos --periodo desenvolvimento --estimar
    uv run --env-file .env python -m ml.avaliar_candidatos --periodo desenvolvimento --jobs 4

MESMA validação dos baselines (`ml/validacao.py`): origem móvel, h = 1..12, só `mes_utilizavel`,
cada modelo recebe só `visao_na_origem`. LÊ a série mensal do SE/CO em `marts.fct_carga_mensal` (só
leitura, com teto de bytes) e a guarda em `data/modelos/`; NÃO grava na nuvem.

SÉRIES. `original` (desenvolvimento: consistente até fev/2021, sem quebra de definição) e
`reconstruida` (`carga_ajustada_reconstruida_mwmed`, desde 2015: o que o teste final treina).

ROBUSTEZ. Cada origem de cada modelo é gravada em `data/modelos/parcial/` assim que termina, e uma
origem já feita é pulada ao reiniciar. `--estimar` mede o tempo de uma origem de cada modelo e
projeta o total ANTES de rodar. `--passo 3` usa uma origem a cada 3 meses (mar, jun, set, dez).

SAÍDAS. Com `--passo 1` e todos os candidatos, vão para `docs/resultados/` (prefixo
`candidatos_<periodo>_<serie>`); qualquer outra execução é exploração e vai para
`data/modelos/exploracao/`.

O TESTE FINAL só roda com `--liberar-teste-final`, depois do Checkpoint B.
"""

import os

os.environ.setdefault("OMP_NUM_THREADS", "1")  # um processo por modelo; evita disputa de núcleos
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import argparse  # noqa: E402
import csv  # noqa: E402
import json  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from concurrent.futures import ProcessPoolExecutor  # noqa: E402
from dataclasses import replace  # noqa: E402
from datetime import UTC, date, datetime  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402

from ml.avaliar import gravar_csv, referencia_git  # noqa: E402
from ml.escolha import escolher  # noqa: E402
from ml.metricas import Registro, erro_anual, metricas, por_horizonte  # noqa: E402
from ml.registro import (  # noqa: E402
    BASES,
    CANDIDATO_DO_TESTE_FINAL,
    CANDIDATOS,
    COMBINACOES,
    INGENUO,
    LIMIAR_PP,
    REGRA_SPRINT_6,
    RESSALVA_VITORIA,
)
from ml.validacao import (  # noqa: E402
    HORIZONTES,
    PERIODOS,
    Periodo,
    Serie,
    pares,
    serie_utilizavel,
    visao_na_origem,
)

RAIZ = Path(__file__).resolve().parents[1]
DADOS = RAIZ / "data" / "modelos"
SAIDA_FINAL = RAIZ / "docs" / "resultados"
SUBMERCADO = "SE"
COLUNA = {"original": "carga_original_mwmed", "reconstruida": "carga_ajustada_reconstruida_mwmed"}
TETO_BYTES = 100 * 1024 * 1024
SEMENTE_BOOTSTRAP = 0
REPLICAS = 2000
CAMPOS_PARCIAL = ("origem", "horizonte", "alvo", "previsto", "real", "segundos")


# ------------------------------------------------ série (nuvem uma vez, depois disco)


def caminho_serie(periodo: Periodo, serie: str) -> Path:
    return DADOS / f"serie_{periodo.nome}_{serie}.csv"


def carregar_serie(periodo: Periodo, serie: str, recarregar: bool = False) -> Path:
    caminho = caminho_serie(periodo, serie)
    if caminho.exists() and not recarregar:
        return caminho
    from ingestion.common import gcp
    from ingestion.common.config import carregar_config

    sql = f"""
        SELECT mes, {COLUNA[serie]} AS valor, mes_utilizavel
        FROM `marts.fct_carga_mensal`
        WHERE codigo_submercado = '{SUBMERCADO}' AND mes <= DATE '{periodo.alvo_fim}'
        ORDER BY mes"""
    res = gcp.executar_consulta(
        gcp.cliente_bigquery(carregar_config()), sql, max_bytes_faturados=TETO_BYTES
    )
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["mes", "valor", "mes_utilizavel"])
        for linha in res.linhas:
            w.writerow(
                [
                    linha["mes"],
                    "" if linha["valor"] is None else linha["valor"],
                    linha["mes_utilizavel"],
                ]
            )
    return caminho


def ler_serie(caminho: Path) -> Serie:
    with caminho.open(encoding="utf-8") as f:
        linhas = [
            {
                "mes": date.fromisoformat(r["mes"]),
                "valor": float(r["valor"]) if r["valor"] != "" else None,
                "mes_utilizavel": r["mes_utilizavel"] == "True",
            }
            for r in csv.DictReader(f)
        ]
    return serie_utilizavel(linhas, "valor")


# ------------------------------------------------ execução por modelo, com checkpoint


def origens_do_periodo(periodo: Periodo, passo: int) -> list[date]:
    todas = sorted({p.origem for p in pares(periodo)})
    return todas if passo == 1 else [o for o in todas if o.month % passo == 0]


def arquivos_parcial(parcial: Path, periodo: Periodo, serie: str, nome: str) -> tuple[Path, Path]:
    pasta = parcial / periodo.nome / serie
    return pasta / f"{nome}.csv", pasta / f"{nome}.feito"


def ler_parcial(
    parcial: Path, periodo: Periodo, serie: str, nome: str
) -> tuple[list[dict], set[date]]:
    dados, feito = arquivos_parcial(parcial, periodo, serie, nome)
    if not feito.exists():
        return [], set()
    origens = {date.fromisoformat(x) for x in feito.read_text().split()}
    linhas = []
    if dados.exists():
        with dados.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                o = date.fromisoformat(r["origem"])
                if o in origens:  # linhas de uma origem interrompida no meio não contam
                    linhas.append(
                        {
                            "origem": o,
                            "horizonte": int(r["horizonte"]),
                            "alvo": date.fromisoformat(r["alvo"]),
                            "previsto": float(r["previsto"]),
                            "real": float(r["real"]),
                            "segundos": float(r["segundos"]),
                        }
                    )
    return linhas, origens


def _funcao(nome: str):
    return BASES[nome].funcao


def rodar_modelo(args: tuple) -> tuple[str, int, float]:
    """Processo de um modelo: percorre as origens que faltam e grava cada uma ao terminar."""
    nome, periodo_nome, serie_nome, caminho, parcial, passo = args
    periodo = PERIODOS[periodo_nome]
    serie = ler_serie(Path(caminho))
    parcial = Path(parcial)
    dados, feito = arquivos_parcial(parcial, periodo, serie_nome, nome)
    dados.parent.mkdir(parents=True, exist_ok=True)
    _, ja = ler_parcial(parcial, periodo, serie_nome, nome)
    todas = origens_do_periodo(periodo, passo)
    faltam = [o for o in todas if o not in ja]
    funcao = _funcao(nome)
    t0 = time.time()
    novas = 0
    for k, origem in enumerate(faltam, 1):
        alvos = {p.horizonte: p.alvo for p in pares(periodo) if p.origem == origem}
        hs = [h for h, a in alvos.items() if a in serie and origem in serie]
        t = time.time()
        try:
            previsto = funcao(visao_na_origem(serie, origem), origem, hs) if hs else {}
        except ValueError:  # janela de 72 meses incompleta: sem previsão, o par fica fora
            previsto = {}
        seg = (time.time() - t) / max(len(previsto), 1)
        escrever_cabecalho = not dados.exists()
        with dados.open("a", newline="", encoding="utf-8") as f:
            w = csv.writer(f, lineterminator="\n")
            if escrever_cabecalho:
                w.writerow(CAMPOS_PARCIAL)
            for h, p in sorted(previsto.items()):
                w.writerow([origem, h, alvos[h], repr(p), repr(serie[alvos[h]]), f"{seg:.4f}"])
        with feito.open("a", encoding="utf-8") as f:
            f.write(f"{origem}\n")
        novas += 1
        if k % 10 == 0 or k == len(faltam):
            print(f"[{nome}] {k}/{len(faltam)} origens, {time.time() - t0:.0f}s", flush=True)
    return nome, novas, time.time() - t0


def estimar(periodo: Periodo, serie_nome: str, caminho: Path, passo: int, jobs: int, nomes) -> None:
    serie = ler_serie(caminho)
    n = len(origens_do_periodo(periodo, passo))
    origem = origens_do_periodo(periodo, 1)[-12]  # uma origem com os 12 horizontes
    hs = [p.horizonte for p in pares(periodo) if p.origem == origem]
    print(f"origens a rodar: {n} (passo {passo}); origem de teste: {origem}")
    total = 0.0
    for nome in nomes:
        if nome not in BASES:
            continue
        t = time.time()
        _funcao(nome)(visao_na_origem(serie, origem), origem, hs)
        seg = time.time() - t
        total += seg * n
        print(f"  {nome:10s} {seg:5.2f} s/origem -> {seg * n / 60:5.1f} min sozinho")
    print(
        f"soma sequencial {total / 60:.1f} min; com {jobs} processos, ~{total / jobs / 60:.1f} min "
        f"(limitado pelo modelo mais lento)"
    )


# ---------------------------------------------------------------- métricas


def registros_do_periodo(
    parcial: Path, periodo: Periodo, serie_nome: str, serie: Serie, nomes, passo: int
):
    """Registros por candidato; as combinações saem da média das previsões já gravadas."""
    base: dict[str, dict[tuple, dict]] = {}
    tempos: dict[str, float] = {}
    for nome in BASES:
        if nome not in nomes and not any(
            nome in COMBINACOES[c].componentes for c in nomes if c in COMBINACOES
        ):
            continue
        linhas, _ = ler_parcial(parcial, periodo, serie_nome, nome)
        base[nome] = {(r["origem"], r["horizonte"]): r for r in linhas}
        tempos[nome] = sum(r["segundos"] for r in linhas)
    saida: dict[str, list[Registro]] = {}
    origens = set(origens_do_periodo(periodo, passo))
    for p in pares(periodo):
        if p.origem not in origens or p.alvo not in serie or p.origem not in serie:
            continue
        real = serie[p.alvo]
        ing = INGENUO.funcao(visao_na_origem(serie, p.origem), p.origem, p.horizonte)
        if ing is not None:
            saida.setdefault(INGENUO.nome, []).append(
                Registro(serie_nome, INGENUO.nome, p.origem, p.horizonte, p.alvo, ing, real)
            )
        for nome, tabela in base.items():
            r = tabela.get((p.origem, p.horizonte))
            if r is not None and nome in nomes:
                saida.setdefault(nome, []).append(
                    Registro(serie_nome, nome, p.origem, p.horizonte, p.alvo, r["previsto"], real)
                )
        for c in nomes:
            if c in COMBINACOES:
                partes = [base[x].get((p.origem, p.horizonte)) for x in COMBINACOES[c].componentes]
                if all(partes):
                    prev = sum(x["previsto"] for x in partes) / len(partes)
                    saida.setdefault(c, []).append(
                        Registro(serie_nome, c, p.origem, p.horizonte, p.alvo, prev, real)
                    )
    return saida, tempos


def _pct_abs(rs: list[Registro]) -> dict[tuple, float]:
    return {(r.origem, r.horizonte): 100 * abs(r.erro) / r.real for r in rs}


def diferenca_contra_ingenuo(cand: list[Registro], ing: list[Registro]) -> dict:
    """MAPE(ingênuo) - MAPE(candidato) nos MESMOS pares (positivo = candidato melhor), EP por
    bootstrap em blocos de ano-alvo (semente fixa) e em quantos anos o candidato tem MAPE menor."""
    a, b = _pct_abs(ing), _pct_abs(cand)
    comuns = sorted(set(a) & set(b))
    if not comuns:
        return {
            "diferenca_mape_vs_ingenuo_pp": float("nan"),
            "ep_diferenca_pp": float("nan"),
            "anos_melhores_que_ingenuo": 0,
            "anos": 0,
        }
    alvo_ano = {(r.origem, r.horizonte): r.alvo.year for r in cand}
    por_ano: dict[int, list[float]] = {}
    for k in comuns:
        por_ano.setdefault(alvo_ano[k], []).append(a[k] - b[k])
    medias = np.array([np.mean(v) for _, v in sorted(por_ano.items())])
    rng = np.random.default_rng(SEMENTE_BOOTSTRAP)
    boot = rng.choice(medias, size=(REPLICAS, len(medias)), replace=True).mean(axis=1)
    return {
        "diferenca_mape_vs_ingenuo_pp": float(np.mean([a[k] - b[k] for k in comuns])),
        "ep_diferenca_pp": float(boot.std(ddof=1)),
        "anos_melhores_que_ingenuo": int((medias > 0).sum()),
        "anos": len(medias),
    }


def mape_por_ano(rs: list[Registro]) -> dict[int, float]:
    anos: dict[int, list[Registro]] = {}
    for r in rs:
        anos.setdefault(r.alvo.year, []).append(r)
    return {a: metricas(v)["mape_pct"] for a, v in sorted(anos.items())}


def resumo(registros: dict[str, list[Registro]], tempos: dict[str, float]) -> list[dict]:
    ing = registros[INGENUO.nome]
    linhas = []
    for nome, rs in registros.items():
        m = metricas(rs)
        dez = [r for r in rs if r.origem.month == 12]
        anual = erro_anual(dez)
        anos = mape_por_ano(rs)
        comp = (
            sum(tempos.get(x, 0.0) for x in CANDIDATOS[nome].componentes)
            if nome in COMBINACOES
            else tempos.get(nome, 0.0)
        )
        linhas.append(
            {
                "candidato": nome,
                "n": m["n"],
                "mape_pct": m["mape_pct"],
                "mae_mwmed": m["mae_mwmed"],
                "vies_mwmed": m["vies_mwmed"],
                "vies_pct": m["vies_pct"],
                "mape_h1_pct": metricas([r for r in rs if r.horizonte == 1])["mape_pct"],
                "mape_h12_pct": metricas([r for r in rs if r.horizonte == 12])["mape_pct"],
                "erro_anual_dez_abs_pct": (
                    sum(abs(a["erro_pct"]) for a in anual) / len(anual) if anual else float("nan")
                ),
                "mape_pior_ano_pct": max(anos.values()),
                "complexidade": CANDIDATOS[nome].complexidade if nome in CANDIDATOS else 0,
                **(
                    diferenca_contra_ingenuo(rs, ing)
                    if nome != INGENUO.nome
                    else {
                        "diferenca_mape_vs_ingenuo_pp": 0.0,
                        "ep_diferenca_pp": 0.0,
                        "anos_melhores_que_ingenuo": 0,
                        "anos": len(anos),
                    }
                ),
                "segundos_de_modelo": comp,
            }
        )
    return sorted(linhas, key=lambda r: r["mape_pct"])


def tabela_por_horizonte(registros: dict[str, list[Registro]]) -> list[dict]:
    saida = []
    for nome, rs in registros.items():
        for recorte in ("todas_as_origens", "origem_dezembro"):
            sub = rs if recorte == "todas_as_origens" else [r for r in rs if r.origem.month == 12]
            saida += [
                {"candidato": nome, "recorte": recorte, **x} for x in por_horizonte(sub) if x["n"]
            ]
    return saida


def tabela_erro_anual(registros: dict[str, list[Registro]]) -> list[dict]:
    return [
        {"candidato": nome, **a}
        for nome, rs in registros.items()
        for a in erro_anual([r for r in rs if r.origem.month == 12])
    ]


def tabela_previsoes(registros: dict[str, list[Registro]]) -> list[dict]:
    """Insumo da Parte B: o erro de cada previsão, por origem e horizonte."""
    return [
        {
            "candidato": nome,
            "origem": r.origem.isoformat(),
            "horizonte": r.horizonte,
            "alvo": r.alvo.isoformat(),
            "previsto_mwmed": r.previsto,
            "real_mwmed": r.real,
            "erro_mwmed": r.erro,
            "erro_pct": 100 * r.erro / r.real,
        }
        for nome, rs in registros.items()
        for r in sorted(rs, key=lambda x: (x.origem, x.horizonte))
    ]


def hashes_do_codigo() -> dict[str, str]:
    """`git hash-object` dos arquivos que definem o resultado (confere o código com a árvore
    suja)."""
    arquivos = [
        *(
            f"ml/{n}.py"
            for n in (
                "validacao",
                "metricas",
                "baselines",
                "features",
                "preparo",
                "modelos",
                "registro",
                "escolha",
                "avaliar_candidatos",
            )
        ),
        "dbt/models/marts/fct_carga_mensal.sql",
        "dbt/seeds/carga_mensal_ons.csv",
        "dbt/seeds/ajuste_definicao_carga.csv",
    ]
    saida = {}
    for a in arquivos:
        r = subprocess.run(
            ["git", "hash-object", a], cwd=RAIZ, capture_output=True, text=True, check=False
        )
        saida[a] = r.stdout.strip()[:12]
    return saida


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--periodo", required=True, choices=list(PERIODOS))
    ap.add_argument(
        "--serie", choices=list(COLUNA), help="padrão: original (desenvolvimento) / reconstruida"
    )
    ap.add_argument("--candidatos", nargs="+", default=list(CANDIDATOS), choices=list(CANDIDATOS))
    ap.add_argument("--passo", type=int, default=1, choices=(1, 3))
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--estimar", action="store_true", help="mede o tempo e sai, sem rodar")
    ap.add_argument("--recarregar", action="store_true", help="relê a série da nuvem")
    ap.add_argument("--parcial", type=Path, default=DADOS / "parcial")
    ap.add_argument("--liberar-teste-final", action="store_true")
    args = ap.parse_args(argv)
    periodo = PERIODOS[args.periodo]
    if periodo.final and not args.liberar_teste_final:
        print(
            "RECUSADO: o teste final só roda uma vez, depois do Checkpoint B aprovado. "
            "Passe --liberar-teste-final.",
            file=sys.stderr,
        )
        return 2
    if periodo.final and list(dict.fromkeys(args.candidatos)) != [CANDIDATO_DO_TESTE_FINAL]:
        print(
            "RECUSADO: o teste final roda só o vencedor pré-registrado "
            f"({CANDIDATO_DO_TESTE_FINAL}) e o ingênuo; use --candidatos com esse nome.",
            file=sys.stderr,
        )
        return 2
    serie_nome = args.serie or ("reconstruida" if periodo.final else "original")
    caminho = carregar_serie(periodo, serie_nome, args.recarregar)
    serie = ler_serie(caminho)
    nomes = list(dict.fromkeys(args.candidatos))
    bases = list(
        dict.fromkeys(b for n in nomes for b in ([n] if n in BASES else COMBINACOES[n].componentes))
    )
    if args.estimar:
        estimar(periodo, serie_nome, caminho, args.passo, args.jobs, bases)
        return 0
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=args.jobs) as ex:
        tarefas = [
            (b, periodo.nome, serie_nome, str(caminho), str(args.parcial), args.passo)
            for b in bases
        ]
        for nome, novas, seg in ex.map(rodar_modelo, tarefas):
            print(f"[{nome}] pronto: {novas} origens novas em {seg:.0f}s", flush=True)
    registros, tempos = registros_do_periodo(
        args.parcial, periodo, serie_nome, serie, nomes, args.passo
    )
    # Se o candidato tem menos pares que o ingênuo (janela de 72 meses incompleta nas primeiras
    # origens do teste final), o ingênuo também é reportado nos MESMOS pares (comparação justa).
    for nome in nomes:
        if nome in registros:
            chaves = {(r.origem, r.horizonte) for r in registros[nome]}
            ing = registros[INGENUO.nome]
            if chaves != {(r.origem, r.horizonte) for r in ing}:
                registros[f"{INGENUO.nome}_mesmos_pares"] = [
                    replace(r, baseline=f"{INGENUO.nome}_mesmos_pares")
                    for r in ing
                    if (r.origem, r.horizonte) in chaves
                ]
            break
    tabela = resumo(registros, tempos)
    escolha = None if periodo.final else escolher(tabela)  # o teste final não escolhe nada
    completo = args.passo == 1 and (periodo.final or set(nomes) == set(CANDIDATOS))
    saida = SAIDA_FINAL if completo else DADOS / "exploracao"
    prefixo = saida / f"candidatos_{periodo.nome}_{serie_nome}"
    gravar_csv(Path(f"{prefixo}_resumo.csv"), tabela)
    gravar_csv(Path(f"{prefixo}_por_horizonte.csv"), tabela_por_horizonte(registros))
    gravar_csv(Path(f"{prefixo}_erro_anual.csv"), tabela_erro_anual(registros))
    gravar_csv(Path(f"{prefixo}_previsoes.csv"), tabela_previsoes(registros))
    meta = {
        "gerado_em_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        **referencia_git(),
        "periodo": periodo.nome,
        "serie": serie_nome,
        "passo_das_origens": args.passo,
        "candidatos": nomes,
        "escolha": escolha,
        **(
            {"regra_pre_registrada": REGRA_SPRINT_6, "ressalva_da_vitoria": RESSALVA_VITORIA}
            if periodo.final
            else {}
        ),
        "criterio": {"limiar_pp": LIMIAR_PP, "min_anos_melhores": 5},
        "pares": {n: len(rs) for n, rs in registros.items()},
        "hashes_de_conteudo": hashes_do_codigo(),
        "semente_bootstrap": SEMENTE_BOOTSTRAP,
        "replicas_bootstrap": REPLICAS,
        "horizontes": [HORIZONTES[0], HORIZONTES[-1]],
        "tempo_total_s": round(time.time() - t0, 1),
    }
    Path(f"{prefixo}.meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8"
    )
    print(
        f"\n{'candidato':28s} {'MAPE%':>6s} {'viés%':>6s} {'dif.pp':>7s} {'EP':>5s} {'anos+':>5s}"
        f" {'dez%':>5s} {'pior%':>6s}"
    )
    for r in tabela:
        print(
            f"{r['candidato']:28s} {r['mape_pct']:6.2f} {r['vies_pct']:6.2f} "
            f"{r['diferenca_mape_vs_ingenuo_pp']:7.2f} {r['ep_diferenca_pp']:5.2f} "
            f"{r['anos_melhores_que_ingenuo']:3d}/{r['anos']} "
            f"{r['erro_anual_dez_abs_pct']:5.2f} {r['mape_pior_ano_pct']:6.2f}"
        )
    if escolha:
        print(f"\nescolha: {escolha['vencedor']} ({escolha['motivo']}); resultados em {saida}")
    else:
        print(f"\nteste final (sem escolha): resultados em {saida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
