{{ config(severity='error') }}
-- A API tem de ser coerente consigo mesma: global = líquida + MMGD (em MWmed, com folga de
-- arredondamento do seed, 4 casas). Se não fechar, o ajuste de MMGD e o de tipo III se misturam.
-- Mais: o seed tem de cobrir os 12 meses seguintes à quebra da MMGD em cada submercado, que é de onde
-- sai o fator r do mart.
select codigo_submercado, mes, api_global_mwmed, api_liquida_mwmed, api_mmgd_mwmed
from {{ ref('ajuste_definicao_carga') }}
where abs(api_global_mwmed - api_liquida_mwmed - api_mmgd_mwmed) > 0.001

union all

select codigo_submercado, cast(null as date), null, null, null
from {{ ref('ajuste_definicao_carga') }}
where status_mmgd = 'incorporado_na_curva'
group by codigo_submercado
having count(*) != 12
