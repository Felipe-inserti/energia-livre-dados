{{ config(severity='error') }}
-- De 2021-01 ao mês corrente, um mês por linha, sem pular nenhum.
select count(*) as linhas, date_diff(max(mes), min(mes), month) + 1 as meses_esperados, min(mes) as primeiro
from {{ ref('fct_pld_ponderado_mensal') }}
having count(*) != date_diff(max(mes), min(mes), month) + 1 or min(mes) != date '2021-01-01'
