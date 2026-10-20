"""Utilitários dos testes de página (AppTest): ler a árvore, textos, gráficos e contar palavras.

Compartilhados por `test_dashboard_decisao.py`, `test_dashboard_previsao.py` e os demais. As
páginas são rodadas por `AppTest.from_function`, cuja função precisa estar num arquivo de teste.
"""

import json
import re

import pandas as pd


def achatar(bloco, saida=None):
    """Todos os elementos na ordem em que aparecem (entrando nos expanders e colunas)."""
    saida = [] if saida is None else saida
    for k in sorted(bloco.children):
        n = bloco.children[k]
        if getattr(n, "children", None):
            saida.append((n.type, n))
            achatar(n, saida)
        else:
            saida.append((n.type, n))
    return saida


def elementos(at):
    return achatar(at.main)


def spec(no) -> str:
    """O spec Vega-Lite de um gráfico, legível (o JSON do Streamlit escapa os acentos)."""
    return json.dumps(json.loads(no.proto.spec), ensure_ascii=False)


def dados_do_grafico(no, coluna: str | None = None) -> pd.DataFrame:
    """Os dados de um gráfico Altair (o Streamlit os manda em Arrow, fora do spec). Com várias
    camadas há vários conjuntos: devolve o maior que tem a `coluna`."""
    import pyarrow as pa

    todos = [pa.ipc.open_stream(ds.data.data).read_all().to_pandas() for ds in no.proto.datasets]
    candidatos = [d for d in todos if coluna is None or coluna in d.columns]
    return max(candidatos, key=len)


def texto(no) -> str:
    """O texto de um elemento; de um gráfico, o spec e os dados; de uma tabela, o CSV."""
    if hasattr(no, "proto") and hasattr(no.proto, "spec"):
        tudo = [spec(no)]
        for ds in no.proto.datasets:
            import pyarrow as pa

            tudo.append(pa.ipc.open_stream(ds.data.data).read_all().to_pandas().to_csv())
        return "\n".join(tudo)
    valor = getattr(no, "value", "")
    rotulo = getattr(no, "label", "") or ""  # métricas e expanders: o rótulo também é texto
    if isinstance(valor, str):
        return f"{rotulo}\n{valor}" if rotulo else valor
    if isinstance(valor, pd.DataFrame):
        return valor.to_csv() + " ".join(map(str, valor.columns))
    return rotulo


def indice(at, tipo: str, contem: str) -> int:
    for i, (t, no) in enumerate(elementos(at)):
        if t == tipo and contem in texto(no):
            return i
    raise AssertionError(f"não achei {tipo} com {contem!r}")


def indice_exp(at, comeca_com: str) -> int:
    return next(
        i
        for i, (t, no) in enumerate(elementos(at))
        if t == "expander" and no.label.startswith(comeca_com)
    )


def primeiro(at, tipo: str) -> int:
    return next(i for i, (t, _) in enumerate(elementos(at)) if t == tipo)


def expander(at, comeca_com: str):
    return next(
        no for t, no in elementos(at) if t == "expander" and no.label.startswith(comeca_com)
    )


def toda_a_tela(at) -> str:
    return "\n".join(texto(no) for _, no in elementos(at))


def antes_do_glossario(at) -> str:
    """Tudo que aparece fora do glossário e da auditoria (o glossário vem antes da auditoria)."""
    saida = []
    for t, no in elementos(at):
        if t == "expander" and no.label.startswith("Glossário"):
            break
        saida.append(texto(no))
    return "\n".join(saida)


def palavras(t: str) -> int:
    return len(re.findall(r"\S+", re.sub(r"[*`_#>]", "", t or "")))


def palavras_visiveis(bloco) -> int:
    """Prosa visível, sem tooltips e sem o que está dentro de expanders (fechados)."""
    total = 0
    for k in sorted(bloco.children):
        n = bloco.children[k]
        if n.type == "expander":
            continue
        if getattr(n, "children", None):
            total += palavras_visiveis(n)
        elif n.type in ("title", "subheader", "caption", "markdown", "info", "warning"):
            total += palavras(n.value)
        elif n.type == "metric":
            total += palavras(n.label) + palavras(n.value)
    return total


def textos_do_grafico(no) -> str:
    """O que o leitor VÊ de um gráfico: títulos e células de texto dos dados (não os nomes de campo,
    que ficam no JSON)."""
    import pyarrow as pa

    def titulos(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k in ("title", "text") and isinstance(v, str):
                    yield v
                else:
                    yield from titulos(v)
        elif isinstance(x, list):
            for v in x:
                yield from titulos(v)

    saida = list(titulos(json.loads(no.proto.spec)))
    for ds in no.proto.datasets:
        d = pa.ipc.open_stream(ds.data.data).read_all().to_pandas()
        for c in d.select_dtypes(include=["object", "string"]).columns:
            saida.extend(map(str, d[c].unique()))
    return "\n".join(saida)
