import pytest

from ingestion import ons


def test_montar_url_por_ano():
    assert ons.montar_url(2024) == (
        "https://ons-aws-prod-opendata.s3.amazonaws.com/dataset/curva-carga-ho/CURVA_CARGA_2024.csv"
    )
    assert ons.montar_url(2000).endswith("/CURVA_CARGA_2000.csv")


def test_caminho_no_gcs_da_bronze():
    assert ons.caminho_gcs(2024) == "bronze/ons/curva_carga/ano=2024/CURVA_CARGA_2024.csv"
    assert ons.caminho_gcs(2000) == "bronze/ons/curva_carga/ano=2000/CURVA_CARGA_2000.csv"
    assert ons.nome_arquivo(2026) == "CURVA_CARGA_2026.csv"


def test_anos_a_carregar_de_2000_ate_o_ano_final():
    assert ons.anos_a_carregar(2000, 2003) == [2000, 2001, 2002, 2003]
    assert len(ons.anos_a_carregar(2000, 2026)) == 27


def test_anos_invalidos():
    with pytest.raises(ValueError):
        ons.anos_a_carregar(1999, 2020)  # 1999 não existe no ONS
    with pytest.raises(ValueError):
        ons.anos_a_carregar(2020, 2019)


def test_validar_colunas_aceita_o_layout_conhecido_e_recusa_mudanca():
    ons.validar_colunas(list(ons.COLUNAS_ESPERADAS))
    with pytest.raises(ValueError, match="Layout inesperado"):
        ons.validar_colunas(["id_subsistema", "din_instante"])


def test_consultas_citam_a_tabela_do_raw_e_nao_a_do_bronze():
    sql = ons.CONSULTA_TIPICA.format(tabela="p.raw.ons_curva_carga")
    assert "`p.raw.ons_curva_carga`" in sql and "'SE'" in sql and "2024-01-01" in sql
