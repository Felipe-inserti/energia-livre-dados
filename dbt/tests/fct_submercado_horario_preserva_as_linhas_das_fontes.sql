-- A junção completa não pode perder nem inventar valores: cada coluna do fct_submercado_horario tem
-- tantas linhas não nulas quanto a sua fonte.
with contagens as (

    select
        (select count(*) from {{ ref('fct_submercado_horario') }} where carga_mwmed is not null)
            as carga_no_fato,
        (select count(*) from {{ ref('fct_carga_horaria') }} where carga_mwmed is not null)
            as carga_na_fonte,
        (select count(*) from {{ ref('fct_submercado_horario') }} where pld_rs_mwh is not null)
            as pld_no_fato,
        (select count(*) from {{ ref('fct_pld_horario') }} where pld_rs_mwh is not null)
            as pld_na_fonte,
        (select count(*) from {{ ref('fct_submercado_horario') }} where temperatura_c is not null)
            as clima_no_fato,
        (select count(*) from {{ ref('int_clima_submercado_horario') }} where temperatura_c is not null)
            as clima_na_fonte

)

select *
from contagens
where carga_no_fato != carga_na_fonte
    or pld_no_fato != pld_na_fonte
    or clima_no_fato != clima_na_fonte
