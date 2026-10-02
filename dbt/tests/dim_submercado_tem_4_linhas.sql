-- Os 4 submercados do SIN (SE/CO, S, NE e N).
select linhas
from (select count(*) as linhas from {{ ref('dim_submercado') }})
where linhas != 4
