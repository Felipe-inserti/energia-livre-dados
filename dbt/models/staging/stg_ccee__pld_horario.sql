{#
  PLD horário por submercado, em UTC.

  O raw não tem timestamp: o instante local (horário de Brasília) se monta com mês, dia e hora.
  O layout muda entre 2024 e 2025 (`01` contra `1`), então `dia` e `hora` entram como número.
  O preço é NUMERIC (valor monetário exato; FLOAT64 acumularia erro de arredondamento nos custos
  do backtest). Não descarta nenhuma linha: 2021+ não tem horário de verão e o teste de contagem
  garante que o staging tem as mesmas linhas do raw.
#}
with raw as (

    select
        submercado,
        datetime(
            cast(substr(mes_referencia, 1, 4) as int64),
            cast(substr(mes_referencia, 5, 2) as int64),
            cast(dia as int64),
            cast(hora as int64),
            0,
            0
        ) as instante_local,
        cast(periodo_comercializacao as int64) as periodo_comercializacao,
        cast(nullif(pld_hora, '') as numeric) as pld_rs_mwh,
        _arquivo_origem,
        _carregado_em
    from {{ source('raw', 'ccee_pld_horario') }}

),

com_utc as (

    select
        *,
        timestamp(instante_local, 'America/Sao_Paulo') as instante_utc
    from raw

),

deduplicada as (

    select *
    from com_utc
    qualify row_number() over (
        partition by submercado, instante_utc
        order by _carregado_em desc
    ) = 1

)

select
    submercado,
    instante_utc,
    periodo_comercializacao,
    pld_rs_mwh,
    _arquivo_origem,
    _carregado_em
from deduplicada
