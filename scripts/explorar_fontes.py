"""Exploração das fontes de dados (tarefa 1.4): baixa/lê amostras e imprime um perfil.

Uso:
    uv run python scripts/explorar_fontes.py [ons|ccee|inmet|todas]

- ONS: baixa os CSVs de 2021 e 2025 (~1,5 MB cada) para data/amostras/ons/.
- CCEE: o portal bloqueia downloads automáticos; perfila os CSVs já colocados à mão
  em data/amostras/ccee/.
- INMET: lê do ZIP anual (data/amostras/inmet/2024.zip) só algumas estações do Sudeste,
  sem descompactar o resto, e salva essas estações em data/amostras/inmet/estacoes/.

Nada aqui é código de produção: é só para entender as fontes antes de escrever os extratores.
"""

import io
import sys
import zipfile
from pathlib import Path

import pandas as pd
import requests

RAIZ = Path(__file__).resolve().parent.parent
AMOSTRAS = RAIZ / "data" / "amostras"

ONS_URL = (
    "https://ons-aws-prod-opendata.s3.amazonaws.com/dataset/curva-carga-ho/CURVA_CARGA_{ano}.csv"
)
ONS_ANOS = (2021, 2025)

# Estações do Sudeste: SP Mirante, SP Bauru, RJ Copacabana, MG BH-Pampulha
INMET_ESTACOES = ("A701", "A705", "A652", "A521")
INMET_SENTINELA = -9999


def titulo(texto: str) -> None:
    print(f"\n{'=' * 78}\n{texto}\n{'=' * 78}")


def perfil_basico(df: pd.DataFrame, nome: str) -> None:
    """Colunas, tipos, nulos e uma amostra das primeiras linhas."""
    print(f"\n--- {nome}: {len(df):,} linhas x {df.shape[1]} colunas")
    resumo = pd.DataFrame(
        {
            "tipo": df.dtypes.astype(str),
            "nulos": df.isna().sum(),
            "pct_nulos": (df.isna().mean() * 100).round(2),
            "distintos": df.nunique(),
        }
    )
    print(resumo.to_string())
    print("\nprimeiras linhas:")
    print(df.head(3).to_string())


def perfil_serie_horaria(df: pd.DataFrame, ts: str, chave: str, valor: str) -> None:
    """Período, duplicatas e buracos de uma série horária com uma chave (ex.: subsistema)."""
    print(f"\nperíodo: {df[ts].min()}  ->  {df[ts].max()}")
    dup = df.duplicated([chave, ts]).sum()
    print(f"duplicatas em ({chave}, {ts}): {dup}")
    for k, g in df.groupby(chave):
        esperado = pd.date_range(g[ts].min(), g[ts].max(), freq="h")
        faltam = esperado.difference(g[ts])
        print(f"  {k}: {len(g):,} horas, esperadas {len(esperado):,}, faltando {len(faltam)}")
    v = df[valor]
    print(
        f"{valor}: min={v.min():.2f} mediana={v.median():.2f} max={v.max():.2f} "
        f"zeros={(v == 0).sum()} negativos={(v < 0).sum()}"
    )


# ---------------------------------------------------------------- ONS


def baixar(url: str, destino: Path) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.exists():
        print(f"já existe: {destino.relative_to(RAIZ)}")
        return
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    destino.write_bytes(resp.content)
    print(f"baixado: {destino.relative_to(RAIZ)} ({len(resp.content) / 1e6:.2f} MB)")


def explorar_ons() -> None:
    titulo("ONS: Curva de Carga Horária")
    for ano in ONS_ANOS:
        arq = AMOSTRAS / "ons" / f"curva_carga_{ano}.csv"
        baixar(ONS_URL.format(ano=ano), arq)
        df = pd.read_csv(arq, sep=";")
        perfil_basico(df, f"ONS {ano}")
        df["din_instante"] = pd.to_datetime(df["din_instante"])
        perfil_serie_horaria(df, "din_instante", "id_subsistema", "val_cargaenergiahomwmed")
        # o dado traz minutos diferentes de zero?
        print(f"instantes com minuto != 0: {(df['din_instante'].dt.minute != 0).sum()}")


# ---------------------------------------------------------------- CCEE


def ler_ccee(arq: Path) -> pd.DataFrame:
    # dtype=str para ver o formato cru (zeros à esquerda, aspas) antes de converter
    return pd.read_csv(arq, sep=";", dtype=str, encoding="utf-8")


def explorar_ccee_pld() -> None:
    titulo("CCEE: PLD horário (arquivos locais)")
    layouts = {}
    for arq in sorted((AMOSTRAS / "ccee").glob("pld_horario_*.csv")):
        bruto = arq.read_bytes()
        cabecalho = bruto.split(b"\n", 1)[0].decode()
        df = ler_ccee(arq)
        layouts[arq.name] = {
            "colunas": tuple(df.columns),
            "aspas": b'"' in bruto[:200],
            "crlf": b"\r\n" in bruto[:500],
            "dia_com_zero": bool(df["DIA"].str.len().eq(2).any() and df["DIA"].iloc[0] == "01"),
            "periodo_max": int(df["PERIODO_COMERCIALIZACAO"].astype(int).max()),
        }
        print(f"\n### {arq.name}  cabeçalho: {cabecalho.strip()}")
        print(f"layout: { {k: v for k, v in layouts[arq.name].items() if k != 'colunas'} }")
        df["PLD_HORA"] = df["PLD_HORA"].astype(float)
        mes = pd.to_datetime(df["MES_REFERENCIA"], format="%Y%m")
        df["ts"] = (
            mes
            + pd.to_timedelta(df["DIA"].astype(int) - 1, unit="D")
            + pd.to_timedelta(df["HORA"].astype(int), unit="h")
        )
        perfil_basico(df.drop(columns="ts"), arq.stem)
        perfil_serie_horaria(df, "ts", "SUBMERCADO", "PLD_HORA")
        print(f"submercados: {sorted(df['SUBMERCADO'].unique())}")
        print(f"meses presentes: {df['MES_REFERENCIA'].nunique()}")
        print(f"ordem das linhas crescente por tempo: {df['ts'].is_monotonic_increasing}")
    base = next(iter(layouts.values()))["colunas"]
    mudou = [n for n, d in layouts.items() if d["colunas"] != base]
    print(f"\narquivos com colunas diferentes de {next(iter(layouts))}: {mudou or 'nenhum'}")


def explorar_ccee_consumo() -> None:
    titulo("CCEE: consumo por ramo de atividade (arquivos locais)")
    for arq in sorted((AMOSTRAS / "ccee").glob("consumo_ramo_atividade_*.csv")):
        df = pd.read_csv(arq, sep=";")
        print(f"\n### {arq.name}")
        perfil_basico(df, arq.stem)
        print(f"meses: {sorted(df['MES_REFERENCIA'].unique())}")
        print(f"ramos distintos: {df['RAMO_ATIVIDADE'].nunique()}")
        dup = df.duplicated(["MES_REFERENCIA", "RAMO_ATIVIDADE"]).sum()
        print(f"duplicatas (mês, ramo): {dup}")
        ramo = df[df["RAMO_ATIVIDADE"].str.contains("SERVIÇOS|COMÉRCIO|VAREJ", case=False)]
        print("ramos de comércio/serviços:", sorted(ramo["RAMO_ATIVIDADE"].unique()))


# ---------------------------------------------------------------- INMET


def ler_estacao(conteudo: bytes) -> tuple[dict, pd.DataFrame]:
    texto = conteudo.decode("latin-1")
    linhas = texto.splitlines()
    meta = {}
    for linha in linhas[:8]:
        chave, _, valor = linha.partition(";")
        meta[chave.rstrip(":")] = valor
    df = pd.read_csv(
        io.StringIO("\n".join(linhas[8:])),
        sep=";",
        decimal=",",
        dtype={"Data": str, "Hora UTC": str},
    )
    df = df.loc[:, ~df.columns.str.startswith("Unnamed")]  # ';' final gera coluna vazia
    return meta, df


def explorar_inmet() -> None:
    titulo("INMET: estações automáticas (ZIP anual local)")
    caminho = AMOSTRAS / "inmet" / "2024.zip"
    saida = AMOSTRAS / "inmet" / "estacoes"
    saida.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(caminho) as z:
        nomes = z.namelist()
        print(f"{len(nomes)} arquivos no ZIP; ex.: {nomes[0]}")
        for cod in INMET_ESTACOES:
            alvo = [n for n in nomes if f"_{cod}_" in n]
            if not alvo:
                print(f"estação {cod} não encontrada no ZIP")
                continue
            conteudo = z.read(alvo[0])  # só este arquivo é descompactado
            (saida / Path(alvo[0]).name).write_bytes(conteudo)
            meta, df = ler_estacao(conteudo)
            print(f"\n### {alvo[0]}")
            print(f"metadados: {meta}")
            col_t = next(c for c in df.columns if c.startswith("TEMPERATURA DO AR"))
            perfil_basico(df, f"INMET {cod}")
            temp = df[col_t]
            print(
                f"\n{col_t}: nulos={temp.isna().sum()} sentinela({INMET_SENTINELA})="
                f"{(temp == INMET_SENTINELA).sum()} "
                f"min={temp[temp != INMET_SENTINELA].min()} max={temp.max()}"
            )
            hora = df["Hora UTC"].str.replace(" UTC", "").str.zfill(4)
            data = df["Data"].str.replace("/", "-")
            ts = pd.to_datetime(data + " " + hora, format="%Y-%m-%d %H%M")
            print(f"período: {ts.min()} -> {ts.max()}  duplicatas: {ts.duplicated().sum()}")
            esperado = pd.date_range(ts.min(), ts.max(), freq="h")
            print(f"horas esperadas {len(esperado)}, presentes {ts.nunique()}")
            print(f"formatos de Hora UTC: {sorted(df['Hora UTC'].str.len().unique())}")
            print(f"colunas totalmente nulas: {[c for c in df.columns if df[c].isna().all()]}")


# ---------------------------------------------------------------- main

FONTES = {
    "ons": [explorar_ons],
    "ccee": [explorar_ccee_pld, explorar_ccee_consumo],
    "inmet": [explorar_inmet],
}


def main() -> None:
    escolha = sys.argv[1] if len(sys.argv) > 1 else "todas"
    nomes = list(FONTES) if escolha == "todas" else [escolha]
    for nome in nomes:
        for fn in FONTES[nome]:
            try:
                fn()
            except Exception as exc:  # uma fonte com problema não derruba as outras
                print(f"\n[ERRO em {fn.__name__}] {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
