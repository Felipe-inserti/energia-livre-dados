import pytest

from ingestion.common.config import Config, carregar_config


def test_carregar_config_com_ambiente_completo():
    config = carregar_config(
        {"GCP_PROJECT_ID": " meu-projeto ", "GCS_BUCKET": "bucket", "BQ_LOCATION": "us-central1"}
    )
    assert config == Config("meu-projeto", "bucket", "us-central1")
    assert config.tabela("raw", "ons_curva_carga") == "meu-projeto.raw.ons_curva_carga"


def test_carregar_config_lista_so_os_nomes_ausentes():
    ambiente = {"GCP_PROJECT_ID": "segredo-que-nao-pode-aparecer", "GCS_BUCKET": "  "}
    with pytest.raises(ValueError) as erro:
        carregar_config(ambiente)
    mensagem = str(erro.value)
    assert "GCS_BUCKET" in mensagem and "BQ_LOCATION" in mensagem
    assert "GCP_PROJECT_ID" not in mensagem  # só os ausentes
    assert "segredo-que-nao-pode-aparecer" not in mensagem  # nunca valores
