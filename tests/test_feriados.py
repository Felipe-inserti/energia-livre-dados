from datetime import date

import pytest

from ingestion import feriados


def test_listar_feriados_2000_a_2030():
    f = feriados.listar_feriados(2000, 2030)
    datas = [d for d, _ in f]
    assert datas == sorted(datas) and len(set(datas)) == len(datas)  # ordem e uma linha por data
    assert all(date.fromisoformat(d) for d in datas)  # texto ISO válido
    assert datas[0].startswith("2000-") and datas[-1].startswith("2030-")
    assert ("2021-01-01", "Confraternização Universal") in f


def test_data_com_dois_feriados_vem_numa_linha_so():
    f = dict(feriados.listar_feriados(2000, 2030))
    assert f["2000-04-21"] == "Sexta-feira Santa; Tiradentes"


def test_consciencia_negra_so_aparece_a_partir_de_2024():
    f = dict(feriados.listar_feriados(2020, 2025))
    assert "2023-11-20" not in f
    assert "Consciência Negra" in f["2024-11-20"]


def test_anos_invalidos():
    with pytest.raises(ValueError):
        feriados.listar_feriados(2030, 2000)


def test_montar_csv():
    csv_ = feriados.montar_csv(
        [("2021-01-01", "Ano Novo, o primeiro")], "2026-10-02T12:00:00+00:00"
    )
    linhas = csv_.decode().splitlines()
    assert linhas[0] == "data,nome,_carregado_em"
    assert (
        linhas[1] == '2021-01-01,"Ano Novo, o primeiro",2026-10-02T12:00:00+00:00'
    )  # vírgula protegida
