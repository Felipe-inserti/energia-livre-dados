"""Escolha do modelo pelo critério DEFINIDO ANTES de rodar (Sprint 5, docs/decisoes.md).

Entrada: uma linha por candidato com as métricas do desenvolvimento. Regras, nesta ordem:
1. Elegível = bate o sazonal ingênuo por mais de LIMIAR_PP pontos de MAPE E em pelo menos
   MIN_ANOS_MELHORES dos anos-alvo. Se ninguém é elegível, vence o próprio ingênuo.
2. Entre os elegíveis, o melhor MAPE define o grupo de empate: quem está a até LIMIAR_PP dele.
3. Dentro do grupo, desempate lexicográfico: menor |viés %|, menor erro absoluto do ano inteiro na
   origem de dezembro, menor MAPE do pior ano, menor complexidade.
Só o desenvolvimento entra aqui; o teste final nunca escolhe nada.
"""

from ml.registro import LIMIAR_PP, MIN_ANOS_MELHORES


def escolher(linhas: list[dict]) -> dict:
    """`linhas`: dicts com candidato, mape_pct, vies_pct, erro_anual_dez_abs_pct, mape_pior_ano_pct,
    anos_melhores_que_ingenuo, diferenca_mape_vs_ingenuo_pp (positivo = melhor que o ingênuo) e
    complexidade. Devolve {"vencedor", "elegiveis", "empate", "motivo"}."""
    candidatos = [r for r in linhas if r["candidato"] != "sazonal_ingenuo"]
    elegiveis = [
        r
        for r in candidatos
        if r["diferenca_mape_vs_ingenuo_pp"] > LIMIAR_PP
        and r["anos_melhores_que_ingenuo"] >= MIN_ANOS_MELHORES
    ]
    if not elegiveis:
        return {
            "vencedor": "sazonal_ingenuo",
            "elegiveis": [],
            "empate": [],
            "motivo": "nenhum candidato bate o ingênuo pelo critério",
        }
    melhor = min(r["mape_pct"] for r in elegiveis)
    empate = [r for r in elegiveis if r["mape_pct"] - melhor <= LIMIAR_PP]
    ordenado = sorted(
        empate,
        key=lambda r: (
            abs(r["vies_pct"]),
            r["erro_anual_dez_abs_pct"],
            r["mape_pior_ano_pct"],
            r["complexidade"],
        ),
    )
    motivo = (
        "menor MAPE"
        if len(empate) == 1
        else f"empate (até {LIMIAR_PP} pp do melhor) desfeito por viés, erro anual, pior ano, "
        "simplicidade"
    )
    return {
        "vencedor": ordenado[0]["candidato"],
        "elegiveis": [r["candidato"] for r in elegiveis],
        "empate": [r["candidato"] for r in empate],
        "motivo": motivo,
    }
