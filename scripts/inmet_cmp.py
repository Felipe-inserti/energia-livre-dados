"""Análise dos ZIPs anuais do INMET (tarefa 1.4): layout entre anos e completude da temperatura.

Uso:
    uv run python scripts/inmet_cmp.py [ANO ...]        (padrão: 2021 2024)

Espera os ZIPs em data/amostras/inmet/{ANO}.zip e lê os CSVs direto do ZIP, sem descompactar.

1. Compara o layout dos arquivos entre os anos (metadados, cabeçalho, formato de Data e Hora UTC).
2. Calcula, por estação, o % de horas do ano com temperatura válida (não nula e != -9999).
   Hora ausente do arquivo conta como inválida, porque o denominador são as horas do ano.
3. Aplica o critério de seleção: >= LIMITE % em TODOS os anos analisados, em SE e CO.

Saída: relatório no terminal e data/amostras/inmet/completude_estacoes.csv (ignorado pelo git).
"""

import collections
import io
import re
import sys
import zipfile
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
PASTA = RAIZ / "data" / "amostras" / "inmet"
SAIDA = PASTA / "completude_estacoes.csv"

REGIOES = ("SE", "CO")  # Sudeste e Centro-Oeste (submercado SE/CO)
LIMITE = 95.0  # % mínimo de horas válidas de temperatura em cada ano
SENTINELA = -9999
LINHAS_METADADOS = 8


def horas_no_ano(ano: int) -> int:
    return 8784 if ano % 4 == 0 and (ano % 100 != 0 or ano % 400 == 0) else 8760


def mascara(texto: str) -> str:
    """Troca dígitos por 9 para comparar formatos (ex.: 2021/01/01 -> 9999/99/99)."""
    return re.sub(r"\d", "9", texto)


def ler_arquivo(conteudo: bytes) -> tuple[dict[str, str], str, pd.DataFrame]:
    linhas = conteudo.decode("latin-1").splitlines()
    meta = {}
    for linha in linhas[:LINHAS_METADADOS]:
        campo, _, valor = linha.partition(";")
        meta[campo.rstrip(":")] = valor
    cabecalho = linhas[LINHAS_METADADOS]
    df = pd.read_csv(
        io.StringIO("\n".join(linhas[LINHAS_METADADOS:])),
        sep=";",
        decimal=",",
        dtype={"Data": str, "Hora UTC": str},
    )
    df = df.loc[:, ~df.columns.str.startswith("Unnamed")]  # ';' final gera coluna vazia
    return meta, cabecalho, df


def analisar_ano(ano: int) -> tuple[pd.DataFrame, dict]:
    estacoes = []
    cabecalhos = collections.Counter()
    campos_meta = collections.Counter()
    fmt_data = collections.Counter()
    fmt_hora = collections.Counter()
    sentinelas = 0
    with zipfile.ZipFile(PASTA / f"{ano}.zip") as z:
        for nome in z.namelist():
            if not nome.upper().endswith(".CSV"):
                continue
            meta, cabecalho, df = ler_arquivo(z.read(nome))
            cabecalhos[cabecalho] += 1
            campos_meta[tuple(meta)] += 1
            fmt_data[mascara(df["Data"].iloc[0])] += 1
            fmt_hora[mascara(df["Hora UTC"].iloc[0])] += 1
            col = next(c for c in df.columns if c.startswith("TEMPERATURA DO AR"))
            temp = df[col]
            sentinelas += int((temp == SENTINELA).sum())
            valida = temp.notna() & (temp != SENTINELA)
            horas_validas = (df["Data"] + df["Hora UTC"])[valida].nunique()
            estacoes.append(
                {
                    "cod": meta["CODIGO (WMO)"],
                    "regiao": meta["REGIAO"],
                    "uf": meta["UF"],
                    "nome": meta["ESTACAO"],
                    f"pct_{ano}": 100 * horas_validas / horas_no_ano(ano),
                }
            )
    layout = {
        "arquivos": len(estacoes),
        "cabecalhos": cabecalhos,
        "campos_meta": len(campos_meta),
        "fmt_data": dict(fmt_data),
        "fmt_hora": dict(fmt_hora),
        "sentinelas": sentinelas,
    }
    return pd.DataFrame(estacoes), layout


def main() -> None:
    anos = [int(a) for a in sys.argv[1:]] or [2021, 2024]
    tabelas, layouts = {}, {}
    for ano in anos:
        tabelas[ano], layouts[ano] = analisar_ano(ano)
        lay = layouts[ano]
        print(
            f"{ano}: {lay['arquivos']} estações | cabeçalhos distintos: {len(lay['cabecalhos'])} | "
            f"variantes de metadados: {lay['campos_meta']} | Data {lay['fmt_data']} | "
            f"Hora {lay['fmt_hora']} | sentinelas na temperatura: {lay['sentinelas']}"
        )
    base = set(layouts[anos[0]]["cabecalhos"])
    for ano in anos[1:]:
        print(f"cabeçalho {anos[0]} == {ano}: {set(layouts[ano]['cabecalhos']) == base}")

    # uma linha por estação; NaN no ano em que a estação não existe
    todas = pd.concat([t.set_index("cod")[[f"pct_{a}"]] for a, t in tabelas.items()], axis=1)
    info = pd.concat(t.set_index("cod")[["regiao", "uf", "nome"]] for t in tabelas.values())
    todas = todas.join(info[~info.index.duplicated()])
    colunas = [f"pct_{a}" for a in anos]
    todas["em_todos_os_anos"] = todas[colunas].notna().all(axis=1)
    todas["passa"] = todas["em_todos_os_anos"] & (todas[colunas] >= LIMITE).all(axis=1)
    todas = todas.sort_values(["regiao", "uf", "nome"])
    todas.round(2).to_csv(SAIDA)

    alvo = todas[todas["regiao"].isin(REGIOES)]
    print(
        f"\nEstações {'/'.join(REGIOES)}: {len(alvo)} (em todos os anos: "
        f"{int(alvo['em_todos_os_anos'].sum())}); passam em >= {LIMITE}% em {anos}: "
        f"{int(alvo['passa'].sum())}"
    )
    resumo = (
        alvo[alvo["em_todos_os_anos"]]
        .groupby(["regiao", "uf"])
        .agg(em_todos=("passa", "size"), passam=("passa", "sum"))
    )
    print(resumo.to_string())
    for uf, grupo in alvo[alvo["passa"]].groupby("uf"):
        itens = "; ".join(
            f"{cod} {r['nome']} (" + "/".join(f"{r[c]:.1f}" for c in colunas) + ")"
            for cod, r in grupo.iterrows()
        )
        print(f"\n{uf}: {itens}")
    print(f"\nCSV completo: {SAIDA.relative_to(RAIZ)}")


if __name__ == "__main__":
    main()
