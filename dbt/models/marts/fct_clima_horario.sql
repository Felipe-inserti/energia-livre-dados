{#
  Fato: medições horárias das estações do INMET. Grão: (estação, hora UTC). 1.837.272 linhas.

  Fica no grão natural (estação x hora), com as 17 medidas. A temperatura agregada por estado e por
  submercado (a agregação em dois passos) vive nos modelos intermediários int_clima_*. O `uf` é uma
  cópia do atributo da dim_estacao, guardada aqui para clusterizar e filtrar sem junção (um teste
  confere que ele bate com a dimensão). Particionada por mês e clusterizada por UF e estação.
#}
{{
    config(
        partition_by={'field': 'instante_utc', 'data_type': 'timestamp', 'granularity': 'month'},
        cluster_by=['uf', 'estacao_codigo'],
    )
}}

select
    estacao_codigo,
    uf,
    instante_utc,
    precipitacao_mm,
    pressao_mb,
    pressao_max_mb,
    pressao_min_mb,
    radiacao_kj_m2,
    temperatura_c,
    temperatura_orvalho_c,
    temperatura_max_c,
    temperatura_min_c,
    temperatura_orvalho_max_c,
    temperatura_orvalho_min_c,
    umidade_max_pct,
    umidade_min_pct,
    umidade_pct,
    vento_direcao_graus,
    vento_rajada_ms,
    vento_velocidade_ms,
    _carregado_em
from {{ ref('stg_inmet__estacoes_horario') }}
