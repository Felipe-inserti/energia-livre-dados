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
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from ingestion.common import gcp
from ingestion.common.config import DATASET_RAW, RAIZ, Config, carregar_config
from ingestion.common.csv_utils import CsvTransformado, transformar_csv
from ingestion.common.logs import obter_logger

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

CONSULTA_VALIDACAO = """
SELECT _arquivo_origem,
       COUNT(*) AS linhas,
       COUNTIF({valor} IS NULL) AS nulos,
       COUNTIF({valor} = '') AS strings_vazias
FROM `{tabela}`
GROUP BY _arquivo_origem
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


class ArquivosAusentes(Exception):
    """Faltam arquivos na pasta manual; a mensagem diz o que baixar e de onde."""


def mensagem_ausentes(ausentes: list[ArquivoEsperado], pasta: Path) -> str:
    linhas = [f"Faltam {len(ausentes)} arquivo(s) em {pasta}:"]
    for arq in ausentes:
        linhas += [
            f"  - {arq.nome}: {arq.descricao}",
            f"      baixe em {arq.conjunto.pagina} e salve como {pasta / arq.nome}",
        ]
    linhas.append(f"Passo a passo: {SECAO_DOCS}.")
    return "\n".join(linhas)


def verificar_arquivos(pasta: Path, esperados: list[ArquivoEsperado]) -> None:
    ausentes = [a for a in esperados if not (pasta / a.nome).is_file()]
    if ausentes:
        raise ArquivosAusentes(mensagem_ausentes(ausentes, pasta))


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


@dataclass
class Medicoes:
    arquivos: int = 0
    bytes_lidos: int = 0
    linhas_csv: int = 0
    linhas_carregadas: int = 0
    t_leitura: float = 0.0
    t_gcs: float = 0.0
    t_bigquery: float = 0.0
    por_arquivo: list[tuple[str, int, int]] = field(default_factory=list)  # nome, bytes, linhas
    # tabela -> caminho no GCS -> (linhas, vazios na coluna de valor), para validar o raw
    esperado: dict[str, dict[str, tuple[int, int]]] = field(default_factory=dict)

    @property
    def t_total(self) -> float:
        return self.t_leitura + self.t_gcs + self.t_bigquery


def carregar_arquivos(pasta: Path, esperados: list[ArquivoEsperado], config: Config) -> Medicoes:
    storage_cli = gcp.cliente_storage(config)
    bq_cli = gcp.cliente_bigquery(config)
    carregado_em = datetime.now(UTC).isoformat(timespec="seconds")
    medicoes = Medicoes()
    ja_carregou: set[str] = set()  # tabelas que já receberam o TRUNCATE desta execução

    for arq in esperados:
        caminho_local = pasta / arq.nome
        t0 = time.perf_counter()
        original = caminho_local.read_bytes()
        medicoes.t_leitura += time.perf_counter() - t0
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

        t0 = time.perf_counter()
        tabela = arq.conjunto.tabela
        linhas = gcp.carregar_csv_no_bigquery(
            bq_cli,
            config.tabela(DATASET_RAW, tabela),
            csv_raw.conteudo,
            gcp.montar_esquema(arq.conjunto.colunas, TIPOS_EXTRAS),
            truncar=tabela not in ja_carregou,
        )
        medicoes.t_bigquery += time.perf_counter() - t0
        ja_carregou.add(tabela)

        if linhas != csv_raw.linhas:
            raise RuntimeError(
                f"{arq.nome}: o CSV tem {csv_raw.linhas} linhas e o job carregou {linhas}"
            )
        medicoes.arquivos += 1
        medicoes.bytes_lidos += len(original)
        medicoes.linhas_csv += csv_raw.linhas
        medicoes.linhas_carregadas += linhas
        medicoes.por_arquivo.append((arq.nome, len(original), linhas))
        vazios = csv_raw.vazios[arq.conjunto.coluna_valor]
        medicoes.esperado.setdefault(tabela, {})[arq.caminho_gcs] = (csv_raw.linhas, vazios)
        log.info("%s: %d linhas -> %s (raw.%s)", arq.nome, linhas, origem, tabela)
    return medicoes


def validar_raw(config: Config, medicoes: Medicoes, conjuntos: list[Conjunto]) -> list[str]:
    """Compara, por arquivo, linhas e vazios do raw com os dos CSVs. Devolve os problemas."""
    bq_cli = gcp.cliente_bigquery(config)
    problemas = []
    for conjunto in conjuntos:
        esperado = medicoes.esperado.get(conjunto.tabela, {})
        resultado = gcp.executar_consulta(
            bq_cli,
            CONSULTA_VALIDACAO.format(
                tabela=config.tabela(DATASET_RAW, conjunto.tabela), valor=conjunto.coluna_valor
            ),
        )
        no_raw = {r["_arquivo_origem"]: r for r in resultado.linhas}
        for caminho, (linhas, vazios) in esperado.items():
            r = no_raw.get(caminho)
            if r is None:
                problemas.append(f"{caminho}: ausente em raw.{conjunto.tabela}")
                continue
            if r["linhas"] != linhas:
                problemas.append(f"{caminho}: {r['linhas']} linhas no raw, {linhas} no CSV")
            if r["nulos"] + r["strings_vazias"] != vazios:
                problemas.append(
                    f"{caminho}: {r['nulos']} NULL + {r['strings_vazias']} '' no raw, "
                    f"{vazios} vazios no CSV"
                )
        extras = sorted(set(no_raw) - set(esperado))
        if extras:
            problemas.append(
                f"raw.{conjunto.tabela}: arquivos que não vieram desta carga: {extras}"
            )
        log.info(
            "validação raw.%s: %d arquivos, %d NULL, %d strings vazias",
            conjunto.tabela,
            len(no_raw),
            sum(r["nulos"] for r in no_raw.values()),
            sum(r["strings_vazias"] for r in no_raw.values()),
        )
    return problemas


def medir_consulta_tipica(config: Config) -> dict[str, object]:
    bq_cli = gcp.cliente_bigquery(config)
    sql = CONSULTA_TIPICA.format(tabela=config.tabela(DATASET_RAW, PLD_HORARIO.tabela))
    estimativa = gcp.executar_consulta(bq_cli, sql, dry_run=True)
    real = gcp.executar_consulta(bq_cli, sql, usar_cache=False)  # sem cache: mede de verdade
    return {
        "bytes_estimados": estimativa.bytes_processados,
        "bytes_processados": real.bytes_processados,
        "bytes_faturados": real.bytes_faturados,
        "cache": real.cache,
        "horas": len(real.linhas),
    }


def imprimir_resumo(medicoes: Medicoes, consulta: dict | None) -> None:
    print("\n=== Medições da carga full da CCEE (para docs/metricas.md) ===")
    print(
        f"arquivos: {medicoes.arquivos} | volume dos arquivos carregados: "
        f"{medicoes.bytes_lidos / 1e6:.1f} MB (lidos da pasta manual, sem download)"
    )
    print(
        f"linhas nos CSVs: {medicoes.linhas_csv:,} | linhas carregadas: "
        f"{medicoes.linhas_carregadas:,}"
    )
    print(
        f"tempo total da carga: {medicoes.t_total:.1f} s "
        f"(leitura {medicoes.t_leitura:.1f} s, GCS {medicoes.t_gcs:.1f} s, "
        f"BigQuery {medicoes.t_bigquery:.1f} s)"
    )
    print("linhas por arquivo:")
    for nome, tamanho, linhas in medicoes.por_arquivo:
        print(f"  {nome}: {linhas:,} linhas, {tamanho / 1e6:.2f} MB")
    if consulta:
        proc, fat = consulta["bytes_processados"], consulta["bytes_faturados"]
        print("consulta típica (PLD médio por hora do SUDESTE em 2024, tabela sem partição):")
        print(f"  estimativa do dry-run: {consulta['bytes_estimados']:,} bytes")
        print(f"  bytes processados: {proc:,} ({proc / 1e6:.1f} MB)")
        print(f"  bytes faturados: {fat:,} ({fat / 1e6:.1f} MB) | cache: {consulta['cache']}")
        print(f"  linhas devolvidas: {consulta['horas']} (esperado: 24 horas)")


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
        problemas = validar_raw(config, medicoes, [PLD_HORARIO, PLD_SEMANAL, CONSUMO_RAMO])
        if problemas:
            for problema in problemas:
                log.error("validação: %s", problema)
            return 1
        log.info("validação do raw: ok (linhas e vazios batem com os CSVs)")
        consulta = medir_consulta_tipica(config)
    imprimir_resumo(medicoes, consulta)
    return 0


if __name__ == "__main__":
    sys.exit(main())
