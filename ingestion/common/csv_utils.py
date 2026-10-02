"""Padronização de colunas e montagem do CSV que vai para o BigQuery `raw`.

O Python faz só o mínimo (decisão em docs/decisoes.md): padroniza os nomes das colunas e
acrescenta colunas de controle. Tipagem e limpeza ficam no dbt. O arquivo original, sem
alteração, já foi para o GCS (bronze) antes disso.
"""

import csv
import io
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass


def padronizar_coluna(nome: str) -> str:
    """Minúsculas, sem acento, e tudo que não é letra ou dígito vira `_`.

    Ex.: 'TEMPERATURA DO AR - BULBO SECO, HORARIA (°C)' -> 'temperatura_do_ar_bulbo_seco_horaria_c'.
    """
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFKD", nome) if not unicodedata.combining(c)
    )
    padrao = re.sub(r"[^a-z0-9]+", "_", sem_acento.lower()).strip("_")
    if not padrao:
        raise ValueError(f"Nome de coluna vazio depois de padronizar: {nome!r}")
    if padrao[0].isdigit():  # o BigQuery não aceita nome começando com dígito
        padrao = f"c_{padrao}"
    return padrao


def padronizar_colunas(nomes: Sequence[str]) -> list[str]:
    """Padroniza todos os nomes e recusa colisões (duas colunas viram o mesmo nome)."""
    padronizados = [padronizar_coluna(n) for n in nomes]
    repetidos = sorted({n for n in padronizados if padronizados.count(n) > 1})
    if repetidos:
        raise ValueError(f"Colunas duplicadas depois de padronizar: {repetidos}")
    return padronizados


@dataclass(frozen=True)
class CsvTransformado:
    conteudo: bytes  # CSV em UTF-8, separador vírgula, com cabeçalho
    colunas: list[str]  # colunas da fonte, já padronizadas (sem as extras)
    linhas: int  # linhas de dados (sem o cabeçalho)
    vazios: dict[str, int]  # campos vazios por coluna da fonte


def transformar_csv(
    conteudo: bytes,
    extras: Mapping[str, str],
    *,
    codificacao: str = "utf-8-sig",
    separador: str = ";",
) -> CsvTransformado:
    """Padroniza o cabeçalho e acrescenta as colunas `extras` (nome -> valor) a cada linha.

    Os valores originais não são alterados (campos vazios continuam vazios). A estrutura é
    validada: uma linha com número de campos diferente do cabeçalho gera erro.
    """
    leitor = csv.reader(io.StringIO(conteudo.decode(codificacao), newline=""), delimiter=separador)
    cabecalho = next(leitor, None)
    if cabecalho is None:
        raise ValueError("CSV vazio")
    colunas = padronizar_colunas(cabecalho)
    colidem = sorted(set(colunas) & set(extras))
    if colidem:
        raise ValueError(f"Colunas extras colidem com colunas da fonte: {colidem}")

    saida = io.StringIO()
    escritor = csv.writer(saida, lineterminator="\n")
    escritor.writerow([*colunas, *extras])
    vazios = dict.fromkeys(colunas, 0)
    linhas = 0
    valores_extras = list(extras.values())
    for numero, linha in enumerate(leitor, start=2):
        if not linha:  # linha em branco no fim do arquivo
            continue
        if len(linha) != len(colunas):
            raise ValueError(f"Linha {numero}: {len(linha)} campos, esperado {len(colunas)}")
        for coluna, valor in zip(colunas, linha, strict=True):
            if valor == "":
                vazios[coluna] += 1
        escritor.writerow([*linha, *valores_extras])
        linhas += 1
    return CsvTransformado(saida.getvalue().encode("utf-8"), colunas, linhas, vazios)
