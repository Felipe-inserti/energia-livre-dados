"""Extrator da CCEE (PLD e consumo por ramo): carga FULL, de propósito ingênua (o "antes").

    uv run python -m ingestion.ccee [--pasta data/manual/ccee] [--verificar] [--sem-consulta]

O portal da CCEE bloqueia downloads automáticos (HTTP 403, ver docs/decisoes.md), então os
arquivos são baixados à mão para data/manual/ccee/ (passo a passo em docs/fontes.md).
Este extrator lê essa pasta e, para cada arquivo:
1. sobe o CSV ORIGINAL, sem alteração, para o GCS (bronze/ccee/<conjunto>/...);
2. carrega no BigQuery (raw) com as colunas padronizadas, todas como STRING, mais
   `_arquivo_origem` e `_carregado_em`. Sem partição.

Três tabelas, porque a semântica é diferente (docs/fontes.md):
- raw.ccee_pld_horario: PLD horário, 2021 em diante (um arquivo por ano);
- raw.ccee_pld_semanal: PLD semanal por patamar de carga, 2001–2020 (um arquivo);
- raw.ccee_consumo_ramo_atividade: consumo mensal por ramo, 2024 em diante (um arquivo por ano).

O layout muda entre 2024 e 2025 (aspas, CRLF/LF, zeros à esquerda): o raw guarda os valores como
vieram; a normalização é do staging. Limitação desta versão: a carga de cada tabela não é
atômica (o primeiro arquivo trunca e os demais acrescentam).
"""

import argparse
import csv
import io
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ingestion.common import gcp, manual
from ingestion.common.config import DATASET_RAW, RAIZ, Config, carregar_config
from ingestion.common.csv_utils import CsvTransformado, transformar_csv
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

log = obter_logger("ingestion.ccee")

PASTA_PADRAO = RAIZ / "data" / "manual" / "ccee"
SECAO_DOCS = 'docs/fontes.md, seção "Download manual dos arquivos da CCEE"'
TIPOS_EXTRAS = {"_arquivo_origem": "STRING", "_carregado_em": "TIMESTAMP"}

COLUNAS_PLD = [
    "mes_referencia",
    "submercado",
    "periodo_comercializacao",
    "dia",
    "hora",
    "pld_hora",
]
COLUNAS_CONSUMO = [
    "mes_referencia",
    "ramo_atividade",
    "consumo_cl_esp_acl",
    "consumo_autop_acl",
    "consumo_ponto_conexao_cl_esp_acl",
    "consumo_ponto_conexao_autop_acl",
]


@dataclass(frozen=True)
class Conjunto:
    tabela: str  # nome da tabela no dataset raw
    pasta_bronze: str  # bronze/ccee/<pasta_bronze>/
    colunas: list[str]  # colunas esperadas (já padronizadas)
    coluna_valor: str  # coluna usada para contar vazios na validação
    pagina: str  # página do portal onde se baixa
    por_ano: bool  # um arquivo por ano (com `ano=AAAA` no bronze) ou arquivo único


PLD_HORARIO = Conjunto(
    "ccee_pld_horario",
    "pld_horario",
    COLUNAS_PLD,
    "pld_hora",
    "https://dadosabertos.ccee.org.br/dataset/pld_horario",
    por_ano=True,
)
PLD_SEMANAL = Conjunto(
    "ccee_pld_semanal",
    "pld_semanal",
    COLUNAS_PLD,
    "pld_hora",
    "https://dadosabertos.ccee.org.br/dataset/pld_horario",  # recurso "2001-2020" da mesma página
    por_ano=False,
)
CONSUMO_RAMO = Conjunto(
    "ccee_consumo_ramo_atividade",
    "consumo_ramo_atividade",
    COLUNAS_CONSUMO,
    "consumo_cl_esp_acl",
    "https://dadosabertos.ccee.org.br/dataset/consumo_ramo_atividade",
    por_ano=True,
)

CONJUNTOS = [PLD_HORARIO, PLD_SEMANAL, CONSUMO_RAMO]

ANO_INICIAL_PLD_HORARIO = 2021
ANO_INICIAL_CONSUMO = 2024
NOME_PLD_SEMANAL = "pld_historico_semanal_2001_2020.csv"
# O PLD semanal cobre 2001–2020; meses fora desse intervalo indicam arquivo errado
MES_MIN_SEMANAL, MES_MAX_SEMANAL = "200101", "202012"

CONSULTA_TIPICA = """
SELECT SAFE_CAST(hora AS INT64) AS hora,
       AVG(SAFE_CAST(pld_hora AS FLOAT64)) AS pld_medio
FROM `{tabela}`
WHERE submercado = 'SUDESTE' AND SUBSTR(mes_referencia, 1, 4) = '2024'
GROUP BY hora
ORDER BY hora
"""


@dataclass(frozen=True)
class ArquivoEsperado:
    conjunto: Conjunto
    nome: str
    ano: int | None  # None no arquivo único (PLD semanal)

    @property
    def caminho_gcs(self) -> str:
        base = f"bronze/ccee/{self.conjunto.pasta_bronze}"
        if self.conjunto.por_ano:
            return f"{base}/ano={self.ano}/{self.nome}"
        return f"{base}/{self.nome}"

    @property
    def pagina(self) -> str:
        return self.conjunto.pagina

    @property
    def descricao(self) -> str:
        if self.conjunto is PLD_SEMANAL:
            return 'PLD histórico semanal, recurso "2001-2020"'
        quem = "PLD horário" if self.conjunto is PLD_HORARIO else "consumo por ramo de atividade"
        return f'{quem}, recurso "{self.ano}"'


def nome_pld_horario(ano: int) -> str:
    return f"pld_horario_{ano}.csv"


def nome_consumo(ano: int) -> str:
    return f"consumo_ramo_atividade_{ano}.csv"


def arquivos_esperados(ano_atual: int) -> list[ArquivoEsperado]:
    """Todos os arquivos que precisam estar na pasta manual, do ano inicial até o ano atual."""
    return [
        *(
            ArquivoEsperado(PLD_HORARIO, nome_pld_horario(a), a)
            for a in range(ANO_INICIAL_PLD_HORARIO, ano_atual + 1)
        ),
        ArquivoEsperado(PLD_SEMANAL, NOME_PLD_SEMANAL, None),
        *(
            ArquivoEsperado(CONSUMO_RAMO, nome_consumo(a), a)
            for a in range(ANO_INICIAL_CONSUMO, ano_atual + 1)
        ),
    ]


def verificar_arquivos(pasta: Path, esperados: list[ArquivoEsperado]) -> None:
    """Confere se todos os arquivos estão na pasta manual (lança ArquivosAusentes se faltar)."""
    manual.verificar_arquivos(pasta, esperados, SECAO_DOCS)


def meses_do_csv(conteudo: bytes) -> set[str]:
    """Valores distintos de `mes_referencia` do CSV já transformado (vírgula, com cabeçalho)."""
    leitor = csv.DictReader(io.StringIO(conteudo.decode("utf-8"), newline=""))
    return {linha["mes_referencia"] for linha in leitor}


def validar_conteudo(arquivo: ArquivoEsperado, csv_raw: CsvTransformado) -> None:
    """Pega o erro típico de download manual: arquivo trocado, ano errado ou layout diferente."""
    if csv_raw.colunas != arquivo.conjunto.colunas:
        raise ValueError(
            f"{arquivo.nome}: colunas {csv_raw.colunas}, esperado {arquivo.conjunto.colunas}"
        )
    if csv_raw.linhas == 0:
        raise ValueError(f"{arquivo.nome}: arquivo sem linhas de dados")
    meses = meses_do_csv(csv_raw.conteudo)
    if arquivo.conjunto is PLD_SEMANAL:
        fora = sorted(m for m in meses if not MES_MIN_SEMANAL <= m <= MES_MAX_SEMANAL)
        if fora:
            raise ValueError(
                f"{arquivo.nome}: meses fora de {MES_MIN_SEMANAL}–{MES_MAX_SEMANAL}: {fora[:3]}"
                " (é o arquivo do recurso '2001-2020'?)"
            )
        return
    fora = sorted(m for m in meses if not m.startswith(str(arquivo.ano)))
    if fora:
        raise ValueError(
            f"{arquivo.nome}: contém meses de outro ano ({fora[:3]}); esperado só {arquivo.ano}"
            " (o arquivo é do recurso certo?)"
        )


def carregar_arquivos(pasta: Path, esperados: list[ArquivoEsperado], config: Config) -> Medicoes:
    storage_cli = gcp.cliente_storage(config)
    bq_cli = gcp.cliente_bigquery(config)
    carregado_em = datetime.now(UTC).isoformat(timespec="seconds")
    medicoes = Medicoes()
    carregadores: dict[str, Carregador] = {}  # um por tabela: o primeiro job trunca

    for arq in esperados:
        caminho_local = pasta / arq.nome
        t0 = time.perf_counter()
        original = caminho_local.read_bytes()
        medicoes.t_origem += time.perf_counter() - t0
        info = caminho_local.stat()
        log.info(
            "%s: %.2f MB, modificado em %s",
            arq.nome,
            info.st_size / 1e6,
            datetime.fromtimestamp(info.st_mtime, UTC).isoformat(timespec="seconds"),
        )

        # valida o conteúdo antes de gravar qualquer coisa na nuvem
        extras = {"_arquivo_origem": arq.caminho_gcs, "_carregado_em": carregado_em}
        csv_raw = transformar_csv(original, extras)
        validar_conteudo(arq, csv_raw)

        t0 = time.perf_counter()
        origem = gcp.enviar_para_gcs(storage_cli, config.bucket, arq.caminho_gcs, original)
        medicoes.t_gcs += time.perf_counter() - t0

        tabela = arq.conjunto.tabela
        if tabela not in carregadores:
            carregadores[tabela] = Carregador(
                bq_cli,
                config.tabela(DATASET_RAW, tabela),
                gcp.montar_esquema(arq.conjunto.colunas, TIPOS_EXTRAS),
                medicoes,
            )
        linhas = carregadores[tabela].carregar(csv_raw.conteudo, csv_raw.linhas, arq.nome)

        medicoes.registrar_arquivo(arq.nome, len(original), linhas)
        medicoes.registrar_esperado(
            tabela, (arq.caminho_gcs,), csv_raw.linhas, csv_raw.vazios[arq.conjunto.coluna_valor]
        )
        log.info("%s: %d linhas -> %s (raw.%s)", arq.nome, linhas, origem, tabela)
    return medicoes


def main(argv: list[str] | None = None) -> int:
    ano_atual = datetime.now(UTC).year
    parser = argparse.ArgumentParser(description="Carga full da CCEE (arquivos baixados à mão)")
    parser.add_argument("--pasta", type=Path, default=PASTA_PADRAO)
    parser.add_argument(
        "--verificar", action="store_true", help="só confere se os arquivos estão na pasta"
    )
    parser.add_argument(
        "--sem-consulta", action="store_true", help="não valida o raw nem mede a consulta típica"
    )
    args = parser.parse_args(argv)

    esperados = arquivos_esperados(ano_atual)
    try:
        verificar_arquivos(args.pasta, esperados)
    except ArquivosAusentes as erro:
        print(erro, file=sys.stderr)
        return 2
    if args.verificar:
        print(f"ok: os {len(esperados)} arquivos esperados estão em {args.pasta}")
        return 0

    config = carregar_config()
    log.info(
        "carga full da CCEE: %d arquivos de %s, bucket %s",
        len(esperados),
        args.pasta,
        config.bucket,
    )
    medicoes = carregar_arquivos(args.pasta, esperados, config)
    consulta = None
    if not args.sem_consulta:
        conjuntos = [ConjuntoValidacao(c.tabela, c.coluna_valor) for c in CONJUNTOS]
        problemas = validar_raw(config, medicoes, conjuntos)
        if problemas:
            for problema in problemas:
                log.error("validação: %s", problema)
            return 1
        log.info("validação do raw: ok (linhas e vazios batem com os CSVs)")
        sql = CONSULTA_TIPICA.format(tabela=config.tabela(DATASET_RAW, PLD_HORARIO.tabela))
        consulta = medir_consulta_tipica(config, sql)
    imprimir_resumo(
        "da carga full da CCEE",
        medicoes,
        consulta,
        rotulo_volume="volume dos arquivos carregados (lidos da pasta manual, sem download)",
        rotulo_origem="leitura",
        descricao_consulta="PLD médio por hora do SUDESTE em 2024",
        listar_arquivos=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
