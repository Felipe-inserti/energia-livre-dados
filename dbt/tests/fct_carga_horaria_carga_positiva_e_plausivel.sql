{{ config(severity='error') }}
-- Carga horária não nula tem de ser maior que zero e menor que o teto de plausibilidade (variável
-- `carga_maxima_mwmed`, por subsistema). `error`: carga zero ou absurda contamina a média mensal que
-- alimenta a previsão. O 0,0 do S em 2018-11-04 00:00 NÃO precisa de exceção aqui: é uma hora local
-- que não existe e o staging a descarta (o teste `ons_descarta_so_horas_conhecidas` cuida dele, no
-- raw). Os nulos são tratados no teste `fct_carga_horaria_nulos_so_nos_dias_conhecidos`.
select codigo_submercado, instante_utc, carga_mwmed
from {{ ref('fct_carga_horaria') }}
where carga_mwmed <= 0
    or carga_mwmed > {{ var('carga_maxima_mwmed') }}
