{{ config(severity='warn') }}
-- Completude da temperatura por estação e ano (UTC): horas com valor sobre as horas esperadas, que
-- vão de 1º de janeiro até a última hora presente no ano (o ano parcial de 2026 não é cobrado até
-- dezembro). `warn`: a degradação de uma estação é problema da fonte e não pára o pipeline, mas as
-- médias por estado precisam ser lidas com cuidado. Limite = critério de seleção (95%). Em 2026
-- são esperadas 10 estações abaixo do limite (docs/fontes.md).
with por_estacao_ano as (

    select
        estacao_codigo,
        extract(year from instante_utc) as ano,
        countif(temperatura_c is not null) as horas_validas
    from {{ ref('fct_clima_horario') }}
    group by 1, 2

),

horas_do_ano as (

    select
        extract(year from instante_utc) as ano,
        timestamp_diff(
            max(instante_utc),
            timestamp(date(extract(year from min(instante_utc)), 1, 1)),
            hour
        ) + 1 as horas_esperadas
    from {{ ref('fct_clima_horario') }}
    group by 1

)

select
    e.estacao_codigo,
    e.ano,
    e.horas_validas,
    h.horas_esperadas,
    round(e.horas_validas / h.horas_esperadas, 4) as fracao_valida
from por_estacao_ano as e
inner join horas_do_ano as h using (ano)
where e.horas_validas / h.horas_esperadas < {{ var('completude_minima_inmet') }}
