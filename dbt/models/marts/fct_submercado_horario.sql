{#
  Base de análise: carga, PLD e temperatura na mesma granularidade, uma linha por (submercado, hora
  UTC). Foi o `int_submercado_horario` até a 2.8, quando virou mart porque é o que o notebook, o ML
  (Sprint 5) e o dashboard consomem (docs/decisoes.md).

  Junção COMPLETA das três fontes, porque os períodos diferem: a carga vai de 2000 a out/2026, o PLD
  e o clima de 2021 em diante (o PLD é publicado no dia anterior, então passa um pouco da carga).
  Onde uma fonte não tem a linha, a coluna fica nula. A chave é a mesma nas três: o código do ONS do
  submercado (SE, S, NE, N). Lê os fatos de carga e de PLD (que já trazem o código do ONS) e o
  intermediário da temperatura, que só existe para o SE (as estações do INMET estão no SE/CO).

  Particionada por mês e clusterizada por submercado, como os outros fatos horários.
#}
{{
    config(
        partition_by={'field': 'instante_utc', 'data_type': 'timestamp', 'granularity': 'month'},
        cluster_by=['codigo_submercado'],
    )
}}

with carga as (

    select
        codigo_submercado,
        instante_utc,
        carga_mwmed
    from {{ ref('fct_carga_horaria') }}

),

pld as (

    select
        codigo_submercado,
        instante_utc,
        pld_rs_mwh
    from {{ ref('fct_pld_horario') }}

),

clima as (

    select
        codigo_submercado,
        instante_utc,
        temperatura_c
    from {{ ref('int_clima_submercado_horario') }}

)

select
    codigo_submercado,
    instante_utc,
    carga_mwmed,
    pld_rs_mwh,
    temperatura_c
from carga
full outer join pld using (codigo_submercado, instante_utc)
full outer join clima using (codigo_submercado, instante_utc)
