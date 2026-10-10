"""Sensibilidades (6.4): registro = plano, só o parâmetro declarado muda, invariância da ingênua e
da pontual, f = 0, determinismo, trava contra repetição e caso base intocado."""

import hashlib
import json
import re
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from test_ml_backtest import dados_sinteticos

from ml import backtest as bt
from ml import sensibilidades as sn
from ml.backtest import ErroDeTrava, executar
from ml.otimizacao import grade_de_r, limites_de_r

RAIZ = Path(__file__).resolve().parents[1]
PLANO = RAIZ / "docs" / "planejamento" / "plano_sprint6b.md"
AGORA = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
CONGELADOS = [s for s in sn.REGISTRO if s["cenarios"] == "congelados"]
NOVOS = [s for s in sn.REGISTRO if s["cenarios"] == "novos"]


@pytest.fixture(scope="module")
def dados():
    return dados_sinteticos()


@pytest.fixture(scope="module")
def base(dados):
    return executar(dados)


def linhas(res, estrategia):
    a = res.anual
    return a[a["estrategia"] == estrategia].reset_index(drop=True)


COLUNAS_REAIS = ["v_mwm", "custo_rs", "descoberto_mwh", "sobrando_mwh", "meses_fora_da_faixa"]


# ---------------------------------------------------------------- registro e plano


def test_registro_e_igual_ao_bloco_json_do_plano():
    texto = PLANO.read_text(encoding="utf-8")
    bloco = re.search(r"```json\n(.*?)\n```", texto, re.S).group(1)
    assert json.loads(bloco)["sensibilidades"] == list(sn.REGISTRO)


def test_registro_tem_13_execucoes_10_congeladas_e_3_novas():
    assert len(sn.REGISTRO) == 13 and len(set(sn.IDS)) == 13
    assert len(CONGELADOS) == 10 and {s["sens_id"] for s in NOVOS} == {"disp125", "disp150", "clip"}
    assert all(len(s["muda"]) == 1 for s in sn.REGISTRO)  # uma variável por vez


def test_sens_id_fora_do_registro_e_recusado():
    with pytest.raises(ErroDeTrava, match="fora do registro"):
        sn.buscar("f10")
    with pytest.raises(ErroDeTrava):
        sn.buscar("lam05")


# ---------------------------------------------------------------- só o parâmetro declarado muda


@pytest.mark.parametrize("sens", sn.REGISTRO, ids=sn.IDS)
def test_so_o_parametro_declarado_difere_do_caso_base(sens):
    id_ = "abc123def456" if sens["cenarios"] == "novos" else sn.EXECUCAO_CONGELADA
    dif = sn.diferencas(sens["sens_id"], id_)
    assert set(dif) == set(sens["muda"])
    base, nova = sn.criterios_do_caso_base(), sn.criterios(sens, id_)
    declarados = {sn.CHAVE_DO_CRITERIO.get(k, k) for k in sens["muda"]}
    outros = (set(base) | set(nova)) - declarados - {"execucao_id"}
    assert all(base[k] == nova[k] for k in outros)
    assert (nova["execucao_id"] == base["execucao_id"]) == (sens["cenarios"] == "congelados")


def test_o_criterio_do_caso_base_estende_o_do_backtest_sem_mudar_nada():
    ext = sn.criterios_do_caso_base()
    original = bt.criterios()
    assert all(ext[k] == v for k, v in original.items())
    assert (
        ext["r_max"] is None
        and ext["dispersao"] == 1.0
        and ext["transformacao_pld"] == "deslocamento"
    )


def test_config_hash_distingue_sensibilidades_e_e_estavel():
    hashes = {
        s["sens_id"]: sn.hash_da_configuracao(s["sens_id"], sn.criterios(s)) for s in CONGELADOS
    }
    assert len(set(hashes.values())) == len(hashes)
    assert hashes["f00"] == sn.hash_da_configuracao("f00", sn.criterios(sn.buscar("f00")))


# ---------------------------------------------------------------- f = 0: otimizada = pontual


def test_f_zero_a_otimizada_e_igual_a_pontual_por_construcao(dados):
    res = sn.executar_sensibilidade(sn.buscar("f00"), dados)
    ot, pont = linhas(res, "otimizada"), linhas(res, "pontual")
    assert_frame_equal(ot.drop(columns="estrategia"), pont.drop(columns="estrategia"))
    assert (ot["razao_v_pontual"] == 1.0).all()
    e = res.economia
    assert (e["valor_otimizacao_rs"] == 0).all()
    assert (e["custo_otimizada_rs"] == e["custo_pontual_rs"]).all()


def test_f_zero_tem_grade_de_um_ponto():
    assert limites_de_r(0.0) == (1.0, 1.0)
    assert grade_de_r(0.0).tolist() == [1.0]


# ---------------------------------------------------------------- invariância


@pytest.mark.parametrize(
    "sens",
    [s for s in CONGELADOS if s["sens_id"] in sn.INVARIANTES_INGENUA_PONTUAL],
    ids=lambda s: s["sens_id"],
)
def test_ingenua_e_pontual_identicas_ao_caso_base(dados, base, sens):
    res = sn.executar_sensibilidade(sens, dados)
    for e in ("ingenua", "pontual"):
        assert_frame_equal(linhas(res, e)[COLUNAS_REAIS], linhas(base, e)[COLUNAS_REAIS])
    ex = ["esperado_ex_ante_rs", "cvar_ex_ante_rs", "pit_custo_realizado"]
    if sens["sens_id"] in sn.INVARIANTES_EX_ANTE:
        for e in ("ingenua", "pontual"):
            assert_frame_equal(linhas(res, e)[ex], linhas(base, e)[ex])
    assert res.economia["valor_previsao_rs"].tolist() == base.economia["valor_previsao_rs"].tolist()


def test_cenarios_diferentes_nao_mudam_o_custo_da_ingenua_e_da_pontual(dados, base):
    """Vale para `disp125`, `disp150` e `clip`: trocar os cenários não toca ingênua e pontual."""
    outro = replace(
        dados,
        cenario_consumo=dados.cenario_consumo.assign(
            consumo_mwh=dados.cenario_consumo["consumo_mwh"] * 1.3
        ),
        cenario_pld=dados.cenario_pld.assign(pld_rs_mwh=dados.cenario_pld["pld_rs_mwh"] * 0.4),
    )
    res = executar(outro)
    for e in ("ingenua", "pontual"):
        assert_frame_equal(linhas(res, e)[COLUNAS_REAIS], linhas(base, e)[COLUNAS_REAIS])


def test_otimizada_igual_ao_caso_base_onde_o_r_e_igual(dados, base):
    res = sn.executar_sensibilidade(sn.buscar("alfa90"), dados)
    a, b = linhas(res, "otimizada"), linhas(base, "otimizada")
    iguais = (a["razao_v_pontual"] - b["razao_v_pontual"]).abs() < 1e-9
    assert iguais.all()  # nos dados sintéticos o limite superior vale para qualquer alfa
    assert_frame_equal(a[COLUNAS_REAIS][iguais], b[COLUNAS_REAIS][iguais])


def test_f_e_spread_mudam_o_custo_das_tres_estrategias(dados, base):
    for sens_id in ("spread00", "spread40", "f05", "f15"):
        res = sn.executar_sensibilidade(sn.buscar(sens_id), dados)
        for e in bt.ESTRATEGIAS:
            assert not np.allclose(linhas(res, e)["custo_rs"], linhas(base, e)["custo_rs"]), (
                sens_id,
                e,
            )


def test_spread_muda_o_preco_das_tres_estrategias_igualmente(dados):
    p0 = sn.executar_sensibilidade(sn.buscar("spread00"), dados).anual
    p40 = sn.executar_sensibilidade(sn.buscar("spread40"), dados).anual
    for a in (p0, p40):
        assert a.groupby("ano")["preco_contrato_rs_mwh"].nunique().eq(1).all()
    assert (p40["preco_contrato_rs_mwh"] - p0["preco_contrato_rs_mwh"]).round(9).eq(40.0).all()


def test_rmax_mantem_o_limite_inferior_e_a_grade_contem_a_do_caso_base_menos_o_teto():
    f = 0.10
    assert limites_de_r(f, 1.2) == (1 / (1 + f), 1.2)
    base, ampla = grade_de_r(f), grade_de_r(f, r_max=1.2)
    assert ampla[0] == base[0] and ampla[-1] == 1.2
    # pontos do caso base, exceto o limite superior (1,1111), que não é múltiplo do passo
    assert set(np.round(base[:-1], 9)) <= set(np.round(ampla, 9))
    assert 1 / (1 - f) not in set(ampla)


# ---------------------------------------------------------------- determinismo


def digest(res):
    h = hashlib.sha256()
    for df in (res.mensal, res.anual, res.economia):
        h.update(df.to_csv(index=False, float_format="%.6f").encode())
    return h.hexdigest()


def test_determinismo_mesma_entrada_mesma_saida(dados):
    s = sn.buscar("lam10")
    assert digest(sn.executar_sensibilidade(s, dados)) == digest(
        sn.executar_sensibilidade(s, dados)
    )


def test_embaralhar_os_cenarios_nao_muda_nada(dados):
    embaralhado = replace(
        dados,
        cenario_consumo=dados.cenario_consumo.sample(frac=1, random_state=3).reset_index(drop=True),
        cenario_pld=dados.cenario_pld.sample(frac=1, random_state=4).reset_index(drop=True),
    )
    s = sn.buscar("f15")
    assert digest(sn.executar_sensibilidade(s, dados)) == digest(
        sn.executar_sensibilidade(s, embaralhado)
    )


# ---------------------------------------------------------------- trava contra repetição e saídas


def rodar(sens_id, dados, tmp_path):
    return sn.rodar_sensibilidade(
        sn.buscar(sens_id),
        dados,
        sn.EXECUCAO_CONGELADA,
        {"origens": {"2020-12-01": {"x": 1}}},
        "h" * 40,
        None,
        "0" * 16,
        log=tmp_path / "log.jsonl",
        resultados=tmp_path,
        agora=lambda: AGORA,
    )


def test_segunda_execucao_da_mesma_sens_id_e_recusada(dados, tmp_path):
    rodar("lam00", dados, tmp_path)
    with pytest.raises(ErroDeTrava, match="já foi executada"):
        rodar("lam00", dados, tmp_path)
    log = bt.ler_log(tmp_path / "log.jsonl")
    assert len(log) == 1 and log[0]["sens_id"] == "lam00" and log[0]["evento"] == "sensibilidade"
    assert log[0]["muda"] == {"lambda": [0.5, 0.0]}
    assert log[0]["preregistro"] == sn.PREREGISTRO_6B


def test_saida_existente_sem_linha_no_log_aborta_e_nada_e_sobrescrito(dados, tmp_path):
    existente = tmp_path / "sens_lam10_anual.csv"
    existente.write_text("intacto")
    with pytest.raises(ErroDeTrava, match="não sobrescrita"):
        rodar("lam10", dados, tmp_path)
    assert existente.read_text() == "intacto"
    assert not (tmp_path / "log.jsonl").exists()


def test_todo_arquivo_gravado_leva_o_sens_id_no_nome(dados, tmp_path):
    rodar("alfa90", dados, tmp_path)
    nomes = sorted(p.name for p in tmp_path.iterdir() if p.name != "log.jsonl")
    assert nomes == sorted(f"sens_alfa90_{k}.csv" for k in sn.SAIDAS)
    assert not any(n.startswith("backtest_caso_base") for n in nomes)
    saida = pd.read_csv(tmp_path / "sens_alfa90_economia.csv")
    assert set(saida["sens_id"]) == {"alfa90"} and saida["config_hash"].nunique() == 1


def test_saidas_do_log_batem_com_os_hashes_dos_arquivos(dados, tmp_path):
    rodar("rmax120", dados, tmp_path)
    entrada = bt.ler_log(tmp_path / "log.jsonl")[0]
    for nome, h in entrada["saidas"].items():
        assert sn._sha(tmp_path / nome) == h


def test_o_log_so_cresce_e_nao_e_o_do_caso_base():
    assert sn.LOG.name == "sensibilidades_execucoes.jsonl" and sn.LOG != sn.LOG_CASO_BASE


# ---------------------------------------------------------------- caso base intocado


def test_os_arquivos_reais_do_caso_base_batem_com_o_log_dele():
    antes = {p.name: sn._sha(p) for p in sn.RESULTADOS.glob("backtest_caso_base_*.csv")}
    log_antes = sn._sha(sn.LOG_CASO_BASE)
    assert sn.conferir_caso_base_intacto() == log_antes
    assert len(antes) == 3


def test_caso_base_alterado_e_detectado(tmp_path):
    for nome in ("mensal", "anual", "economia"):
        (tmp_path / f"backtest_caso_base_{nome}.csv").write_text(nome)
    saidas = {
        f"backtest_caso_base_{n}.csv": sn._sha(tmp_path / f"backtest_caso_base_{n}.csv")
        for n in ("mensal", "anual", "economia")
    }
    log = tmp_path / "base.jsonl"
    bt.acrescentar_log({"evento": "caso_base", "numero": 1, "saidas": saidas}, log)
    assert sn.conferir_caso_base_intacto(tmp_path, log) == sn._sha(log)
    (tmp_path / "backtest_caso_base_anual.csv").write_text("mexido")
    with pytest.raises(ErroDeTrava, match="não é o registrado"):
        sn.conferir_caso_base_intacto(tmp_path, log)


def test_nenhum_codigo_novo_escreve_nos_arquivos_do_caso_base():
    for caminho in sn.saidas_de("f00", Path("x")).values():
        assert caminho.name.startswith("sens_") and "caso_base" not in caminho.name
    fonte = Path(sn.__file__).read_text()
    assert "LOG_CASO_BASE" in fonte
    assert not re.search(r"acrescentar_log\([^)]*LOG_CASO_BASE", fonte)  # nunca grava nele


def test_a_execucao_de_sensibilidades_nao_altera_o_dado_de_entrada(dados):
    antes = dados.cenario_pld.copy()
    for s in CONGELADOS:
        sn.executar_sensibilidade(s, dados)
    assert_frame_equal(dados.cenario_pld, antes)


# ---------------------------------------------------------------- travas do git e do realizado


def git_falso(ancestral=True, sujo="", remotos="origin/sprint6/parte-b-sensibilidades"):
    def git(*args):
        if args[0] == "merge-base":
            return (0 if ancestral else 1), ""
        if args[:2] == ("status", "--porcelain"):
            return 0, sujo
        if args[0] == "rev-parse":
            return 0, "a" * 40
        if args[:2] == ("branch", "-r"):
            return 0, remotos
        raise AssertionError(args)

    return git


def test_trava_do_git_aceita_quando_tudo_confere():
    assert sn.conferir_git_6b(git_falso()) == "a" * 40


@pytest.mark.parametrize(
    ("kw", "msg"),
    [
        ({"ancestral": False}, "não é ancestral"),
        ({"sujo": " M ml/x.py"}, "não está limpa"),
        ({"remotos": ""}, "remota"),
    ],
)
def test_trava_do_git_aborta(kw, msg):
    with pytest.raises(ErroDeTrava, match=msg):
        sn.conferir_git_6b(git_falso(**kw))


def test_o_lote_aborta_pelo_git_antes_de_ler_qualquer_dado(tmp_path):
    with pytest.raises(ErroDeTrava):
        sn.rodar_lote(git=git_falso(sujo="?? x"), diretorio=tmp_path / "nao_existe")


def test_realizado_diferente_do_manifesto_aborta(tmp_path):
    (tmp_path / "previstos.parquet").write_bytes(b"a")
    (tmp_path / "manifest.json").write_text(
        json.dumps({"hash_dos_arquivos": {"previstos": "0" * 16}})
    )
    with pytest.raises(ErroDeTrava, match="difere do manifesto"):
        sn.conferir_realizado(tmp_path)


def test_o_preregistro_e_o_commit_aprovado():
    assert sn.PREREGISTRO_6B == "4c02987d0270dd91639cdc410d801fe550710af9"


def test_novos_sem_cenarios_gerados_abortam_com_instrucao(dados, tmp_path):
    with pytest.raises(ErroDeTrava, match="cenarios_sens gerar"):
        sn.dados_da_sensibilidade(sn.buscar("clip"), dados, tmp_path)


# ---------------------------------------------------------------- resumo


@pytest.fixture(scope="module")
def pasta_completa(dados, tmp_path_factory):
    pasta = tmp_path_factory.mktemp("resultados")
    base = executar(dados)
    for chave in sn.SAIDAS:
        getattr(base, chave).to_csv(
            pasta / f"{bt.PREFIXO}_{chave}.csv", index=False, float_format="%.6f"
        )
    bt.acrescentar_log({"evento": "caso_base", "numero": 1}, pasta / sn.LOG.name)
    for sens in sn.REGISTRO:
        sn.rodar_sensibilidade(
            sens, dados, sn.EXECUCAO_CONGELADA, {"origens": {}}, "h" * 40, None, "0" * 16,
            log=pasta / sn.LOG.name, resultados=pasta, agora=lambda: AGORA,
        )  # fmt: skip
    return pasta


def test_resumo_tem_as_tabelas_com_o_formato_do_plano(pasta_completa):
    caminhos = sn.gerar_resumos(pasta_completa)
    assert set(caminhos) == {
        "sens_resumo.csv",
        "sens_resumo_por_ano.csv",
        "sens_banda_f.csv",
        "sens_invariancias.csv",
    }
    resumo = pd.read_csv(caminhos["sens_resumo.csv"])
    assert len(resumo) == 14 * 2 and resumo["sens_id"].iloc[0] == "caso_base"
    assert list(dict.fromkeys(resumo["sens_id"])) == [
        "caso_base",
        *sn.IDS,
    ]  # ordem do plano, sem ranking
    por_ano = pd.read_csv(caminhos["sens_resumo_por_ano.csv"])
    assert len(por_ano) == 14 * 2  # a base sintética tem 2 anos
    banda = pd.read_csv(caminhos["sens_banda_f.csv"])
    assert sorted(banda["f"].unique()) == [0.0, 0.05, 0.1, 0.15]
    assert len(banda) == 4 * (2 + 2)  # 2 anos + 2 recortes


def test_resumo_marca_as_invariancias_previstas(pasta_completa):
    inv = pd.read_csv(sn.gerar_resumos(pasta_completa)["sens_invariancias.csv"]).set_index(
        "sens_id"
    )
    for sens_id in sn.INVARIANTES_INGENUA_PONTUAL:
        assert inv.loc[sens_id, ["ingenua_custo_igual", "pontual_custo_igual"]].all(), sens_id
    for sens_id in sn.INVARIANTES_EX_ANTE:
        assert inv.loc[sens_id, ["ingenua_ex_ante_igual", "pontual_ex_ante_igual"]].all(), sens_id
    assert not inv.loc["spread40", "ingenua_custo_igual"]


def test_resumo_exige_as_13_no_log(dados, tmp_path):
    bt.acrescentar_log({"evento": "sensibilidade", "sens_id": "f00"}, tmp_path / sn.LOG.name)
    with pytest.raises(ErroDeTrava, match="faltam"):
        sn.gerar_resumos(tmp_path)


def test_resumo_nao_altera_as_saidas_individuais_nem_o_caso_base(pasta_completa):
    antes = {
        p.name: sn._sha(p)
        for p in pasta_completa.glob("*.csv")
        if p.name.startswith(("sens_", "backtest_"))
    }
    sn.gerar_resumos(pasta_completa)
    sn.gerar_resumos(pasta_completa)  # regerável
    depois = {p.name: sn._sha(p) for p in pasta_completa.glob("*.csv") if p.name in antes}
    assert antes == depois
