{{ config(severity='error') }}
-- Temperatura do ar das 37 estações do SE/CO entre `temperatura_minima_c` e `temperatura_maxima_c`.
-- `error`: sentinela (-9999) ou sensor com defeito distorce a média por estado. Observado em
-- 2021-2026: de -4,7 a 42,7 °C; a faixa tem folga para o frio de serra e o calor de onda.
select estacao_codigo, instante_utc, temperatura_c
from {{ ref('fct_clima_horario') }}
where temperatura_c < {{ var('temperatura_minima_c') }}
    or temperatura_c > {{ var('temperatura_maxima_c') }}
