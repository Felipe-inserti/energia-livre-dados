{{ config(severity='error') }}
-- O PLD horário tem de ficar entre o piso e o TETO HORÁRIO do ano (seed `pld_limites`, ANEEL). Usa o
-- teto horário e não o estrutural: em 2021 o PLD horário chegou a 1.128,72, acima do estrutural
-- (583,88). `error` porque um preço fora do limite regulatório é dado corrompido (ou regra nova que
-- precisa ser entendida antes de o contrato usar o preço). O ano é o da data LOCAL da hora.
-- Devolve as linhas fora da faixa e também as horas de um ano que não tem limite no seed.
with pld as (

    select
        codigo_submercado,
        instante_utc,
        pld_rs_mwh,
        extract(year from datetime(instante_utc, 'America/Sao_Paulo')) as ano
    from {{ ref('fct_pld_horario') }}

)

select
    pld.codigo_submercado,
    pld.instante_utc,
    pld.pld_rs_mwh,
    pld.ano,
    limites.pld_min,
    limites.pld_max_horario,
    case
        when limites.ano is null then 'ano sem limite no seed'
        when pld.pld_rs_mwh < limites.pld_min - {{ var('pld_tolerancia_rs') }} then 'abaixo do piso'
        else 'acima do teto horário'
    end as problema
from pld
left join {{ ref('pld_limites') }} as limites on limites.ano = pld.ano
where limites.ano is null
    or pld.pld_rs_mwh < limites.pld_min - {{ var('pld_tolerancia_rs') }}
    or pld.pld_rs_mwh > limites.pld_max_horario + {{ var('pld_tolerancia_rs') }}
