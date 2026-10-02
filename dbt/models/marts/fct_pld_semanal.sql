{#
  Fato: PLD histórico semanal por patamar (2001-2020). Grão: (submercado, semana, ordem do preço),
  3 linhas por semana. 12.312 linhas, sem partição (é pequena demais para valer a pena).

  Acrescenta o fim de cada semana (o início da seguinte; a última dura 7 dias) e as horas reais
  dela, que contam o horário de verão (uma semana pode ter 167 ou 169 horas). O patamar não é
  identificável; `ordem_preco_na_semana` só ordena os 3 preços da semana. Serve ao preço de
  contrato de 2021 (PLD médio de 2020, ponderado pelas horas de cada semana).
#}
with semanas as (

    select distinct
        submercado,
        data_inicio_semana,
        inicio_semana_utc
    from {{ ref('stg_ccee__pld_semanal') }}

),

com_fim as (

    select
        *,
        coalesce(
            lead(inicio_semana_utc) over (partition by submercado order by inicio_semana_utc),
            timestamp_add(inicio_semana_utc, interval 7 day)
        ) as fim_semana_utc
    from semanas

)

select
    d.codigo_submercado,
    p.data_inicio_semana,
    p.inicio_semana_utc,
    f.fim_semana_utc,
    timestamp_diff(f.fim_semana_utc, p.inicio_semana_utc, hour) as horas_na_semana,
    p.ordem_preco_na_semana,
    p.pld_rs_mwh
from {{ ref('stg_ccee__pld_semanal') }} as p
inner join com_fim as f
    on f.submercado = p.submercado
    and f.inicio_semana_utc = p.inicio_semana_utc
left join {{ ref('dim_submercado') }} as d on d.nome_ccee = p.submercado
