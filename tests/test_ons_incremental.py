"""Carga incremental do ONS (Sprint 4): fatia por mês, ETag, guarda de revisão e os dois fluxos."""

from datetime import date

import pytest

from ingestion import ons
from ingestion.common import gcp
from ingestion.common.config import Config
from ingestion.common.raw import Medicoes
from ingestion.janela import calcular_janela, janela_de_intervalo

CONFIG = Config("p", "b", "us-central1")
RAW = ons.Raw("p.verificacao_incremental.t", "verificacao_incremental", "t")
CABECALHO = "id_subsistema;nom_subsistema;din_instante;val_cargaenergiahomwmed\n"


def csv_ons(ano: int, meses: range, vazio_em: str | None = None) -> bytes:
    """Duas linhas (SE, 00h e 01h) por mês; `vazio_em` (AAAA-MM) deixa o valor da 1ª em branco."""
    linhas = []
    for m in meses:
        mes = f"{ano}-{m:02d}"
        valor = "" if mes == vazio_em else "100.5"
        linhas.append(f"SE;SUDESTE;{mes}-01 00:00:00;{valor}")
        linhas.append(f"SE;SUDESTE;{mes}-01 01:00:00;200.5")
    return (CABECALHO + "\n".join(linhas) + "\n").encode()


def raw_do_ano(ano: int, meses: range, **k):
    return ons._csv_do_raw(csv_ons(ano, meses, **k), ano, "2026-10-06T00:00:00+00:00")


# --- CSV do raw e fatia por mês ----------------------------------------------------------------


def test_csv_do_raw_acrescenta_o_mes_de_referencia_no_fim_das_colunas():
    texto = raw_do_ano(2026, range(1, 3)).conteudo.decode().splitlines()
    assert texto[0] == (
        "id_subsistema,nom_subsistema,din_instante,val_cargaenergiahomwmed,"
        "_arquivo_origem,_carregado_em,_mes_referencia"
    )
    assert texto[1].endswith(",2026-01-01") and texto[3].endswith(",2026-02-01")


def test_mes_referencia_e_o_mes_local_e_recusa_instante_estranho():
    assert ons.mes_referencia({"din_instante": "2026-09-30 23:00:00"}) == "2026-09-01"
    with pytest.raises(ValueError):
        ons.mes_referencia({"din_instante": ""})


def test_fatiar_por_mes_cria_um_csv_por_mes_com_so_as_linhas_dele():
    fatias = ons.fatiar_por_mes(raw_do_ano(2026, range(1, 4), vazio_em="2026-02").conteudo)
    assert list(fatias) == ["2026-01", "2026-02", "2026-03"]
    for mes, fatia in fatias.items():
        linhas = fatia.conteudo.decode().splitlines()
        assert linhas[0].startswith("id_subsistema,") and len(linhas) == 3 and fatia.linhas == 2
        assert all(linha.endswith(f",{mes}-01") for linha in linhas[1:])
    assert [f.vazios for f in fatias.values()] == [0, 1, 0]


# --- ETag dos anos fechados ----------------------------------------------------------------------


class Objeto:
    def __init__(self, conteudo: bytes):
        self.md5_hash = gcp.md5_base64(conteudo)


def hex_md5(conteudo: bytes) -> str:
    import hashlib

    return hashlib.md5(conteudo, usedforsecurity=False).hexdigest()


def test_etag_md5_vira_o_formato_do_gcs_e_o_que_nao_e_md5_vira_none():
    c = b"abc"
    assert ons.etag_para_md5_base64(hex_md5(c)) == gcp.md5_base64(c)
    assert ons.etag_para_md5_base64("d41d8cd98f00b204e9800998ecf8427e-3") is None  # multipart
    assert ons.etag_para_md5_base64(None) is None


def test_anos_fechados_desatualizados_compara_o_etag_com_o_md5_do_bronze_sem_baixar():
    iguais, mudado = b"2019 igual", b"2020 novo"
    objetos = {
        ons.caminho_gcs(2019): Objeto(iguais),
        ons.caminho_gcs(2020): Objeto(b"2020 antigo"),
        ons.caminho_gcs(2022): Objeto(b"x"),
        # 2021 não tem bronze
    }
    etags = {
        ons.montar_url(2019): hex_md5(iguais),
        ons.montar_url(2020): hex_md5(mudado),
        ons.montar_url(2021): hex_md5(b"qualquer"),
        ons.montar_url(2022): "abc-2",  # não é MD5: na dúvida, baixa
    }
    consultados = []

    def buscar(url):
        consultados.append(url)
        return etags[url]

    r = ons.anos_fechados_desatualizados([2019, 2020, 2021, 2022], objetos, buscar)
    assert r == [2020, 2021, 2022]
    assert sorted(consultados) == sorted(ons.montar_url(a) for a in (2019, 2020, 2021, 2022))


# --- guarda de revisão e escolha dos meses ------------------------------------------------------


def test_revisao_so_dentro_da_janela_nao_dispara_a_guarda():
    j = calcular_janela(date(2026, 10, 6))
    assert ons.meses_fora_da_janela({"meses_afetados": ["2026-09", "2026-10"]}, j) == []
    assert ons.meses_fora_da_janela({}, j) == []


def test_revisao_fora_da_janela_e_listada():
    j = calcular_janela(date(2026, 10, 6))
    assert ons.meses_fora_da_janela({"meses_afetados": ["2026-03", "2026-09"]}, j) == ["2026-03"]


def test_meses_a_carregar_so_a_janela_ou_o_ano_inteiro():
    fatias = ons.fatiar_por_mes(raw_do_ano(2026, range(1, 11)).conteudo)
    j = calcular_janela(date(2026, 10, 6))
    assert ons.meses_a_carregar(2026, fatias, j, set()) == ["2026-08", "2026-09", "2026-10"]
    assert len(ons.meses_a_carregar(2026, fatias, j, {2026})) == 10


# --- carregar_incremental com a nuvem trocada por fakes -----------------------------------------


@pytest.fixture
def nuvem(monkeypatch):
    estado = {"urls": [], "trabalhos": None, "revisao": None, "fechados": []}
    arquivos = {2026: csv_ons(2026, range(1, 11)), 2025: csv_ons(2025, range(1, 13))}
    arquivos[2019] = csv_ons(2019, range(1, 13))
    estado["arquivos"] = arquivos

    def baixar(url):
        estado["urls"].append(url)
        ano = int(url.rsplit("_", 1)[1][:4])
        if ano not in arquivos:
            raise ons.ArquivoNaoEncontrado(url)
        return arquivos[ano]

    def sincronizar(cli, bucket, ano, original, medicoes):
        if estado["revisao"] and ano == 2026:
            medicoes.revisoes.append(estado["revisao"])
        return estado.get("bronze", {}).get(ano, "gravado")

    def paralelo(cli, tabela_id, trabalhos, esquema, *, concorrencia):
        estado["trabalhos"], estado["concorrencia"], estado["tabela"] = (
            trabalhos,
            concorrencia,
            tabela_id,
        )
        if estado.get("falha"):
            ok = {k: t.linhas for k, t in trabalhos.items() if k != estado["falha"]}
            raise gcp.ErroCargaParcial({estado["falha"]: "BadRequest: x"}, ok)
        return {k: t.linhas for k, t in trabalhos.items()}

    monkeypatch.setattr(ons.gcp, "cliente_storage", lambda config: None)
    monkeypatch.setattr(ons.gcp, "cliente_bigquery", lambda config: None)
    monkeypatch.setattr(ons.gcp, "listar_objetos", lambda *a: {})
    monkeypatch.setattr(ons, "baixar_bytes", baixar)
    monkeypatch.setattr(ons, "sincronizar_bronze", sincronizar)
    monkeypatch.setattr(ons.gcp, "carregar_em_paralelo", paralelo)
    monkeypatch.setattr(
        ons, "anos_fechados_desatualizados", lambda anos, objetos, **k: estado["fechados"]
    )
    return estado


def incremental(janela, **k):
    return ons.carregar_incremental(janela, CONFIG, RAW, 8, verificar_fechados=k.pop("v", True))


def test_janela_diaria_baixa_so_o_ano_corrente_e_carrega_so_os_3_meses(nuvem):
    m = incremental(calcular_janela(date(2026, 10, 6)))
    assert nuvem["urls"] == [ons.montar_url(2026)]
    assert sorted(nuvem["trabalhos"]) == ["202608", "202609", "202610"]
    assert all(t.truncar and t.particao == k for k, t in nuvem["trabalhos"].items())
    assert nuvem["tabela"] == RAW.id and nuvem["concorrencia"] == 8
    assert m.jobs_bigquery == 3 and m.particoes_carregadas == ["202608", "202609", "202610"]
    assert m.linhas_carregadas == 6 and m.arquivos == 1
    assert m.esperado["t"][(ons.caminho_gcs(2026), "2026-09-01")] == (2, 0)


def test_reexecutar_a_mesma_janela_monta_os_mesmos_jobs(nuvem):
    j = calcular_janela(date(2026, 10, 6))
    incremental(j)
    primeira = {k: (t.particao, t.linhas) for k, t in nuvem["trabalhos"].items()}
    incremental(j)
    assert {k: (t.particao, t.linhas) for k, t in nuvem["trabalhos"].items()} == primeira


def test_ano_fechado_que_mudou_no_ons_e_recarregado_por_inteiro(nuvem):
    nuvem["fechados"] = [2019]
    m = incremental(calcular_janela(date(2026, 10, 6)))
    assert set(nuvem["urls"]) == {ons.montar_url(2019), ons.montar_url(2026)}
    assert len(nuvem["trabalhos"]) == 12 + 3 and "201903" in nuvem["trabalhos"]
    assert m.anos_recarregados == [2019]


def test_backfill_nao_confere_anos_fechados(nuvem, monkeypatch):
    chamado = []
    monkeypatch.setattr(
        ons, "anos_fechados_desatualizados", lambda *a, **k: chamado.append(1) or []
    )
    incremental(janela_de_intervalo("2025-11", "2026-02"), v=False)
    assert chamado == [] and sorted(nuvem["urls"]) == [ons.montar_url(2025), ons.montar_url(2026)]
    assert sorted(nuvem["trabalhos"]) == ["202511", "202512", "202601", "202602"]


def test_revisao_fora_da_janela_recarrega_o_ano_inteiro_e_loga_aviso(nuvem, monkeypatch, caplog):
    monkeypatch.setattr(ons.log, "propagate", True)
    nuvem["revisao"] = {"meses_afetados": ["2026-03", "2026-10"]}
    m = incremental(calcular_janela(date(2026, 10, 6)))
    assert len(nuvem["trabalhos"]) == 10  # janeiro a outubro
    assert m.anos_recarregados == [2026] and "FORA da janela" in caplog.text


def test_revisao_dentro_da_janela_nao_amplia_a_carga(nuvem):
    nuvem["revisao"] = {"meses_afetados": ["2026-09", "2026-10"]}
    m = incremental(calcular_janela(date(2026, 10, 6)))
    assert len(nuvem["trabalhos"]) == 3 and m.anos_recarregados == []


def test_janeiro_cruza_dois_arquivos_e_ignora_o_404_do_ano_novo(nuvem):
    # em janeiro de 2027 o arquivo de 2027 ainda não existe (404): carrega só o ano anterior
    nuvem["arquivos"][2026] = csv_ons(2026, range(1, 13))
    m = incremental(calcular_janela(date(2027, 1, 15)))
    assert nuvem["urls"] == [ons.montar_url(2026), ons.montar_url(2027)]
    assert m.arquivos == 1 and sorted(nuvem["trabalhos"]) == ["202611", "202612"]


def test_falha_de_uma_particao_propaga_com_as_que_deram_certo(nuvem):
    nuvem["falha"] = "202609"
    with pytest.raises(gcp.ErroCargaParcial) as erro:
        incremental(calcular_janela(date(2026, 10, 6)))
    assert set(erro.value.falhas) == {"202609"} and set(erro.value.ok) == {"202608", "202610"}


# --- carga full ---------------------------------------------------------------------------------


def test_full_trunca_o_primeiro_ano_e_acrescenta_os_demais_em_paralelo(monkeypatch):
    eventos = {"garantir": None, "diretos": [], "paralelo": None}
    arquivos = {a: csv_ons(a, range(1, 13)) for a in (2000, 2001, 2002)}
    monkeypatch.setattr(ons.gcp, "cliente_storage", lambda c: None)
    monkeypatch.setattr(ons.gcp, "cliente_bigquery", lambda c: None)
    monkeypatch.setattr(ons, "baixar_bytes", lambda url: arquivos[int(url[-8:-4])])
    monkeypatch.setattr(ons, "sincronizar_bronze", lambda *a: "pulado (hash igual)")
    monkeypatch.setattr(
        ons.gcp,
        "garantir_tabela_particionada",
        lambda cli, tabela, esquema, campo, *, criar: (
            eventos.update(garantir=(tabela, campo, criar)) or "criada"
        ),
    )

    def direto(cli, tabela, conteudo, esquema, *, truncar, particao=None, particionamento=None):
        eventos["diretos"].append((truncar, particao, particionamento.field))
        return 24

    def paralelo(cli, tabela, trabalhos, esquema, *, concorrencia):
        eventos["paralelo"] = (
            sorted(trabalhos),
            concorrencia,
            {t.truncar for t in trabalhos.values()},
        )
        return {k: t.linhas for k, t in trabalhos.items()}

    monkeypatch.setattr(ons.gcp, "carregar_csv_no_bigquery", direto)
    monkeypatch.setattr(ons.gcp, "carregar_em_paralelo", paralelo)
    m = ons.carregar_full([2000, 2001, 2002], CONFIG, RAW, 2026, 8)
    assert eventos["garantir"] == (RAW.id, "_mes_referencia", True)
    assert eventos["diretos"] == [(True, None, "_mes_referencia")]
    assert eventos["paralelo"] == (["ano 2001", "ano 2002"], 8, {False})
    assert m.jobs_bigquery == 3 and m.linhas_carregadas == 72 and m.arquivos == 3
    assert (ons.caminho_gcs(2001),) in m.esperado["t"]


# --- janela e validação -------------------------------------------------------------------------


def test_resolver_janela_usa_o_ultimo_mes_do_raw_e_estende(monkeypatch):
    chamadas = []
    monkeypatch.setattr(ons.gcp, "cliente_bigquery", lambda c: None)
    monkeypatch.setattr(
        ons.gcp,
        "garantir_tabela_particionada",
        lambda *a, criar: chamadas.append(criar) or "existente",
    )
    monkeypatch.setattr(ons.gcp, "listar_particoes", lambda cli, t: ["202605", "202606", "NULL"])
    j = ons.resolver_janela(CONFIG, RAW, None, None, date(2026, 10, 6))
    assert j.estendida and j.mes_inicial == date(2026, 6, 1) and chamadas == [False]


def test_resolver_janela_recusa_raw_vazio_e_nao_consulta_particoes_no_backfill(monkeypatch):
    monkeypatch.setattr(ons.gcp, "cliente_bigquery", lambda c: None)
    monkeypatch.setattr(ons.gcp, "garantir_tabela_particionada", lambda *a, criar: "existente")
    monkeypatch.setattr(ons.gcp, "listar_particoes", lambda cli, t: [])
    with pytest.raises(gcp.TabelaIncompativel, match="--full"):
        ons.resolver_janela(CONFIG, RAW, None, None, date(2026, 10, 6))
    j = ons.resolver_janela(CONFIG, RAW, "2021-01", "2021-03", date(2026, 10, 6))
    assert j.particoes_raw == ["202101", "202102", "202103"]


def test_validacao_incremental_so_dos_meses_recarregados_e_a_full_por_arquivo():
    m = Medicoes()
    m.registrar_esperado("t", ("a.csv", "2026-09-01"), 2, 0)
    m.registrar_esperado("t", ("a.csv", "2026-08-01"), 2, 0)
    inc = ons.conjunto_de_validacao("janela", RAW, m)
    assert inc.colunas_chave == ("_arquivo_origem", "_mes_referencia")
    assert inc.filtro_sql == "_mes_referencia IN ('2026-08-01', '2026-09-01')"
    assert inc.dataset == "verificacao_incremental"
    full = ons.conjunto_de_validacao("full", RAW, m)
    assert full.colunas_chave == ("_arquivo_origem",) and full.filtro_sql == ""
    assert ons.conjunto_de_validacao("janela", RAW, Medicoes()) is None


def test_heads_em_paralelo_respeitam_a_concorrencia_e_mantem_a_ordem_dos_anos():
    import threading
    import time

    ativos, maximo, trava = 0, 0, threading.Lock()
    objetos = {ons.caminho_gcs(a): Objeto(f"{a}".encode()) for a in range(2000, 2012)}

    def buscar(url):
        nonlocal ativos, maximo
        with trava:
            ativos += 1
            maximo = max(maximo, ativos)
        time.sleep(0.05)
        with trava:
            ativos -= 1
        ano = int(url[-8:-4])
        # os anos pares estão desatualizados (ETag diferente do MD5 do bronze)
        return hex_md5(f"{ano}".encode() if ano % 2 else b"outro")

    r = ons.anos_fechados_desatualizados(list(range(2000, 2012)), objetos, buscar, concorrencia=4)
    assert r == [2000, 2002, 2004, 2006, 2008, 2010]  # ordem dos anos, não a de término
    assert 1 < maximo <= 4


def test_head_que_falha_depois_das_retentativas_manda_so_aquele_ano_para_o_download(
    monkeypatch, caplog
):
    monkeypatch.setattr(ons.log, "propagate", True)
    objetos = {ons.caminho_gcs(a): Objeto(f"{a}".encode()) for a in (2019, 2020, 2021)}

    def buscar(url):
        ano = int(url[-8:-4])
        if ano == 2020:
            raise ons.download.ErroDownload("3 tentativas esgotadas")
        return hex_md5(f"{ano}".encode())  # os outros estão em dia

    r = ons.anos_fechados_desatualizados([2019, 2020, 2021], objetos, buscar)
    assert r == [2020]  # só o do HEAD que falhou
    assert "HEAD de 2020 falhou" in caplog.text and "o ano será baixado" in caplog.text


def test_head_com_erro_de_rede_do_requests_tambem_cai_no_download():
    import requests

    def buscar(url):
        raise requests.exceptions.SSLError("certificado")

    assert ons.anos_fechados_desatualizados(
        [2019], {ons.caminho_gcs(2019): Objeto(b"x")}, buscar
    ) == [2019]


def test_erro_de_programacao_no_head_nao_e_engolido():
    def buscar(url):
        raise ValueError("bug meu")

    with pytest.raises(ValueError, match="bug meu"):
        ons.anos_fechados_desatualizados([2019], {}, buscar)
    assert ons.anos_fechados_desatualizados([], {}) == []


def test_ano_fechado_baixado_por_falha_do_head_e_identico_ao_bronze_nao_e_recarregado(nuvem):
    nuvem["fechados"] = [2019]  # o HEAD falhou: o ano foi mandado para o download
    nuvem["bronze"] = {2019: "pulado (hash igual)"}
    m = incremental(calcular_janela(date(2026, 10, 6)))
    assert ons.montar_url(2019) in nuvem["urls"]  # baixou
    assert sorted(nuvem["trabalhos"]) == ["202608", "202609", "202610"]  # mas não recarregou
    assert m.anos_recarregados == []


def test_ano_fechado_cujo_arquivo_mudou_de_verdade_e_recarregado_inteiro(nuvem):
    nuvem["fechados"] = [2019]
    nuvem["bronze"] = {2019: "gravado em gs://x, versão antiga arquivada"}
    m = incremental(calcular_janela(date(2026, 10, 6)))
    assert len(nuvem["trabalhos"]) == 12 + 3 and m.anos_recarregados == [2019]
