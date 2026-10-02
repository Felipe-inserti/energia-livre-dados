{#
  Dados horários das estações do INMET (37 estações do SE/CO), em UTC.

  O raw já está em UTC (`hora_utc`, como `0000 UTC`); aqui se monta o instante, convertem-se as
  medidas (texto com vírgula decimal) para FLOAT64 e renomeiam-se as colunas. Vazio vira NULL
  (cerca de 1,35% na temperatura; 5,9% em 2026). Não há sentinela -9999 nos dados.
  As medidas "_max_" e "_min_" são o máximo e o mínimo da hora anterior (campos "NA HORA ANT.").
#}
with raw as (

    select
        estacao_codigo,
        estacao_uf as uf,
        estacao_nome,
        {{ decimal_virgula('estacao_latitude') }} as latitude,
        {{ decimal_virgula('estacao_longitude') }} as longitude,
        parse_timestamp('%Y/%m/%d %H%M', concat(`data`, ' ', substr(hora_utc, 1, 4))) as instante_utc,
        {{ decimal_virgula('precipitacao_total_horario_mm') }} as precipitacao_mm,
        {{ decimal_virgula('pressao_atmosferica_ao_nivel_da_estacao_horaria_mb') }} as pressao_mb,
        {{ decimal_virgula('pressao_atmosferica_max_na_hora_ant_aut_mb') }} as pressao_max_mb,
        {{ decimal_virgula('pressao_atmosferica_min_na_hora_ant_aut_mb') }} as pressao_min_mb,
        {{ decimal_virgula('radiacao_global_kj_m2') }} as radiacao_kj_m2,
        {{ decimal_virgula('temperatura_do_ar_bulbo_seco_horaria_c') }} as temperatura_c,
        {{ decimal_virgula('temperatura_do_ponto_de_orvalho_c') }} as temperatura_orvalho_c,
        {{ decimal_virgula('temperatura_maxima_na_hora_ant_aut_c') }} as temperatura_max_c,
        {{ decimal_virgula('temperatura_minima_na_hora_ant_aut_c') }} as temperatura_min_c,
        {{ decimal_virgula('temperatura_orvalho_max_na_hora_ant_aut_c') }} as temperatura_orvalho_max_c,
        {{ decimal_virgula('temperatura_orvalho_min_na_hora_ant_aut_c') }} as temperatura_orvalho_min_c,
        {{ decimal_virgula('umidade_rel_max_na_hora_ant_aut') }} as umidade_max_pct,
        {{ decimal_virgula('umidade_rel_min_na_hora_ant_aut') }} as umidade_min_pct,
        {{ decimal_virgula('umidade_relativa_do_ar_horaria') }} as umidade_pct,
        {{ decimal_virgula('vento_direcao_horaria_gr_gr') }} as vento_direcao_graus,
        {{ decimal_virgula('vento_rajada_maxima_m_s') }} as vento_rajada_ms,
        {{ decimal_virgula('vento_velocidade_horaria_m_s') }} as vento_velocidade_ms,
        _arquivo_origem,
        _carregado_em
    from {{ source('raw', 'inmet_estacoes_horario') }}

)

select *
from raw
qualify row_number() over (
    partition by estacao_codigo, instante_utc
    order by _carregado_em desc
) = 1
