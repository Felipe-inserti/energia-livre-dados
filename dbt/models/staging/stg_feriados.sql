{#
  Feriados nacionais (biblioteca `holidays`). Uma data com dois feriados vem numa linha só, com os
  nomes separados por "; " (2000-04-21 = "Sexta-feira Santa; Tiradentes"); desmembrar fica para a
  dim_tempo.
#}
with raw as (

    select
        cast(`data` as date) as data_feriado,
        nome as nome_feriado,
        _carregado_em
    from {{ source('raw', 'feriados') }}

)

select *
from raw
qualify row_number() over (
    partition by data_feriado
    order by _carregado_em desc
) = 1
