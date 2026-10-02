{#
  Fato: carga horária do ONS por submercado. Grão: (submercado, hora UTC). 937.796 linhas.

  Particionada por MÊS em `instante_utc` e clusterizada por submercado. Mensal e não diária porque
  o BigQuery limita a 10.000 partições por tabela (2000 a hoje são 9.772 dias) e, segundo fontes
  secundárias, a 4.000 partições modificadas por job, e um `dbt run` completo é um job só; mensal
  são 322 partições. Os valores nulos (dias inteiros sem dado de 2013 a 2015) ficam: tratar é papel
  dos testes da Sprint 3.
#}
{{
    config(
        partition_by={'field': 'instante_utc', 'data_type': 'timestamp', 'granularity': 'month'},
        cluster_by=['codigo_submercado'],
    )
}}

select
    id_subsistema as codigo_submercado,
    instante_utc,
    carga_mwmed,
    _carregado_em
from {{ ref('stg_ons__curva_carga') }}
