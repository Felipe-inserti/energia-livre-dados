"""Registro dos candidatos da Sprint 5 (grade FECHADA, definida antes de rodar o desenvolvimento).

Nada é acrescentado depois de ver o resultado: o limite de complexidade é este arquivo. Cada
candidato tem o nome, a função de previsão (ou, nas combinações, a lista dos componentes) e uma
`complexidade` usada só no último desempate da escolha (menor = mais simples).
"""

from dataclasses import dataclass

from ml.baselines import sazonal_ingenuo
from ml.modelos import ets, lgbm, regressao, sarima


@dataclass(frozen=True)
class Candidato:
    nome: str
    funcao: object = None  # None nas combinações
    componentes: tuple[str, ...] = ()
    complexidade: int = 0


INGENUO = Candidato("sazonal_ingenuo", sazonal_ingenuo, complexidade=0)

BASES = {
    "regressao": Candidato("regressao", regressao, complexidade=1),
    "ets": Candidato("ets", ets, complexidade=2),
    "sarima": Candidato("sarima", sarima, complexidade=3),
    "lgbm": Candidato("lgbm", lgbm, complexidade=6),
}
COMBINACOES = {
    "comb_ets_sarima": Candidato("comb_ets_sarima", componentes=("ets", "sarima"), complexidade=4),
    "comb_ets_sarima_regressao": Candidato(
        "comb_ets_sarima_regressao", componentes=("ets", "sarima", "regressao"), complexidade=5
    ),
}
CANDIDATOS = {c.nome: c for c in (*BASES.values(), *COMBINACOES.values())}

# Critério de escolha (docs/decisoes.md; aprovado antes de rodar)
LIMIAR_PP = 0.25  # um erro-padrão da diferença de MAPE contra o ingênuo, medido na exploração
MIN_ANOS_MELHORES = 5  # de 8 anos-alvo do desenvolvimento

# REGRA PRÉ-REGISTRADA ANTES DO TESTE FINAL (docs/decisoes.md). O teste final roda UMA vez, só com o
# vencedor do critério congelado no desenvolvimento e o ingênuo; nenhum outro candidato entra nele.
CANDIDATO_DO_TESTE_FINAL = "comb_ets_sarima_regressao"
REGRA_SPRINT_6 = (
    "a Sprint 6 usa a média ETS+SARIMA+regressão na estratégia de previsão independentemente "
    "do resultado do teste final; o teste final serve para reportar o desempenho, não para "
    "nova seleção"
)
RESSALVA_VITORIA = (
    "a vitória no desenvolvimento foi de 0,255 p.p. sobre o ingênuo (limiar 0,25 p.p.), menor que "
    "1 erro-padrão (0,27 p.p.)"
)

# Versão do modelo em produção (Sprint 5): a média ETS+SARIMA+regressão sobre a série reconstruída,
# janela de 72 meses e choque da COVID imputado. Mudar QUALQUER parâmetro abaixo muda o hash e deve
# subir a versão (o hash vai em cada linha de `fct_previsao_carga`).
MODELO_VERSAO = "comb_ets_sarima_regressao_v1"
SERIE_DE_PRODUCAO = "carga_ajustada_reconstruida_mwmed"


def parametros_do_modelo() -> dict:
    """Tudo o que define a previsão, para o hash de proveniência."""
    from ml import modelos, preparo

    return {
        "componentes": list(COMBINACOES[CANDIDATO_DO_TESTE_FINAL].componentes),
        "janela_meses": preparo.JANELA_MESES,
        "evento_covid": [d.isoformat() for d in preparo.EVENTO_COVID],
        "k_sigma": preparo.K_SIGMA,
        "ref_meses": preparo.REF_MESES,
        "ets_grade": list(modelos.ETS_GRADE),
        "sarima_grade": [[list(o), list(s)] for o, s in modelos.SARIMA_GRADE],
        "regressao_alpha": modelos.REGRESSAO_ALPHA,
        "serie": SERIE_DE_PRODUCAO,
    }


def previsor_do_vencedor():
    """A função de previsão do vencedor: média simples dos componentes registrados."""
    from ml.modelos import media_de

    return media_de(*(BASES[n].funcao for n in COMBINACOES[CANDIDATO_DO_TESTE_FINAL].componentes))


# Resolução da série de carga que entra nos modelos: 3 casas = 1 kW. O mart (`fct_carga_mensal`) já
# sai arredondado assim (var `casas_decimais_carga` do dbt); aqui o arredondamento é a DEFESA EM
# PROFUNDIDADE: é idempotente sobre um valor já arredondado e protege a previsão de um mart
# construído antes da mudança ou de outra fonte. O AVG paralelo do BigQuery não é reproduzível bit
# a bit (ruído de 1e-12) e o SARIMA amplifica esse ruído (docs/decisoes.md).
CASAS_DECIMAIS_CARGA = 3


def arredondar_serie(serie: dict) -> dict:
    return {mes: round(float(valor), CASAS_DECIMAIS_CARGA) for mes, valor in serie.items()}
