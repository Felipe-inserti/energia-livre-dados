from datetime import UTC, datetime

import pytest

from ingestion import ccee
from ingestion.common.csv_utils import transformar_csv

# Layout 2021-2024: aspas, CRLF e zeros à esquerda. Layout 2025-2026: sem aspas, LF, sem zeros.
LAYOUT_ANTIGO = (
    b'"MES_REFERENCIA";"SUBMERCADO";"PERIODO_COMERCIALIZACAO";"DIA";"HORA";"PLD_HORA"\r\n'
    b'"202401";NORDESTE;1;"01";"00";61.07\r\n'
)
LAYOUT_NOVO = (
    b"MES_REFERENCIA;SUBMERCADO;PERIODO_COMERCIALIZACAO;DIA;HORA;PLD_HORA\n"
    b"202512;NORDESTE;721;1;0;205.25\n"
)
EXTRAS = {"_arquivo_origem": "bronze/x.csv", "_carregado_em": "2026-10-02T12:00:00+00:00"}


def transformar(conteudo):
    return transformar_csv(conteudo, EXTRAS)


def esperado(nome):
    return next(a for a in ccee.arquivos_esperados(2026) if a.nome == nome)


# ---------------------------------------------------------------- arquivos esperados


def test_arquivos_esperados_ate_o_ano_atual():
    nomes = [a.nome for a in ccee.arquivos_esperados(2026)]
    assert nomes[:6] == [f"pld_horario_{ano}.csv" for ano in range(2021, 2027)]
    assert "pld_historico_semanal_2001_2020.csv" in nomes
    assert nomes[-3:] == [f"consumo_ramo_atividade_{ano}.csv" for ano in (2024, 2025, 2026)]
    assert len(nomes) == 10
    assert len(ccee.arquivos_esperados(2027)) == 12  # um PLD horário e um consumo a mais


def test_caminhos_no_gcs_da_bronze():
    assert esperado("pld_horario_2024.csv").caminho_gcs == (
        "bronze/ccee/pld_horario/ano=2024/pld_horario_2024.csv"
    )
    assert esperado("pld_historico_semanal_2001_2020.csv").caminho_gcs == (
        "bronze/ccee/pld_semanal/pld_historico_semanal_2001_2020.csv"
    )
    assert esperado("consumo_ramo_atividade_2025.csv").caminho_gcs == (
        "bronze/ccee/consumo_ramo_atividade/ano=2025/consumo_ramo_atividade_2025.csv"
    )


def test_tabelas_do_raw():
    assert esperado("pld_horario_2021.csv").conjunto.tabela == "ccee_pld_horario"
    assert esperado("pld_historico_semanal_2001_2020.csv").conjunto.tabela == "ccee_pld_semanal"
    assert esperado("consumo_ramo_atividade_2024.csv").conjunto.tabela == (
        "ccee_consumo_ramo_atividade"
    )


def test_verificar_arquivos_todos_presentes(tmp_path):
    esperados = ccee.arquivos_esperados(2026)
    for arq in esperados:
        (tmp_path / arq.nome).write_bytes(b"x")
    ccee.verificar_arquivos(tmp_path, esperados)  # não levanta


def test_arquivo_ausente_gera_mensagem_clara(tmp_path):
    esperados = ccee.arquivos_esperados(2026)
    for arq in esperados:
        if arq.nome not in {"pld_horario_2026.csv", "pld_historico_semanal_2001_2020.csv"}:
            (tmp_path / arq.nome).write_bytes(b"x")
    with pytest.raises(ccee.ArquivosAusentes) as erro:
        ccee.verificar_arquivos(tmp_path, esperados)
    mensagem = str(erro.value)
    assert "Faltam 2 arquivo(s)" in mensagem
    assert "pld_horario_2026.csv" in mensagem
    assert "pld_historico_semanal_2001_2020.csv" in mensagem
    assert 'recurso "2026"' in mensagem and 'recurso "2001-2020"' in mensagem
    assert "https://dadosabertos.ccee.org.br/dataset/pld_horario" in mensagem
    assert str(tmp_path / "pld_horario_2026.csv") in mensagem  # onde salvar
    assert "docs/fontes.md" in mensagem
    assert "pld_horario_2025.csv" not in mensagem  # só os que faltam


# ---------------------------------------------------------------- layouts e validação


def test_dois_layouts_do_pld_viram_o_mesmo_formato_sem_alterar_valores():
    antigo = transformar(LAYOUT_ANTIGO)
    novo = transformar(LAYOUT_NOVO)
    assert antigo.colunas == novo.colunas == ccee.COLUNAS_PLD
    linha_antiga = antigo.conteudo.decode().splitlines()[1]
    linha_nova = novo.conteudo.decode().splitlines()[1]
    # zeros à esquerda preservados no layout antigo; sem zeros no novo (o raw guarda como veio)
    assert linha_antiga.startswith("202401,NORDESTE,1,01,00,61.07,")
    assert linha_nova.startswith("202512,NORDESTE,721,1,0,205.25,")


def test_meses_do_csv():
    assert ccee.meses_do_csv(transformar(LAYOUT_ANTIGO).conteudo) == {"202401"}


def test_validar_conteudo_aceita_arquivo_do_ano_certo():
    ccee.validar_conteudo(esperado("pld_horario_2024.csv"), transformar(LAYOUT_ANTIGO))
    ccee.validar_conteudo(esperado("pld_horario_2025.csv"), transformar(LAYOUT_NOVO))


def test_validar_conteudo_recusa_arquivo_de_outro_ano():
    with pytest.raises(ValueError, match="outro ano"):
        ccee.validar_conteudo(esperado("pld_horario_2025.csv"), transformar(LAYOUT_ANTIGO))


def test_validar_conteudo_do_semanal_exige_meses_de_2001_a_2020():
    semanal = esperado("pld_historico_semanal_2001_2020.csv")
    dentro = LAYOUT_ANTIGO.replace(b"202401", b"201912")
    ccee.validar_conteudo(semanal, transformar(dentro))  # não levanta
    with pytest.raises(ValueError, match="fora de 200101"):
        ccee.validar_conteudo(semanal, transformar(LAYOUT_ANTIGO))  # 202401 não é histórico


def test_validar_conteudo_recusa_colunas_diferentes():
    consumo = b"MES_REFERENCIA;RAMO_ATIVIDADE;CONSUMO_CL_ESP_ACL\n202404;COMERCIO;1.5\n"
    with pytest.raises(ValueError, match="colunas"):
        ccee.validar_conteudo(esperado("consumo_ramo_atividade_2024.csv"), transformar(consumo))


def test_validar_conteudo_recusa_arquivo_sem_linhas():
    vazio = b"MES_REFERENCIA;SUBMERCADO;PERIODO_COMERCIALIZACAO;DIA;HORA;PLD_HORA\n"
    with pytest.raises(ValueError, match="sem linhas"):
        ccee.validar_conteudo(esperado("pld_horario_2024.csv"), transformar(vazio))


def test_consumo_com_acento_em_utf8_passa_pela_transformacao():
    consumo = (
        "MES_REFERENCIA;RAMO_ATIVIDADE;CONSUMO_CL_ESP_ACL;CONSUMO_AUTOP_ACL;"
        "CONSUMO_PONTO_CONEXAO_CL_ESP_ACL;CONSUMO_PONTO_CONEXAO_AUTOP_ACL\n"
        "202412;TÊXTEIS;498.1;4.7;486.3;4.6\n"
    ).encode()
    resultado = transformar(consumo)
    ccee.validar_conteudo(esperado("consumo_ramo_atividade_2024.csv"), resultado)
    assert "TÊXTEIS" in resultado.conteudo.decode()


# ---------------------------------------------------------------- consulta e CLI


def test_consulta_tipica_usa_a_tabela_horaria_e_o_sudeste_de_2024():
    sql = ccee.CONSULTA_TIPICA.format(tabela="p.raw.ccee_pld_horario")
    assert "`p.raw.ccee_pld_horario`" in sql
    assert "'SUDESTE'" in sql and "'2024'" in sql


def test_main_verificar_com_pasta_incompleta_devolve_2(tmp_path, capsys):
    (tmp_path / "pld_horario_2021.csv").write_bytes(b"x")
    assert ccee.main(["--pasta", str(tmp_path), "--verificar"]) == 2
    assert "Faltam" in capsys.readouterr().err


def test_main_verificar_com_pasta_completa_devolve_0(tmp_path, capsys):
    for arq in ccee.arquivos_esperados(datetime.now(UTC).year):
        (tmp_path / arq.nome).write_bytes(b"x")
    assert ccee.main(["--pasta", str(tmp_path), "--verificar"]) == 0
    assert "ok:" in capsys.readouterr().out
