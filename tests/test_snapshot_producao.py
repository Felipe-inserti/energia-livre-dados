from scripts import snapshot_producao as sp

ANTES = {
    "marts.fct_carga_horaria": {"2026-09|SE": [720, 720, 5.0e7], "2026-10|SE": [120, 120, 8.0e6]},
    "marts.fct_submercado_horario": {"2026-09|SE": [720, 720, 5.0e7, 700, 9.9e4, 700, 1.5e4]},
}


def copia(mudancas=None):
    novo = {t: {k: list(v) for k, v in g.items()} for t, g in ANTES.items()}
    for (tabela, chave), valor in (mudancas or {}).items():
        novo[tabela][chave] = valor
    return novo


def test_snapshots_identicos_nao_tem_diferenca():
    dif, totais = sp.comparar_snapshots(ANTES, copia())
    assert dif == [] and totais == {t: len(g) for t, g in ANTES.items()}


def test_soma_diferente_alem_da_tolerancia_e_listada_so_no_grupo_que_mudou():
    depois = copia({("marts.fct_carga_horaria", "2026-10|SE"): [120, 120, 8.0e6 + 1]})
    dif, _ = sp.comparar_snapshots(ANTES, depois)
    assert len(dif) == 1 and "2026-10|SE" in dif[0] and "fct_carga_horaria" in dif[0]


def test_ruido_de_ultima_casa_nao_conta():
    depois = copia({("marts.fct_carga_horaria", "2026-10|SE"): [120, 120, 8.0e6 + 0.005]})
    assert sp.comparar_snapshots(ANTES, depois)[0] == []


def test_grupo_ausente_ou_a_mais_ou_contagem_diferente_reprova():
    sem = copia()
    del sem["marts.fct_carga_horaria"]["2026-10|SE"]
    assert len(sp.comparar_snapshots(ANTES, sem)[0]) == 1
    a_mais = copia({("marts.fct_carga_horaria", "2026-11|SE"): [3, 3, 1.0]})
    assert len(sp.comparar_snapshots(ANTES, a_mais)[0]) == 1
    n = copia({("marts.fct_carga_horaria", "2026-09|SE"): [719, 719, 5.0e7]})
    assert len(sp.comparar_snapshots(ANTES, n)[0]) == 1


def test_sql_so_le_e_agrupa_por_mes_e_submercado():
    sql = sp.sql_snapshot("p.marts.t", "codigo_submercado", ["carga_mwmed", "pld_rs_mwh"])
    assert sql.startswith("select") and "group by 1, 2" in sql and "`p.marts.t`" in sql
    assert "sum(carga_mwmed)" in sql and "sum(pld_rs_mwh)" in sql


def test_o_raw_e_as_tres_tabelas_do_ons_estao_no_snapshot_cada_uma_no_seu_mes():
    assert set(sp.TABELAS) == {
        "raw.ons_curva_carga",
        "staging.stg_ons__curva_carga",
        "marts.fct_carga_horaria",
        "marts.fct_submercado_horario",
    }
    assert sp.TABELAS["raw.ons_curva_carga"][2] == sp.MES_LOCAL_RAW  # a partição do raw
    assert all(v[2] == sp.MES_UTC for k, v in sp.TABELAS.items() if not k.startswith("raw."))
    sql = sp.sql_snapshot("p.raw.t", "id_subsistema", ["x"], sp.MES_LOCAL_RAW)
    assert "format_date('%Y-%m', _mes_referencia) mes" in sql


# ---- regras do checkpoint 6-7: meses recentes só informam; perder linhas reprova ------------
REGRAS_ANTES = {
    "raw.ons_curva_carga": {
        "2025-12|SE": [100, 100, 5.0],
        "2026-09|SE": [100, 100, 5.0],
        "2026-10|SE": [20, 20, 1.0],
    }
}


def depois(**mudancas):
    novo = {t: {k: list(v) for k, v in g.items()} for t, g in REGRAS_ANTES.items()}
    for chave, valor in mudancas.items():
        if valor is None:
            del novo["raw.ons_curva_carga"][chave.replace("_", "|", 1).replace("_", "-")]
        else:
            novo["raw.ons_curva_carga"][chave.replace("_", "|", 1).replace("_", "-")] = valor
    return novo


def test_mes_antigo_com_qualquer_mudanca_reprova_mesmo_com_o_corte_dos_recentes():
    b = depois(**{"2025-12_SE": [100, 100, 5.5]})
    est, inf, _ = sp.comparar_com_regras(REGRAS_ANTES, b, "2026-08")
    assert len(est) == 1 and inf == []


def test_mes_recente_com_valor_revisado_ou_linhas_novas_so_informa():
    b = depois(**{"2026-09_SE": [100, 100, 5.4], "2026-10_SE": [48, 48, 2.4]})
    est, inf, _ = sp.comparar_com_regras(REGRAS_ANTES, b, "2026-08")
    assert est == [] and len(inf) == 2


def test_mes_recente_que_perde_linhas_ou_some_reprova():
    menos = depois(**{"2026-10_SE": [19, 19, 0.9]})
    assert len(sp.comparar_com_regras(REGRAS_ANTES, menos, "2026-08")[0]) == 1
    sumiu = depois(**{"2026-09_SE": None})
    assert len(sp.comparar_com_regras(REGRAS_ANTES, sumiu, "2026-08")[0]) == 1


def test_sem_corte_tudo_e_estrito_e_so_comuns_ignora_tabela_so_de_um_lado():
    b = depois(**{"2026-10_SE": [48, 48, 2.4]})
    assert len(sp.comparar_com_regras(REGRAS_ANTES, b)[0]) == 1
    so_um_lado = {**REGRAS_ANTES, "marts.fct_carga_horaria": {"2026-10|SE": [1, 1, 1.0]}}
    assert len(sp.comparar_com_regras(REGRAS_ANTES, so_um_lado)[0]) == 1
    assert sp.comparar_com_regras(REGRAS_ANTES, so_um_lado, so_comuns=True)[0] == []
