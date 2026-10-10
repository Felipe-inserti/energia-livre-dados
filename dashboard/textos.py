"""Textos da página de Decisão: UM lugar só para toda ressalva.

Cada função devolve o texto JÁ PREENCHIDO com os números do snapshot (calculados em `calculos.py`,
nunca digitados aqui). Redesenho aprovado em `data/logs/relatorio_6c2_redesign.md`: frases curtas,
linguagem comum (o jargão do código só aparece na auditoria) e todo valor em R$ por
`visual.reais(..., md=True)`, que escapa o `$` do Markdown.
Os testes procuram as frases-chave abaixo (`CHAVES`) na tela e a posição delas.
"""

from dashboard import calculos as cal
from dashboard import visual as vis

# Frases-chave que os testes procuram (e que não podem sumir da tela)
CHAVES = {
    "cinco_anos": "sem teste de significância",
    "simulado": "um consumidor desse porte ainda não podia migrar ao mercado livre",
    "portaria": "Portaria MME 465/2019",
    "uma_vez": "uma única vez",
    "uma_vez_cada": "uma vez cada",
    "placar": "6 se confirmaram e 6 foram parcialmente refutadas",
    "h4": "a H4 (ii) do plano A",
    "concentracao": "Dois anos concentram o ganho",
    "previsao_zero": "a previsão vale ≈ 0",
    "sem_preco": "A flexibilidade não tem preço no modelo",
    "opcao": "banda maior é uma opção maior",
    "f0": "efeito do volume sob o diferencial de preço",
    "especulacao": "especulação",
    "excluida": "excluída do caso base",
    "previa": "PRÉVIA",
    "nao_e_a_decisao": "não é a decisão do contrato de 2027",
    "reversao": "volta à média",
    "nao_garantia": "não uma garantia",
    "lastro": "Sem penalidade por insuficiência de lastro",
    "arredondamento": "arredondado ao centavo uma vez",
}

R = vis.reais  # atalho: sempre com md=True quando o texto vai para o Markdown

NOTA_ARREDONDAMENTO = (
    f"Cada valor é {CHAVES['arredondamento']}, a partir do valor exato; por isso a soma das "
    "partes exibidas pode diferir do total exibido em R$ 0,01.".replace("$", "\\$")
)
NOTA_DOS_CARTOES = (
    "Cartões arredondados uma vez, a partir dos valores exatos; as tabelas mantêm os centavos."
)

# ---------------------------------------------------------------- 1. em uma frase


def frase_principal(res: dict) -> str:
    return (
        f"Em 5 anos simulados, otimizar o volume contratado reduziu o custo em "
        f"**{vis.percentual(res['economia_total_pct'], 1)}** "
        f"({vis.reais_curto(res['economia_total_rs'], md=True)}); o ganho veio de 2022 e 2025, e a "
        "previsão de consumo, sozinha, quase não contou."
    )


# ---------------------------------------------------------------- 2. três cartões

AJUDA_ECONOMIA = (
    "Economia total = custo do Ano anterior − custo da Otimizada = valor da previsão + valor da "
    "otimização. Ano anterior: repete o consumo do ano passado. Otimizada: contrata o volume que a "
    "regra escolhe dentro da banda. Percentual sobre o custo do Ano anterior; positivo é custo "
    "evitado."
)
AJUDA_CONCENTRACAO = (
    "Valor da otimização = custo da Previsão − custo da Otimizada. Previsão: contrata o volume "
    "previsto. Em 2022 e 2025 o PLD do ano ficou do lado certo do preço do contrato. São 5 anos "
    "que dependem uns dos outros: ordem de grandeza, não evidência."
)


def ajuda_previsao(meses: tuple[int, int]) -> str:
    return (
        "Valor da previsão = custo do Ano anterior − custo da Previsão. Dentro da banda de ±10% o "
        "custo não depende do volume contratado, e o erro de previsão (1% a 4%) cabe na banda; "
        f"Ano anterior e Previsão ficam de {meses[0]} a {meses[1]} meses por ano fora da faixa."
    )


def cartoes(res: dict, res_sem_2021: dict, conc: dict, meses: tuple[int, int]) -> list[dict]:
    """Os três cartões: a ressalva (ANTES do número), o rótulo, o valor e a linha de apoio."""
    soma_23_24 = conc["soma_outros_rs"] - conc["outros"].get(2021, 0.0)
    zero_prev = abs(res["valor_previsao_pct"]) < 0.1
    return [
        {
            "ressalva": f"5 anos simulados, {CHAVES['cinco_anos']}",
            "rotulo": "Economia total",
            "valor": vis.reais_curto(res["economia_total_rs"]),
            "linhas": [
                f"{vis.percentual(res['economia_total_pct'], 1)} do custo · "
                f"sem 2021: {vis.percentual(res_sem_2021['economia_total_pct'], 1)}"
            ],
            "ajuda": AJUDA_ECONOMIA,
        },
        {
            "ressalva": CHAVES["concentracao"],
            "rotulo": "Parte vinda de 2022 e 2025",
            "valor": vis.percentual(conc["pct_do_total"], 0),
            "linhas": [
                f"do valor da otimização ({vis.reais_curto(conc['soma_destacados_rs'], md=True)} "
                f"de {vis.reais_curto(conc['total_rs'], md=True)}); 2023 e 2024 somam "
                f"{vis.reais_curto(soma_23_24, md=True)}"
            ],
            "ajuda": AJUDA_CONCENTRACAO,
        },
        {
            "ressalva": "Com banda de ±10%",
            "rotulo": "Valor da previsão",
            "valor": "≈ 0" if zero_prev else vis.reais_curto(res["valor_previsao_rs"]),
            "linhas": [
                f"{vis.reais_curto(res['valor_previsao_rs'], md=True)} "
                f"({vis.percentual(res['valor_previsao_pct'], 2)}): {CHAVES['previsao_zero']}; "
                "o ganho vem da flexibilidade da banda",
                f"sem 2021: {vis.reais_curto(res_sem_2021['valor_previsao_rs'], md=True)} "
                f"({vis.percentual(res_sem_2021['valor_previsao_pct'], 2)})",
            ],
            "ajuda": ajuda_previsao(meses),
        },
    ]


# ---------------------------------------------------------------- 3. ganho por ano

LEGENDA_GANHO = (
    "Destaque: 2022 e 2025. Faixa cinza (2021–2023): simulado; "
    f"{CHAVES['simulado']} ({CHAVES['portaria']}). Em 2024 e 2025 já podia, via comercializador "
    "varejista (Portaria Normativa MME 50/2022)."
)


def legenda_concentracao_exata(c: dict) -> str:
    """O arredondamento único, com centavos (no expander de números por ano)."""
    soma_23_24 = c["soma_outros_rs"] - c["outros"].get(2021, 0.0)
    return (
        f"2022 + 2025 = {R(c['soma_destacados_rs'], md=True)} "
        f"({vis.percentual(c['pct_do_total'], 1)} de {R(c['total_rs'], md=True)}); "
        f"2023 + 2024 = {R(soma_23_24, md=True)}; 2021 = "
        f"{R(c['outros'].get(2021, 0.0), md=True)}. {NOTA_ARREDONDAMENTO}"
    )


# ---------------------------------------------------------------- 4. por que funcionou


def por_que_funcionou(n_no_limite: int) -> str:
    return (
        "A regra compara o preço do contrato com o PLD esperado pelos cenários e aposta na "
        f"**{CHAVES['reversao']}**: contrato acima do esperado, contrata menos que a previsão; "
        f"abaixo, mais. Em {n_no_limite} dos 5 anos foi ao limite da banda. **Ganhou onde o PLD do "
        "ano ficou do lado certo (2022, 2025) e perdeu pouco onde não ficou (2023, 2024).**"
    )


LEGENDA_D3 = (
    "Contrato acima do PLD esperado: a regra contrata o mínimo da banda; abaixo: o máximo. "
    "Em 2021, com a menor diferença, o volume fica no meio da banda. " + NOTA_ARREDONDAMENTO
)

# ---------------------------------------------------------------- 5. a banda

RESSALVA_BANDA = (
    f"**{CHAVES['sem_preco']}:** o mesmo preço de contrato vale para qualquer banda, então o "
    "valor da otimização é um **teto**, não uma estimativa."
)


def texto_da_banda(t) -> str:
    v0, v3 = float(t["valor_otimizacao_rs"].iloc[0]), float(t["valor_otimizacao_rs"].iloc[-1])
    return (
        f"Valor da otimização de {vis.reais_curto(v0, md=True)} (banda de 0%) a "
        f"{vis.reais_curto(v3, md=True)} (15%). **Esperava-se mais valor da otimização com banda "
        f"menor; foi o contrário, porque {CHAVES['opcao']}** (expectativa pré-registrada e "
        "refutada)."
    )


ROTULO_F0 = f"{CHAVES['f0']} (não é valor da previsão)"


def nota_f0(por_ano_f0: dict[int, float], soma: float) -> str:
    def v(ano):
        return R(por_ano_f0[ano], sinal=True, md=True)

    return (
        "**Com banda de 0% o contrato é fixo em MWm e todo desvio é liquidado ao PLD.** O custo "
        "depende do volume e do diferencial de preço; a precisão da previsão não entra. O Ano "
        "anterior contrata menos que a Previsão em todos os anos; por isso o sinal segue o PLD do "
        f"ano: **{v(2022)} em 2022** e **positivo em 2021 ({v(2021)}), 2024 ({v(2024)}) e 2025 "
        f"({v(2025)})**. A soma de 5 anos ({R(soma, sinal=True, md=True)}) é resultado de apostas "
        "de sinais opostos, não de uma previsão melhor."
    )


# ---------------------------------------------------------------- 6. sensibilidades

NOTA_SENSIBILIDADES = (
    "Cada ponto muda **uma variável por vez**, na ordem declarada antes de rodar; nenhum foi "
    f"escolhido por render mais e nenhum substitui o caso base. Em âmbar, a "
    f"{CHAVES['especulacao']} **{CHAVES['excluida']}**."
)

NOTA_SENSIBILIDADES_TABELA = (
    "A tabela segue a ordem declarada antes de rodar e **não é ordenada por economia**. Em 8 "
    "variações (peso do risco, nível do CVaR, volume até 1,2×, PLD simples, dispersão ×1,25 e "
    "×1,5, limitação do PLD) o Ano anterior e a Previsão são **idênticos** ao caso base: só a "
    "Otimizada muda. Quatro variações de cenário deram o **mesmo** valor da otimização do caso "
    "base: a decisão depende do sinal de (PLD esperado − preço do contrato), não do detalhe "
    "dos cenários. " + NOTA_ARREDONDAMENTO
)

NOTA_ESPECULATIVA = f"{CHAVES['especulacao']}, {CHAVES['excluida']}"
ROTULO_ESPECULATIVA = "Volume até 1,2× a previsão"

ROTULOS_SENSIBILIDADES = {
    "caso_base": "Caso base",
    "f00": "Banda de 0%",
    "f05": "Banda de 5%",
    "f15": "Banda de 15%",
    "spread00": "Contrato sem margem (PLD do ano anterior + R$ 0)",
    "spread40": "Contrato com margem de R$ 40 (em vez de R$ 20)",
    "lam00": "Sem peso para o risco (CVaR)",
    "lam10": "Peso máximo para o risco (CVaR)",
    "alfa90": "CVaR no nível de 90% (em vez de 95%)",
    "rmax120": f"{ROTULO_ESPECULATIVA} ({CHAVES['especulacao']})",
    "pldsimples": "Cenários de PLD simples (em vez de blocos de 12 meses)",
    "disp125": "Cenários com dispersão ×1,25",
    "disp150": "Cenários com dispersão ×1,5",
    "clip": "PLD limitado ao piso e ao teto (clip)",
}


def rotulo_rmax120(linha: dict, por_ano: dict[int, float], pld_set_out: tuple[float, float]) -> str:
    return (
        f"**Volume até 1,2× a previsão: {CHAVES['especulacao']}, {CHAVES['excluida']}.** Dobra o "
        f"valor da otimização (**{R(linha['valor_otimizacao_rs'], md=True)}**, "
        f"{vis.percentual(linha['valor_otimizacao_pct'], 2)}; economia total "
        f"{R(linha['economia_total_rs'], md=True)}, "
        f"{vis.percentual(linha['economia_total_pct'], 2)}"
        "), mas **só porque contrata mais para vender a sobra ao PLD**: o ganho é uma aposta em "
        f"**PLD acima do preço do contrato** (2025: {R(por_ano[2025], sinal=True, md=True)}; 2024: "
        f"{R(por_ano[2024], sinal=True, md=True)}, com sobra vendida em meses de PLD de "
        f"R\\$ {cal.numero(pld_set_out[0], 0)} e R\\$ {cal.numero(pld_set_out[1], 0)}) e **o "
        f"espelho perde** (2023: {R(por_ano[2023], sinal=True, md=True)}). O caso base limita o "
        "volume a `[1/(1+banda); 1/(1−banda)]` da previsão de propósito, para que a banda "
        'contratada sempre contenha a previsão (decisão tomada **antes** de rodar). Não é "a '
        'melhor" estratégia.'
    )


# ---------------------------------------------------------------- 7. prévia


def previa(
    data_snapshot: str,
    inicio: str,
    fim: str,
    frase_regra: str,
    v_otimizada: float,
    v_previsao: float,
    assumidos: bool,
) -> str:
    regra = frase_regra.replace("$", "\\$")
    texto = (
        f"**{CHAVES['previa']}: {CHAVES['nao_e_a_decisao']}.** Próximos 12 meses "
        f"({inicio} a {fim}), dados de {data_snapshot}. **{regra}.** A Otimizada contrata "
        f"**{cal.numero(v_otimizada, 4)} MWm**, contra **{cal.numero(v_previsao, 4)} MWm** da "
        f"Previsão. Regra que volta à média, **{CHAVES['nao_garantia']}**; os cenários "
        "subestimam o regime de piso do PLD"
    )
    texto += "; limites de PLD de 2027 **assumidos**." if assumidos else "."
    return texto + " Sem economia: não há consumo nem PLD realizados."


# ---------------------------------------------------------------- 8. limitações (sempre visíveis)

TITULO_LIMITACOES = "O que este resultado não mostra"
LIMITACOES = [
    f"**{CHAVES['lastro']}** (regra a confirmar na CCEE): o valor da previsão é um piso; a "
    "economia da otimização, um teto.",
    "**A flexibilidade da banda não tem preço no modelo.**",
    f"**5 anos simulados, consumidor sintético, {CHAVES['cinco_anos']}.** Em 2021–2023 um "
    f"consumidor desse porte ainda não podia migrar ({CHAVES['portaria']}).",
    "**O preço do contrato é uma regra** (PLD do ano anterior + R\\$ 20), não de mercado.",
    "**Os cenários de PLD subestimam o regime de piso prolongado** (10% a 15% dos meses no piso, "
    "contra 58% a 67% em 2022–2023).",
]

LIMITACOES_EXTRAS = (
    "Um caso terminou com a cobertura abaixo de 100%: a Otimizada de 2022 (5,36 MWh, +0,46% acima "
    "do teto contratado). O custo realizado de 2023 passou do CVaR95 ex-ante nas três estratégias. "
    "O contrato é plano em MWm, modulado perfeitamente pela carga dentro do mês (simplificação). "
    "O acompanhamento diário do contrato vigente (6.8) não está implementado."
)

# ---------------------------------------------------------------- glossário

GLOSSARIO = {
    "PLD": "Preço de Liquidação das Diferenças: o preço da energia no mercado de curto prazo "
    "(R\\$/MWh).",
    "MWm": "megawatt médio: a energia média por hora; 100 MWh/mês ≈ 0,137 MWm.",
    "CVaR": "média do custo nos 5% piores cenários.",
    "Banda": "folga (±) que o contrato permite em torno do volume contratado.",
    "Valor da previsão": "custo do Ano anterior − custo da Previsão.",
    "Valor da otimização": "custo da Previsão − custo da Otimizada.",
    "Ano anterior · Previsão · Otimizada": "contrata o consumo do ano passado · o volume previsto "
    "· o volume que a regra escolhe dentro da banda.",
    "Contrafactual": "o que teria acontecido numa condição que não existiu; aqui, contratar no "
    "mercado livre antes de poder migrar.",
}


# ---------------------------------------------------------------- auditoria


def pre_registro(hash_base: str, hash_sens: str, execucao_id: str, commit: str) -> str:
    return (
        "**Como estes números foram produzidos.** O backtest do caso base foi executado "
        f"**{CHAVES['uma_vez']}**, depois do pré-registro **`{hash_base}`** (critérios congelados "
        "antes de ler o dado realizado de 2021 a 2025). As **13 sensibilidades** foram executadas "
        f"**{CHAVES['uma_vez_cada']}**, depois do pré-registro **`{hash_sens}`**. Cenários do "
        f"caso base: `execucao_id` **`{execucao_id}`**. Versão do código do snapshot: "
        f"`{commit[:7]}`. Nenhum critério foi alterado depois de ver o resultado.\n\n"
        "**Expectativas pré-registradas:** das 12 expectativas das sensibilidades, "
        f"{CHAVES['placar']}; {CHAVES['h4']} (mais valor da otimização com banda menor) foi "
        "refutada; todas estão reportadas em `docs/decisoes.md`, no repositório."
    )
