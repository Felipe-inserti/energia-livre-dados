{#
  PLD histórico semanal (2001-2020): 3 linhas por semana e submercado, uma por patamar de carga.

  O arquivo NÃO identifica o patamar nem traz as horas de cada um, então este modelo não tenta
  deduplicar (as 3 linhas podem ser idênticas: patamares com o mesmo preço) nem inventa o nome do
  patamar. `ordem_preco_na_semana` (1 a 3, do menor ao maior preço) só dá uma ordem determinística
  dentro da semana. A semana começa em `data_inicio_semana` (horário de Brasília); a duração é o
  intervalo até a semana seguinte (a modelagem fica para o intermediate).
#}
with raw as (

    select
        submercado,
        date(
            cast(substr(mes_referencia, 1, 4) as int64),
            cast(substr(mes_referencia, 5, 2) as int64),
            cast(dia as int64)
        ) as data_inicio_semana,
        cast(periodo_comercializacao as int64) as periodo_comercializacao,
        cast(nullif(pld_hora, '') as numeric) as pld_rs_mwh,
        _arquivo_origem,
        _carregado_em
    from {{ source('raw', 'ccee_pld_semanal') }}

)

select
    submercado,
    data_inicio_semana,
    timestamp(datetime(data_inicio_semana), 'America/Sao_Paulo') as inicio_semana_utc,
    periodo_comercializacao,
    pld_rs_mwh,
    row_number() over (
        partition by submercado, data_inicio_semana
        order by pld_rs_mwh, _arquivo_origem
    ) as ordem_preco_na_semana,
    _arquivo_origem,
    _carregado_em
from raw
