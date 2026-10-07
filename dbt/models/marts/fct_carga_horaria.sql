{#
  Fato: carga horária do ONS por submercado. Grão: (submercado, hora UTC). 937.796 linhas.

  Particionada por MÊS em `instante_utc` e clusterizada por submercado. Mensal e não diária porque
  o BigQuery limita a 10.000 partições por tabela (2000 a hoje são 9.772 dias) e, segundo fontes
  secundárias, a 4.000 partições modificadas por job, e um `dbt run` completo é um job só; mensal
  são 322 partições. Os valores nulos (dias inteiros sem dado de 2013 a 2015) ficam: tratar é papel
  dos testes da Sprint 3.

  MATERIALIZAÇÃO (Sprint 4, decidida com números medidos; ver docs/decisoes.md): `table`. O
  incremental (insert_overwrite das partições da janela, igual ao staging) FATURA MAIS que o `table`
  neste tamanho: 31,5 MB contra 26,2 MB por execução, porque o MERGE paga o piso de 10 MiB duas vezes
  (tabela temporária e destino) e mais 10 MiB da própria tabela temporária. Só reduz os bytes
  PROCESSADOS (25,8 MB -> 0,3 a 0,5 MB). A alternativa continua pronta e testada: troca-se com
  `--vars '{fct_carga_materializacao: incremental}'`, que passa a valer a pena quando a reconstrução
  completa passar de ~31,5 MB faturados (o fato cresce ~3,7% ao ano: não antes de ~5 anos).
  A janela incremental, se usada, vem das mesmas vars do staging (macro `janela_incremental`).
#}
{{
    config(
        materialized=var('fct_carga_materializacao', 'table'),
        incremental_strategy='insert_overwrite',
        partitions=janela_particoes(),
        on_schema_change='fail',
        partition_by={'field': 'instante_utc', 'data_type': 'timestamp', 'granularity': 'month'},
        cluster_by=['codigo_submercado'],
    )
}}
{% set janela = janela_incremental() if is_incremental() else none %}

select
    id_subsistema as codigo_submercado,
    instante_utc,
    carga_mwmed,
    _carregado_em
from {{ ref('stg_ons__curva_carga') }}
{% if is_incremental() %}
where instante_utc >= timestamp('{{ janela.utc_inicio }}')
    and instante_utc < timestamp('{{ janela.utc_fim }}')
{% endif %}
