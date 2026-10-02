"""Utilitários dos notebooks: consulta com proteção de custo, estilo dos gráficos e figuras.

Toda consulta passa por `consultar`, que usa `ingestion.common.gcp.executar_consulta` (teto de
`maximum_bytes_billed` por consulta) e recusa SQL que leia fora do dataset `marts`: os notebooks
analisam as camadas finais, nunca o raw nem o staging.
"""

import re
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from ingestion.common import gcp
from ingestion.common.config import DATASET_MARTS, carregar_config

RAIZ = Path(__file__).resolve().parent.parent
PASTA_FIGURAS = RAIZ / "docs" / "figuras"
LIMITE_FIGURA_KB = 300  # as figuras vão para o git: mantê-las pequenas

# Paleta categórica de dataviz validada (CVD e contraste; ver docs/decisoes.md). Ordem fixa.
AZUL, LARANJA, VERDE_AGUA = "#2a78d6", "#eb6834", "#1baf7a"
TINTA, TINTA_2, TINTA_3 = "#0b0b0b", "#52514e", "#8a8984"
GRADE, SUPERFICIE = "#e6e5e1", "#fcfcfb"

_CONSULTA_CTE = re.compile(r"\b(\w+)\s+as\s*\(", re.IGNORECASE)
_CONSULTA_TABELA = re.compile(r"\b(?:from|join)\s+([`\w.\-]+)", re.IGNORECASE)


@dataclass
class RegistroConsulta:
    nome: str
    bytes_processados: int
    linhas: int


class Sessao:
    """Cliente do BigQuery mais o registro do que cada consulta processou."""

    def __init__(self):
        self.config = carregar_config()
        self.cliente = gcp.cliente_bigquery(self.config)
        self.registros: list[RegistroConsulta] = []

    def tabela(self, nome: str) -> str:
        """Identificador completo de uma tabela do mart (para montar o SQL)."""
        return f"`{self.config.tabela(DATASET_MARTS, nome)}`"

    def consultar(self, nome: str, sql: str) -> pd.DataFrame:
        """Roda a consulta com o teto de custo e devolve um DataFrame.

        Levanta ValueError se o SQL ler alguma tabela fora do dataset `marts`; o teto de bytes
        (200 MiB por padrão) faz o BigQuery recusar a consulta que o ultrapassaria.
        """
        fora = tabelas_fora_dos_marts(sql)
        if fora:
            raise ValueError(f"{nome}: o notebook só lê dos marts, mas a consulta lê {fora}")
        # sem cache: uma consulta atendida pelo cache reporta 0 bytes e esconderia o custo real
        resultado = gcp.executar_consulta(self.cliente, sql, usar_cache=False)
        df = pd.DataFrame([dict(linha) for linha in resultado.linhas])
        self.registros.append(RegistroConsulta(nome, resultado.bytes_processados or 0, len(df)))
        return df

    def resumo_de_custo(self) -> pd.DataFrame:
        tabela = pd.DataFrame([vars(r) for r in self.registros])
        tabela["MB processados"] = (tabela.pop("bytes_processados") / 1e6).round(1)
        total = pd.DataFrame(
            [
                {
                    "nome": "total",
                    "linhas": tabela["linhas"].sum(),
                    "MB processados": tabela["MB processados"].sum().round(1),
                }
            ]
        )
        return pd.concat([tabela, total], ignore_index=True)


def tabelas_fora_dos_marts(sql: str) -> list[str]:
    """Tabelas citadas em FROM/JOIN que não são do dataset marts nem CTEs da própria consulta."""
    ctes = {c.lower() for c in _CONSULTA_CTE.findall(sql)}
    fora = []
    for ref in _CONSULTA_TABELA.findall(sql):
        limpo = ref.strip("`")
        if limpo.lower() in ctes or limpo.lower().startswith("unnest"):
            continue
        if f".{DATASET_MARTS}." not in limpo:
            fora.append(limpo)
    return fora


def aplicar_estilo() -> None:
    """Estilo único dos gráficos: grade só horizontal e discreta, sem moldura, tinta em 3 níveis."""
    plt.rcParams.update(
        {
            "figure.facecolor": SUPERFICIE,
            "axes.facecolor": SUPERFICIE,
            "savefig.facecolor": SUPERFICIE,
            "font.size": 10,
            "text.color": TINTA,
            "axes.labelcolor": TINTA_2,
            "axes.edgecolor": GRADE,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "axes.grid.axis": "y",
            "grid.color": GRADE,
            "grid.linewidth": 0.8,
            "axes.axisbelow": True,
            "xtick.color": TINTA_2,
            "ytick.color": TINTA_2,
            "axes.titlesize": 12,
            "axes.titleweight": "bold",
            "axes.titlelocation": "left",
            "legend.frameon": False,
            "lines.linewidth": 1.8,
        }
    )


def salvar_figura(fig: plt.Figure, nome: str) -> Path:
    """Salva em docs/figuras/<nome>.png (130 dpi) e confere o tamanho."""
    PASTA_FIGURAS.mkdir(parents=True, exist_ok=True)
    caminho = PASTA_FIGURAS / f"{nome}.png"
    fig.savefig(caminho, dpi=130, bbox_inches="tight")
    kb = caminho.stat().st_size / 1024
    if kb > LIMITE_FIGURA_KB:
        raise ValueError(f"{caminho.name} tem {kb:.0f} KB (limite {LIMITE_FIGURA_KB} KB)")
    print(f"salvo: {caminho.relative_to(RAIZ)} ({kb:.0f} KB)")
    return caminho
