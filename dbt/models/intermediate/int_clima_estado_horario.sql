{#
  Temperatura por estado e hora UTC: primeiro passo da agregação em dois passos (premissas.md).

  Média das estações do estado que têm dado naquela hora (tolerante a falhas: uma estação sem
  medição não anula as outras). A grade é COMPLETA (todos os estados x todas as horas do período do
  INMET), então uma hora em que o estado inteiro ficou sem dado aparece como linha. Nesse caso a
  temperatura é a da última hora válida do próprio estado, até 3 horas antes (`temperatura_imputada`).
  Isso quase nunca acontece (de 2021 a ago/2026, 4 horas no DF, 9 em GO, 4 em MG e 4 em MS, de
  49.656), então não vale uma imputação mais elaborada (como o perfil típico do dia).
#}
with limites as (

    select
        min(instante_utc) as inicio,
        max(instante_utc) as fim
    from {{ ref('stg_inmet__estacoes_horario') }}

),

horas as (

    select t.instante_utc
    from {{ ref('dim_tempo') }} as t
    cross join limites as l
    where t.instante_utc between l.inicio and l.fim

),

estados as (

    select distinct uf
    from {{ ref('dim_estacao') }}

),

observacoes as (

    select
        uf,
        instante_utc,
        avg(temperatura_c) as temperatura_media_c,
        count(temperatura_c) as n_estacoes_com_dado
    from {{ ref('stg_inmet__estacoes_horario') }}
    group by uf, instante_utc

),

grade as (

    select
        e.uf,
        h.instante_utc,
        o.temperatura_media_c,
        coalesce(o.n_estacoes_com_dado, 0) as n_estacoes_com_dado
    from estados as e
    cross join horas as h
    left join observacoes as o
        on o.uf = e.uf
        and o.instante_utc = h.instante_utc

),

com_ultima_valida as (

    select
        *,
        last_value(temperatura_media_c ignore nulls) over (
            partition by uf
            order by instante_utc
            rows between 3 preceding and 1 preceding
        ) as ultima_valida_c
    from grade

)

select
    uf,
    instante_utc,
    coalesce(temperatura_media_c, ultima_valida_c) as temperatura_c,
    temperatura_media_c is null and ultima_valida_c is not null as temperatura_imputada,
    n_estacoes_com_dado
from com_ultima_valida
