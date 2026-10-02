-- Sem buracos nem repetições: cada hora UTC está exatamente 1 hora depois da anterior.
select
    instante_utc,
    anterior
from (
    select
        instante_utc,
        lag(instante_utc) over (order by instante_utc) as anterior
    from {{ ref('dim_tempo') }}
)
where anterior is not null
    and timestamp_diff(instante_utc, anterior, hour) != 1
