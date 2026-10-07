from scripts import resumir_execucao_dag as r

BYTES = """intervalo (UTC): 2026-10-07T21:00:00 a 2026-10-07T21:03:00
dbt                        64 jobs (0 com erro) | processados   250.1 MB | faturados   520.4 MB
outros (ingestão, freshness)  2 jobs (0 com erro) | processados  11.0 MB | faturados  21.0 MB
total                            processados 261.1 MB | faturados 541.4 MB
(a própria consulta leu 0.0 MB de metadados)
"""
TAREFAS = """parametros_execucao|success|1|1.2
ons_ingestao|success|1|40.5
ccee_ha_arquivo_novo|success|1|0.4
ccee_ingestao|skipped|1|0.0
selecao_dbt|success|1|1.1
freshness_ons|success|1|11.0
dbt_run|success|1|35.0
dbt_test|success|1|60.0
freshness_manuais|success|1|8.0
pipeline_ok|success|1|0.1
"""


def test_ler_bytes_separa_dbt_outros_e_total():
    b = r.ler_bytes(BYTES)
    assert b["dbt"] == {"jobs": 64.0, "proc": 250.1, "fat": 520.4}
    assert b["outros"]["jobs"] == 2.0 and b["outros"]["fat"] == 21.0
    assert b["total"] == {"jobs": 0.0, "proc": 261.1, "fat": 541.4}


def test_ler_bytes_sem_linha_dbt_devolve_so_o_que_existe():
    assert "dbt" not in r.ler_bytes(
        "total                  processados 1.0 MB | faturados 2.0 MB\\n"
    )


def test_ler_tarefas_ignora_linhas_estranhas():
    t = r.ler_tarefas(TAREFAS + "\\nlixo sem separador\\n")
    assert len(t) == 10 and t[1].id == "ons_ingestao" and t[1].segundos == 40.5
    assert t[3].estado == "skipped"


def test_comparacao_com_o_antes_mostra_a_variacao_de_cada_medida():
    linhas = r.tabela_de_comparacao(180.0, r.ler_tarefas(TAREFAS), r.ler_bytes(BYTES))
    texto = "\\n".join(linhas)
    assert "6 min 40 s" in texto and "3 min 00 s" in texto  # DAG: antes e depois
    assert "4 min 22 s" in texto and "0 min 40 s" in texto or "0 min 41 s" in texto  # ons_ingestao
    assert "194" in texto and "1557.9" in texto and "2965.4" in texto
    assert "-55%" in texto  # a DAG de 400 s para 180 s
    assert "-82%" in texto  # dbt faturado: 2965,4 -> 520,4


def test_sucesso_sem_problemas_e_com_task_falha_vira_problema():
    assert r.avaliar("success", r.ler_tarefas(TAREFAS), "sucesso") == []
    quebrada = TAREFAS.replace("dbt_run|success", "dbt_run|failed")
    p = r.avaliar("failed", r.ler_tarefas(quebrada), "sucesso")
    assert any("dbt_run" in x for x in p) and any("terminou em 'failed'" in x for x in p)


FALHA = TAREFAS.replace("dbt_test|success|1|60.0", "dbt_test|failed|1|55.0").replace(
    "pipeline_ok|success", "pipeline_ok|upstream_failed"
)


def test_falha_proposital_esperada_exige_dbt_test_falho_sem_retentativa_e_pipeline_barrado():
    assert r.avaliar("failed", r.ler_tarefas(FALHA), "falha") == []
    repetido = FALHA.replace("dbt_test|failed|1|", "dbt_test|failed|2|")
    assert any("repetido" in x for x in r.avaliar("failed", r.ler_tarefas(repetido), "falha"))
    assert r.avaliar(
        "success", r.ler_tarefas(TAREFAS), "falha"
    )  # rodou limpo: o alerta não foi provado


def test_main_imprime_e_devolve_o_codigo(tmp_path, capsys):
    (tmp_path / "t.txt").write_text(TAREFAS)
    (tmp_path / "b.log").write_text(BYTES)
    args = ["--rotulo", "normal", "--dag", "success|2026-10-07T21:00:03|2026-10-07T21:03:03|180.0"]
    args += ["--tarefas", str(tmp_path / "t.txt"), "--bytes", str(tmp_path / "b.log")]
    assert r.main(args) == 0
    saida = capsys.readouterr().out
    assert "execução 'normal': success" in saida and saida.rstrip().endswith("OK")
