"""O macro `janela_incremental` (dbt/macros/janela_incremental.sql), renderizado com jinja2 puro,
sem dbt nem nuvem: valida as vars da janela, recusa execução incremental sem elas e nunca deixa uma
partição sobrescrita sem o raw que a recompõe."""

import json
import re
from pathlib import Path
from types import SimpleNamespace

import jinja2
import pytest

from ingestion.janela import janela_de_intervalo

MACROS = Path(__file__).resolve().parent.parent / "dbt" / "macros" / "janela_incremental.sql"
VALIDAS = janela_de_intervalo("2026-07", "2026-09").vars_dbt()


class ErroDeCompilacao(Exception):
    pass


class _Retorno(Exception):
    def __init__(self, valor):
        self.valor = valor


def _retornar(valor):
    raise _Retorno(valor)


def _erro(mensagem):
    raise ErroDeCompilacao(mensagem)


def macro(nome: str, variaveis: dict):
    """Chama o macro como o dbt faria: `var()`, `model`, `exceptions`, `modules.re` e `return`."""
    ambiente = jinja2.Environment(extensions=["jinja2.ext.do"])
    ambiente.globals.update(
        var=lambda chave, padrao=None: variaveis.get(chave, padrao),
        model=SimpleNamespace(name="stg_ons__curva_carga"),
        exceptions=SimpleNamespace(raise_compiler_error=_erro),
        modules=SimpleNamespace(re=re),
    )
    ambiente.globals["return"] = _retornar
    modulo = ambiente.from_string(MACROS.read_text()).module
    try:
        getattr(modulo, nome)()
    except _Retorno as retorno:
        return retorno.valor
    raise AssertionError("o macro não retornou nada")


def com(**mudancas):
    return {**VALIDAS, **mudancas}


def test_vars_validas_do_janela_py_passam_e_devolvem_os_limites():
    r = macro("janela_incremental", VALIDAS)
    assert r == {
        "utc_inicio": "2026-07-01",
        "utc_fim": "2026-11-01",
        "raw_mes_inicio": "2026-06-01",
        "raw_mes_fim": "2026-10-01",
    }


def test_particoes_estaticas_viram_literais_de_timestamp():
    r = macro("janela_particoes", VALIDAS)
    assert r == [f"timestamp('2026-{m:02d}-01')" for m in (7, 8, 9, 10)]
    assert macro("janela_particoes", {}) == []  # parse e --full-refresh não precisam das vars


@pytest.mark.parametrize("faltando", list(VALIDAS))
def test_execucao_incremental_sem_qualquer_var_falha_com_mensagem_clara(faltando):
    variaveis = {k: v for k, v in VALIDAS.items() if k != faltando}
    with pytest.raises(ErroDeCompilacao) as erro:
        macro("janela_incremental", variaveis)
    texto = str(erro.value)
    assert "sem as vars da janela" in texto and faltando in texto
    assert "ingestion.janela" in texto and "--full-refresh" in texto


def test_sem_nenhuma_var_lista_todas_as_que_faltam():
    with pytest.raises(ErroDeCompilacao, match="utc_inicio, utc_fim, particoes_utc"):
        macro("janela_incremental", {})


@pytest.mark.parametrize(
    "mudanca",
    [
        {"utc_inicio": "2026-07-15"},  # não é dia 1
        {"utc_fim": "2026-11-01'); drop table x; --"},  # nada de texto arbitrário no SQL
        {"raw_mes_inicio": "junho"},
        {"particoes_utc": ["2026-07-01", "x"]},
    ],
)
def test_datas_fora_do_formato_sao_recusadas_antes_de_entrar_no_sql(mudanca):
    with pytest.raises(ErroDeCompilacao, match="Data inválida"):
        macro("janela_incremental", com(**mudanca))


def test_lista_de_particoes_vazia_ou_texto_e_recusada():
    for ruim in ([], "2026-07-01"):
        with pytest.raises(ErroDeCompilacao):
            macro("janela_incremental", com(particoes_utc=ruim))


def test_primeira_particao_diferente_de_utc_inicio_e_recusada():
    with pytest.raises(ErroDeCompilacao, match="deve ser igual a utc_inicio"):
        macro("janela_incremental", com(particoes_utc=["2026-08-01", "2026-09-01"]))


def test_particao_fora_do_intervalo_do_filtro_e_recusada():
    """Regra 2: a lista e o filtro cobrem o mesmo intervalo. Uma partição além de utc_fim seria
    apagada sem o filtro devolver as linhas dela (perda de dado)."""
    ruim = com(particoes_utc=[*VALIDAS["particoes_utc"], "2026-11-01"])
    with pytest.raises(ErroDeCompilacao, match="fora de \\[utc_inicio, utc_fim\\)"):
        macro("janela_incremental", ruim)


def test_raw_que_nao_cobre_a_ultima_particao_e_recusado():
    """Regra 1: janela local até setembro => partições até outubro => o raw lido inclui outubro."""
    with pytest.raises(ErroDeCompilacao, match="não cobre todas as horas"):
        macro("janela_incremental", com(raw_mes_fim="2026-09-01"))


def test_raw_que_comeca_no_mesmo_mes_utc_perde_as_horas_do_mes_local_anterior():
    # 01/07 00h UTC é 30/06 21h local: o raw tem de começar em junho, não em julho
    with pytest.raises(ErroDeCompilacao, match="não cobre todas as horas"):
        macro("janela_incremental", com(raw_mes_inicio="2026-07-01"))


def test_o_json_do_janela_py_e_aceito_como_chega_do_dbt_vars():
    como_chega = json.loads(json.dumps(VALIDAS))
    assert macro("janela_incremental", como_chega)["utc_fim"] == "2026-11-01"
