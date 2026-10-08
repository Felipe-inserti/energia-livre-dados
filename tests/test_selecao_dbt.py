"""Seleção do dbt por fonte (4b): a função pura, o CLI e, com o dbt de verdade (`dbt ls`, sem
nuvem), que os testes que CRUZAM fontes rodam sempre que qualquer fonte envolvida muda."""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from ingestion import orquestracao as orq

DBT = Path(__file__).resolve().parent.parent / "dbt"


def test_dia_comum_seleciona_so_o_ons():
    assert orq.selecao_dbt() == ["source:raw.ons_curva_carga+"]


def test_arquivo_novo_do_inmet_acrescenta_so_o_inmet():
    assert orq.selecao_dbt(inmet_novo=True) == [
        "source:raw.ons_curva_carga+",
        "source:raw.inmet_estacoes_horario+",
    ]


def test_arquivo_novo_da_ccee_acrescenta_as_tres_fontes_da_ccee():
    sel = orq.selecao_dbt(ccee_novo=True)
    assert sel[0] == "source:raw.ons_curva_carga+" and len(sel) == 4
    assert {s for s in sel[1:]} == {
        "source:raw.ccee_pld_horario+",
        "source:raw.ccee_pld_semanal+",
        "source:raw.ccee_consumo_ramo_atividade+",
    }


def test_as_duas_fontes_novas_somam_as_selecoes_sem_repetir():
    sel = orq.selecao_dbt(ccee_novo=True, inmet_novo=True)
    assert len(sel) == len(set(sel)) == 5


def test_a_selecao_de_teste_traz_sempre_o_teste_do_alerta():
    for ccee in (False, True):
        for inmet in (False, True):
            teste = orq.selecao_dbt_teste(ccee, inmet)
            assert teste[-1] == "teste_alerta_falha_proposital"
            assert teste[:-1] == orq.selecao_dbt(ccee, inmet)


def test_toda_selecao_comeca_pelo_ons_que_roda_todo_dia():
    for ccee in (False, True):
        for inmet in (False, True):
            assert orq.selecao_dbt(ccee, inmet)[0] == "source:raw.ons_curva_carga+"


def test_cli_imprime_os_seletores_em_uma_linha(capsys):
    assert orq.main(["selecao-dbt"]) == 0
    assert capsys.readouterr().out.strip() == "source:raw.ons_curva_carga+"
    assert orq.main(["selecao-dbt-teste", "inmet"]) == 0
    assert capsys.readouterr().out.split() == [*orq.selecao_dbt(inmet_novo=True), orq.TESTE_ALERTA]
    assert orq.main(["selecao-dbt", "outra"]) == 2  # argumento desconhecido


# ---------------------------------------------------------------- com o dbt de verdade (dbt ls)
SEM_DBT = pytest.mark.skipif(
    not (DBT / "dbt_packages").exists() or not shutil.which("dbt"),
    reason="precisa do dbt instalado e de `dbt deps`",
)
ESTATICOS = re.compile(
    r"dim_tempo|stg_feriados|dim_submercado|pld_limites|ajuste_definicao_carga|carga_mensal_ons|teste_alerta_falha"
)


def dbt_ls(tmp_path: Path, selecao: list[str] | None) -> set[str]:
    shutil.copy(DBT / "profiles.yml.example", tmp_path / "profiles.yml")
    comando = ["dbt", "ls", "--resource-type", "test", "--output", "name", "--no-use-colors"]
    comando += ["--project-dir", str(DBT), "--profiles-dir", str(tmp_path)]
    comando += ["--target-path", str(tmp_path / "t"), "--log-path", str(tmp_path / "l")]
    if selecao:
        comando += ["--select", *selecao]
    ambiente = {
        **os.environ,
        "GCP_PROJECT_ID": "projeto-de-teste",
        "BQ_LOCATION": "us-central1",
        "CLOUDSDK_CONFIG": str(tmp_path / "sem-gcloud"),
        "GOOGLE_APPLICATION_CREDENTIALS": str(tmp_path / "nao-existe.json"),
    }
    r = subprocess.run(comando, capture_output=True, text=True, env=ambiente, timeout=180)
    assert r.returncode == 0, r.stdout[-800:] + r.stderr[-400:]
    return {
        linha.strip() for linha in r.stdout.splitlines() if re.fullmatch(r"[\w]+", linha.strip())
    }


@pytest.fixture(scope="module")
def selecoes(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("ls")
    return {
        "todos": dbt_ls(tmp, None),
        "ons": dbt_ls(tmp, orq.selecao_dbt()),
        "inmet": dbt_ls(tmp, ["source:raw.inmet_estacoes_horario+"]),
        "ccee": dbt_ls(tmp, orq.selecao_dbt(ccee_novo=True)[1:]),
    }


CRUZA_FONTES = "fct_submercado_horario_preserva_as_linhas_das_fontes"


@SEM_DBT
@pytest.mark.parametrize("fonte", ["ons", "inmet", "ccee"])
def test_o_teste_que_cruza_as_tres_fontes_roda_quando_qualquer_uma_muda(selecoes, fonte):
    """fct_submercado_horario junta ONS, CCEE e INMET: se só uma delas muda, o teste que confere
    as linhas das três tem de rodar do mesmo jeito."""
    assert CRUZA_FONTES in selecoes[fonte]


@SEM_DBT
def test_testes_que_comparam_o_ons_com_dimensoes_e_marts_rodam_no_dia_comum(selecoes):
    esperados = {
        "dim_submercado_cobre_os_nomes_do_ons",
        "ons_linhas_conferem_com_raw",
        "ons_descarta_so_horas_conhecidas",
        "fct_carga_horaria_carga_positiva_e_plausivel",
    }
    assert esperados <= selecoes["ons"]
    assert len(selecoes["ons"]) >= 26  # os 26 testes do `dbt build` do passo 3


@SEM_DBT
def test_so_ficam_fora_do_dia_a_dia_os_testes_de_calendario_seeds_e_dimensao_estatica(selecoes):
    dia_a_dia = selecoes["ons"] | selecoes["inmet"] | selecoes["ccee"]
    fora = selecoes["todos"] - dia_a_dia
    inesperados = {t for t in fora if not ESTATICOS.search(t)}
    assert inesperados == set(), (
        "testes fora de qualquer seleção por fonte e que não são de calendário/seed: "
        f"{sorted(inesperados)}"
    )
    assert fora  # e eles existem: só rodam na execução completa
