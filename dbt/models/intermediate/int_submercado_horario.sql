{#
  Carga, PLD e temperatura na mesma granularidade: uma linha por (submercado, hora UTC).

  Junção COMPLETA das três fontes, porque os períodos diferem: a carga vai de 2000 a out/2026, o PLD
  e o clima de 2021 em diante (o PLD é publicado no dia anterior, então passa um pouco da carga).
  Onde uma fonte não tem a linha, a coluna fica nula. A chave é a mesma nas três: o código do ONS do
  submercado (SE, S, NE, N); o PLD, que vem com o nome da CCEE, é traduzido pela dim_submercado. A
  temperatura só existe para o SE (as estações do INMET estão no SE/CO).

  Particionada por mês e clusterizada por submercado, como os fatos.
#}
{{
    config(
        partition_by={'field': 'instante_utc', 'data_type': 'timestamp', 'granularity': 'month'},
        cluster_by=['codigo_submercado'],
    )
}}

with carga as (

    select
        id_subsistema as codigo_submercado,
        instante_utc,
        carga_mwmed
    from {{ ref('stg_ons__curva_carga') }}

),

pld as (

    select
        s.codigo_submercado,
        p.instante_utc,
        p.pld_rs_mwh
    from {{ ref('stg_ccee__pld_horario') }} as p
    inner join {{ ref('dim_submercado') }} as s on s.nome_ccee = p.submercado

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
