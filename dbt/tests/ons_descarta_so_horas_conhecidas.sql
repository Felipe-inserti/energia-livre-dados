-- O staging do ONS descarta as linhas cuja hora local NÃO EXISTE (o relógio salta de 00:00 para
-- 01:00 no início do horário de verão). Só são esperadas as 00:00 dos 5 dias conhecidos (2014 a
-- 2018, ver docs/fontes.md), com valor vazio ou 0,0. Qualquer outra hora inexistente indica um
-- problema novo na fonte: este teste devolve essas linhas (e falha se houver alguma).
with raw as (

    select
        id_subsistema,
        cast(din_instante as datetime) as instante_local,
        cast(nullif(val_cargaenergiahomwmed, '') as float64) as carga_mwmed
    from {{ source('raw', 'ons_curva_carga') }}

),

inexistentes as (

    select *
    from raw
    where datetime(timestamp(instante_local, 'America/Sao_Paulo'), 'America/Sao_Paulo')
        != instante_local

)

select *
from inexistentes
where instante_local not in (
        datetime '2014-10-19 00:00:00',
        datetime '2015-10-18 00:00:00',
        datetime '2016-10-16 00:00:00',
        datetime '2017-10-15 00:00:00',
        datetime '2018-11-04 00:00:00'
    )
    or coalesce(carga_mwmed, 0) != 0
