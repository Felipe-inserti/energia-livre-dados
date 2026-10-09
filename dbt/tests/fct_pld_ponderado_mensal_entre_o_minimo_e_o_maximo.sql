{{ config(severity='error') }}
-- Uma média ponderada com pesos positivos fica entre o menor e o maior PLD horário do mês, e a razão
-- ponderado/simples não pode fugir de [0,8; 1,25] (um perfil de loja não muda o preço do mês em 25%). Pega
-- peso trocado de lugar ou junção que perde horas.
with faixa as (

    select
        date_trunc(date(instante_utc, 'America/Sao_Paulo'), month) as mes,
        min(cast(pld_rs_mwh as float64)) as pld_min,
        max(cast(pld_rs_mwh as float64)) as pld_max
    from {{ ref('fct_pld_horario') }}
    where codigo_submercado = 'SE'
    group by mes

)

select p.mes, p.pld_ponderado_rs_mwh, f.pld_min, f.pld_max, p.razao
from {{ ref('fct_pld_ponderado_mensal') }} as p
inner join faixa as f on f.mes = p.mes
where p.pld_ponderado_rs_mwh < f.pld_min - 1e-6
    or p.pld_ponderado_rs_mwh > f.pld_max + 1e-6
    or p.razao not between 0.8 and 1.25
