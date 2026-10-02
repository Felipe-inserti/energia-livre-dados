{#
  Dimensão de tempo: UMA LINHA POR HORA UTC, de 2000-01-01 00:00Z a 2030-12-31 23:00Z
  (271.752 linhas), com os atributos de calendário na hora LOCAL (America/Sao_Paulo).

  O ONS e o PLD estão em horário local e o INMET em UTC; no staging tudo é UTC, e esta dimensão
  traduz cada instante para a hora do relógio local e para o calendário brasileiro. Todos os
  atributos de dia (feriado, dia da semana, mês, ano, tipo de dia, estação) usam a DATA LOCAL, não
  a UTC: das 21h às 23h59 locais a data UTC já é a do dia seguinte e marcaria o feriado errado.

  Dois conceitos de feriado, cada um com a sua definição (decisão documentada em decisoes.md):
  - `eh_feriado`: feriados nacionais da biblioteca `holidays` (stg_feriados). Alimenta `tipo_dia`
    (a loja opera como domingo no feriado, ver premissas.md). Inclui o Dia da Consciência Negra a
    partir de 2024 e NÃO inclui Carnaval nem Corpus Christi.
  - `eh_feriado_aneel`: os 11 feriados nacionais que a ANEEL considera para o horário de ponta:
    1º de janeiro, terça de Carnaval, Sexta-feira Santa, Tiradentes, 1º de maio, Corpus Christi,
    7 de setembro, 12 de outubro, Finados, 15 de novembro e Natal. É a lista da biblioteca sem a
    Consciência Negra, mais a terça de Carnaval (Sexta-feira Santa - 45 dias) e Corpus Christi
    (Sexta-feira Santa + 62 dias); a aritmética é conferida contra a biblioteca em pytest.

  O horário de ponta (3 horas locais a partir de `hora_ponta_inicio`, em dias úteis fora dos
  feriados da ANEEL) é uma premissa (a distribuidora é quem define as horas) usada só na análise;
  não entra no cálculo do contrato.
#}
{% set inicio = var('data_inicio_dim_tempo') %}
{% set fim = var('data_fim_dim_tempo') %}
{% set ponta_inicio = var('hora_ponta_inicio') %}
{% set ponta_fim = var('hora_ponta_inicio') + var('horas_de_ponta') - 1 %}

with horas_utc as (

    select instante_utc
    from unnest(
        generate_timestamp_array(
            timestamp('{{ inicio }} 00:00:00+00'),
            timestamp('{{ fim }} 23:00:00+00'),
            interval 1 hour
        )
    ) as instante_utc

),

hora_local as (

    select
        instante_utc,
        datetime(instante_utc, 'America/Sao_Paulo') as instante_local
    from horas_utc

),

calendario as (

    select
        instante_utc,
        instante_local,
        date(instante_local) as data_local,
        extract(hour from instante_local) as hora_local,
        datetime_diff(instante_local, datetime(instante_utc), hour) as deslocamento_utc_horas,
        extract(year from instante_local) as ano,
        extract(month from instante_local) as mes,
        extract(day from instante_local) as dia_do_mes,
        -- ISO: 1 = segunda ... 7 = domingo (o EXTRACT do BigQuery conta domingo = 1 ... sábado = 7)
        mod(extract(dayofweek from instante_local) + 5, 7) + 1 as dia_da_semana
    from hora_local

),

feriados as (

    select
        data_feriado,
        split(nome_feriado, '; ') as nomes_feriado
    from {{ ref('stg_feriados') }}

),

sexta_feira_santa as (

    select data_feriado as data
    from {{ ref('stg_feriados') }}
    where nome_feriado like '%Sexta-feira Santa%'

),

feriados_aneel as (

    -- os feriados nacionais da biblioteca, menos a Consciência Negra (a ANEEL não a lista)
    select data_feriado as data
    from {{ ref('stg_feriados') }}
    where nome_feriado not like '%Consciência Negra%'

    union distinct

    -- terça-feira de Carnaval
    select date_sub(data, interval 45 day) from sexta_feira_santa

    union distinct

    -- Corpus Christi
    select date_add(data, interval 62 day) from sexta_feira_santa

),

com_feriados as (

    select
        c.*,
        coalesce(f.nomes_feriado, array<string>[]) as nomes_feriado,
        f.data_feriado is not null as eh_feriado,
        a.data is not null as eh_feriado_aneel
    from calendario as c
    left join feriados as f on f.data_feriado = c.data_local
    left join feriados_aneel as a on a.data = c.data_local

)

select
    instante_utc,
    instante_local,
    data_local,
    hora_local,
    deslocamento_utc_horas,
    deslocamento_utc_horas = -2 as eh_horario_verao,
    ano,
    mes,
    dia_do_mes,
    dia_da_semana,
    eh_feriado,
    array_length(nomes_feriado) as qtd_feriados,
    nomes_feriado,
    case
        when eh_feriado or dia_da_semana = 7 then 'domingo_feriado'
        when dia_da_semana = 6 then 'sabado'
        else 'dia_util'
    end as tipo_dia,
    case
        when mes in (12, 1, 2) then 'verao'
        when mes in (3, 4, 5) then 'outono'
        when mes in (6, 7, 8) then 'inverno'
        else 'primavera'
    end as estacao_do_ano,
    eh_feriado_aneel,
    (
        not eh_feriado_aneel
        and dia_da_semana between 1 and 5
        and hora_local between {{ ponta_inicio }} and {{ ponta_fim }}
    ) as eh_horario_ponta
from com_feriados
