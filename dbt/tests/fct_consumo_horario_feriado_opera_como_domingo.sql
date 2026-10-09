{{ config(severity='error') }}
-- Feriado nacional opera como domingo: aberta das 8h às 20h (horas 8 a 19), inclusive o que cai num sábado
-- ou numa sexta. Três checagens: (1) todo feriado da dim_tempo é `domingo_feriado` na curva; (2) nesse tipo de
-- dia a loja abre exatamente nas horas 8 a 19; (3) datas conhecidas: 2022-01-01 (sábado) e 2020-12-25
-- (sexta) abrem às 8h e não às 7h; a segunda 2022-01-03 abre às 7h.
select c.data_local, c.hora_local, 'feriado fora de domingo_feriado' as problema
from {{ ref('fct_consumo_horario') }} as c
inner join {{ ref('dim_tempo') }} as t on t.instante_utc = c.instante_utc
where t.eh_feriado and c.tipo_dia != 'domingo_feriado'

union all
select data_local, hora_local, 'horário de domingo errado'
from {{ ref('fct_consumo_horario') }}
where tipo_dia = 'domingo_feriado' and loja_aberta != (hora_local between 8 and 19)

union all
select data_local, hora_local, 'data conhecida errada'
from {{ ref('fct_consumo_horario') }}
where (data_local in (date '2022-01-01', date '2020-12-25') and hora_local in (7, 8)
        and loja_aberta != (hora_local = 8))
    or (data_local = date '2022-01-03' and hora_local = 7 and not loja_aberta)
