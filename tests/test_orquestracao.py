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
