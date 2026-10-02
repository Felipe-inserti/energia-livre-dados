"""Exploração das fontes de dados (tarefa 1.4): baixa/lê amostras e imprime um perfil.

Uso:
    uv run python scripts/explorar_fontes.py \
        [ons|ccee|inmet|pld-historico|ons-historico|todas]

- ONS: baixa os CSVs de 2021 e 2025 (~1,5 MB cada) para data/amostras/ons/.
- CCEE: o portal bloqueia downloads automáticos; perfila os CSVs já colocados à mão
  em data/manual/ccee/.
- INMET: lê do ZIP anual (data/manual/inmet/2024.zip) só algumas estações do Sudeste,
  sem descompactar o resto, e salva essas estações em data/amostras/inmet/estacoes/.

- PLD-HISTORICO (tarefa 1.10): perfila o arquivo semanal 2001–2020 (colocado à mão em
  data/manual/ccee/) e calcula o PLD médio de 2020 do SUDESTE, ponderado pelas horas de cada
  semana.
- ONS-HISTORICO (tarefa 1.10): baixa os CSVs de 2000 a 2025 e verifica layout, completude,
  horário de verão e quebras de nível na carga mensal do SE.

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
MANUAL_CCEE = RAIZ / "data" / "manual" / "ccee"  # arquivos baixados à mão (ver docs/fontes.md)

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
    for arq in sorted(MANUAL_CCEE.glob("pld_horario_*.csv")):
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
    for arq in sorted(MANUAL_CCEE.glob("consumo_ramo_atividade_*.csv")):
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
    caminho = RAIZ / "data" / "manual" / "inmet" / "2024.zip"
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


# ---------------------------------------------------------------- PLD histórico (1.10)

PLD_HIST = MANUAL_CCEE / "pld_historico_semanal_2001_2020.csv"
LIMITE_ERRO_PLD = 20.0  # R$/MWh: aproximação aceita se o erro máximo for menor que isso


def explorar_pld_historico() -> None:
    titulo("CCEE: PLD histórico semanal 2001–2020 (arquivo local)")
    bruto = PLD_HIST.read_bytes()
    aspas = b'"' in bruto[:200]
    crlf = b"\r\n" in bruto[:500]
    cabecalho = bruto.split(b"\n", 1)[0].decode().strip()
    print(f"layout: aspas={aspas} crlf={crlf} cabeçalho={cabecalho}")
    d = pd.read_csv(PLD_HIST, sep=";", dtype=str)
    perfil_basico(d, "pld_historico_semanal")
    d["PLD"] = d["PLD_HORA"].astype(float)
    for c in ("PERIODO_COMERCIALIZACAO", "DIA", "HORA"):
        d[c] = d[c].astype(int)
    print(f"\nHORA distintas: {sorted(d['HORA'].unique())}  (sempre 0: não é série horária)")
    print(f"submercados: {d['SUBMERCADO'].value_counts().to_dict()}")
    print(
        f"meses de referência: {d['MES_REFERENCIA'].nunique()} "
        f"({d['MES_REFERENCIA'].min()} a {d['MES_REFERENCIA'].max()})"
    )
    print(f"linhas por ano: {d.groupby(d['MES_REFERENCIA'].str[:4]).size().to_dict()}")

    # cada semana tem 3 linhas (patamares): a chave natural não é única
    chave = ["MES_REFERENCIA", "SUBMERCADO", "PERIODO_COMERCIALIZACAO", "DIA"]
    print(f"linhas por {chave}: {d.groupby(chave).size().value_counts().to_dict()}")
    print(
        f"linhas exatamente duplicadas: {d.duplicated().sum()} "
        "(são patamares com o mesmo preço, não erro: não deduplicar)"
    )

    # data de início de cada semana e checagens de estrutura
    d["inicio"] = pd.to_datetime(
        d["MES_REFERENCIA"].str[:4]
        + "-"
        + d["MES_REFERENCIA"].str[4:]
        + "-"
        + d["DIA"].astype(str),
        format="%Y-%m-%d",
    )
    print(
        f"dia da semana do início das semanas: {d['inicio'].dt.day_name().value_counts().to_dict()}"
    )
    ok_periodo = (d["PERIODO_COMERCIALIZACAO"] == (d["DIA"] - 1) * 24 + 1).mean()
    print(
        f"PERIODO = (DIA-1)*24+1 em {ok_periodo * 100:.1f}% das linhas "
        "(índice da hora do mês em que a semana começa)"
    )

    semanas = d.drop_duplicates(["SUBMERCADO", "inicio"])[["SUBMERCADO", "inicio"]]
    for sub, g in semanas.groupby("SUBMERCADO"):
        passos = g["inicio"].sort_values().diff().dropna().dt.days.value_counts().to_dict()
        print(f"  {sub}: semanas={len(g)} intervalos entre inícios (dias): {passos}")

    # patamar: o arquivo não diz qual linha é qual; a ordem das linhas é informativa?
    d["ordem"] = d.groupby(chave).cumcount()
    w = d.pivot_table(index=chave, columns="ordem", values="PLD")
    mono = ((w[0] <= w[1]) & (w[1] <= w[2])).mean() * 100
    print(f"semanas com linha1 <= linha2 <= linha3: {mono:.1f}% (ordem não identifica o patamar)")

    # PLD médio de 2020, SUDESTE, ponderado pelas horas de cada semana que caem em 2020
    print("\n--- PLD médio de 2020 ponderado pelas horas de cada semana ---")
    ini, fim = pd.Timestamp("2020-01-01"), pd.Timestamp("2021-01-01")
    for sub in ("SUDESTE", "NORDESTE", "NORTE", "SUL"):
        s_ = w.reset_index()
        s_ = s_[s_["SUBMERCADO"] == sub].copy()
        s_["inicio"] = pd.to_datetime(
            s_["MES_REFERENCIA"].str[:4]
            + "-"
            + s_["MES_REFERENCIA"].str[4:]
            + "-"
            + s_["DIA"].astype(str)
        )
        s_ = s_.sort_values("inicio")
        s_["fim"] = s_["inicio"] + pd.Timedelta(days=7)  # semana operativa: sábado a sexta
        a = s_["inicio"].clip(lower=ini)
        b = s_["fim"].clip(upper=fim)
        horas = ((b - a).dt.total_seconds() / 3600).clip(lower=0)
        s_ = s_[horas > 0]
        horas = horas[horas > 0]
        media = s_[[0, 1, 2]].mean(axis=1)
        pesos = horas / horas.sum()
        m, lo, hi = (
            (media * pesos).sum(),
            (s_[[0, 1, 2]].min(axis=1) * pesos).sum(),
            (s_[[0, 1, 2]].max(axis=1) * pesos).sum(),
        )
        err = max(hi - m, m - lo)
        marca = "OK (< R$ 20)" if err < LIMITE_ERRO_PLD else "ACIMA DE R$ 20: AVISAR"
        print(
            f"{sub}: semanas={len(s_)} horas cobertas={horas.sum():.0f} (2020 tem 8784) "
            f"média={m:.2f} piso={lo:.2f} teto={hi:.2f} erro máximo={err:.2f} -> {marca}"
        )
        if sub == "SUDESTE":
            print(
                f"   primeira semana: {s_['inicio'].iloc[0].date()} "
                f"(horas em 2020: {horas.iloc[0]:.0f}); última: {s_['inicio'].iloc[-1].date()} "
                f"(horas em 2020: {horas.iloc[-1]:.0f})"
            )
            print(f"   média simples das semanas (sem pesos): {media.mean():.2f}")


# ---------------------------------------------------------------- ONS histórico (1.10)

ONS_HIST_ANOS = range(2000, 2026)
ONS_DIARIA_URL = "https://ons-aws-prod-opendata.s3.amazonaws.com/dataset/carga_energia_di/CARGA_ENERGIA_{ano}.csv"
LIMIAR_DEGRAU = 0.05  # ±5% (variação contra o mesmo mês do ano anterior)
# Início do horário de verão em 2014–2018 (datas de memória; 2000–2013 vêm da lacuna na série)
DST_INICIO_MEMORIA = {
    2014: "2014-10-19",
    2015: "2015-10-18",
    2016: "2016-10-16",
    2017: "2017-10-15",
    2018: "2018-11-04",
}


def terceiro_domingo(ano: int, mes: int) -> pd.Timestamp:
    d = pd.Timestamp(ano, mes, 1)
    return d + pd.Timedelta(days=(6 - d.weekday()) % 7 + 14)


def deslocamento_perfil(se: pd.DataFrame, dia: pd.Timestamp) -> tuple[int, float]:
    """Deslocamento (h) que melhor alinha o perfil diário (dias úteis) antes e depois de `dia`.

    Compara os 21 dias antes com os 21 dias depois. Se a série acompanha o relógio oficial, o
    perfil não muda de lugar quando o horário de verão começa (deslocamento 0). Se estivesse em
    horário fixo, o perfil depois do início andaria cerca de 1 hora.
    """

    def perfil(a: pd.Timestamp, b: pd.Timestamp) -> list[float]:
        x = se[(se["t"] >= a) & (se["t"] < b) & (se["t"].dt.weekday < 5)]
        return x.groupby(x["t"].dt.hour)["v"].mean().reindex(range(24)).tolist()

    antes = pd.Series(perfil(dia - pd.Timedelta(days=21), dia))
    depois = perfil(dia + pd.Timedelta(days=1), dia + pd.Timedelta(days=22))
    melhor = (0, -2.0)
    for k in range(-2, 3):
        girado = pd.Series(depois[-k:] + depois[:-k] if k else depois)
        corr = float(antes.corr(girado))
        if corr > melhor[1]:
            melhor = (k, corr)
    return melhor


def comparar_carga_diaria() -> None:
    """A média diária da curva horária bate com o dataset 'Carga de Energia Diária' do ONS?

    Importa porque a página desse dataset documenta as mudanças de definição da carga (inclusão
    de geração não despachada em 2021 e da MMGD estimada a partir de 29/04/2023), e a página da
    curva horária não documenta nenhuma.
    """
    print("\n--- Média diária da curva horária contra o dataset 'Carga de Energia Diária'")
    print("ano  dias  max|razão-1|  dias com diferença > 0,01%")
    for ano in ONS_HIST_ANOS:
        arq = AMOSTRAS / "ons" / "carga_diaria" / f"CARGA_ENERGIA_{ano}.csv"
        baixar(ONS_DIARIA_URL.format(ano=ano), arq)
        diaria = pd.read_csv(arq, sep=";")
        diaria["dia"] = pd.to_datetime(diaria["din_instante"])
        horaria = pd.read_csv(
            AMOSTRAS / "ons" / f"curva_carga_{ano}.csv", sep=";", parse_dates=["din_instante"]
        )
        horaria["dia"] = horaria["din_instante"].dt.normalize()
        media = horaria.groupby(["id_subsistema", "dia"])["val_cargaenergiahomwmed"].mean()
        x = diaria.merge(media.rename("h").reset_index(), on=["id_subsistema", "dia"])
        x = x.dropna(subset=["h", "val_cargaenergiamwmed"])
        r = (x["h"] / x["val_cargaenergiamwmed"] - 1).abs()
        print(f"{ano} {len(x):5d} {r.max():11.2e} {int((r > 1e-4).sum()):5d}")


def explorar_ons_historico() -> None:
    titulo("ONS: curva de carga 2000–2025 (layout, completude, horário de verão, quebras)")
    linhas, cabecalhos, mensal, share = [], {}, {}, {}
    dst = []
    for ano in ONS_HIST_ANOS:
        arq = AMOSTRAS / "ons" / f"curva_carga_{ano}.csv"
        baixar(ONS_URL.format(ano=ano), arq)
        bruto = arq.read_bytes()
        cab = bruto.split(b"\n", 1)[0].decode("utf-8-sig").strip()
        cabecalhos.setdefault(
            (cab, bruto[:3] == b"\xef\xbb\xbf", b"\r\n" in bruto[:300]), []
        ).append(ano)
        df = pd.read_csv(arq, sep=";")
        df["t"] = pd.to_datetime(df["din_instante"])
        df["v"] = df["val_cargaenergiahomwmed"]
        horas = pd.date_range(f"{ano}-01-01", f"{ano}-12-31 23:00", freq="h")
        faltam, nulos, dup = {}, {}, {}
        for sub, g in df.groupby("id_subsistema"):
            faltam[sub] = len(horas.difference(g["t"]))
            nulos[sub] = int(g["v"].isna().sum())
            dup[sub] = int(g["t"].duplicated().sum())
        linhas.append(
            {
                "ano": ano,
                "linhas": len(df),
                "esperado": 4 * len(horas),
                "subsistemas": ",".join(sorted(df["id_subsistema"].unique())),
                "faltam_linhas": sum(faltam.values()),
                "nulos": sum(nulos.values()),
                "duplicatas": sum(dup.values()),
                "minuto!=0": int((df["t"].dt.minute != 0).sum()),
                "negativos_ou_zero": int((df["v"] <= 0).sum()),
            }
        )
        se = df[df["id_subsistema"] == "SE"]
        mensal[ano] = se.groupby(se["t"].dt.month)["v"].mean()
        tot = df.groupby("id_subsistema")["v"].sum()
        share[ano] = tot["SE"] / tot.sum()

        # horário de verão: início pela lacuna (2000–2013) ou por data de memória; depois controle
        lac = horas.difference(se["t"])
        nulo_00 = se[se["v"].isna()]["t"]
        if len(lac) == 1 and lac[0].hour == 0:
            d0, origem = lac[0].normalize(), "lacuna de 00:00 na série"
        elif ano in DST_INICIO_MEMORIA:
            d0, origem = pd.Timestamp(DST_INICIO_MEMORIA[ano]), "data de memória"
        else:
            d0, origem = terceiro_domingo(ano, 10), "controle (sem DST no país)"
        if ano > 2000:
            k, c = deslocamento_perfil(se.dropna(subset=["v"]), d0)
            dst.append(
                {
                    "ano": ano,
                    "data": str(d0.date()),
                    "origem": origem,
                    "linha_00h_no_dia": "ausente"
                    if len(lac) == 1 and lac[0].hour == 0
                    else (
                        "nula"
                        if ((nulo_00.dt.normalize() == d0) & (nulo_00.dt.hour == 0)).any()
                        else "presente"
                    ),
                    "desloc_perfil_h": k,
                    "corr": round(c, 4),
                }
            )

    tab = pd.DataFrame(linhas).set_index("ano")
    print("\n--- Layout (cabeçalho, BOM, CRLF) por grupo de anos")
    for k, anos in cabecalhos.items():
        print(f"  {k}: {anos[0]}..{anos[-1]} ({len(anos)} anos)")
    print("\n--- Completude por ano (todos os subsistemas)")
    print(tab.to_string())

    print("\n--- Horário de verão: o perfil diário do SE muda de lugar quando o horário muda?")
    print("(deslocamento 0 = série em horário oficial local, acompanhando o relógio)")
    print(pd.DataFrame(dst).to_string(index=False))

    # carga mensal do SE e quebras de nível
    m = pd.DataFrame(mensal).T.rename_axis("ano")
    m.columns = [f"{c:02d}" for c in m.columns]
    print("\n--- Carga média mensal do SE (MWmed): linhas = ano, colunas = mês")
    print(m.round(0).astype("Int64").to_string())
    anual = m.mean(axis=1)
    print("\n--- Média anual do SE (MWmed) | variação anual | participação do SE no total dos 4")
    for ano in m.index:
        var = anual.loc[ano] / anual.loc[ano - 1] - 1 if ano - 1 in anual.index else float("nan")
        print(
            f"{ano}: {anual.loc[ano]:9.0f} {var * 100:+6.1f}%   SE/total = {share[ano] * 100:.2f}%"
        )

    serie = m.stack()
    serie.index = pd.PeriodIndex([f"{a}-{mm}" for a, mm in serie.index], freq="M")
    yoy = serie / serie.shift(12) - 1
    flag = yoy[yoy.abs() > LIMIAR_DEGRAU]
    print(
        f"\n--- Meses com variação > ±{LIMIAR_DEGRAU * 100:.0f}% contra o mesmo mês do ano anterior"
    )
    # agrupa meses consecutivos em blocos
    blocos, atual = [], []
    for per, v in flag.items():
        if atual and (per - atual[-1][0]).n > 1:
            blocos.append(atual)
            atual = []
        atual.append((per, v))
    if atual:
        blocos.append(atual)
    for b in blocos:
        print(
            f"  {b[0][0]} a {b[-1][0]} ({len(b)} meses): de {min(v for _, v in b) * 100:+.1f}% "
            f"a {max(v for _, v in b) * 100:+.1f}%"
        )
    mm12 = serie.rolling(12).mean()
    var12 = mm12 / mm12.shift(12) - 1
    f12 = var12[var12.abs() > LIMIAR_DEGRAU]
    print(
        f"meses com a média móvel de 12 meses > ±{LIMIAR_DEGRAU * 100:.0f}% contra 12 meses antes: "
        f"{len(f12)}" + (f" ({f12.index.min()} a {f12.index.max()})" if len(f12) else "")
    )
    saida = AMOSTRAS / "ons" / "carga_mensal_se.csv"
    serie.rename("carga_media_se_mwmed").to_csv(saida)
    print(f"\nsérie mensal do SE gravada em {saida.relative_to(RAIZ)}")

    # variação anual por subsistema em abr e mai/2023 (a MMGD estimada entra em 29/04/2023)
    print("\n--- Variação anual (%) por subsistema, abr e mai/2023")
    for sub in ("N", "NE", "S", "SE"):
        tot = {}
        for ano in (2022, 2023):
            df = pd.read_csv(
                AMOSTRAS / "ons" / f"curva_carga_{ano}.csv", sep=";", parse_dates=["din_instante"]
            )
            df = df[df["id_subsistema"] == sub]
            tot[ano] = df.groupby(df["din_instante"].dt.month)["val_cargaenergiahomwmed"].mean()
        var = (tot[2023] / tot[2022] - 1) * 100
        print(f"  {sub}: abr {var[4]:+.1f}%  mai {var[5]:+.1f}%  salto {var[5] - var[4]:+.1f} p.p.")
    comparar_carga_diaria()


# ---------------------------------------------------------------- main

FONTES = {
    "ons": [explorar_ons],
    "ccee": [explorar_ccee_pld, explorar_ccee_consumo],
    "inmet": [explorar_inmet],
    "pld-historico": [explorar_pld_historico],
    "ons-historico": [explorar_ons_historico],
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
