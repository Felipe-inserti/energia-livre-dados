import pytest

from ingestion.common.csv_utils import padronizar_coluna, padronizar_colunas, transformar_csv


@pytest.mark.parametrize(
    "original, esperado",
    [
        ("id_subsistema", "id_subsistema"),  # já padronizado: não muda
        ("DIREÇÃO", "direcao"),
        ("Hora UTC", "hora_utc"),
        ("TEMPERATURA DO AR - BULBO SECO, HORARIA (°C)", "temperatura_do_ar_bulbo_seco_horaria_c"),
        ("RADIACAO GLOBAL (Kj/m²)", "radiacao_global_kj_m2"),
        ("VENTO, DIREÇÃO HORARIA (gr) (° (gr))", "vento_direcao_horaria_gr_gr"),
        ("  Data  ", "data"),
        ("2024 total", "c_2024_total"),  # BigQuery não aceita começar com dígito
    ],
)
def test_padronizar_coluna(original, esperado):
    assert padronizar_coluna(original) == esperado


def test_padronizar_coluna_vazia_gera_erro():
    with pytest.raises(ValueError):
        padronizar_coluna(" (°) ")


def test_padronizar_colunas_recusa_colisao():
    with pytest.raises(ValueError, match="duplicadas"):
        padronizar_colunas(["Hora UTC", "hora_utc"])


ORIGINAL = (
    b"id_subsistema;nom_subsistema;din_instante;val_cargaenergiahomwmed\n"
    b"N;NORTE;2014-10-19 00:00:00;\n"
    b"SE;SUDESTE;2014-10-19 01:00:00;31660.899\n"
    b"\n"
)


def test_transformar_csv_acrescenta_colunas_e_preserva_valores():
    extras = {"_arquivo_origem": "bronze/x.csv", "_carregado_em": "2026-10-02T12:00:00+00:00"}
    resultado = transformar_csv(ORIGINAL, extras)
    linhas = resultado.conteudo.decode().splitlines()
    assert linhas[0] == (
        "id_subsistema,nom_subsistema,din_instante,val_cargaenergiahomwmed,"
        "_arquivo_origem,_carregado_em"
    )
    assert linhas[1] == "N,NORTE,2014-10-19 00:00:00,,bronze/x.csv,2026-10-02T12:00:00+00:00"
    assert linhas[2].startswith("SE,SUDESTE,2014-10-19 01:00:00,31660.899,bronze/x.csv")
    assert len(linhas) == 3  # a linha em branco do fim não vira linha de dados
    assert resultado.linhas == 2
    assert resultado.vazios["val_cargaenergiahomwmed"] == 1  # o campo vazio continua vazio
    assert resultado.colunas == [
        "id_subsistema",
        "nom_subsistema",
        "din_instante",
        "val_cargaenergiahomwmed",
    ]


def test_transformar_csv_nao_altera_os_bytes_originais():
    copia = bytes(ORIGINAL)
    transformar_csv(ORIGINAL, {"_arquivo_origem": "x"})
    assert ORIGINAL == copia


def test_transformar_csv_aceita_bom_e_aspas():
    conteudo = b'\xef\xbb\xbf"a";"b"\n"1";"x;y"\n'
    resultado = transformar_csv(conteudo, {"_e": "1"})
    assert resultado.colunas == ["a", "b"]
    assert resultado.conteudo.decode().splitlines()[1] == "1,x;y,1"


def test_transformar_csv_linha_com_campos_a_mais_gera_erro():
    with pytest.raises(ValueError, match="Linha 2"):
        transformar_csv(b"a;b\n1;2;3\n", {"_e": "1"})


def test_colunas_da_fonte_nunca_comecam_com_underscore_mas_extra_igual_colide():
    with pytest.raises(ValueError, match="colidem"):
        transformar_csv(b"a;e\n1;2\n", {"e": "1"})


def test_nome_com_underscore_na_fonte_nao_pode_imitar_coluna_de_controle():
    # '_arquivo_origem' na fonte viraria 'arquivo_origem' (underscore inicial é removido)
    assert padronizar_coluna("_arquivo_origem") == "arquivo_origem"
