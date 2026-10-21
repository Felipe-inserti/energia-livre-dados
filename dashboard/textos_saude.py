"""Textos da página Saúde do pipeline, no mesmo padrão da Decisão e da Previsão: números do
snapshot, nunca digitados; `$` escapado; linguagem comum (siglas com ajuda e no glossário).

Três coisas aqui NÃO vêm do snapshot e por isso têm fonte escrita e teste:
- `FALHAS_PROPOSITAIS`: quais execuções falharam de propósito (cada `run_id` consta do metricas.md);
- `LINHA_SPRINT_4`: os ganhos da Sprint 4 (conferidos contra o metricas.md);
- `ETAPAS` e `TIPOS_DE_TESTE`: nomes em português das etapas da DAG e dos tipos de teste do dbt.
"""

import pandas as pd

from dashboard import calculos as cal
from dashboard import glossario

CHAVES = {
    "maquina": "Roda na máquina do autor: execução ausente pode ser máquina desligada",
    "ultimo_dbt": "Último dbt test",
    "provavelmente_manual": "provavelmente manual",
    "fontes_manuais": "CCEE e INMET (manuais) não entram",
    "sem_execucao": "sem execução registrada",
    "nao_ao_vivo": "não ao vivo",
}

GLOSSARIO = glossario.selecionar("DAG", "dbt", "Aviso", "Fonte manual")
TITULO_LIMITES = "O que este estado não mostra"

# Execuções que falharam DE PROPÓSITO (testes do alerta do Discord, `{"falha_proposital": true}`),
# com a fonte de cada uma. Toda outra falha aparece só como "falha". Um teste confere que cada
# `run_id` consta do docs/metricas.md.
FALHAS_PROPOSITAIS = {
    "manual__2026-10-06T22:12:05.158514+00:00": "metricas.md, Sprint 3 (3.7): "
    "falha_proposital=true",
    "manual__passo8_falha_20261007T045457": "metricas.md, Sprint 6 C2 (registro das falhas): "
    "disparada com falha_proposital (data/logs/passo8_falha_trigger.log)",
    "manual__falha_20261008T032754": "metricas.md, Sprint 6 C2 (registro das falhas): "
    "disparada com falha_proposital (data/logs/sprint5c_dag_falha.log)",
}

# Sprint 4 (docs/metricas.md, "A DAG com a previsão mensal, medida"): conferido por teste
LINHA_SPRINT_4 = (
    "Ganhos da Sprint 4: DAG de 6 min 40 s → 1 min 54 s (−71%), já incluindo a previsão mensal, "
    "que a DAG de antes não tinha; bytes faturados −69%. Fonte: métricas da Sprint 4 (detalhe na "
    "auditoria)."
)
FONTE_SPRINT_4 = (
    'docs/metricas.md, seção "A DAG com a previsão mensal, medida (dag-gerar, 08/10/2026)": '
    "6 min 40 s → 1 min 54 s (−71%) e total faturado (dbt + validações) 3.031,4 → 944,8 MB (−69%)."
)

ETAPAS = {
    "ons_ingestao": "Ingestão do ONS",
    "dbt_run": "dbt: construir tabelas",
    "dbt_test": "dbt: testes",
    "freshness_ons": "Checagem do ONS",
    "freshness_manuais": "Checagem das fontes manuais",
    "previsao_mensal": "Previsão mensal",
    "previsao_ha_mes_novo": "Há mês novo para prever?",
    "parametros_execucao": "Parâmetros da execução",
    "selecao_dbt": "Seleção do dbt",
    "ccee_ha_arquivo_novo": "CCEE: há arquivo novo?",
    "inmet_ha_arquivo_novo": "INMET: há arquivo novo?",
    "ccee_ingestao": "CCEE: ingestão",
    "inmet_ingestao": "INMET: ingestão",
    "ccee_registrar_estado": "CCEE: registrar estado",
    "inmet_registrar_estado": "INMET: registrar estado",
    "pipeline_ok": "Fim do pipeline",
}

TIPOS_DE_TESTE = {
    "accepted_range": "Faixa de valores",
    "accepted_values": "Valores aceitos",
    "equal_rowcount": "Mesma contagem de linhas",
    "not_null": "Sem nulos",
    "relationships": "Chaves que existem na outra tabela",
    "singular": "Regra própria do projeto",
    "unique": "Valores únicos",
    "unique_combination_of_columns": "Combinação única de colunas",
}

ESTADOS = {
    "success": "sucesso",
    "failed": "falha",
    "skipped": "pulada",
    "upstream_failed": "não rodou (etapa anterior falhou)",
    "running": "em andamento",
    "queued": "na fila",
}
TIPOS_DE_EXECUCAO = {"scheduled": "agendada", "manual": "manual"}


def etapa(task_id: str) -> str:
    return ETAPAS.get(task_id, task_id)


def plural(n: int, singular: str, plural_: str) -> str:
    return f"{n} {singular if n == 1 else plural_}"


def dias(n: int) -> str:
    return plural(n, "dia", "dias")


def mes(d) -> str:
    return cal.mes_por_extenso(d)


def data_curta(d) -> str:
    d = pd.Timestamp(d)
    return f"{d.day:02d}/{d.month:02d}"


# ---------------------------------------------------------------- em uma frase


def frase(data: str, ultima: dict | None, dbt: dict | None, fontes: dict) -> str:
    partes = []
    if ultima is None:
        partes.append("não há registro das execuções da DAG")
    else:
        resultado = "terminou com sucesso" if ultima["estado"] == "success" else "falhou"
        partes.append(
            f"a última execução da DAG {resultado} em {cal.duracao_texto(ultima['duracao_s'])}"
        )
    if dbt is None:
        partes.append("não há resultado do dbt test nesta máquina")
    else:
        partes.append(
            f"o último dbt test {'completo ' if dbt['completo'] else ''}passou em "
            f"{dbt['pass']} de {dbt['testes']} testes "
            f"({plural(dbt['warn'], 'aviso', 'avisos')}, {plural(dbt['error'], 'erro', 'erros')})"
        )
    todas = fontes["fontes_nesse_mes"] == fontes["fontes"]
    ate = mes(fontes["mes"])
    partes.append(
        f"as {fontes['fontes']} fontes vão até {ate}"
        if todas
        else f"a fonte mais atrasada vai até {ate}"
    )
    return f"No snapshot de {data}, " + ", ".join(partes[:-1]) + f" e {partes[-1]}."


# ---------------------------------------------------------------- cartões


def cartoes(ultima: dict | None, dbt: dict | None, fontes: dict, dias_do_fim: int) -> list[dict]:
    if ultima is None:
        c1 = {
            "ressalva": CHAVES["maquina"],
            "rotulo": "Última execução da DAG",
            "valor": "Indisponível",
            "linhas": ["o banco de metadados do orquestrador não respondeu na geração do snapshot"],
            "ajuda": glossario.TERMOS["DAG"],
        }
    else:
        n = ultima["contagem"]
        c1 = {
            "ressalva": CHAVES["maquina"],
            "rotulo": "Última execução da DAG",
            "valor": "Sucesso" if ultima["estado"] == "success" else "Falhou",
            "linhas": [
                f"{cal.hora_utc(ultima['inicio'])} · {cal.duracao_texto(ultima['duracao_s'])} · "
                f"{TIPOS_DE_EXECUCAO.get(ultima['tipo'], ultima['tipo'])}",
                f"{n['total']} execuções registradas: {n['sucesso']} com sucesso, "
                f"{n['falha']} com falha",
            ],
            "ajuda": glossario.TERMOS["DAG"],
        }
    if dbt is None:
        c2 = {
            "ressalva": f"{CHAVES['ultimo_dbt']} nesta máquina, que pode não ser o da DAG",
            "rotulo": "Testes do dbt",
            "valor": "Indisponível",
            "linhas": ["o resultado do dbt test não existe nesta máquina"],
            "ajuda": f"{glossario.TERMOS['dbt']} {glossario.TERMOS['Aviso']}",
        }
    else:
        c2 = {
            "ressalva": (
                f"{CHAVES['ultimo_dbt']} {'completo' if dbt['completo'] else 'parcial'} nesta "
                f"máquina ({CHAVES['provavelmente_manual']}, {cal.hora_utc(dbt['gerado_em'])})"
            ),
            "rotulo": "Testes do dbt",
            "valor": f"{dbt['pass']} de {dbt['testes']}",
            "linhas": [
                f"{plural(dbt['warn'], 'aviso', 'avisos')} · "
                f"{plural(dbt['error'], 'erro', 'erros')}"
            ],
            "ajuda": f"{glossario.TERMOS['dbt']} {glossario.TERMOS['Aviso']}",
        }
    todas = fontes["fontes_nesse_mes"] == fontes["fontes"]
    if dias_do_fim <= 0:
        encerrado = "mês ainda em andamento na data do snapshot"
    else:
        encerrado = f"mês encerrado há {dias(dias_do_fim)} na data do snapshot"
    c3 = {
        "ressalva": (
            f"{'As' if todas else 'Das'} {fontes['fontes']} fontes do snapshot; "
            f"{CHAVES['fontes_manuais']}"
        ),
        "rotulo": "Último mês com dado",
        "valor": mes(fontes["mes"]),
        "linhas": [
            encerrado,
            "todas as fontes chegam a esse mês"
            if todas
            else f"{fontes['fontes_nesse_mes']} de {fontes['fontes']} fontes chegam só a esse mês",
        ],
        "ajuda": glossario.TERMOS["Fonte manual"],
    }
    return [c1, c2, c3]


def nota_fontes_manuais(checagem: dict) -> str:
    estado = (
        ESTADOS.get(checagem["estado"], "sem registro") if checagem["estado"] else "sem registro"
    )
    quando = (
        f", {cal.numero(checagem['duracao_s'], 1)} s" if checagem["duracao_s"] is not None else ""
    )
    return (
        "A idade dos dados da CCEE e do INMET não está no snapshot; essas fontes são baixadas à "
        "mão e só avisam. A checagem delas rodou na última execução "
        f"(estado: {estado}{quando}), mas o estado não diz quão velhos são os dados."
    )


# ---------------------------------------------------------------- gráficos


def legenda_execucoes(runs: pd.DataFrame, ausentes: list[pd.Timestamp], propositais: int) -> str:
    n, falhas = len(runs), int(runs["falhou"].sum())
    partes = [
        f"Uma barra por execução ({n}, de {data_curta(runs['inicio'].min())} a "
        f"{data_curta(runs['inicio'].max())}; horas em UTC; ag. = agendada, man. = manual); "
        "✕ marca falha."
    ]
    if falhas:
        if propositais == falhas:
            frase_ = plural(falhas, "falha foi proposital", "falhas foram propositais")
            quais = f"{frase_} (testes do alerta)"
        elif propositais == 0:
            quais = f"{plural(falhas, 'falha', 'falhas')}, sem causa registrada"
        else:
            quais = (
                f"{propositais} de {plural(falhas, 'falha', 'falhas')} foram propositais "
                f"(testes do alerta); as outras {falhas - propositais} não têm causa registrada"
            )
        partes.append(quais[0].upper() + quais[1:] + ".")
    for a in ausentes:
        partes.append(
            f"Em {data_curta(a)}, {a.hour:02d}:{a.minute:02d} UTC, a execução agendada está "
            f"ausente do registro: combina com máquina desligada (dias sem execução não viram "
            "fila; a seguinte recarrega o período)."
        )
    return " ".join(partes)


def legenda_etapas(minimo_s: float = 5.0) -> str:
    return (
        f"Só as etapas que levam em média {cal.numero(minimo_s, 0)} s ou mais; etapas puladas ou "
        "que não rodaram não têm duração e não aparecem (nunca viram zero). ✕ marca falha."
    )


# ---------------------------------------------------------------- limites


def limites(data: str, runs: pd.DataFrame) -> list[str]:
    return [
        f"**É o estado de {data}**, {CHAVES['nao_ao_vivo']}: o que aconteceu depois não aparece.",
        f"**Só {len(runs)} execuções, de {data_curta(runs['inicio'].min())} a "
        f"{data_curta(runs['inicio'].max())}**: dá para ver falhas e durações, não para falar de "
        "estabilidade.",
        "**Do dbt só há o último comando desta máquina**: o histórico dos testes da DAG não está "
        "no snapshot.",
    ]


# ---------------------------------------------------------------- auditoria


def auditoria(manifesto: dict, runs: pd.DataFrame, dbt: dict | None, ultima: dict | None) -> str:
    saude = manifesto["saude"]
    partes = [
        "**Fontes.** Execuções: banco de metadados do Airflow (Postgres local), tabelas "
        f"`dag_run` e `task_instance`, as últimas 30 pedidas ({len(runs)} existem). Testes: "
        "`dbt/target/run_results.json` local. Idade das fontes: calculada dos arquivos do próprio "
        "snapshot (`frescor_fontes.csv`)."
    ]
    if dbt is not None:
        t = saude["testes_dbt"]
        partes.append(
            f"**Resultado do dbt.** `generated_at` = `{t['run_results_gerado_em']}`, comando "
            f"`{t['comando']}`, seleção {'vazia' if dbt['completo'] else str(t['selecao'])}, "
            f"{t['n_resultados']} resultados, {cal.numero(t['tempo_s'], 1)} s."
        )
    if dbt is not None and ultima is not None:
        fim = ultima["inicio"] + pd.Timedelta(seconds=ultima["duracao_s"])
        gerado = pd.Timestamp(dbt["gerado_em"])
        partes.append(
            "**Inferência, não fato registrado: o `run_results.json` provavelmente não é o da "
            "DAG.** O arquivo foi gerado às "
            f"{gerado:%H:%M:%S}Z, depois do fim da última execução da DAG ({fim:%H:%M:%S}Z), e "
            f"levou {cal.numero(saude['testes_dbt']['tempo_s'], 1)} s, contra "
            f"{cal.numero(ultima['dbt_test_s'], 1)} s do `dbt_test` dessa execução. O log local "
            "`data/logs/dbt_test_completo_6c2.log` (fora do repositório) termina no mesmo "
            f"horário ({gerado:%H:%M:%S}) e na mesma contagem ({dbt['testes']} testes: "
            f"{dbt['pass']}/{dbt['warn']}/{dbt['error']}). Horário e contagem coincidem, mas "
            "quem disparou o comando não está registrado: por isso o cartão diz "
            f'"{CHAVES["provavelmente_manual"]}".'
        )
    partes.append(
        "**Falhas propositais** (só estas execuções são rotuladas assim; as outras são "
        '"falha"):\n\n'
        + "\n".join(f"- `{rid}`: {fonte}" for rid, fonte in FALHAS_PROPOSITAIS.items())
    )
    partes.append(
        "**Execução ausente.** O horário esperado é diário às 21:00 UTC "
        '(`airflow/dags/energia_livre_diaria.py`: `schedule="0 21 * * *"`, `catchup=False`); '
        "ausente = horário sem execução agendada entre a primeira e a última registradas."
    )
    sprint_4 = f"**Sprint 4.** {FONTE_SPRINT_4}"
    agendadas = runs[runs["run_type"] == "scheduled"]
    if not agendadas.empty:
        antiga = agendadas.iloc[0]
        sprint_4 += (
            f" A barra agendada mais antiga ({data_curta(antiga['inicio'])}) mede "
            f"{cal.numero(antiga['duracao_dag_s'], 1)} s "
            f"({cal.duracao_texto(antiga['duracao_dag_s'])}) "
            "no registro do Airflow, contra os 6 min 40 s do documento: a diferença de ~1 s vem do "
            "arredondamento e de onde se conta o início."
        )
    partes.append(sprint_4)
    return "\n\n".join(partes)
