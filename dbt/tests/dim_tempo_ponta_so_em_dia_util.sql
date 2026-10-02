-- Horário de ponta: 3 horas por dia útil (segunda a sexta, fora dos feriados da ANEEL) e nenhuma
-- hora nos demais dias. Os dias das pontas do intervalo ficam de fora (a grade UTC os corta).
select
    data_local,
    count(*) as horas,
    countif(eh_horario_ponta) as horas_de_ponta,
    logical_and(not eh_feriado_aneel and dia_da_semana between 1 and 5) as dia_util_aneel
from {{ ref('dim_tempo') }}
where data_local > date '{{ var("data_inicio_dim_tempo") }}'
    and data_local < date '{{ var("data_fim_dim_tempo") }}'
group by data_local
having (
        logical_and(not eh_feriado_aneel and dia_da_semana between 1 and 5)
        and countif(eh_horario_ponta) != {{ var('horas_de_ponta') }}
    )
    or (
        not logical_and(not eh_feriado_aneel and dia_da_semana between 1 and 5)
        and countif(eh_horario_ponta) != 0
    )
