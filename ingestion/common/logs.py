"""Logging simples: stdout, hora em UTC, nível e nome do módulo.

O arquivo se chama `logs` (e não `logging`) para não esconder o módulo da biblioteca padrão.
"""

import logging
import sys
import time


def obter_logger(nome: str) -> logging.Logger:
    logger = logging.getLogger(nome)
    if not logger.handlers:  # evita duplicar mensagens se for chamado mais de uma vez
        handler = logging.StreamHandler(sys.stdout)
        formato = logging.Formatter("%(asctime)sZ %(levelname)s %(name)s: %(message)s")
        formato.converter = time.gmtime
        handler.setFormatter(formato)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger
