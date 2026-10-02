import pytest

from ingestion.common.csv_utils import (
    ler_metadados,
    padronizar_coluna,
    padronizar_colunas,
    transformar_csv,
)


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


# ---------------------------------------------------------------- formato do INMET

INMET = (
    "REGIAO:;SE\n"
    "UF:;SP\n"
    "ESTACAO:;SAO PAULO - MIRANTE\n"
    "CODIGO (WMO):;A701\n"
    "LATITUDE:;-23,49638888\n"
    "LONGITUDE:;-46,61999999\n"
    "ALTITUDE:;785,64\n"
    "DATA DE FUNDACAO:;25/07/06\n"
    "Data;Hora UTC;PRECIPITAÇÃO TOTAL, HORÁRIO (mm);RADIACAO GLOBAL (Kj/m²);\n"
    "2024/01/01;0000 UTC;0;;\n"
    "2024/01/01;0100 UTC;0,2;12,5;\n"
).encode("latin-1")


def test_ler_metadados():
    meta = ler_metadados(INMET, 8, codificacao="latin-1")
    assert meta["CODIGO (WMO)"] == "A701" and meta["UF"] == "SP"
    assert meta["LATITUDE"] == "-23,49638888"  # o decimal com vírgula fica como veio
    assert len(meta) == 8


def test_transformar_csv_do_inmet_pula_metadados_e_descarta_coluna_vazia():
    resultado = transformar_csv(
        INMET,
        {"estacao_codigo": "A701"},
        codificacao="latin-1",
        pular_linhas=8,
        descartar_coluna_vazia_final=True,
    )
    assert resultado.colunas == [
        "data",
        "hora_utc",
        "precipitacao_total_horario_mm",
        "radiacao_global_kj_m2",
    ]
    linhas = resultado.conteudo.decode().splitlines()
    assert (
        linhas[0]
        == "data,hora_utc,precipitacao_total_horario_mm,radiacao_global_kj_m2,estacao_codigo"
    )
    assert linhas[1] == "2024/01/01,0000 UTC,0,,A701"
    assert linhas[2] == '2024/01/01,0100 UTC,"0,2","12,5",A701'  # a vírgula decimal é protegida
    assert resultado.linhas == 2 and resultado.vazios["radiacao_global_kj_m2"] == 1
    assert resultado.metadados["ESTACAO"] == "SAO PAULO - MIRANTE"


def test_sem_descartar_a_coluna_vazia_o_cabecalho_com_separador_final_falha():
    with pytest.raises(ValueError, match="vazio"):
        transformar_csv(INMET, {}, codificacao="latin-1", pular_linhas=8)


def test_erro_de_linha_conta_as_linhas_puladas():
    ruim = INMET + b"2024/01/01;0200 UTC;1;2;3;4;5;\n"
    with pytest.raises(ValueError, match="Linha 12"):
        transformar_csv(
            ruim, {}, codificacao="latin-1", pular_linhas=8, descartar_coluna_vazia_final=True
        )


def test_menos_linhas_de_metadados_do_que_o_pedido():
    with pytest.raises(ValueError, match="menos de 8"):
        transformar_csv(b"a;b\n", {}, pular_linhas=8)
