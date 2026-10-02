-- Todo ano da dim_tempo tem feriados. Protege contra estender o intervalo além dos anos que o raw de
-- feriados cobre (2000 a 2030): um ano sem feriados viraria dias úteis em silêncio.
-- Da lista da ANEEL, são 11 por ano; em 2000 são 10 porque a Sexta-feira Santa caiu em 21 de abril.
select
    ano,
    count(distinct if(eh_feriado, data_local, null)) as feriados,
    count(distinct if(eh_feriado_aneel, data_local, null)) as feriados_aneel
from {{ ref('dim_tempo') }}
-- as 2 primeiras horas UTC (2000-01-01 00:00Z e 01:00Z) são 31/12/1999 no relógio local (horário de
-- verão): a data local fora do intervalo configurado não conta
where data_local between date '{{ var("data_inicio_dim_tempo") }}' and date '{{ var("data_fim_dim_tempo") }}'
group by ano
having count(distinct if(eh_feriado, data_local, null)) < 8
    or (ano != 2000 and count(distinct if(eh_feriado_aneel, data_local, null)) != 11)
    or (ano = 2000 and count(distinct if(eh_feriado_aneel, data_local, null)) != 10)
