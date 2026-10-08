"""Previsão mensal em produção (5.4): gera `marts.fct_previsao_carga` e `fct_erro_previsao_carga`.

    uv run --env-file .env python -m ml.previsao verificar        # exit 0: mês novo; 10: nada novo
    uv run --env-file .env python -m ml.previsao gerar --dry-run # só lê e mostra; não grava
    uv run --env-file .env python -m ml.previsao gerar           # grava (idempotente)

O modelo é MENSAL: rodar todo dia não faz sentido. A DAG diária chama `verificar` (ShortCircuit) e
só roda `gerar` quando o último mês COMPLETO da série é posterior à última origem gravada. Mês
completo = `mes_utilizavel` e cobertura de 100% (>= 0,999): o limiar de 95% da `fct_carga_mensal`
aceita um dia faltando, e o ONS publica com ~2 dias de atraso, então no dia 2 o mês teria 1 dia
faltando e passaria com viés de até ~0,9% na origem.

`gerar`: (1) lê a série reconstruída do SE/CO; (2) calcula os erros realizados das previsões de
produção anteriores; (3) calibra os quantis com TODOS os erros (desenvolvimento, teste final e
produção; regra de produção em `ml/intervalos.py`); (4) prevê h = 1..12 a partir da última origem;
(5) grava por `MERGE` numa chave natural (reexecutar dá o mesmo resultado, sem duplicata).

PROVENIÊNCIA em toda linha: versão do modelo, hash dos parâmetros, hash do código (blobs do git dos
arquivos que definem a previsão), commit (lido do `.git`, sem o binário do git) e data de geração.
"""

import argparse
import hashlib
import json
import math
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from ml.intervalos import NIVEIS, Erro, calibrar, erro_de, intervalo, ultimo_alvo_do_vetor
from ml.registro import (
    CANDIDATO_DO_TESTE_FINAL,
    CASAS_DECIMAIS_CARGA,
    MODELO_VERSAO,
    SERIE_DE_PRODUCAO,
    arredondar_serie,
    parametros_do_modelo,
    previsor_do_vencedor,
)
from ml.validacao import HORIZONTES, somar_meses

RAIZ = Path(__file__).resolve().parents[1]
RESULTADOS = RAIZ / "docs" / "resultados"
PREVISAO = "marts.fct_previsao_carga"
ERROS = "marts.fct_erro_previsao_carga"
TEMP_PREVISAO = "staging.tmp_fct_previsao_carga"
TEMP_ERROS = "staging.tmp_fct_erro_previsao_carga"
SUBMERCADO = "SE"
COBERTURA_COMPLETA = 0.999
TETO_BYTES = 200 * 1024 * 1024
CODIGO = (
    "ml/validacao.py",
    "ml/features.py",
    "ml/preparo.py",
    "ml/modelos.py",
    "ml/intervalos.py",
    "ml/registro.py",
    "ml/previsao.py",
)
SAIDA_SEM_MES_NOVO = 10

ESQUEMA_PREVISAO = [
    ("modelo_versao", "STRING"),
    ("tipo", "STRING"),
    ("origem", "DATE"),
    ("horizonte", "INT64"),
    ("mes_alvo", "DATE"),
    ("previsao_mwmed", "FLOAT64"),
    ("p025_mwmed", "FLOAT64"),
    ("p10_mwmed", "FLOAT64"),
    ("p50_mwmed", "FLOAT64"),
    ("p90_mwmed", "FLOAT64"),
    ("p975_mwmed", "FLOAT64"),
    ("calibracao", "STRING"),
    ("n_erros_calibracao", "INT64"),
    ("serie", "STRING"),
    ("serie_ate", "DATE"),
    ("entrada_hash", "STRING"),
    ("entrada_meses", "INT64"),
    ("entrada_soma_mwmed", "FLOAT64"),
    ("entrada_janela_soma_mwmed", "FLOAT64"),
    ("entrada_ultimo_mwmed", "FLOAT64"),
    ("parametros_hash", "STRING"),
    ("codigo_hash", "STRING"),
    ("commit", "STRING"),
    ("gerado_em", "TIMESTAMP"),
]
CHAVE_PREVISAO = ("modelo_versao", "tipo", "origem", "horizonte")
ESQUEMA_ERROS = [
    ("modelo_versao", "STRING"),
    ("periodo", "STRING"),
    ("origem", "DATE"),
    ("horizonte", "INT64"),
    ("mes_alvo", "DATE"),
    ("ultimo_mes_alvo_da_origem", "DATE"),
    ("previsto_mwmed", "FLOAT64"),
    ("real_mwmed", "FLOAT64"),
    ("erro_mwmed", "FLOAT64"),
    ("erro_pct", "FLOAT64"),
    ("log_razao", "FLOAT64"),
    ("serie", "STRING"),
    ("parametros_hash", "STRING"),
    ("codigo_hash", "STRING"),
    ("commit", "STRING"),
    ("gerado_em", "TIMESTAMP"),
]
CHAVE_ERROS = ("modelo_versao", "periodo", "origem", "horizonte")


# ---------------------------------------------------------------- proveniência (sem git, sem nuvem)


def hash_blob_git(caminho: Path) -> str:
    """O mesmo hash de `git hash-object`: sha1("blob <tamanho>\\0" + conteúdo)."""
    dados = caminho.read_bytes()
    return hashlib.sha1(b"blob %d\0" % len(dados) + dados).hexdigest()  # noqa: S324


def ler_commit(raiz: Path = RAIZ) -> str:
    """O commit de HEAD lido de `.git` (a imagem do Airflow não tem o binário do git)."""
    git = raiz / ".git"
    try:
        head = (git / "HEAD").read_text().strip()
        if not head.startswith("ref: "):
            return head
        ref = head[5:]
        arquivo = git / ref
        if arquivo.exists():
            return arquivo.read_text().strip()
        for linha in (git / "packed-refs").read_text().splitlines():
            if linha.endswith(" " + ref):
                return linha.split()[0]
    except OSError:
        pass
    return "desconhecido"


def hash_curto(objeto) -> str:
    return hashlib.sha256(json.dumps(objeto, sort_keys=True, default=str).encode()).hexdigest()[:12]


def proveniencia(raiz: Path = RAIZ, agora: datetime | None = None) -> dict:
    return {
        "modelo_versao": MODELO_VERSAO,
        "parametros_hash": hash_curto(parametros_do_modelo()),
        "codigo_hash": hash_curto({c: hash_blob_git(raiz / c) for c in CODIGO}),
        "commit": ler_commit(raiz),
        "gerado_em": (agora or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# ---------------------------------------------------------------- linhas (puras)


def impressao_da_entrada(serie: dict[date, float], janela: int | None = None) -> dict:
    """Impressão digital da série que entrou no modelo: série igual, previsão igual.

    Hash de `mês:valor` com os valores na resolução da série (CASAS_DECIMAIS_CARGA), a contagem e a
    soma de todos os meses, a soma da janela de treino e o último valor. Serve para explicar
    qualquer diferença futura entre duas gerações da mesma origem (ONS revisou? o mart mudou?).
    """
    from ml.preparo import JANELA_MESES

    janela = janela or JANELA_MESES
    meses = sorted(serie)
    texto = "\n".join(f"{m.isoformat()}:{serie[m]:.{CASAS_DECIMAIS_CARGA}f}" for m in meses)
    return {
        "entrada_hash": hashlib.sha256(texto.encode()).hexdigest()[:12],
        "entrada_meses": len(meses),
        "entrada_soma_mwmed": round(math.fsum(serie[m] for m in meses), CASAS_DECIMAIS_CARGA),
        "entrada_janela_soma_mwmed": round(
            math.fsum(serie[m] for m in meses[-janela:]), CASAS_DECIMAIS_CARGA
        ),
        "entrada_ultimo_mwmed": round(serie[meses[-1]], CASAS_DECIMAIS_CARGA),
    }


def linhas_previsao(
    origem: date,
    previsoes: dict[int, float],
    quantis: dict[int, dict[str, float]],
    prov: dict,
    serie_ate: date,
    n_erros: int,
    calibracao: str,
    entrada: dict,
) -> list[dict]:
    linhas = []
    for h in HORIZONTES:
        lim = intervalo(previsoes[h], quantis[h])
        linhas.append(
            {
                "modelo_versao": prov["modelo_versao"],
                "tipo": "producao",
                "origem": origem.isoformat(),
                "horizonte": h,
                "mes_alvo": somar_meses(origem, h).isoformat(),
                "previsao_mwmed": previsoes[h],
                **{f"{nome}_mwmed": lim[nome] for nome in NIVEIS},
                "calibracao": calibracao,
                "n_erros_calibracao": n_erros,
                "serie": SERIE_DE_PRODUCAO,
                "serie_ate": serie_ate.isoformat(),
                **entrada,
                "parametros_hash": prov["parametros_hash"],
                "codigo_hash": prov["codigo_hash"],
                "commit": prov["commit"],
                "gerado_em": prov["gerado_em"],
            }
        )
    return linhas


def validar_linhas(linhas: list[dict]) -> None:
    """Falha (e nada é gravado) se a previsão não faz sentido (horizontes, positivos, ordem)."""
    if [x["horizonte"] for x in linhas] != list(HORIZONTES):
        raise ValueError("a previsão precisa dos horizontes 1..12, uma vez cada")
    origem = date.fromisoformat(linhas[0]["origem"])
    for x in linhas:
        if x["mes_alvo"] != somar_meses(origem, x["horizonte"]).isoformat():
            raise ValueError(f"mês-alvo errado no horizonte {x['horizonte']}")
        valores = [x[f"{n}_mwmed"] for n in NIVEIS]
        if not all(v is not None and v > 0 for v in (x["previsao_mwmed"], *valores)):
            raise ValueError(f"valor nulo ou não positivo no horizonte {x['horizonte']}")
        if not x.get("entrada_hash"):
            raise ValueError("falta a impressão digital da entrada")
        if not x["p025_mwmed"] < x["p10_mwmed"] < x["p90_mwmed"] < x["p975_mwmed"]:
            raise ValueError(f"quantis fora de ordem no horizonte {x['horizonte']}")


def linha_de_erro(
    periodo: str, origem: date, h: int, previsto: float, real: float, serie: str, prov: dict
) -> dict:
    e = erro_de(origem, h, previsto, real)
    return {
        "modelo_versao": prov["modelo_versao"],
        "periodo": periodo,
        "origem": origem.isoformat(),
        "horizonte": h,
        "mes_alvo": e.alvo.isoformat(),
        "ultimo_mes_alvo_da_origem": ultimo_alvo_do_vetor(origem).isoformat(),
        "previsto_mwmed": previsto,
        "real_mwmed": real,
        "erro_mwmed": previsto - real,
        "erro_pct": 100 * (previsto - real) / real,
        "log_razao": e.log_razao,
        "serie": serie,
        "parametros_hash": prov["parametros_hash"],
        "codigo_hash": prov["codigo_hash"],
        "commit": prov["commit"],
        "gerado_em": prov["gerado_em"],
    }


def erros_de_backtest(resultados: Path = RESULTADOS) -> list[dict]:
    """Erros do vencedor no desenvolvimento (original) e no teste final (reconstruída), dos arquivos
    versionados. A proveniência dessas linhas é a do `.meta.json` que gerou cada arquivo."""
    import csv

    linhas = []
    for periodo, serie in (("desenvolvimento", "original"), ("teste_final", "reconstruida")):
        meta = json.loads((resultados / f"candidatos_{periodo}_{serie}.meta.json").read_text())
        prov = {
            "modelo_versao": MODELO_VERSAO,
            "parametros_hash": hash_curto(parametros_do_modelo()),
            "codigo_hash": hash_curto(meta["hashes_de_conteudo"]),
            "commit": meta["commit"],
            "gerado_em": meta["gerado_em_utc"],
        }
        with (resultados / f"candidatos_{periodo}_{serie}_previsoes.csv").open(
            encoding="utf-8"
        ) as f:
            for r in csv.DictReader(f):
                if r["candidato"] != CANDIDATO_DO_TESTE_FINAL:
                    continue
                linhas.append(
                    linha_de_erro(
                        periodo,
                        date.fromisoformat(r["origem"]),
                        int(r["horizonte"]),
                        float(r["previsto_mwmed"]),
                        float(r["real_mwmed"]),
                        serie,
                        prov,
                    )
                )
    return linhas


def como_erros(linhas: list[dict]) -> list[Erro]:
    return [
        Erro(
            date.fromisoformat(str(x["origem"])),
            int(x["horizonte"]),
            date.fromisoformat(str(x["mes_alvo"])),
            float(x["log_razao"]),
        )
        for x in linhas
    ]


# ---------------------------------------------------------------- SQL (strings puras)


def ddl(tabela: str, esquema: list[tuple[str, str]], chave: tuple[str, ...]) -> str:
    colunas = ", ".join(f"`{n}` {t}" for n, t in esquema)
    return (
        f"CREATE TABLE IF NOT EXISTS `{tabela}` ({colunas}) "
        f"OPTIONS (description='Chave natural: {', '.join(chave)}. Gerada por ml.previsao.')"
    )


def colunas_novas(tabela: str, esquema: list[tuple[str, str]]) -> str:
    """ALTER idempotente: acrescenta as colunas que a tabela já criada ainda não tem."""
    adicoes = ", ".join(f"ADD COLUMN IF NOT EXISTS `{n}` {t}" for n, t in esquema)
    return f"ALTER TABLE `{tabela}` {adicoes}"


def merge(destino: str, origem: str, esquema: list[tuple[str, str]], chave: tuple[str, ...]) -> str:
    nomes = [n for n, _ in esquema]
    cond = " AND ".join(f"T.`{c}` = S.`{c}`" for c in chave)
    sets = ", ".join(f"T.`{n}` = S.`{n}`" for n in nomes if n not in chave)
    cols = ", ".join(f"`{n}`" for n in nomes)
    vals = ", ".join(f"S.`{n}`" for n in nomes)
    return (
        f"MERGE `{destino}` AS T USING `{origem}` AS S ON {cond} "
        f"WHEN MATCHED THEN UPDATE SET {sets} "
        f"WHEN NOT MATCHED THEN INSERT ({cols}) VALUES ({vals})"
    )


SQL_SERIE = f"""
    SELECT mes, carga_ajustada_reconstruida_mwmed AS valor, cobertura
    FROM `marts.fct_carga_mensal`
    WHERE codigo_submercado = '{SUBMERCADO}' AND mes_utilizavel
      AND carga_ajustada_reconstruida_mwmed IS NOT NULL
    ORDER BY mes"""


def ultima_origem_completa(serie_linhas: list[tuple[date, float, float]]) -> date:
    completas = [m for m, _, cob in serie_linhas if cob >= COBERTURA_COMPLETA]
    if not completas:
        raise RuntimeError("nenhum mês completo na série")
    return max(completas)


# ---------------------------------------------------------------- nuvem


def _cliente():
    from ingestion.common import gcp
    from ingestion.common.config import carregar_config

    return gcp, gcp.cliente_bigquery(carregar_config())


def _consulta(gcp, cliente, sql: str):
    return gcp.executar_consulta(cliente, sql, max_bytes_faturados=TETO_BYTES)


def _tabela_existe(cliente, tabela: str) -> bool:
    from google.api_core.exceptions import NotFound

    try:
        cliente.get_table(tabela)
        return True
    except NotFound:
        return False


def _gravar(gcp, cliente, linhas, temp, destino, esquema, chave) -> None:
    from google.cloud import bigquery

    campos = [bigquery.SchemaField(n, t) for n, t in esquema]
    cliente.load_table_from_json(
        linhas,
        temp,
        job_config=bigquery.LoadJobConfig(
            schema=campos, write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE
        ),
    ).result()
    try:
        _consulta(gcp, cliente, merge(destino, temp, esquema, chave))
    finally:
        cliente.delete_table(temp, not_found_ok=True)


def ler_serie(gcp, cliente) -> tuple[dict[date, float], date]:
    res = _consulta(gcp, cliente, SQL_SERIE)
    linhas = [(r["mes"], float(r["valor"]), float(r["cobertura"])) for r in res.linhas]
    origem = ultima_origem_completa(linhas)
    serie = {m: v for m, v, _ in linhas if m <= origem}
    return arredondar_serie(serie), origem


def ultima_origem_gravada(gcp, cliente) -> date | None:
    if not _tabela_existe(cliente, PREVISAO):
        return None
    sql = (
        f"SELECT MAX(origem) AS o FROM `{PREVISAO}` "
        f"WHERE modelo_versao = '{MODELO_VERSAO}' AND tipo = 'producao'"
    )
    return _consulta(gcp, cliente, sql).linhas[0]["o"]


def verificar() -> int:
    gcp, cliente = _cliente()
    _, origem = ler_serie(gcp, cliente)
    gravada = ultima_origem_gravada(gcp, cliente)
    novo = gravada is None or origem > gravada
    print(
        f"último mês completo: {origem:%Y-%m}; última origem gravada: {gravada:%Y-%m}"
        if gravada
        else f"último mês completo: {origem:%Y-%m}; nenhuma origem gravada"
    )
    print("mês novo: gerar a previsão" if novo else "sem mês novo: nada a fazer")
    return 0 if novo else SAIDA_SEM_MES_NOVO


def erros_realizados(gcp, cliente, serie: dict[date, float], prov: dict) -> list[dict]:
    """Erro das previsões de produção já gravadas cujo mês-alvo agora tem valor real."""
    if not _tabela_existe(cliente, PREVISAO):
        return []
    sql = (
        f"SELECT origem, horizonte, mes_alvo, previsao_mwmed FROM `{PREVISAO}` "
        f"WHERE modelo_versao = '{MODELO_VERSAO}' AND tipo = 'producao'"
    )
    return [
        linha_de_erro(
            "producao",
            r["origem"],
            r["horizonte"],
            r["previsao_mwmed"],
            serie[r["mes_alvo"]],
            "reconstruida",
            prov,
        )
        for r in _consulta(gcp, cliente, sql).linhas
        if r["mes_alvo"] in serie
    ]


def gerar(dry_run: bool, forcar: bool) -> int:
    gcp, cliente = _cliente()
    serie, origem = ler_serie(gcp, cliente)
    gravada = ultima_origem_gravada(gcp, cliente)
    if gravada is not None and origem <= gravada and not forcar:
        print(f"origem {origem:%Y-%m} já gravada: nada a fazer (use --forcar para regravar)")
        return 0
    prov = proveniencia()
    print(
        f"origem {origem:%Y-%m}; série de {min(serie):%Y-%m} a {max(serie):%Y-%m}; "
        f"commit {prov['commit'][:10]}; parâmetros {prov['parametros_hash']}"
    )
    backtest = erros_de_backtest()
    realizados = erros_realizados(gcp, cliente, serie, prov)
    todos = como_erros(backtest) + como_erros(realizados)
    quantis = calibrar(todos, modo="producao")
    previsoes = previsor_do_vencedor()(serie, origem, list(HORIZONTES))
    if set(previsoes) != set(HORIZONTES):
        raise RuntimeError(f"o modelo não previu todos os horizontes: {sorted(previsoes)}")
    calibracao = "desenvolvimento+teste_final" + ("+producao" if realizados else "")
    entrada = impressao_da_entrada(serie)
    print(
        f"entrada: {entrada['entrada_meses']} meses, hash {entrada['entrada_hash']}, "
        f"soma {entrada['entrada_soma_mwmed']}, último {entrada['entrada_ultimo_mwmed']}"
    )
    linhas = linhas_previsao(
        origem, previsoes, quantis, prov, max(serie), len(todos), calibracao, entrada
    )
    validar_linhas(linhas)
    for x in linhas:
        print(
            f"  h={x['horizonte']:2d} {x['mes_alvo']}  {x['previsao_mwmed']:9.0f}  "
            f"[{x['p025_mwmed']:9.0f} {x['p10_mwmed']:9.0f} "
            f"{x['p90_mwmed']:9.0f} {x['p975_mwmed']:9.0f}]"
        )
    if dry_run:
        print(
            f"DRY-RUN: nada gravado ({len(linhas)} previsões, {len(backtest)} erros de backtest, "
            f"{len(realizados)} realizados)"
        )
        return 0
    _consulta(gcp, cliente, ddl(PREVISAO, ESQUEMA_PREVISAO, CHAVE_PREVISAO))
    _consulta(
        gcp, cliente, colunas_novas(PREVISAO, ESQUEMA_PREVISAO)
    )  # tabela criada antes da impressão
    _consulta(gcp, cliente, ddl(ERROS, ESQUEMA_ERROS, CHAVE_ERROS))
    _gravar(gcp, cliente, backtest + realizados, TEMP_ERROS, ERROS, ESQUEMA_ERROS, CHAVE_ERROS)
    _gravar(gcp, cliente, linhas, TEMP_PREVISAO, PREVISAO, ESQUEMA_PREVISAO, CHAVE_PREVISAO)
    print(
        f"gravado: {len(linhas)} previsões em {PREVISAO}; "
        f"{len(backtest) + len(realizados)} erros em {ERROS}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="comando", required=True)
    sub.add_parser("verificar", help="exit 0 se fechou um mês novo, 10 se não")
    g = sub.add_parser("gerar", help="gera e grava a previsão da última origem completa")
    g.add_argument("--dry-run", action="store_true", help="lê e mostra, sem gravar")
    g.add_argument("--forcar", action="store_true", help="regrava mesmo com a origem já gravada")
    args = ap.parse_args(argv)
    if args.comando == "verificar":
        return verificar()
    return gerar(args.dry_run, args.forcar)


if __name__ == "__main__":
    sys.exit(main())
