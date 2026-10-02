"""Download com retry simples.

O arquivo se chama `download` (e não `http`) para não esconder o módulo `http` da biblioteca
padrão.

Repete (até `tentativas`, com espera exponencial) só quando vale a pena: erro de conexão,
timeout, 429 (muitas requisições) e 5xx. Um 404 ou outro 4xx não adianta repetir.
"""

import time
from collections.abc import Callable

import requests

from ingestion.common.logs import obter_logger

log = obter_logger(__name__)

TIMEOUT_PADRAO = (10, 120)  # (conexão, leitura) em segundos
STATUS_COM_RETRY = frozenset({429, *range(500, 600)})


class ErroDownload(Exception):
    """Falha de download depois de esgotar as tentativas, ou erro que não se repete."""


class ArquivoNaoEncontrado(ErroDownload):
    """HTTP 404: o arquivo não existe (ex.: o ano corrente ainda não foi publicado)."""


def deve_repetir(status: int) -> bool:
    return status in STATUS_COM_RETRY


def baixar_bytes(
    url: str,
    *,
    tentativas: int = 3,
    espera_base: float = 2.0,
    timeout: tuple[float, float] = TIMEOUT_PADRAO,
    requisitar: Callable[..., requests.Response] = requests.get,
    dormir: Callable[[float], None] = time.sleep,
) -> bytes:
    """Baixa `url` e devolve o conteúdo exatamente como veio."""
    ultimo_erro: Exception | None = None
    for tentativa in range(1, tentativas + 1):
        try:
            resposta = requisitar(url, timeout=timeout)
        except (requests.ConnectionError, requests.Timeout) as erro:
            ultimo_erro = erro
            motivo = type(erro).__name__
        else:
            if resposta.status_code == 404:
                raise ArquivoNaoEncontrado(f"404 em {url}")
            if resposta.status_code < 400:
                return resposta.content
            if not deve_repetir(resposta.status_code):
                raise ErroDownload(f"HTTP {resposta.status_code} em {url} (não se repete)")
            ultimo_erro = ErroDownload(f"HTTP {resposta.status_code} em {url}")
            motivo = f"HTTP {resposta.status_code}"
        if tentativa < tentativas:
            espera = espera_base * 2 ** (tentativa - 1)
            log.warning(
                "falha (%s) em %s; tentativa %d/%d, nova tentativa em %.0fs",
                motivo,
                url,
                tentativa,
                tentativas,
                espera,
            )
            dormir(espera)
    raise ErroDownload(f"{tentativas} tentativas esgotadas para {url}") from ultimo_erro
