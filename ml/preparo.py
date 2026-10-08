"""Preparo da série de treino (tarefas 5.1 e decisões da Sprint 5): janela móvel e choque da COVID.

TUDO AQUI RECEBE SÓ O HISTÓRICO VISÍVEL NA ORIGEM (`visao_na_origem`) e devolve outro histórico.

1. JANELA MÓVEL DE 72 MESES (`JANELA_MESES`). O treino usa os últimos 72 meses até a origem, e não
   a série inteira desde 2000. Dois motivos, medidos (docs/decisoes.md): (a) o crescimento da carga
   mudou de regime (cerca de +3,5% ao ano até 2014 e 0 a 1% em 2015-2019) e uma tendência estimada
   no histórico inteiro erra muito; (b) a série longa de treino do teste final só é consistente
   (tipo III reconstruído) a partir de 2015-01, e 72 meses é exatamente o que cabe na origem de
   dez/2020. Com 120 meses a janela incluiria 2011-2014, uma quebra NÃO tratada que o
   desenvolvimento (série original, sem quebra) não revelaria.

2. CHOQUE DA COVID (`EVENTO_COVID`). Os meses do evento cuja variação anual desvia mais que
   K_SIGMA desvios-padrão da variação anual pré-choque são TROCADOS por (mesmo mês do ano anterior)
   x (crescimento dos 12 meses anteriores ao evento). O indicador abr-dez foi descartado: o choque
   se concentra em abr-jun e o segundo semestre rebate, e um indicador constante gerou viés de +4%
   a +10% na simulação. A regra usa só dados até a origem: o mês é julgado com a distribuição
   pré-evento (anterior à origem por construção) e o próprio mês só entra se `mes <= origem`.
"""

import math
from datetime import date
from statistics import mean, stdev

from ml.validacao import Serie, meses_entre, somar_meses, visao_na_origem

JANELA_MESES = 72
# Evento exógeno conhecido, definido antes de olhar os resultados.
EVENTO_COVID = (date(2020, 3, 1), date(2020, 12, 1))
K_SIGMA = 2.0
REF_MESES = 36  # meses de variação anual anteriores ao evento que definem o "normal"


def meses_de_choque(historico: Serie, origem: date, evento=EVENTO_COVID) -> list[date]:
    """Meses do evento, até a origem, cuja variação anual foge do normal pré-evento."""
    inicio, fim = evento
    if origem < inicio:
        return []
    ref = meses_entre(somar_meses(inicio, -REF_MESES), somar_meses(inicio, -1))
    try:
        g_ref = [math.log(historico[m] / historico[somar_meses(m, -12)]) for m in ref]
    except KeyError:
        return []  # sem histórico para definir o normal: não se sinaliza nada
    mu, dp = mean(g_ref), stdev(g_ref)
    sinalizados = []
    for m in meses_entre(inicio, min(fim, origem)):
        if m in historico and somar_meses(m, -12) in historico:
            g = math.log(historico[m] / historico[somar_meses(m, -12)])
            if abs(g - mu) > K_SIGMA * dp:
                sinalizados.append(m)
    return sinalizados


def imputar_choque(historico: Serie, origem: date, evento=EVENTO_COVID) -> tuple[Serie, list[date]]:
    """Troca os meses sinalizados por (mesmo mês do ano anterior) x (crescimento pré-evento)."""
    meses = meses_de_choque(historico, origem, evento)
    if not meses:
        return dict(historico), []
    inicio = evento[0]
    recentes = [historico[somar_meses(inicio, -i)] for i in range(1, 13)]
    anteriores = [historico[somar_meses(inicio, -i)] for i in range(13, 25)]
    crescimento = sum(recentes) / sum(anteriores)
    saida = dict(historico)
    for m in meses:
        saida[m] = historico[somar_meses(m, -12)] * crescimento
    return saida, meses


def janela(historico: Serie, meses: int = JANELA_MESES) -> Serie:
    """Os últimos `meses` meses do histórico; ValueError se houver buraco ou pouca história."""
    ultimo = max(historico)
    corte = meses_entre(somar_meses(ultimo, -(meses - 1)), ultimo)
    faltam = [m for m in corte if m not in historico]
    if faltam:
        raise ValueError(
            f"janela de {meses} meses incompleta (faltam {len(faltam)}, ex.: {faltam[0]})"
        )
    return {m: historico[m] for m in corte}


def preparar(
    historico: Serie, origem: date, meses: int = JANELA_MESES, evento=EVENTO_COVID
) -> Serie:
    """O que um modelo treina: visão na origem -> choque imputado -> janela móvel."""
    visivel = visao_na_origem(historico, origem)
    if origem not in visivel:
        raise ValueError(f"a origem {origem} não está na série")
    corrigido, _ = imputar_choque(visivel, origem, evento)
    return janela(corrigido, meses)
