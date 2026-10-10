"""Cenários de consumo e de PLD da otimização (5.6 e 5.7): geração e gravação em uma execução só.

    uv run --env-file .env python -m ml.cenarios gerar --n 2000 --dry-run   # só lê e conta
    uv run --env-file .env python -m ml.cenarios gerar --n 2000             # grava (idempotente)
    uv run --env-file .env python -m ml.cenarios gerar-producao --dry-run   # só a origem nova
    uv run --env-file .env python -m ml.cenarios gerar-producao             # grava só ela

Grava três tabelas em `marts`, por `MERGE` numa chave natural (reexecutar dá o mesmo resultado):
- `fct_cenario_consumo`: carga do SE/CO e consumo do supermercado por (execução, origem, cenário,
  horizonte);
- `fct_cenario_pld`: PLD mensal (R$/MWh) por (execução, origem, método, cenário, horizonte), com o
  mês histórico sorteado (auditoria); métodos `simples` e `blocos`;
- `fct_cenario_execucao`: uma linha por (execução, origem) com N, semente, `k`, impressões digitais
  dos insumos (erros, PLD, pisos), proveniência (hash do código, commit) e data.
O `execucao_id` é um hash dos insumos: mesmo N, semente, `k`, erros, PLD e pisos dão o mesmo id.

Origens: dezembro de 2020 a 2024 (decisão de 2021 a 2025) e a última origem de produção. Na
produção, os meses de 2027 repetem os limites de 2026 (o ANEEL publica os de `y` em dezembro de
`y − 1`; coluna `limites_assumidos` da tabela de execução).

`gerar-producao` (Sprint 6, Parte C1): a cadeia mensal. Gera os cenários **só da origem de produção
mais recente**, com um `execucao_id` próprio derivado dos insumos DELA, sem tocar nas origens de
backtest nem na execução congelada `51cf99b073fe` (recusa qualquer origem `<= 2024-12`). Mesmo N e
mesma semente do caso base; o MERGE é idempotente (mesmos insumos, mesmo id, mesmas linhas).

Funções de leitura e de linhas primeiro; a nuvem no fim.
"""

import argparse
import csv
import sys
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from ml.cenarios_consumo import CHAVE_CENARIOS as CHAVE_CONSUMO
from ml.cenarios_consumo import (
    ESQUEMA_CENARIOS,
    N_PADRAO,
    SEMENTE_BASE,
    execucao_id,
    hash_curto,
    hash_dos_erros,
    k_do_dbt,
    ler_erros_e_previstos,
    linhas_de_cenarios,
    origens_de_decisao,
    previstos_de_producao,
    sortear,
)
from ml.cenarios_pld import (
    INICIO_HISTORICO,
    METODOS,
    blocos_de_12,
    bootstrap,
    historico_ate,
    limites_do_ano,
    mensal_do_semanal,
    meses_alvo,
)
from ml.intervalos import vetores_completos_ate
from ml.medida_bytes import ContaBytes
from ml.piso_pld import completar_pisos, detectar_por_ano
from ml.registro import MODELO_VERSAO
from ml.validacao import HORIZONTES

RAIZ = Path(__file__).resolve().parents[1]
CONSUMO = "marts.fct_cenario_consumo"
PLD = "marts.fct_cenario_pld"
EXECUCAO = "marts.fct_cenario_execucao"
TEMP = {
    CONSUMO: "staging.tmp_fct_cenario_consumo",
    PLD: "staging.tmp_fct_cenario_pld",
    EXECUCAO: "staging.tmp_fct_cenario_execucao",
}
TETO_BYTES = 200 * 1024 * 1024
CODIGO = (
    "ml/cenarios.py",
    "ml/cenarios_consumo.py",
    "ml/cenarios_pld.py",
    "ml/piso_pld.py",
    "ml/intervalos.py",
)
ESQUEMA_PLD = [
    ("execucao_id", "STRING"),
    ("origem", "DATE"),
    ("metodo", "STRING"),
    ("cenario", "INT64"),
    ("horizonte", "INT64"),
    ("mes_alvo", "DATE"),
    ("mes_historico", "DATE"),
    ("pld_rs_mwh", "FLOAT64"),
]
CHAVE_PLD = ("execucao_id", "origem", "metodo", "cenario", "horizonte")
ESQUEMA_EXECUCAO = [
    ("execucao_id", "STRING"),
    ("origem", "DATE"),
    ("modelo_versao", "STRING"),
    ("n_cenarios", "INT64"),
    ("semente_base", "INT64"),
    ("calibracao", "STRING"),
    ("n_vetores_consumo", "INT64"),
    ("erros_hash", "STRING"),
    ("k_consumo", "FLOAT64"),
    ("n_meses_pld", "INT64"),
    ("n_blocos_pld", "INT64"),
    ("pld_hash", "STRING"),
    ("pisos_hash", "STRING"),
    ("limites_assumidos", "BOOL"),
    ("codigo_hash", "STRING"),
    ("commit", "STRING"),
    ("gerado_em", "TIMESTAMP"),
]
CHAVE_EXECUCAO = ("execucao_id", "origem")
# As origens do backtest 2021-2025 (decidem 2021 a 2025) pertencem à execução congelada: a cadeia
# mensal de produção nunca as escreve.
ORIGENS_DE_BACKTEST = tuple(date(a, 12, 1) for a in range(2020, 2025))
EXECUCAO_CONGELADA = "51cf99b073fe"
SQL_SEMANAL = """SELECT data_inicio_semana, inicio_semana_utc, fim_semana_utc,
    CAST(pld_rs_mwh AS FLOAT64) AS pld
    FROM `marts.fct_pld_semanal` WHERE codigo_submercado = 'SE'"""
SQL_PONDERADO = """SELECT mes, CAST(pld_ponderado_rs_mwh AS FLOAT64) AS pld
    FROM `marts.fct_pld_ponderado_mensal` WHERE mes_completo ORDER BY mes"""


# ---------------------------------------------------------------- dados do PLD


@dataclass(frozen=True)
class DadosPld:
    serie: dict[date, float]  # PLD mensal nominal, 2002-01 em diante
    detectados: dict[int, float]  # pisos detectados 2002-2020 (mínimo de 3 blocos)
    excecoes: dict[int, float]  # seed pld_piso_excecoes
    limites: dict[int, tuple[float, float]]  # ano -> (piso, teto estrutural), seed pld_limites

    def pisos(self, variante: str = "interpolado") -> dict[int, float]:
        """Piso de cada ano: 2002-2020 detectado, exceção ou lacuna; 2021 em diante, a seed."""
        anos = range(INICIO_HISTORICO.year, 2021)
        antigos = completar_pisos(self.detectados, self.excecoes, anos, variante)
        pisos = {a: v for a, (v, _) in antigos.items()}
        pisos.update({a: piso for a, (piso, _) in self.limites.items() if a >= 2021})
        return pisos

    def origem_dos_pisos(self, variante: str = "interpolado") -> dict[int, str]:
        anos = range(INICIO_HISTORICO.year, 2021)
        return {
            a: o
            for a, (_, o) in completar_pisos(self.detectados, self.excecoes, anos, variante).items()
        }


def ler_csv(caminho: Path) -> list[dict]:
    with caminho.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def limites_da_seed() -> dict[int, tuple[float, float]]:
    """ano -> (piso, teto ESTRUTURAL). O teto horário não entra no modelo mensal."""
    return {
        int(r["ano"]): (float(r["pld_min"]), float(r["pld_max_estrutural"]))
        for r in ler_csv(RAIZ / "dbt" / "seeds" / "pld_limites.csv")
    }


def excecoes_da_seed() -> dict[int, float]:
    return {
        int(r["ano"]): float(r["piso"])
        for r in ler_csv(RAIZ / "dbt" / "seeds" / "pld_piso_excecoes.csv")
    }


def montar_dados_pld(semanal: list[dict], ponderado: list[dict]) -> DadosPld:
    """`semanal`: linhas (patamar a patamar) do PLD semanal; `ponderado`: PLDp mensal de 2021+."""
    from datetime import timedelta

    semanas: dict[tuple, list[float]] = {}
    obs_por_ano: dict[int, list[tuple[object, float]]] = {}
    for r in semanal:
        semanas.setdefault((r["inicio_semana_utc"], r["fim_semana_utc"]), []).append(
            float(r["pld"])
        )
        ano = (r["data_inicio_semana"] + timedelta(days=3)).year  # ano do dia do meio da semana
        obs_por_ano.setdefault(ano, []).append((r["data_inicio_semana"], float(r["pld"])))
    medias = [(i, f, sum(v) / len(v)) for (i, f), v in sorted(semanas.items())]
    serie = {
        m: v
        for m, v in mensal_do_semanal(medias).items()
        if INICIO_HISTORICO <= m < date(2021, 1, 1)
    }
    serie.update({r["mes"]: float(r["pld"]) for r in ponderado if r["mes"] >= date(2021, 1, 1)})
    detectados = {
        r.ano: r.piso
        for r in detectar_por_ano({a: o for a, o in obs_por_ano.items() if 2002 <= a <= 2020})
        if r.piso is not None
    }
    return DadosPld(serie, detectados, excecoes_da_seed(), limites_da_seed())


def carregar_dados_pld(gcp, cliente) -> DadosPld:
    from ml.previsao import _consulta

    r1 = _consulta(gcp, cliente, SQL_SEMANAL)
    r2 = _consulta(gcp, cliente, SQL_PONDERADO)
    return montar_dados_pld(
        [dict(x.items()) for x in r1.linhas], [dict(x.items()) for x in r2.linhas]
    )


def impressao_do_pld(historico: dict[date, float]) -> str:
    return hash_curto([(m.isoformat(), round(v, 6)) for m, v in sorted(historico.items())])


def impressao_dos_pisos(pisos: dict[int, float], limites: dict[int, tuple[float, float]]) -> str:
    return hash_curto({"pisos": pisos, "limites": {a: list(v) for a, v in limites.items()}})


# ---------------------------------------------------------------- linhas


def linhas_de_pld(id_: str, origem: date, metodo: str, cenarios: list[list[tuple[date, float]]]):
    alvos = meses_alvo(origem)
    return [
        {
            "execucao_id": id_,
            "origem": origem.isoformat(),
            "metodo": metodo,
            "cenario": s,
            "horizonte": h,
            "mes_alvo": alvo.isoformat(),
            "mes_historico": mes.isoformat(),
            "pld_rs_mwh": valor,
        }
        for s, cenario in enumerate(cenarios)
        for h, alvo, (mes, valor) in zip(HORIZONTES, alvos, cenario, strict=True)
    ]


def proveniencia() -> dict:
    from ml.previsao import hash_blob_git, ler_commit

    return {
        "codigo_hash": hash_curto({c: hash_blob_git(RAIZ / c) for c in CODIGO}),
        "commit": ler_commit(RAIZ),
        "gerado_em": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# ---------------------------------------------------------------- nuvem


def ddl(tabela: str, esquema: list[tuple[str, str]], chave: tuple[str, ...]) -> str:
    colunas = ", ".join(f"`{n}` {t}" for n, t in esquema)
    return (
        f"CREATE TABLE IF NOT EXISTS `{tabela}` ({colunas}) "
        f"OPTIONS (description='Chave natural: {', '.join(chave)}. Gerada por ml.cenarios.')"
    )


def gravar_medido(gcp, cliente, linhas, tabela, esquema, chave) -> dict:
    """Cria a tabela se preciso, carrega numa temporária e faz o MERGE. Devolve as medidas."""
    from google.cloud import bigquery

    from ml.previsao import colunas_novas, merge

    t0 = time.perf_counter()
    faturados = 0
    for sql in (ddl(tabela, esquema, chave), colunas_novas(tabela, esquema)):
        faturados += (
            gcp.executar_consulta(cliente, sql, max_bytes_faturados=TETO_BYTES).bytes_faturados or 0
        )
    temp = TEMP.get(tabela) or f"staging.tmp_{tabela.split('.')[-1]}"
    campos = [bigquery.SchemaField(n, t) for n, t in esquema]
    t1 = time.perf_counter()
    cliente.load_table_from_json(
        linhas,
        temp,
        job_config=bigquery.LoadJobConfig(
            schema=campos, write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE
        ),
    ).result()
    t2 = time.perf_counter()
    try:
        res = gcp.executar_consulta(
            cliente, merge(tabela, temp, esquema, chave), max_bytes_faturados=TETO_BYTES
        )
        faturados += res.bytes_faturados or 0
    finally:
        cliente.delete_table(temp, not_found_ok=True)
    t3 = time.perf_counter()
    return {
        "tabela": tabela,
        "linhas": len(linhas),
        "s_ddl": t1 - t0,
        "s_carga": t2 - t1,
        "s_merge": t3 - t2,
        "bytes_faturados": faturados,
    }


def gerar(n: int, dry_run: bool, semente: int = SEMENTE_BASE) -> int:
    from ml.previsao import _cliente

    inicio = time.perf_counter()
    gcp, cliente = _cliente()
    k = k_do_dbt()
    erros, previstos = ler_erros_e_previstos(gcp, cliente)
    plano = [(o, [previstos[o][h] for h in HORIZONTES]) for o in origens_de_decisao(previstos)]
    o_prod, p_prod = previstos_de_producao(gcp, cliente)
    plano.append((o_prod, p_prod))
    dados = carregar_dados_pld(gcp, cliente)
    pisos = dados.pisos()
    erros_hash = {o: hash_dos_erros(erros, o) for o, _ in plano}
    pld_hash = {o: impressao_do_pld(historico_ate(dados.serie, o)) for o, _ in plano}
    pisos_hash = impressao_dos_pisos(pisos, dados.limites)
    id_ = execucao_id(
        n,
        semente,
        k,
        erros_hash,
        {"pld": {o.isoformat(): h for o, h in pld_hash.items()}, "pisos": pisos_hash},
    )
    prov = proveniencia()
    consumo, pld, execucoes = [], [], []
    for origem, prev in plano:
        consumo += linhas_de_cenarios(id_, origem, prev, sortear(erros, origem, n, semente), k)
        hist = historico_ate(dados.serie, origem)
        for metodo in METODOS:
            pld += linhas_de_pld(
                id_,
                origem,
                metodo,
                bootstrap(metodo, hist, origem, n, semente, pisos, dados.limites),
            )
        assumidos = any(limites_do_ano(dados.limites, m.year)[2] for m in meses_alvo(origem))
        execucoes.append(
            {
                "execucao_id": id_,
                "origem": origem.isoformat(),
                "modelo_versao": MODELO_VERSAO,
                "n_cenarios": n,
                "semente_base": semente,
                "calibracao": "crescente",
                "n_vetores_consumo": len(vetores_completos_ate(erros, origem)),
                "erros_hash": erros_hash[origem],
                "k_consumo": k,
                "n_meses_pld": len(hist),
                "n_blocos_pld": len(blocos_de_12(hist, meses_alvo(origem)[0])),
                "pld_hash": pld_hash[origem],
                "pisos_hash": pisos_hash,
                "limites_assumidos": assumidos,
                **prov,
            }
        )
        print(
            f"origem {origem:%Y-%m}: {execucoes[-1]['n_vetores_consumo']} vetores de consumo, "
            f"{len(hist)} meses de PLD, {execucoes[-1]['n_blocos_pld']} blocos de 12, "
            f"limites assumidos: {assumidos}"
        )
    print(
        f"execucao_id {id_}: {len(consumo)} linhas de consumo, {len(pld)} de PLD, "
        f"{len(execucoes)} de execução; leitura {time.perf_counter() - inicio:.1f}s"
    )
    if dry_run:
        print("dry-run: nada gravado")
        return 0
    medidas = [
        gravar_medido(gcp, cliente, consumo, CONSUMO, ESQUEMA_CENARIOS, CHAVE_CONSUMO),
        gravar_medido(gcp, cliente, pld, PLD, ESQUEMA_PLD, CHAVE_PLD),
        gravar_medido(gcp, cliente, execucoes, EXECUCAO, ESQUEMA_EXECUCAO, CHAVE_EXECUCAO),
    ]
    print("\ntabela | linhas | s DDL | s carga | s MERGE | bytes faturados")
    for m in medidas:
        print(
            f"{m['tabela']} | {m['linhas']} | {m['s_ddl']:.1f} | {m['s_carga']:.1f} | "
            f"{m['s_merge']:.1f} | {m['bytes_faturados']:,}".replace(",", ".")
        )
    total = sum(m["bytes_faturados"] for m in medidas)
    print(
        f"total: {total:,} bytes faturados ({total / 1024 / 1024:.1f} MiB); "
        f"tempo total {time.perf_counter() - inicio:.1f}s".replace(",", ".")
    )
    return 0


# ---------------------------------------------------------------- cadeia mensal: só a origem nova


class ErroDeOrigem(RuntimeError):
    """A origem pedida não pode ser gerada pela cadeia mensal de produção."""


def conferir_origem_de_producao(origem: date) -> None:
    """Recusa as origens do backtest e qualquer origem que não seja posterior a elas."""
    if origem in ORIGENS_DE_BACKTEST or origem <= max(ORIGENS_DE_BACKTEST):
        raise ErroDeOrigem(
            f"a origem {origem:%Y-%m} é do backtest (a execução congelada {EXECUCAO_CONGELADA}); "
            "a cadeia de produção só gera origens posteriores a 2024-12"
        )


def id_da_origem(
    origem: date, n: int, semente: int, k: float, erros_hash: str, pld_hash: str, pisos_hash: str
) -> str:
    """`execucao_id` da origem de produção: só dos insumos dela (e do N, da semente e do `k`).

    Não passa pela mesma conta de `gerar` (que mistura todas as origens): tem o marcador `producao`
    e uma única origem, então nunca coincide com o id do caso base."""
    return execucao_id(
        n,
        semente,
        k,
        {origem: erros_hash},
        {"pld": {origem.isoformat(): pld_hash}, "pisos": pisos_hash, "producao": True},
    )


@dataclass(frozen=True)
class CenariosDaOrigem:
    execucao_id: str
    origem: date
    consumo: list[dict]
    pld: list[dict]
    execucao: dict


def gerar_cenarios_da_origem(
    origem: date,
    previsto_mwmed: list[float],
    erros,
    dados_pld: DadosPld,
    k: float,
    n: int = N_PADRAO,
    semente: int = SEMENTE_BASE,
    prov: dict | None = None,
) -> CenariosDaOrigem:
    """Cenários de consumo e de PLD (simples e blocos) de UMA origem de produção. Função pura."""
    conferir_origem_de_producao(origem)
    if len(previsto_mwmed) != len(HORIZONTES):
        raise ValueError("são necessários os 12 previstos da origem")
    erros = list(erros)
    pisos = dados_pld.pisos()
    historico = historico_ate(dados_pld.serie, origem)
    erros_h = hash_dos_erros(erros, origem)
    pld_h = impressao_do_pld(historico)
    pisos_h = impressao_dos_pisos(pisos, dados_pld.limites)
    id_ = id_da_origem(origem, n, semente, k, erros_h, pld_h, pisos_h)
    consumo = linhas_de_cenarios(id_, origem, previsto_mwmed, sortear(erros, origem, n, semente), k)
    pld = []
    for metodo in METODOS:
        pld += linhas_de_pld(
            id_,
            origem,
            metodo,
            bootstrap(metodo, historico, origem, n, semente, pisos, dados_pld.limites),
        )
    assumidos = any(limites_do_ano(dados_pld.limites, m.year)[2] for m in meses_alvo(origem))
    execucao = {
        "execucao_id": id_,
        "origem": origem.isoformat(),
        "modelo_versao": MODELO_VERSAO,
        "n_cenarios": n,
        "semente_base": semente,
        "calibracao": "crescente",
        "n_vetores_consumo": len(vetores_completos_ate(erros, origem)),
        "erros_hash": erros_h,
        "k_consumo": k,
        "n_meses_pld": len(historico),
        "n_blocos_pld": len(blocos_de_12(historico, meses_alvo(origem)[0])),
        "pld_hash": pld_h,
        "pisos_hash": pisos_h,
        "limites_assumidos": assumidos,
        **(prov or {"codigo_hash": "", "commit": "", "gerado_em": "1970-01-01T00:00:00Z"}),
    }
    return CenariosDaOrigem(id_, origem, consumo, pld, execucao)


def ler_insumos_de_producao(gcp, cliente):
    """(k, erros, origem, previsto, dados_pld): o BigQuery, da origem de produção mais recente."""
    k = k_do_dbt()
    erros, _ = ler_erros_e_previstos(gcp, cliente)
    origem, previsto = previstos_de_producao(gcp, cliente)
    return k, erros, origem, previsto, carregar_dados_pld(gcp, cliente)


CAMPOS_DOS_INSUMOS = ("erros_hash", "pld_hash", "pisos_hash")


def execucoes_da_origem(gcp, cliente, origem: date) -> list[dict]:
    """As execuções já gravadas para a origem, com a impressão dos insumos de cada uma (vazio se a
    tabela ainda não existe)."""
    from ml.previsao import _consulta, _tabela_existe

    if not _tabela_existe(cliente, EXECUCAO):
        return []
    sql = (
        "SELECT execucao_id, erros_hash, pld_hash, pisos_hash, k_consumo "
        f"FROM `{EXECUCAO}` WHERE origem = DATE '{origem.isoformat()}'"
    )
    return [dict(r.items()) for r in _consulta(gcp, cliente, sql).linhas]


def descrever_estado(execucao: dict, ja: list[dict]) -> str:
    """Como a origem está gravada. O id muda por DOIS motivos que não se confundem: (1) o escopo da
    derivação (a execução congelada mistura 6 origens; aqui há 1) e (2) mudança de insumo. Só o
    segundo é "os insumos mudaram": compara-se o que realmente entra no id, campo a campo."""
    if not ja:
        return "ainda não gravada"
    if any(e["execucao_id"] == execucao["execucao_id"] for e in ja):
        return "já gravada com este id (idempotente: o MERGE só atualiza)"
    partes = []
    for e in ja:
        diferentes = [c for c in CAMPOS_DOS_INSUMOS if e.get(c) != execucao[c]]
        if abs(float(e["k_consumo"]) - float(execucao["k_consumo"])) > 1e-18:
            diferentes.append("k_consumo")
        if diferentes:
            partes.append(
                f"insumos DIFERENTES dos do id {e['execucao_id']} ({', '.join(diferentes)}): "
                "este é um conjunto novo"
            )
        else:
            origem_do_id = (
                "a execução congelada do backtest, que deriva o id de 6 origens"
                if e["execucao_id"] == EXECUCAO_CONGELADA
                else "outra execução"
            )
            partes.append(
                f"mesmos insumos (erros, PLD, pisos e k) do id {e['execucao_id']}; o id difere só "
                f"pelo escopo da derivação ({origem_do_id}; aqui, 1 origem): nenhum insumo mudou"
            )
    return "; ".join(partes)


def gerar_producao(
    dry_run: bool,
    n: int = N_PADRAO,
    semente: int = SEMENTE_BASE,
    gcp=None,
    cliente=None,
    ler=ler_insumos_de_producao,
    existentes=execucoes_da_origem,
    gravar=None,
    prov: dict | None = None,
    forcar: bool = False,
) -> int:
    """Gera e grava os cenários da origem de produção mais recente (só ela).

    Se a origem já está na execução congelada (hoje, 2026-09), nada é gravado: a cadeia usa o id
    que já existe. `forcar` gera um id próprio mesmo assim."""
    inicio = time.perf_counter()
    if gcp is None:
        from ml.previsao import _cliente

        gcp, cliente = _cliente()
    gcp = ContaBytes(gcp)
    if prov is None:
        prov = proveniencia()
    k, erros, origem, previsto, dados_pld = ler(gcp, cliente)
    conferir_origem_de_producao(origem)  # antes de gastar qualquer cálculo
    cen = gerar_cenarios_da_origem(origem, previsto, erros, dados_pld, k, n, semente, prov)
    ja = existentes(gcp, cliente, origem)
    estado = descrever_estado(cen.execucao, ja)
    print(
        f"origem de produção {origem:%Y-%m}: execucao_id {cen.execucao_id}; "
        f"{len(cen.consumo)} linhas de consumo, {len(cen.pld)} de PLD, 1 de execução; "
        f"limites assumidos: {cen.execucao['limites_assumidos']}; {estado}"
    )
    print(f"leitura do BigQuery: {gcp.linha(com_estimativa=dry_run)}")
    if any(e["execucao_id"] == EXECUCAO_CONGELADA for e in ja) and not forcar:
        print(
            f"nada a gravar: a origem {origem:%Y-%m} já está na execução congelada "
            f"{EXECUCAO_CONGELADA}, que a cadeia usa. (--forcar gera um id próprio.)"
        )
        return 0
    if dry_run:
        print(
            "dry-run: nada gravado. A gravação seria 3 MERGE (consumo, PLD, execução); o MERGE "
            "lê o destino inteiro (ESTIMATIVA pelo piso de 10 MiB por tabela: ~63 MiB, não medida)"
        )
        return 0
    if gravar is None:
        gravar = gravar_medido
    medidas = [
        gravar(gcp, cliente, cen.consumo, CONSUMO, ESQUEMA_CENARIOS, CHAVE_CONSUMO),
        gravar(gcp, cliente, cen.pld, PLD, ESQUEMA_PLD, CHAVE_PLD),
        gravar(gcp, cliente, [cen.execucao], EXECUCAO, ESQUEMA_EXECUCAO, CHAVE_EXECUCAO),
    ]
    print("\ntabela | linhas | s DDL | s carga | s MERGE | bytes faturados (job)")
    for m in medidas:
        print(
            f"{m['tabela']} | {m['linhas']} | {m['s_ddl']:.1f} | {m['s_carga']:.1f} | "
            f"{m['s_merge']:.1f} | {m['bytes_faturados']:,}".replace(",", ".")
        )
    total = sum(m["bytes_faturados"] for m in medidas)
    print(
        f"total: {total:,} bytes faturados ({total / 1024 / 1024:.1f} MiB); "
        f"tempo total {time.perf_counter() - inicio:.1f}s".replace(",", ".")
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="comando", required=True)
    g = sub.add_parser("gerar")
    g.add_argument("--n", type=int, default=N_PADRAO)
    g.add_argument("--semente", type=int, default=SEMENTE_BASE)
    g.add_argument("--dry-run", action="store_true")
    p = sub.add_parser(
        "gerar-producao", help="só a origem de produção mais recente (cadeia mensal)"
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--forcar", action="store_true", help="id próprio mesmo se a origem já existe")
    args = ap.parse_args(argv)
    if args.comando == "gerar-producao":
        try:
            return gerar_producao(args.dry_run, forcar=args.forcar)
        except ErroDeOrigem as erro:
            print(f"ABORTADO, nada foi gravado: {erro}", file=sys.stderr)
            return 2
    return gerar(args.n, args.dry_run, args.semente)


if __name__ == "__main__":
    sys.exit(main())
