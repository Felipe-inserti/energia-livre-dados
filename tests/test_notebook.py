"""Guardas do notebook de exploração (sem rede): leve no git, só lê dos marts, estrutura fixa."""

import re

import nbformat
import pytest

from notebooks import utilitarios as u

CAMINHO = u.RAIZ / "notebooks" / "01_exploracao.ipynb"
LIMITE_KB = 100
FIGURAS = {
    "01_carga_mensal_se",
    "02_perfil_horario_por_tipo_de_dia",
    "03_carga_x_temperatura",
    "04_pld_se_por_ano",
    "05_pld_medio_anual",
}


@pytest.fixture(scope="module")
def nb():
    return nbformat.read(CAMINHO, as_version=4)


def test_o_notebook_vai_ao_git_sem_saidas_e_pequeno(nb):
    for celula in nb.cells:
        if celula.cell_type == "code":
            assert celula.outputs == [] and celula.execution_count is None
    assert CAMINHO.stat().st_size / 1024 < LIMITE_KB


def test_gitattributes_liga_o_nbstripout():
    texto = (u.RAIZ / ".gitattributes").read_text()
    assert "*.ipynb filter=nbstripout" in texto


def test_cada_grafico_e_seguido_de_uma_celula_minhas_conclusoes(nb):
    salvas = []
    for i, celula in enumerate(nb.cells):
        if celula.cell_type == "code" and "salvar_figura" in celula.source:
            salvas += re.findall(r'salvar_figura\(fig, "(\w+)"\)', celula.source)
            seguinte = nb.cells[i + 1]
            assert seguinte.cell_type == "markdown"
            assert seguinte.source.startswith("### Minhas conclusões")  # o texto é do autor
    assert set(salvas) == FIGURAS and len(salvas) == 5


def sql_das_celulas(nb):
    """O SQL das células de código com `{T('tabela')}` trocado por um identificador do mart."""
    codigo = "\n".join(c.source for c in nb.cells if c.cell_type == "code")
    codigo = "\n".join(re.findall(r'f"""(.*?)"""', codigo, flags=re.S))  # só os SQL (f"""...""")
    return re.sub(r"\{T\(['\"](\w+)['\"]\)\}", r"`projeto.marts.\1`", codigo)


def test_as_consultas_do_notebook_leem_so_dos_marts(nb):
    sql = sql_das_celulas(nb)
    assert "FROM `projeto.marts." in sql
    assert u.tabelas_fora_dos_marts(sql) == []
    assert "raw." not in sql and ".staging." not in sql


def test_todo_acesso_ao_bigquery_passa_pelo_helper_com_teto_de_custo(nb):
    codigo = "\n".join(c.source for c in nb.cells if c.cell_type == "code")
    assert "bigquery" not in codigo.lower().replace("marts", "")  # nada de cliente próprio
    assert codigo.count("sessao.consultar(") == 5


def test_guarda_de_marts_recusa_raw_staging_e_aceita_cte_e_ids_com_hifen():
    assert u.tabelas_fora_dos_marts("SELECT 1 FROM `meu-proj.raw.ons_curva_carga`") == [
        "meu-proj.raw.ons_curva_carga"
    ]
    assert u.tabelas_fora_dos_marts("select * from meu-proj.staging.x join `meu-proj.marts.y`") == [
        "meu-proj.staging.x"
    ]
    sql = "WITH a AS (SELECT 1 FROM `meu-proj.marts.dim_tempo`) SELECT * FROM a"
    assert u.tabelas_fora_dos_marts(sql) == []


def test_consultar_recusa_antes_de_enviar_ao_bigquery():
    sessao = u.Sessao.__new__(u.Sessao)  # sem conectar: a recusa vem antes de qualquer rede
    sessao.registros = []
    with pytest.raises(ValueError, match="só lê dos marts"):
        sessao.consultar("x", "SELECT * FROM `p.raw.ons_curva_carga`")
    assert sessao.registros == []


def test_salvar_figura_recusa_arquivo_grande(tmp_path, monkeypatch):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    monkeypatch.setattr(u, "PASTA_FIGURAS", tmp_path)
    monkeypatch.setattr(u, "RAIZ", tmp_path.parent)
    fig, ax = plt.subplots()
    ax.scatter(*np.random.default_rng(0).random((2, 20000)))  # ruído: PNG pesado
    monkeypatch.setattr(u, "LIMITE_FIGURA_KB", 1)
    with pytest.raises(ValueError, match="limite"):
        u.salvar_figura(fig, "grande")
    plt.close(fig)
