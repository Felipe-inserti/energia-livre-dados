{#
  Fato: PLD horário por submercado. Grão: (submercado, hora UTC). 201.696 linhas.

  O submercado vem com o nome da CCEE (SUDESTE, ...) e é traduzido para o código do ONS pela
  dim_submercado, que é a chave comum de todos os fatos. Particionada por mês e clusterizada por
  submercado (ver fct_carga_horaria).
#}
{{
    config(
        partition_by={'field': 'instante_utc', 'data_type': 'timestamp', 'granularity': 'month'},
        cluster_by=['codigo_submercado'],
    )
}}

select
    s.codigo_submercado,
    p.instante_utc,
    p.pld_rs_mwh,
    p._carregado_em
from {{ ref('stg_ccee__pld_horario') }} as p
left join {{ ref('dim_submercado') }} as s on s.nome_ccee = p.submercado
