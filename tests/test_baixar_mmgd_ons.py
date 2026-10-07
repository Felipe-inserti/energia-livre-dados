"""`scripts/baixar_mmgd_ons.py`: saneamento do JSON inválido da API, médias mensais, status dos
componentes e o CSV do seed. O exemplo vem de resposta REAL da API (tests/fixtures), com o
defeito que quebra `json.loads`: campos vazios (`"val_cargammgd": ,`)."""

import csv
import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from scripts import baixar_mmgd_ons as m

EXEMPLO = Path(__file__).resolve().parent / "fixtures" / "carga_verificada_exemplo.json"


def test_o_exemplo_real_nao_e_json_valido():
    # prova de que o saneamento é necessário: o json padrão recusa a resposta da API
    with pytest.raises(json.JSONDecodeError):
        json.loads(EXEMPLO.read_text())


def test_sanear_json_troca_campo_vazio_por_null():
    registros = m.sanear_json(EXEMPLO.read_text())
    assert len(registros) == 5
    assert registros[0]["val_cargammgd"] is None
    assert registros[0]["val_cargaglobalsmmgd"] is None
    assert registros[0]["val_cargaglobal"] == 31336.965  # o campo preenchido não muda
    assert registros[2]["val_cargammgd"] == 41.8102  # 2019-02-15: primeiro dia com MMGD


def test_sanear_json_nao_mexe_em_json_valido_nem_em_texto_com_virgula():
    texto = '[{"a": 1, "b": "x: ,y", "c": null}]'
    assert m.sanear_json(texto) == [{"a": 1, "b": "x: ,y", "c": None}]


def _registro(utc, glob, liq=None, mmgd=None, atualizado="2026-08-14T03:00:00.000Z", area="SECO"):
    return {
        "cod_areacarga": area,
        "din_atualizacao": atualizado,
        "dat_referencia": utc[:10],
        "din_referenciautc": utc,
        "val_cargaglobal": glob,
        "val_cargaglobalsmmgd": liq,
        "val_cargammgd": mmgd,
    }


def test_media_mensal_trata_mmgd_vazia_como_zero_e_liquida_vazia_como_global():
    regs = [
        _registro("2019-02-10T03:00:00.000Z", 100.0),  # sem MMGD: liquida = global, mmgd = 0
        _registro("2019-02-20T03:00:00.000Z", 120.0, liq=116.0, mmgd=4.0),
    ]
    v = m.agregar_mensal(regs)[("2019-02", "SECO")]
    assert v["api_global_mwmed"] == 110.0
    assert v["api_liquida_mwmed"] == 108.0  # (100 + 116) / 2
    assert v["api_mmgd_mwmed"] == 2.0  # (0 + 4) / 2
    assert (v["api_intervalos"], v["api_intervalos_sem_mmgd"]) == (2, 1)


def test_global_igual_liquida_mais_mmgd_no_exemplo_real():
    regs = m.sanear_json(EXEMPLO.read_text())[2:]  # só registros com MMGD preenchida
    for r in regs:
        assert r["val_cargaglobal"] == pytest.approx(r["val_cargaglobalsmmgd"] + r["val_cargammgd"])


def test_deduplica_pelo_instante_ficando_com_a_atualizacao_mais_nova():
    antigo = _registro("2019-03-01T03:00:00.000Z", 100.0, atualizado="2020-01-01T00:00:00.000Z")
    novo = _registro("2019-03-01T03:00:00.000Z", 90.0, atualizado="2026-01-01T00:00:00.000Z")
    for ordem in ([antigo, novo], [novo, antigo]):
        v = m.agregar_mensal(ordem)[("2019-03", "SECO")]
        assert v["api_global_mwmed"] == 90.0 and v["api_intervalos"] == 1


def test_descarta_registro_sem_carga_global():
    assert m.agregar_mensal([_registro("2019-03-01T03:00:00.000Z", None)]) == {}


@pytest.mark.parametrize(
    ("mes", "intervalos", "sem_mmgd", "esperado"),
    [
        ("2018-12", 100, 100, "zero_por_premissa"),
        ("2019-01", 100, 100, "zero_por_premissa"),
        ("2019-02", 100, 40, "medido_parcial"),  # a API só preenche a partir de 15/02
        ("2019-03", 100, 0, "medido"),
        ("2023-04", 100, 0, "medido"),  # último mês antes da quebra
        ("2023-05", 100, 0, "incorporado_na_curva"),  # a quebra do DADO é 01/05/2023, não 29/04
        ("2024-04", 100, 0, "incorporado_na_curva"),
    ],
)
def test_status_mmgd(mes, intervalos, sem_mmgd, esperado):
    assert m.status_mmgd(mes, intervalos, sem_mmgd) == esperado


@pytest.mark.parametrize(
    ("mes", "esperado"),
    [("2018-01", "medido"), ("2021-02", "medido"), ("2021-03", "incorporado_na_curva")],
)
def test_status_tipo3(mes, esperado):
    assert m.status_tipo3(mes) == esperado


def test_meses_cobre_o_intervalo_inclusivo_com_ultimo_dia_certo():
    r = m.meses("2023-12", "2024-02")
    assert r == [
        (date(2023, 12, 1), date(2023, 12, 31)),
        (date(2024, 1, 1), date(2024, 1, 31)),
        (date(2024, 2, 1), date(2024, 2, 29)),  # bissexto
    ]


def test_gerar_de_ponta_a_ponta_com_api_de_mentira(tmp_path):
    def api(url, **_):
        area = url.split("cod_areacarga=")[1]
        mes = url.split("dat_inicio=")[1][:7]
        n = 28 * 48 if mes == "2019-02" else 31 * 48
        texto = ",".join(
            json.dumps(
                _registro(
                    f"{mes}-{1 + i % 27:02d}T{i % 24:02d}:{30 * (i % 2):02d}:00.000Z",
                    100.0 + i,
                    area=area,
                )
            )
            .replace('"val_cargaglobalsmmgd": null', '"val_cargaglobalsmmgd": ')
            .replace('"val_cargammgd": null', '"val_cargammgd": ')
            for i in range(n)
        )
        return f"[{texto}]".encode()

    linhas = m.gerar("2019-02", "2019-03", baixar=api)
    assert {(x["mes"], x["codigo_submercado"]) for x in linhas} == {
        (f"2019-0{k}-01", sm) for k in (2, 3) for sm in ("SE", "S", "NE", "N")
    }
    destino = tmp_path / "seed.csv"
    m.gravar(linhas, destino)
    lidas = list(csv.DictReader(destino.open()))
    assert tuple(lidas[0]) == m.COLUNAS
    assert lidas[0]["status_mmgd"] == "zero_por_premissa"  # a API de mentira não traz MMGD
    assert lidas[0]["status_tipo3"] == "medido"
    assert lidas[0]["consultado_em"] == datetime.now(UTC).date().isoformat()


def test_mes_com_intervalos_a_menos_derruba_a_geracao():
    def api(url, **_):
        return b"[]"

    with pytest.raises(RuntimeError, match="intervalos"):
        m.baixar_mes("SECO", date(2019, 3, 1), date(2019, 3, 31), api)
