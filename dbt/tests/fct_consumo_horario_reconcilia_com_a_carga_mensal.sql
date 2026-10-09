{{ config(severity='error') }}
-- Cada mês com todos os dias na curva tem de dar: consumo médio por hora / k = carga ajustada do mês. É o elo que
-- liga a previsão mensal à curva (prever a carga mensal do SE/CO é prever o consumo, a menos do k). A
-- tolerância é 1 kW (1,01e-3 MWmed): a carga original e o ajuste saem arredondados a 3 casas no mart mensal.
-- Um erro de verdade (dia perdido, fuso, ajuste fora do mês) é ordens de grandeza maior.
with mensal as (

    select
        date_trunc(data_local, month) as mes,
        count(*) as horas,
        sum(consumo_mwh) / count(*) / {{ var('k_consumo') }} as carga_da_curva_mwmed
    from {{ ref('fct_consumo_horario') }}
    group by mes

),

grade as (

    select date_trunc(data_local, month) as mes, count(*) as horas_esperadas
    from {{ ref('dim_tempo') }}
    group by mes

)

select
    m.mes,
    m.carga_da_curva_mwmed,
    c.carga_ajustada_mwmed,
    abs(m.carga_da_curva_mwmed - c.carga_ajustada_mwmed) as diferenca_mwmed
from mensal as m
inner join grade as g on g.mes = m.mes and g.horas_esperadas = m.horas
inner join {{ ref('fct_carga_mensal') }} as c on c.mes = m.mes and c.codigo_submercado = 'SE'
where abs(m.carga_da_curva_mwmed - c.carga_ajustada_mwmed) > 1.01e-3
