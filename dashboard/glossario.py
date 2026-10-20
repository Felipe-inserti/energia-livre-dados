"""Glossário único do dashboard: cada página escolhe os termos que usa (`selecionar`).

Dois nomes parecidos NÃO são a mesma coisa e ficam definidos juntos em toda página:
- "Ano anterior": estratégia de CONTRATO (página Decisão), contrata o consumo médio do ano passado;
- "Mesmo mês do ano anterior": modelo de COMPARAÇÃO da previsão (página Previsão), repete o valor do
  mesmo mês do ano passado.
`visual.ANO_ANTERIOR` e `visual.MESMO_MES` guardam os nomes; um teste impede trocá-los.
"""

TERMOS = {
    "PLD": "Preço de Liquidação das Diferenças: o preço da energia no mercado de curto prazo "
    "(R\\$/MWh).",
    "MWm": "megawatt médio: a energia média por hora; 100 MWh/mês ≈ 0,137 MWm.",
    "MAPE": "erro percentual médio absoluto: a média dos erros em %, sem sinal (previsto menos "
    "real, dividido pelo real).",
    "MMGD": "micro e minigeração distribuída (painéis solares em telhados, por exemplo): a carga "
    "deixa de aparecer na rede e muda a definição da série em 2023.",
    "CVaR": "média do custo nos 5% piores cenários.",
    "Viés": "erro médio com sinal: negativo quer dizer previsto abaixo do real.",
    "Cobertura": "parte dos meses em que o valor real caiu dentro do intervalo previsto; um "
    "intervalo de 80% deveria cobrir 80%.",
    "Modelo": "a média de três modelos estatísticos (ETS, SARIMA e regressão), escolhida no "
    "desenvolvimento e usada uma única vez no teste final.",
    "Mesmo mês do ano anterior": "modelo de comparação da página Previsão: repete o valor do "
    "mesmo mês do ano passado. Não é a estratégia de contrato 'Ano anterior'.",
    "Ano anterior": "estratégia de contrato da página Decisão: contrata o consumo médio do ano "
    "passado. Não é o modelo de comparação 'Mesmo mês do ano anterior'.",
    "Previsão · Otimizada": "estratégias de contrato: o volume previsto · o volume que a regra "
    "escolhe dentro da banda.",
    "Banda": "folga (±) que o contrato permite em torno do volume contratado.",
    "Valor da previsão": "custo do Ano anterior − custo da Previsão.",
    "Valor da otimização": "custo da Previsão − custo da Otimizada.",
    "Contrafactual": "o que teria acontecido numa condição que não existiu; aqui, contratar no "
    "mercado livre antes de poder migrar.",
}


def selecionar(*chaves: str) -> dict[str, str]:
    """Os termos pedidos, na ordem pedida; chave desconhecida é erro (não some em silêncio)."""
    return {c: TERMOS[c] for c in chaves}
