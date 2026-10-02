"""Arquivos baixados à mão (CCEE e INMET): verificação da pasta com mensagem clara.

Os portais da CCEE e do INMET não aceitam download automático (ver docs/decisoes.md). Os
arquivos ficam em data/manual/<fonte>/ e o extrator confere, antes de tocar na nuvem, se todos
estão lá, dizendo qual arquivo baixar, de onde e com que nome salvar.
"""

from pathlib import Path
from typing import Protocol


class ArquivoManual(Protocol):
    nome: str  # nome do arquivo na pasta manual
    descricao: str  # o que é (ex.: 'PLD horário, recurso "2024"')
    pagina: str  # de onde baixar


class ArquivosAusentes(Exception):
    """Faltam arquivos na pasta manual; a mensagem diz o que baixar e de onde."""


def mensagem_ausentes(ausentes: list[ArquivoManual], pasta: Path, secao_docs: str) -> str:
    linhas = [f"Faltam {len(ausentes)} arquivo(s) em {pasta}:"]
    for arq in ausentes:
        linhas += [
            f"  - {arq.nome}: {arq.descricao}",
            f"      baixe em {arq.pagina} e salve como {pasta / arq.nome}",
        ]
    linhas.append(f"Passo a passo: {secao_docs}.")
    return "\n".join(linhas)


def verificar_arquivos(pasta: Path, esperados: list[ArquivoManual], secao_docs: str) -> None:
    ausentes = [a for a in esperados if not (pasta / a.nome).is_file()]
    if ausentes:
        raise ArquivosAusentes(mensagem_ausentes(ausentes, pasta, secao_docs))
