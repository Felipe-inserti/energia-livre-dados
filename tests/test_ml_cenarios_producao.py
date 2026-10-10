"""Cadeia mensal, passo 2 (C1): cenários só da origem de produção nova, id próprio, sem backtest."""

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_ml_cenarios_sens import erros_sinteticos, pld_sintetico

from ml import cenarios as cen
from ml import otimizacao as ot
from ml.cenarios_consumo import execucao_id
from ml.intervalos import Erro
from ml.validacao import HORIZONTES

K = 1e-5
N = 20
ORIGEM = date(2026, 10, 1)
PREVISTO = [15_000.0 + 10 * h for h in HORIZONTES]
PROV = {"codigo_hash": "x", "commit": "c" * 40, "gerado_em": "2026-10-11T00:00:00Z"}
RAIZ = Path(__file__).resolve().parents[1]
MIB = 1024 * 1024


@pytest.fixture(scope="module")
def erros():
    return erros_sinteticos()


@pytest.fixture(scope="module")
def gerado(erros):
    return cen.gerar_cenarios_da_origem(ORIGEM, PREVISTO, erros, pld_sintetico(), K, n=N, prov=PROV)


# ---- nenhuma origem de backtest


@pytest.mark.parametrize("origem", [*cen.ORIGENS_DE_BACKTEST, date(2020, 1, 1), date(2024, 11, 1)])
def test_a_cadeia_recusa_as_origens_do_backtest(origem, erros):
    with pytest.raises(cen.ErroDeOrigem, match="backtest"):
        cen.conferir_origem_de_producao(origem)
    with pytest.raises(cen.ErroDeOrigem):
        cen.gerar_cenarios_da_origem(origem, PREVISTO, erros, pld_sintetico(), K, n=N)


@pytest.mark.parametrize("origem", [date(2025, 1, 1), date(2026, 9, 1), date(2026, 12, 1)])
def test_a_cadeia_aceita_origens_posteriores_ao_backtest(origem):
    cen.conferir_origem_de_producao(origem)


def test_as_origens_do_backtest_sao_as_5_dezembros_de_2020_a_2024():
    assert cen.ORIGENS_DE_BACKTEST == tuple(date(a, 12, 1) for a in range(2020, 2025))


# ---- só a origem nova, id próprio


def test_so_a_origem_nova_tem_linhas(gerado):
    assert {r["origem"] for r in gerado.consumo} == {ORIGEM.isoformat()}
    assert {r["origem"] for r in gerado.pld} == {ORIGEM.isoformat()}
    assert gerado.execucao["origem"] == ORIGEM.isoformat()
    assert len(gerado.consumo) == N * 12
    assert len(gerado.pld) == 2 * N * 12  # simples e blocos
    assert {r["execucao_id"] for r in gerado.consumo + gerado.pld} == {gerado.execucao_id}
    assert gerado.execucao["limites_assumidos"] is True  # 2027 repete os limites de 2026
    assert gerado.execucao["n_cenarios"] == N


def test_os_meses_alvo_sao_os_12_seguintes_a_origem(gerado):
    meses = sorted({r["mes_alvo"] for r in gerado.consumo})
    assert meses[0] == "2026-11-01" and meses[-1] == "2027-10-01" and len(meses) == 12


def test_limites_nao_assumidos_quando_a_tabela_cobre_o_ano_alvo(erros):
    c = cen.gerar_cenarios_da_origem(date(2025, 12, 1), PREVISTO, erros, pld_sintetico(), K, n=N)
    assert c.execucao["limites_assumidos"] is False  # 2026 está na tabela


def test_o_id_da_origem_nunca_e_o_do_caso_base(gerado, erros):
    assert gerado.execucao_id != cen.EXECUCAO_CONGELADA
    outra = cen.gerar_cenarios_da_origem(date(2026, 9, 1), PREVISTO, erros, pld_sintetico(), K, n=N)
    assert outra.execucao_id != cen.EXECUCAO_CONGELADA != gerado.execucao_id
    assert outra.execucao_id != gerado.execucao_id  # cada origem tem o seu


def test_o_id_depende_so_dos_insumos_da_origem(gerado, erros):
    igual = cen.gerar_cenarios_da_origem(ORIGEM, PREVISTO, erros, pld_sintetico(), K, n=N)
    assert igual.execucao_id == gerado.execucao_id
    # um erro com alvo DEPOIS da origem não entra (sem vazamento): mesmo id
    futuro = [*erros, Erro(date(2030, 1, 1), 1, date(2030, 2, 1), 9.9)]
    assert (
        cen.gerar_cenarios_da_origem(ORIGEM, PREVISTO, futuro, pld_sintetico(), K, n=N).execucao_id
        == gerado.execucao_id
    )
    # um erro conhecido que muda: outro id
    mexido = [Erro(e.origem, e.horizonte, e.alvo, e.log_razao + 0.01) for e in erros]
    assert (
        cen.gerar_cenarios_da_origem(ORIGEM, PREVISTO, mexido, pld_sintetico(), K, n=N).execucao_id
        != gerado.execucao_id
    )


def test_idempotencia_mesmos_insumos_mesmas_linhas(gerado, erros):
    de_novo = cen.gerar_cenarios_da_origem(
        ORIGEM, PREVISTO, erros, pld_sintetico(), K, n=N, prov=PROV
    )
    assert de_novo == gerado


def test_a_previsao_precisa_dos_12_horizontes(erros):
    with pytest.raises(ValueError, match="12 previstos"):
        cen.gerar_cenarios_da_origem(ORIGEM, PREVISTO[:11], erros, pld_sintetico(), K, n=N)


# ---- o id do caso base continua intacto


def test_o_id_do_caso_base_nao_mudou():
    assert cen.EXECUCAO_CONGELADA == ot.EXECUCAO_CONGELADA == "51cf99b073fe"
    congelado = json.loads((RAIZ / "ml" / "congelado_6a.json").read_text())
    assert congelado["execucao_id"] == "51cf99b073fe"
    # a conta antiga (várias origens, sem o marcador) segue dando o mesmo valor
    legado = execucao_id(
        2000,
        0,
        K,
        {date(2020, 12, 1): "e1", date(2021, 12, 1): "e2"},
        {"pld": {"2020-12-01": "a", "2021-12-01": "b"}, "pisos": "p"},
    )
    assert legado == "5cd5d8c69a49"


def test_a_conta_de_gerar_nao_foi_tocada():
    fonte = (RAIZ / "ml" / "cenarios.py").read_text()
    # `gerar` continua construindo o id com os extras de sempre (sem o marcador de produção)
    trecho = fonte[fonte.index("def gerar(") : fonte.index("def gerar(") + 1500]
    assert '"producao"' not in trecho


# ---- o comando, com leitura e gravação falsas


def gravada(id_, origem=ORIGEM, erros_=None, **mudar):
    """Uma linha de `fct_cenario_execucao` como `execucoes_da_origem` a devolve, com os insumos
    que o gerador calcularia para a origem (e `mudar` troca algum)."""
    e = cen.gerar_cenarios_da_origem(
        origem, PREVISTO, erros_ or erros_sinteticos(), pld_sintetico(), K, n=N
    ).execucao
    linha = {"execucao_id": id_, **{c: e[c] for c in (*cen.CAMPOS_DOS_INSUMOS, "k_consumo")}}
    linha.update(mudar)
    return linha


def ler_falso(erros, origem=ORIGEM):
    return lambda gcp, cliente: (K, erros, origem, PREVISTO, pld_sintetico())


class Gravador:
    def __init__(self):
        self.chamadas = []

    def __call__(self, gcp, cliente, linhas, tabela, esquema, chave):
        self.chamadas.append((tabela, list(linhas), chave))
        return {
            "tabela": tabela,
            "linhas": len(linhas),
            "s_ddl": 0.0,
            "s_carga": 0.0,
            "s_merge": 0.0,
            "bytes_faturados": 20 * MIB,
        }


def rodar(erros, dry_run=False, existentes=lambda g, c, o: [], origem=ORIGEM, forcar=False, g=None):
    g = g or Gravador()
    rc = cen.gerar_producao(
        dry_run,
        n=N,
        gcp=SimpleNamespace(),
        cliente=None,
        ler=ler_falso(erros, origem),
        existentes=existentes,
        gravar=g,
        prov=PROV,
        forcar=forcar,
    )
    return rc, g


def test_o_comando_grava_tres_tabelas_so_com_a_origem_nova(erros):
    rc, g = rodar(erros)
    assert rc == 0 and [t for t, _, _ in g.chamadas] == [cen.CONSUMO, cen.PLD, cen.EXECUCAO]
    for tabela, linhas, _ in g.chamadas:
        assert {r["origem"] for r in linhas} == {ORIGEM.isoformat()}, tabela
        assert not (
            {r["origem"] for r in linhas} & {o.isoformat() for o in cen.ORIGENS_DE_BACKTEST}
        )
    assert len(g.chamadas[2][1]) == 1  # uma linha de execução


def test_duas_execucoes_gravam_exatamente_o_mesmo(erros):
    _, a = rodar(erros)
    _, b = rodar(erros)
    assert a.chamadas == b.chamadas  # MERGE com a mesma chave natural: nada novo


def test_dry_run_nao_grava_e_rotula_a_estimativa(erros, capsys):
    rc, g = rodar(erros, dry_run=True)
    saida = capsys.readouterr().out
    assert rc == 0 and g.chamadas == []
    assert "nada gravado" in saida and "ESTIMATIVA" in saida and "execucao_id" in saida


def test_o_comando_recusa_origem_de_backtest_antes_de_gravar(erros):
    g = Gravador()
    with pytest.raises(cen.ErroDeOrigem):
        rodar(erros, origem=date(2024, 12, 1), g=g)
    assert g.chamadas == []


def test_origem_ja_na_execucao_congelada_nao_grava_nada(erros, capsys):
    rc, g = rodar(
        erros,
        origem=date(2026, 9, 1),
        existentes=lambda g_, c, o: [gravada(cen.EXECUCAO_CONGELADA, date(2026, 9, 1), erros)],
    )
    assert rc == 0 and g.chamadas == []
    assert "já está na execução congelada" in capsys.readouterr().out


def test_forcar_gera_id_proprio_mesmo_se_a_origem_esta_na_congelada(erros):
    rc, g = rodar(
        erros,
        origem=date(2026, 9, 1),
        existentes=lambda g_, c, o: [gravada(cen.EXECUCAO_CONGELADA, date(2026, 9, 1), erros)],
        forcar=True,
    )
    assert rc == 0 and len(g.chamadas) == 3
    ids = {r["execucao_id"] for _, linhas, _ in g.chamadas for r in linhas}
    assert len(ids) == 1 and cen.EXECUCAO_CONGELADA not in ids


def test_origem_ja_gravada_com_o_mesmo_id_diz_que_e_idempotente(erros, capsys):
    id_ = cen.gerar_cenarios_da_origem(ORIGEM, PREVISTO, erros, pld_sintetico(), K, n=N).execucao_id
    rodar(erros, existentes=lambda g_, c, o: [gravada(id_)])
    assert "já gravada com este id" in capsys.readouterr().out


def test_id_diferente_com_os_mesmos_insumos_nao_diz_que_os_insumos_mudaram(erros, capsys):
    """O caso real da 2026-09: o id de 6 origens difere do de 1 origem só pelo escopo."""
    rodar(erros, existentes=lambda g_, c, o: [gravada("aaaaaaaaaaaa")])
    saida = capsys.readouterr().out
    assert "mesmos insumos" in saida and "só pelo escopo da derivação" in saida
    assert "nenhum insumo mudou" in saida
    assert "DIFERENTES" not in saida and "os insumos mudaram" not in saida


def test_insumo_diferente_e_nomeado_campo_a_campo(erros, capsys):
    rodar(erros, existentes=lambda g_, c, o: [gravada("aaaaaaaaaaaa", pld_hash="outro")])
    saida = capsys.readouterr().out
    assert "insumos DIFERENTES" in saida and "pld_hash" in saida and "conjunto novo" in saida
    assert "erros_hash" not in saida.split("DIFERENTES")[1].split(":")[0]


def test_k_diferente_tambem_e_insumo_que_mudou():
    e = cen.gerar_cenarios_da_origem(
        ORIGEM, PREVISTO, erros_sinteticos(), pld_sintetico(), K, n=N
    ).execucao
    ja = [gravada("bbbbbbbbbbbb", k_consumo=K * 2)]
    texto = cen.descrever_estado(e, ja)
    assert "k_consumo" in texto and "DIFERENTES" in texto


def test_descrever_estado_sem_gravacao_e_com_o_mesmo_id():
    e = cen.gerar_cenarios_da_origem(
        ORIGEM, PREVISTO, erros_sinteticos(), pld_sintetico(), K, n=N
    ).execucao
    assert cen.descrever_estado(e, []) == "ainda não gravada"
    assert "idempotente" in cen.descrever_estado(e, [gravada(e["execucao_id"])])


def test_caso_real_2026_09_a_diferenca_de_id_e_so_de_escopo():
    """Com as impressões REGISTRADAS em ml/congelado_6a.json: o id de 6 origens reproduz o
    51cf99b073fe e o de 1 origem (56f7a38a099c, o que a cadeia calcula) vem dos MESMOS insumos."""
    c = json.loads((RAIZ / "ml" / "congelado_6a.json").read_text())
    org = {date.fromisoformat(o): v for o, v in c["origens"].items()}
    todas = execucao_id(
        c["n_cenarios"],
        c["semente_base"],
        c["k_consumo"],
        {o: v["erros_hash"] for o, v in org.items()},
        {
            "pld": {o.isoformat(): v["pld_hash"] for o, v in org.items()},
            "pisos": org[date(2020, 12, 1)]["pisos_hash"],
        },
    )
    assert todas == cen.EXECUCAO_CONGELADA == "51cf99b073fe"
    f = org[date(2026, 9, 1)]
    um = cen.id_da_origem(
        date(2026, 9, 1),
        c["n_cenarios"],
        c["semente_base"],
        c["k_consumo"],
        f["erros_hash"],
        f["pld_hash"],
        f["pisos_hash"],
    )
    assert um == "56f7a38a099c" != todas
    gerado = {
        "execucao_id": um,
        "k_consumo": c["k_consumo"],
        **{x: f[x] for x in cen.CAMPOS_DOS_INSUMOS},
    }
    registrada = {
        "execucao_id": todas,
        "k_consumo": c["k_consumo"],
        **{x: f[x] for x in cen.CAMPOS_DOS_INSUMOS},
    }
    texto = cen.descrever_estado(gerado, [registrada])
    assert "nenhum insumo mudou" in texto and "6 origens" in texto and "DIFERENTES" not in texto


# ---- a gravação de verdade (MERGE por chave)


def test_gravar_medido_so_faz_merge_sem_apagar_nada(erros):
    sqls, cargas = [], []

    class Gcp:
        def executar_consulta(self, cliente, sql, **kw):
            sqls.append(sql)
            return SimpleNamespace(
                linhas=[], bytes_processados=0, bytes_faturados=20 * MIB, cache=False
            )

    class Cliente:
        def load_table_from_json(self, linhas, temp, job_config=None):
            cargas.append((temp, list(linhas)))
            return SimpleNamespace(result=lambda: None)

        def delete_table(self, nome, not_found_ok=False):
            pass

    gerado = cen.gerar_cenarios_da_origem(
        ORIGEM, PREVISTO, erros, pld_sintetico(), K, n=N, prov=PROV
    )
    cen.gravar_medido(
        Gcp(), Cliente(), [gerado.execucao], cen.EXECUCAO, cen.ESQUEMA_EXECUCAO, cen.CHAVE_EXECUCAO
    )
    merges = [s for s in sqls if s.lstrip().startswith("MERGE")]
    assert len(merges) == 1
    assert "WHEN MATCHED THEN UPDATE" in merges[0] and "WHEN NOT MATCHED THEN INSERT" in merges[0]
    assert "NOT MATCHED BY SOURCE" not in merges[0]  # nada que apague linhas de outras origens
    assert not [s for s in sqls if "DELETE" in s.upper() or "TRUNCATE" in s.upper()]
    assert [len(lin) for _, lin in cargas] == [1] and cargas[0][1][0]["origem"] == "2026-10-01"


def test_a_chave_natural_inclui_o_id_e_a_origem():
    assert "execucao_id" in cen.CHAVE_EXECUCAO and "origem" in cen.CHAVE_EXECUCAO
    assert "execucao_id" in cen.CHAVE_PLD and "execucao_id" in cen.CHAVE_CONSUMO
