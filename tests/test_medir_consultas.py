from decimal import Decimal

import pytest

from scripts import medir_consultas as mc


def medida(processado, faturado=10 * 1024 * 1024, pares=None):
    return mc.Medida(processado, processado, faturado, pares or [(0, 1.0)])


def test_como_pares_aceita_row_dict_tupla_e_numeric():
    linhas = [{"hora": 0, "v": Decimal("61.07")}, (1, 62.5)]
    assert mc.como_pares(linhas) == [(0, 61.07), (1, 62.5)]


def test_resultados_iguais_com_tolerancia():
    a = [(0, 100.0), (1, 200.0)]
    assert mc.resultados_iguais(a, [(0, 100.0000001), (1, 200.0)])
    assert not mc.resultados_iguais(a, [(0, 100.5), (1, 200.0)])


def test_resultados_com_horas_diferentes_nao_sao_iguais():
    assert not mc.resultados_iguais([(0, 1.0)], [(1, 1.0)])
    assert not mc.resultados_iguais([(0, 1.0), (1, 2.0)], [(0, 1.0)])


def test_variacao_percentual():
    assert mc.variacao_percentual(200, 100) == -50.0
    assert mc.variacao_percentual(0, 5) == 0.0


def test_tres_fontes_com_consultas_nos_tres_pontos():
    assert set(mc.PARES) == {"ons", "ccee", "inmet"}
    for par in mc.PARES.values():
        for sql in (par.sql_raw, par.sql_staging, par.sql_fato):
            assert "{tabela}" in sql
            sql.format(tabela="p.d.t")
        assert par.tabela_staging.startswith("stg_") and par.tabela_fato.startswith("fct_")
        assert par.colunas_cluster


def test_consultas_do_staging_respondem_a_mesma_pergunta_do_raw():
    ons_, ccee_, inmet_ = (mc.PARES[k] for k in ("ons", "ccee", "inmet"))
    # ONS e CCEE: hora e ano LOCAIS (horário de Brasília), como no raw
    for par in (ons_, ccee_):
        assert "AT TIME ZONE 'America/Sao_Paulo'" in par.sql_staging
        assert "TIMESTAMP('2024-01-01', 'America/Sao_Paulo')" in par.sql_staging
    assert "id_subsistema = 'SE'" in ons_.sql_staging and "'SE'" in ons_.sql_raw
    assert "'SUDESTE'" in ccee_.sql_staging and "'SUDESTE'" in ccee_.sql_raw
    # INMET: UTC nas três tabelas
    assert "uf = 'SP'" in inmet_.sql_staging and "'SP'" in inmet_.sql_raw
    assert "America/Sao_Paulo" not in inmet_.sql_staging


def test_consultas_do_fato_usam_o_codigo_do_submercado_e_o_filtro_que_poda_a_particao():
    ons_, ccee_, inmet_ = (mc.PARES[k] for k in ("ons", "ccee", "inmet"))
    assert "codigo_submercado = 'SE'" in ons_.sql_fato and "id_subsistema" not in ons_.sql_fato
    assert "codigo_submercado = 'SE'" in ccee_.sql_fato  # SUDESTE da CCEE = SE do ONS
    for par in mc.PARES.values():
        # filtro de intervalo direto em instante_utc, a coluna de partição do fato
        assert "instante_utc >= TIMESTAMP" in par.sql_fato and "instante_utc <" in par.sql_fato


def test_nenhuma_consulta_tipada_precisa_de_cast():
    for par in mc.PARES.values():
        assert "SAFE_CAST" not in par.sql_staging and "SAFE_CAST" not in par.sql_fato
        assert "SAFE_CAST" in par.sql_raw


def test_main_sem_tabela_devolve_2(monkeypatch, capsys):
    from google.api_core.exceptions import NotFound

    def falha(*args, **kwargs):
        raise NotFound("Not found: Table x")

    monkeypatch.setattr(mc, "carregar_config", lambda: mc.Config("p", "b", "l"))
    monkeypatch.setattr(mc.gcp, "cliente_bigquery", lambda c: object())
    monkeypatch.setattr(mc, "medir_par", falha)
    assert mc.main(["--fonte", "ons"]) == 2
    assert "Rode o dbt run" in capsys.readouterr().out


def test_imprimir_par_mostra_os_tres_pontos_e_os_efeitos(capsys):
    raw = medida(37_316_108, 37_748_736)
    staging = medida(18_285_126, 18_874_368)
    fato = medida(743_184)
    assert mc.imprimir_par(mc.PARES["ons"], raw, staging, fato) is True
    saida = capsys.readouterr().out
    assert (
        "raw (STRING)" in saida and "staging (tipado)" in saida and "fato (particionada)" in saida
    )
    assert "tipagem -51.0%" in saida and "partição e cluster -95.9%" in saida
    assert "total -98.0%" in saida and "resultados iguais nos três pontos: sim" in saida
    assert "piso de 10 MiB" in saida and "bytes processados" in saida


def test_imprimir_par_detecta_resultado_diferente(capsys):
    raw = medida(100, pares=[(0, 1.0)])
    staging = medida(50, pares=[(0, 1.0)])
    fato = medida(10, pares=[(0, 9.0)])
    assert mc.imprimir_par(mc.PARES["ons"], raw, staging, fato) is False
    assert "resultados iguais nos três pontos: NÃO" in capsys.readouterr().out


def test_sql_das_variantes_do_isolamento():
    origem, destino = "p.marts.fct", "p.staging.tmp"
    nada = mc.sql_variante("sem_nada", origem, destino, ("uf", "estacao_codigo"))
    particao = mc.sql_variante("so_particao", origem, destino, ("uf",))
    cluster = mc.sql_variante("so_cluster", origem, destino, ("uf", "estacao_codigo"))
    assert "PARTITION BY" not in nada and "CLUSTER BY" not in nada
    assert (
        "PARTITION BY TIMESTAMP_TRUNC(instante_utc, MONTH)" in particao
        and "CLUSTER BY" not in particao
    )
    assert "CLUSTER BY uf, estacao_codigo" in cluster and "PARTITION BY" not in cluster
    for sql in (nada, particao, cluster):
        assert (
            sql.startswith("CREATE OR REPLACE TABLE `p.staging.tmp`")
            and "FROM `p.marts.fct`" in sql
        )


def test_copias_temporarias_ficam_no_staging_e_sao_apagadas_mesmo_com_erro(monkeypatch):
    apagadas = []

    class Cliente:
        def delete_table(self, tabela, not_found_ok):
            apagadas.append(tabela)

    chamadas = []

    def executar(bq, sql, **kwargs):
        chamadas.append(sql)
        if len(chamadas) == 2:  # a 2ª cópia falha
            raise RuntimeError("falhou")

    monkeypatch.setattr(mc.gcp, "executar_consulta", executar)
    monkeypatch.setattr(mc, "medir", lambda bq, sql: medida(1))
    with pytest.raises(RuntimeError):
        mc.isolar_cluster(Cliente(), mc.Config("p", "b", "l"), mc.PARES["ons"], medida(1))
    # as duas cópias que chegaram a ser pedidas são apagadas
    assert apagadas == [
        "p.staging.tmp_exp_fct_carga_horaria_sem_nada",
        "p.staging.tmp_exp_fct_carga_horaria_so_particao",
    ]


def test_isolamento_devolve_as_quatro_medidas(monkeypatch):
    class Cliente:
        def delete_table(self, tabela, not_found_ok):
            pass

    monkeypatch.setattr(mc.gcp, "executar_consulta", lambda bq, sql, **kw: None)
    monkeypatch.setattr(mc, "medir", lambda bq, sql: medida(18_000_000))
    fato = medida(743_184)
    medidas = mc.isolar_cluster(Cliente(), mc.Config("p", "b", "l"), mc.PARES["ons"], fato)
    assert set(medidas) == {"sem_nada", "so_particao", "so_cluster", "particao_e_cluster"}
    assert medidas["particao_e_cluster"] is fato


def test_imprimir_isolamento(capsys):
    medidas = {
        "sem_nada": medida(18_285_126),
        "so_particao": medida(743_184),
        "so_cluster": medida(18_000_000),
        "particao_e_cluster": medida(743_184),
    }
    assert mc.imprimir_isolamento(mc.PARES["ons"], medidas) is True
    saida = capsys.readouterr().out
    assert "só partição -95.9%" in saida and "só cluster -1.6%" in saida
    assert "efeito do cluster por cima da partição: +0.0%" in saida
    assert "resultados iguais nas quatro tabelas: sim" in saida
