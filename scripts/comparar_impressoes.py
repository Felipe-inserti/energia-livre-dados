"""Compara duas impressões digitais de `fct_previsao_carga` (`conferir_previsao --impressao`).

    uv run python -m scripts.comparar_impressoes ANTES.log DEPOIS.log

A previsão gravada é um retrato da origem. Duas gerações da MESMA origem só têm de dar o mesmo
resultado se a ENTRADA for a mesma:
  (a) mesma impressão digital da entrada -> previsão e erros têm de ser IDÊNTICOS (senão, FAIL);
  (b) entrada diferente (ou desconhecida: linha gravada antes de a impressão existir) -> mostra a
      diferença da entrada e da saída e PASSA: a diferença está explicada pela entrada.
"""

import sys


def ler(texto: str) -> dict:
    """`previsao n=12 soma=1.0 origem=.. entrada_hash=ab | erros n=3 soma=0.1` -> chaves."""
    saida = {}
    esquerda, _, direita = texto.strip().partition("|")
    for prefixo, parte in (("previsao", esquerda), ("erros", direita)):
        for token in parte.split():
            if "=" in token:
                chave, _, valor = token.partition("=")
                saida[f"{prefixo}_{chave}" if chave in ("n", "soma") else chave] = valor
    return saida


def comparar(antes: dict, depois: dict) -> tuple[bool, list[str]]:
    ha, hd = antes.get("entrada_hash"), depois.get("entrada_hash")
    conhecida = ha not in (None, "None", "")
    igual = conhecida and ha == hd
    campos = ("previsao_n", "previsao_soma", "origem", "erros_n", "erros_soma")
    difs = [c for c in campos if antes.get(c) != depois.get(c)]
    linhas = [f"entrada: {ha} -> {hd} ({'igual' if igual else 'DIFERENTE ou desconhecida'})"]
    if igual:
        linhas += [f"  {c}: {antes.get(c)} -> {depois.get(c)}" for c in difs]
        linhas.append(
            "PASS  mesma entrada e mesma saída"
            if not difs
            else "FAIL  mesma entrada, saída diferente"
        )
        return not difs, linhas
    for c in campos + ("entrada_ultimo",):
        marca = " (mudou)" if antes.get(c) != depois.get(c) else ""
        linhas.append(f"  {c}: {antes.get(c)} -> {depois.get(c)}{marca}")
    try:
        a, d = float(antes["previsao_soma"]), float(depois["previsao_soma"])
        linhas.append(f"  soma da previsão: {d - a:+.1f} MWmed ({100 * (d - a) / a:+.4f}%)")
    except (KeyError, ValueError):
        pass
    linhas.append(
        "PASS  a entrada é diferente (ou desconhecida): a diferença acima está explicada por ela"
    )
    return True, linhas


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("uso: comparar_impressoes ANTES.log DEPOIS.log")
        return 2
    antes, depois = (ler(open(a, encoding="utf-8").read()) for a in argv)
    ok, linhas = comparar(antes, depois)
    print("\n".join(linhas))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
