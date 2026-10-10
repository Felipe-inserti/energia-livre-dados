"""Snapshot do dashboard (C2): manifesto, cópias, caso base, cobertura, saúde e higiene.

Sem BigQuery e sem Docker: o BigQuery e o banco do orquestrador são falsos; os resultados
versionados (docs/resultados/) são os de verdade."""

import calendar
import csv
import io
import json
import re
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_ml_cenarios import semanal_sintetico

from dashboard import snapshot as snap
from ml import recomendacao as rc
from ml import sensibilidades as sn

RAIZ = Path(__file__).resolve().parents[1]
RESULTADOS = RAIZ / "docs" / "resultados"
AGORA = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
MIB = 1024 * 1024


def meses(inicio: date, fim: date):
    m = inicio
    while m <= fim:
        yield m
        m = date(m.year + (m.month // 12), m.month % 12 + 1, 1)


# ---- BigQuery falso


def rotas(recomendacao_origem=date(2026, 9, 1), cache_carga=False):
    carga = [
        {
            "mes": m,
            "carga_original_mwmed": 40_000.0,
            "carga_ajustada_reconstruida_mwmed": 41_000.0,
            "cobertura": 1.0,
            "mes_utilizavel": True,
        }
        for m in meses(date(2025, 1, 1), date(2026, 9, 1))
    ] + [
        {
            "mes": date(2026, 10, 1),
            "carga_original_mwmed": 1.0,
            "carga_ajustada_reconstruida_mwmed": 1.0,
            "cobertura": 0.4,
            "mes_utilizavel": False,
        }
    ]
    ponderado = [{"mes": m, "pld": 150.0} for m in meses(date(2021, 1, 1), date(2026, 9, 1))]
    consumo = [
        {
            "mes": m,
            "consumo_mwh": 100.0,
            "horas": calendar.monthrange(m.year, m.month)[1] * 24,
        }
        for m in meses(date(2025, 1, 1), date(2026, 9, 1))
    ] + [{"mes": date(2026, 10, 1), "consumo_mwh": 28.8, "horas": 192}]  # outubro incompleto
    previsao = [
        {
            "origem": date(2026, 9, 1),
            "horizonte": h,
            "mes_alvo": date(2026 + (8 + h) // 12, (8 + h) % 12 + 1, 1),
            "previsao_mwmed": 42_000.0,
            "p025_mwmed": 40_000.0,
            "p10_mwmed": 40_500.0,
            "p50_mwmed": 42_000.0,
            "p90_mwmed": 43_500.0,
            "p975_mwmed": 44_000.0,
            "calibracao": "desenvolvimento+teste_final",
            "n_erros_calibracao": 654,
            "serie": "reconstruida",
            "gerado_em": datetime(2026, 10, 8, 3, 0, tzinfo=UTC),
        }
        for h in range(1, 13)
    ]
    recomendacao = []
    for e in ("ingenua", "pontual", "otimizada"):
        linha = dict.fromkeys(rc.COLUNAS)
        linha.update(
            sens_id="caso_base",
            origem=recomendacao_origem,
            estrategia=e,
            tipo="previa",
            v_mwm=0.14,
            preco_contrato_rs_mwh=246.89,
            limites_assumidos=True,
        )
        recomendacao.append(linha)
    # (trecho do SQL, linhas, processados, faturados, cache)
    return [
        ("fct_carga_mensal", carga, 1000, 0 if cache_carga else 10 * MIB, cache_carga),
        ("fct_pld_semanal", semanal_sintetico(), 500, 10 * MIB, False),
        ("fct_pld_ponderado_mensal", ponderado, 100, 10 * MIB, False),
        ("fct_consumo_horario", consumo, 2000, 10 * MIB, False),
        ("fct_erro_previsao_carga", [], 300, 10 * MIB, False),
        ("fct_previsao_carga", previsao, 400, 10 * MIB, False),
        ("fct_recomendacao_contrato", recomendacao, 600, 10 * MIB, False),
    ]


class GcpFalso:
    def __init__(self, rotas_):
        self.rotas = rotas_
        self.sqls = []

    def executar_consulta(self, cliente, sql, **kw):
        self.sqls.append((sql, kw))
        for chave, linhas, proc, fat, cache in self.rotas:
            if chave in sql:
                return SimpleNamespace(
                    linhas=linhas, bytes_processados=proc, bytes_faturados=fat, cache=cache
                )
        raise AssertionError(f"consulta inesperada: {sql[:90]}")


# ---- saúde falsa


def psql_ok(sql: str) -> str:
    if "from dag_run" in sql and "task_instance" not in sql:
        return (
            "run_id,run_type,estado_dag,inicio_utc,duracao_dag_s\n"
            "scheduled__2026-10-10T21:00:00+00:00,scheduled,success,2026-10-10T21:00:03Z,247.0\n"
            "manual__2026-10-08T03:25:54+00:00,manual,failed,2026-10-08T03:25:56Z,60.5\n"
        )
    return (
        "run_id,task_id,estado_task,tentativas,duracao_task_s\n"
        "scheduled__2026-10-10T21:00:00+00:00,ons_ingestao,success,1,19.6\n"
        "scheduled__2026-10-10T21:00:00+00:00,dbt_run,success,1,35.7\n"
        "manual__2026-10-08T03:25:54+00:00,dbt_test,failed,1,12.0\n"
    )


def psql_fora(sql: str) -> str:
    raise RuntimeError('connection to server at "postgres" (172.18.0.2), user airflow, falhou')


def dbt_local(tmp_path: Path) -> tuple[Path, Path]:
    resultados = {
        "metadata": {"generated_at": "2026-10-08T21:12:38Z"},
        "args": {"which": "test", "select": ["source:raw.ons"], "project_dir": "dbt"},
        "elapsed_time": 3.2,
        "results": [
            {"unique_id": "test.a", "status": "pass", "failures": 0},
            {"unique_id": "test.b", "status": "warn", "failures": 3},
            {"unique_id": "test.c", "status": "fail", "failures": 1},
        ],
    }
    manifesto = {
        "nodes": {
            "test.a": {"resource_type": "test", "test_metadata": {"name": "not_null"}},
            "test.b": {"resource_type": "test", "test_metadata": {"name": "not_null"}},
            "test.c": {"resource_type": "test"},
        }
    }
    (tmp_path / "run_results.json").write_text(json.dumps(resultados))
    (tmp_path / "manifest.json").write_text(json.dumps(manifesto))
    return tmp_path / "run_results.json", tmp_path / "manifest.json"


def montar(tmp_path, psql=psql_ok, rotas_=None, dbt=True, **kw):
    rr, mf = dbt_local(tmp_path) if dbt else (tmp_path / "nao_existe.json", tmp_path / "x.json")
    return snap.montar_snapshot(
        GcpFalso(rotas_ or rotas()),
        None,
        RESULTADOS,
        executar_psql=psql,
        run_results=rr,
        dbt_manifest=mf,
        agora=AGORA,
        commit="c" * 40,
        **kw,
    )


@pytest.fixture(scope="module")
def gravado(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("snap")
    s = montar(tmp)
    destino = tmp / "dados"
    snap.gravar(s, destino)
    return s, destino


# ---- manifesto confere com os arquivos


def test_o_manifesto_confere_com_os_arquivos(gravado):
    s, destino = gravado
    manifesto = json.loads((destino / "manifest.json").read_text())
    nomes = {p.name for p in destino.iterdir()}
    assert nomes == {*manifesto["arquivos"], "manifest.json"}
    for nome, info in manifesto["arquivos"].items():
        conteudo = (destino / nome).read_bytes()
        assert info["sha256"] == snap.sha256(conteudo), nome
        assert info["bytes"] == len(conteudo), nome
        assert info["linhas"] == len(conteudo.decode().splitlines()) - 1, nome
        assert info["tipo"] in {"bigquery", "copia", "derivado", "local"}
    assert manifesto["tamanho_total_bytes"] == sum(
        i["bytes"] for i in manifesto["arquivos"].values()
    )


def test_o_conjunto_de_arquivos_e_o_aprovado(gravado):
    _, destino = gravado
    esperado = {
        "carga_mensal_se.csv", "pld_mensal_se.csv", "consumo_exemplo_mensal.csv",
        "previsao_producao.csv", "erros_producao.csv", "recomendacao.csv", "frescor_fontes.csv",
        "backtest_economia.csv", "backtest_anual.csv", "backtest_mensal_caso_base.csv",
        "sens_resumo.csv", "sens_resumo_por_ano.csv", "sens_banda_f.csv", "sens_invariancias.csv",
        "pre_registros.csv", "previsoes_teste_final.csv", "mape_por_ano.csv", "modelos_resumo.csv",
        "cobertura_fora_da_amostra.csv", "saude_execucoes.csv", "saude_testes_dbt.csv",
        "manifest.json",
    }  # fmt: skip
    assert {p.name for p in destino.iterdir()} == esperado


# ---- cópias idênticas à origem


def test_o_hash_de_cada_copia_e_o_da_origem(gravado):
    s, destino = gravado
    manifesto = json.loads((destino / "manifest.json").read_text())
    copias = {n: i for n, i in manifesto["arquivos"].items() if i["tipo"] == "copia"}
    assert set(copias) == set(snap.COPIAS)
    for nome, info in copias.items():
        origem = RESULTADOS / snap.COPIAS[nome]
        assert snap.sha256((destino / nome).read_bytes()) == snap.sha256(origem.read_bytes()), nome
        assert info["fontes"] == [
            {"arquivo": f"docs/resultados/{snap.COPIAS[nome]}", "sha256": info["sha256"]}
        ]


def test_os_derivados_registram_o_hash_de_cada_fonte(gravado):
    _, destino = gravado
    manifesto = json.loads((destino / "manifest.json").read_text())
    for nome in (
        "backtest_economia.csv",
        "backtest_anual.csv",
        "pre_registros.csv",
        "previsoes_teste_final.csv",
    ):
        for f in manifesto["arquivos"][nome]["fontes"]:
            origem = RAIZ / f["arquivo"]
            assert f["sha256"] == snap.sha256(origem.read_bytes()), (nome, f["arquivo"])


# ---- o caso base bate com o backtest


def ler_csv(caminho: Path):
    return list(csv.DictReader(io.StringIO(caminho.read_text(encoding="utf-8"))))


@pytest.mark.parametrize("sufixo", ["economia", "anual"])
def test_o_caso_base_do_snapshot_e_o_do_backtest_texto_por_texto(gravado, sufixo):
    _, destino = gravado
    origem = ler_csv(RESULTADOS / f"backtest_caso_base_{sufixo}.csv")
    no_snapshot = [
        {k: v for k, v in r.items() if k != "sens_id"}
        for r in ler_csv(destino / f"backtest_{sufixo}.csv")
        if r["sens_id"] == "caso_base"
    ]
    assert no_snapshot == origem


def test_o_total_do_caso_base_e_o_do_metricas(gravado):
    _, destino = gravado
    linha = next(
        r
        for r in ler_csv(destino / "backtest_economia.csv")
        if r["sens_id"] == "caso_base" and r["recorte"] == "2021-2025"
    )
    assert float(linha["valor_otimizacao_rs"]) == pytest.approx(9020.19, abs=0.01)
    assert float(linha["valor_previsao_rs"]) == pytest.approx(-330.10, abs=0.01)
    assert float(linha["economia_total_rs"]) == pytest.approx(8690.10, abs=0.01)


def test_as_13_sensibilidades_tambem_batem_com_os_arquivos(gravado):
    _, destino = gravado
    linhas = ler_csv(destino / "backtest_economia.csv")
    assert {r["sens_id"] for r in linhas} == {"caso_base", *sn.IDS}
    for i in sn.IDS:
        origem = ler_csv(RESULTADOS / f"sens_{i}_economia.csv")
        no_snapshot = [r for r in linhas if r["sens_id"] == i]
        assert len(no_snapshot) == len(origem) == 7
        for a, b in zip(no_snapshot, origem, strict=True):
            assert (
                a["recorte"] == b["recorte"] and a["custo_otimizada_rs"] == b["custo_otimizada_rs"]
            )


# ---- cobertura: a fora da amostra


def test_a_cobertura_gravada_e_a_fora_da_amostra(gravado):
    _, destino = gravado
    geral = next(
        r for r in ler_csv(destino / "cobertura_fora_da_amostra.csv") if r["recorte"] == "geral"
    )
    assert (
        round(float(geral["cobertura80_pct"]), 1),
        round(float(geral["cobertura95_pct"]), 1),
    ) == (70.2, 87.8)
    assert geral["n"] == "654"
    # nunca a da calibração de produção (70,8% e 90,5%)
    assert (
        round(float(geral["cobertura80_pct"]), 1),
        round(float(geral["cobertura95_pct"]), 1),
    ) != (70.8, 90.5)


def test_o_manifesto_cita_as_duas_origens_da_calibracao(gravado):
    s, destino = gravado
    m = json.loads((destino / "manifest.json").read_text())
    cal = m["calibracao_dos_intervalos_de_producao"]
    assert "desenvolvimento" in cal["descricao"] and "teste final" in cal["descricao"]
    assert "JÁ VIU o teste final" in cal["descricao"]
    assert cal["valores_no_banco"] == ["desenvolvimento+teste_final"]
    cob = m["cobertura_exibida"]
    assert "FORA DA AMOSTRA" in cob["descricao"] and "só no desenvolvimento" in cob["descricao"]
    assert cob["fonte"].endswith("analise_teste_final_reconstruida_cobertura_por_horizonte.csv")
    assert round(cob["cobertura80_pct"], 1) == 70.2 and round(cob["cobertura95_pct"], 1) == 87.8
    assert (
        cob["nominal_80_pct"] == 80 and cob["nominal_95_pct"] == 95 and "5.6" in cob["referencia"]
    )


def test_a_cobertura_de_producao_e_recusada():
    with pytest.raises(snap.ErroDeSnapshot, match="fora da amostra"):
        snap.conferir_cobertura(
            RESULTADOS / "analise_teste_final_reconstruida_cobertura_pooled.csv"
        )
    assert snap.conferir_cobertura(RESULTADOS / snap.COBERTURA_FONTE)["n"] == 654


def test_arquivo_com_a_cobertura_errada_e_recusado(tmp_path):
    falso = tmp_path / snap.COBERTURA_FONTE
    falso.write_text("recorte,valor,n,cobertura80_pct,cobertura95_pct\ngeral,geral,654,70.8,90.5\n")
    with pytest.raises(snap.ErroDeSnapshot, match="não é a fora da amostra"):
        snap.conferir_cobertura(falso)


# ---- saúde: indisponível sem a fonte


def test_sem_a_fonte_a_saude_fica_indisponivel_e_o_snapshot_sai(tmp_path):
    s = montar(tmp_path, psql=psql_fora, dbt=False)
    destino = tmp_path / "dados"
    snap.gravar(s, destino)
    m = json.loads((destino / "manifest.json").read_text())
    for chave in ("execucoes_da_dag", "testes_dbt"):
        assert m["saude"][chave]["estado"] == "indisponivel"
        assert "indisponível no momento do snapshot" in m["saude"][chave]["motivo"]
    assert (destino / "saude_execucoes.csv").read_text().strip() == ",".join(snap.COLUNAS_EXECUCOES)
    assert (destino / "saude_testes_dbt.csv").read_text().strip() == ",".join(snap.COLUNAS_TESTES)
    # o resto do snapshot não foi afetado
    assert (destino / "carga_mensal_se.csv").exists() and (
        destino / "backtest_economia.csv"
    ).exists()
    # a mensagem do erro (host, usuário) não vai para nenhum arquivo
    todos = "".join(p.read_text() for p in destino.iterdir())
    assert "connection" not in todos and "172.18" not in todos


def test_so_a_fonte_que_falta_fica_indisponivel(tmp_path):
    s = montar(tmp_path, psql=psql_fora)  # o dbt local existe
    assert s.manifesto["saude"]["execucoes_da_dag"]["estado"] == "indisponivel"
    assert s.manifesto["saude"]["testes_dbt"]["estado"] == "disponivel"


def test_com_as_fontes_a_saude_vem_do_banco_e_do_dbt(tmp_path):
    s = montar(tmp_path)
    m = s.manifesto["saude"]
    assert (
        m["execucoes_da_dag"]["estado"] == "disponivel" and m["execucoes_da_dag"]["execucoes"] == 2
    )
    assert m["execucoes_da_dag"]["ultima_execucao_utc"] == "2026-10-10T21:00:03Z"
    t = m["testes_dbt"]
    assert t["comando"] == "test" and t["selecao"] == ["source:raw.ons"] and t["n_resultados"] == 3
    assert t["run_results_gerado_em"] == "2026-10-08T21:12:38Z" and "ÚLTIMO comando" in t["aviso"]
    execucoes = {a.nome: a for a in s.arquivos}["saude_execucoes.csv"].conteudo.decode()
    assert (
        "ons_ingestao" in execucoes and "failed" in execucoes and len(execucoes.splitlines()) == 4
    )
    testes = ler_csv_texto(next(a for a in s.arquivos if a.nome == "saude_testes_dbt.csv").conteudo)
    por_tipo = {r["tipo"]: r for r in testes}
    assert por_tipo["not_null"]["testes"] == "2" and por_tipo["not_null"]["warn"] == "1"
    assert por_tipo["singular"]["error"] == "1" and por_tipo["not_null"]["registros"] == "3"


def ler_csv_texto(conteudo: bytes):
    return list(csv.DictReader(io.StringIO(conteudo.decode())))


# ---- nenhuma credencial nem caminho absoluto

PROIBIDO = [
    r"/home/", r"/mnt/", r"/tmp/", r"/Users/", r"[A-Za-z]:\\",
    r"postgres", r"://", r"password", r"senha", r"passwd", r"private_key", r"GOOGLE_APPLICATION",
    r"secret", r"token", r"api[_-]?key", r"localhost", r"127\.0\.0\.1", r"@", r"energia-livre-\d",
    r"-U airflow", r"\buser\s*=", r"\bhost\s*=",
]  # fmt: skip


@pytest.mark.parametrize("cenario", ["completo", "sem_saude"])
def test_nenhuma_credencial_nem_caminho_absoluto_em_nenhum_arquivo(tmp_path, cenario):
    s = montar(tmp_path) if cenario == "completo" else montar(tmp_path, psql=psql_fora, dbt=False)
    destino = tmp_path / "dados"
    snap.gravar(s, destino)
    proibidos = [re.compile(p, re.IGNORECASE) for p in PROIBIDO]
    nomes = {p.name for p in destino.iterdir()}
    assert {"manifest.json", "saude_execucoes.csv"} <= nomes
    for p in destino.iterdir():
        texto = p.read_text(encoding="utf-8")
        for rx in proibidos:
            achado = rx.search(texto)
            contexto = texto[max(0, achado.start() - 30) : achado.end() + 30] if achado else ""
            assert not achado, f"{p.name}: padrão proibido {rx.pattern!r}: {contexto!r}"
        for local in (str(RAIZ), str(tmp_path), str(Path.home())):
            assert local not in texto, f"{p.name} contém o caminho {local}"


# ---- tamanho


def test_o_snapshot_gerado_cabe_no_limite(gravado):
    s, destino = gravado
    total = sum(p.stat().st_size for p in destino.iterdir())
    assert total < snap.LIMITE_BYTES == 5 * 1024 * 1024
    assert s.manifesto["tamanho_total_bytes"] <= total


def test_passar_do_limite_falha():
    grande = snap.Arquivo("x.csv", b"a,b\n" + b"1,2\n" * (snap.LIMITE_BYTES // 4), "local", ())
    with pytest.raises(snap.ErroDeSnapshot, match="acima do limite"):
        snap.conferir_tamanho([grande])
    assert (
        snap.conferir_tamanho([snap.Arquivo("y.csv", b"a\n1\n", "local", ())]) < snap.LIMITE_BYTES
    )


def test_o_snapshot_versionado_no_repositorio_cabe_no_limite():
    destino = snap.DESTINO
    if not (destino / "manifest.json").exists():
        pytest.skip("dashboard/dados/ ainda não foi gerado")
    assert sum(p.stat().st_size for p in destino.iterdir()) < snap.LIMITE_BYTES


# ---- data e último dado, bytes do job


def test_o_manifesto_registra_a_data_do_snapshot_e_a_do_ultimo_dado(gravado):
    s, destino = gravado
    m = json.loads((destino / "manifest.json").read_text())
    assert m["snapshot_gerado_em"] == "2026-10-11T12:00:00Z" and m["commit"] == "c" * 40
    u = m["ultimo_dado_por_fonte"]
    assert u["carga_mensal"] == "2026-09-01"  # o mês 2026-10 não é utilizável
    assert u["pld_mensal"] == "2026-09-01" and u["consumo_exemplo"] == "2026-09-01"
    assert (
        u["previsao_producao_origem"] == "2026-09-01" and u["recomendacao_origem"] == "2026-09-01"
    )
    assert u["execucao_da_dag_utc"] == "2026-10-10T21:00:03Z"
    assert u["dbt_test_utc"] == "2026-10-08T21:12:38Z"
    assert m["origem_de_producao"] == "2026-09-01" and m["origem_da_previa"] == "2026-09-01"
    assert m["ultimo_mes_fechado"] == "2026-09-01" and m["avisos_de_defasagem"] == []
    frescor = ler_csv(destino / "frescor_fontes.csv")
    assert {r["fonte"]: r["idade_dias_no_snapshot"] for r in frescor}["carga mensal (ONS)"] == str(
        (AGORA.date() - date(2026, 9, 1)).days
    )


def test_os_bytes_faturados_vem_do_job_e_o_cache_nao_fatura(tmp_path):
    s = montar(tmp_path, rotas_=rotas(cache_carga=True))
    por_nome = {c["nome"]: c for c in s.manifesto["consultas"]}
    assert set(por_nome) == {
        "carga_mensal", "pld_semanal", "pld_ponderado", "consumo_exemplo",
        "previsao_producao", "erros_producao", "recomendacao",
    }  # fmt: skip
    assert por_nome["carga_mensal"] == {
        "nome": "carga_mensal",
        "tabela": "marts.fct_carga_mensal",
        "processados": 1000,
        "faturados": 0,
        "cache_hit": True,
    }
    assert (
        por_nome["recomendacao"]["faturados"] == 10 * MIB
        and not por_nome["recomendacao"]["cache_hit"]
    )
    assert s.manifesto["bytes_faturados_total"] == 6 * 10 * MIB
    assert all("sql" not in c for c in s.manifesto["consultas"])


def test_toda_consulta_tem_teto_de_bytes(tmp_path):
    gcp = GcpFalso(rotas())
    rr, mf = dbt_local(tmp_path)
    snap.montar_snapshot(
        gcp, None, RESULTADOS, executar_psql=psql_ok, run_results=rr, dbt_manifest=mf, agora=AGORA
    )
    assert len(gcp.sqls) == 7 and all(
        kw["max_bytes_faturados"] == snap.TETO_BYTES for _, kw in gcp.sqls
    )
    # nenhuma tabela horária grande: o consumo é agregado por mês no próprio SQL
    sql_consumo = next(s for s, _ in gcp.sqls if "fct_consumo_horario" in s)
    assert "GROUP BY mes" in sql_consumo


# ---- pré-registros, defasagem, determinismo


def test_os_pre_registros_sao_os_dos_logs(gravado):
    _, destino = gravado
    m = json.loads((destino / "manifest.json").read_text())
    assert m["pre_registros"]["caso_base"] == "02990fdf26529b59bd0aec5883f7ca7e9e2443d0"
    assert m["pre_registros"]["sensibilidades"] == "4c02987d0270dd91639cdc410d801fe550710af9"
    linhas = ler_csv(destino / "pre_registros.csv")
    assert [r["sens_id"] for r in linhas] == ["caso_base", *sn.IDS]
    assert {r["preregistro"] for r in linhas[1:]} == {m["pre_registros"]["sensibilidades"]}
    assert linhas[0]["execucao_id"] == "51cf99b073fe" and json.loads(linhas[0]["muda"]) == {}
    assert json.loads(linhas[1]["muda"]) == {"f": [0.1, 0.0]}


def test_previa_atras_da_previsao_gera_aviso_de_defasagem(tmp_path):
    s = montar(tmp_path, rotas_=rotas(recomendacao_origem=date(2026, 8, 1)))
    assert s.manifesto["origem_da_previa"] == "2026-08-01"
    assert any(
        "AVISO DE DEFASAGEM" in a and "gerar-producao" in a
        for a in s.manifesto["avisos_de_defasagem"]
    )


def test_determinismo_mesmas_entradas_mesmos_bytes(tmp_path):
    a, b = montar(tmp_path), montar(tmp_path)
    assert [(x.nome, x.conteudo) for x in a.arquivos] == [(x.nome, x.conteudo) for x in b.arquivos]
    assert a.manifesto_bytes() == b.manifesto_bytes()


# ---- dry-run e gravação


def test_dry_run_nao_grava_e_imprime_consultas_linhas_e_bytes(tmp_path, capsys):
    destino = tmp_path / "dados"
    rr, mf = dbt_local(tmp_path)
    rc_ = snap.gerar(
        True, destino, RESULTADOS, GcpFalso(rotas()), None,
        executar_psql=psql_ok, run_results=rr, dbt_manifest=mf, agora=AGORA, commit="c" * 40,
    )  # fmt: skip
    saida = capsys.readouterr().out
    assert rc_ == 0 and not destino.exists()
    for trecho in (
        "CONSULTAS",
        "fct_carga_mensal",
        "ARQUIVOS",
        "linhas",
        "bytes faturados",
        "dry-run: nada gravado",
    ):
        assert trecho in saida
    assert "70.2% e 87.8%" in saida


def test_gerar_grava_e_remove_csv_antigo_que_saiu_do_conjunto(tmp_path):
    destino = tmp_path / "dados"
    destino.mkdir()
    (destino / "velho.csv").write_text("a\n1\n")
    rr, mf = dbt_local(tmp_path)
    snap.gerar(
        False, destino, RESULTADOS, GcpFalso(rotas()), None,
        executar_psql=psql_ok, run_results=rr, dbt_manifest=mf, agora=AGORA, commit="c" * 40,
    )  # fmt: skip
    assert not (destino / "velho.csv").exists() and (destino / "manifest.json").exists()


def test_o_app_nao_importa_o_snapshot_nem_o_bigquery():
    """Só o snapshot fala com a nuvem; o resto de `dashboard/` (o app) não pode."""
    for p in (RAIZ / "dashboard").glob("*.py"):
        if p.name == "snapshot.py":
            continue
        texto = p.read_text()
        assert not re.search(r"^\s*(from|import)\s+(google|ml|ingestion)", texto, re.M), p.name
        assert (
            "snapshot" not in re.sub(r'""".*?"""', "", texto, flags=re.S) or p.name == "__init__.py"
        )


# ---- o mês corrente: carga e curva do consumidor-exemplo


def test_o_consumo_marca_o_ultimo_mes_incompleto(gravado):
    _, destino = gravado
    linhas = ler_csv(destino / "consumo_exemplo_mensal.csv")
    assert list(linhas[0]) == ["mes", "consumo_mwh", "horas", "mes_completo"]
    assert linhas[-1]["mes"] == "2026-10-01" and linhas[-1]["horas"] == "192"
    assert linhas[-1]["mes_completo"] == "False"  # o último mês está incompleto e marcado
    assert all(r["mes_completo"] == "True" for r in linhas[:-1])
    assert [r["mes"] for r in linhas if r["mes_completo"] == "False"] == ["2026-10-01"]


def test_mes_completo_e_horas_iguais_as_esperadas_do_mes():
    import pandas as pd

    q = pd.DataFrame(
        {
            "mes": [date(2024, 2, 1), date(2024, 3, 1), date(2025, 2, 1), date(2025, 3, 1)],
            "consumo_mwh": [1.0, 1.0, 1.0, 1.0],
            "horas": [696, 743, 672, 744],  # fev/2024 (29 dias) e mar/2025 completos
        }
    )
    assert snap.marcar_meses_completos(q)["mes_completo"].tolist() == [True, False, True, True]


def test_a_pagina_pode_filtrar_o_ultimo_dado_so_dos_meses_completos(gravado):
    s, destino = gravado
    m = json.loads((destino / "manifest.json").read_text())
    assert m["ultimo_dado_por_fonte"]["consumo_exemplo"] == "2026-09-01"  # não 2026-10-01
    frescor = {r["fonte"]: r["ultimo_dado"] for r in ler_csv(destino / "frescor_fontes.csv")}
    assert frescor["consumo do consumidor-exemplo"] == "2026-09-01"


def test_a_carga_inclui_o_mes_corrente_marcado_como_nao_utilizavel(gravado):
    _, destino = gravado
    linhas = ler_csv(destino / "carga_mensal_se.csv")
    ultimo = linhas[-1]
    assert ultimo["mes"] == "2026-10-01"  # o mês corrente está no arquivo
    assert ultimo["mes_utilizavel"] == "False" and float(ultimo["cobertura"]) < 0.95
    utilizaveis = [r["mes"] for r in linhas if r["mes_utilizavel"] == "True"]
    assert max(utilizaveis) == "2026-09-01"  # o último mês utilizável é o último fechado


def test_o_manifesto_lista_os_meses_que_nao_sao_dado_fechado(gravado):
    _, destino = gravado
    m = json.loads((destino / "manifest.json").read_text())
    assert m["meses_incompletos"] == {
        "carga_mensal_se.csv": ["2026-10-01"],
        "consumo_exemplo_mensal.csv": ["2026-10-01"],
    }
    assert m["ultimo_mes_fechado"] == "2026-09-01"


# ---- o snapshot que vai ser publicado (dashboard/dados/), conferido como está no repositório


def _snapshot_real():
    if not (snap.DESTINO / "manifest.json").exists():
        pytest.skip("dashboard/dados/ ainda não foi gerado")
    return snap.DESTINO


def test_o_snapshot_versionado_confere_com_o_proprio_manifesto():
    destino = _snapshot_real()
    m = json.loads((destino / "manifest.json").read_text())
    assert {p.name for p in destino.iterdir()} == {*m["arquivos"], "manifest.json"}
    for nome, info in m["arquivos"].items():
        conteudo = (destino / nome).read_bytes()
        assert info["sha256"] == snap.sha256(conteudo) and info["bytes"] == len(conteudo), nome
        assert info["linhas"] == len(conteudo.decode().splitlines()) - 1, nome
    assert m["tamanho_total_bytes"] < snap.LIMITE_BYTES


def test_o_snapshot_versionado_nao_tem_credencial_nem_caminho_absoluto():
    destino = _snapshot_real()
    proibidos = [re.compile(p, re.IGNORECASE) for p in PROIBIDO]
    for p in destino.iterdir():
        texto = p.read_text(encoding="utf-8")
        for rx in proibidos:
            assert not rx.search(texto), f"{p.name}: padrão proibido {rx.pattern!r}"
        for local in (str(RAIZ), str(Path.home())):
            assert local not in texto, f"{p.name} contém o caminho {local}"


def test_o_snapshot_versionado_tem_a_cobertura_fora_da_amostra_e_o_caso_base():
    destino = _snapshot_real()
    cob = json.loads((destino / "manifest.json").read_text())["cobertura_exibida"]
    assert (round(cob["cobertura80_pct"], 1), round(cob["cobertura95_pct"], 1)) == (70.2, 87.8)
    origem = ler_csv(RESULTADOS / "backtest_caso_base_economia.csv")
    no_snapshot = [
        {k: v for k, v in r.items() if k != "sens_id"}
        for r in ler_csv(destino / "backtest_economia.csv")
        if r["sens_id"] == "caso_base"
    ]
    assert no_snapshot == origem
    for nome, info in json.loads((destino / "manifest.json").read_text())["arquivos"].items():
        if info["tipo"] == "copia":
            fonte = RAIZ / info["fontes"][0]["arquivo"]
            assert snap.sha256((destino / nome).read_bytes()) == snap.sha256(fonte.read_bytes())


def test_o_snapshot_versionado_marca_o_mes_incompleto():
    destino = _snapshot_real()
    consumo = ler_csv(destino / "consumo_exemplo_mensal.csv")
    assert "mes_completo" in consumo[0]
    carga = ler_csv(destino / "carga_mensal_se.csv")
    m = json.loads((destino / "manifest.json").read_text())
    for arquivo, linhas in (
        ("carga_mensal_se.csv", carga),
        ("consumo_exemplo_mensal.csv", consumo),
    ):
        campo = "mes_utilizavel" if arquivo.startswith("carga") else "mes_completo"
        incompletos = [
            r["mes"] for r in linhas if r[campo] == "False" and r["mes"] > m["ultimo_mes_fechado"]
        ]
        assert incompletos == m["meses_incompletos"][arquivo], arquivo
