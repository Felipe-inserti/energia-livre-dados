{{ config(severity='error') }}
-- No mês em que a transição do tipo III termina, a diferença entre a carga líquida da API e a curva
-- tem de caber no ruído (|diferença| <= limiar). Confere o fim pelo lado dos DADOS (seed + curva),
-- sem usar as CTEs do mart, para pegar erro de implementação da regra. Só vale quando o fim vem da
-- regra (antes da quebra da MMGD); fim = quebra da MMGD significaria "nunca terminou" e já é
-- reprovado por `fct_carga_mensal_ajuste_so_onde_deve`.
select
    m.codigo_submercado,
    m.mes as fim_transicao,
    abs(a.api_liquida_mwmed - m.carga_original_mwmed) as dif,
    m.ajuste_tipo3_limiar_mwmed as limiar
from {{ ref('fct_carga_mensal') }} as m
inner join {{ ref('ajuste_definicao_carga') }} as a
    on a.codigo_submercado = m.codigo_submercado and cast(a.mes as date) = m.mes
where m.mes = m.ajuste_tipo3_fim_transicao
    and m.mes < date '{{ var("mes_quebra_mmgd") }}'
    and abs(a.api_liquida_mwmed - m.carga_original_mwmed) > m.ajuste_tipo3_limiar_mwmed
