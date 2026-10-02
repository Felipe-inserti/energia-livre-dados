-- As 37 estações selecionadas (ingestion/inmet.py, constante ESTACOES).
select estacoes
from (select count(*) as estacoes from {{ ref('dim_estacao') }})
where estacoes != 37
