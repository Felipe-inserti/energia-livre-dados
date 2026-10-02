-- O horário de verão acabou no Brasil em fevereiro de 2019: depois disso o deslocamento é sempre -3.
-- (O tzdata do BigQuery tem esse histórico; este teste pega um fuso errado ou desatualizado.)
select
    instante_utc,
    data_local,
    deslocamento_utc_horas
from {{ ref('dim_tempo') }}
where eh_horario_verao
    and data_local > date '2019-02-17'
