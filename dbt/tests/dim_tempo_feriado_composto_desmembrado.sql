-- 2000-04-21 tem dois feriados (Sexta-feira Santa e Tiradentes) numa linha só no raw. A dim_tempo
-- os desmembra: qtd_feriados = 2 e os dois nomes em nomes_feriado.
with dia as (

    select qtd_feriados, nomes_feriado, tipo_dia
    from {{ ref('dim_tempo') }}
    where data_local = date '2000-04-21' and hora_local = 12

)

select 'dia ausente' as problema from (select count(*) as n from dia) where n != 1

union all

select 'feriados mal desmembrados'
from dia
where qtd_feriados != 2
    or 'Sexta-feira Santa' not in unnest(nomes_feriado)
    or 'Tiradentes' not in unnest(nomes_feriado)
    or tipo_dia != 'domingo_feriado'
