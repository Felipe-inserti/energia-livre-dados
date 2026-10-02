-- A grade do int_clima_estado_horario é completa: cada estado tem uma linha por hora do período do
-- INMET, sem buracos (é isso que faz uma hora sem dado aparecer como linha).
select
    uf,
    count(*) as linhas,
    timestamp_diff(max(instante_utc), min(instante_utc), hour) + 1 as horas_esperadas
from {{ ref('int_clima_estado_horario') }}
group by uf
having count(*) != timestamp_diff(max(instante_utc), min(instante_utc), hour) + 1
