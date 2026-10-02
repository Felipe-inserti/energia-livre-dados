{#
  Consumo mensal por ramo de atividade (CCEE). É um agregado mensal, sem hora nem fuso: `mes` é o
  primeiro dia do mês. A unidade das colunas de consumo ainda está por confirmar (ver
  docs/fontes.md).
#}
with raw as (

    select
        parse_date('%Y%m', mes_referencia) as mes,
        ramo_atividade,
        cast(nullif(consumo_cl_esp_acl, '') as float64) as consumo_cl_esp_acl,
        cast(nullif(consumo_autop_acl, '') as float64) as consumo_autop_acl,
        cast(nullif(consumo_ponto_conexao_cl_esp_acl, '') as float64) as consumo_ponto_conexao_cl_esp_acl,
        cast(nullif(consumo_ponto_conexao_autop_acl, '') as float64) as consumo_ponto_conexao_autop_acl,
        _arquivo_origem,
        _carregado_em
    from {{ source('raw', 'ccee_consumo_ramo_atividade') }}

)

select *
from raw
qualify row_number() over (
    partition by mes, ramo_atividade
    order by _carregado_em desc
) = 1
