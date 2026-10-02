import csv
import zipfile
from collections import Counter

import pytest

from ingestion import inmet
from ingestion.common.config import Config
from ingestion.common.csv_utils import transformar_csv

CABECALHO = (
    "Data;Hora UTC;PRECIPITAÇÃO TOTAL, HORÁRIO (mm);PRESSAO ATMOSFERICA AO NIVEL DA ESTACAO, "
    "HORARIA (mB);PRESSÃO ATMOSFERICA MAX.NA HORA ANT. (AUT) (mB);PRESSÃO ATMOSFERICA MIN. NA "
    "HORA ANT. (AUT) (mB);RADIACAO GLOBAL (Kj/m²);TEMPERATURA DO AR - BULBO SECO, HORARIA (°C);"
    "TEMPERATURA DO PONTO DE ORVALHO (°C);TEMPERATURA MÁXIMA NA HORA ANT. (AUT) (°C);"
    "TEMPERATURA MÍNIMA NA HORA ANT. (AUT) (°C);TEMPERATURA ORVALHO MAX. NA HORA ANT. (AUT) (°C);"
    "TEMPERATURA ORVALHO MIN. NA HORA ANT. (AUT) (°C);UMIDADE REL. MAX. NA HORA ANT. (AUT) (%);"
    "UMIDADE REL. MIN. NA HORA ANT. (AUT) (%);UMIDADE RELATIVA DO AR, HORARIA (%);"
    "VENTO, DIREÇÃO HORARIA (gr) (° (gr));VENTO, RAJADA MAXIMA (m/s);"
    "VENTO, VELOCIDADE HORARIA (m/s);\n"
)
CONFIG = Config("p", "b", "us-central1")


def csv_da_estacao(codigo, uf, ano, horas=3, temperatura="19,5", codigo_nos_metadados=None):
    meta = (
        f"REGIAO:;SE\nUF:;{uf}\nESTACAO:;ESTACAO {codigo}\n"
        f"CODIGO (WMO):;{codigo_nos_metadados or codigo}\nLATITUDE:;-23,49\n"
        "LONGITUDE:;-46,62\nALTITUDE:;785,64\nDATA DE FUNDACAO:;25/07/06\n"
    )
    # 19 valores + ';' final, como nos arquivos reais (a radiação fica vazia à noite)
    linhas = "".join(
        f"{ano}/01/01;{h:02d}00 UTC;0;926,9;926,9;926,4;;{temperatura};15;19,9;19,4;15,2;14,5;"
        "76;71;75;161;8,8;3,4;\n"
        for h in range(horas)
    )
    return (meta + CABECALHO + linhas).encode("latin-1")


# ---------------------------------------------------------------- estações e ZIPs


def test_37_estacoes_sem_duplicatas_e_so_do_se_co():
    assert len(inmet.ESTACOES) == 37
    por_uf = Counter(uf for uf, _ in inmet.ESTACOES.values())
    assert por_uf == {"MG": 14, "RJ": 6, "DF": 4, "ES": 4, "SP": 4, "GO": 3, "MS": 2}
    assert "MT" not in por_uf  # MT não tem estação aprovada no critério de 95%
    assert "A701" in inmet.ESTACOES  # São Paulo - Mirante


def test_zips_esperados_de_2021_ate_o_ano_atual():
    zips = inmet.zips_esperados(2026)
    assert [z.nome for z in zips] == [f"{ano}.zip" for ano in range(2021, 2027)]
    assert zips[0].caminho_gcs == "bronze/inmet/ano=2021/2021.zip"
    assert len(inmet.zips_esperados(2027)) == 7


def test_zip_ausente_gera_mensagem_clara(tmp_path):
    (tmp_path / "2021.zip").write_bytes(b"x")
    with pytest.raises(inmet.ArquivosAusentes) as erro:
        inmet.verificar_arquivos(tmp_path, inmet.zips_esperados(2022))
    msg = str(erro.value)
    assert "Faltam 1 arquivo(s)" in msg and "2022.zip" in msg
    assert "https://portal.inmet.gov.br/dadoshistoricos" in msg
    assert "https://portal.inmet.gov.br/uploads/dadoshistoricos/2022.zip" in msg
    assert str(tmp_path / "2022.zip") in msg and "docs/fontes.md" in msg


@pytest.mark.parametrize(
    "nome, esperado",
    [
        ("INMET_SE_SP_A701_SAO PAULO - MIRANTE_01-01-2024_A_31-12-2024.CSV", "A701"),
        ("2025/INMET_SE_MG_F501_BELO HORIZONTE - CERCADINHO_01-01-2025_A_31-12-2025.CSV", "F501"),
        ("INMET_CO_DF_A001_BRASILIA_01-01-2021_A_31-12-2021.CSV", "A001"),
        ("2025/", None),  # a pasta
        ("LEIAME.txt", None),
    ],
)
def test_codigo_da_estacao(nome, esperado):
    assert inmet.codigo_da_estacao(nome) == esperado


def test_indexar_estacoes_ignora_a_pasta_do_zip_de_2025():
    nomes = ["2025/", "2025/INMET_SE_SP_A701_X_01-01-2025_A_31-12-2025.CSV"]
    assert inmet.indexar_estacoes(nomes) == {"A701": nomes[1]}


# ---------------------------------------------------------------- validação da estação


def transformado(codigo, uf, ano, **kw):
    dados = csv_da_estacao(codigo, uf, ano, **kw)
    return dados, transformar_csv(
        dados, {}, codificacao="latin-1", pular_linhas=8, descartar_coluna_vazia_final=True
    )


def meta_de(dados):
    return inmet.ler_metadados(dados, 8, codificacao="latin-1")


def test_validar_estacao_aceita_um_arquivo_correto():
    dados, csv_raw = transformado("A701", "SP", 2024)
    assert csv_raw.colunas == inmet.COLUNAS_ESPERADAS  # os 19 nomes reais padronizam como esperado
    inmet.validar_estacao("A701", 2024, meta_de(dados), csv_raw)


def test_validar_estacao_recusa_codigo_diferente_do_nome_do_arquivo():
    dados, csv_raw = transformado("A701", "SP", 2024, codigo_nos_metadados="A702")
    with pytest.raises(ValueError, match="código nos metadados"):
        inmet.validar_estacao("A701", 2024, meta_de(dados), csv_raw)


def test_validar_estacao_recusa_uf_diferente():
    dados, csv_raw = transformado("A701", "RJ", 2024)
    with pytest.raises(ValueError, match="UF"):
        inmet.validar_estacao("A701", 2024, meta_de(dados), csv_raw)


def test_validar_estacao_recusa_zip_de_outro_ano():
    dados, csv_raw = transformado("A701", "SP", 2023)
    with pytest.raises(ValueError, match="não são de 2024"):
        inmet.validar_estacao("A701", 2024, meta_de(dados), csv_raw)


def test_validar_estacao_recusa_layout_diferente():
    dados = csv_da_estacao("A701", "SP", 2024).replace(b"Hora UTC", b"Hora Local")
    csv_raw = transformar_csv(
        dados, {}, codificacao="latin-1", pular_linhas=8, descartar_coluna_vazia_final=True
    )
    with pytest.raises(ValueError, match="layout inesperado"):
        inmet.validar_estacao("A701", 2024, meta_de(dados), csv_raw)


# ---------------------------------------------------------------- blocos


def test_separar_cabecalho_e_bloco():
    cabecalho, corpo = inmet.separar_cabecalho(b"a,b\n1,2\n3,4\n")
    assert cabecalho == b"a,b\n" and corpo == b"1,2\n3,4\n"
    bloco = inmet.Bloco(cabecalho)
    bloco.adicionar(b"1,2\n", 1)
    bloco.adicionar(b"3,4\n", 1)
    assert bloco.conteudo() == b"a,b\n1,2\n3,4\n" and bloco.linhas == 2 and not bloco.cheio


def test_bloco_cheio_ao_passar_do_limite(monkeypatch):
    monkeypatch.setattr(inmet, "BLOCO_BYTES", 10)
    bloco = inmet.Bloco(b"h\n")
    bloco.adicionar(b"123456789\n", 1)
    assert bloco.cheio


# ------------------------------------------------------- carga de ponta a ponta (sem nuvem)


@pytest.fixture
def nuvem_falsa(monkeypatch):
    estado = {"jobs": [], "uploads": []}

    def carregar(cliente, tabela_id, conteudo, esquema, *, truncar):
        linhas = conteudo.count(b"\n") - 1
        estado["jobs"].append((truncar, linhas, conteudo))
        return linhas

    monkeypatch.setattr(inmet.gcp, "cliente_storage", lambda c: object())
    monkeypatch.setattr(inmet.gcp, "cliente_bigquery", lambda c: object())
    monkeypatch.setattr(
        inmet.gcp,
        "enviar_arquivo_para_gcs",
        lambda cli, bucket, caminho, local, tipo=None: (
            estado["uploads"].append(caminho) or f"gs://{bucket}/{caminho}"
        ),
    )
    monkeypatch.setattr(inmet.gcp, "carregar_csv_no_bigquery", carregar)
    monkeypatch.setattr(
        inmet, "ESTACOES", {"A701": ("SP", "SAO PAULO"), "A001": ("DF", "BRASILIA")}
    )
    return estado


def criar_zip(pasta, ano, estacoes=(("A701", "SP"), ("A001", "DF")), subpasta="", **kw):
    caminho = pasta / f"{ano}.zip"
    with zipfile.ZipFile(caminho, "w") as z:
        for codigo, uf in estacoes:
            nome = f"{subpasta}INMET_X_{uf}_{codigo}_NOME_01-01-{ano}_A_31-12-{ano}.CSV"
            z.writestr(nome, csv_da_estacao(codigo, uf, ano, **kw))
    return caminho


def test_carregar_zips_de_ponta_a_ponta(tmp_path, nuvem_falsa):
    criar_zip(tmp_path, 2024, horas=3)
    criar_zip(tmp_path, 2025, horas=2, subpasta="2025/")  # o ZIP de 2025 tem uma pasta
    medicoes = inmet.carregar_zips(
        tmp_path, [inmet.ZipEsperado(2024), inmet.ZipEsperado(2025)], CONFIG
    )

    assert nuvem_falsa["uploads"] == [
        "bronze/inmet/ano=2024/2024.zip",
        "bronze/inmet/ano=2025/2025.zip",
    ]
    assert medicoes.arquivos == 2
    assert medicoes.linhas_csv == medicoes.linhas_carregadas == 2 * 3 + 2 * 2
    assert [j[0] for j in nuvem_falsa["jobs"]] == [True, False]  # só o primeiro trunca
    assert medicoes.por_arquivo[0][0] == "2024.zip" and medicoes.por_arquivo[0][2] == 6
    # uma chave de validação por (ZIP, estação), com linhas e vazios (radiação vazia != temperatura)
    esperado = medicoes.esperado[inmet.NOME_TABELA]
    assert esperado[("bronze/inmet/ano=2024/2024.zip", "A701")] == (3, 0)
    assert len(esperado) == 4
    # o CSV carregado tem o cabeçalho certo e os metadados da estação em cada linha
    conteudo = nuvem_falsa["jobs"][0][2].decode().splitlines()
    assert conteudo[0].endswith(
        "estacao_codigo,estacao_uf,estacao_nome,estacao_latitude,estacao_longitude,"
        "_arquivo_origem,_carregado_em"
    )
    campos = next(csv.reader([conteudo[1]]))
    assert len(campos) == 26  # 19 colunas da fonte + 5 da estação + 2 de controle
    assert campos[19:24] == [
        "A001",
        "DF",
        "ESTACAO A001",
        "-23,49",
        "-46,62",
    ]  # a vírgula decimal fica
    assert campos[24] == "bronze/inmet/ano=2024/2024.zip" and campos[25].endswith("+00:00")
    assert "bronze/inmet/ano=2024/2024.zip" in conteudo[1]
    assert conteudo[1].startswith("2024/01/01,0000 UTC,0,")


def test_carregar_zips_conta_temperatura_vazia(tmp_path, nuvem_falsa):
    criar_zip(tmp_path, 2024, horas=3, temperatura="")
    medicoes = inmet.carregar_zips(tmp_path, [inmet.ZipEsperado(2024)], CONFIG)
    assert medicoes.esperado[inmet.NOME_TABELA][("bronze/inmet/ano=2024/2024.zip", "A701")] == (
        3,
        3,
    )


def test_zip_sem_uma_das_estacoes_selecionadas_falha_antes_de_subir(tmp_path, nuvem_falsa):
    criar_zip(tmp_path, 2024, estacoes=(("A701", "SP"),))
    with pytest.raises(ValueError, match=r"faltam as estações \['A001'\]"):
        inmet.carregar_zips(tmp_path, [inmet.ZipEsperado(2024)], CONFIG)
    assert nuvem_falsa["uploads"] == [] and nuvem_falsa["jobs"] == []


def test_zip_do_ano_errado_e_recusado(tmp_path, nuvem_falsa):
    criar_zip(tmp_path, 2023)
    (tmp_path / "2023.zip").rename(tmp_path / "2024.zip")  # baixou o ZIP errado
    with pytest.raises(ValueError, match="não são de 2024"):
        inmet.carregar_zips(tmp_path, [inmet.ZipEsperado(2024)], CONFIG)


def test_zip_truncado_e_recusado(tmp_path, nuvem_falsa):
    (tmp_path / "2024.zip").write_bytes(b"isto nao e um zip")
    with pytest.raises(zipfile.BadZipFile):
        inmet.carregar_zips(tmp_path, [inmet.ZipEsperado(2024)], CONFIG)
    assert nuvem_falsa["uploads"] == []


def test_consulta_tipica_do_inmet():
    sql = inmet.CONSULTA_TIPICA.format(tabela="p.raw.inmet_estacoes_horario")
    assert "`p.raw.inmet_estacoes_horario`" in sql and "'SP'" in sql and "'2024'" in sql
    assert "REPLACE" in sql and "SAFE_CAST" in sql  # o decimal vem com vírgula, tudo STRING


def test_main_verificar(tmp_path, capsys):
    assert inmet.main(["--pasta", str(tmp_path), "--verificar"]) == 2
    assert "Faltam" in capsys.readouterr().err
