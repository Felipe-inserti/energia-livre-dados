"""`scripts/verificar_incremental.py`: ferramenta permanente para provar que um modelo incremental
dá o mesmo resultado de um build full, SÓ no dataset `verificacao_incremental`."""

import pytest

from scripts import verificar_incremental as v


class Config:
    projeto = "proj"

    def tabela(self, dataset, nome):
        return f"proj.{dataset}.{nome}"


def test_so_o_dataset_de_verificacao_e_aceito():
    assert v.tabela_segura(Config(), "verificacao_incremental.stg_x") == (
        "proj.verificacao_incremental.stg_x"
    )
    for ruim in ("staging.stg_x", "marts.fct_x", "raw.ons_curva_carga", "stg_x", "a.b.c", ""):
        with pytest.raises(ValueError):
            v.tabela_segura(Config(), ruim)


def test_except_nos_dois_sentidos_e_so_as_colunas_pedidas():
    sql = v.sql_except("p.d.a", "p.d.b", ["x", "y"])
    assert "select x, y from `p.d.a` except distinct select x, y from `p.d.b`" in sql
    assert v.sql_except("p.d.b", "p.d.a", ["x"]).count("except distinct") == 1


def test_colunas_comparadas_tiram_as_excluidas_e_exigem_as_mesmas_colunas():
    class Coluna:
        def __init__(self, nome):
            self.name = nome

    class Tabela:
        def __init__(self, *nomes):
            self.schema = [Coluna(n) for n in nomes]

    class Cliente:
        def __init__(self, tabelas):
            self.tabelas = tabelas

        def get_table(self, id_):
            return self.tabelas[id_]

    cli = Cliente(
        {"a": Tabela("id", "valor", "_carregado_em"), "b": Tabela("valor", "id", "_carregado_em")}
    )
    assert v.colunas_comuns(cli, "a", "b", {"_carregado_em"}) == ["id", "valor"]
    cli.tabelas["b"] = Tabela("id", "outra")
    with pytest.raises(ValueError, match="colunas diferentes"):
        v.colunas_comuns(cli, "a", "b", set())


def test_grupos_diferentes_lista_so_os_que_diferem_e_aceita_ruido_de_soma():
    a = {("2026-09", "SE"): (100, 100, 5.0), ("2026-10", "SE"): (50, 50, 2.0)}
    b = {
        ("2026-09", "SE"): (100, 100, 5.004),
        ("2026-10", "SE"): (49, 49, 2.0),
        ("2026-11", "SE"): (1, 1, 1.0),
    }
    dif, total = v.grupos_diferentes(a, b)
    assert total == 3 and len(dif) == 2
    assert any("2026-10" in x for x in dif) and any("2026-11" in x for x in dif)


def test_sql_dos_grupos_agrupa_por_mes_utc_e_submercado():
    sql = v.sql_grupos("p.d.t", "id_subsistema", "carga_mwmed")
    assert "format_timestamp('%Y-%m', instante_utc)" in sql and "group by 1, 2" in sql


def test_apagar_particoes_recusa_dataset_e_formato_invalidos_e_apaga_so_as_pedidas(monkeypatch):
    apagadas = []

    class Cliente:
        def delete_table(self, id_, not_found_ok):
            apagadas.append(id_)

    monkeypatch.setattr(v, "carregar_config", lambda: Config())
    monkeypatch.setattr(v.gcp, "cliente_bigquery", lambda config: Cliente())
    v.apagar_particoes("verificacao_incremental.t", ["202608", "202609"])
    assert apagadas == [
        "proj.verificacao_incremental.t$202608",
        "proj.verificacao_incremental.t$202609",
    ]
    with pytest.raises(ValueError):
        v.apagar_particoes("marts.fct_carga_horaria", ["202608"])  # nunca a produção
    with pytest.raises(ValueError):
        v.apagar_particoes("verificacao_incremental.t", ["2026-08"])
    assert len(apagadas) == 2  # as recusas não apagaram nada


def test_parser_exige_os_argumentos_de_cada_comando():
    p = v.montar_parser()
    assert (
        p.parse_args(["comparar", "--a", "d.a", "--b", "d.b", "--submercado", "s"]).comando
        == "comparar"
    )
    assert (
        p.parse_args(["apagar-particoes", "--tabela", "d.t", "--particoes", "202608"]).particoes
        == "202608"
    )
    with pytest.raises(SystemExit):
        v.main(["comparar"])
    with pytest.raises(SystemExit):
        v.main(["apagar-particoes"])
