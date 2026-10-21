"""Os dois nomes parecidos não podem ser trocados:

- "Ano anterior": estratégia de CONTRATO (página Decisão), o consumo médio do ano passado;
- "Mesmo mês do ano anterior": modelo de COMPARAÇÃO da previsão (página Previsão).
"""

from pathlib import Path

from apptest_util import antes_do_glossario, expander
from streamlit.testing.v1 import AppTest

from dashboard import glossario
from dashboard import graficos as gr
from dashboard import textos as tx_decisao
from dashboard import textos_previsao as tx_previsao
from dashboard import visual as vis

RAIZ = Path(__file__).resolve().parents[1]
PAGINAS = RAIZ / "dashboard" / "paginas"


def decisao():
    from dashboard.paginas import decisao

    decisao.renderizar()


def previsao():
    from dashboard.paginas import previsao

    previsao.renderizar()


def rodar(funcao) -> AppTest:
    at = AppTest.from_function(funcao, default_timeout=90)
    at.run()
    assert not at.exception
    return at


def test_os_dois_nomes_sao_diferentes_e_um_nao_contem_o_outro_com_a_mesma_caixa():
    assert vis.ANO_ANTERIOR == "Ano anterior" and vis.MESMO_MES == "Mesmo mês do ano anterior"
    assert vis.ANO_ANTERIOR != vis.MESMO_MES
    assert vis.ANO_ANTERIOR not in vis.MESMO_MES  # "Ano" maiúsculo: só a estratégia o usa


def test_cada_nome_designa_so_o_que_deveria():
    assert vis.NOMES_DAS_ESTRATEGIAS["ingenua"] == vis.ANO_ANTERIOR
    assert gr.NOME_COMPARACAO == vis.MESMO_MES != vis.ANO_ANTERIOR
    assert tx_previsao.vis.MESMO_MES == vis.MESMO_MES


def test_a_decisao_so_usa_o_ano_anterior_e_a_previsao_so_usa_o_mesmo_mes():
    d = antes_do_glossario(rodar(decisao))
    p = antes_do_glossario(rodar(previsao))
    assert vis.ANO_ANTERIOR in d and vis.MESMO_MES not in d
    assert vis.MESMO_MES in p and vis.ANO_ANTERIOR not in p


def test_o_codigo_de_cada_pagina_nao_importa_o_nome_do_outro():
    codigo = {
        nome: (RAIZ / "dashboard" / arq).read_text()
        for nome, arq in {
            "decisao": "paginas/decisao.py",
            "textos": "textos.py",
            "previsao": "paginas/previsao.py",
            "textos_previsao": "textos_previsao.py",
        }.items()
    }
    for nome in ("decisao", "textos"):
        assert "MESMO_MES" not in codigo[nome], nome
    for nome in ("previsao", "textos_previsao"):
        assert "ANO_ANTERIOR" not in codigo[nome], nome


def test_o_glossario_das_duas_paginas_define_os_dois_e_remete_um_ao_outro():
    for at in (rodar(decisao), rodar(previsao)):
        md = expander(at, "Glossário").markdown[0].value
        assert "**Ano anterior:**" in md and "**Mesmo mês do ano anterior:**" in md
    ano = glossario.TERMOS["Ano anterior"]
    mes = glossario.TERMOS["Mesmo mês do ano anterior"]
    assert "Mesmo mês do ano anterior" in ano and "contrata" in ano
    assert "Ano anterior" in mes and "repete" in mes
    assert "Ano anterior" in tx_decisao.GLOSSARIO and "Ano anterior" in tx_previsao.GLOSSARIO
