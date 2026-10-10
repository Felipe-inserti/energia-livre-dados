"""Previsão em produção: proveniência, linhas, SQL e o que a imagem do Airflow precisa."""

import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

from ml import previsao as p
from ml.intervalos import calibrar
from ml.registro import MODELO_VERSAO, parametros_do_modelo
from ml.validacao import HORIZONTES, meses_entre, somar_meses

RAIZ = Path(__file__).resolve().parents[1]


def git(*args):
    return subprocess.run(["git", *args], cwd=RAIZ, capture_output=True, text=True).stdout.strip()


@pytest.mark.skipif(not git("rev-parse", "HEAD"), reason="sem git")
def test_hash_e_commit_sem_o_binario_do_git_batem_com_o_git():
    assert p.hash_blob_git(RAIZ / "ml" / "validacao.py") == git("hash-object", "ml/validacao.py")
    assert p.ler_commit(RAIZ) == git("rev-parse", "HEAD")
    assert p.ler_commit(RAIZ / "nao_existe") == "desconhecido"


def test_proveniencia_tem_o_que_a_tabela_exige():
    prov = p.proveniencia(agora=datetime(2026, 10, 8, 12, 0))
    assert prov["modelo_versao"] == MODELO_VERSAO
    assert prov["gerado_em"] == "2026-10-08T12:00:00Z"
    assert len(prov["parametros_hash"]) == len(prov["codigo_hash"]) == 12
    # os parâmetros definem o hash: mudar um muda o hash
    alterado = {**parametros_do_modelo(), "janela_meses": 120}
    assert p.hash_curto(alterado) != prov["parametros_hash"]
    assert p.hash_curto(parametros_do_modelo()) == prov["parametros_hash"]


def previsoes_ok(origem=date(2026, 9, 1)):
    prev = {h: 40000.0 + 100 * h for h in HORIZONTES}
    erros = p.como_erros(p.erros_de_backtest())
    return origem, prev, calibrar(erros, modo="producao"), len(erros)


def serie_de_entrada():
    return {
        m: 40000.0 + 10 * i for i, m in enumerate(meses_entre(date(2015, 1, 1), date(2026, 9, 1)))
    }


def linhas_ok():
    origem, prev, q, n = previsoes_ok()
    entrada = p.impressao_da_entrada(serie_de_entrada())
    return p.linhas_previsao(origem, prev, q, p.proveniencia(), date(2026, 9, 1), n, "x", entrada)


def test_linhas_de_previsao_tem_12_horizontes_e_quantis_ordenados():
    linhas = linhas_ok()
    p.validar_linhas(linhas)
    assert [x["horizonte"] for x in linhas] == list(HORIZONTES)
    assert linhas[0]["mes_alvo"] == "2026-10-01" and linhas[-1]["mes_alvo"] == "2027-09-01"
    assert {x["tipo"] for x in linhas} == {"producao"}
    assert {n for n, _ in p.ESQUEMA_PREVISAO} == set(linhas[0])


@pytest.mark.parametrize(
    "estrago",
    [
        lambda ls: ls.pop(),  # 11 horizontes
        lambda ls: ls[3].update(previsao_mwmed=-1.0),
        lambda ls: ls[3].update(p10_mwmed=ls[3]["p975_mwmed"] + 1),  # quantis fora de ordem
        lambda ls: ls[5].update(mes_alvo="2030-01-01"),
        lambda ls: ls[0].update(p025_mwmed=None),
    ],
)
def test_validacao_barra_previsao_sem_sentido(estrago):
    linhas = linhas_ok()
    estrago(linhas)
    with pytest.raises(ValueError):
        p.validar_linhas(linhas)


def test_o_backtest_vem_dos_arquivos_com_chave_unica():
    linhas = p.erros_de_backtest()
    chaves = [(x["modelo_versao"], x["periodo"], x["origem"], x["horizonte"]) for x in linhas]
    assert len(chaves) == len(set(chaves)) == 1152 + 654
    assert {x["periodo"] for x in linhas} == {"desenvolvimento", "teste_final"}
    assert {n for n, _ in p.ESQUEMA_ERROS} == set(linhas[0])
    um = linhas[0]
    assert um["erro_mwmed"] == pytest.approx(um["previsto_mwmed"] - um["real_mwmed"])
    assert date.fromisoformat(um["ultimo_mes_alvo_da_origem"]) == somar_meses(
        date.fromisoformat(um["origem"]), 12
    )


def test_merge_usa_a_chave_natural_e_todas_as_colunas():
    sql = p.merge(p.PREVISAO, p.TEMP_PREVISAO, p.ESQUEMA_PREVISAO, p.CHAVE_PREVISAO)
    for c in p.CHAVE_PREVISAO:
        assert f"T.`{c}` = S.`{c}`" in sql
    assert "UPDATE SET" in sql and "INSERT" in sql
    atualizadas = sql.split("UPDATE SET")[1].split("WHEN NOT MATCHED")[0]
    assert "T.`modelo_versao`" not in atualizadas  # a chave não é atualizada
    assert "T.`previsao_mwmed` = S.`previsao_mwmed`" in atualizadas
    assert all(f"`{n}`" in sql for n, _ in p.ESQUEMA_PREVISAO)
    assert p.ddl(p.ERROS, p.ESQUEMA_ERROS, p.CHAVE_ERROS).startswith("CREATE TABLE IF NOT EXISTS")


def test_ultima_origem_exige_mes_completo():
    serie = [(m, 40000.0, 1.0) for m in meses_entre(date(2026, 1, 1), date(2026, 7, 1))]
    serie += [(date(2026, 8, 1), 40000.0, 0.967)]  # 1 dia faltando: passa em 95%, não em 100%
    assert p.ultima_origem_completa(serie) == date(2026, 7, 1)
    with pytest.raises(RuntimeError):
        p.ultima_origem_completa([(date(2026, 8, 1), 1.0, 0.9)])


def test_a_previsao_roda_sem_lightgbm_como_na_imagem_do_airflow():
    """A imagem só instala o grupo `ml`: o caminho de produção não pode importar o lightgbm."""
    codigo = """
import sys
sys.modules['lightgbm'] = None   # qualquer import do lightgbm falha
from datetime import date
from ml.previsao import SQL_SERIE
from ml.registro import previsor_do_vencedor
from ml.validacao import meses_entre
serie = {m: 40000 * (1 + 0.05 * ((m.month % 12) / 12)) * 1.002 ** i
         for i, m in enumerate(meses_entre(date(2015, 1, 1), date(2021, 6, 1)))}
prev = previsor_do_vencedor()(serie, date(2021, 6, 1), list(range(1, 13)))
assert len(prev) == 12 and all(v > 0 for v in prev.values())
print('ok')
"""
    r = subprocess.run([sys.executable, "-c", codigo], cwd=RAIZ, capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.strip() == "ok", r.stderr[-800:]


def test_dockerfile_instala_ml_mas_nao_ml_exploracao_nem_dev():
    docker = (RAIZ / "airflow" / "Dockerfile").read_text()
    assert "--no-default-groups --group dbt --group ml " in docker
    assert "ml-exploracao" not in docker.split("RUN cd /tmp/projeto")[1]
    import tomllib

    grupos = tomllib.loads((RAIZ / "pyproject.toml").read_text())["dependency-groups"]
    # Conjunto EXATO. O pyarrow entrou de propósito na Sprint 6, Parte A: ml/otimizacao.py grava
    # e lê o parquet da leitura congelada dos cenários (dependência direta, não só transitiva).
    esperado = {"statsmodels", "scikit-learn", "pyarrow"}
    assert {d.split(">")[0] for d in grupos["ml"]} == esperado
    assert [d.split(">")[0] for d in grupos["ml-exploracao"]] == ["lightgbm"]


class ClienteFalso:
    def __init__(self):
        self.eventos = []

    def load_table_from_json(self, linhas, destino, job_config=None):
        self.eventos.append(("carga", destino, len(linhas)))
        return type("Job", (), {"result": lambda self: None})()

    def delete_table(self, tabela, not_found_ok=False):
        self.eventos.append(("apaga", tabela))


def test_gravar_carrega_na_temporaria_faz_o_merge_e_apaga_a_temporaria(monkeypatch):
    cliente = ClienteFalso()
    monkeypatch.setattr(p, "_consulta", lambda gcp, c, sql: cliente.eventos.append(("sql", sql)))
    linhas = linhas_ok()
    p._gravar(
        None, cliente, linhas, p.TEMP_PREVISAO, p.PREVISAO, p.ESQUEMA_PREVISAO, p.CHAVE_PREVISAO
    )
    tipos = [e[0] for e in cliente.eventos]
    assert tipos == ["carga", "sql", "apaga"]
    assert cliente.eventos[0][1:] == (p.TEMP_PREVISAO, 12)
    assert cliente.eventos[1][1].startswith(f"MERGE `{p.PREVISAO}`")


def test_gravar_apaga_a_temporaria_mesmo_se_o_merge_falhar(monkeypatch):
    cliente = ClienteFalso()

    def falha(gcp, c, sql):
        raise RuntimeError("merge falhou")

    monkeypatch.setattr(p, "_consulta", falha)
    with pytest.raises(RuntimeError):
        p._gravar(None, cliente, linhas_ok(), p.TEMP_ERROS, p.ERROS, p.ESQUEMA_ERROS, p.CHAVE_ERROS)
    assert ("apaga", p.TEMP_ERROS) in cliente.eventos


# ---------------------------------------------------------------- impressão digital da entrada


def test_impressao_da_entrada_e_estavel_e_sensivel():
    serie = serie_de_entrada()
    a = p.impressao_da_entrada(serie)
    assert a == p.impressao_da_entrada(dict(serie))  # determinística
    assert a["entrada_meses"] == 141 and len(a["entrada_hash"]) == 12
    ultimo = max(serie)
    assert a["entrada_ultimo_mwmed"] == serie[ultimo]
    assert a["entrada_janela_soma_mwmed"] < a["entrada_soma_mwmed"]  # a janela é um pedaço da série
    # um kW a mais em UM mês muda o hash e as somas; ruído de 1e-10 (abaixo da resolução) não muda
    mexida = {**serie, date(2020, 5, 1): serie[date(2020, 5, 1)] + 0.001}
    assert p.impressao_da_entrada(mexida)["entrada_hash"] != a["entrada_hash"]
    ruido = {m: v + 1e-10 for m, v in serie.items()}
    assert p.impressao_da_entrada(ruido) == a


def test_a_impressao_vai_em_todas_as_linhas_e_a_validacao_a_exige():
    linhas = linhas_ok()
    assert {n for n, _ in p.ESQUEMA_PREVISAO} == set(linhas[0])
    assert len({x["entrada_hash"] for x in linhas}) == 1
    linhas[4]["entrada_hash"] = None
    with pytest.raises(ValueError, match="impressão digital"):
        p.validar_linhas(linhas)


def test_colunas_novas_e_um_alter_idempotente_so_com_as_colunas_do_esquema():
    sql = p.colunas_novas(p.PREVISAO, p.ESQUEMA_PREVISAO)
    assert sql.startswith(f"ALTER TABLE `{p.PREVISAO}`")
    assert sql.count("ADD COLUMN IF NOT EXISTS") == len(p.ESQUEMA_PREVISAO)
    assert "`entrada_hash` STRING" in sql and "`entrada_ultimo_mwmed` FLOAT64" in sql


def test_a_leitura_da_serie_arredonda_a_1_kw_sem_mexer_no_que_ja_esta_arredondado():
    from ml.registro import arredondar_serie

    bruta = {date(2026, 9, 1): 44516.808041666667, date(2026, 8, 1): 43681.658}
    r = arredondar_serie(bruta)
    assert r == {date(2026, 9, 1): 44516.808, date(2026, 8, 1): 43681.658}
    assert arredondar_serie(r) == r  # idempotente: o mart já arredondado passa intacto
    # o ruído de 1e-10 do AVG paralelo desaparece
    assert arredondar_serie({date(2026, 9, 1): 44516.808 + 1e-10}) == {date(2026, 9, 1): 44516.808}


def test_o_ruido_de_ultimo_digito_nao_muda_a_previsao_depois_do_arredondamento():
    """O caso real: a série diferia ~1e-10 entre builds do mart e o SARIMA mudava a previsão."""
    from ml.registro import arredondar_serie, previsor_do_vencedor

    base = {
        m: 40000.0 * (1 + 0.05 * (m.month % 12) / 12) * 1.002**i
        for i, m in enumerate(meses_entre(date(2015, 1, 1), date(2021, 6, 1)))
    }
    base = arredondar_serie(base)
    ruidosa = {m: v + (1e-10 if m.month % 2 else -1e-10) for m, v in base.items()}
    origem = date(2021, 6, 1)
    prev = previsor_do_vencedor()
    a = prev(arredondar_serie(base), origem, list(HORIZONTES))
    b = prev(arredondar_serie(ruidosa), origem, list(HORIZONTES))
    assert a == b


# ---------------------------------------------------------------- comparação de impressões

from scripts import comparar_impressoes as ci  # noqa: E402

BASE = (
    "previsao n=12 soma=539214.3 origem=2026-09-01 entrada_hash=abc123 entrada_ultimo=44516.808 "
    "| erros n=1806 soma=1.060693645"
)


def test_mesma_entrada_exige_saida_identica():
    ok, linhas = ci.comparar(ci.ler(BASE), ci.ler(BASE))
    assert ok and "PASS" in linhas[-1]
    outra_saida = BASE.replace("soma=539214.3", "soma=539224.3")
    ok, linhas = ci.comparar(ci.ler(BASE), ci.ler(outra_saida))
    assert not ok and "FAIL" in linhas[-1] and any("previsao_soma" in x for x in linhas)


def test_entrada_diferente_mostra_as_diferencas_e_passa():
    depois = BASE.replace("soma=539214.3", "soma=539224.3").replace("abc123", "def456")
    ok, linhas = ci.comparar(ci.ler(BASE), ci.ler(depois))
    texto = "\n".join(linhas)
    assert ok and "abc123 -> def456" in texto and "+10.0 MWmed" in texto and "(mudou)" in texto


def test_linha_gravada_antes_da_impressao_conta_como_entrada_desconhecida():
    antiga = BASE.replace("entrada_hash=abc123", "entrada_hash=None")
    ok, linhas = ci.comparar(ci.ler(antiga), ci.ler(antiga))  # None == None não é "mesma entrada"
    assert ok and "DIFERENTE ou desconhecida" in linhas[0]


def test_o_modo_local_e_o_dag_usam_o_comparador():
    texto = (RAIZ / "scripts" / "passo_sprint5_c.sh").read_text()
    assert texto.count("scripts.comparar_impressoes") == 3  # local, dag e dag-gerar
    assert "diff <(sed" not in texto
