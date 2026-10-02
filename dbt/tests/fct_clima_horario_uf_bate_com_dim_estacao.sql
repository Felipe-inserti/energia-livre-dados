-- O `uf` do fato é uma cópia do atributo da dim_estacao (guardada para clusterizar sem junção).
-- Qualquer estação em que os dois divergem aparece aqui.
select distinct
    f.estacao_codigo,
    f.uf as uf_no_fato,
    d.uf as uf_na_dimensao
from {{ ref('fct_clima_horario') }} as f
left join {{ ref('dim_estacao') }} as d using (estacao_codigo)
where d.uf is null
    or f.uf != d.uf
