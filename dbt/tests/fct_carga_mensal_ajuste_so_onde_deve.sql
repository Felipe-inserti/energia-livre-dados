{{ config(severity='error') }}
-- Cada ajuste só pode ser diferente de zero na janela em que foi medido, e a série ajustada só
-- existe onde os dois componentes existem. Impede um ajuste "vazando" para meses em que a curva já
-- traz o componente (dupla contagem) ou sendo inventado antes de 2018.
select
    codigo_submercado, mes, ajuste_tipo3_status, ajuste_tipo3_mwmed, ajuste_tipo3_limiar_mwmed,
    ajuste_tipo3_fim_transicao, ajuste_mmgd_status, ajuste_mmgd_mwmed
from {{ ref('fct_carga_mensal') }}
where
    -- a curva já traz o tipo III: ajuste zero
    (ajuste_tipo3_status = 'incorporado_na_curva' and ajuste_tipo3_mwmed != 0)
    -- a curva já traz a MMGD: ajuste zero
    or (mes >= date '{{ var("mes_quebra_mmgd") }}' and ajuste_mmgd_mwmed != 0)
    -- antes de 2018 o tipo III não existe como medida: nulo, nunca um número
    or (mes < date '{{ var("inicio_api_carga") }}'
        and (ajuste_tipo3_mwmed is not null or ajuste_tipo3_status != 'nao_disponivel'))
    or (mes >= date '{{ var("inicio_api_carga") }}' and ajuste_tipo3_status = 'nao_disponivel')
    -- MMGD zero por premissa antes de 2019-02
    or (ajuste_mmgd_status = 'zero_por_premissa' and ajuste_mmgd_mwmed != 0)
    -- tipo III medido antes da quebra tem de ser positivo (a API inclui o que a curva não inclui)
    or (ajuste_tipo3_status = 'medido' and ajuste_tipo3_mwmed <= 0)
    -- a transição só existe de 2021-03 até o mês do fim (todos os meses anteriores ao fim são
    -- transição, mesmo um mês isolado que por sorte caiu dentro do ruído)
    or (ajuste_tipo3_status = 'medido_transicao'
        and (mes < date '{{ var("mes_quebra_tipo3") }}' or mes >= ajuste_tipo3_fim_transicao))
    or (ajuste_tipo3_status = 'incorporado_na_curva' and mes < ajuste_tipo3_fim_transicao
        and mes >= date '{{ var("mes_quebra_tipo3") }}')
    -- o fim da transição vem antes do ano usado para medir o ruído (senão a regra estaria medindo
    -- o ruído com meses que ainda são transição) e depois da quebra; nunca "não terminou"
    or ajuste_tipo3_fim_transicao < date '{{ var("mes_quebra_tipo3") }}'
    or ajuste_tipo3_fim_transicao >= date '{{ var("ano_ruido_tipo3") }}-01-01'
    -- a série ajustada é nula exatamente quando o tipo III é nao_disponivel
    or ((carga_ajustada_mwmed is null) != (ajuste_tipo3_status = 'nao_disponivel'))
