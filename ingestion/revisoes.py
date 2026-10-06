"""Revisões retroativas do ONS: compara duas versões do mesmo CSV e mede o que mudou.

O ONS avisa que os dados passam por "processo de consistência recorrente", ou seja, valores já
publicados podem mudar. Comparar duas versões do arquivo, linha a linha, pela chave natural
(`id_subsistema`, `din_instante`), responde: quantas linhas mudaram, em que meses e de quanto.

A comparação é em memória (sem BigQuery e sem custo). Cada medição vira uma linha de JSONL em
`data/logs/revisoes_ons.jsonl` (a tabela no BigQuery fica para quando a DAG o produzir sozinha).
"""

import hashlib
import io
import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

CHAVE = ["id_subsistema", "din_instante"]
COLUNA_VALOR = "val_cargaenergiahomwmed"
ARQUIVO_LOG = Path("data/logs/revisoes_ons.jsonl")


def _ler(conteudo: bytes) -> pd.DataFrame:
    df = pd.read_csv(io.BytesIO(conteudo), sep=";", dtype=str)
    if df.duplicated(CHAVE).any():
        raise ValueError("chave (id_subsistema, din_instante) duplicada no arquivo")
    df["valor"] = pd.to_numeric(df[COLUNA_VALOR], errors="raise")
    return df.set_index(CHAVE)


def comparar_csv_ons(antes: bytes, depois: bytes, ano: int) -> dict:
    """Mede a diferença entre duas versões do CSV de um ano. Mesmo conteúdo -> `identico`."""
    registro: dict = {
        "ano": ano,
        "bytes_antes": len(antes),
        "bytes_depois": len(depois),
        "md5_antes": hashlib.md5(antes, usedforsecurity=False).hexdigest(),
        "md5_depois": hashlib.md5(depois, usedforsecurity=False).hexdigest(),
    }
    registro["identico"] = antes == depois
    if registro["identico"]:
        return registro

    a, d = _ler(antes), _ler(depois)
    ambas = a.join(d, how="inner", lsuffix="_antes", rsuffix="_depois")
    va, vd = ambas["valor_antes"], ambas["valor_depois"]
    mudou = ~((va == vd) | (va.isna() & vd.isna()))
    nulo_para_valor = va.isna() & vd.notna()
    valor_para_nulo = va.notna() & vd.isna()
    valor_para_valor = mudou & va.notna() & vd.notna()
    dif = (vd - va)[valor_para_valor]
    pct = (dif.abs() / va[valor_para_valor].abs()).replace([float("inf")], float("nan"))
    nome_alterado = ambas["nom_subsistema_antes"] != ambas["nom_subsistema_depois"]

    alteradas = mudou | nome_alterado
    meses = ambas.index.get_level_values("din_instante").str.slice(0, 7)
    registro.update(
        {
            "linhas_antes": len(a),
            "linhas_depois": len(d),
            "adicionadas": len(d.index.difference(a.index)),
            "removidas": len(a.index.difference(d.index)),
            "valor_alterado": int(valor_para_valor.sum()),
            "nulo_para_valor": int(nulo_para_valor.sum()),
            "valor_para_nulo": int(valor_para_nulo.sum()),
            "nome_alterado": int(nome_alterado.sum()),
            "linhas_alteradas": int(alteradas.sum()),
            "dif_abs_media_mwmed": float(dif.abs().mean()) if len(dif) else 0.0,
            "dif_abs_max_mwmed": float(dif.abs().max()) if len(dif) else 0.0,
            "dif_pct_max": float(pct.max()) if len(pct) and pct.notna().any() else 0.0,
            "dif_liquida_mwmed": float(dif.sum()) if len(dif) else 0.0,
            "por_subsistema": {
                k: int(v)
                for k, v in alteradas.groupby(ambas.index.get_level_values("id_subsistema"))
                .sum()
                .items()
                if v
            },
            "por_mes": {k: int(v) for k, v in alteradas.groupby(meses).sum().items() if v},
        }
    )
    return registro


def resumir(registro: dict) -> str:
    """Uma linha legível por arquivo."""
    if registro["identico"]:
        return f"{registro['ano']}: idêntico ({registro['bytes_depois']:,} bytes)"
    return (
        f"{registro['ano']}: {registro['bytes_antes']:,} -> {registro['bytes_depois']:,} bytes; "
        f"{registro['linhas_alteradas']} linhas alteradas "
        f"(valor {registro['valor_alterado']}, nulo->valor {registro['nulo_para_valor']}, "
        f"valor->nulo {registro['valor_para_nulo']}, nome {registro['nome_alterado']}), "
        f"+{registro['adicionadas']} / -{registro['removidas']} linhas; "
        f"dif. máx {registro['dif_abs_max_mwmed']:.3f} MWmed ({registro['dif_pct_max']:.4%}); "
        f"meses: {registro['por_mes']}"
    )


def registrar(registro: dict, origem: str, arquivo: Path = ARQUIVO_LOG) -> None:
    """Acrescenta a medição ao JSONL (origem: `ingestao` ou `comparacao`)."""
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    completo = {"medido_em": datetime.now(UTC).isoformat(timespec="seconds"), "origem": origem}
    with arquivo.open("a", encoding="utf-8") as f:
        f.write(json.dumps({**completo, **registro}, ensure_ascii=False) + "\n")
