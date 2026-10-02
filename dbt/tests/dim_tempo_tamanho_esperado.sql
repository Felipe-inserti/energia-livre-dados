-- A dim_tempo tem uma linha por hora UTC do intervalo configurado nas variáveis do projeto
-- (2000-01-01 a 2030-12-31 = 11.323 dias x 24 = 271.752 linhas).
with esperado as (

    select
        (date_diff(date '{{ var("data_fim_dim_tempo") }}', date '{{ var("data_inicio_dim_tempo") }}', day) + 1) * 24
            as horas
),

obtido as (

    select count(*) as linhas from {{ ref('dim_tempo') }}

)

select esperado.horas, obtido.linhas
from esperado
cross join obtido
where esperado.horas != obtido.linhas
