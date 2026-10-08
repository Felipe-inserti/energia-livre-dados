{{ config(severity='error') }}
-- A reconstrução do tipo III só existe de `inicio_reconstrucao_tipo3` até o mês anterior a
-- `inicio_api_carga`; antes disso nada é inventado; de 2018 em diante a série reconstruída é a medida.
select codigo_submercado, mes, ajuste_tipo3_reconstruido_status, ajuste_tipo3_reconstruido_mwmed,
    carga_ajustada_reconstruida_mwmed, carga_ajustada_mwmed
from {{ ref('fct_carga_mensal') }}
where
    (ajuste_tipo3_reconstruido_status = 'reconstruido_carga_mensal'
        and (mes < date '{{ var("inicio_reconstrucao_tipo3") }}' or mes >= date '{{ var("inicio_api_carga") }}'
            or ajuste_tipo3_reconstruido_mwmed <= 0))
    or (mes >= date '{{ var("inicio_reconstrucao_tipo3") }}' and mes < date '{{ var("inicio_api_carga") }}'
        and ajuste_tipo3_reconstruido_status != 'reconstruido_carga_mensal')
    -- antes da reconstrução: não disponível, sem número
    or (mes < date '{{ var("inicio_reconstrucao_tipo3") }}'
        and (ajuste_tipo3_reconstruido_status != 'nao_disponivel'
            or ajuste_tipo3_reconstruido_mwmed is not null or carga_ajustada_reconstruida_mwmed is not null))
    -- a partir da API a série reconstruída é exatamente a ajustada medida
    or (mes >= date '{{ var("inicio_api_carga") }}'
        and (carga_ajustada_reconstruida_mwmed is distinct from carga_ajustada_mwmed))
    -- a partir de 2015 há série
    or (mes >= date '{{ var("inicio_reconstrucao_tipo3") }}' and carga_ajustada_reconstruida_mwmed is null)
