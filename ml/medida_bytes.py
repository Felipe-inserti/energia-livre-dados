"""Medida de bytes das consultas ao BigQuery: o que o JOB reporta; a estimativa, só como estimativa.

Uma consulta atendida pelo cache (`cache_hit`) reporta 0 bytes processados e **0 faturados**. Somar
o piso de 10 MiB nesse caso (o que uma versão anterior fazia quando `total_bytes_billed` vinha 0)
inventa um custo que não existiu. Aqui:
- consulta executada: `faturados` = `total_bytes_billed` do job (0 no cache), com `cache_hit`;
- consulta de estimativa (`dry_run=True` do BigQuery, sem job faturado): o faturamento é
  desconhecido, e só então se calcula a estimativa pelo piso (10 MiB por tabela referenciada),
  rotulada como estimativa e nunca somada às medidas.
"""

from dataclasses import dataclass

PISO_FATURADO = 10 * 1024 * 1024  # mínimo cobrado por tabela referenciada


@dataclass(frozen=True)
class Medida:
    processados: int
    faturados: int | None  # total_bytes_billed do job; None quando não houve job faturado
    cache: bool | None
    estimativa: int  # piso de 10 MiB (ou os processados, se maiores): só serve de estimativa
    sql: str = ""  # o texto da consulta (para o dry-run imprimir; nunca vai para arquivo)


class ContaBytes:
    """Envolve o módulo `gcp` e guarda a medida de cada consulta, sem inventar bytes faturados."""

    def __init__(self, gcp):
        self._gcp = gcp
        self.medidas: list[Medida] = []

    def executar_consulta(self, cliente, sql, **kw):
        r = self._gcp.executar_consulta(cliente, sql, **kw)
        proc = r.bytes_processados or 0
        self.medidas.append(
            Medida(
                proc,
                r.bytes_faturados,
                getattr(r, "cache", None),
                max(proc, PISO_FATURADO),
                sql if isinstance(sql, str) else "",
            )
        )
        return r

    def __getattr__(self, nome):
        return getattr(self._gcp, nome)

    @property
    def processados(self) -> int:
        return sum(m.processados for m in self.medidas)

    @property
    def faturados(self) -> int:
        """Soma do que os jobs faturaram (0 no cache). Ignora o que não foi medido."""
        return sum(m.faturados or 0 for m in self.medidas)

    @property
    def do_cache(self) -> int:
        return sum(1 for m in self.medidas if m.cache)

    @property
    def sem_medida(self) -> int:
        """Consultas em que o job não reportou `total_bytes_billed` (só estimativa possível)."""
        return sum(1 for m in self.medidas if m.faturados is None)

    @property
    def estimativa_pelo_piso(self) -> int:
        """Estimativa (NÃO medida): o piso de 10 MiB por consulta que não veio do cache."""
        return sum(m.estimativa for m in self.medidas if not m.cache)

    def linha(self, com_estimativa: bool = False) -> str:
        """Texto para o log: medido pelo job; a estimativa pelo piso só quando pedida."""
        n = len(self.medidas)
        texto = (
            f"{n} consultas ({self.do_cache} do cache), {self.processados:,} bytes processados, "
            f"{self.faturados:,} faturados (total_bytes_billed dos jobs; "
            f"{self.faturados / 1024**2:.1f} MiB)"
        )
        if self.sem_medida:
            texto += f"; {self.sem_medida} sem medida de faturamento"
        if com_estimativa:
            est = self.estimativa_pelo_piso
            texto += (
                f"; ESTIMATIVA pelo piso de 10 MiB por consulta fora do cache: {est:,} "
                f"({est / 1024**2:.1f} MiB), não medida"
            )
        return texto.replace(",", ".")
