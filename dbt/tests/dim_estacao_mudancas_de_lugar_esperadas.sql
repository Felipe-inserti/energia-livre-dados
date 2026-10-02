{{ config(severity='warn') }}
-- Só duas estações mudaram de lugar nos arquivos de 2021 a 2026: A042 Brazlândia (~9,5 km, em
-- 2026) e A704 Três Lagoas (~1,3 km, em 2023). O teste AVISA (não falha) se outra estação passar a
-- mudar de lugar, ou se uma dessas deixar de aparecer: mudar de lugar quebra a continuidade da série.
with moveram as (

    select estacao_codigo, deslocamento_m
    from {{ ref('dim_estacao') }}
    where mudou_de_lugar

),

esperadas as (

    select codigo as estacao_codigo
    from unnest(['A042', 'A704']) as codigo

)

select 'mudou e não era esperada' as problema, estacao_codigo, deslocamento_m
from moveram
where estacao_codigo not in (select estacao_codigo from esperadas)

union all

select 'era esperada e não mudou', estacao_codigo, null
from esperadas
where estacao_codigo not in (select estacao_codigo from moveram)
