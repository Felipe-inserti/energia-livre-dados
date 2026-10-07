"""Janela do incremental do ONS: meses a recarregar, anos a baixar e partições a escrever.

Função pura: nada de relógio, rede ou nuvem. Toda data vem de fora (a data lógica da execução da
DAG, ou `--desde/--ate`), então reprocessar um dia dá sempre o mesmo resultado.

Há DOIS calendários, e a janela existe para não misturá-los:
- o **raw** está particionado por mês LOCAL (America/Sao_Paulo), o mês de `din_instante`;
- o **staging e os fatos** estão particionados por mês UTC (`instante_utc`).
O mês local M começa em M-01 00:00 local (03:00Z, ou 02:00Z no horário de verão) e termina no
mesmo fuso do mês seguinte. Por isso as últimas ~3 h do mês local caem no mês UTC seguinte.

REGRAS (cada uma tem teste em tests/test_janela.py; a primeira evita perda de dado):

1. **Toda partição UTC sobrescrita precisa ser recomposta INTEIRA.** O `insert_overwrite` apaga a
   partição e insere só o que a consulta devolveu; se a consulta não enxergar todas as horas da
   partição, o MERGE apaga o que não leu (perda de dado, pior que duplicata). Logo o raw lido pelo
   dbt cobre todas as horas de todas as partições UTC da lista: do mês local que contém a PRIMEIRA
   hora de `utc_inicio` até o mês local que contém a ÚLTIMA hora antes de `utc_fim` (`raw_mes_*`).
   Exemplo: janela local de jul a set -> partições UTC jul, ago, set **e out** -> o raw lido vai de
   jun a **out** (o raw de outubro entra na leitura, embora não seja recarregado).
2. **Lista de partições e filtro cobrem exatamente o mesmo intervalo UTC**: `[utc_inicio, utc_fim)`,
   alinhado a meses UTC inteiros. Nenhuma linha é inserida numa partição que não foi apagada.
3. **A lista de partições UTC é todo mês UTC que o intervalo local toca**, não só os meses do
   calendário local: a janela local jul a set toca out (as horas de 30/09 21h a 24h local são 01/10
   00h a 02h UTC), então out entra. Sem isso uma revisão dessas horas ficaria sem ser aplicada.
4. **O raw recarregado (load job por partição `$AAAAMM`) é só a janela local**, sem os meses extras
   que o dbt lê.
5. **Janela autocorretiva**: o início é o MENOR entre (mês da referência - (N-1) meses) e o mês do
   último dado presente no raw (lido dos metadados de partição). Um período longo sem execução
   (PC desligado) não deixa buraco. Quando a janela é estendida, loga um aviso.
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from ingestion.common.logs import obter_logger

log = obter_logger("ingestion.janela")

FUSO_LOCAL = ZoneInfo("America/Sao_Paulo")
MESES_PADRAO = 3  # mês corrente + 2 anteriores (decisoes.md)
PRIMEIRO_MES = date(2000, 1, 1)  # o ONS publica a partir de 2000
_PADRAO_MES = re.compile(r"^(\d{4})-(\d{2})$")
_PADRAO_PARTICAO = re.compile(r"^(\d{4})(\d{2})$")


def primeiro_dia(d: date) -> date:
    return d.replace(day=1)


def somar_meses(mes: date, n: int) -> date:
    """1º dia do mês `n` meses depois (ou antes, se negativo) do mês de `mes`."""
    indice = mes.year * 12 + (mes.month - 1) + n
    return date(indice // 12, indice % 12 + 1, 1)


def meses_entre(inicio: date, fim: date) -> list[date]:
    """Todos os meses (1º dia) de `inicio` a `fim`, inclusive."""
    saida, mes = [], primeiro_dia(inicio)
    while mes <= primeiro_dia(fim):
        saida.append(mes)
        mes = somar_meses(mes, 1)
    return saida


def _mes_local_de(instante_utc: datetime) -> date:
    return primeiro_dia(instante_utc.astimezone(FUSO_LOCAL).date())


def _inicio_do_mes_local(mes: date) -> datetime:
    """Meia-noite local do 1º dia do mês, como instante UTC."""
    return datetime(mes.year, mes.month, 1, tzinfo=FUSO_LOCAL).astimezone(UTC)


def _inicio_do_mes_utc(mes: date) -> datetime:
    return datetime(mes.year, mes.month, 1, tzinfo=UTC)


@dataclass(frozen=True)
class Janela:
    """Meses LOCAIS recarregados, do primeiro ao último (inclusive), 1º dia de cada mês."""

    mes_inicial: date
    mes_final: date
    estendida: bool = False  # True quando a autocorreção puxou o início para trás

    @property
    def meses_locais(self) -> list[date]:
        return meses_entre(self.mes_inicial, self.mes_final)

    @property
    def particoes_raw(self) -> list[str]:
        """Decoradores `$AAAAMM` dos load jobs do raw: só os meses da janela (regra 4)."""
        return [m.strftime("%Y%m") for m in self.meses_locais]

    @property
    def anos(self) -> list[int]:
        """Anos dos arquivos do ONS a baixar. Em janeiro a janela cruza dois arquivos."""
        return sorted({m.year for m in self.meses_locais})

    @property
    def _intervalo_local_em_utc(self) -> tuple[datetime, datetime]:
        return (
            _inicio_do_mes_local(self.mes_inicial),
            _inicio_do_mes_local(somar_meses(self.mes_final, 1)),
        )

    @property
    def particoes_utc(self) -> list[date]:
        """Todo mês UTC que o intervalo local toca (regra 3)."""
        inicio, fim = self._intervalo_local_em_utc
        ultimo = primeiro_dia((fim - timedelta(microseconds=1)).date())
        return meses_entre(primeiro_dia(inicio.date()), ultimo)

    @property
    def utc_inicio(self) -> datetime:
        """Início do 1º mês UTC da lista (inclusive)."""
        return _inicio_do_mes_utc(self.particoes_utc[0])

    @property
    def utc_fim(self) -> datetime:
        """Início do mês UTC seguinte ao último da lista (exclusivo)."""
        return _inicio_do_mes_utc(somar_meses(self.particoes_utc[-1], 1))

    @property
    def raw_mes_inicio(self) -> date:
        """Primeiro mês local do raw que o dbt lê (regra 1): o da primeira hora de utc_inicio."""
        return _mes_local_de(self.utc_inicio)

    @property
    def raw_mes_fim(self) -> date:
        """Último mês local do raw que o dbt lê, inclusive (regra 1): o da última hora UTC."""
        return _mes_local_de(self.utc_fim - timedelta(hours=1))

    @property
    def meses_raw_lidos(self) -> list[date]:
        return meses_entre(self.raw_mes_inicio, self.raw_mes_fim)

    def vars_dbt(self) -> dict:
        """Variáveis do dbt (`--vars`), todas datas ISO. O modelo só repete estes limites."""
        return {
            "utc_inicio": self.utc_inicio.date().isoformat(),
            "utc_fim": self.utc_fim.date().isoformat(),
            "particoes_utc": [m.isoformat() for m in self.particoes_utc],
            "raw_mes_inicio": self.raw_mes_inicio.isoformat(),
            "raw_mes_fim": self.raw_mes_fim.isoformat(),
        }


def ultimo_mes_de_particoes(ids: list[str]) -> date | None:
    """Mês do último dado do raw, a partir dos `partition_id` do INFORMATION_SCHEMA.PARTITIONS.

    Ignora `__NULL__`, `__UNPARTITIONED__` e qualquer id que não seja `AAAAMM`. Sem partição
    válida devolve None (a tabela está vazia ou não é particionada: quem decide é o chamador).
    """
    meses = []
    for id_ in ids:
        achou = _PADRAO_PARTICAO.match(id_)
        if achou and 1 <= int(achou[2]) <= 12:
            meses.append(date(int(achou[1]), int(achou[2]), 1))
    return max(meses) if meses else None


def calcular_janela(
    referencia: date,
    ultimo_mes_no_raw: date | None = None,
    meses: int = MESES_PADRAO,
) -> Janela:
    """Janela da execução: de (referência - (meses-1)) até o mês da referência, autocorretiva.

    `referencia` é a data lógica da execução (nunca `datetime.now()`).
    `ultimo_mes_no_raw`: mês do último dado já presente no raw; se for anterior ao início padrão,
    a janela começa nele (regra 5) e loga o aviso.
    """
    if meses < 1:
        raise ValueError(f"A janela precisa de pelo menos 1 mês, não {meses}")
    mes_final = primeiro_dia(referencia)
    inicio = somar_meses(mes_final, -(meses - 1))
    estendida = False
    if ultimo_mes_no_raw is not None and primeiro_dia(ultimo_mes_no_raw) < inicio:
        inicio, estendida = primeiro_dia(ultimo_mes_no_raw), True
        log.warning(
            "janela estendida: o último dado do raw é de %s (anterior ao início padrão); "
            "recarregando de %s a %s",
            ultimo_mes_no_raw.strftime("%Y-%m"),
            inicio.strftime("%Y-%m"),
            mes_final.strftime("%Y-%m"),
        )
    if inicio < PRIMEIRO_MES:
        raise ValueError(f"O ONS publica a partir de {PRIMEIRO_MES:%Y-%m}, não de {inicio:%Y-%m}")
    return Janela(inicio, mes_final, estendida)


def _mes_de_texto(texto: str) -> date:
    achou = _PADRAO_MES.match(texto.strip())
    if not achou or not 1 <= int(achou[2]) <= 12:
        raise ValueError(f"Mês inválido: {texto!r} (use AAAA-MM)")
    return date(int(achou[1]), int(achou[2]), 1)


def janela_de_intervalo(desde: str, ate: str) -> Janela:
    """Backfill: janela explícita `--desde AAAA-MM --ate AAAA-MM` (ambos inclusive)."""
    inicio, fim = _mes_de_texto(desde), _mes_de_texto(ate)
    if fim < inicio:
        raise ValueError(f"--ate ({ate}) é anterior a --desde ({desde})")
    if inicio < PRIMEIRO_MES:
        raise ValueError(f"O ONS publica a partir de {PRIMEIRO_MES:%Y-%m}, não de {desde}")
    return Janela(inicio, fim)


def cobrindo(janela: Janela, particoes: list[str]) -> Janela:
    """Janela do DBT: a janela do raw ampliada para cobrir tudo o que o raw recarregou (`AAAAMM`).

    O raw pode recarregar mais que a janela: um ano fechado cujo ETag mudou, ou o ano inteiro quando
    a guarda acha revisão fora da janela. O dbt precisa reprocessar esses meses também, senão o
    staging e o fato ficariam desatualizados. A janela do dbt é UM intervalo contínuo (do menor ao
    maior mês), porque o filtro do modelo e a lista de partições têm de cobrir o mesmo intervalo
    (regra 2). Reprocessar um mês que não mudou é só trabalho a mais, nunca dado errado.
    """
    meses = [janela.mes_inicial, janela.mes_final]
    for particao in particoes:
        achou = _PADRAO_PARTICAO.match(particao)
        if not achou or not 1 <= int(achou[2]) <= 12:
            raise ValueError(f"Partição inválida: {particao!r} (use AAAAMM)")
        meses.append(date(int(achou[1]), int(achou[2]), 1))
    return Janela(min(meses), max(meses), janela.estendida)


def montar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Janela do incremental do ONS: gera as vars do dbt (ponto único)"
    )
    parser.add_argument("--formato", choices=["dbt-vars"], required=True)
    parser.add_argument("--data-referencia", type=date.fromisoformat, help="AAAA-MM-DD")
    parser.add_argument("--ultimo-mes-raw", help="AAAA-MM do último dado do raw (autocorreção)")
    parser.add_argument("--meses", type=int, default=MESES_PADRAO)
    parser.add_argument("--desde", help="backfill: AAAA-MM (com --ate)")
    parser.add_argument("--ate", help="backfill: AAAA-MM, inclusive (com --desde)")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Imprime, em UMA linha de JSON, as vars para `dbt --vars` (os avisos vão para o stderr)."""
    parser = montar_parser()
    args = parser.parse_args(argv)
    if bool(args.desde) != bool(args.ate):
        parser.error("--desde e --ate andam juntos")
    if args.desde and (args.data_referencia or args.ultimo_mes_raw):
        parser.error("--desde/--ate não combinam com --data-referencia nem --ultimo-mes-raw")
    if not args.desde and not args.data_referencia:
        parser.error("informe --data-referencia ou --desde/--ate")
    for handler in log.handlers:  # stdout é só o JSON
        if hasattr(handler, "setStream"):
            handler.setStream(sys.stderr)
    if args.desde:
        janela = janela_de_intervalo(args.desde, args.ate)
    else:
        ultimo = _mes_de_texto(args.ultimo_mes_raw) if args.ultimo_mes_raw else None
        janela = calcular_janela(args.data_referencia, ultimo, args.meses)
    print(json.dumps(janela.vars_dbt(), separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
