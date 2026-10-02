from dataclasses import dataclass

import pytest

from ingestion.common import manual


@dataclass(frozen=True)
class Item:
    nome: str
    descricao: str = "descrição"
    pagina: str = "https://exemplo/pagina"


def test_pasta_completa_nao_levanta(tmp_path):
    (tmp_path / "a.csv").write_bytes(b"x")
    manual.verificar_arquivos(tmp_path, [Item("a.csv")], "docs/x.md")


def test_mensagem_lista_so_o_que_falta(tmp_path):
    (tmp_path / "a.csv").write_bytes(b"x")
    esperados = [Item("a.csv"), Item("b.csv", "o arquivo B"), Item("c.csv")]
    with pytest.raises(manual.ArquivosAusentes) as erro:
        manual.verificar_arquivos(tmp_path, esperados, "docs/x.md, seção Y")
    msg = str(erro.value)
    assert "Faltam 2 arquivo(s)" in msg
    assert "b.csv: o arquivo B" in msg and "c.csv" in msg and "a.csv" not in msg
    assert f"salve como {tmp_path / 'b.csv'}" in msg
    assert "baixe em https://exemplo/pagina" in msg
    assert "Passo a passo: docs/x.md, seção Y." in msg


def test_diretorio_com_o_nome_do_arquivo_nao_conta_como_arquivo(tmp_path):
    (tmp_path / "a.csv").mkdir()
    with pytest.raises(manual.ArquivosAusentes):
        manual.verificar_arquivos(tmp_path, [Item("a.csv")], "docs/x.md")
