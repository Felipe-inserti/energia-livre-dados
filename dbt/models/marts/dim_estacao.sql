{#
  As 37 estações do INMET selecionadas, com o REGISTRO MAIS RECENTE dos metadados (UF, nome e
  coordenadas do arquivo mais novo). Cada linha do raw leva os metadados do ZIP de onde veio, e eles
  mudam entre os arquivos: 14 das 37 estações têm coordenadas diferentes entre os anos, na maioria
  só por precisão (6 contra 8 casas decimais, ~0,1 m), mas duas MUDARAM DE LUGAR (A042 Brazlândia,
  ~9,5 km em 2026; A704 Três Lagoas, ~1,3 km em 2023), e a A521 BH Pampulha tem dois nomes.

  Para documentar isso, a dimensão guarda também as coordenadas do registro mais antigo, o
  deslocamento entre as duas (`deslocamento_m`) e `mudou_de_lugar` (deslocamento a partir de
  `limite_mudanca_estacao_m`, 500 m). Uma estação que mudou de lugar quebra a continuidade da sua
  série (outro microclima). O teste `dim_estacao_mudancas_de_lugar_esperadas` avisa se outra mudar.
#}
with medicoes as (

    select
        estacao_codigo,
        uf,
        estacao_nome,
        latitude,
        longitude,
        instante_utc
    from {{ ref('stg_inmet__estacoes_horario') }}

),

mais_recente as (

    select *
    from medicoes
    qualify row_number() over (partition by estacao_codigo order by instante_utc desc) = 1

),

mais_antigo as (

    select
        estacao_codigo,
        latitude as latitude_inicial,
        longitude as longitude_inicial
    from medicoes
    qualify row_number() over (partition by estacao_codigo order by instante_utc asc) = 1

),

resumo as (

    select
        estacao_codigo,
        count(distinct estacao_nome) as n_nomes,
        min(instante_utc) as primeiro_instante_utc,
        max(instante_utc) as ultimo_instante_utc
    from medicoes
    group by estacao_codigo

),

com_deslocamento as (

    select
        r.estacao_codigo,
        r.uf,
        case
            when r.uf in ('ES', 'MG', 'RJ', 'SP') then 'SE'
            when r.uf in ('DF', 'GO', 'MS', 'MT') then 'CO'
        end as regiao,
        r.estacao_nome,
        r.latitude,
        r.longitude,
        a.latitude_inicial,
        a.longitude_inicial,
        round(
            st_distance(
                st_geogpoint(a.longitude_inicial, a.latitude_inicial),
                st_geogpoint(r.longitude, r.latitude)
            ),
            1
        ) as deslocamento_m,
        s.n_nomes,
        s.primeiro_instante_utc,
        s.ultimo_instante_utc
    from mais_recente as r
    inner join mais_antigo as a using (estacao_codigo)
    inner join resumo as s using (estacao_codigo)

)

select
    *,
    deslocamento_m >= {{ var('limite_mudanca_estacao_m') }} as mudou_de_lugar
from com_deslocamento
