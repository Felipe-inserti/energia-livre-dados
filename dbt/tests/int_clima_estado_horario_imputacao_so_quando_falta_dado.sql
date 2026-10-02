-- A temperatura só é imputada quando o estado inteiro ficou sem dado na hora, e uma hora com dado
-- nunca fica sem temperatura.
select
    uf,
    instante_utc,
    temperatura_c,
    temperatura_imputada,
    n_estacoes_com_dado
from {{ ref('int_clima_estado_horario') }}
where (temperatura_imputada and n_estacoes_com_dado > 0)
    or (n_estacoes_com_dado > 0 and temperatura_c is null)
    or (not temperatura_imputada and n_estacoes_com_dado = 0 and temperatura_c is not null)
