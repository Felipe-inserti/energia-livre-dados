from datetime import UTC, date, datetime

import pytest

from ingestion import ons
from ingestion.common import gcp
from ingestion.common.config import Config
from ingestion.common.raw import Medicoes
from ingestion.janela import calcular_janela


def test_montar_url_por_ano():
    assert ons.montar_url(2024) == (
        "https://ons-aws-prod-opendata.s3.amazonaws.com/dataset/curva-carga-ho/CURVA_CARGA_2024.csv"
    )
    assert ons.montar_url(2000).endswith("/CURVA_CARGA_2000.csv")


def test_caminho_no_gcs_da_bronze():
    assert ons.caminho_gcs(2024) == "bronze/ons/curva_carga/ano=2024/CURVA_CARGA_2024.csv"
    assert ons.caminho_gcs(2000) == "bronze/ons/curva_carga/ano=2000/CURVA_CARGA_2000.csv"
    assert ons.nome_arquivo(2026) == "CURVA_CARGA_2026.csv"


def test_anos_a_carregar_de_2000_ate_o_ano_final():
    assert ons.anos_a_carregar(2000, 2003) == [2000, 2001, 2002, 2003]
    assert len(ons.anos_a_carregar(2000, 2026)) == 27


def test_anos_invalidos():
    with pytest.raises(ValueError):
        ons.anos_a_carregar(1999, 2020)  # 1999 não existe no ONS
    with pytest.raises(ValueError):
        ons.anos_a_carregar(2020, 2019)


def test_validar_colunas_aceita_o_layout_conhecido_e_recusa_mudanca():
    ons.validar_colunas(list(ons.COLUNAS_ESPERADAS))
    with pytest.raises(ValueError, match="Layout inesperado"):
        ons.validar_colunas(["id_subsistema", "din_instante"])


def test_consultas_citam_a_tabela_do_raw_e_nao_a_do_bronze():
    sql = ons.CONSULTA_TIPICA.format(tabela="p.raw.ons_curva_carga")
    assert "`p.raw.ons_curva_carga`" in sql and "'SE'" in sql and "2024-01-01" in sql


# ---- bronze gravado só quando o hash muda (tarefa 3.4) ----
CABECALHO_CSV = b"id_subsistema;nom_subsistema;din_instante;val_cargaenergiahomwmed\n"
CSV_ANTIGO = CABECALHO_CSV + b"SE;SUDESTE;2026-01-01 00:00:00;100.0\n"
CSV_NOVO = CSV_ANTIGO.replace(b"100.0", b"101.0")


class ObjetoFalso:
    def __init__(self, conteudo: bytes):
        self._c = conteudo
        self.md5_hash = gcp.md5_base64(conteudo)
        self.size = len(conteudo)
        self.updated = datetime(2026, 10, 2, 15, 6, 0, tzinfo=UTC)

    def download_as_bytes(self):
        return self._c


def preparar(monkeypatch, tmp_path, existente: bytes | None):
    eventos = []
    monkeypatch.setattr(
        gcp, "buscar_objeto", lambda *_: ObjetoFalso(existente) if existente else None
    )
    monkeypatch.setattr(
        gcp, "copiar_objeto", lambda cli, b, origem, destino: eventos.append(("copia", destino))
    )
    monkeypatch.setattr(
        gcp,
        "enviar_para_gcs",
        lambda cli, b, caminho, c: eventos.append(("envio", caminho)) or "gs://x",
    )
    monkeypatch.setattr(ons.revisoes, "ARQUIVO_LOG", tmp_path / "rev.jsonl")
    monkeypatch.setattr(
        ons.revisoes,
        "registrar",
        lambda reg, origem: (tmp_path / "rev.jsonl").write_text(origem),
    )
    return eventos


def test_hash_igual_nao_grava_nada(monkeypatch, tmp_path):
    eventos = preparar(monkeypatch, tmp_path, CSV_ANTIGO)
    m = Medicoes()
    texto = ons.sincronizar_bronze(None, "b", 2026, CSV_ANTIGO, m)
    assert texto == "pulado (hash igual)"
    assert eventos == [] and (m.gcs_pulados, m.gcs_gravados, m.gcs_versoes) == (1, 0, 0)


def test_arquivo_novo_so_grava(monkeypatch, tmp_path):
    eventos = preparar(monkeypatch, tmp_path, None)
    m = Medicoes()
    texto = ons.sincronizar_bronze(None, "b", 2026, CSV_NOVO, m)
    assert texto == "gravado em gs://x"
    assert [e[0] for e in eventos] == ["envio"]
    assert m.gcs_gravados == 1 and m.gcs_bytes_gravados == len(CSV_NOVO) and m.gcs_versoes == 0


def test_arquivo_mudado_arquiva_a_versao_antiga_antes_de_sobrescrever(monkeypatch, tmp_path):
    eventos = preparar(monkeypatch, tmp_path, CSV_ANTIGO)
    m = Medicoes()
    texto = ons.sincronizar_bronze(None, "b", 2026, CSV_NOVO, m)
    assert texto == "gravado em gs://x, versão antiga arquivada"
    assert eventos == [
        (
            "copia",
            "bronze/ons/curva_carga_versoes/ano=2026/carga=20261002T150600Z/CURVA_CARGA_2026.csv",
        ),
        ("envio", "bronze/ons/curva_carga/ano=2026/CURVA_CARGA_2026.csv"),
    ]
    assert m.gcs_versoes == 1 and m.gcs_bytes_versoes == len(CSV_ANTIGO)
    assert m.revisoes[0]["valor_alterado"] == 1


def test_md5_do_gcs_e_base64_do_digest():
    assert gcp.md5_base64(b"") == "1B2M2Y8AsgTpgAmY7PhCfg=="


CONFIG = Config("p", "b", "us-central1")


def _simular(monkeypatch, modo_chamadas):
    """Troca as pontas de nuvem do `main` por registradores; devolve a lista de chamadas."""
    chamadas = modo_chamadas
    monkeypatch.setattr(ons, "carregar_config", lambda: CONFIG)
    monkeypatch.setattr(
        ons, "resolver_janela", lambda *a: chamadas.append(("janela", a[1].id, a[2:])) or JANELA
    )
    monkeypatch.setattr(
        ons,
        "carregar_incremental",
        lambda janela, config, raw, conc, **k: (
            chamadas.append(("incremental", raw.id, k)) or Medicoes()
        ),
    )
    monkeypatch.setattr(
        ons,
        "carregar_full",
        lambda anos, config, raw, ano_atual, conc: (
            chamadas.append(("full", raw.id, anos[:1])) or Medicoes()
        ),
    )
    monkeypatch.setattr(ons, "validar_raw", lambda *a: chamadas.append("validar") or [])
    monkeypatch.setattr(ons, "medir_consulta_tipica", lambda *a: chamadas.append("medir"))
    monkeypatch.setattr(ons, "imprimir_resumo", lambda *a, **k: None)


JANELA = calcular_janela(date(2026, 10, 6))


def test_sem_medicao_valida_o_raw_mas_nao_roda_a_consulta_tipica(monkeypatch):
    chamadas = []
    _simular(monkeypatch, chamadas)
    medicoes = Medicoes()
    medicoes.registrar_esperado("ons_curva_carga", ("c", "2026-10-01"), 1, 0)
    monkeypatch.setattr(ons, "carregar_incremental", lambda *a, **k: medicoes)
    assert ons.main(["--sem-medicao"]) == 0
    assert chamadas[-1] == "validar" and "medir" not in chamadas


def test_modo_padrao_e_janela_no_raw_configurado_e_so_verifica_fechados_na_janela(monkeypatch):
    chamadas = []
    _simular(monkeypatch, chamadas)
    argv = ["--sem-consulta", "--dataset-raw", "verificacao_incremental"]
    assert ons.main([*argv, "--tabela-raw", "t_teste"]) == 0
    assert chamadas[0][1] == "p.verificacao_incremental.t_teste"
    assert chamadas[1] == (
        "incremental",
        "p.verificacao_incremental.t_teste",
        {"verificar_fechados": True},
    )


def test_backfill_nao_verifica_anos_fechados(monkeypatch):
    chamadas = []
    _simular(monkeypatch, chamadas)
    assert ons.main(["--sem-consulta", "--desde", "2021-01", "--ate", "2021-03"]) == 0
    assert chamadas[0][2][:2] == ("2021-01", "2021-03")
    assert chamadas[1][2] == {"verificar_fechados": False}


def test_full_usa_a_carga_full_e_o_raw_de_producao_por_padrao(monkeypatch):
    chamadas = []
    _simular(monkeypatch, chamadas)
    assert ons.main(["--full", "--sem-consulta", "--ano-final", "2002"]) == 0
    assert chamadas == [("full", "p.raw.ons_curva_carga", [2000])]


@pytest.mark.parametrize(
    "argv",
    [
        ["--desde", "2021-01"],
        ["--ate", "2021-01"],
        ["--full", "--desde", "2021-01", "--ate", "2021-02"],
    ],
)
def test_combinacoes_invalidas_de_argumentos(monkeypatch, argv):
    _simular(monkeypatch, [])
    with pytest.raises(SystemExit):
        ons.main(argv)


def test_tabela_incompativel_vira_codigo_2_sem_gravar_nada(monkeypatch):
    chamadas = []
    _simular(monkeypatch, chamadas)

    def recusar(*a):
        raise gcp.TabelaIncompativel("sem partição: rode a migração")

    monkeypatch.setattr(ons, "resolver_janela", recusar)
    assert ons.main([]) == 2
    assert chamadas == []


def test_carga_parcial_vira_codigo_1_e_lista_os_meses(monkeypatch, caplog):
    _simular(monkeypatch, [])
    monkeypatch.setattr(ons.log, "propagate", True)

    def falhar(*a, **k):
        raise gcp.ErroCargaParcial({"202609": "BadRequest: x"}, {"202610": 10})

    monkeypatch.setattr(ons, "carregar_incremental", falhar)
    assert ons.main(["--sem-consulta"]) == 1
    assert "falhou: 202609" in caplog.text and "idempotente" in caplog.text


def test_o_destino_e_o_modo_sao_logados_no_inicio(monkeypatch, caplog):
    _simular(monkeypatch, [])
    monkeypatch.setattr(ons.log, "propagate", True)
    ons.main(["--sem-consulta", "--dataset-raw", "verificacao_incremental"])
    assert (
        caplog.records[0]
        .getMessage()
        .startswith("destino: p.verificacao_incremental.ons_curva_carga | modo: janela")
    )
