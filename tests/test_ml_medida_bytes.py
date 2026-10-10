"""Medida de bytes: o faturado é o do job (0 no cache); o piso é só estimativa rotulada."""

from types import SimpleNamespace

import pytest

from ml.medida_bytes import PISO_FATURADO, ContaBytes

MIB = 1024 * 1024


class GcpFalso:
    """Devolve, em ordem, os resultados de consulta combinados (como `ResultadoConsulta`)."""

    def __init__(self, *resultados):
        self.resultados = list(resultados)

    def executar_consulta(self, cliente, sql, **kw):
        return self.resultados.pop(0)

    outra_coisa = "passa pelo proxy"


def r(proc, fat, cache):
    return SimpleNamespace(linhas=[], bytes_processados=proc, bytes_faturados=fat, cache=cache)


def test_consulta_do_cache_nao_fatura_o_piso():
    conta = ContaBytes(GcpFalso(r(0, 0, True), r(0, 0, True)))
    conta.executar_consulta(None, "a")
    conta.executar_consulta(None, "b")
    assert conta.faturados == 0 and conta.processados == 0 and conta.do_cache == 2
    assert "0 faturados" in conta.linha() and "2 do cache" in conta.linha()
    assert PISO_FATURADO == 10 * MIB


def test_consulta_executada_soma_o_total_bytes_billed_do_job():
    conta = ContaBytes(GcpFalso(r(768, 10 * MIB, False), r(948_864, 10 * MIB, False)))
    conta.executar_consulta(None, "a")
    conta.executar_consulta(None, "b")
    assert conta.faturados == 20 * MIB and conta.processados == 949_632 and conta.do_cache == 0
    assert "20.971.520 faturados" in conta.linha()


def test_misturado_cache_e_job_so_conta_o_que_o_job_faturou():
    conta = ContaBytes(GcpFalso(r(1190, 10 * MIB, False), r(0, 0, True), r(0, 0, True)))
    for sql in "abc":
        conta.executar_consulta(None, sql)
    assert conta.faturados == 10 * MIB and conta.do_cache == 2
    # a estimativa pelo piso só olha o que não veio do cache, e nunca entra no faturado
    assert conta.estimativa_pelo_piso == 10 * MIB


def test_a_estimativa_so_aparece_quando_pedida_e_rotulada():
    conta = ContaBytes(GcpFalso(r(100, 10 * MIB, False), r(0, 0, True)))
    conta.executar_consulta(None, "a")
    conta.executar_consulta(None, "b")
    assert "ESTIMATIVA" not in conta.linha()
    texto = conta.linha(com_estimativa=True)
    assert "ESTIMATIVA" in texto and "não medida" in texto and "10.485.760" in texto


def test_sem_medida_de_faturamento_nao_inventa_bytes():
    conta = ContaBytes(GcpFalso(r(5 * MIB, None, None)))
    conta.executar_consulta(None, "a", dry_run=True)
    assert conta.faturados == 0 and conta.sem_medida == 1
    assert conta.estimativa_pelo_piso == 10 * MIB  # estimativa; o faturado segue 0
    assert "sem medida de faturamento" in conta.linha()


def test_a_estimativa_usa_os_processados_quando_passam_do_piso():
    conta = ContaBytes(GcpFalso(r(30 * MIB, None, None)))
    conta.executar_consulta(None, "a", dry_run=True)
    assert conta.estimativa_pelo_piso == 30 * MIB


def test_o_proxy_repassa_o_resto_do_modulo():
    conta = ContaBytes(GcpFalso())
    assert conta.outra_coisa == "passa pelo proxy"
    with pytest.raises(AttributeError):
        _ = conta.nao_existe
