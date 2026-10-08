{{ config(severity='warn') }}
-- Em 2018 o tipo III é medido pelas duas fontes: (Carga Mensal - curva) deve ficar perto de
-- (API líquida - curva). Erro absoluto médio acima de 1% da curva, por submercado, é aviso.
-- Medido em 07/10/2026: SE 0,19%, NE 0,11%, N 0,28%, S 0,62% (2018-2020).
select codigo_submercado, avg(abs(cm.carga_mensal_ons_mwmed - a.api_liquida_mwmed) / m.carga_original_mwmed) as erro_medio
from {{ ref('carga_mensal_ons') }} as cm
inner join {{ ref('ajuste_definicao_carga') }} as a using (mes, codigo_submercado)
inner join {{ ref('fct_carga_mensal') }} as m using (mes, codigo_submercado)
where cast(cm.mes as date) >= date '2018-01-01' and cast(cm.mes as date) < date '2019-01-01'
group by codigo_submercado
having avg(abs(cm.carga_mensal_ons_mwmed - a.api_liquida_mwmed) / m.carga_original_mwmed) > 0.01
