import pytest

from ingestion.common import raw
from ingestion.common.config import Config
from ingestion.common.gcp import ResultadoConsulta

CONFIG = Config("p", "b", "us-central1")


def test_medicoes_registra_arquivo_e_esperado():
    m = raw.Medicoes()
    m.registrar_arquivo("a.csv", 1000, 10)
    m.registrar_arquivo("b.csv", 500, 5)
    m.registrar_esperado("t", ("bronze/a.csv",), 10, 2)
    assert (m.arquivos, m.bytes_origem, m.linhas_csv) == (2, 1500, 15)
    assert m.por_arquivo == [("a.csv", 1000, 10), ("b.csv", 500, 5)]
    assert m.esperado == {"t": {("bronze/a.csv",): (10, 2)}}


def test_t_total_soma_as_tres_etapas():
    m = raw.Medicoes(t_origem=1.0, t_gcs=2.0, t_bigquery=3.5)
    assert m.t_total == 6.5


def test_carregador_so_o_primeiro_job_trunca(monkeypatch):
    chamadas = []

    def fake(cliente, tabela, conteudo, esquema, *, truncar):
        chamadas.append(truncar)
        return 3

    monkeypatch.setattr(raw.gcp, "carregar_csv_no_bigquery", fake)
    m = raw.Medicoes()
    c = raw.Carregador(object(), "p.raw.t", [], m)
    assert c.carregar(b"x", 3, "a") == 3
    assert c.carregar(b"x", 3, "b") == 3
    assert chamadas == [True, False]
    assert m.linhas_carregadas == 6 and m.t_bigquery >= 0


def test_carregador_recusa_contagem_diferente(monkeypatch):
    monkeypatch.setattr(raw.gcp, "carregar_csv_no_bigquery", lambda *a, **k: 2)
    c = raw.Carregador(object(), "p.raw.t", [], raw.Medicoes())
    with pytest.raises(RuntimeError, match="3 linhas e o job carregou 2"):
        c.carregar(b"x", 3, "2024")


def linha(chave, linhas, nulos=0, vazias=0, **extra):
    return {
        "_arquivo_origem": chave,
        "linhas": linhas,
        "nulos": nulos,
        "strings_vazias": vazias,
        **extra,
    }


def validar(monkeypatch, linhas_do_raw, medicoes, conjunto):
    sqls = []

    def fake(cliente, sql, **kwargs):
        sqls.append(sql)
        return ResultadoConsulta(linhas_do_raw, 1, 1, False)

    monkeypatch.setattr(raw.gcp, "cliente_bigquery", lambda config: object())
    monkeypatch.setattr(raw.gcp, "executar_consulta", fake)
    return raw.validar_raw(CONFIG, medicoes, [conjunto]), sqls


def test_validar_raw_sem_problemas(monkeypatch):
    m = raw.Medicoes()
    m.registrar_esperado("t", ("a",), 10, 2)
    problemas, sqls = validar(
        monkeypatch, [linha("a", 10, nulos=2)], m, raw.ConjuntoValidacao("t", "valor")
    )
    assert problemas == []
    assert "`p.raw.t`" in sqls[0] and "GROUP BY _arquivo_origem" in sqls[0]


def test_validar_raw_aceita_vazio_como_null_ou_string_vazia(monkeypatch):
    m = raw.Medicoes()
    m.registrar_esperado("t", ("a",), 10, 3)
    problemas, _ = validar(
        monkeypatch, [linha("a", 10, nulos=1, vazias=2)], m, raw.ConjuntoValidacao("t", "valor")
    )
    assert problemas == []


def test_validar_raw_aponta_linhas_vazios_ausentes_e_extras(monkeypatch):
    m = raw.Medicoes()
    m.registrar_esperado("t", ("a",), 10, 0)
    m.registrar_esperado("t", ("b",), 5, 0)
    no_raw = [linha("a", 9, nulos=1), linha("outro", 1)]
    problemas, _ = validar(monkeypatch, no_raw, m, raw.ConjuntoValidacao("t", "valor"))
    texto = " | ".join(problemas)
    assert "9 linhas no raw, 10 no CSV" in texto
    assert "1 NULL + 0 '' no raw, 0 vazios no CSV" in texto
    assert "b: ausente em raw.t" in texto
    assert "que não vieram desta carga" in texto


def test_validar_raw_com_chave_composta(monkeypatch):
    m = raw.Medicoes()
    m.registrar_esperado("t", ("zip", "A701"), 4, 1)
    no_raw = [
        linha("zip", 4, nulos=1, estacao_codigo="A701"),
        linha("zip", 9, estacao_codigo="A999"),
    ]
    conjunto = raw.ConjuntoValidacao("t", "v", colunas_chave=("_arquivo_origem", "estacao_codigo"))
    problemas, sqls = validar(monkeypatch, no_raw, m, conjunto)
    assert "GROUP BY _arquivo_origem, estacao_codigo" in sqls[0]
    assert len(problemas) == 1 and "que não vieram desta carga" in problemas[0]


def test_medir_consulta_tipica_faz_dry_run_e_depois_executa_sem_cache(monkeypatch):
    chamadas = []

    def fake(cliente, sql, **kwargs):
        chamadas.append(kwargs)
        if kwargs.get("dry_run"):
            return ResultadoConsulta([], 100, None, None)
        return ResultadoConsulta([1, 2, 3], 100, 10485760, False)

    monkeypatch.setattr(raw.gcp, "cliente_bigquery", lambda config: object())
    monkeypatch.setattr(raw.gcp, "executar_consulta", fake)
    r = raw.medir_consulta_tipica(CONFIG, "SELECT 1")
    assert chamadas == [{"dry_run": True}, {"usar_cache": False}]
    assert r == {
        "bytes_estimados": 100,
        "bytes_processados": 100,
        "bytes_faturados": 10485760,
        "cache": False,
        "linhas": 3,
    }


def test_imprimir_resumo(capsys):
    m = raw.Medicoes(t_origem=1.0, t_gcs=2.0, t_bigquery=3.0)
    m.registrar_arquivo("a.csv", 2_000_000, 100)
    m.linhas_carregadas = 100
    consulta = {
        "bytes_estimados": 5,
        "bytes_processados": 5,
        "bytes_faturados": 10485760,
        "cache": False,
        "linhas": 24,
    }
    raw.imprimir_resumo(
        "da carga X",
        m,
        consulta,
        rotulo_volume="volume baixado",
        rotulo_origem="download",
        descricao_consulta="consulta Y",
        detalhe_arquivos=" (2000 a 2001)",
        listar_arquivos=True,
    )
    saida = capsys.readouterr().out
    assert "=== Medições da carga X (para docs/metricas.md) ===" in saida
    assert "arquivos: 1 (2000 a 2001)" in saida and "volume baixado: 2.0 MB" in saida
    assert "tempo total da carga: 6.0 s (download 1.0 s, GCS 2.0 s, BigQuery 3.0 s)" in saida
    assert "a.csv: 100 linhas" in saida and "consulta típica (consulta Y" in saida
    assert "linhas devolvidas: 24 (esperado: 24)" in saida


def test_validar_raw_com_dataset_filtro_e_chave_de_data(monkeypatch):
    import datetime

    m = raw.Medicoes()
    m.registrar_esperado("t", ("a.csv", "2026-09-01"), 4, 0)
    no_raw = [linha("a.csv", 4, _mes_referencia=datetime.date(2026, 9, 1))]
    conjunto = raw.ConjuntoValidacao(
        "t",
        "v",
        colunas_chave=("_arquivo_origem", "_mes_referencia"),
        dataset="verificacao_incremental",
        filtro_sql="_mes_referencia IN ('2026-09-01')",
    )
    problemas, sqls = validar(monkeypatch, no_raw, m, conjunto)
    assert problemas == []  # a chave DATE do BigQuery casa com o texto ISO esperado
    assert "`p.verificacao_incremental.t`" in sqls[0]
    assert "WHERE _mes_referencia IN ('2026-09-01')" in sqls[0]


def test_imprimir_resumo_mostra_jobs_e_particoes_do_incremental(capsys):
    m = raw.Medicoes(jobs_bigquery=3, particoes_carregadas=["202608", "202610"])
    m.anos_recarregados = [2019]
    raw.imprimir_resumo("x", m, None, rotulo_volume="v", rotulo_origem="o", descricao_consulta="c")
    saida = capsys.readouterr().out
    assert "load jobs no BigQuery: 3" in saida
    assert "partições recarregadas: 2 (202608 a 202610)" in saida
    assert "anos recarregados por inteiro (ETag/guarda): [2019]" in saida
