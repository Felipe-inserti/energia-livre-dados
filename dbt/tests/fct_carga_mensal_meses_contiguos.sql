{{ config(severity='error') }}
-- Sem buraco: de 2000-01 ao mês corrente, todos os meses existem, e para os 4 submercados.
select
    codigo_submercado,
    min(mes) as primeiro,
    max(mes) as ultimo,
    count(*) as meses,
    date_diff(max(mes), min(mes), month) + 1 as meses_esperados
from {{ ref('fct_carga_mensal') }}
group by codigo_submercado
having min(mes) != date '2000-01-01'
    or count(*) != date_diff(max(mes), min(mes), month) + 1
