"""`ml/metricas.py` e `ml/avaliar.py`: sinal do viés, erro por horizonte, ausência de vazamento de
futuro, meses não utilizáveis fora e a proteção do teste final."""

import json
from datetime import date

import pytest

from ml import avaliar as a
from ml import metricas as m
from ml import validacao as v

DEV = v.PERIODOS["desenvolvimento"]


def reg(previsto, real, h=1, origem=date(2015, 12, 1), serie="original", baseline="x"):
    return m.Registro(serie, baseline, origem, h, v.somar_meses(origem, h), previsto, real)


def sintetica(fim=date(2020, 12, 1), ruido=True):
    s = {}
    for i, mes in enumerate(v.meses_entre(date(2000, 1, 1), fim)):
        # sazonalidade + tendência + um ruído determinístico que muda o crescimento de ano a ano
        s[mes] = 1000 + 4 * i + 80 * ((mes.month * 7) % 12) + (60 * ((i * 37) % 11) if ruido else 0)
    return s


def linhas_do_mart(serie, nao_utilizaveis=()):
    return [
        {
            "mes": mes,
            "carga_original_mwmed": valor,
            "carga_ajustada_mwmed": valor if mes >= date(2018, 1, 1) else None,
            "mes_utilizavel": mes not in nao_utilizaveis,
        }
        for mes, valor in serie.items()
    ]


def series_de(linhas):
    return {n: v.serie_utilizavel(linhas, c) for n, c in a.SERIES.items()}


# ---------------------------------------------------------------- métricas


def test_metricas_com_numeros_conferidos_a_mao():
    r = m.metricas([reg(110.0, 100.0), reg(90.0, 100.0)])
    assert r == {"n": 2, "mape_pct": 10.0, "mae_mwmed": 10.0, "vies_mwmed": 0.0, "vies_pct": 0.0}


def test_sinal_do_vies_positivo_quando_preve_acima_e_negativo_quando_preve_abaixo():
    acima = m.metricas([reg(110.0, 100.0), reg(220.0, 200.0)])
    abaixo = m.metricas([reg(90.0, 100.0), reg(180.0, 200.0)])
    assert acima["vies_mwmed"] == 15.0 and acima["vies_pct"] == pytest.approx(10.0)
    assert abaixo["vies_mwmed"] == -15.0 and abaixo["vies_pct"] == pytest.approx(-10.0)
    assert acima["mape_pct"] == abaixo["mape_pct"] == pytest.approx(10.0)  # o MAPE esconde o sinal


def test_metricas_de_conjunto_vazio_nao_inventam_numero():
    assert m.metricas([])["mape_pct"] is None and m.metricas([])["n"] == 0


def test_por_horizonte_tem_12_linhas_mais_a_geral():
    linhas = m.por_horizonte([reg(110.0, 100.0, h=h) for h in v.HORIZONTES])
    assert [x["horizonte"] for x in linhas] == [*v.HORIZONTES, "geral"]
    assert linhas[-1]["n"] == 12


def test_erro_anual_compara_a_media_dos_12_meses_e_ignora_ano_incompleto():
    completos = [reg(110.0, 100.0, h=h) for h in v.HORIZONTES]  # origem 2015-12: alvos de 2016
    incompleto = [
        m.Registro("s", "b", date(2016, 12, 1), h, v.somar_meses(date(2016, 12, 1), h), 1.0, 1.0)
        for h in range(1, 7)
    ]
    (linha,) = m.erro_anual([*completos, *incompleto])
    assert (
        linha["ano"] == 2016
        and linha["erro_mwmed"] == 10.0
        and linha["erro_pct"] == pytest.approx(10.0)
    )


# ---------------------------------------------------------------- pipeline


def mapa(registros):
    return {(r.serie, r.baseline, r.origem, r.horizonte): r.previsto for r in registros}


def test_sem_vazamento_serie_adulterada_depois_da_origem_nao_muda_a_previsao():
    base = sintetica()
    corte = date(2015, 6, 1)
    adulterada = {mes: (valor * 10 if mes > corte else valor) for mes, valor in base.items()}
    r1 = a.gerar_registros(series_de(linhas_do_mart(base)), DEV)
    r2 = a.gerar_registros(series_de(linhas_do_mart(adulterada)), DEV)
    p1, p2 = mapa(r1), mapa(r2)
    antes_do_corte = [k for k in p1 if k[2] <= corte]
    assert len(antes_do_corte) > 100  # o teste tem dentes: há muitas previsões com origem <= corte
    assert all(p1[k] == p2[k] for k in antes_do_corte)
    # e o futuro mudou de verdade: o valor REAL dos alvos depois do corte é outro
    reais1 = {(r.serie, r.baseline, r.origem, r.horizonte): r.real for r in r1}
    reais2 = {(r.serie, r.baseline, r.origem, r.horizonte): r.real for r in r2}
    assert any(reais1[k] != reais2[k] for k in antes_do_corte)
    # e depois do corte as previsões mudam (a origem já enxerga os valores adulterados)
    assert any(p1[k] != p2[k] for k in p1 if k[2] > corte and k[2].year >= 2017)


def test_o_ingenuo_preve_o_mesmo_valor_para_um_alvo_em_qualquer_horizonte():
    registros = a.gerar_registros(series_de(linhas_do_mart(sintetica())), DEV)
    ingenuo = [r for r in registros if r.baseline == "sazonal_ingenuo" and r.serie == "original"]
    por_alvo = {}
    for r in ingenuo:
        por_alvo.setdefault(r.alvo, set()).add(r.previsto)
    assert len(por_alvo) == 96 and all(len(x) == 1 for x in por_alvo.values())


def test_o_ingenuo_tem_o_mesmo_erro_em_todos_os_horizontes_e_o_de_crescimento_nao():
    registros = a.gerar_registros(series_de(linhas_do_mart(sintetica())), DEV)
    mape = {}
    for baseline in ("sazonal_ingenuo", "sazonal_crescimento"):
        rs = [r for r in registros if r.baseline == baseline and r.serie == "original"]
        linhas = m.por_horizonte(rs)[:-1]
        assert all(x["n"] == 96 for x in linhas)  # cada horizonte avalia os mesmos 96 alvos
        mape[baseline] = [x["mape_pct"] for x in linhas]
    assert max(mape["sazonal_ingenuo"]) == pytest.approx(min(mape["sazonal_ingenuo"]))
    assert max(mape["sazonal_crescimento"]) - min(mape["sazonal_crescimento"]) > 0.1


def test_mes_nao_utilizavel_nao_e_alvo_nem_base_nem_origem():
    ruim = date(2015, 5, 1)  # por exemplo, um mês sem cobertura
    registros = a.gerar_registros(
        series_de(linhas_do_mart(sintetica(), nao_utilizaveis={ruim})), DEV
    )
    original = [r for r in registros if r.serie == "original"]
    assert all(r.alvo != ruim and r.origem != ruim for r in original)  # nem alvo nem origem
    ingenuo = [r for r in original if r.baseline == "sazonal_ingenuo"]
    assert not [r for r in ingenuo if v.somar_meses(r.alvo, -12) == ruim]  # nem base do ingênuo
    crescimento = [r for r in original if r.baseline == "sazonal_crescimento"]
    for r in crescimento:  # nem dentro dos 24 meses do crescimento
        assert ruim not in {v.somar_meses(r.origem, -i) for i in range(24)}


def test_o_mes_corrente_fica_fora_porque_a_serie_so_tem_meses_utilizaveis():
    s = sintetica(fim=date(2020, 10, 1))
    linhas = linhas_do_mart(s, nao_utilizaveis={date(2020, 10, 1)})  # outubro ainda corre
    serie = v.serie_utilizavel(linhas, "carga_original_mwmed")
    assert date(2020, 10, 1) not in serie and max(serie) == date(2020, 9, 1)


def test_a_ajustada_so_aparece_onde_existe_e_a_original_e_comparada_nos_mesmos_pares():
    registros = a.com_original_nos_pares_da_ajustada(
        a.gerar_registros(series_de(linhas_do_mart(sintetica())), DEV)
    )
    ajustada = [r for r in registros if r.serie == "ajustada"]
    assert ajustada and all(r.alvo >= date(2019, 1, 1) for r in ajustada)  # base >= 2018-01
    assert all(r.baseline == "sazonal_ingenuo" for r in ajustada)  # o crescimento pede 24 meses
    chaves = {(r.baseline, r.origem, r.horizonte) for r in ajustada}
    pares = [r for r in registros if r.serie == a.SERIE_COMPARACAO]
    assert {(r.baseline, r.origem, r.horizonte) for r in pares} == chaves


# ---------------------------------------------------------------- proteções e gravação


def test_a_consulta_nao_le_nada_depois_do_ultimo_mes_alvo():
    sql = a.sql_serie(DEV)
    assert "DATE '2019-12-01'" in sql and "2020" not in sql and "2021" not in sql


def test_o_teste_final_e_recusado_sem_a_autorizacao_explicita(monkeypatch, capsys):
    def nao_deve_ler(_periodo):
        raise AssertionError("leu da nuvem antes de a autorização ser dada")

    monkeypatch.setattr(a, "carregar_da_nuvem", nao_deve_ler)
    assert a.main(["--periodo", "teste_final"]) == 2
    assert "RECUSADO" in capsys.readouterr().err
    with pytest.raises(AssertionError, match="leu da nuvem"):  # com a opção, segue para a leitura
        a.main(["--periodo", "teste_final", "--liberar-teste-final"])


def test_gravacao_cria_os_arquivos_com_data_e_commit_no_meta(tmp_path):
    linhas = linhas_do_mart(sintetica())
    a.avaliar(DEV, linhas, {"bytes_processados": 123, "seed_consultado_em": "2026-10-07"}, tmp_path)
    nomes = sorted(p.name for p in tmp_path.iterdir())
    assert nomes == [
        "baseline_desenvolvimento.meta.json",
        "baseline_desenvolvimento_erro_anual.csv",
        "baseline_desenvolvimento_por_horizonte.csv",
        "baseline_desenvolvimento_previsoes.csv",
    ]
    meta = json.loads((tmp_path / "baseline_desenvolvimento.meta.json").read_text())
    assert len(meta["commit"]) == 40 and "gerado_em_utc" in meta and "arvore_com_mudancas" in meta
    assert meta["periodo"] == "desenvolvimento" and meta["submercado"] == "SE"
    assert meta["seed_consultado_em"] == "2026-10-07"
    cabecalho = (
        (tmp_path / "baseline_desenvolvimento_por_horizonte.csv").read_text().splitlines()[0]
    )
    assert cabecalho == "serie,baseline,recorte,horizonte,n,mape_pct,mae_mwmed,vies_mwmed,vies_pct"


def test_defesa_em_profundidade_um_baseline_que_tenta_ler_o_alvo_nao_encontra_nada(monkeypatch):
    """Mesmo um baseline escrito errado (que lê o próprio alvo) não vaza: ele só recebe a visão
    cortada na origem, onde o alvo não existe, e então não há previsão alguma."""
    monkeypatch.setattr(
        a, "BASELINES", {"ler_o_alvo": lambda hist, origem, h: hist.get(v.somar_meses(origem, h))}
    )
    assert a.gerar_registros(series_de(linhas_do_mart(sintetica())), DEV) == []


def test_os_proprios_resultados_nao_contam_como_mudanca_na_arvore(monkeypatch):
    chamadas = []

    def falso(args, **_):
        chamadas.append(args)

        class R:
            stdout = "abc123\n"

        return R()

    monkeypatch.setattr(a.subprocess, "run", falso)
    a.referencia_git()
    status = next(c for c in chamadas if "status" in c)
    assert ":(exclude)docs/resultados" in status
