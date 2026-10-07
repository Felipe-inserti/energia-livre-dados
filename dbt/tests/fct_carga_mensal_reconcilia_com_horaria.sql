{{ config(severity='error') }}
-- A média mensal tem de ser a média das horas VÁLIDAS da carga horária (soma / horas válidas), mês a
-- mês e por submercado, inclusive nos meses com lacuna. Dividir pelas horas esperadas, que é o erro
-- que este teste existe para pegar, subestimaria o mês em ~3% (2013-12, 2014-02 e 2015-04).
-- Pega também mês duplicado, fuso errado na virada do mês e hora perdida. Tolerância de 1e-6 MWmed.
with horaria as (

    select
        codigo_submercado,
        date_trunc(date(instante_utc, 'America/Sao_Paulo'), month) as mes,
        sum(carga_mwmed) as soma,
        count(carga_mwmed) as validas
    from {{ ref('fct_carga_horaria') }}
    group by codigo_submercado, mes

)

select
    codigo_submercado,
    mes,
    m.carga_original_mwmed,
    h.soma / h.validas as media_das_horas_validas,
    m.horas_validas,
    h.validas
from {{ ref('fct_carga_mensal') }} as m
full outer join horaria as h using (codigo_submercado, mes)
where m.horas_validas != h.validas
    or abs(m.carga_original_mwmed - h.soma / h.validas) > 1e-6
    or m.codigo_submercado is null
    or h.codigo_submercado is null
