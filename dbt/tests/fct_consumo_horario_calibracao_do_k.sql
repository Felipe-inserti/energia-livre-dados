{{ config(severity='error') }}
-- O consumo médio de 2020-01 a 2025-12 tem de ser os `consumo_medio_mwh_mes` (100 MWh/mês) da definição do
-- cliente. O k está CONGELADO no dbt_project.yml; se uma revisão do ONS ou do ajuste de definição afastar a média
-- em mais de 0,5%, o teste falha e a decisão é recalibrar o k de propósito (e registrar), não deixar passar.
-- Também exige os 72 meses completos: um mês faltando na curva falsearia a média.
with mensal as (

    select date_trunc(data_local, month) as mes, sum(consumo_mwh) as consumo_mwh
    from {{ ref('fct_consumo_horario') }}
    where data_local between date('{{ var('consumo_inicio') }}') and date('{{ var('consumo_calibracao_fim') }}')
    group by mes

)

select count(*) as meses, avg(consumo_mwh) as consumo_medio_mwh_mes
from mensal
having count(*) != 72
    or abs(avg(consumo_mwh) / {{ var('consumo_medio_mwh_mes') }} - 1) > 0.005
