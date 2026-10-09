"""Orquestrador dos cenários (5.6 e 5.7): dados do PLD, linhas e identificação da execução."""

from datetime import UTC, date, datetime, timedelta

from ml.cenarios import (
    CHAVE_PLD,
    ESQUEMA_EXECUCAO,
    ESQUEMA_PLD,
    ddl,
    excecoes_da_seed,
    impressao_do_pld,
    limites_da_seed,
    linhas_de_pld,
    montar_dados_pld,
)
from ml.cenarios_consumo import execucao_id
from ml.cenarios_pld import bootstrap, historico_ate, meses_alvo


def semanal_sintetico():
    """Semanas de 2002 a 2020; em 1 de cada 5 semanas os 3 patamares valem o piso do ano."""
    linhas = []
    inicio = datetime(2002, 1, 5, 3, tzinfo=UTC)
    k = 0
    while inicio.year < 2021:
        fim = inicio + timedelta(days=7)
        piso = 10.0 + (inicio + timedelta(days=3)).year - 2002
        for p in (piso if k % 5 == 0 else 100.0 + k % 7,) * 3:
            linhas.append(
                {
                    "data_inicio_semana": (inicio - timedelta(hours=3)).date(),
                    "inicio_semana_utc": inicio,
                    "fim_semana_utc": fim,
                    "pld": p,
                }
            )
        inicio, k = fim, k + 1
    return linhas


def test_montar_dados_pld_junta_semanal_e_horario_e_detecta_os_pisos():
    ponderado = [{"mes": date(2021, m, 1), "pld": 150.0 + m} for m in range(1, 13)]
    d = montar_dados_pld(semanal_sintetico(), ponderado)
    assert min(d.serie) == date(2002, 1, 1) and max(d.serie) == date(2021, 12, 1)
    assert d.serie[date(2021, 3, 1)] == 153.0  # 2021 em diante vem do PLD ponderado
    assert d.detectados[2010] == 18.0 and d.detectados[2002] == 10.0
    assert 2021 not in d.detectados  # o piso de 2021+ vem da seed
    pisos = d.pisos()
    assert pisos[2004] == excecoes_da_seed()[2004] == 18.59  # a exceção vale mesmo se há detectado
    assert pisos[2021] == limites_da_seed()[2021][0]


def test_seeds_de_limites_e_excecoes():
    lim = limites_da_seed()
    assert set(lim) == set(range(2021, 2027))
    piso, teto = lim[2024]
    assert (piso, teto) == (61.07, 716.8)  # teto ESTRUTURAL, não o horário
    assert excecoes_da_seed() == {2004: 18.59, 2019: 42.35}


def test_linhas_de_pld_tem_n_x_12_linhas_e_chave_unica():
    d = montar_dados_pld(semanal_sintetico(), [])
    t = date(2020, 12, 1)
    hist = historico_ate(d.serie, t)
    cen = bootstrap(
        "blocos", hist, t, 5, 0, {a: 10.0 for a in range(2002, 2027)}, limites_da_seed()
    )
    linhas = linhas_de_pld("x", t, "blocos", cen)
    assert len(linhas) == 5 * 12
    chave = {tuple(r[c] for c in CHAVE_PLD) for r in linhas}
    assert len(chave) == 60
    assert {r["mes_alvo"] for r in linhas} == {m.isoformat() for m in meses_alvo(t)}
    assert {r["nome"] for r in [{"nome": n} for n, _ in ESQUEMA_PLD]} >= set(linhas[0])


def test_execucao_id_muda_com_o_pld_e_nao_com_a_ordem_dos_extras():
    h1, h2 = {date(2020, 1, 1): 10.0}, {date(2020, 1, 1): 11.0}
    base = execucao_id(2000, 0, 1e-6, {}, {"pld": impressao_do_pld(h1), "pisos": "a"})
    assert base == execucao_id(2000, 0, 1e-6, {}, {"pisos": "a", "pld": impressao_do_pld(h1)})
    assert base != execucao_id(2000, 0, 1e-6, {}, {"pld": impressao_do_pld(h2), "pisos": "a"})
    assert base != execucao_id(2000, 0, 1e-6, {}, {"pld": impressao_do_pld(h1), "pisos": "b"})


def test_ddl_e_esquema_de_execucao_tem_a_proveniencia():
    colunas = {n for n, _ in ESQUEMA_EXECUCAO}
    assert {"execucao_id", "origem", "codigo_hash", "commit", "gerado_em", "pld_hash"} <= colunas
    sql = ddl("marts.fct_cenario_pld", ESQUEMA_PLD, CHAVE_PLD)
    assert "CREATE TABLE IF NOT EXISTS" in sql and "mes_historico" in sql
