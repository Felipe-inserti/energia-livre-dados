import json
import os

import pytest
import requests

from ingestion import orquestracao as orq


def criar(pasta, nome, conteudo=b"x"):
    arquivo = pasta / nome
    arquivo.write_bytes(conteudo)
    return arquivo


def test_sem_estado_e_arquivo_novo_e_depois_de_registrar_deixa_de_ser(tmp_path):
    pasta, estado = tmp_path / "ccee", tmp_path / "estado" / "ccee.json"
    pasta.mkdir()
    criar(pasta, "a.csv")
    assert orq.ha_arquivo_novo(pasta, "*.csv", estado) is True
    orq.registrar_estado(pasta, "*.csv", estado)
    assert orq.ha_arquivo_novo(pasta, "*.csv", estado) is False
    assert set(json.loads(estado.read_text())) == {"a.csv"}


def test_arquivo_trocado_ou_acrescentado_conta_como_novo(tmp_path):
    pasta, estado = tmp_path, tmp_path / "e.json"
    arquivo = criar(pasta, "a.csv", b"1")
    orq.registrar_estado(pasta, "*.csv", estado)
    arquivo.write_bytes(b"12345")  # outro tamanho
    assert orq.ha_arquivo_novo(pasta, "*.csv", estado) is True
    orq.registrar_estado(pasta, "*.csv", estado)
    criar(pasta, "b.csv")
    assert orq.ha_arquivo_novo(pasta, "*.csv", estado) is True


def test_mesma_data_e_tamanho_com_outra_data_de_modificacao_tambem_e_novo(tmp_path):
    pasta, estado = tmp_path, tmp_path / "e.json"
    arquivo = criar(pasta, "a.csv", b"1")
    orq.registrar_estado(pasta, "*.csv", estado)
    os.utime(arquivo, ns=(1, 2_000_000_000))
    assert orq.ha_arquivo_novo(pasta, "*.csv", estado) is True


def test_pasta_sem_arquivos_nao_dispara_carga_e_estado_corrompido_conta_como_novo(tmp_path):
    estado = tmp_path / "e.json"
    assert orq.ha_arquivo_novo(tmp_path, "*.csv", estado) is False
    criar(tmp_path, "a.csv")
    estado.write_text("{ não é json")
    assert orq.ha_arquivo_novo(tmp_path, "*.csv", estado) is True


def test_registrar_estado_nao_deixa_arquivo_temporario(tmp_path):
    criar(tmp_path, "a.csv")
    estado = tmp_path / "estado" / "x.json"
    orq.registrar_estado(tmp_path, "*.csv", estado)
    assert [p.name for p in estado.parent.iterdir()] == ["x.json"]


def mensagem(**extra):
    base = dict(
        dag_id="energia_livre_diaria",
        task_id="dbt_test",
        run_id="manual__2026-10-06",
        tentativa=1,
        max_tentativas=1,
        erro="Got 1 result",
        url="http://localhost:8080/x",
    )
    return orq.montar_mensagem_falha(**{**base, **extra})


def test_mensagem_tem_dag_task_execucao_tentativa_erro_e_link():
    texto = mensagem()
    for trecho in (
        "energia_livre_diaria",
        "dbt_test",
        "manual__2026-10-06",
        "tentativa 1 de 1",
        "Got 1 result",
        "http://localhost:8080/x",
    ):
        assert trecho in texto


def test_mensagem_longa_e_cortada_no_erro_e_mantem_o_link():
    texto = mensagem(erro="falha " * 1000)
    assert len(texto) <= orq.LIMITE_DISCORD
    assert texto.endswith("http://localhost:8080/x") and "..." in texto


def test_mensagem_junta_quebras_de_linha_do_erro():
    assert "a b c" in mensagem(erro="a\n  b\n\tc")


class RespostaFalsa:
    def __init__(self, ok=True):
        self.ok = ok

    def raise_for_status(self):
        if not self.ok:
            raise requests.HTTPError("404")


def test_enviar_discord_manda_json_com_timeout_e_sem_mencoes(monkeypatch):
    chamadas = []
    monkeypatch.setattr(
        requests, "post", lambda url, **kw: chamadas.append((url, kw)) or RespostaFalsa()
    )
    assert orq.enviar_discord("https://discord/webhook/segredo", "oi") is True
    url, kw = chamadas[0]
    assert kw["json"] == {"content": "oi", "allowed_mentions": {"parse": []}}
    assert kw["timeout"] > 0


def test_falha_no_envio_nao_levanta_e_nao_imprime_a_url(monkeypatch, capsys):
    monkeypatch.setattr(requests, "post", lambda url, **kw: RespostaFalsa(ok=False))
    assert orq.enviar_discord("https://discord/webhook/SEGREDO", "oi") is False
    saida = capsys.readouterr()
    assert "SEGREDO" not in saida.out + saida.err


def test_alertar_sem_webhook_nao_envia(monkeypatch):
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    monkeypatch.setattr(requests, "post", lambda *a, **k: pytest.fail("não devia enviar"))
    assert orq.alertar_falha({}) is False


def test_alertar_falha_monta_o_contexto_do_airflow(monkeypatch):
    class TI:
        dag_id, task_id, run_id, try_number, max_tries = "d", "t", "r1", 3, 2

    enviados = []
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord/webhook/x")
    monkeypatch.setattr(orq, "enviar_discord", lambda w, texto: enviados.append(texto) or True)
    assert orq.alertar_falha({"task_instance": TI(), "exception": ValueError("boom")}) is True
    assert "tentativa 3 de 3" in enviados[0] and "boom" in enviados[0]
    assert "/dags/d/runs/r1/tasks/t" in enviados[0]


# ---- Sprint 4, passo 8: parâmetros da execução, seleção e XCom da DAG ---------------------------
from datetime import UTC, datetime  # noqa: E402


def utc(*args):
    return datetime(*args, tzinfo=UTC)


def parametros(**kw):
    base = {
        "data_interval_end": utc(2026, 10, 7, 21),
        "logical_date": None,
        "run_after": utc(2026, 10, 7, 21, 0, 3),
        "params": {"desde": None, "ate": None, "execucao_completa": False},
        "conf": {},
        "run_id": "scheduled__2026-10-07T21:00:00+00:00",
    }
    return orq.parametros_da_execucao(**{**base, **kw})


def test_data_de_referencia_prefere_o_fim_do_intervalo_depois_logical_date_depois_run_after():
    assert (
        orq.data_referencia(utc(2026, 10, 7, 21), utc(2026, 10, 6, 21), utc(2026, 10, 9))
        == "2026-10-07"
    )
    assert orq.data_referencia(None, utc(2026, 10, 6, 21), utc(2026, 10, 9)) == "2026-10-06"
    assert orq.data_referencia(None, None, utc(2026, 10, 9, 3)) == "2026-10-09"
    with pytest.raises(ValueError):
        orq.data_referencia(None, None, None)


def test_a_data_de_referencia_e_sempre_em_utc_mesmo_com_outro_fuso():
    from datetime import timedelta, timezone

    brasilia = timezone(timedelta(hours=-3))
    assert orq.data_referencia(datetime(2026, 10, 7, 23, 30, tzinfo=brasilia)) == "2026-10-08"


def test_execucao_agendada_e_modo_janela_com_a_data_do_fim_do_intervalo():
    p = parametros()
    assert p["modo"] == "janela" and p["referencia"] == "2026-10-07"
    assert p["argumentos_ons"] == "--data-referencia 2026-10-07"
    assert p["completa"] is False and p["desde"] == p["ate"] == ""


def test_execucao_manual_sem_intervalo_usa_o_run_after_e_nao_o_relogio():
    p = parametros(data_interval_end=None, logical_date=None, run_after=utc(2026, 10, 9, 1, 2))
    assert p["referencia"] == "2026-10-09"
    # a mesma execução reexecutada (clear) dá a mesma janela: nada depende de "agora"
    assert (
        parametros(data_interval_end=None, logical_date=None, run_after=utc(2026, 10, 9, 1, 2)) == p
    )


def test_conf_de_backfill_vira_desde_ate_e_vence_os_params():
    p = parametros(conf={"desde": "2026-07", "ate": "2026-08"})
    assert p["modo"] == "backfill" and p["argumentos_ons"] == "--desde 2026-07 --ate 2026-08"
    q = parametros(
        params={"desde": "2025-01", "ate": "2025-03"}, conf={"desde": "2026-07", "ate": "2026-08"}
    )
    assert q["desde"] == "2026-07"  # conf > params
    r = parametros(params={"desde": "2025-01", "ate": "2025-03"})
    assert r["modo"] == "backfill" and r["ate"] == "2025-03"  # params do formulário também valem


@pytest.mark.parametrize(
    "conf",
    [
        {"desde": "2026-07"},  # só um dos dois
        {"ate": "2026-08"},
        {"desde": "2026-08", "ate": "2026-07"},  # invertido
        {"desde": "2026-7", "ate": "2026-08"},  # formato
        {"desde": "2026-13", "ate": "2026-14"},
        {"desde": "2026-07; rm -rf /", "ate": "2026-08"},  # a conf vira linha de comando: validar
        {"desde": "2026-07", "ate": "$(whoami)"},
    ],
)
def test_conf_invalida_ou_perigosa_e_recusada_antes_de_virar_comando(conf):
    with pytest.raises(ValueError):
        parametros(conf=conf)


def test_strings_vazias_na_conf_contam_como_ausentes():
    assert parametros(conf={"desde": "", "ate": ""})["modo"] == "janela"
    assert parametros(params={"desde": None, "ate": ""})["modo"] == "janela"


def test_execucao_completa_aceita_booleano_e_texto():
    for valor in (True, "true", "True", "1"):
        assert parametros(conf={"execucao_completa": valor})["completa"] is True
    for valor in (False, "false", "0", ""):
        assert parametros(conf={"execucao_completa": valor})["completa"] is False


def test_arquivo_de_vars_e_por_execucao_e_com_nome_seguro():
    a = parametros(run_id="scheduled__2026-10-07T21:00:00+00:00")["arquivo_vars"]
    b = parametros(run_id="manual__2026-10-07T22:12:05.158514+00:00")["arquivo_vars"]
    assert a != b and a.startswith("data/estado/ons_vars_") and a.endswith(".json")
    for nome in (a, b):
        assert not set(nome.removeprefix("data/estado/").removesuffix(".json")) & set(":+ /\\;$()")
    assert (
        parametros(run_id="x; rm -rf /")["arquivo_vars"] == "data/estado/ons_vars_x__rm_-rf__.json"
    )


def test_selecao_da_execucao_normal_e_por_fonte_e_completa_sem_select():
    assert orq.selecao_da_execucao() == {
        "run": "--select source:raw.ons_curva_carga+",
        "test": "--select source:raw.ons_curva_carga+ teste_alerta_falha_proposital",
        "fontes": "ons",
    }
    inmet = orq.selecao_da_execucao(inmet_novo=True)
    assert "source:raw.inmet_estacoes_horario+" in inmet["run"] and inmet["fontes"] == "ons+inmet"
    ambas = orq.selecao_da_execucao(ccee_novo=True, inmet_novo=True)
    assert ambas["fontes"] == "ons+inmet+ccee" and ambas["run"].count("source:") == 5
    assert ambas["test"].endswith("teste_alerta_falha_proposital")
    completa = orq.selecao_da_execucao(ccee_novo=True, completa=True)
    assert completa["run"] == "" and completa["test"] == ""  # sem --select: o dbt roda tudo


class TiFalso:
    def __init__(self):
        self.enviados = {}

    def xcom_push(self, key, value):
        self.enviados[key] = value


def test_checar_arquivo_novo_grava_o_resultado_no_xcom_e_devolve_o_mesmo_valor(tmp_path):
    pasta = tmp_path / "manual"
    pasta.mkdir()
    (pasta / "a.csv").write_text("x")
    estado = tmp_path / "estado.json"
    ti = TiFalso()
    assert orq.checar_arquivo_novo(pasta, "*.csv", estado, ti) is True  # nunca carregado
    assert ti.enviados == {"novo": True}
    orq.registrar_estado(pasta, "*.csv", estado)
    ti2 = TiFalso()
    assert orq.checar_arquivo_novo(pasta, "*.csv", estado, ti2) is False  # nada mudou
    assert ti2.enviados == {"novo": False}


def test_enviar_discord_registra_o_sucesso_sem_a_url(monkeypatch, capsys):
    class Resposta:
        def raise_for_status(self):
            pass

    monkeypatch.setattr(requests, "post", lambda *a, **k: Resposta())
    assert orq.enviar_discord("https://discord/webhook/SEGREDO", "oi") is True
    saida = capsys.readouterr()
    assert "alerta no Discord enviado" in saida.err
    assert "SEGREDO" not in saida.out + saida.err
