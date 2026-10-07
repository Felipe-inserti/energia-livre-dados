import logging
from datetime import UTC, date, datetime, timedelta

import pytest

from ingestion import janela
from ingestion.janela import Janela, calcular_janela, janela_de_intervalo


def meses(j: Janela) -> list[str]:
    return [m.strftime("%Y-%m") for m in j.meses_locais]


# --- cálculo da janela -------------------------------------------------------------------------


def test_janela_padrao_e_o_mes_corrente_e_os_dois_anteriores():
    j = calcular_janela(date(2026, 10, 6))
    assert meses(j) == ["2026-08", "2026-09", "2026-10"]
    assert j.particoes_raw == ["202608", "202609", "202610"]
    assert not j.estendida


@pytest.mark.parametrize("dia", [date(2026, 10, 1), date(2026, 10, 31)])
def test_primeiro_e_ultimo_dia_do_mes_dao_a_mesma_janela(dia):
    assert meses(calcular_janela(dia)) == ["2026-08", "2026-09", "2026-10"]


def test_tamanho_da_janela_e_configuravel_e_recusa_zero():
    assert meses(calcular_janela(date(2026, 10, 6), meses=1)) == ["2026-10"]
    assert len(calcular_janela(date(2026, 10, 6), meses=6).meses_locais) == 6
    with pytest.raises(ValueError):
        calcular_janela(date(2026, 10, 6), meses=0)


def test_virada_de_ano_cruza_dois_arquivos():
    j = calcular_janela(date(2027, 1, 15))
    assert meses(j) == ["2026-11", "2026-12", "2027-01"]
    assert j.anos == [2026, 2027]
    assert j.particoes_raw == ["202611", "202612", "202701"]


def test_fora_de_janeiro_baixa_so_um_arquivo():
    assert calcular_janela(date(2026, 10, 6)).anos == [2026]
    assert calcular_janela(date(2026, 3, 1)).anos == [2026]  # jan, fev e mar
    assert calcular_janela(date(2026, 2, 1)).anos == [2025, 2026]  # dez, jan e fev


def test_o_resultado_depende_so_dos_argumentos():
    a = calcular_janela(date(2026, 10, 6), date(2026, 7, 1))
    assert a == calcular_janela(date(2026, 10, 6), date(2026, 7, 1))
    assert a == calcular_janela(date(2026, 10, 7), date(2026, 7, 1))  # mesmo mês: igual
    assert a == calcular_janela(date(2026, 10, 31), date(2026, 7, 1))


def test_anterior_a_2000_e_recusado():
    with pytest.raises(ValueError):
        calcular_janela(date(2000, 1, 5))


# --- janela autocorretiva (acréscimo 4) --------------------------------------------------------


def test_raw_em_dia_nao_estende(caplog, monkeypatch):
    monkeypatch.setattr(janela.log, "propagate", True)
    with caplog.at_level(logging.WARNING, logger="ingestion.janela"):
        j = calcular_janela(date(2026, 10, 6), date(2026, 10, 1))
    assert not j.estendida
    assert meses(j) == ["2026-08", "2026-09", "2026-10"]
    assert not caplog.records


def test_raw_com_ultimo_dado_dentro_da_janela_nao_estende():
    # o último mês presente (agosto) é o início padrão: nada a estender
    assert not calcular_janela(date(2026, 10, 6), date(2026, 8, 1)).estendida


def test_periodo_longo_sem_execucao_estende_o_inicio_e_loga(caplog, monkeypatch):
    monkeypatch.setattr(janela.log, "propagate", True)
    with caplog.at_level(logging.WARNING, logger="ingestion.janela"):
        j = calcular_janela(date(2026, 10, 6), date(2026, 5, 20))
    assert j.estendida
    assert meses(j) == ["2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]
    assert {r.levelname for r in caplog.records} == {"WARNING"}
    assert "2026-05" in caplog.text and "estendida" in caplog.text


def test_estender_pela_virada_de_ano_baixa_os_dois_arquivos():
    j = calcular_janela(date(2027, 2, 3), date(2026, 11, 30))
    assert j.anos == [2026, 2027]
    assert meses(j)[0] == "2026-11"


def test_sem_informacao_do_raw_usa_a_janela_padrao():
    j = calcular_janela(date(2026, 10, 6), None)
    assert not j.estendida and len(j.meses_locais) == 3


def test_ultimo_mes_a_partir_dos_ids_de_particao():
    ids = ["202607", "202610", "202609", "__NULL__", "__UNPARTITIONED__", "20261", "202613"]
    assert janela.ultimo_mes_de_particoes(ids) == date(2026, 10, 1)
    assert janela.ultimo_mes_de_particoes(["__NULL__", "NULL"]) is None
    assert janela.ultimo_mes_de_particoes([]) is None


# --- backfill ---------------------------------------------------------------------------------


def test_backfill_por_intervalo_e_inclusivo():
    j = janela_de_intervalo("2021-01", "2021-03")
    assert meses(j) == ["2021-01", "2021-02", "2021-03"]
    assert janela_de_intervalo("2026-10", "2026-10").meses_locais == [date(2026, 10, 1)]
    assert janela_de_intervalo("2025-11", "2026-02").anos == [2025, 2026]


@pytest.mark.parametrize(
    ("desde", "ate"),
    [
        ("2026-10", "2026-09"),
        ("1999-12", "2000-02"),
        ("2026-13", "2026-14"),
        ("2026/10", "2026-10"),
    ],
)
def test_backfill_recusa_intervalo_invalido(desde, ate):
    with pytest.raises(ValueError):
        janela_de_intervalo(desde, ate)


# --- partições UTC, as duas bordas e a leitura do raw (regras 1 a 3) ----------------------------


def test_janela_ate_setembro_toca_outubro_utc_e_le_o_raw_de_outubro():
    """Regra 1: partições jul a out => o raw lido inclui outubro local (senão, perda de dado)."""
    j = janela_de_intervalo("2026-07", "2026-09")
    assert j.particoes_utc == [date(2026, m, 1) for m in (7, 8, 9, 10)]
    assert j.utc_inicio == datetime(2026, 7, 1, tzinfo=UTC)
    assert j.utc_fim == datetime(2026, 11, 1, tzinfo=UTC)
    assert j.raw_mes_inicio == date(2026, 6, 1)  # 01/07 00h UTC é 30/06 21h local
    assert j.raw_mes_fim == date(2026, 10, 1)  # a última hora de outubro UTC é 31/10 20h local
    assert date(2026, 10, 1) in j.meses_raw_lidos
    assert date(2026, 11, 1) not in j.meses_raw_lidos
    # o que o load job recarrega no raw continua sendo só a janela local (regra 4)
    assert j.particoes_raw == ["202607", "202608", "202609"]


def test_borda_inicial_31_08_21h_local_e_setembro_utc():
    # a primeira hora de setembro UTC (01/09 00h) é 31/08 21h local: o raw de agosto tem de ser lido
    j = janela_de_intervalo("2026-09", "2026-09")
    assert j.particoes_utc[0] == date(2026, 9, 1)
    assert j.raw_mes_inicio == date(2026, 8, 1)


def test_borda_final_30_09_21h_local_e_outubro_utc():
    j = janela_de_intervalo("2026-09", "2026-09")
    assert j.particoes_utc == [date(2026, 9, 1), date(2026, 10, 1)]
    hora = datetime(2026, 9, 30, 21, tzinfo=janela.FUSO_LOCAL).astimezone(UTC)
    assert hora == datetime(2026, 10, 1, 0, tzinfo=UTC)
    assert j.utc_inicio <= hora < j.utc_fim  # inserida E a partição de outubro é apagada


def test_vars_do_dbt_sao_datas_iso_com_os_mesmos_limites():
    v = janela_de_intervalo("2026-07", "2026-09").vars_dbt()
    assert v == {
        "utc_inicio": "2026-07-01",
        "utc_fim": "2026-11-01",
        "particoes_utc": ["2026-07-01", "2026-08-01", "2026-09-01", "2026-10-01"],
        "raw_mes_inicio": "2026-06-01",
        "raw_mes_fim": "2026-10-01",
    }


def test_janela_diaria_inclui_o_mes_utc_seguinte_so_com_as_horas_da_borda():
    j = calcular_janela(date(2026, 10, 6))
    assert j.particoes_utc[-1] == date(2026, 11, 1)  # as 3 h finais de 31/10 local
    assert j.raw_mes_fim == date(2026, 11, 1)  # o raw lido vai até novembro (ainda sem dados)


def _horas(inicio: datetime, fim: datetime):
    h = inicio
    while h < fim:
        yield h
        h += timedelta(hours=1)


@pytest.mark.parametrize("ano", [2017, 2018, 2019, 2026])  # com e sem horário de verão
def test_invariantes_para_todas_as_janelas_do_ano(ano):
    """Para qualquer janela: (a) toda hora de toda partição UTC sobrescrita tem o seu mês local
    entre os meses lidos do raw (nada é apagado sem ser recomposto) e (b) toda hora dos meses
    locais recarregados cai dentro de [utc_inicio, utc_fim) (nada é inserido sem a partição ser
    apagada). As partições são contíguas e a lista bate com o intervalo."""
    for mes in range(1, 13):
        for tamanho in (1, 2, 3):
            ini = date(ano, mes, 1)
            j = Janela(ini, janela.somar_meses(ini, tamanho - 1))
            lidos = set(j.meses_raw_lidos)
            for hora in _horas(j.utc_inicio, j.utc_fim):
                assert janela._mes_local_de(hora) in lidos, (ini, tamanho, hora)
            for m in j.meses_locais:
                primeira = janela._inicio_do_mes_local(m)
                ultima = janela._inicio_do_mes_local(janela.somar_meses(m, 1)) - timedelta(hours=1)
                assert j.utc_inicio <= primeira and ultima < j.utc_fim
            assert j.particoes_utc == janela.meses_entre(j.particoes_utc[0], j.particoes_utc[-1])
            assert j.utc_inicio == datetime.combine(j.particoes_utc[0], datetime.min.time(), UTC)
