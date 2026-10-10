"""Cadeia mensal, passo 3 (C1): a prévia da origem mais recente, sem tocar no backtest."""

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pandas as pd
import pytest

from ml import recomendacao as rc
from ml.cenarios import ORIGENS_DE_BACKTEST
from ml.cenarios_consumo import horas_do_mes
from ml.otimizacao import EXECUCAO_CONGELADA, Dados
from ml.previsao import SQL_SERIE
from ml.validacao import HORIZONTES, somar_meses

K = 1e-5
N = 4
MIB = 1024 * 1024
AGORA = datetime(2026, 10, 11, tzinfo=UTC)
PROV = {"commit": "c" * 40, "codigo_hash": "h", "gerado_em": "2026-10-11T00:00:00Z"}
CAB = {"config_hash": "0" * 16, "preregistro": "02990fdf26529b59bd0aec5883f7ca7e9e2443d0"}


def meses(inicio: date, fim: date):
    m = inicio
    while m <= fim:
        yield m
        m = somar_meses(m, 1)


def dados_de_producao(origem: date) -> tuple[Dados, pd.DataFrame]:
    """Cenários simétricos em torno de 0,15 MWm (como o backtest sintético), PLD a 300."""
    alvos = [somar_meses(origem, h) for h in HORIZONTES]
    execucao = [
        {
            "origem": origem,
            "modelo_versao": "m",
            "n_cenarios": N,
            "semente_base": 0,
            "calibracao": "crescente",
            "n_vetores_consumo": 9,
            "erros_hash": "e",
            "k_consumo": K,
            "n_meses_pld": 10,
            "n_blocos_pld": 3,
            "pld_hash": "p",
            "pisos_hash": "q",
            "limites_assumidos": True,
            "codigo_hash": "c",
        }
    ]
    cons, pld = [], []
    for s in range(N):
        fator = 0.8 if s % 2 == 0 else 1.2
        for h, m in zip(HORIZONTES, alvos, strict=True):
            cons.append(
                {
                    "origem": origem,
                    "cenario": s,
                    "horizonte": h,
                    "mes_alvo": m,
                    "consumo_mwh": fator * 0.15 * horas_do_mes(m),
                }
            )
            pld.append(
                {
                    "origem": origem,
                    "metodo": "blocos",
                    "cenario": s,
                    "horizonte": h,
                    "mes_alvo": m,
                    "pld_rs_mwh": 300.0,
                }
            )
    pld_mensal = [
        {
            "mes": m,
            "horas": horas_do_mes(m),
            "horas_esperadas": horas_do_mes(m),
            "mes_completo": True,
            "pld_medio_simples_rs_mwh": 100.0,
            "pld_ponderado_rs_mwh": 250.0,
        }
        for m in meses(date(2025, 1, 1), date(2026, 12, 1))
    ]
    consumo_mensal = pd.DataFrame(
        [
            {"mes": m, "consumo_mwh": 0.15 * horas_do_mes(m), "horas": horas_do_mes(m)}
            for m in meses(date(2025, 1, 1), date(2026, 12, 1))
        ]
    )
    dados = Dados(
        execucao=pd.DataFrame(execucao),
        cenario_consumo=pd.DataFrame(cons),
        cenario_pld=pd.DataFrame(pld),
        previstos=pd.DataFrame(),
        pld_mensal=pd.DataFrame(pld_mensal),
        pld_2020=0.0,
    )
    return dados, consumo_mensal


# ---- a origem mais recente


def exe(origem, id_="x", gerado="2026-10-01T00:00:00Z"):
    return {"execucao_id": id_, "origem": origem, "gerado_em": gerado}


def test_escolhe_a_origem_mais_recente_com_previsao_e_cenarios():
    o1, o2 = date(2026, 9, 1), date(2026, 10, 1)
    assert rc.escolher_origem([o1, o2], [exe(o1), exe(o2)]) == o2
    # sem cenários para a mais recente: usa a anterior (e o aviso de defasagem cobra o resto)
    assert rc.escolher_origem([o1, o2], [exe(o1)]) == o1
    # cenários sem previsão não contam
    assert rc.escolher_origem([o1], [exe(o1), exe(o2)]) == o1


def test_nunca_escolhe_origem_de_backtest():
    dez = ORIGENS_DE_BACKTEST[-1]
    with pytest.raises(rc.ErroDeProducao, match="gerar-producao"):
        rc.escolher_origem([dez], [exe(dez)])
    assert rc.escolher_origem([dez, date(2026, 9, 1)], [exe(dez), exe(date(2026, 9, 1))]) == date(
        2026, 9, 1
    )


def test_sem_cenarios_a_cadeia_manda_gerar():
    with pytest.raises(rc.ErroDeProducao, match="gerar-producao"):
        rc.escolher_origem([date(2026, 10, 1)], [])


def test_escolhe_a_execucao_mais_recente_da_origem():
    o = date(2026, 9, 1)
    base = exe(o, EXECUCAO_CONGELADA, "2026-10-08T00:00:00Z")
    nova = exe(o, "aaaa", "2026-10-12T00:00:00Z")
    assert rc.escolher_execucao([base, nova], o) == "aaaa"
    assert rc.escolher_execucao([base], o) == EXECUCAO_CONGELADA
    with pytest.raises(rc.ErroDeProducao):
        rc.escolher_execucao([base], date(2026, 10, 1))


def test_empate_de_data_fica_com_o_maior_id():
    o = date(2026, 9, 1)
    assert rc.escolher_execucao([exe(o, "a"), exe(o, "b")], o) == "b"


# ---- aviso de defasagem


def test_sem_defasagem_nao_ha_aviso():
    o = date(2026, 10, 1)
    assert rc.aviso_de_defasagem(o, o, o) == []


def test_previsao_sem_cenarios_gera_aviso_com_o_comando():
    avisos = rc.aviso_de_defasagem(date(2026, 9, 1), date(2026, 10, 1), date(2026, 10, 1))
    assert len(avisos) == 1 and "AVISO DE DEFASAGEM" in avisos[0]
    assert "1 mês" in avisos[0] and "gerar-producao" in avisos[0]


def test_mes_fechado_alem_da_previsao_gera_aviso_com_o_comando():
    avisos = rc.aviso_de_defasagem(date(2026, 9, 1), date(2026, 9, 1), date(2026, 11, 1))
    assert len(avisos) == 1 and "2 mês" in avisos[0] and "ml.previsao gerar" in avisos[0]


def test_os_dois_avisos_juntos():
    avisos = rc.aviso_de_defasagem(date(2026, 8, 1), date(2026, 10, 1), date(2026, 12, 1))
    assert len(avisos) == 2


# ---- nenhuma linha de backtest


def linhas_de(origem, dados, consumo):
    return rc.linhas_producao(dados, origem, [15_000.0] * 12, consumo, "id", CAB, PROV, f=0.10)


def test_a_validacao_aceita_so_producao_do_caso_base():
    o = date(2026, 10, 1)
    dados, consumo = dados_de_producao(o)
    rc.validar_somente_producao(linhas_de(o, dados, consumo))


def test_a_validacao_recusa_linha_de_backtest_outro_sens_id_e_origem_de_backtest():
    o = date(2026, 10, 1)
    dados, consumo = dados_de_producao(o)
    df = linhas_de(o, dados, consumo)
    with pytest.raises(rc.ErroDeProducao, match="backtest"):
        rc.validar_somente_producao(df.assign(tipo="backtest"))
    with pytest.raises(rc.ErroDeProducao, match="caso base"):
        rc.validar_somente_producao(df.assign(sens_id="f00"))
    with pytest.raises(rc.ErroDeProducao, match="backtest"):
        rc.validar_somente_producao(df.assign(origem=ORIGENS_DE_BACKTEST[0]))
    with pytest.raises(rc.ErroDeProducao, match="3 linhas"):
        rc.validar_somente_producao(df.iloc[:2])


# ---- o comando, com leitura e gravação falsas


class Gravador:
    def __init__(self):
        self.chamadas = []

    def __call__(self, gcp, cliente, linhas, tabela, esquema, chave):
        self.chamadas.append((tabela, list(linhas), chave))
        return {
            "tabela": tabela,
            "linhas": len(linhas),
            "s_ddl": 0.0,
            "s_carga": 0.0,
            "s_merge": 0.0,
            "bytes_faturados": 20 * MIB,
        }


def montar_comando(origens_previsao, execucoes, fechado, dados_por_origem):
    def ler_o_inicio(gcp, cliente):
        return rc.Inicio(origens_previsao, execucoes, fechado)

    def ler_a_origem(gcp, cliente, origem, execucao_id):
        dados, consumo = dados_por_origem[origem]
        return rc.LeituraDaOrigem(dados, [15_000.0] * 12, consumo)

    return ler_o_inicio, ler_a_origem


def rodar(origens_previsao, execucoes, fechado, dry_run=False, g=None):
    o_max = max(o for o in origens_previsao)
    dados_por = {o: dados_de_producao(o) for o in set(origens_previsao)}
    ini, ori = montar_comando(origens_previsao, execucoes, fechado, dados_por)
    g = g or Gravador()
    rc_ = rc.producao(
        dry_run,
        gcp=SimpleNamespace(),
        cliente=None,
        ler_o_inicio=ini,
        ler_a_origem=ori,
        gravar=g,
        prov=PROV,
        cabecalho=CAB,
        agora=lambda: AGORA,
    )
    return rc_, g, o_max


def test_grava_so_as_3_linhas_da_origem_mais_recente(capsys):
    o = date(2026, 10, 1)
    rc_, g, _ = rodar([date(2026, 9, 1), o], [exe(date(2026, 9, 1)), exe(o)], o)
    assert rc_ == 0 and len(g.chamadas) == 1
    tabela, linhas, chave = g.chamadas[0]
    assert tabela == rc.TABELA and chave == rc.CHAVE and len(linhas) == 3
    assert {r["origem"] for r in linhas} == {"2026-10-01"}
    assert {r["tipo"] for r in linhas} == {"previa"} and {r["sens_id"] for r in linhas} == {
        "caso_base"
    }
    assert {r["ano_contrato"] for r in linhas} == {None}
    assert all(r["custo_realizado_rs"] is None for r in linhas)
    assert not ({r["origem"] for r in linhas} & {d.isoformat() for d in ORIGENS_DE_BACKTEST})
    assert "AVISO" not in capsys.readouterr().out


def test_origem_de_dezembro_vira_producao_com_ano_calendario():
    o = date(2026, 12, 1)
    _, g, _ = rodar([o], [exe(o)], o)
    linhas = g.chamadas[0][1]
    assert {r["tipo"] for r in linhas} == {"producao"} and {r["ano_contrato"] for r in linhas} == {
        2027
    }
    assert {r["janela_inicio"] for r in linhas} == {"2027-01-01"}


def test_usa_a_origem_anterior_e_avisa_quando_a_mais_recente_nao_tem_cenarios(capsys):
    o1, o2 = date(2026, 9, 1), date(2026, 10, 1)
    _, g, _ = rodar([o1, o2], [exe(o1)], o2)
    assert {r["origem"] for r in g.chamadas[0][1]} == {"2026-09-01"}
    saida = capsys.readouterr().out
    assert saida.count("AVISO DE DEFASAGEM") >= 2  # no começo e repetido no fim, depois de gravar
    assert "gerar-producao" in saida


def test_avisa_quando_o_mes_fechado_passou_da_previsao(capsys):
    o = date(2026, 9, 1)
    rodar([o], [exe(o)], date(2026, 11, 1))
    assert "ml.previsao gerar" in capsys.readouterr().out


def test_idempotencia_duas_execucoes_gravam_as_mesmas_linhas():
    o = date(2026, 10, 1)
    _, a, _ = rodar([o], [exe(o)], o)
    _, b, _ = rodar([o], [exe(o)], o)
    assert a.chamadas == b.chamadas


def test_dry_run_nao_grava_e_rotula_a_estimativa(capsys):
    o = date(2026, 10, 1)
    rc_, g, _ = rodar([o], [exe(o)], o, dry_run=True)
    saida = capsys.readouterr().out
    assert rc_ == 0 and g.chamadas == []
    assert "nada gravado" in saida and "ESTIMATIVA" in saida and "previa" in saida


def test_sem_cenarios_o_comando_aborta_antes_de_ler_e_gravar():
    o = date(2026, 10, 1)
    g = Gravador()
    with pytest.raises(rc.ErroDeProducao):
        rodar([o], [], o, g=g)
    assert g.chamadas == []


# ---- as consultas (BigQuery falso)


class GcpFalso:
    def __init__(self, respostas):
        self.respostas = respostas
        self.sqls = []

    def executar_consulta(self, cliente, sql, **kw):
        self.sqls.append(sql)
        for chave, linhas in self.respostas:
            if chave in sql:
                return SimpleNamespace(
                    linhas=linhas, bytes_processados=10, bytes_faturados=10 * MIB, cache=False
                )
        raise AssertionError(f"consulta inesperada: {sql[:90]}")


def test_ler_inicio_exclui_o_backtest_no_proprio_sql():
    serie = [
        {"mes": m, "valor": 40_000.0, "cobertura": 1.0}
        for m in meses(date(2026, 1, 1), date(2026, 9, 1))
    ]
    gcp = GcpFalso(
        [
            ("SELECT DISTINCT origem", [{"origem": date(2026, 9, 1)}]),
            ("fct_cenario_execucao", [exe(date(2026, 9, 1), EXECUCAO_CONGELADA)]),
            ("fct_carga_mensal", serie),
        ]
    )
    ini = rc.ler_inicio(gcp, None)
    assert ini.origens_previsao == [date(2026, 9, 1)]
    assert ini.ultimo_mes_fechado == date(2026, 9, 1)
    sql_exec = next(s for s in gcp.sqls if "fct_cenario_execucao" in s)
    assert "origem > DATE '2024-12-01'" in sql_exec
    assert not [s for s in gcp.sqls if "fct_recomendacao_contrato" in s]
    assert SQL_SERIE in gcp.sqls


def test_ler_da_origem_filtra_por_execucao_e_origem_e_so_blocos():
    o = date(2026, 9, 1)
    dados, consumo = dados_de_producao(o)
    previsao = [{"horizonte": h, "previsao_mwmed": 15_000.0} for h in HORIZONTES]
    gcp = GcpFalso(
        [
            ("FROM `marts.fct_cenario_execucao`", dados.execucao.to_dict("records")),
            ("FROM `marts.fct_cenario_consumo`", dados.cenario_consumo.to_dict("records")),
            ("FROM `marts.fct_cenario_pld`", dados.cenario_pld.to_dict("records")),
            ("FROM `marts.fct_previsao_carga`", previsao),
            ("FROM `marts.fct_pld_ponderado_mensal`", dados.pld_mensal.to_dict("records")),
            ("FROM `marts.fct_consumo_horario`", consumo.to_dict("records")),
        ]
    )
    leitura = rc.ler_da_origem(gcp, None, o, "idx")
    for sql in gcp.sqls:
        if "fct_cenario_" in sql:
            assert "execucao_id = 'idx'" in sql and "origem = DATE '2026-09-01'" in sql
    assert any("metodo = 'blocos'" in s for s in gcp.sqls)
    assert leitura.previsto_mwmed == [15_000.0] * 12
    assert len(leitura.dados.cenario_consumo) == N * 12
    assert not [s for s in gcp.sqls if "fct_recomendacao_contrato" in s]  # só lê; nunca o destino


def test_previsao_incompleta_aborta():
    o = date(2026, 9, 1)
    dados, consumo = dados_de_producao(o)
    gcp = GcpFalso(
        [
            ("FROM `marts.fct_cenario_execucao`", dados.execucao.to_dict("records")),
            ("FROM `marts.fct_cenario_consumo`", dados.cenario_consumo.to_dict("records")),
            ("FROM `marts.fct_cenario_pld`", dados.cenario_pld.to_dict("records")),
            ("FROM `marts.fct_previsao_carga`", [{"horizonte": 1, "previsao_mwmed": 1.0}]),
        ]
    )
    with pytest.raises(rc.ErroDeProducao, match="12 horizontes"):
        rc.ler_da_origem(gcp, None, o, "idx")


# ---- a gravação de verdade


def test_o_merge_da_producao_so_atualiza_e_insere_pela_chave():
    from ml.cenarios import gravar_medido

    o = date(2026, 10, 1)
    dados, consumo = dados_de_producao(o)
    df = linhas_de(o, dados, consumo)
    sqls, cargas = [], []

    class Gcp:
        def executar_consulta(self, cliente, sql, **kw):
            sqls.append(sql)
            return SimpleNamespace(
                linhas=[], bytes_processados=0, bytes_faturados=20 * MIB, cache=False
            )

    class Cliente:
        def load_table_from_json(self, linhas, temp, job_config=None):
            cargas.append((temp, list(linhas)))
            return SimpleNamespace(result=lambda: None)

        def delete_table(self, nome, not_found_ok=False):
            pass

    gravar_medido(Gcp(), Cliente(), rc.linhas_para_carga(df), rc.TABELA, rc.ESQUEMA, rc.CHAVE)
    merge = next(s for s in sqls if s.lstrip().startswith("MERGE"))
    for coluna in rc.CHAVE:
        assert f"T.`{coluna}` = S.`{coluna}`" in merge
    assert "NOT MATCHED BY SOURCE" not in merge
    assert not [s for s in sqls if "DELETE" in s.upper() or "TRUNCATE" in s.upper()]
    assert len(cargas[0][1]) == 3
    assert {r["tipo"] for r in cargas[0][1]} == {"previa"}
