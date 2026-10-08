"""Resume UMA execução da DAG `energia_livre_diaria` e compara com o "antes" da Sprint 3.

    uv run python -m scripts.resumir_execucao_dag --rotulo normal \\
        --dag "success|2026-10-07T21:00:03|2026-10-07T21:04:10|247.0" \\
        --tarefas data/logs/passo8_normal_tarefas.txt --bytes data/logs/passo8_normal_bytes.log \\
        [--esperado sucesso|falha]

`--tarefas`: uma linha por task, `task_id|estado|tentativa|segundos` (psql -tA no Postgres do
Airflow). `--bytes`: a saída de `scripts.medir_bytes_bigquery` para o intervalo da execução (os jobs
do dbt, inclusive a freshness, e as validações da ingestão). Só leitura; não toca em nada.

O "antes" (Sprint 3, execução agendada de 06/10/2026, medidor corrigido, `docs/metricas.md`):
DAG 6 min 40 s, `ons_ingestao` 4 min 22 s, dbt 194 jobs, 1.557,9 MB processados e 2.965,4 MB
faturados (total com a validação do raw: 3.031,4 MB).
"""

import argparse
import re
import sys
from dataclasses import dataclass

ANTES = {
    "dag_s": 400.0,  # 6 min 40 s
    "ons_ingestao_s": 262.0,  # 4 min 22 s
    "dbt_jobs": 194,
    "dbt_processados_mb": 1557.9,
    "dbt_faturados_mb": 2965.4,
    "total_faturados_mb": 3031.4,
}
PADRAO_BYTES = re.compile(
    r"^(?P<origem>dbt|outros[^|]*?|total)\s+(?:(?P<jobs>\d+) jobs \(\d+ com erro\) \| )?"
    r"(?:processados\s+(?P<proc>[\d.]+) MB \| faturados\s+(?P<fat>[\d.]+) MB)"
)


@dataclass
class Tarefa:
    id: str
    estado: str
    tentativa: int
    segundos: float


def ler_tarefas(texto: str) -> list[Tarefa]:
    saida = []
    for linha in texto.splitlines():
        partes = linha.strip().split("|")
        if len(partes) != 4 or not partes[0]:
            continue
        segundos = float(partes[3]) if partes[3] else 0.0
        saida.append(Tarefa(partes[0], partes[1], int(partes[2] or 0), segundos))
    return saida


def ler_bytes(texto: str) -> dict[str, dict[str, float]]:
    """{'dbt': {'jobs', 'proc', 'fat'}, 'outros': {...}, 'total': {...}}, o que existir no texto."""
    saida: dict[str, dict[str, float]] = {}
    for linha in texto.splitlines():
        achou = PADRAO_BYTES.match(linha.strip())
        if achou:
            origem = "outros" if achou["origem"].startswith("outros") else achou["origem"]
            saida[origem] = {
                "jobs": float(achou["jobs"] or 0),
                "proc": float(achou["proc"]),
                "fat": float(achou["fat"]),
            }
    return saida


def minutos(segundos: float) -> str:
    return f"{int(segundos // 60)} min {int(round(segundos % 60)):02d} s"


def variacao(antes: float, depois: float) -> str:
    return f"{100 * (depois - antes) / antes:+.0f}%" if antes else "n/d"


def tabela_de_comparacao(dag_s: float, tarefas: list[Tarefa], bytes_: dict) -> list[str]:
    ons = next((t.segundos for t in tarefas if t.id == "ons_ingestao"), None)
    dbt = bytes_.get("dbt", {"jobs": 0, "proc": 0.0, "fat": 0.0})
    total = bytes_.get("total", {"fat": dbt["fat"]})
    linhas = [f"{'medida':34} {'antes (06/10)':>16} {'depois':>16} {'variação':>9}"]

    def linha(nome, antes_txt, depois_txt, antes=None, depois=None):
        v = variacao(antes, depois) if antes is not None and depois is not None else ""
        linhas.append(f"{nome:34} {antes_txt:>16} {depois_txt:>16} {v:>9}")

    linha("DAG, do início ao fim", minutos(ANTES["dag_s"]), minutos(dag_s), ANTES["dag_s"], dag_s)
    if ons is not None:
        linha(
            "task ons_ingestao",
            minutos(ANTES["ons_ingestao_s"]),
            minutos(ons),
            ANTES["ons_ingestao_s"],
            ons,
        )
    linha(
        "jobs do dbt", str(ANTES["dbt_jobs"]), f"{int(dbt['jobs'])}", ANTES["dbt_jobs"], dbt["jobs"]
    )
    linha(
        "dbt, MB processados",
        f"{ANTES['dbt_processados_mb']:.1f}",
        f"{dbt['proc']:.1f}",
        ANTES["dbt_processados_mb"],
        dbt["proc"],
    )
    linha(
        "dbt, MB faturados",
        f"{ANTES['dbt_faturados_mb']:.1f}",
        f"{dbt['fat']:.1f}",
        ANTES["dbt_faturados_mb"],
        dbt["fat"],
    )
    linha(
        "total faturado (dbt + validações)",
        f"{ANTES['total_faturados_mb']:.1f}",
        f"{total['fat']:.1f}",
        ANTES["total_faturados_mb"],
        total["fat"],
    )
    return linhas


def avaliar(estado_dag: str, tarefas: list[Tarefa], esperado: str) -> list[str]:
    """Problemas da execução em relação ao esperado ('sucesso' ou 'falha' proposital)."""
    problemas = []
    por_id = {t.id: t for t in tarefas}
    if esperado == "sucesso":
        if estado_dag != "success":
            problemas.append(f"a DAG terminou em '{estado_dag}', esperado 'success'")
        problemas += [
            f"task {t.id}: {t.estado} (tentativa {t.tentativa})"
            for t in tarefas
            if t.estado not in ("success", "skipped")
        ]
    else:  # falha proposital: o dbt_test falha, sem retentativa, e o pipeline não fecha
        if estado_dag != "failed":
            problemas.append(f"a DAG terminou em '{estado_dag}', esperado 'failed'")
        teste = por_id.get("dbt_test")
        if teste is None or teste.estado != "failed":
            problemas.append("o dbt_test deveria ter falhado")
        elif teste.tentativa != 1:
            problemas.append(f"o dbt_test foi repetido (tentativa {teste.tentativa}): não deveria")
        # nada que dependa do dbt_test pode rodar: a previsão e o fechamento ficam upstream_failed
        # (o pipeline_ok é NONE_FAILED, que trata upstream_failed como falha, não como skipped)
        for depois in ("previsao_ha_mes_novo", "previsao_mensal", "pipeline_ok"):
            t = por_id.get(depois)
            if t is None or t.estado != "upstream_failed":
                problemas.append(f"{depois} deveria ficar 'upstream_failed'")
    return problemas


def montar_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Resume e compara uma execução da DAG")
    p.add_argument("--rotulo", required=True)
    p.add_argument("--dag", required=True, help="estado|inicio|fim|segundos da execução")
    p.add_argument("--tarefas", required=True, help="arquivo task_id|estado|tentativa|segundos")
    p.add_argument("--bytes", required=True, help="saída do medir_bytes_bigquery")
    p.add_argument("--esperado", choices=["sucesso", "falha"], default="sucesso")
    return p


def main(argv: list[str]) -> int:
    args = montar_parser().parse_args(argv)
    estado, inicio, fim, segundos = (args.dag.split("|") + ["", "", "", "0"])[:4]
    dag_s = float(segundos or 0)
    with open(args.tarefas, encoding="utf-8") as f:
        tarefas = ler_tarefas(f.read())
    with open(args.bytes, encoding="utf-8") as f:
        bytes_ = ler_bytes(f.read())
    print(f"=== execução '{args.rotulo}': {estado}, {inicio} a {fim} (UTC), {minutos(dag_s)} ===")
    for t in tarefas:
        print(f"  {t.id:26} {t.estado:15} tentativa {t.tentativa}  {minutos(t.segundos):>10}")
    print()
    for linha in tabela_de_comparacao(dag_s, tarefas, bytes_):
        print(linha)
    problemas = avaliar(estado, tarefas, args.esperado)
    for problema in problemas:
        print(f"PROBLEMA: {problema}")
    print("OK" if not problemas else "COM PROBLEMAS")
    return 0 if not problemas else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
