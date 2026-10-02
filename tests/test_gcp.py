from pathlib import Path

import pytest

from ingestion.common import gcp


class JobFalso:
    total_bytes_processed = 123
    total_bytes_billed = 10 * 1024 * 1024
    cache_hit = False

    def result(self):
        return ["linha"]


class ClienteBigQueryFalso:
    def __init__(self):
        self.configuracoes = []

    def query(self, sql, job_config):
        self.configuracoes.append(job_config)
        return JobFalso()


def test_consulta_sempre_leva_maximum_bytes_billed():
    cliente = ClienteBigQueryFalso()
    resultado = gcp.executar_consulta(cliente, "SELECT 1")
    assert cliente.configuracoes[0].maximum_bytes_billed == gcp.MAX_BYTES_PADRAO
    assert gcp.MAX_BYTES_PADRAO == 200 * 1024 * 1024
    assert resultado.linhas == ["linha"]
    assert resultado.bytes_processados == 123 and resultado.cache is False


def test_limite_pode_ser_diminuido_mas_nao_desligado():
    cliente = ClienteBigQueryFalso()
    gcp.executar_consulta(cliente, "SELECT 1", max_bytes_faturados=1000)
    assert cliente.configuracoes[0].maximum_bytes_billed == 1000
    for invalido in (0, -1, None):
        with pytest.raises(ValueError):
            gcp.executar_consulta(cliente, "SELECT 1", max_bytes_faturados=invalido)


def test_dry_run_e_cache_desligado_vao_para_a_configuracao():
    cliente = ClienteBigQueryFalso()
    gcp.executar_consulta(cliente, "SELECT 1", dry_run=True)
    gcp.executar_consulta(cliente, "SELECT 1", usar_cache=False)
    estimativa, sem_cache = cliente.configuracoes
    assert estimativa.dry_run is True and estimativa.maximum_bytes_billed is not None
    assert sem_cache.use_query_cache is False and sem_cache.maximum_bytes_billed is not None


def test_dry_run_nao_devolve_linhas_nem_bytes_faturados():
    resultado = gcp.executar_consulta(ClienteBigQueryFalso(), "SELECT 1", dry_run=True)
    assert resultado.linhas == [] and resultado.bytes_faturados is None


def test_nenhum_codigo_consulta_o_bigquery_fora_de_executar_consulta():
    """Guarda de custo: `.query(` só pode aparecer em ingestion/common/gcp.py."""
    raiz = Path(__file__).resolve().parent.parent / "ingestion"
    fora = [
        str(arq.relative_to(raiz.parent))
        for arq in raiz.rglob("*.py")
        if arq.name != "gcp.py" and ".query(" in arq.read_text()
    ]
    assert fora == []


def test_enviar_para_gcs_grava_bytes_com_checksum():
    gravado = {}

    class Blob:
        def upload_from_string(self, dados, content_type, checksum):
            gravado.update(dados=dados, tipo=content_type, checksum=checksum)

    class Bucket:
        def blob(self, caminho):
            gravado["caminho"] = caminho
            return Blob()

    class Cliente:
        def bucket(self, nome):
            gravado["bucket"] = nome
            return Bucket()

    uri = gcp.enviar_para_gcs(Cliente(), "meu-bucket", "bronze/a.csv", b"\x00\xffbytes")
    assert uri == "gs://meu-bucket/bronze/a.csv"
    assert gravado["dados"] == b"\x00\xffbytes"  # sem alteração
    assert gravado["checksum"] == "crc32c" and gravado["bucket"] == "meu-bucket"


def test_montar_esquema_fonte_em_string_e_extras_com_tipo():
    esquema = gcp.montar_esquema(
        ["a", "b"], {"_arquivo_origem": "STRING", "_carregado_em": "TIMESTAMP"}
    )
    assert [(c.name, c.field_type) for c in esquema] == [
        ("a", "STRING"),
        ("b", "STRING"),
        ("_arquivo_origem", "STRING"),
        ("_carregado_em", "TIMESTAMP"),
    ]


def test_enviar_arquivo_para_gcs_usa_o_arquivo_local_com_checksum(tmp_path):
    gravado = {}

    class Blob:
        def upload_from_filename(self, caminho, content_type, checksum):
            gravado.update(caminho=caminho, tipo=content_type, checksum=checksum)

    class Bucket:
        def blob(self, caminho):
            gravado["destino"] = caminho
            return Blob()

    class Cliente:
        def bucket(self, nome):
            return Bucket()

    arquivo = tmp_path / "2024.zip"
    uri = gcp.enviar_arquivo_para_gcs(
        Cliente(), "meu-bucket", "bronze/inmet/ano=2024/2024.zip", arquivo, tipo="application/zip"
    )
    assert uri == "gs://meu-bucket/bronze/inmet/ano=2024/2024.zip"
    assert gravado == {
        "caminho": str(arquivo),
        "tipo": "application/zip",
        "checksum": "crc32c",
        "destino": "bronze/inmet/ano=2024/2024.zip",
    }
