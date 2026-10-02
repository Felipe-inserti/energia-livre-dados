-- O fct_pld_semanal cobre as 8.784 horas de 2020 em cada submercado, e o PLD médio de 2020 do
-- SUDESTE ponderado pelas horas de cada semana (média simples dos 3 patamares) é R$ 178,03/MWh: o
-- número que sustenta o preço de contrato de 2021 (docs/premissas.md e docs/fontes.md).
with limites as (

    select
        timestamp('2020-01-01', 'America/Sao_Paulo') as inicio,
        timestamp('2021-01-01', 'America/Sao_Paulo') as fim

),

semanas as (

    select
        s.codigo_submercado,
        s.inicio_semana_utc,
        avg(s.pld_rs_mwh) as pld_medio_dos_patamares,
        timestamp_diff(
            least(any_value(s.fim_semana_utc), any_value(l.fim)),
            greatest(s.inicio_semana_utc, any_value(l.inicio)),
            hour
        ) as horas_em_2020
    from {{ ref('fct_pld_semanal') }} as s
    cross join limites as l
    where s.fim_semana_utc > l.inicio
        and s.inicio_semana_utc < l.fim
    group by s.codigo_submercado, s.inicio_semana_utc

),

resumo as (

    select
        codigo_submercado,
        sum(horas_em_2020) as horas,
        sum(pld_medio_dos_patamares * horas_em_2020) / sum(horas_em_2020) as pld_medio_2020
    from semanas
    group by codigo_submercado

)

select *
from resumo
where horas != 8784
    or (codigo_submercado = 'SE' and abs(pld_medio_2020 - 178.03) > 0.005)
