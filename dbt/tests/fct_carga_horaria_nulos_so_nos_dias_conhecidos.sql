{{ config(severity='error') }}
-- Carga nula só é aceita nos três dias inteiros sem dado já investigados (docs/fontes.md): 2013-12-01
-- (4 subsistemas, 96 nulos), 2014-02-01 e 2015-04-09 (NE, S e SE; o N não tem linha nesses dias).
-- Qualquer nulo fora dessas datas locais é problema novo na fonte e falha. O teste par
-- `fct_carga_horaria_excecoes_de_nulos_ainda_existem` (warn) avisa quando uma exceção fica velha.
select codigo_submercado, instante_utc, date(instante_utc, 'America/Sao_Paulo') as data_local
from {{ ref('fct_carga_horaria') }}
where carga_mwmed is null
    and date(instante_utc, 'America/Sao_Paulo') not in (
        date '2013-12-01', date '2014-02-01', date '2015-04-09'
    )
