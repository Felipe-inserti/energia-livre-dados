"""Extrator da curva de carga horária do ONS: carga incremental por janela, ou full.

    uv run python -m ingestion.ons                       # janela (3 meses), referência = hoje (UTC)
    uv run python -m ingestion.ons --data-referencia 2026-10-06
    uv run python -m ingestion.ons --desde 2021-01 --ate 2021-03    # backfill por intervalo
    uv run python -m ingestion.ons --full [--ano-inicial 2000] [--ano-final 2026]
    (todos aceitam --dataset-raw, --tabela-raw, --concorrencia, --sem-consulta, --sem-medicao)

Três modos (o destino completo e o modo são logados no início de toda execução):

- **janela** (diária): meses locais da janela (ingestion/janela.py: mês corrente + 2 anteriores,
  estendida se o raw estiver atrasado). Baixa só o(s) arquivo(s) do ano da janela; confere por HEAD
  (ETag = MD5 do arquivo, nada é baixado) se algum ano fechado mudou no ONS e, se mudou, recarrega
  esse ano; se a comparação do bronze mostrar revisão FORA da janela, recarrega o ano inteiro.
- **backfill**: `--desde/--ate AAAA-MM` (inclusive), os mesmos load jobs por partição.
- **full**: trunca a tabela particionada inteira e carrega os 27 anos (o 1º ano com WRITE_TRUNCATE e
  os demais com WRITE_APPEND em paralelo).

Raw: `raw.ons_curva_carga` é particionado por MÊS LOCAL em `_mes_referencia` (DATE). Janela e
backfill fazem UM load job por mês no decorador `tabela$AAAAMM` com WRITE_TRUNCATE (load não é
cobrado e substituir a partição é idempotente), em paralelo com concorrência limitada
(`--concorrencia`).

ATOMICIDADE: cada partição é atômica (o load job é tudo ou nada), mas entre partições não há. Se um
job falhar, a execução termina com erro listando os meses que falharam, e os outros meses já estão
novos. É aceitável porque reexecutar é seguro (idempotente: cada job substitui a sua partição) e é
melhor que a carga de antes, em que uma falha deixava a tabela inteira parcial. A carga full
continua não atômica (se um append falhar, a tabela fica parcial até a próxima `--full`).

O código NUNCA apaga nem recria uma tabela existente: se `--tabela-raw` existir sem a partição
esperada (o raw de produção, antes da migração), ele recusa. A migração é um passo manual.

Bronze: o CSV ORIGINAL vai para bronze/ons/curva_carga/ano=AAAA/ só se o MD5 mudou (a versão antiga
é arquivada em bronze/ons/curva_carga_versoes/ e a revisão é medida, ingestion/revisoes.py).
Nulos e casos conhecidos (docs/fontes.md) entram como estão: o tratamento é do staging e dos testes.
"""

import argparse
import csv
import io
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import requests

from ingestion import revisoes
from ingestion.common import download, gcp
from ingestion.common.config import DATASET_RAW, Config, carregar_config
from ingestion.common.csv_utils import transformar_csv
from ingestion.common.download import ArquivoNaoEncontrado, baixar_bytes
from ingestion.common.logs import obter_logger
from ingestion.common.raw import (
    ConjuntoValidacao,
    Medicoes,
    imprimir_resumo,
    medir_consulta_tipica,
    validar_raw,
)
from ingestion.janela import (
    Janela,
    calcular_janela,
    cobrindo,
    janela_de_intervalo,
    ultimo_mes_de_particoes,
)

log = obter_logger("ingestion.ons")

ANO_INICIAL = 2000  # primeiro ano publicado (1999 retorna 404)
URL_MODELO = (
    "https://ons-aws-prod-opendata.s3.amazonaws.com/dataset/curva-carga-ho/CURVA_CARGA_{ano}.csv"
)
NOME_TABELA = "ons_curva_carga"
PREFIXO_BRONZE = "bronze/ons/curva_carga/"
COLUNAS_ESPERADAS = [
    "id_subsistema",
    "nom_subsistema",
    "din_instante",
    "val_cargaenergiahomwmed",
]
COLUNA_VALOR = "val_cargaenergiahomwmed"
CAMPO_PARTICAO = "_mes_referencia"  # DATE: 1º dia do mês LOCAL de din_instante
TIPOS_EXTRAS = {"_arquivo_origem": "STRING", "_carregado_em": "TIMESTAMP", CAMPO_PARTICAO: "DATE"}
_PADRAO_INSTANTE = re.compile(r"^\d{4}-\d{2}-\d{2}")
CONCORRENCIA_PADRAO = 8

# "Carga média por hora do SE em 2024". As colunas são STRING no raw, então a data é comparada
# como texto ISO e o valor precisa de SAFE_CAST. Esta é a consulta do "antes".
CONSULTA_TIPICA = """
SELECT EXTRACT(HOUR FROM TIMESTAMP(din_instante)) AS hora,
       AVG(SAFE_CAST(val_cargaenergiahomwmed AS FLOAT64)) AS carga_media
FROM `{tabela}`
WHERE id_subsistema = 'SE'
  AND din_instante >= '2024-01-01' AND din_instante < '2025-01-01'
GROUP BY hora
ORDER BY hora
"""


@dataclass(frozen=True)
class Raw:
    """Destino da carga (configurável: a validação real usa um dataset fora da produção)."""

    id: str  # projeto.dataset.tabela
    dataset: str
    tabela: str


def mes_referencia(linha: dict[str, str]) -> str:
    """`_mes_referencia` da linha: 1º dia do mês local de `din_instante` (AAAA-MM-01)."""
    instante = linha["din_instante"]
    if not _PADRAO_INSTANTE.match(instante):
        raise ValueError(f"din_instante inesperado: {instante!r}")
    return f"{instante[:7]}-01"


@dataclass(frozen=True)
class FatiaMes:
    mes: str  # AAAA-MM
    conteudo: bytes  # CSV com cabeçalho, só com as linhas do mês
    linhas: int
    vazios: int  # linhas com a coluna de valor vazia


def fatiar_por_mes(conteudo: bytes, coluna_valor: str = COLUNA_VALOR) -> dict[str, FatiaMes]:
    """Divide o CSV do raw (já com `_mes_referencia`) em um CSV por mês.

    Necessário porque o load no decorador `$AAAAMM` só aceita linhas daquela partição: o
    BigQuery recusa o job se alguma linha for de outro mês.
    """
    leitor = csv.reader(io.StringIO(conteudo.decode("utf-8"), newline=""))
    cabecalho = next(leitor)
    i_mes, i_valor = cabecalho.index(CAMPO_PARTICAO), cabecalho.index(coluna_valor)
    linhas_por_mes: dict[str, list[list[str]]] = {}
    for linha in leitor:
        if linha:
            linhas_por_mes.setdefault(linha[i_mes][:7], []).append(linha)
    fatias = {}
    for mes, linhas in sorted(linhas_por_mes.items()):
        saida = io.StringIO()
        escritor = csv.writer(saida, lineterminator="\n")
        escritor.writerow(cabecalho)
        escritor.writerows(linhas)
        vazios = sum(1 for linha in linhas if linha[i_valor] == "")
        fatias[mes] = FatiaMes(mes, saida.getvalue().encode("utf-8"), len(linhas), vazios)
    return fatias


def montar_url(ano: int) -> str:
    return URL_MODELO.format(ano=ano)


def nome_arquivo(ano: int) -> str:
    return f"CURVA_CARGA_{ano}.csv"


def caminho_gcs(ano: int) -> str:
    """Caminho do CSV original no bucket (camada bronze), sem o nome do bucket."""
    return f"bronze/ons/curva_carga/ano={ano}/{nome_arquivo(ano)}"


def caminho_versao(ano: int, gravado_em: datetime) -> str:
    """Onde fica a versão antiga: a pasta leva o momento em que ELA foi gravada (sua carga)."""
    momento = gravado_em.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"bronze/ons/curva_carga_versoes/ano={ano}/carga={momento}/{nome_arquivo(ano)}"


def sincronizar_bronze(
    storage_cli, bucket: str, ano: int, original: bytes, medicoes: Medicoes
) -> str:
    """Grava o CSV no bronze só se o hash mudou; se mudou, arquiva a versão antiga e mede a revisão.

    Devolve o texto do que aconteceu com o bronze, para o log: "pulado (hash igual)" ou
    "gravado em gs://..." (com "versão antiga arquivada" quando havia um arquivo diferente).

    A versão antiga é copiada ANTES de a nova sobrescrevê-la, para uma falha no meio não perder
    o que existia. Os anos fechados não mudam (medido: 2000 a 2025 idênticos entre duas cargas),
    então na prática só o ano corrente gera versões.
    """
    caminho = caminho_gcs(ano)
    existente = gcp.buscar_objeto(storage_cli, bucket, caminho)
    if existente is not None and existente.md5_hash == gcp.md5_base64(original):
        medicoes.gcs_pulados += 1
        return "pulado (hash igual)"

    if existente is not None:
        registro = revisoes.comparar_csv_ons(existente.download_as_bytes(), original, ano)
        revisoes.registrar(registro, origem="ingestao")
        medicoes.revisoes.append(registro)
        log.info("revisão: %s", revisoes.resumir(registro))
        gcp.copiar_objeto(storage_cli, bucket, existente, caminho_versao(ano, existente.updated))
        medicoes.gcs_versoes += 1
        medicoes.gcs_bytes_versoes += existente.size or 0

    destino = gcp.enviar_para_gcs(storage_cli, bucket, caminho, original)
    medicoes.gcs_gravados += 1
    medicoes.gcs_bytes_gravados += len(original)
    arquivada = ", versão antiga arquivada" if existente is not None else ""
    return f"gravado em {destino}{arquivada}"


def anos_a_carregar(ano_inicial: int, ano_final: int) -> list[int]:
    if ano_inicial < ANO_INICIAL:
        raise ValueError(f"O ONS publica a partir de {ANO_INICIAL}, não de {ano_inicial}")
    if ano_final < ano_inicial:
        raise ValueError(f"ano_final ({ano_final}) menor que ano_inicial ({ano_inicial})")
    return list(range(ano_inicial, ano_final + 1))


def validar_colunas(colunas: list[str]) -> None:
    """O layout é o mesmo nos 26 anos (docs/fontes.md); se mudar, melhor parar do que carregar."""
    if colunas != COLUNAS_ESPERADAS:
        raise ValueError(f"Layout inesperado: {colunas}, esperado {COLUNAS_ESPERADAS}")


def etag_para_md5_base64(etag: str | None) -> str | None:
    """ETag do S3 -> MD5 em base64 (o formato de `blob.md5_hash`), ou None se não for um MD5.

    O ETag é o MD5 do arquivo só em upload simples (32 hex); em upload multipart ele tem outro
    formato e não serve para comparar (devolve None, e o chamador baixa o arquivo).
    """
    if etag is None or not re.fullmatch(r"[0-9a-f]{32}", etag):
        return None
    return gcp.md5_base64_de_hex(etag)


def anos_fechados_desatualizados(
    anos: list[int],
    objetos: dict,
    buscar_etag=download.buscar_etag,
    concorrencia: int = CONCORRENCIA_PADRAO,
) -> list[int]:
    """Anos fechados cujo arquivo no ONS mudou desde o bronze (HEAD; nada é baixado).

    Os HEADs vão em paralelo (a mesma concorrência dos loads): em série os 26 levaram 16,7 s, e cada
    um é só espera de rede. A ordem do resultado é a de `anos`. Um HEAD que falha depois das
    retentativas NÃO derruba a conferência: aquele ano é tratado como desatualizado e cai no
    download (que tem as próprias retentativas); só se o download também falhar a ingestão falha.

    Sem objeto no bronze, ou com ETag que não é MD5, o ano é tratado como desatualizado: na
    dúvida, baixa (o custo é 1,5 MB) em vez de deixar uma revisão passar em silêncio.
    """
    if not anos:
        return []

    def etag_ou_none(ano: int) -> str | None:
        try:
            return buscar_etag(montar_url(ano))
        except (download.ErroDownload, requests.RequestException) as erro:
            # o HEAD falhou depois das retentativas: o ano cai no DOWNLOAD (que tem as próprias
            # retentativas), em vez de a conferência derrubar a ingestão inteira
            log.warning(
                "HEAD de %d falhou (%s: %s); o ano será baixado", ano, type(erro).__name__, erro
            )
            return None

    with ThreadPoolExecutor(max_workers=max(1, min(concorrencia, len(anos)))) as pool:
        etags = list(pool.map(etag_ou_none, anos))
    desatualizados = []
    for ano, etag in zip(anos, etags, strict=True):
        objeto = objetos.get(caminho_gcs(ano))
        md5_ons = etag_para_md5_base64(etag)
        if objeto is None or md5_ons is None or md5_ons != objeto.md5_hash:
            desatualizados.append(ano)
    return desatualizados


def meses_fora_da_janela(registro: dict, janela: Janela) -> list[str]:
    """Meses (AAAA-MM) com linha alterada, adicionada ou removida que a janela NÃO recarrega."""
    dentro = {m.strftime("%Y-%m") for m in janela.meses_locais}
    return [m for m in registro.get("meses_afetados", []) if m not in dentro]


def meses_a_carregar(ano: int, fatias: dict[str, FatiaMes], janela: Janela, inteiro: set[int]):
    """Meses do arquivo do ano que viram load job: todos se o ano é recarregado inteiro."""
    if ano in inteiro:
        return sorted(fatias)
    dentro = {m.strftime("%Y-%m") for m in janela.meses_locais}
    return sorted(m for m in fatias if m in dentro)


def _baixar_ano(ano: int, ano_atual: int, medicoes: Medicoes) -> bytes | None:
    t0 = time.perf_counter()
    try:
        return baixar_bytes(montar_url(ano))
    except ArquivoNaoEncontrado:
        if ano == ano_atual:  # o arquivo do ano corrente pode ainda não existir (janeiro)
            log.warning("%d: arquivo ainda não publicado (404); ano ignorado", ano)
            return None
        raise
    finally:
        medicoes.t_origem += time.perf_counter() - t0


def _csv_do_raw(original: bytes, ano: int, carregado_em: str):
    extras = {"_arquivo_origem": caminho_gcs(ano), "_carregado_em": carregado_em}
    csv_raw = transformar_csv(original, extras, derivadas={CAMPO_PARTICAO: mes_referencia})
    validar_colunas(csv_raw.colunas)
    return csv_raw


def resolver_janela(
    config: Config, raw: Raw, desde: str | None, ate: str | None, referencia: date
) -> Janela:
    """Janela do backfill (`--desde/--ate`) ou a diária, autocorretiva pelo último mês do raw."""
    cliente = gcp.cliente_bigquery(config)
    esquema = gcp.montar_esquema(COLUNAS_ESPERADAS, TIPOS_EXTRAS)
    gcp.garantir_tabela_particionada(cliente, raw.id, esquema, CAMPO_PARTICAO, criar=False)
    if desde and ate:
        return janela_de_intervalo(desde, ate)
    ultimo = ultimo_mes_de_particoes(gcp.listar_particoes(cliente, raw.id))
    if ultimo is None:
        raise gcp.TabelaIncompativel(f"{raw.id} não tem dados: carregue-a primeiro com --full")
    return calcular_janela(referencia, ultimo)


def carregar_incremental(
    janela: Janela,
    config: Config,
    raw: Raw,
    concorrencia: int,
    *,
    verificar_fechados: bool,
) -> Medicoes:
    """Recarrega as partições da janela (e os anos que o ETag ou a guarda de revisão apontarem)."""
    storage_cli = gcp.cliente_storage(config)
    cliente_bq = gcp.cliente_bigquery(config)
    esquema = gcp.montar_esquema(COLUNAS_ESPERADAS, TIPOS_EXTRAS)
    medicoes = Medicoes()
    carregado_em = datetime.now(UTC).isoformat(timespec="seconds")
    ano_atual = janela.mes_final.year
    log.info(
        "janela: meses %s a %s (%d), anos %s, partições UTC do dbt %s a %s",
        janela.mes_inicial.strftime("%Y-%m"),
        janela.mes_final.strftime("%Y-%m"),
        len(janela.meses_locais),
        janela.anos,
        janela.particoes_utc[0].strftime("%Y-%m"),
        janela.particoes_utc[-1].strftime("%Y-%m"),
    )

    inteiros: set[int] = set()  # anos recarregados por inteiro
    t0 = time.perf_counter()
    if verificar_fechados:
        objetos = gcp.listar_objetos(storage_cli, config.bucket, PREFIXO_BRONZE)
        fechados = [a for a in range(ANO_INICIAL, ano_atual + 1) if a not in janela.anos]
        t_etag = time.perf_counter()
        mudaram = anos_fechados_desatualizados(fechados, objetos, concorrencia=concorrencia)
        log.info(
            "ETag: %d anos fechados conferidos, %d desatualizados %s (%.1f s, concorrência %d)",
            len(fechados),
            len(mudaram),
            mudaram or "",
            time.perf_counter() - t_etag,
            concorrencia,
        )
        inteiros |= set(mudaram)
    medicoes.t_gcs += time.perf_counter() - t0

    trabalhos: dict[str, gcp.Trabalho] = {}
    for ano in sorted(set(janela.anos) | inteiros):
        original = _baixar_ano(ano, ano_atual, medicoes)
        if original is None:
            continue
        t0 = time.perf_counter()
        revisoes_antes = len(medicoes.revisoes)
        bronze = sincronizar_bronze(storage_cli, config.bucket, ano, original, medicoes)
        medicoes.t_gcs += time.perf_counter() - t0
        if ano in janela.anos and len(medicoes.revisoes) > revisoes_antes:
            fora = meses_fora_da_janela(medicoes.revisoes[-1], janela)
            if fora:
                log.warning(
                    "%d: revisão do ONS FORA da janela (meses %s); recarregando o ano inteiro",
                    ano,
                    fora,
                )
                inteiros.add(ano)
        if ano not in janela.anos and bronze.startswith("pulado"):
            # ano fechado baixado só porque o HEAD falhou (ou o ETag não é MD5): o arquivo é
            # IDÊNTICO ao bronze, então o raw já o tem: nada a recarregar nem a reprocessar no dbt
            log.info("%d: arquivo idêntico ao bronze (hash igual); nada a recarregar", ano)
            inteiros.discard(ano)
            medicoes.registrar_arquivo(nome_arquivo(ano), len(original), 0)
            continue
        csv_raw = _csv_do_raw(original, ano, carregado_em)
        fatias = fatiar_por_mes(csv_raw.conteudo)
        meses = meses_a_carregar(ano, fatias, janela, inteiros)
        for mes in meses:
            fatia = fatias[mes]
            particao = mes.replace("-", "")
            trabalhos[particao] = gcp.Trabalho(fatia.conteudo, fatia.linhas, particao=particao)
            medicoes.registrar_esperado(
                raw.tabela, (caminho_gcs(ano), f"{mes}-01"), fatia.linhas, fatia.vazios
            )
        medicoes.registrar_arquivo(nome_arquivo(ano), len(original), csv_raw.linhas)
        log.info(
            "%d: %.2f MB baixados, %d de %d meses do arquivo viram load job%s; bronze: %s",
            ano,
            len(original) / 1e6,
            len(meses),
            len(fatias),
            " (ano inteiro)" if ano in inteiros else "",
            bronze,
        )
    medicoes.anos_recarregados = sorted(inteiros)

    t0 = time.perf_counter()
    medicoes.jobs_bigquery = len(trabalhos)
    try:
        carregadas = gcp.carregar_em_paralelo(
            cliente_bq, raw.id, trabalhos, esquema, concorrencia=concorrencia
        )
    except gcp.ErroCargaParcial as erro:
        medicoes.particoes_carregadas = sorted(erro.ok)
        raise
    finally:
        medicoes.t_bigquery += time.perf_counter() - t0
    medicoes.particoes_carregadas = sorted(carregadas)
    medicoes.linhas_carregadas = sum(carregadas.values())
    return medicoes


def carregar_full(
    anos: list[int], config: Config, raw: Raw, ano_atual: int, concorrencia: int
) -> Medicoes:
    """Carga full: trunca a tabela particionada e carrega todos os anos com poucos load jobs.

    O 1º ano com WRITE_TRUNCATE (sem decorador, com o particionamento esperado) e os demais com
    WRITE_APPEND, em paralelo. Cada job escreve em várias partições (`_mes_referencia` linha a
    linha), então são 27 jobs, não ~320.
    """
    storage_cli = gcp.cliente_storage(config)
    cliente_bq = gcp.cliente_bigquery(config)
    esquema = gcp.montar_esquema(COLUNAS_ESPERADAS, TIPOS_EXTRAS)
    medicoes = Medicoes()
    carregado_em = datetime.now(UTC).isoformat(timespec="seconds")

    t0 = time.perf_counter()
    situacao = gcp.garantir_tabela_particionada(
        cliente_bq, raw.id, esquema, CAMPO_PARTICAO, criar=True
    )
    medicoes.t_bigquery += time.perf_counter() - t0
    log.info("tabela %s: %s", raw.id, situacao)

    preparados = []  # (ano, csv do raw)
    for ano in anos:
        original = _baixar_ano(ano, ano_atual, medicoes)
        if original is None:
            continue
        t0 = time.perf_counter()
        bronze = sincronizar_bronze(storage_cli, config.bucket, ano, original, medicoes)
        medicoes.t_gcs += time.perf_counter() - t0
        csv_raw = _csv_do_raw(original, ano, carregado_em)
        medicoes.registrar_arquivo(nome_arquivo(ano), len(original), csv_raw.linhas)
        medicoes.registrar_esperado(
            raw.tabela, (caminho_gcs(ano),), csv_raw.linhas, csv_raw.vazios[COLUNA_VALOR]
        )
        preparados.append((ano, csv_raw))
        log.info(
            "%d: %.2f MB baixados, %d linhas; bronze: %s",
            ano,
            len(original) / 1e6,
            csv_raw.linhas,
            bronze,
        )
    if not preparados:
        raise RuntimeError("nenhum arquivo para carregar")

    t0 = time.perf_counter()
    try:
        primeiro_ano, primeiro = preparados[0]
        carregadas = gcp.carregar_csv_no_bigquery(
            cliente_bq,
            raw.id,
            primeiro.conteudo,
            esquema,
            truncar=True,
            particionamento=gcp.particionamento_mensal(CAMPO_PARTICAO),
        )
        if carregadas != primeiro.linhas:
            raise RuntimeError(
                f"{primeiro_ano}: o CSV tem {primeiro.linhas} linhas e o job carregou {carregadas}"
            )
        medicoes.linhas_carregadas += carregadas
        medicoes.jobs_bigquery = 1
        restantes = {
            f"ano {ano}": gcp.Trabalho(csv_raw.conteudo, csv_raw.linhas, None, False)
            for ano, csv_raw in preparados[1:]
        }
        medicoes.jobs_bigquery += len(restantes)
        try:
            ok = gcp.carregar_em_paralelo(
                cliente_bq, raw.id, restantes, esquema, concorrencia=concorrencia
            )
        except gcp.ErroCargaParcial as erro:
            medicoes.linhas_carregadas += sum(erro.ok.values())
            raise
        medicoes.linhas_carregadas += sum(ok.values())
    finally:
        medicoes.t_bigquery += time.perf_counter() - t0
    return medicoes


def conjunto_de_validacao(modo: str, raw: Raw, medicoes: Medicoes) -> ConjuntoValidacao | None:
    """Full: confere por arquivo. Incremental: por (arquivo, mês), só os meses recarregados."""
    if modo == "full":
        return ConjuntoValidacao(raw.tabela, COLUNA_VALOR, dataset=raw.dataset)
    meses = sorted({chave[1] for chave in medicoes.esperado.get(raw.tabela, {})})
    if not meses:
        return None
    lista = ", ".join(f"'{m}'" for m in meses)
    return ConjuntoValidacao(
        raw.tabela,
        COLUNA_VALOR,
        colunas_chave=("_arquivo_origem", CAMPO_PARTICAO),
        dataset=raw.dataset,
        filtro_sql=f"{CAMPO_PARTICAO} IN ({lista})",
    )


def _data_iso(texto: str) -> date:
    return date.fromisoformat(texto)


def montar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Carga da curva de carga do ONS")
    parser.add_argument("--full", action="store_true", help="carga full (trunca e recarrega tudo)")
    parser.add_argument("--desde", help="backfill: primeiro mês, AAAA-MM (com --ate)")
    parser.add_argument("--ate", help="backfill: último mês, AAAA-MM, inclusive (com --desde)")
    parser.add_argument(
        "--data-referencia",
        type=_data_iso,
        help="AAAA-MM-DD que ancora a janela (a DAG passa a data lógica); padrão: hoje (UTC)",
    )
    parser.add_argument(
        "--saida-vars",
        help="janela e backfill: grava aqui, em JSON, as vars do dbt do que foi carregado de fato "
        "(a janela ampliada por anos recarregados), para o `dbt --vars` do passo seguinte",
    )
    parser.add_argument("--concorrencia", type=int, default=CONCORRENCIA_PADRAO)
    parser.add_argument("--dataset-raw", default=DATASET_RAW, help="dataset do raw (padrão: raw)")
    parser.add_argument("--tabela-raw", default=NOME_TABELA, help="tabela do raw")
    parser.add_argument("--ano-inicial", type=int, default=ANO_INICIAL, help="só com --full")
    parser.add_argument("--ano-final", type=int, default=None, help="só com --full")
    parser.add_argument(
        "--sem-consulta", action="store_true", help="não valida o raw nem mede a consulta típica"
    )
    parser.add_argument(
        "--sem-medicao",
        action="store_true",
        help="valida o raw, mas não roda a consulta típica (37 MB; é benchmark, não precisa ser "
        "diária): é o modo da DAG do Airflow",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = montar_parser()
    args = parser.parse_args(argv)
    if bool(args.desde) != bool(args.ate):
        parser.error("--desde e --ate andam juntos")
    if args.full and args.desde:
        parser.error("--full não combina com --desde/--ate")
    if args.full and args.saida_vars:
        parser.error("--saida-vars não vale para --full (o dbt reconstrói tudo com --full-refresh)")

    hoje = datetime.now(UTC).date()  # o relógio só é lido aqui, na borda da CLI
    referencia = args.data_referencia or hoje
    config = carregar_config()
    raw = Raw(config.tabela(args.dataset_raw, args.tabela_raw), args.dataset_raw, args.tabela_raw)
    modo = "full" if args.full else "backfill" if args.desde else "janela"
    log.info("destino: %s | modo: %s | bucket: %s", raw.id, modo, config.bucket)

    try:
        if modo == "full":
            ano_final = args.ano_final or hoje.year
            anos = anos_a_carregar(args.ano_inicial, ano_final)
            log.info("carga full do ONS: anos %d a %d", anos[0], anos[-1])
            medicoes = carregar_full(anos, config, raw, hoje.year, args.concorrencia)
            detalhe = f" (anos {anos[0]} a {anos[-1]})"
        else:
            janela = resolver_janela(config, raw, args.desde, args.ate, referencia)
            medicoes = carregar_incremental(
                janela,
                config,
                raw,
                args.concorrencia,
                verificar_fechados=(modo == "janela"),
            )
            detalhe = f" (anos {janela.anos})"
            if args.saida_vars:
                vars_dbt = cobrindo(janela, medicoes.particoes_carregadas).vars_dbt()
                Path(args.saida_vars).parent.mkdir(parents=True, exist_ok=True)
                Path(args.saida_vars).write_text(json.dumps(vars_dbt, separators=(",", ":")))
                log.info("vars do dbt gravadas em %s", args.saida_vars)
    except gcp.TabelaIncompativel as erro:
        log.error("%s", erro)
        return 2
    except gcp.ErroCargaParcial as erro:
        log.error("%s", erro)
        for rotulo, causa in sorted(erro.falhas.items()):
            log.error("  falhou: %s (%s)", rotulo, causa)
        log.error("reexecute: é idempotente (cada job substitui a sua partição)")
        return 1

    consulta = None
    if not args.sem_consulta:
        conjunto = conjunto_de_validacao(modo, raw, medicoes)
        problemas = validar_raw(config, medicoes, [conjunto]) if conjunto else []
        if problemas:
            for problema in problemas:
                log.error("validação: %s", problema)
            return 1
        log.info("validação do raw: ok (linhas e vazios batem com os CSVs)")
        if not args.sem_medicao:
            consulta = medir_consulta_tipica(config, CONSULTA_TIPICA.format(tabela=raw.id))
    imprimir_resumo(
        f"da carga do ONS (modo {modo})",
        medicoes,
        consulta,
        rotulo_volume="volume baixado",
        rotulo_origem="download",
        descricao_consulta="carga média por hora do SE em 2024",
        detalhe_arquivos=detalhe,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
