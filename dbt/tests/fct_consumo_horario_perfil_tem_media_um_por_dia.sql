{{ config(severity='error') }}
-- O perfil da loja é normalizado para média 1 em CADA dia local (premissas.md, seção 2): é isso que faz a
-- média diária da curva ser k × L_d. Um dia com média diferente de 1 indica horas faltando ou perfil errado.
select
    data_local,
    count(*) as horas,
    avg(perfil) as perfil_medio
from {{ ref('fct_consumo_horario') }}
group by data_local
having count(*) != 24 or abs(avg(perfil) - 1) > 1e-9
