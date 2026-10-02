"""Desenha o lineage (DAG) do projeto dbt a partir do manifesto e salva em docs/figuras/.

Lê `dbt/target/manifest.json` (gerado por `dbt parse` ou `dbt docs generate`; não consulta o
BigQuery). As arestas são as dependências de código (`ref` e `source`); os `relationships` dos
testes não entram, senão toda tabela ligaria à `dim_tempo` e o desenho viraria um emaranhado.

    uv run --env-file .env dbt parse --project-dir dbt --profiles-dir dbt
    uv run python scripts/gerar_lineage.py
"""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # sem janela: só gera arquivo
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, PathPatch  # noqa: E402
from matplotlib.path import Path as CaminhoBezier  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
MANIFESTO = RAIZ / "dbt" / "target" / "manifest.json"
SAIDA = RAIZ / "docs" / "figuras"

# Cores por tipo de nó (escolhidas para se distinguirem também em tons de cinza)
CORES = {
    "fonte": ("#E8E8E8", "#555555", "Fonte (raw)"),
    "staging": ("#C6DBEF", "#2171B5", "Staging"),
    "dimensao": ("#C7E9C0", "#238B45", "Dimensão (mart)"),
    "intermediario": ("#FDD0A2", "#D94801", "Intermediário"),
    "fato": ("#DADAEB", "#6A51A3", "Fato (mart)"),
}


def tipo_do_no(unique_id: str, no: dict) -> str:
    if unique_id.startswith("source."):
        return "fonte"
    nome = no["name"]
    for prefixo, tipo in (
        ("stg_", "staging"),
        ("int_", "intermediario"),
        ("dim_", "dimensao"),
        ("fct_", "fato"),
    ):
        if nome.startswith(prefixo):
            return tipo
    raise ValueError(f"modelo fora da convenção de nomes: {nome}")


def ler_grafo(manifesto: dict) -> tuple[dict[str, str], dict[str, str], list[tuple[str, str]]]:
    """Devolve (nome por id, tipo por id, arestas pai -> filho) de modelos e fontes."""
    nos = {
        uid: n
        for uid, n in {**manifesto["nodes"], **manifesto["sources"]}.items()
        if uid.startswith("source.") or (uid.startswith("model.") and n["resource_type"] == "model")
    }
    nomes = {uid: n["name"] for uid, n in nos.items()}
    tipos = {uid: tipo_do_no(uid, n) for uid, n in nos.items()}
    arestas = [
        (pai, uid)
        for uid, n in nos.items()
        if uid.startswith("model.")
        for pai in n["depends_on"]["nodes"]
        if pai in nos
    ]
    return nomes, tipos, arestas


# Coluna de cada tipo: a camada decide a coluna, nunca o caminho no grafo
COLUNA = {"fonte": 0, "staging": 1, "dimensao": 2, "intermediario": 3, "fato": 4}
TITULOS = ["Fontes (raw)", "Staging", "Dimensões", "Intermediários", "Fatos"]


def _cruzam(a: tuple, b: tuple) -> bool:
    """Os segmentos a e b, cada um ((x0, y0), (x1, y1)), se cruzam em pontos internos?"""

    def lado(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    (p1, p2), (p3, p4) = a, b
    if {p1, p2} & {p3, p4}:  # compartilham uma ponta: não conta
        return False
    return lado(p1, p2, p3) * lado(p1, p2, p4) < 0 and lado(p3, p4, p1) * lado(p3, p4, p2) < 0


def _cruzamentos(ordem: list[list[str]], arestas: list[tuple[str, str]]) -> int:
    """Cruzamentos entre as arestas desenhadas como retas entre os centros das caixas."""
    ponto = {u: (c, i) for c, nos in enumerate(ordem) for i, u in enumerate(nos)}
    segmentos = [(ponto[pai], ponto[filho]) for pai, filho in arestas]
    return sum(
        _cruzam(segmentos[i], segmentos[j])
        for i in range(len(segmentos))
        for j in range(i + 1, len(segmentos))
    )


def posicoes(
    nomes: dict[str, str], tipos: dict[str, str], arestas: list[tuple[str, str]]
) -> dict[str, tuple[int, float]]:
    """(coluna, linha) de cada nó. A coluna vem do tipo; a ordem das linhas vem de uma busca
    com sorteios (semente fixa) e trocas de pares que só aceita trocas que reduzem os
    cruzamentos. Cada coluna fica centrada na vertical."""
    import random

    ids = sorted(nomes, key=lambda u: nomes[u])
    colunas = [[u for u in ids if COLUNA[tipos[u]] == c] for c in range(len(COLUNA))]
    sorteio = random.Random(0)
    melhor, melhor_custo = colunas, _cruzamentos(colunas, arestas)
    for _ in range(300):
        ordem = [sorteio.sample(nos, len(nos)) for nos in colunas]
        custo = _cruzamentos(ordem, arestas)
        melhorou = True
        while melhorou and custo:
            melhorou = False
            for nos in ordem:
                for i in range(len(nos)):
                    for j in range(i + 1, len(nos)):
                        nos[i], nos[j] = nos[j], nos[i]
                        novo = _cruzamentos(ordem, arestas)
                        if novo < custo:
                            custo, melhorou = novo, True
                        else:
                            nos[i], nos[j] = nos[j], nos[i]
        if custo < melhor_custo:
            melhor, melhor_custo = [list(n) for n in ordem], custo
    maior = max(len(nos) for nos in melhor)
    return {
        u: (c, i + (maior - len(nos)) / 2)
        for c, nos in enumerate(melhor)
        for i, u in enumerate(nos)
    }


LARGURA, ALTURA, PASSO_X, PASSO_Y = 2.3, 0.52, 3.6, 0.78


def _rota(origem, destino, coluna_o, coluna_d, xy_por_coluna, ocupados):
    """Caminho (vértices e códigos do Path) de uma seta. Setas que atravessam colunas passam pelos
    vãos entre as caixas (uma faixa horizontal em cada coluna do meio), nunca por trás delas."""
    (x0, y0), (x1, y1) = origem, destino
    cod, pts = [CaminhoBezier.MOVETO], [(x0 + LARGURA / 2, y0)]
    if coluna_o == coluna_d:  # mesma coluna: arco que sai e volta pelo lado direito
        xr = x0 + LARGURA / 2
        arco = 0.55
        return [CaminhoBezier.MOVETO] + [CaminhoBezier.CURVE4] * 3, [
            (xr, y0),
            (xr + arco, y0),
            (xr + arco, y1),
            (xr, y1),
        ]
    ponto_atual = pts[0]
    for c in range(coluna_o + 1, coluna_d):
        xc = c * PASSO_X
        ys = sorted(y for _, y in xy_por_coluna[c])
        vaos = [ys[0] + PASSO_Y / 2] + [(a + b) / 2 for a, b in zip(ys, ys[1:], strict=False)]
        vaos += [ys[-1] - PASSO_Y / 2]
        alvo = y0 + (y1 - y0) * (xc - x0) / (x1 - x0)
        vao = min(vaos, key=lambda g: abs(g - alvo))
        k = ocupados.setdefault((c, round(vao, 3)), 0)
        ocupados[(c, round(vao, 3))] = k + 1
        y = vao + 0.06 * ((k + 1) // 2) * (1 if k % 2 else -1)  # faixas lado a lado no vão
        entrada, saida = xc - LARGURA / 2 - 0.15, xc + LARGURA / 2 + 0.15
        dx = entrada - ponto_atual[0]
        cod += [CaminhoBezier.CURVE4] * 3 + [CaminhoBezier.LINETO]
        pts += [(ponto_atual[0] + dx / 2, ponto_atual[1]), (entrada - dx / 2, y), (entrada, y)]
        pts += [(saida, y)]
        ponto_atual = (saida, y)
    dx = (x1 - LARGURA / 2) - ponto_atual[0]
    cod += [CaminhoBezier.CURVE4] * 3
    pts += [
        (ponto_atual[0] + dx / 2, ponto_atual[1]),
        (x1 - LARGURA / 2 - dx / 2, y1),
        (x1 - LARGURA / 2, y1),
    ]
    return cod, pts


def desenhar(manifesto: dict) -> plt.Figure:
    nomes, tipos, arestas = ler_grafo(manifesto)
    pos = posicoes(nomes, tipos, arestas)
    ncol = len(COLUNA)
    nlin = max(r for _, r in pos.values()) + 1

    fig, ax = plt.subplots(figsize=(PASSO_X * ncol + 0.6, PASSO_Y * nlin + 1.9), dpi=150)
    xy = {u: (c * PASSO_X, -r * PASSO_Y) for u, (c, r) in pos.items()}
    por_coluna = {c: [xy[u] for u in xy if pos[u][0] == c] for c in range(ncol)}

    ocupados: dict = {}
    for pai, filho in sorted(arestas, key=lambda a: (pos[a[0]][0], pos[a[1]][0])):
        cod, pts = _rota(xy[pai], xy[filho], pos[pai][0], pos[filho][0], por_coluna, ocupados)
        ax.add_patch(
            PathPatch(
                CaminhoBezier(pts, cod),
                facecolor="none",
                edgecolor="#888888",
                linewidth=0.9,
                zorder=1,
            )
        )
        xf, yf = pts[-1]
        sentido = -0.12 if pos[pai][0] == pos[filho][0] else 0.12  # arco entra pelo lado direito
        ax.add_patch(
            FancyArrowPatch(
                (xf - sentido, yf),
                (xf, yf),
                arrowstyle="-|>,head_length=4,head_width=2.5",
                color="#888888",
                linewidth=0,
                zorder=1,
            )
        )
    for u, (x, y) in xy.items():
        fundo, borda, _ = CORES[tipos[u]]
        ax.add_patch(
            FancyBboxPatch(
                (x - LARGURA / 2, y - ALTURA / 2),
                LARGURA,
                ALTURA,
                boxstyle="round,pad=0.02,rounding_size=0.08",
                facecolor=fundo,
                edgecolor=borda,
                linewidth=1.2,
                zorder=2,
            )
        )
        ax.text(x, y, nomes[u], ha="center", va="center", fontsize=6.5, zorder=3, color="#222222")
    for c, titulo in enumerate(TITULOS):
        ax.text(
            c * PASSO_X,
            PASSO_Y * 0.8,
            titulo,
            ha="center",
            fontsize=9,
            fontweight="bold",
            color="#333333",
        )
    legenda = [
        FancyBboxPatch((0, 0), 1, 1, facecolor=f, edgecolor=b, label=r)
        for f, b, r in CORES.values()
    ]
    ax.legend(
        handles=legenda,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.0),
        ncol=len(legenda),
        frameon=False,
        fontsize=8,
    )
    ax.set_xlim(-LARGURA / 2 - 0.2, (ncol - 1) * PASSO_X + LARGURA / 2 + 0.9)
    ax.set_ylim(-(nlin - 1) * PASSO_Y - 0.6, PASSO_Y * 1.3)
    ax.axis("off")
    ax.set_title(
        "Linhagem dos dados (dbt): fontes → staging → dimensões → intermediários → fatos",
        fontsize=11,
        pad=6,
        loc="left",
    )
    fig.tight_layout()
    return fig


def main() -> None:
    manifesto = json.loads(MANIFESTO.read_text())
    SAIDA.mkdir(parents=True, exist_ok=True)
    fig = desenhar(manifesto)
    fig.savefig(SAIDA / "lineage.png", bbox_inches="tight", facecolor="white")
    fig.savefig(SAIDA / "lineage.svg", bbox_inches="tight", facecolor="white")
    nomes, _, arestas = ler_grafo(manifesto)
    print(f"{len(nomes)} nós, {len(arestas)} arestas -> {SAIDA / 'lineage.png'}")


if __name__ == "__main__":
    main()
