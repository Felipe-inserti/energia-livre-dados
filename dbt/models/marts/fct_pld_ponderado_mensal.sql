{#
  Fato: PLD mensal do SUDESTE ponderado pelo consumo do supermercado. Grão: mês local. ~69 linhas.

  `PLDp_m = Σ_h consumo_h × PLD_h / Σ_h consumo_h` (docs/premissas.md, seção 4): é o preço de liquidação das
  diferenças do contrato modulado pela carga, e o histórico que a Sprint 5 (tarefa 5.7) reamostra. Fica ao
  lado do PLD médio SIMPLES do mesmo mês (`pld_medio_simples_rs_mwh`, média das horas) para medir quanto
  o perfil de consumo muda o preço. `razao` = ponderado / simples.

  Só meses de 2021 em diante (o PLD horário começa em 2021-01-01; antes só existe o semanal por patamar,
  `fct_pld_semanal`, sem ponderação possível por hora). `mes_completo` marca o mês com todas as horas do
  relógio local; o mês corrente vem com `false` e não deve entrar em histórico nem em backtest.
#}
with grade as (

    select
        date_trunc(data_local, month) as mes,
        count(*) as horas_esperadas
    from {{ ref('dim_tempo') }}
    group by mes

),

horas as (

    select
        date_trunc(c.data_local, month) as mes,
        c.consumo_mwh,
        cast(p.pld_rs_mwh as float64) as pld_rs_mwh
    from {{ ref('fct_consumo_horario') }} as c
    inner join {{ ref('fct_pld_horario') }} as p
        on p.instante_utc = c.instante_utc and p.codigo_submercado = 'SE'

)

select
    h.mes,
    count(*) as horas,
    g.horas_esperadas,
    count(*) = g.horas_esperadas as mes_completo,
    sum(h.consumo_mwh) as consumo_mwh,
    avg(h.pld_rs_mwh) as pld_medio_simples_rs_mwh,
    sum(h.consumo_mwh * h.pld_rs_mwh) / sum(h.consumo_mwh) as pld_ponderado_rs_mwh,
    sum(h.consumo_mwh * h.pld_rs_mwh) / sum(h.consumo_mwh) / avg(h.pld_rs_mwh) as razao
from horas as h
inner join grade as g on g.mes = h.mes
group by h.mes, g.horas_esperadas
