-- Todo par (código, nome) de subsistema que existe no staging do ONS está coberto pela dimensão.
-- O SE tem dois nomes (SUDESTE até 2025, SUDESTE/CENTRO-OESTE em 2026); um nome novo faz o teste falhar.
select distinct
    s.id_subsistema,
    s.nome_subsistema
from {{ ref('stg_ons__curva_carga') }} as s
left join {{ ref('dim_submercado') }} as d on d.codigo_submercado = s.id_subsistema
where d.codigo_submercado is null
    or s.nome_subsistema not in unnest(d.nomes_ons)
