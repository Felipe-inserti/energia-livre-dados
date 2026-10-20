"""Página "Saúde do pipeline": números conferidos contra os CSVs do snapshot e contra o
`docs/metricas.md`, ressalva acima do número, falha por símbolo e texto (sem cor nova), execução
ausente derivada dos dados, orçamento de palavras, `$` escapado, jargão fora da auditoria."""

import csv
import json
import re
import shutil
from pathlib import Path

import pandas as pd
import pytest
from apptest_util import (
    achatar,
    dados_do_grafico,
    elementos,
    expander,
    indice,
    indice_exp,
    palavras,
    palavras_visiveis,
    spec,
    texto,
    textos_do_grafico,
)
from streamlit.testing.v1 import AppTest

from dashboard import calculos as cal
from dashboard import glossario
from dashboard import leitura as lei
from dashboard import textos_saude as tx
from dashboard import visual as vis

RAIZ = Path(__file__).resolve().parents[1]
DADOS = RAIZ / "dashboard" / "dados"
ORCAMENTO_DE_PALAVRAS = 400
METRICAS = (RAIZ / "docs" / "metricas.md").read_text()
UTC = "UTC"


def pagina(diretorio: str | None = None):
    from dashboard.paginas import saude

    saude.renderizar(diretorio)


def rodar(diretorio: Path | None = None) -> AppTest:
    at = AppTest.from_function(
        pagina, args=(str(diretorio) if diretorio else None,), default_timeout=90
    )
    at.run()
    return at


@pytest.fixture(scope="module")
def at():
    return rodar()


def linhas_csv(nome: str) -> list[dict]:
    with open(DADOS / nome, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def runs_do_csv() -> list[dict]:
    vistos = {}
    for r in linhas_csv("saude_execucoes.csv"):
        vistos.setdefault(r["run_id"], r)
    return sorted(vistos.values(), key=lambda r: r["inicio_utc"])


# ---------------------------------------------------------------- números do snapshot


def test_os_numeros_esperados_batem_com_os_csvs_do_snapshot():
    """O teste não inventa: 11 execuções (8 sucesso, 3 falha), 250 testes (249/1/0), 5 fontes."""
    runs = runs_do_csv()
    assert len(runs) == 11
    assert sum(r["estado_dag"] == "success" for r in runs) == 8
    assert sum(r["estado_dag"] == "failed" for r in runs) == 3
    testes = linhas_csv("saude_testes_dbt.csv")
    soma = {k: sum(int(t[k]) for t in testes) for k in ("testes", "pass", "warn", "error")}
    assert soma == {"testes": 250, "pass": 249, "warn": 1, "error": 0}
    assert len(linhas_csv("frescor_fontes.csv")) == 5
    man = lei.manifesto()["saude"]
    assert man["execucoes_da_dag"]["execucoes"] == 11 and man["testes_dbt"]["n_resultados"] == 250


# ---------------------------------------------------------------- carrega e estrutura


def test_a_pagina_carrega_sem_excecao(at):
    assert not at.exception
    assert len(at.get("vega_lite_chart")) == 2  # 1 à vista + o de etapas, no expander


def test_a_ordem_da_piramide(at):
    nos = elementos(at)
    assert nos[0][0] == "title" and nos[0][1].value == "Saúde do pipeline"
    ordem = [
        indice(at, "info", "No snapshot de"),
        indice(at, "metric", "Última execução da DAG"),
        indice(at, "metric", "Testes do dbt"),
        indice(at, "metric", "Último mês com dado"),
        indice(at, "info", "A idade dos dados da CCEE"),
        indice(at, "subheader", "Duração das execuções"),
        indice(at, "vega_lite_chart", "duracao_dag_s"),
        indice(at, "caption", "Ganhos da Sprint 4"),
        indice(at, "subheader", tx.TITULO_LIMITES),
        indice_exp(at, "Ver valores"),
        indice_exp(at, "Glossário"),
        indice_exp(at, "Auditoria"),
    ]
    assert ordem == sorted(ordem)


def test_o_cabecalho_diz_de_quando_sao_os_dados(at):
    assert "10/10/2026" in at.caption[0].value and "sem consulta ao vivo" in at.caption[0].value


# ---------------------------------------------------------------- frase e cartões


def test_a_frase_traz_os_numeros_do_snapshot(at):
    frase = at.info[0].value
    assert "No snapshot de 10/10/2026" in frase
    assert "terminou com sucesso em 1 min 54 s" in frase  # 114,4 s
    assert "249 de 250 testes (1 aviso, 0 erros)" in frase and "completo" in frase
    assert "as 5 fontes vão até set/2026" in frase
    assert palavras(frase) <= 60


def test_os_cartoes_com_a_ressalva_na_legenda_logo_acima_do_numero(at):
    assert [m.label for m in at.metric] == [
        "Última execução da DAG",
        "Testes do dbt",
        "Último mês com dado",
    ]
    assert [m.value for m in at.metric] == ["Sucesso", "249 de 250", "set/2026"]
    nos = elementos(at)
    ressalvas = [
        tx.CHAVES["maquina"],
        "Último dbt test completo nesta máquina (provavelmente manual, 10/10/2026 16:40 UTC)",
        "As 5 fontes do snapshot; CCEE e INMET (manuais) não entram",
    ]
    for metrica, ressalva in zip(at.metric, ressalvas, strict=True):
        i = next(n for n, (_, no) in enumerate(nos) if no is metrica)
        assert nos[i - 1][0] == "caption" and nos[i - 1][1].value == ressalva


def test_as_legendas_de_apoio_dos_cartoes(at):
    legendas = [c.value for c in at.caption]
    assert "10/10/2026 16:38 UTC · 1 min 54 s · agendada" in legendas
    assert "11 execuções registradas: 8 com sucesso, 3 com falha" in legendas
    assert "1 aviso · 0 erros" in legendas
    assert "mês encerrado há 10 dias na data do snapshot" in legendas
    assert "todas as fontes chegam a esse mês" in legendas


def test_o_cartao_do_dbt_diz_o_que_o_numero_e_e_a_hora_vem_do_snapshot():
    gerado = lei.manifesto()["saude"]["testes_dbt"]["run_results_gerado_em"]
    assert cal.hora_utc(gerado) == "10/10/2026 16:40 UTC"
    parcial = tx.cartoes(
        None,
        {"testes": 3, "pass": 3, "warn": 0, "error": 0, "gerado_em": gerado, "completo": False},
        {"mes": pd.Timestamp("2026-09-01"), "fontes_nesse_mes": 5, "fontes": 5},
        10,
    )
    assert parcial[1]["ressalva"].startswith("Último dbt test parcial nesta máquina")
    assert parcial[0]["valor"] == "Indisponível"


def test_o_mes_encerrado_e_contado_do_fim_do_mes():
    assert cal.dias_desde_o_fim_do_mes("2026-09-01", "2026-10-10T21:53:01Z") == 10
    assert cal.dias_desde_o_fim_do_mes("2024-02-01", "2024-03-01T00:00:00Z") == 1  # 29/02
    assert cal.dias_desde_o_fim_do_mes("2026-10-01", "2026-10-10T00:00:00Z") < 0
    fontes = {"mes": pd.Timestamp("2026-10-01"), "fontes_nesse_mes": 5, "fontes": 5}
    em_andamento = tx.cartoes(None, None, fontes, -21)[2]["linhas"][0]
    assert em_andamento == "mês ainda em andamento na data do snapshot"
    assert tx.cartoes(None, None, fontes, 1)[2]["linhas"][0].endswith(
        "há 1 dia na data do snapshot"
    )


def test_a_fonte_mais_atrasada_quando_as_fontes_divergem():
    frescor = pd.DataFrame({"ultimo_dado": ["2026-09-01", "2026-08-01", "2026-09-01"]})
    r = cal.ultimo_mes_das_fontes(frescor)
    assert r["mes"] == pd.Timestamp("2026-08-01") and r["fontes_nesse_mes"] == 1
    assert r["fontes"] == 3
    c = tx.cartoes(None, None, r, 40)[2]
    assert c["valor"] == "ago/2026" and c["linhas"][1] == "1 de 3 fontes chegam só a esse mês"


# ---------------------------------------------------------------- fontes manuais


def test_as_fontes_manuais_so_avisam_e_o_estado_da_checagem_vem_do_csv(at):
    nota = at.info[1].value
    assert (
        "A idade dos dados da CCEE e do INMET não está no snapshot; essas fontes são baixadas à "
        "mão e só avisam." in nota
    )
    runs = runs_do_csv()
    ultima = runs[-1]["run_id"]
    linha = next(
        r
        for r in linhas_csv("saude_execucoes.csv")
        if r["run_id"] == ultima and r["task_id"] == "freshness_manuais"
    )
    assert linha["estado_task"] == "success"
    assert f"estado: sucesso, {cal.numero(float(linha['duracao_task_s']), 1)} s" in nota
    assert "o estado não diz quão velhos são os dados" in nota


# ---------------------------------------------------------------- gráfico das execuções


def grafico_das_execucoes(at):
    return elementos(at)[indice(at, "vega_lite_chart", "duracao_dag_s")][1]


def conjuntos(no) -> list[pd.DataFrame]:
    import pyarrow as pa

    return [pa.ipc.open_stream(ds.data.data).read_all().to_pandas() for ds in no.proto.datasets]


def test_o_grafico_mostra_as_11_execucoes_e_a_ausente_em_ordem_do_tempo(at):
    g = grafico_das_execucoes(at)
    barras = next(
        d
        for d in conjuntos(g)
        if "duracao_dag_s" in d and d["duracao_dag_s"].notna().all() and len(d) > 3
    )
    assert len(barras) == 11
    assert '"zero": true' in spec(g)  # barras a partir de zero
    faltas = [d for d in conjuntos(g) if "marca_ausente" in d and (d["marca_ausente"] != "").all()]
    assert len(faltas) == 1 and list(faltas[0]["rotulo"]) == ["08/10 21:00 · agendada"]
    assert list(faltas[0]["marca_ausente"]) == [tx.CHAVES["sem_execucao"]]
    ordem = json.loads(g.proto.spec)["layer"][0]["encoding"]["x"]["sort"]
    assert len(ordem) == 12  # 11 execuções + o horário agendado sem execução
    assert ordem.index("08/10 21:00 · agendada") == ordem.index("08/10 03:57 · manual") + 1
    assert ordem[-1].endswith("agendada") and ordem[-1].startswith("10/10 16:38")


def test_as_falhas_aparecem_por_simbolo_e_texto_e_sem_cor_nova(at):
    g = grafico_das_execucoes(at)
    barras = next(d for d in conjuntos(g) if len(d) == 11)
    falhas = barras[barras["falhou"]]
    assert len(falhas) == 3
    assert set(falhas["marca"]) == {"✕ falha proposital"}
    assert not barras[~barras["falhou"]]["marca"].any()
    texto_das_falhas = next(d for d in conjuntos(g) if len(d) == 3)
    assert set(texto_das_falhas["marca"]) == {"✕ falha proposital"}
    cores = {c.lower() for c in re.findall(r'"#[0-9a-fA-F]{6}"', spec(g)) for c in [c.strip('"')]}
    assert cores <= {c.lower() for c in vis.PALETA}
    assert vis.AMBAR.lower() not in cores


def test_so_e_proposital_a_falha_que_tem_fonte():
    runs = cal.execucoes_por_run(lei.saude_execucoes()[0])
    marcadas = cal.marcar_falhas(runs, frozenset(tx.FALHAS_PROPOSITAIS))
    assert set(marcadas[marcadas["falhou"]]["marca"]) == {"✕ falha proposital"}
    sem_fonte = cal.marcar_falhas(runs, frozenset())
    assert set(sem_fonte[sem_fonte["falhou"]]["marca"]) == {"✕ falha"}
    uma = cal.marcar_falhas(runs, frozenset(list(tx.FALHAS_PROPOSITAIS)[:1]))
    assert sorted(uma[uma["falhou"]]["marca"]) == ["✕ falha", "✕ falha", "✕ falha proposital"]
    assert not marcadas[~marcadas["falhou"]]["marca"].any()


def test_cada_falha_proposital_tem_fonte_no_metricas_md_e_consta_do_snapshot():
    no_snapshot = {r["run_id"] for r in runs_do_csv() if r["estado_dag"] == "failed"}
    assert set(tx.FALHAS_PROPOSITAIS) == no_snapshot
    for run_id, fonte in tx.FALHAS_PROPOSITAIS.items():
        assert run_id in METRICAS, run_id
        assert "metricas.md" in fonte


def test_a_legenda_conta_as_falhas_e_mostra_a_execucao_ausente(at):
    legenda = next(c.value for c in at.caption if c.value.startswith("Uma barra por execução"))
    assert "(11, de 06/10 a 10/10); ✕ marca falha." in legenda
    assert "3 falhas foram propositais (testes do alerta)." in legenda
    assert "Em 08/10, 21:00 UTC, a execução agendada está ausente do registro" in legenda
    assert "combina com máquina desligada" in legenda


def test_a_execucao_agendada_ausente_vem_dos_dados():
    runs = cal.execucoes_por_run(lei.saude_execucoes()[0])
    assert cal.execucoes_agendadas_ausentes(runs) == [pd.Timestamp("2026-10-08 21:00", tz=UTC)]
    # sem buraco, sem execução agendada, e um buraco de dois dias
    de = lambda *dias: pd.DataFrame(  # noqa: E731
        {
            "run_id": [f"scheduled__2026-10-{d:02d}T21:00:00+00:00" for d in dias],
            "run_type": "scheduled",
        }
    )
    assert cal.execucoes_agendadas_ausentes(de(6, 7, 8)) == []
    assert cal.execucoes_agendadas_ausentes(de(6, 9)) == [
        pd.Timestamp("2026-10-07 21:00", tz=UTC),
        pd.Timestamp("2026-10-08 21:00", tz=UTC),
    ]
    assert cal.execucoes_agendadas_ausentes(de()) == []
    manuais = pd.DataFrame({"run_id": ["manual__x"], "run_type": ["manual"]})
    assert cal.execucoes_agendadas_ausentes(manuais) == []


def test_a_duracao_em_texto():
    assert cal.duracao_texto(114.4) == "1 min 54 s" and cal.duracao_texto(46.2) == "46 s"
    assert cal.duracao_texto(401.4) == "6 min 41 s" and cal.duracao_texto(59.6) == "1 min 0 s"


# ---------------------------------------------------------------- linha da Sprint 4


def test_a_linha_da_sprint_4_bate_com_o_metricas_md_e_com_o_snapshot(at):
    linha = next(c.value for c in at.caption if c.value.startswith("Ganhos da Sprint 4"))
    assert linha == tx.LINHA_SPRINT_4
    assert "DAG de 6 min 40 s → 1 min 54 s (−71%)" in linha
    assert "já incluindo a previsão mensal, que a DAG de antes não tinha" in linha
    assert "bytes faturados −69%" in linha
    for valor in ("6 min 40 s", "1 min 54 s", "−71%", "−69%", "3.031,4", "944,8"):
        assert valor in METRICAS, valor
    assert "3.031,4" in tx.FONTE_SPRINT_4 and "944,8" in tx.FONTE_SPRINT_4
    runs = cal.execucoes_por_run(lei.saude_execucoes()[0])
    antes = runs[runs["run_type"] == "scheduled"].iloc[0]  # a agendada de 06/10 (6 min 40 s)
    assert abs(antes["duracao_dag_s"] - 400) <= 2 and antes["inicio"].day == 6
    depois = runs[runs["run_id"].str.contains("20261008T035743")].iloc[0]  # 1 min 54 s
    assert cal.duracao_texto(depois["duracao_dag_s"]) == "1 min 54 s"


# ---------------------------------------------------------------- etapas e tabelas


def test_as_etapas_do_grafico_sao_as_demoradas_e_falha_aparece_como_cruz(at):
    exe = lei.saude_execucoes()[0]
    etapas = cal.tasks_relevantes(exe)
    assert set(etapas) == {
        "ons_ingestao",
        "dbt_run",
        "dbt_test",
        "freshness_ons",
        "freshness_manuais",
        "previsao_mensal",
    }
    assert etapas[0] == "dbt_run" and etapas[1] == "dbt_test"  # da mais demorada à menos
    e = expander(at, "Ver valores")
    g = next(no for t, no in achatar(e) if t == "vega_lite_chart")
    d = dados_do_grafico(g, "resultado")
    assert set(d["resultado"]) == {"sucesso", "falha ✕"}
    assert set(d[d["resultado"] == "falha ✕"]["task_id"]) == {tx.etapa("dbt_test")}
    assert (d["resultado"] == "falha ✕").sum() == 3
    assert "cross" in spec(g) and '"zero": true' in spec(g)
    assert d["duracao_task_s"].notna().all() and (d["duracao_task_s"] > 0).all()
    assert set(d["task_id"]) <= {tx.etapa(x) for x in etapas}


def test_etapas_puladas_ou_que_nao_rodaram_nunca_viram_zero():
    exe = lei.saude_execucoes()[0]
    d = cal.duracao_por_task(exe, list(exe["task_id"].unique()))
    pulados = exe[exe["estado_task"].isin(["skipped", "upstream_failed"])]
    chaves = set(zip(pulados["run_id"], pulados["task_id"], strict=True))
    assert not chaves & set(zip(d["run_id"], d["task_id"], strict=True))


def test_todo_nome_de_etapa_e_de_teste_do_snapshot_tem_traducao():
    for t in lei.saude_execucoes()[0]["task_id"].unique():
        assert t in tx.ETAPAS, t
    for t in lei.saude_testes()[0]["tipo"]:
        assert t in tx.TIPOS_DE_TESTE, t
    assert all(e in tx.ESTADOS for e in lei.saude_execucoes()[0]["estado_task"].unique())


def test_as_tabelas_ficam_em_expanders_fechados_e_batem_com_os_csvs(at):
    for rotulo in ("Ver valores", "Glossário", "Auditoria"):
        assert not expander(at, rotulo).proto.expanded
    fora = []
    for t, _ in elementos(at):
        if t == "expander":
            break
        fora.append(t)
    assert "dataframe" not in fora
    tabelas = [no.value for t, no in achatar(expander(at, "Ver valores")) if t == "dataframe"]
    assert len(tabelas) == 4
    execucoes, estados, testes, fontes = tabelas
    assert (
        len(execucoes) == 11
        and (execucoes["Observação"] == "falha proposital (teste do alerta)").sum() == 3
    )
    assert (execucoes["Estado"] == "falha").sum() == 3 and (
        execucoes["Estado"] == "sucesso"
    ).sum() == 8
    assert estados.set_index("Estado da etapa")["Etapas (todas as execuções)"].to_dict() == {
        "sucesso": 106,
        "pulada": 46,
        "não rodou (etapa anterior falhou)": 5,
        "falha": 3,
    }
    assert len(testes) == 8 and testes["Testes"].sum() == 250 and testes["Passaram"].sum() == 249
    assert testes["Avisos"].sum() == 1 and testes["Erros"].sum() == 0
    assert len(fontes) == 5 and set(fontes["Último dado"]) == {"set/2026"}
    assert set(fontes["Dias desde o primeiro dia do mês"]) == {39}


# ---------------------------------------------------------------- limites


def test_os_limites_sao_curtos_e_sempre_visiveis(at):
    i = indice(at, "subheader", tx.TITULO_LIMITES)
    corpo = elementos(at)[i + 1][1].value
    assert elementos(at)[i + 1][0] == "markdown"
    assert len(re.findall(r"^\d\. ", corpo, flags=re.M)) == 3
    assert "É o estado de 10/10/2026**, não ao vivo" in corpo
    assert "Só 11 execuções, de 06/10 a 10/10" in corpo
    assert "Do dbt só há o último comando desta máquina" in corpo
    assert palavras(corpo) <= 80


# ---------------------------------------------------------------- auditoria


def test_a_auditoria_declara_a_inferencia_e_cita_o_log_e_as_fontes(at):
    md = next(no.value for t, no in achatar(expander(at, "Auditoria")) if t == "markdown")
    assert "Inferência, não fato registrado" in md and "provavelmente não é o da DAG" in md
    assert "data/logs/dbt_test_completo_6c2.log" in md and "fora do repositório" in md
    assert "quem disparou o comando não está registrado" in md
    assert (
        "16:40:53Z" in md and "16:40:06Z" in md
    )  # gerado; fim da última execução (16:38:12 + 114,4 s)
    assert "80,2 s" in md and "35,7 s" in md and "250 testes: 249/1/0" in md
    for run_id, fonte in tx.FALHAS_PROPOSITAIS.items():
        assert run_id in md and fonte in md
    assert 'schedule="0 21 * * *"' in md and "catchup=False" in md
    assert "docs/metricas.md" in md and "6 min 41 s" in md


def test_o_agendamento_citado_consta_da_dag():
    dag = (RAIZ / "airflow" / "dags" / "energia_livre_diaria.py").read_text()
    assert 'schedule="0 21 * * *"' in dag and "catchup=False" in dag


@pytest.mark.skipif(
    not (RAIZ / "data" / "logs" / "dbt_test_completo_6c2.log").exists(),
    reason="o log local não está no repositório (data/logs/ não é versionado)",
)
def test_o_log_local_coincide_em_horario_e_contagem_com_o_run_results():
    log = (RAIZ / "data" / "logs" / "dbt_test_completo_6c2.log").read_text()
    gerado = lei.manifesto()["saude"]["testes_dbt"]["run_results_gerado_em"]
    hora = pd.Timestamp(gerado).strftime("%H:%M:%S")
    ultima = [linha for linha in log.splitlines() if "Done." in linha][-1]
    assert hora in ultima  # o log termina no mesmo segundo em que o run_results foi gerado
    assert "PASS=249 WARN=1 ERROR=0" in ultima and "TOTAL=250" in ultima


# ---------------------------------------------------------------- regras do redesenho


def test_orcamento_de_palavras_e_de_caixas(at):
    visiveis = palavras_visiveis(at.main)
    assert visiveis <= ORCAMENTO_DE_PALAVRAS, visiveis
    assert len(at.warning) == 0  # âmbar só para prévia e especulação
    assert len(at.info) == 2 and len(at.subheader) == 2
    assert not {t for t, _ in elementos(at)} & {"error", "success", "exception"}


def test_o_ambar_nao_aparece_nos_graficos(at):
    for t, no in elementos(at):
        if t == "vega_lite_chart":
            assert vis.AMBAR.lower() not in spec(no).lower()


def test_so_cores_da_paleta_nos_graficos(at):
    paleta = {c.lower() for c in vis.PALETA}
    for t, no in elementos(at):
        if t == "vega_lite_chart":
            cores = {c.lower() for c in re.findall(r"#[0-9a-fA-F]{6}", spec(no))}
            assert cores <= paleta, cores


SEM_ESCAPE = re.compile(r"(?<!\\)\$")


def test_nenhum_dolar_sem_escape(at):
    for t, no in elementos(at):
        if t in ("markdown", "caption", "info", "warning", "subheader", "title"):
            assert not SEM_ESCAPE.search(no.value), no.value[:100]
        elif t == "metric":
            assert not SEM_ESCAPE.search(no.label + (no.proto.help or ""))


JARGAO = (
    "ons_ingestao",
    "dbt_run",
    "dbt_test",
    "freshness_",
    "previsao_mensal",
    "pipeline_ok",
    "selecao_dbt",
    "ccee_ha_",
    "run_id",
    "task_id",
    "scheduled__",
    "manual__",
    "accepted_",
    "not_null",
    "unique_combination",
    "equal_rowcount",
    "run_results",
    "LocalExecutor",
    "Postgres",
    "sha256",
    ".csv",
    "docs/",
    "manifest",
    "upstream_failed",
    "skipped",
    "catchup",
)


def test_nenhum_jargao_fora_da_auditoria_e_do_glossario(at):
    visivel = []
    for t, no in elementos(at):
        if t == "expander" and no.label.startswith("Glossário"):
            break
        visivel.append(textos_do_grafico(no) if t == "vega_lite_chart" else texto(no))
    tela = "\n".join(visivel)
    achados = [j for j in JARGAO if j in tela]
    assert not achados, achados


def test_as_siglas_tem_ajuda_no_ponto_de_uso_e_no_glossario(at):
    assert "sequência de etapas" in at.metric[0].proto.help
    assert "ferramenta" in at.metric[1].proto.help and "alerta" in at.metric[1].proto.help
    assert "baixado à mão" in at.metric[2].proto.help
    glossario_md = expander(at, "Glossário").markdown[0].value
    for sigla in ("DAG", "dbt", "Aviso", "Fonte manual"):
        assert f"**{sigla}:**" in glossario_md
    assert all(k in glossario.TERMOS for k in tx.GLOSSARIO)


def test_nenhum_numero_aparece_antes_da_ressalva_dele(at):
    nos = elementos(at)
    primeiro_numero = min(
        i for i, (t, _) in enumerate(nos) if t in ("metric", "vega_lite_chart", "dataframe")
    )
    assert indice(at, "info", "No snapshot de") < primeiro_numero  # a frase vem antes de tudo
    for metrica in at.metric:  # e cada cartão tem a ressalva imediatamente acima
        i = next(n for n, (_, no) in enumerate(nos) if no is metrica)
        assert nos[i - 1][0] == "caption" and len(nos[i - 1][1].value) > 20


def test_as_ressalvas_do_bloco_vem_antes_do_grafico(at):
    assert indice(at, "caption", tx.CHAVES["maquina"]) < indice(at, "vega_lite_chart", "rotulo")
    assert indice(at, "info", "essas fontes são baixadas à mão") < indice(
        at, "vega_lite_chart", "rotulo"
    )
    legenda = indice(at, "caption", "Uma barra por execução")
    assert legenda + 1 == indice(at, "vega_lite_chart", "rotulo")  # a legenda é logo acima


# ---------------------------------------------------------------- estados indisponíveis


def test_sem_o_banco_de_metadados_e_sem_run_results_a_pagina_diz_isso_e_nao_quebra(tmp_path):
    pasta = tmp_path / "dados"
    shutil.copytree(DADOS, pasta)
    man = json.loads((pasta / "manifest.json").read_text())
    man["saude"] = {
        "execucoes_da_dag": {"estado": "indisponivel", "motivo": "Docker desligado"},
        "testes_dbt": {"estado": "indisponivel", "motivo": "sem run_results"},
    }
    (pasta / "manifest.json").write_text(json.dumps(man))
    (pasta / "saude_execucoes.csv").write_text(",".join(lei.saude_execucoes()[0].columns) + "\n")
    (pasta / "saude_testes_dbt.csv").write_text("tipo,testes,pass,warn,error,registros\n")
    at = rodar(pasta)
    assert not at.exception
    assert [m.value for m in at.metric][:2] == ["Indisponível", "Indisponível"]
    frase = at.info[0].value
    assert "não há registro das execuções da DAG" in frase
    assert "não há resultado do dbt test nesta máquina" in frase
    assert len(at.get("vega_lite_chart")) == 0


# ---------------------------------------------------------------- navegação


def test_o_app_com_navegacao_tem_as_tres_paginas_e_carrega():
    fonte = (RAIZ / "dashboard" / "app.py").read_text()
    for pagina_ in ("decisao.renderizar", "previsao.renderizar", "saude.renderizar"):
        assert pagina_ in fonte
    assert 'title="Saúde do pipeline", url_path="saude"' in fonte
    app = AppTest.from_file(str(RAIZ / "dashboard" / "app.py"), default_timeout=90)
    app.run()
    assert not app.exception and app.title[0].value == "Decisão de contrato"
