"""Calendário mensal (tarefa 5.1): variáveis conhecidas na origem para QUALQUER horizonte.

Dias úteis, feriados e número de dias de um mês futuro dependem só da data, não de nenhum dado
observado depois da origem; por isso entram nos modelos sem vazamento. Há um teste que garante que
nada aqui recebe a série de carga.

DIAS ÚTEIS EFETIVOS. Segunda a sexta, menos os feriados nacionais da biblioteca `holidays` (a mesma
lista da `dim_tempo`), menos a segunda e a terça de Carnaval e o Corpus Christi. A `dim_tempo` não
trata Carnaval nem Corpus Christi como feriado (a loja não fecha), mas a CARGA do SE/CO cai nesses
dias por causa da indústria, e é a carga que se prevê. Pascoa é calculada (algoritmo anônimo
gregoriano), sem depender de outra biblioteca.
"""

from datetime import date, timedelta
from functools import cache

import holidays

_FERIADOS = holidays.Brazil(years=range(1999, 2036))


def pascoa(ano: int) -> date:
    a, b, c = ano % 19, ano // 100, ano % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    mes = (h + l_ - 7 * m + 114) // 31
    dia = (h + l_ - 7 * m + 114) % 31 + 1
    return date(ano, mes, dia)


@cache
def calendario(mes: date) -> dict[str, int]:
    """Contagens do mês que começa em `mes` (primeiro dia)."""
    p = pascoa(mes.year)
    nao_uteis_extras = {p - timedelta(48), p - timedelta(47), p + timedelta(60)}
    proximo = date(mes.year + (mes.month == 12), mes.month % 12 + 1, 1)
    dias = [mes + timedelta(i) for i in range((proximo - mes).days)]
    uteis = [d for d in dias if d.weekday() < 5 and d not in _FERIADOS]
    efetivos = [d for d in uteis if d not in nao_uteis_extras]
    return {"ndias": len(dias), "uteis": len(uteis), "uteis_efetivos": len(efetivos)}
