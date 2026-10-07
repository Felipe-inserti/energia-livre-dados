{{ config(severity='warn') }}
-- AVISO (não quebra o pipeline): mês fechado com cobertura menor que 100% que não está na lista
-- `meses_com_lacuna_conhecida` é lacuna nova (dados que o ONS ainda não publicou ou revisou). E o
-- contrário: mês da lista sem nenhuma lacuna em nenhum submercado é exceção velha, a retirar.
{% set conhecidas = var('meses_com_lacuna_conhecida') %}
select codigo_submercado, mes, cobertura, 'lacuna fora da lista' as motivo
from {{ ref('fct_carga_mensal') }}
where not mes_incompleto
    and cobertura < 1
    and mes not in (
        {%- for m in conhecidas %}date '{{ m }}'{{ ',' if not loop.last }}{% endfor %}
    )

union all

select cast(null as string), mes, max(cobertura), 'exceção sem lacuna'
from {{ ref('fct_carga_mensal') }}
where mes in (
        {%- for m in conhecidas %}date '{{ m }}'{{ ',' if not loop.last }}{% endfor %}
    )
group by mes
having min(cobertura) >= 1
