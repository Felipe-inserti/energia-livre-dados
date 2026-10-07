{{ config(severity='error') }}
-- `mes_incompleto` é definido pela DATA: só o mês corrente (e nenhum posterior) é incompleto. Um mês
-- passado nunca pode estar marcado, mesmo com lacuna de dados (isso é cobertura, não mês incompleto).
select codigo_submercado, mes, mes_incompleto
from {{ ref('fct_carga_mensal') }}
where mes_incompleto != (mes >= date_trunc(current_date('America/Sao_Paulo'), month))
