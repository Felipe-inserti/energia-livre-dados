{{ config(severity='warn') }}
-- Contraparte do teste de nulos: as exceções são uma lista fixa, e uma lista fixa envelhece. Se o ONS
-- revisar e preencher um desses dias, o número de nulos muda e este teste AVISA (não falha), para
-- eu tirar a data da lista. Esperado: 96, 72 e 72 nulos (240 no total).
with esperado as (

    select data_local, nulos_esperados
    from unnest([
        struct(date '2013-12-01' as data_local, 96 as nulos_esperados),
        struct(date '2014-02-01', 72),
        struct(date '2015-04-09', 72)
    ])

),

observado as (

    select date(instante_utc, 'America/Sao_Paulo') as data_local, count(*) as nulos
    from {{ ref('fct_carga_horaria') }}
    where carga_mwmed is null
    group by 1

)

select esperado.data_local, esperado.nulos_esperados, coalesce(observado.nulos, 0) as nulos_observados
from esperado
left join observado using (data_local)
where coalesce(observado.nulos, 0) != esperado.nulos_esperados
