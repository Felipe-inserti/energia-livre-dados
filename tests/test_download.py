import pytest
import requests

from ingestion.common.download import (
    ArquivoNaoEncontrado,
    ErroDownload,
    baixar_bytes,
    deve_repetir,
)


class Resposta:
    def __init__(self, status, conteudo=b""):
        self.status_code = status
        self.content = conteudo


class Roteiro:
    """Devolve, em ordem, respostas ou exceções; conta as chamadas."""

    def __init__(self, *eventos):
        self.eventos = list(eventos)
        self.chamadas = 0

    def __call__(self, url, timeout):
        self.chamadas += 1
        evento = self.eventos.pop(0)
        if isinstance(evento, Exception):
            raise evento
        return evento


def baixar(roteiro, **kwargs):
    esperas = []
    resultado = baixar_bytes("http://x/y.csv", requisitar=roteiro, dormir=esperas.append, **kwargs)
    return resultado, esperas


@pytest.mark.parametrize("status", [429, 500, 502, 503, 599])
def test_deve_repetir(status):
    assert deve_repetir(status)


@pytest.mark.parametrize("status", [200, 400, 401, 403, 404])
def test_nao_deve_repetir(status):
    assert not deve_repetir(status)


def test_sucesso_na_primeira_tentativa():
    roteiro = Roteiro(Resposta(200, b"dados"))
    conteudo, esperas = baixar(roteiro)
    assert conteudo == b"dados" and roteiro.chamadas == 1 and esperas == []


def test_repete_em_429_e_5xx_com_espera_exponencial():
    roteiro = Roteiro(Resposta(429), Resposta(503), Resposta(200, b"ok"))
    conteudo, esperas = baixar(roteiro, espera_base=2.0)
    assert conteudo == b"ok" and roteiro.chamadas == 3
    assert esperas == [2.0, 4.0]


def test_repete_em_timeout_e_erro_de_conexao():
    roteiro = Roteiro(requests.Timeout(), requests.ConnectionError(), Resposta(200, b"ok"))
    conteudo, _ = baixar(roteiro)
    assert conteudo == b"ok" and roteiro.chamadas == 3


def test_404_nao_repete():
    roteiro = Roteiro(Resposta(404))
    with pytest.raises(ArquivoNaoEncontrado):
        baixar(roteiro)
    assert roteiro.chamadas == 1


def test_outro_4xx_nao_repete():
    roteiro = Roteiro(Resposta(403))
    with pytest.raises(ErroDownload):
        baixar(roteiro)
    assert roteiro.chamadas == 1


def test_esgota_as_tentativas():
    roteiro = Roteiro(Resposta(500), Resposta(500), Resposta(500))
    with pytest.raises(ErroDownload, match="3 tentativas"):
        baixar(roteiro, tentativas=3)
    assert roteiro.chamadas == 3


# ---- HEAD/ETag (Sprint 4) ----
from ingestion.common.download import buscar_etag  # noqa: E402


class RespostaHead:
    def __init__(self, status, etag=None):
        self.status_code = status
        self.headers = {"ETag": etag} if etag else {}


def head(*eventos, **kwargs):
    roteiro = Roteiro(*eventos)
    return buscar_etag(
        "http://x/y.csv", requisitar=roteiro, dormir=lambda s: None, **kwargs
    ), roteiro


def test_etag_sem_as_aspas_e_uma_chamada_so():
    etag, roteiro = head(RespostaHead(200, '"abc123"'))
    assert etag == "abc123" and roteiro.chamadas == 1


def test_sem_etag_devolve_none():
    assert head(RespostaHead(200))[0] is None


def test_head_repete_em_5xx_e_nao_repete_404():
    etag, roteiro = head(RespostaHead(503), RespostaHead(200, '"x"'))
    assert etag == "x" and roteiro.chamadas == 2
    with pytest.raises(ArquivoNaoEncontrado):
        head(RespostaHead(404))
