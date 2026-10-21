"""Sistema visual comum às páginas do dashboard: paleta, formato brasileiro e componentes.

UM módulo só (redesenho aprovado em `data/logs/relatorio_6c2_redesign.md`), para as páginas ficarem
coesas: a mesma cor para a mesma coisa, as mesmas duas caixas, o mesmo formato de número.

Regras:
- Petróleo = a estratégia Otimizada; cinza = comparações; âmbar = SÓ alerta (prévia, especulação).
- Duas caixas: `nota` (neutra) e `alerta` (âmbar). Nada de `st.error` e `st.success`.
- Todo valor em R$ passa por `reais()`; dentro de Markdown, com `md=True` (o `$` vira `\\$`, porque
  o Streamlit trata o texto entre dois `$` como fórmula LaTeX).
"""

import streamlit as st

from dashboard import calculos as cal

# ---------------------------------------------------------------- paleta
PETROLEO = "#0f6e8c"  # Otimizada (destaque)
CINZA = "#8a94a6"  # comparações
CINZA_CLARO = "#cfd5df"
CINZA_ESCURO = "#4b5563"
AMBAR = "#c9731b"  # alerta: só prévia e especulação
TEXTO = "#1f2933"
FUNDO_CARTAO = "#f5f7fa"
PALETA = frozenset({PETROLEO, CINZA, CINZA_CLARO, CINZA_ESCURO, AMBAR, TEXTO, FUNDO_CARTAO})

# nomes curtos e iguais em todo o dashboard (a definição fica no help= e no glossário)
ANO_ANTERIOR = "Ano anterior"  # estratégia de CONTRATO: o consumo médio do ano anterior (Decisão)
# modelo de COMPARAÇÃO da previsão: repete o mesmo mês do ano anterior (Previsão). NÃO é o de cima
MESMO_MES = "Mesmo mês do ano anterior"
PREVISAO = "Previsão"  # contrata o volume previsto (a "pontual")
OTIMIZADA = "Otimizada"  # contrata o volume que a regra escolhe dentro da banda
NOMES_DAS_ESTRATEGIAS = {"ingenua": ANO_ANTERIOR, "pontual": PREVISAO, "otimizada": OTIMIZADA}
COR_DA_ESTRATEGIA = {ANO_ANTERIOR: CINZA_CLARO, PREVISAO: CINZA_ESCURO, OTIMIZADA: PETROLEO}

# ---------------------------------------------------------------- formato brasileiro


def reais(valor: float, casas: int = 2, sinal: bool = False, md: bool = False) -> str:
    """'R$ 9.020,19'. Com `md=True` o `$` sai escapado, para uso dentro de st.markdown/caption."""
    texto = cal.reais(valor, casas, sinal)
    return texto.replace("$", "\\$") if md else texto


def reais_curto(valor: float, md: bool = False) -> str:
    """Para os cartões, sem centavos: 8690,10 -> 'R$ 8,7 mil'; -330,10 -> '−R$ 330'.

    Arredonda UMA vez, a partir do valor exato (a regra de arredondamento da página)."""
    sinal = "−" if round(valor, 0) < 0 else ""
    v = abs(valor)
    if v >= 1000:
        texto = f"R$ {cal.numero(v / 1000, 1)} mil"
    else:
        texto = f"R$ {cal.numero(v, 0)}"
    texto = sinal + texto
    return texto.replace("$", "\\$") if md else texto


def percentual(valor: float, casas: int = 1, sinal: bool = False) -> str:
    return cal.percentual(valor, casas, sinal)


def ano(valor) -> str:
    """O ano é sempre texto ('2021'), nunca número ('2.021')."""
    return str(int(valor))


# ---------------------------------------------------------------- componentes


def cabecalho(titulo: str, manifesto: dict, hashes_curtos: tuple[str, str] | None = None) -> None:
    """Título e uma linha de estado: de quando são os dados e que nada foi ajustado depois."""
    st.title(titulo)
    partes = [f"Dados de {cal.data_br(manifesto['snapshot_gerado_em'])} (sem consulta ao vivo)"]
    if hashes_curtos:
        partes.append(
            f"pré-registrado antes de rodar ({hashes_curtos[0]} · {hashes_curtos[1]}); "
            "as expectativas que erraram estão reportadas na auditoria, no fim"
        )
    st.caption(" · ".join(partes))
    for aviso in manifesto.get("avisos_de_defasagem", []):
        alerta(aviso)


def frase(texto: str) -> None:
    """A mensagem principal, em uma frase, logo abaixo do cabeçalho."""
    nota(texto)


def nota(texto: str) -> None:
    """Caixa neutra (a única, junto de `alerta`)."""
    st.info(texto, icon=":material/info:")


def alerta(texto: str) -> None:
    """Caixa âmbar: só quando a leitura correta depende do aviso (prévia, especulação)."""
    st.warning(texto, icon=":material/warning:")


def cartao(
    ressalva: str, rotulo: str, valor: str, linhas: list[str], ajuda: str | None = None
) -> None:
    """Um cartão: a ressalva ANTES do número, depois o rótulo e o valor, e a linha de apoio.

    A ressalva é uma legenda acima do `st.metric` (o rótulo do metric não quebra linha e cortaria
    o texto em tela estreita)."""
    with st.container(border=True):
        st.caption(ressalva)
        st.metric(rotulo, valor, help=ajuda)
        for linha in linhas:
            st.caption(linha)


def limitacoes(titulo: str, itens: list[str]) -> None:
    st.subheader(titulo)
    st.markdown("\n".join(f"{i}. {t}" for i, t in enumerate(itens, 1)))


def glossario(termos: dict[str, str], titulo: str | None = None):
    """Expander fechado com as siglas e os termos; devolve o contêiner (usar com `with`)."""
    if titulo is None:
        titulo = f"Glossário ({', '.join(list(termos)[:3])} e outros termos)"
    caixa = st.expander(titulo, expanded=False)
    with caixa:
        st.markdown("\n".join(f"- **{k}:** {v}" for k, v in termos.items()))
    return caixa


def auditoria(titulo: str = "Auditoria: pré-registros, execuções, hashes e invariâncias"):
    """Expander FECHADO: tudo que serve para conferir, não para ler de relance."""
    return st.expander(titulo, expanded=False)
