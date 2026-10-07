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


# ---- carga incremental do raw (Sprint 4) ----
import threading  # noqa: E402
import time  # noqa: E402

from google.api_core.exceptions import NotFound  # noqa: E402
from google.cloud import bigquery  # noqa: E402


class ClienteDeCarga:
    """Registra o destino e a configuração de cada load job."""

    def __init__(self, linhas=5):
        self.chamadas = []
        self.linhas = linhas

    def load_table_from_file(self, arquivo, destino, job_config):
        self.chamadas.append((destino, job_config))
        linhas = self.linhas

        class Job:
            output_rows = linhas

            def result(self):
                return None

        return Job()


def test_load_com_particao_usa_o_decorador_e_truncate_so_dela():
    cli = ClienteDeCarga()
    n = gcp.carregar_csv_no_bigquery(cli, "p.d.t", b"x", [], truncar=True, particao="202609")
    destino, config = cli.chamadas[0]
    assert n == 5 and destino == "p.d.t$202609"
    assert config.write_disposition == bigquery.WriteDisposition.WRITE_TRUNCATE


def test_load_full_leva_o_particionamento_esperado_e_sem_decorador():
    cli = ClienteDeCarga()
    gcp.carregar_csv_no_bigquery(
        cli,
        "p.d.t",
        b"x",
        [],
        truncar=True,
        particionamento=gcp.particionamento_mensal("_mes_referencia"),
    )
    destino, config = cli.chamadas[0]
    assert destino == "p.d.t"
    assert config.time_partitioning.field == "_mes_referencia"
    assert config.time_partitioning.type_ == "MONTH"


def test_load_sem_particao_continua_igual_para_ccee_e_inmet():
    cli = ClienteDeCarga()
    gcp.carregar_csv_no_bigquery(cli, "p.d.t", b"x", [], truncar=False)
    destino, config = cli.chamadas[0]
    assert destino == "p.d.t" and config.time_partitioning is None
    assert config.write_disposition == bigquery.WriteDisposition.WRITE_APPEND


class TabelaFalsa:
    def __init__(self, particao):
        self.time_partitioning = particao


class ClienteDeTabelas:
    def __init__(self, tabela=None):
        self.tabela, self.criadas = tabela, []

    def get_table(self, id_):
        if self.tabela is None:
            raise NotFound("não existe")
        return self.tabela

    def create_table(self, tabela):
        self.criadas.append(tabela)


def particao(campo, tipo="MONTH"):
    return bigquery.TimePartitioning(type_=tipo, field=campo)


def garantir(cli, criar):
    return gcp.garantir_tabela_particionada(cli, "p.d.t", [], "_mes_referencia", criar=criar)


def test_tabela_correta_existe_e_nada_e_criado():
    cli = ClienteDeTabelas(TabelaFalsa(particao("_mes_referencia")))
    assert garantir(cli, criar=False) == "existente" and cli.criadas == []


def test_tabela_inexistente_e_criada_particionada_so_se_pedido():
    cli = ClienteDeTabelas()
    assert garantir(cli, criar=True) == "criada"
    assert cli.criadas[0].time_partitioning.field == "_mes_referencia"
    with pytest.raises(gcp.TabelaIncompativel, match="--full"):
        garantir(ClienteDeTabelas(), criar=False)


@pytest.mark.parametrize("p", [None, particao("outra_coluna"), particao("_mes_referencia", "DAY")])
def test_tabela_com_outro_particionamento_e_recusada_sem_ser_alterada(p):
    cli = ClienteDeTabelas(TabelaFalsa(p))
    for criar in (False, True):  # nem a carga full recria uma tabela existente
        with pytest.raises(gcp.TabelaIncompativel, match="migração"):
            garantir(cli, criar=criar)
    assert cli.criadas == []


def trabalhos(*particoes, linhas=3):
    return {p: gcp.Trabalho(b"x", linhas, particao=p) for p in particoes}


def test_carregar_em_paralelo_devolve_as_linhas_por_particao():
    chamadas = []

    def carregar(cli, tabela, conteudo, esquema, *, truncar, particao):
        chamadas.append((particao, truncar))
        return 3

    ok = gcp.carregar_em_paralelo(
        None, "p.d.t", trabalhos("202608", "202609", "202610"), [], carregar=carregar
    )
    assert ok == {"202608": 3, "202609": 3, "202610": 3}
    assert sorted(chamadas) == [("202608", True), ("202609", True), ("202610", True)]


def test_carregar_em_paralelo_respeita_a_concorrencia_maxima():
    ativos, maximo, trava = 0, 0, threading.Lock()

    def carregar(cli, tabela, conteudo, esquema, *, truncar, particao):
        nonlocal ativos, maximo
        with trava:
            ativos += 1
            maximo = max(maximo, ativos)
        time.sleep(0.05)
        with trava:
            ativos -= 1
        return 3

    meses = [f"2026{m:02d}" for m in range(1, 11)]
    gcp.carregar_em_paralelo(None, "t", trabalhos(*meses), [], concorrencia=3, carregar=carregar)
    assert 1 < maximo <= 3


def test_falha_espera_os_outros_jobs_e_lista_os_meses_que_falharam():
    terminaram = []

    def carregar(cli, tabela, conteudo, esquema, *, truncar, particao):
        if particao == "202609":
            raise RuntimeError("quota")
        time.sleep(0.05)
        terminaram.append(particao)
        return 3

    with pytest.raises(gcp.ErroCargaParcial) as erro:
        gcp.carregar_em_paralelo(
            None, "t", trabalhos("202608", "202609", "202610"), [], carregar=carregar
        )
    assert sorted(terminaram) == ["202608", "202610"]  # os outros foram até o fim
    assert set(erro.value.falhas) == {"202609"} and "RuntimeError: quota" in str(erro.value)
    assert set(erro.value.ok) == {"202608", "202610"}


def test_job_que_carrega_outra_contagem_conta_como_falha():
    carregar = lambda *a, **k: 2  # noqa: E731
    with pytest.raises(gcp.ErroCargaParcial, match="o CSV tem 3 linhas e o job carregou 2"):
        gcp.carregar_em_paralelo(None, "t", trabalhos("202609"), [], carregar=carregar)


def test_carregar_em_paralelo_sem_trabalho_nao_faz_nada_e_recusa_concorrencia_zero():
    assert gcp.carregar_em_paralelo(None, "t", {}, []) == {}
    with pytest.raises(ValueError):
        gcp.carregar_em_paralelo(None, "t", trabalhos("202609"), [], concorrencia=0)


def test_listar_particoes_consulta_so_metadados_pela_porta_unica(monkeypatch):
    vistos = []

    def fake(cliente, sql, **kw):
        vistos.append((sql, kw))
        return gcp.ResultadoConsulta([{"partition_id": "202609"}], 1, 1, False)

    monkeypatch.setattr(gcp, "executar_consulta", fake)
    assert gcp.listar_particoes(None, "proj.verif.tab") == ["202609"]
    sql, kw = vistos[0]
    assert "`proj.verif.INFORMATION_SCHEMA.PARTITIONS`" in sql and "table_name = 'tab'" in sql
    assert kw == {"usar_cache": False}


def test_md5_hexadecimal_do_etag_vira_o_base64_do_gcs():
    assert gcp.md5_base64_de_hex("d41d8cd98f00b204e9800998ecf8427e") == gcp.md5_base64(b"")


def test_listar_objetos_indexa_pelo_nome():
    class B:
        def __init__(self, nome):
            self.name = nome

    class Cli:
        def list_blobs(self, bucket, prefix):
            assert (bucket, prefix) == ("b", "bronze/x/")
            return [B("bronze/x/a"), B("bronze/x/b")]

    assert set(gcp.listar_objetos(Cli(), "b", "bronze/x/")) == {"bronze/x/a", "bronze/x/b"}
