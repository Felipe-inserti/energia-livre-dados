"""Dependências do dashboard: `dashboard/requirements.txt` (o que o Community Cloud lê) bate com o
grupo `dashboard` do pyproject.toml e com o uv.lock, tudo fixado, sem nada do resto do projeto.

O Cloud não lê grupos do pyproject.toml (documentação, "App dependencies"): lê o arquivo que está
na pasta do ponto de entrada, que tem precedência sobre o `uv.lock` da raiz."""

import re
import tomllib
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
REQUIREMENTS = RAIZ / "dashboard" / "requirements.txt"
LINHA = re.compile(r"^([A-Za-z0-9_.\-]+)==([A-Za-z0-9_.!+\-]+)$")
# o que NÃO pode estar no Cloud: o resto do projeto
PROIBIDOS = (
    "dbt",
    "google",
    "statsmodels",
    "scikit",
    "lightgbm",
    "apache-airflow",
    "pytest",
    "ruff",
)


def normal(nome: str) -> str:
    return re.sub(r"[-_.]+", "-", nome).lower()


def requirements() -> dict[str, str]:
    saida = {}
    for linha in REQUIREMENTS.read_text().splitlines():
        if not linha.strip() or linha.startswith("#"):
            continue
        m = LINHA.match(linha.strip())
        assert m, f"linha sem versão fixada (nome==versão): {linha!r}"
        saida[normal(m.group(1))] = m.group(2)
    return saida


def pyproject() -> dict:
    return tomllib.loads((RAIZ / "pyproject.toml").read_text())


def grupo() -> dict[str, str]:
    saida = {}
    for item in pyproject()["dependency-groups"]["dashboard"]:
        m = LINHA.match(item.strip())
        assert m, f"o grupo dashboard tem de fixar a versão (nome==versão): {item!r}"
        saida[normal(m.group(1))] = m.group(2)
    return saida


def versoes_no_lock() -> dict[str, set[str]]:
    lock = tomllib.loads((RAIZ / "uv.lock").read_text())
    saida: dict[str, set[str]] = {}
    for p in lock["package"]:
        saida.setdefault(normal(p["name"]), set()).add(p["version"])
    return saida


def test_streamlit_esta_fixado_na_versao_aprovada():
    assert grupo() == {"streamlit": "1.64.0"}
    assert requirements()["streamlit"] == "1.64.0"


def test_o_requirements_tem_tudo_do_grupo_com_a_mesma_versao():
    pedidos, fixados = grupo(), requirements()
    for nome, versao in pedidos.items():
        assert fixados.get(nome) == versao, (
            f"{nome}: grupo {versao}, requirements {fixados.get(nome)}"
        )


def test_o_requirements_tem_todas_as_versoes_fixadas_e_sem_duplicata():
    linhas = [
        li.strip()
        for li in REQUIREMENTS.read_text().splitlines()
        if li.strip() and not li.startswith("#")
    ]
    nomes = [normal(LINHA.match(li).group(1)) for li in linhas]  # falha se faltar o ==
    assert len(nomes) == len(set(nomes)) and len(nomes) > 10
    # o Streamlit traz o pandas, o pyarrow e o altair: o app os usa direto
    assert {"streamlit", "pandas", "pyarrow", "altair", "numpy"} <= set(nomes)


def test_o_cabecalho_registra_o_comando_que_gerou_o_arquivo():
    cabecalho = "\n".join(li for li in REQUIREMENTS.read_text().splitlines() if li.startswith("#"))
    assert "uv pip compile --group dashboard" in cabecalho
    assert "-o dashboard/requirements.txt" in cabecalho


def test_as_versoes_que_o_app_usa_direto_sao_as_do_lock():
    """pandas, pyarrow, altair e numpy: o app roda nos testes com o que o `uv.lock` fixa; o Cloud
    instala o `requirements.txt`. Os dois têm de ser a mesma versão. (As dependências indiretas
    podem diferir: o lock é do projeto inteiro, o requirements só do dashboard.)"""
    fixados, lock = requirements(), versoes_no_lock()
    for nome in ("streamlit", "pandas", "pyarrow", "altair", "numpy"):
        assert fixados[nome] in lock[nome], (
            f"{nome}: {fixados[nome]} não está no uv.lock ({lock[nome]})"
        )


def test_nada_do_resto_do_projeto_vai_para_o_cloud():
    for nome in requirements():
        assert not nome.startswith(PROIBIDOS), f"{nome} não deve estar no requirements do dashboard"


def test_o_grupo_esta_nos_grupos_padrao_e_fora_da_imagem_do_airflow():
    assert "dashboard" in pyproject()["tool"]["uv"]["default-groups"]
    dockerfile = (RAIZ / "airflow" / "Dockerfile").read_text()
    assert "--group dashboard" not in dockerfile  # a imagem instala só `dbt` e `ml`


def test_o_requirements_fica_ao_lado_do_ponto_de_entrada():
    """Precedência da documentação: o arquivo ao lado do entrypoint vale mais que o `uv.lock`."""
    assert REQUIREMENTS.parent.name == "dashboard"
    assert (
        RAIZ / "uv.lock"
    ).exists()  # existe na raiz: por isso o arquivo ao lado do app é obrigatório
