"""Gera o seed `dbt/seeds/ajuste_definicao_carga.csv` a partir da API de Carga Verificada do ONS.

    uv run python -m scripts.baixar_mmgd_ons [--desde 2018-01] [--ate 2024-04] [--saida CAMINHO]

POR QUE EXISTE. A curva horária do ONS muda de definição duas vezes (docs/fontes.md): em 01/03/2021
entram as usinas não despachadas (tipo III) e em 01/05/2023 entra a MMGD estimada. Para comparar
meses de antes e de depois é preciso saber o tamanho de cada componente, e só a API de Carga
Verificada o publica (https://dados.ons.org.br/dataset/carga-energia-verificada): carga global
(bruta), líquida de MMGD e a própria MMGD, a cada meia hora, por área de carga (SECO, S, NE, N).

O QUE GRAVA. Uma linha por (mês, submercado) com as MÉDIAS MENSAIS da API (não o ajuste pronto: o
ajuste compara com a curva, que está no BigQuery, e é calculado no dbt, em `fct_carga_mensal`),
mais o status de cada componente e a data da consulta:

    status_mmgd:  zero_por_premissa | medido_parcial | medido | incorporado_na_curva
    status_tipo3: medido | incorporado_na_curva   (antes de 2018 a API não tem dado: o mart marca
                                                    "nao_disponivel", sem inventar valor)

DADOS DA API QUE EXIGEM CUIDADO (por isso há testes com um exemplo real, em tests/fixtures):
- o JSON vem INVÁLIDO quando um campo está vazio (`"val_cargammgd": ,`); `sanear_json` troca por
  null;
- a MMGD só existe a partir de 2019-02-15; antes, a API devolve campos vazios (tratados como 0 na
  média, e o mês de transição fica `medido_parcial`);
- o ONS revisa a série (`din_atualizacao`), então o seed guarda a data da consulta.

Não escreve na nuvem: só lê a API pública (sem credenciais) e grava um CSV local.
"""

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from ingestion.common.download import baixar_bytes
from ingestion.common.logs import obter_logger

log = obter_logger(__name__)

URL = "https://apicarga.ons.org.br/prd/cargaverificada"
SAIDA_PADRAO = Path(__file__).resolve().parents[1] / "dbt" / "seeds" / "ajuste_definicao_carga.csv"
# Área de carga da API -> código do submercado do projeto (o mesmo do ONS na curva horária)
AREAS = {"SECO": "SE", "S": "S", "NE": "NE", "N": "N"}

# Primeiro mês da API com carga global (antes disso a consulta volta vazia)
INICIO_PADRAO = "2018-01"
# 12 meses depois da quebra de 01/05/2023: a janela de onde sai o fator `r` (ver fct_carga_mensal)
FIM_PADRAO = "2024-04"

# Datas de quebra DO DADO (medidas contra a carga líquida da API; docs/decisoes.md). A documentação
# do ONS diz 29/04/2023 para a MMGD; no dado o salto só aparece em 01/05/2023 (29 e 30/04 não têm
# salto, 01/05 sim).
PRIMEIRO_MES_COM_MMGD_NA_CURVA = "2023-05"
PRIMEIRO_MES_COM_TIPO3_NA_CURVA = "2021-03"

CAMPOS_API = ("val_cargaglobal", "val_cargaglobalsmmgd", "val_cargammgd")
COLUNAS = (
    "mes",
    "codigo_submercado",
    "api_global_mwmed",
    "api_liquida_mwmed",
    "api_mmgd_mwmed",
    "api_intervalos",
    "api_intervalos_sem_mmgd",
    "api_ultima_atualizacao",
    "status_mmgd",
    "status_tipo3",
    "consultado_em",
)

# um campo vazio: `"nome": ,` ou `"nome":\n}` (a vírgula ou a chave fecha o valor que não veio)
_CAMPO_VAZIO = re.compile(r'("[^"]+"\s*:)\s*(?=[,}\]])')


def sanear_json(texto: str) -> list[dict]:
    """Converte a resposta da API em lista de dicionários, tolerando campos vazios (viram None)."""
    return json.loads(_CAMPO_VAZIO.sub(r"\1 null", texto))


@dataclass
class _Soma:
    """Acumulador de um (mês, área): somas para a média e contagens para o status."""

    n: int = 0
    global_: float = 0.0
    liquida: float = 0.0
    mmgd: float = 0.0
    sem_mmgd: int = 0
    atualizacao: str = ""


def agregar_mensal(registros: Iterable[dict]) -> dict[tuple[str, str], dict]:
    """Médias mensais por (mês 'AAAA-MM', área). Cada intervalo de meia hora pesa igual.

    - Deduplica por (área, instante UTC), ficando com o registro de `din_atualizacao` mais novo.
    - MMGD vazia conta como 0, e a líquida vazia é a própria global (nada foi descontado).
    - Registro sem carga global é descartado.
    """
    unicos: dict[tuple[str, str], dict] = {}
    for r in registros:
        if r.get("val_cargaglobal") is None:
            continue
        chave = (r["cod_areacarga"], r["din_referenciautc"])
        antigo = unicos.get(chave)
        if antigo is None or (r.get("din_atualizacao") or "") >= (
            antigo.get("din_atualizacao") or ""
        ):
            unicos[chave] = r

    somas: dict[tuple[str, str], _Soma] = defaultdict(_Soma)
    for r in unicos.values():
        s = somas[(r["dat_referencia"][:7], r["cod_areacarga"])]
        mmgd = r.get("val_cargammgd")
        liquida = r.get("val_cargaglobalsmmgd")
        s.n += 1
        s.global_ += r["val_cargaglobal"]
        s.mmgd += mmgd or 0.0
        s.liquida += liquida if liquida is not None else r["val_cargaglobal"]
        s.sem_mmgd += mmgd is None
        s.atualizacao = max(s.atualizacao, (r.get("din_atualizacao") or "")[:10])

    return {
        chave: {
            "api_global_mwmed": s.global_ / s.n,
            "api_liquida_mwmed": s.liquida / s.n,
            "api_mmgd_mwmed": s.mmgd / s.n,
            "api_intervalos": s.n,
            "api_intervalos_sem_mmgd": s.sem_mmgd,
            "api_ultima_atualizacao": s.atualizacao,
        }
        for chave, s in somas.items()
    }


def status_mmgd(mes: str, intervalos: int, sem_mmgd: int) -> str:
    """Situação da MMGD no mês: o que o ajuste de `fct_carga_mensal` pode fazer com ele."""
    if mes >= PRIMEIRO_MES_COM_MMGD_NA_CURVA:
        return "incorporado_na_curva"
    if sem_mmgd == intervalos:
        return "zero_por_premissa"
    if sem_mmgd > 0:
        return "medido_parcial"
    return "medido"


def status_tipo3(mes: str) -> str:
    return "incorporado_na_curva" if mes >= PRIMEIRO_MES_COM_TIPO3_NA_CURVA else "medido"


def montar_linhas(
    mensal: dict[tuple[str, str], dict], consultado_em: date
) -> list[dict[str, object]]:
    linhas = []
    for (mes, area), v in sorted(mensal.items()):
        linhas.append(
            {
                "mes": f"{mes}-01",
                "codigo_submercado": AREAS[area],
                **{k: round(x, 4) if isinstance(x, float) else x for k, x in v.items()},
                "status_mmgd": status_mmgd(mes, v["api_intervalos"], v["api_intervalos_sem_mmgd"]),
                "status_tipo3": status_tipo3(mes),
                "consultado_em": consultado_em.isoformat(),
            }
        )
    return linhas


def meses(desde: str, ate: str) -> list[tuple[date, date]]:
    """(primeiro, último dia) de cada mês de `desde` a `ate`, ambos 'AAAA-MM' e inclusivos."""
    ano, mes = map(int, desde.split("-"))
    ano_fim, mes_fim = map(int, ate.split("-"))
    saida = []
    while (ano, mes) <= (ano_fim, mes_fim):
        proximo = (ano + (mes == 12), mes % 12 + 1)
        saida.append((date(ano, mes, 1), date(*proximo, 1) - timedelta(days=1)))
        ano, mes = proximo
    return saida


def baixar_mes(area: str, primeiro: date, ultimo: date, baixar: Callable[..., bytes]) -> list[dict]:
    url = f"{URL}?dat_inicio={primeiro}&dat_fim={ultimo}&cod_areacarga={area}"
    registros = sanear_json(baixar(url).decode("utf-8"))
    esperado_minimo = (ultimo - primeiro).days * 48  # 48 meias horas por dia (+/- horário de verão)
    if len(registros) < esperado_minimo:
        raise RuntimeError(
            f"{area} {primeiro:%Y-%m}: {len(registros)} intervalos (< {esperado_minimo})"
        )
    return registros


def gerar(desde: str, ate: str, baixar: Callable[..., bytes] = baixar_bytes) -> list[dict]:
    tarefas = [(a, p, u) for a in AREAS for p, u in meses(desde, ate)]
    log.info("consultando a API: %d áreas x %d meses", len(AREAS), len(tarefas) // len(AREAS))
    with ThreadPoolExecutor(max_workers=4) as pool:
        partes = list(pool.map(lambda t: baixar_mes(*t, baixar), tarefas))
    registros = [r for parte in partes for r in parte]
    log.info("%d registros semi-horários recebidos", len(registros))
    return montar_linhas(agregar_mensal(registros), datetime.now(UTC).date())


def gravar(linhas: list[dict], saida: Path) -> None:
    saida.parent.mkdir(parents=True, exist_ok=True)
    with saida.open("w", newline="", encoding="utf-8") as f:
        escritor = csv.DictWriter(f, fieldnames=COLUNAS, lineterminator="\n")
        escritor.writeheader()
        escritor.writerows(linhas)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--desde", default=INICIO_PADRAO, help="AAAA-MM (padrão: %(default)s)")
    ap.add_argument("--ate", default=FIM_PADRAO, help="AAAA-MM (padrão: %(default)s)")
    ap.add_argument("--saida", type=Path, default=SAIDA_PADRAO)
    args = ap.parse_args(argv)
    linhas = gerar(args.desde, args.ate)
    gravar(linhas, args.saida)
    log.info("%d linhas gravadas em %s", len(linhas), args.saida)
    return 0


if __name__ == "__main__":
    sys.exit(main())
