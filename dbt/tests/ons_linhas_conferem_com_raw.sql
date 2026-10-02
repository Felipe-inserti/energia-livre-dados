-- Linhas do staging do ONS = linhas do raw menos as horas locais inexistentes descartadas.
-- (A deduplicação não remove nada hoje: a unicidade da chave é testada à parte.)
with raw as (

    select cast(din_instante as datetime) as instante_local
    from {{ source('raw', 'ons_curva_carga') }}

),

contagens as (

    select
        (select count(*) from raw) as no_raw,
        (
            select count(*)
            from raw
            where datetime(timestamp(instante_local, 'America/Sao_Paulo'), 'America/Sao_Paulo')
                != instante_local
        ) as descartadas,
        (select count(*) from {{ ref('stg_ons__curva_carga') }}) as no_staging

)

select *
from contagens
where no_raw - descartadas != no_staging
