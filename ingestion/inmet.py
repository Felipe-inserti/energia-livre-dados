"""Extrator do INMET (estações automáticas): carga FULL, de propósito ingênua (o "antes").

    uv run python -m ingestion.inmet [--pasta data/manual/inmet] [--verificar] [--sem-consulta]

O portal do INMET não responde a downloads automáticos na nossa rede (ver docs/fontes.md), então
os ZIPs anuais são baixados à mão para data/manual/inmet/ (passo a passo em docs/fontes.md).
Para cada ZIP (2021 até o ano atual):
1. sobe o ZIP ORIGINAL, sem alteração, para bronze/inmet/ano=AAAA/AAAA.zip;
2. carrega no BigQuery (raw.inmet_estacoes_horario) só as 37 estações do SE/CO selecionadas
   (critério: >= 95% de horas válidas de temperatura em cada ano de 2021 a 2025), com as 19
   colunas padronizadas, os metadados da estação e `_arquivo_origem` e `_carregado_em`.
   Todas as colunas como STRING (inclusive o decimal com vírgula), sem partição.

A lista de estações é regenerável a partir do bronze com scripts/inmet_cmp.py (ver
docs/decisoes.md). Os ZIPs guardam todas as ~570 estações; o raw guarda só as selecionadas.
"""

import argparse
import sys
import time
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ingestion.common import gcp, manual
from ingestion.common.config import DATASET_RAW, RAIZ, Config, carregar_config
from ingestion.common.csv_utils import CsvTransformado, ler_metadados, transformar_csv
from ingestion.common.logs import obter_logger
from ingestion.common.manual import ArquivosAusentes
from ingestion.common.raw import (
    Carregador,
    ConjuntoValidacao,
    Medicoes,
    imprimir_resumo,
    medir_consulta_tipica,
    validar_raw,
)

log = obter_logger("ingestion.inmet")

ANO_INICIAL = 2021
PASTA_PADRAO = RAIZ / "data" / "manual" / "inmet"
PAGINA = "https://portal.inmet.gov.br/dadoshistoricos"
URL_ZIP = "https://portal.inmet.gov.br/uploads/dadoshistoricos/{ano}.zip"
SECAO_DOCS = 'docs/fontes.md, seção "Download manual dos ZIPs do INMET"'

NOME_TABELA = "inmet_estacoes_horario"
LINHAS_METADADOS = 8
BLOCO_BYTES = 40 * 1024 * 1024  # tamanho máximo de cada carga (o upload local tem limite)
COLUNA_TEMPERATURA = "temperatura_do_ar_bulbo_seco_horaria_c"

COLUNAS_ESPERADAS = [
    "data",
    "hora_utc",
    "precipitacao_total_horario_mm",
    "pressao_atmosferica_ao_nivel_da_estacao_horaria_mb",
    "pressao_atmosferica_max_na_hora_ant_aut_mb",
    "pressao_atmosferica_min_na_hora_ant_aut_mb",
    "radiacao_global_kj_m2",
    "temperatura_do_ar_bulbo_seco_horaria_c",
    "temperatura_do_ponto_de_orvalho_c",
    "temperatura_maxima_na_hora_ant_aut_c",
    "temperatura_minima_na_hora_ant_aut_c",
    "temperatura_orvalho_max_na_hora_ant_aut_c",
    "temperatura_orvalho_min_na_hora_ant_aut_c",
    "umidade_rel_max_na_hora_ant_aut",
    "umidade_rel_min_na_hora_ant_aut",
    "umidade_relativa_do_ar_horaria",
    "vento_direcao_horaria_gr_gr",
    "vento_rajada_maxima_m_s",
    "vento_velocidade_horaria_m_s",
]
TIPOS_EXTRAS = {
    "estacao_codigo": "STRING",
    "estacao_uf": "STRING",
    "estacao_nome": "STRING",
    "estacao_latitude": "STRING",
    "estacao_longitude": "STRING",
    "_arquivo_origem": "STRING",
    "_carregado_em": "TIMESTAMP",
}

# código -> (UF, nome). 37 estações do SE/CO com >= 95% de horas válidas de temperatura em cada
# ano de 2021 a 2025 (docs/fontes.md). MT não tem nenhuma; a lista caiu de 72 (só 2021 e 2024)
# para 37 ao incluir os 5 anos. Para regenerar: scripts/inmet_cmp.py 2021 2022 2023 2024 2025.
ESTACOES = {
    "A001": ("DF", "BRASILIA"),
    "A042": ("DF", "BRAZLANDIA"),
    "A046": ("DF", "GAMA (PONTE ALTA)"),
    "A047": ("DF", "PARANOA (COOPA-DF)"),
    "A617": ("ES", "ALEGRE"),
    "A614": ("ES", "LINHARES"),
    "A616": ("ES", "SAO MATEUS"),
    "A633": ("ES", "VENDA NOVA DO IMIGRANTE"),
    "A034": ("GO", "CATALAO"),
    "A036": ("GO", "CRISTALINA"),
    "A037": ("GO", "SILVANIA"),
    "A508": ("MG", "ALMENARA"),
    "A502": ("MG", "BARBACENA"),
    "A521": ("MG", "BELO HORIZONTE (PAMPULHA)"),
    "F501": ("MG", "BELO HORIZONTE - CERCADINHO"),
    "A554": ("MG", "CARATINGA"),
    "A520": ("MG", "CONCEICAO DAS ALAGOAS"),
    "A540": ("MG", "MANTENA"),
    "A531": ("MG", "MARIA DA FE"),
    "A539": ("MG", "MOCAMBINHO"),
    "A509": ("MG", "MONTE VERDE"),
    "A506": ("MG", "MONTES CLAROS"),
    "A570": ("MG", "OLIVEIRA"),
    "A516": ("MG", "PASSOS"),
    "A507": ("MG", "UBERLANDIA"),
    "A756": ("MS", "AGUA CLARA"),
    "A704": ("MS", "TRES LAGOAS"),
    "A607": ("RJ", "CAMPOS DOS GOYTACAZES"),
    "A624": ("RJ", "NOVA FRIBURGO - SALINAS"),
    "A626": ("RJ", "RIO CLARO"),
    "A621": ("RJ", "RIO DE JANEIRO - VILA MILITAR"),
    "A601": ("RJ", "SEROPEDICA-ECOLOGIA AGRICOLA"),
    "A659": ("RJ", "SILVA JARDIM"),
    "A763": ("SP", "MARILIA"),
    "A747": ("SP", "PRADOPOLIS"),
    "A701": ("SP", "SAO PAULO - MIRANTE"),
    "A770": ("SP", "SAO SIMAO"),
}

# "Temperatura média por hora em SP em 2024". A hora é UTC (o INMET publica em UTC), o decimal
# vem com vírgula e as colunas são STRING, então precisa de REPLACE e SAFE_CAST.
CONSULTA_TIPICA = """
SELECT SAFE_CAST(SUBSTR(hora_utc, 1, 2) AS INT64) AS hora_utc,
       AVG(SAFE_CAST(REPLACE(temperatura_do_ar_bulbo_seco_horaria_c, ',', '.') AS FLOAT64))
         AS temp_media
FROM `{tabela}`
WHERE estacao_uf = 'SP' AND SUBSTR(`data`, 1, 4) = '2024'
GROUP BY hora_utc
ORDER BY hora_utc
"""


@dataclass(frozen=True)
class ZipEsperado:
    ano: int

    @property
    def nome(self) -> str:
        return f"{self.ano}.zip"

    @property
    def caminho_gcs(self) -> str:
        return f"bronze/inmet/ano={self.ano}/{self.nome}"

    @property
    def descricao(self) -> str:
        return f'dados históricos de {self.ano} (estações automáticas), arquivo "{self.ano}"'

    @property
    def pagina(self) -> str:
        return f"{PAGINA} (link direto: {URL_ZIP.format(ano=self.ano)})"


def zips_esperados(ano_atual: int) -> list[ZipEsperado]:
    return [ZipEsperado(ano) for ano in range(ANO_INICIAL, ano_atual + 1)]


def verificar_arquivos(pasta: Path, esperados: list[ZipEsperado]) -> None:
    """Confere se todos os ZIPs estão na pasta manual (lança ArquivosAusentes se faltar)."""
    manual.verificar_arquivos(pasta, esperados, SECAO_DOCS)


def codigo_da_estacao(nome_membro: str) -> str | None:
    """'2025/INMET_SE_SP_A701_SAO PAULO - MIRANTE_01-01-2025_A_31-12-2025.CSV' -> 'A701'.

    Usa só o nome-base, porque alguns ZIPs (o de 2025) guardam os arquivos numa pasta.
    """
    partes = nome_membro.rsplit("/", 1)[-1].split("_")
    if len(partes) < 5 or partes[0] != "INMET" or not nome_membro.upper().endswith(".CSV"):
        return None
    return partes[3]


def indexar_estacoes(nomes: list[str]) -> dict[str, str]:
    """Código da estação -> nome do arquivo dentro do ZIP."""
    indice = {}
    for nome in nomes:
        codigo = codigo_da_estacao(nome)
        if codigo:
            indice[codigo] = nome
    return indice


def validar_estacao(codigo: str, ano: int, meta: dict[str, str], csv_raw: CsvTransformado) -> None:
    """Confere a estação (código e UF contra os metadados), o layout e o ano dos dados."""
    if meta.get("CODIGO (WMO)") != codigo:
        raise ValueError(
            f"{codigo}: o código nos metadados é {meta.get('CODIGO (WMO)')!r}, "
            "diferente do nome do arquivo"
        )
    uf_esperada = ESTACOES[codigo][0]
    if meta.get("UF") != uf_esperada:
        raise ValueError(f"{codigo}: UF {meta.get('UF')!r} nos metadados, esperado {uf_esperada!r}")
    if csv_raw.colunas != COLUNAS_ESPERADAS:
        raise ValueError(f"{codigo}: layout inesperado: {csv_raw.colunas}")
    if csv_raw.linhas == 0:
        raise ValueError(f"{codigo}: arquivo sem linhas de dados")
    linhas = csv_raw.conteudo.decode("utf-8").splitlines()
    primeira, ultima = linhas[1], linhas[-1]
    if not (primeira.startswith(f"{ano}/") and ultima.startswith(f"{ano}/")):
        raise ValueError(f"{codigo}: as datas não são de {ano} (o ZIP é do ano certo?)")


def separar_cabecalho(conteudo: bytes) -> tuple[bytes, bytes]:
    """Divide um CSV transformado em (cabeçalho com a quebra de linha, corpo)."""
    cabecalho, quebra, corpo = conteudo.partition(b"\n")
    return cabecalho + quebra, corpo


class Bloco:
    """Acumula o corpo de várias estações para carregá-las num único job do BigQuery."""

    def __init__(self, cabecalho: bytes):
        self.cabecalho = cabecalho
        self.corpos: list[bytes] = []
        self.tamanho = 0
        self.linhas = 0

    def adicionar(self, corpo: bytes, linhas: int) -> None:
        self.corpos.append(corpo)
        self.tamanho += len(corpo)
        self.linhas += linhas

    @property
    def cheio(self) -> bool:
        return self.tamanho >= BLOCO_BYTES

    def conteudo(self) -> bytes:
        return self.cabecalho + b"".join(self.corpos)


def carregar_zips(pasta: Path, esperados: list[ZipEsperado], config: Config) -> Medicoes:
    storage_cli = gcp.cliente_storage(config)
    medicoes = Medicoes()
    carregador = Carregador(
        gcp.cliente_bigquery(config),
        config.tabela(DATASET_RAW, NOME_TABELA),
        gcp.montar_esquema(COLUNAS_ESPERADAS, TIPOS_EXTRAS),
        medicoes,
    )
    carregado_em = datetime.now(UTC).isoformat(timespec="seconds")

    for arq in esperados:
        caminho_local = pasta / arq.nome
        tamanho = caminho_local.stat().st_size
        log.info(
            "%s: %.1f MB, modificado em %s",
            arq.nome,
            tamanho / 1e6,
            datetime.fromtimestamp(caminho_local.stat().st_mtime, UTC).isoformat(
                timespec="seconds"
            ),
        )

        with zipfile.ZipFile(caminho_local) as zip_:
            # confere o ZIP antes de gravar qualquer coisa na nuvem (download manual pode truncar)
            corrompido = zip_.testzip()
            if corrompido:
                raise ValueError(
                    f"{arq.nome}: ZIP corrompido (primeiro arquivo ruim: {corrompido})"
                )
            indice = indexar_estacoes(zip_.namelist())
            faltando = sorted(set(ESTACOES) - set(indice))
            if faltando:
                raise ValueError(f"{arq.nome}: faltam as estações {faltando}")

            # bronze: o ZIP original, sem alteração
            t0 = time.perf_counter()
            origem = gcp.enviar_arquivo_para_gcs(
                storage_cli, config.bucket, arq.caminho_gcs, caminho_local, tipo="application/zip"
            )
            medicoes.t_gcs += time.perf_counter() - t0

            # raw: só as estações selecionadas, em blocos
            t0 = time.perf_counter()
            bloco: Bloco | None = None
            linhas_zip = 0
            for codigo in sorted(ESTACOES):
                dados = zip_.read(indice[codigo])
                meta = ler_metadados(dados, LINHAS_METADADOS, codificacao="latin-1")
                extras = {
                    "estacao_codigo": codigo,
                    "estacao_uf": meta.get("UF", ""),
                    "estacao_nome": meta.get("ESTACAO", ""),
                    "estacao_latitude": meta.get("LATITUDE", ""),
                    "estacao_longitude": meta.get("LONGITUDE", ""),
                    "_arquivo_origem": arq.caminho_gcs,
                    "_carregado_em": carregado_em,
                }
                csv_raw = transformar_csv(
                    dados,
                    extras,
                    codificacao="latin-1",
                    pular_linhas=LINHAS_METADADOS,
                    descartar_coluna_vazia_final=True,
                )
                validar_estacao(codigo, arq.ano, meta, csv_raw)
                cabecalho, corpo = separar_cabecalho(csv_raw.conteudo)
                bloco = bloco or Bloco(cabecalho)
                bloco.adicionar(corpo, csv_raw.linhas)
                medicoes.registrar_esperado(
                    NOME_TABELA,
                    (arq.caminho_gcs, codigo),
                    csv_raw.linhas,
                    csv_raw.vazios[COLUNA_TEMPERATURA],
                )
                linhas_zip += csv_raw.linhas
                if bloco.cheio:
                    medicoes.t_origem += time.perf_counter() - t0
                    carregador.carregar(bloco.conteudo(), bloco.linhas, f"{arq.nome} (bloco)")
                    bloco, t0 = None, time.perf_counter()
            medicoes.t_origem += time.perf_counter() - t0
            if bloco is not None:
                carregador.carregar(bloco.conteudo(), bloco.linhas, f"{arq.nome} (bloco final)")

        medicoes.registrar_arquivo(arq.nome, tamanho, linhas_zip)
        log.info(
            "%s: %d estações, %d linhas -> %s (raw.%s)",
            arq.nome,
            len(ESTACOES),
            linhas_zip,
            origem,
            NOME_TABELA,
        )
    return medicoes


def main(argv: list[str] | None = None) -> int:
    ano_atual = datetime.now(UTC).year
    parser = argparse.ArgumentParser(description="Carga full do INMET (ZIPs baixados à mão)")
    parser.add_argument("--pasta", type=Path, default=PASTA_PADRAO)
    parser.add_argument(
        "--verificar", action="store_true", help="só confere se os ZIPs estão na pasta"
    )
    parser.add_argument(
        "--sem-consulta", action="store_true", help="não valida o raw nem mede a consulta típica"
    )
    args = parser.parse_args(argv)

    esperados = zips_esperados(ano_atual)
    try:
        verificar_arquivos(args.pasta, esperados)
    except ArquivosAusentes as erro:
        print(erro, file=sys.stderr)
        return 2
    if args.verificar:
        print(f"ok: os {len(esperados)} ZIPs esperados estão em {args.pasta}")
        return 0

    config = carregar_config()
    log.info(
        "carga full do INMET: %d ZIPs de %s, %d estações, bucket %s",
        len(esperados),
        args.pasta,
        len(ESTACOES),
        config.bucket,
    )
    medicoes = carregar_zips(args.pasta, esperados, config)
    consulta = None
    if not args.sem_consulta:
        conjunto = ConjuntoValidacao(
            NOME_TABELA, COLUNA_TEMPERATURA, colunas_chave=("_arquivo_origem", "estacao_codigo")
        )
        problemas = validar_raw(config, medicoes, [conjunto])
        if problemas:
            for problema in problemas:
                log.error("validação: %s", problema)
            return 1
        log.info("validação do raw: ok (linhas e vazios batem com os CSVs, por ZIP e estação)")
        sql = CONSULTA_TIPICA.format(tabela=config.tabela(DATASET_RAW, NOME_TABELA))
        consulta = medir_consulta_tipica(config, sql)
    imprimir_resumo(
        "da carga full do INMET",
        medicoes,
        consulta,
        rotulo_volume="volume dos ZIPs carregados (lidos da pasta manual, sem download)",
        rotulo_origem="leitura e transformação",
        descricao_consulta="temperatura média por hora (UTC) em SP em 2024",
        detalhe_arquivos=f" (ZIPs de {esperados[0].ano} a {esperados[-1].ano}, "
        f"{len(ESTACOES)} estações cada)",
        listar_arquivos=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
