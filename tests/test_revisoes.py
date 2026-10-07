import json

from ingestion import revisoes

CABECALHO = "id_subsistema;nom_subsistema;din_instante;val_cargaenergiahomwmed\n"


def csv(*linhas: str) -> bytes:
    return (CABECALHO + "\n".join(linhas) + "\n").encode()


BASE = csv(
    "SE;SUDESTE;2026-01-01 00:00:00;100.0",
    "SE;SUDESTE;2026-01-01 01:00:00;200.0",
    "S;SUL;2026-02-01 00:00:00;50.0",
    "N;NORTE;2026-02-01 00:00:00;",
)


def test_arquivos_iguais_sao_identicos_e_nao_leem_o_csv():
    r = revisoes.comparar_csv_ons(BASE, BASE, 2026)
    assert r["identico"] is True and "linhas_alteradas" not in r


def test_conta_cada_tipo_de_mudanca_e_mede_a_magnitude():
    depois = csv(
        "SE;SUDESTE;2026-01-01 00:00:00;110.0",  # valor -> valor (+10, 10%)
        "SE;SUDESTE;2026-01-01 01:00:00;200.0",  # igual
        "S;SUL;2026-02-01 00:00:00;",  # valor -> nulo
        "N;NORTE;2026-02-01 00:00:00;7.5",  # nulo -> valor
        "NE;NORDESTE;2026-02-01 00:00:00;9.0",  # linha nova
    )
    r = revisoes.comparar_csv_ons(BASE, depois, 2026)
    assert r["identico"] is False
    assert (r["valor_alterado"], r["valor_para_nulo"], r["nulo_para_valor"]) == (1, 1, 1)
    assert (r["adicionadas"], r["removidas"], r["linhas_alteradas"]) == (1, 0, 3)
    assert r["dif_abs_max_mwmed"] == 10.0 and abs(r["dif_pct_max"] - 0.1) < 1e-12
    assert r["por_mes"] == {"2026-01": 1, "2026-02": 2}
    assert r["por_subsistema"] == {"N": 1, "S": 1, "SE": 1}


def test_linha_removida_e_formato_numerico_diferente_nao_conta_como_alteracao():
    depois = csv(
        "SE;SUDESTE;2026-01-01 00:00:00;100",  # 100 == 100.0
        "SE;SUDESTE;2026-01-01 01:00:00;200.0",
        "S;SUL;2026-02-01 00:00:00;50.0",
    )
    r = revisoes.comparar_csv_ons(BASE, depois, 2026)
    assert r["linhas_alteradas"] == 0 and r["removidas"] == 1


def test_mudanca_so_no_nome_do_subsistema_e_contada():
    depois = BASE.replace(b"SUDESTE;", b"SUDESTE/CENTRO-OESTE;")
    r = revisoes.comparar_csv_ons(BASE, depois, 2026)
    assert r["nome_alterado"] == 2 and r["valor_alterado"] == 0


def test_registrar_acrescenta_uma_linha_de_json_por_medicao(tmp_path):
    arquivo = tmp_path / "logs" / "revisoes.jsonl"
    revisoes.registrar({"ano": 2026, "identico": True}, "comparacao", arquivo)
    revisoes.registrar({"ano": 2025, "identico": True}, "ingestao", arquivo)
    linhas = [json.loads(x) for x in arquivo.read_text().splitlines()]
    assert [x["ano"] for x in linhas] == [2026, 2025]
    assert linhas[0]["origem"] == "comparacao" and "medido_em" in linhas[0]


def test_resumir_nao_quebra_nos_dois_casos():
    assert "idêntico" in revisoes.resumir(revisoes.comparar_csv_ons(BASE, BASE, 2026))
    depois = BASE.replace(b"100.0", b"101.0")
    assert "1 linhas alteradas" in revisoes.resumir(revisoes.comparar_csv_ons(BASE, depois, 2026))


def test_ruido_de_ponto_flutuante_abaixo_da_tolerancia_nao_conta_como_revisao():
    """Medido em 06/10/2026: 5 valores de agosto 'mudaram' em 7e-12 MWmed. Isso não é revisão."""
    depois = BASE.replace(b"100.0", b"100.000000000007").replace(b"200.0", b"200.0000000000036")
    r = revisoes.comparar_csv_ons(BASE, depois, 2026)
    assert r["identico"] is False  # os bytes são diferentes...
    assert r["valor_alterado"] == 0 and r["linhas_alteradas"] == 0  # ...mas nada foi revisado
    assert r["valor_ruido_float"] == 2 and r["por_mes"] == {} and r["meses_afetados"] == []
    assert r["tolerancia_abs_mwmed"] == revisoes.TOLERANCIA_ABS_MWMED == 1e-6


def test_diferenca_logo_acima_da_tolerancia_ja_e_revisao():
    depois = BASE.replace(b"100.0", b"100.000002")  # 2e-6 MWmed
    r = revisoes.comparar_csv_ons(BASE, depois, 2026)
    assert r["valor_alterado"] == 1 and r["valor_ruido_float"] == 0
    assert r["meses_afetados"] == ["2026-01"]


def test_meses_afetados_inclui_linhas_adicionadas_e_removidas_alem_das_alteradas():
    depois = csv(
        "SE;SUDESTE;2026-01-01 00:00:00;100.0",
        "SE;SUDESTE;2026-01-01 01:00:00;200.0",
        # a linha de 2026-02 do S some; do N também é igual; entra uma linha nova em 2026-03
        "N;NORTE;2026-02-01 00:00:00;",
        "SE;SUDESTE;2026-03-01 00:00:00;5.0",
    )
    r = revisoes.comparar_csv_ons(BASE, depois, 2026)
    assert r["linhas_alteradas"] == 0 and (r["adicionadas"], r["removidas"]) == (1, 1)
    assert r["meses_afetados"] == ["2026-02", "2026-03"]
