"""Padronização de colunas e montagem do CSV que vai para o BigQuery `raw`.

O Python faz só o mínimo (decisão em docs/decisoes.md): padroniza os nomes das colunas e
acrescenta colunas de controle. Tipagem e limpeza ficam no dbt. O arquivo original, sem
alteração, já foi para o GCS (bronze) antes disso.
"""

import csv
import io
import re
import unicodedata
from collections.abc import Callable, Mapping, Sequence
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
    metadados: dict[str, str]  # linhas puladas antes do cabeçalho (campo -> valor), se houver


def _ler_metadados(leitor, quantidade: int) -> dict[str, str]:
    metadados: dict[str, str] = {}
    for _ in range(quantidade):
        linha = next(leitor, None)
        if linha is None:
            raise ValueError(f"CSV com menos de {quantidade} linhas de metadados")
        if linha:
            metadados[linha[0].strip().rstrip(":")] = linha[1].strip() if len(linha) > 1 else ""
    return metadados


def ler_metadados(
    conteudo: bytes, quantidade: int, *, codificacao: str = "utf-8-sig", separador: str = ";"
) -> dict[str, str]:
    """Lê só as primeiras `quantidade` linhas ('CAMPO:;valor') de um CSV com metadados."""
    leitor = csv.reader(io.StringIO(conteudo.decode(codificacao), newline=""), delimiter=separador)
    return _ler_metadados(leitor, quantidade)


def transformar_csv(
    conteudo: bytes,
    extras: Mapping[str, str],
    *,
    codificacao: str = "utf-8-sig",
    separador: str = ";",
    pular_linhas: int = 0,
    descartar_coluna_vazia_final: bool = False,
    derivadas: Mapping[str, Callable[[dict[str, str]], str]] | None = None,
) -> CsvTransformado:
    """Padroniza o cabeçalho e acrescenta as colunas `extras` (nome -> valor) a cada linha.

    - `derivadas`: colunas calculadas POR LINHA (nome -> função da linha como dicionário de colunas
      padronizadas). Entram depois dos `extras`. Ex.: `_mes_referencia` a partir de `din_instante`.

    - `pular_linhas`: linhas de metadados antes do cabeçalho (INMET: 8). Elas não vão para o
      CSV, mas voltam em `metadados` (`'CODIGO (WMO):;A701'` -> `{'CODIGO (WMO)': 'A701'}`).
    - `descartar_coluna_vazia_final`: ignora o campo vazio que sobra quando cada linha termina
      com o separador (INMET).

    Os valores originais não são alterados (campos vazios continuam vazios). A estrutura é
    validada: uma linha com número de campos diferente do cabeçalho gera erro.
    """
    leitor = csv.reader(io.StringIO(conteudo.decode(codificacao), newline=""), delimiter=separador)
    metadados = _ler_metadados(leitor, pular_linhas)
    cabecalho = next(leitor, None)
    if cabecalho is None:
        raise ValueError("CSV vazio")
    descartar = descartar_coluna_vazia_final and cabecalho[-1] == ""
    if descartar:
        cabecalho = cabecalho[:-1]
    colunas = padronizar_colunas(cabecalho)
    derivadas = derivadas or {}
    colidem = sorted(set(colunas) & (set(extras) | set(derivadas)))
    if colidem:
        raise ValueError(f"Colunas extras colidem com colunas da fonte: {colidem}")

    saida = io.StringIO()
    escritor = csv.writer(saida, lineterminator="\n")
    escritor.writerow([*colunas, *extras, *derivadas])
    vazios = dict.fromkeys(colunas, 0)
    linhas = 0
    valores_extras = list(extras.values())
    for numero, linha in enumerate(leitor, start=pular_linhas + 2):
        if not linha:  # linha em branco no fim do arquivo
            continue
        if descartar and len(linha) == len(colunas) + 1 and linha[-1] == "":
            linha = linha[:-1]
        if len(linha) != len(colunas):
            raise ValueError(f"Linha {numero}: {len(linha)} campos, esperado {len(colunas)}")
        for coluna, valor in zip(colunas, linha, strict=True):
            if valor == "":
                vazios[coluna] += 1
        if derivadas:
            registro = dict(zip(colunas, linha, strict=True))
            calculadas = [funcao(registro) for funcao in derivadas.values()]
        else:
            calculadas = []
        escritor.writerow([*linha, *valores_extras, *calculadas])
        linhas += 1
    return CsvTransformado(saida.getvalue().encode("utf-8"), colunas, linhas, vazios, metadados)
