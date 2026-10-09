{#
  Fato: curva horária de consumo do consumidor-exemplo (supermercado, SE/CO). Grão: hora UTC.
  Uma linha por hora de cada dia local COMPLETO (24 horas válidas no ONS) de 2020-01-01 em diante.
  Sem partição (~59 mil linhas, 2 a 3 MB; mesmo critério da `fct_carga_mensal`).

      consumo_h (MWh) = k × L_d × p(h, tipo_dia)          (docs/premissas.md, seção 2)

  - `L_d` (MWmed): carga média do dia local do SE, na definição BRUTA. O ajuste de definição do ONS
    (tipo III e MMGD, `fct_carga_mensal`) é mensal, então entra como um acréscimo constante em todos os
    dias do mês: L_d = média diária da carga horária original + (ajustada − original do mês). Assim a
    média mensal da curva reproduz exatamente a série que a previsão usa (teste de reconciliação, 1 kW).
    O custo é um pequeno degrau na virada do mês nos meses em que o ajuste muda.
  - `p(h, tipo_dia)`: 40% de refrigeração constante nas 24 h + 60% de operação no horário da loja,
    normalizado para média 1 em CADA dia. Aberta: p = r + (1 − r) × 24 / N; fechada: p = r, com N as horas
    abertas. Feriado nacional opera como domingo (`tipo_dia` da dim_tempo). Sem ruído e sem temperatura.
  - `k` (var `k_consumo`): fator único para todo o período, calibrado para que o consumo médio de 2020 a
    2025 seja de 100 MWh/mês. É uma DEFINIÇÃO DO TAMANHO DO CLIENTE (ver premissas.md): escala o custo e a
    economia em R$ na mesma proporção, a economia em % não depende dele. Está congelado em vez de
    recalculado a cada rodada para que uma revisão do ONS não mude a curva em silêncio; o teste
    `fct_consumo_horario_calibracao_do_k` falha se o dado se afastar da calibração.
  Parâmetros (horário da loja, refrigeração, tamanho) são vars em dbt_project.yml.
#}
{% set refrigeracao = var('consumo_refrigeracao') %}

with horas as (

    select
        c.instante_utc,
        c.carga_mwmed,
        t.data_local,
        t.hora_local,
        t.tipo_dia
    from {{ ref('fct_carga_horaria') }} as c
    inner join {{ ref('dim_tempo') }} as t on t.instante_utc = c.instante_utc
    where c.codigo_submercado = 'SE'
        and t.data_local >= date('{{ var('consumo_inicio') }}')

),

dias as (

    -- só dias locais completos: com menos de 24 horas válidas a média diária não é a do dia, e o perfil
    -- deixaria de ter média 1 (o dia corrente e os ~2 dias de atraso do ONS ficam de fora)
    select
        data_local,
        avg(carga_mwmed) as carga_dia_original_mwmed
    from horas
    group by data_local
    having count(*) = 24 and count(carga_mwmed) = 24

),

ajuste as (

    select
        mes,
        carga_ajustada_mwmed - carga_original_mwmed as ajuste_mwmed
    from {{ ref('fct_carga_mensal') }}
    where codigo_submercado = 'SE'

),

perfil as (

    select
        h.instante_utc,
        h.data_local,
        h.hora_local,
        h.tipo_dia,
        d.carga_dia_original_mwmed + a.ajuste_mwmed as carga_dia_mwmed,
        -- horas abertas no dia: seg a sáb (e feriado de dia útil NÃO: opera como domingo)
        if(h.tipo_dia = 'domingo_feriado',
            {{ var('consumo_hora_fecha_domingo') }} - {{ var('consumo_hora_abre_domingo') }},
            {{ var('consumo_hora_fecha_util') }} - {{ var('consumo_hora_abre_util') }}) as horas_abertas,
        if(h.tipo_dia = 'domingo_feriado',
            h.hora_local >= {{ var('consumo_hora_abre_domingo') }} and h.hora_local < {{ var('consumo_hora_fecha_domingo') }},
            h.hora_local >= {{ var('consumo_hora_abre_util') }} and h.hora_local < {{ var('consumo_hora_fecha_util') }}) as loja_aberta
    from horas as h
    inner join dias as d on d.data_local = h.data_local
    inner join ajuste as a on a.mes = date_trunc(h.data_local, month)

)

select
    instante_utc,
    data_local,
    hora_local,
    tipo_dia,
    carga_dia_mwmed,
    loja_aberta,
    if(loja_aberta, {{ refrigeracao }} + (1 - {{ refrigeracao }}) * 24 / horas_abertas, {{ refrigeracao }}) as perfil,
    {{ var('k_consumo') }} * carga_dia_mwmed
        * if(loja_aberta, {{ refrigeracao }} + (1 - {{ refrigeracao }}) * 24 / horas_abertas, {{ refrigeracao }}) as consumo_mwh
from perfil
