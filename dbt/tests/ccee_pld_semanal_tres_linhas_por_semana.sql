-- Cada semana de cada submercado tem exatamente 3 linhas (os 3 patamares de carga).
select
    submercado,
    data_inicio_semana,
    count(*) as linhas
from {{ ref('stg_ccee__pld_semanal') }}
group by submercado, data_inicio_semana
having count(*) != 3
