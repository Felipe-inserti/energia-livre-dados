{#
  Fato: carga MENSAL por submercado, com a série original do ONS e uma série AJUSTADA para uma
  definição só. Grão: (submercado, mês local). Cerca de 1.290 linhas, sem partição nem cluster (uma
  tabela desse tamanho particionada só adiciona custo; mesmo critério da `fct_pld_semanal`).

  POR QUE EXISTE. A curva horária do ONS muda de definição duas vezes (docs/fontes.md), e isso é o
  que mais distorce a previsão mensal 12 meses à frente:
    - 01/03/2021: entram as usinas não despachadas (geração tipo III). Antes, a curva as exclui.
    - 01/05/2023: entra a MMGD estimada. Antes, a curva é líquida de MMGD. (A documentação do ONS diz
      29/04/2023; no dado o salto só aparece em 01/05, ver docs/decisoes.md.)
  O consumo do supermercado segue a carga BRUTA (consumo total, com MMGD e com tipo III), então a
  série ajustada leva os meses antigos a essa definição: original + tipo III + MMGD.

  A SÉRIE ORIGINAL FICA INTACTA (`carga_original_mwmed`); o ajuste vem em colunas separadas, cada uma
  com o seu status, para ficar explícito o que é medido, o que é zero por premissa e o que não existe:
    status do ajuste        valor           quando
    medido                  o ajuste        a API do ONS permite medir (tipo III: 2018-01 a 2021-02;
                                            MMGD: 2019-02 a 2023-04, com o fator r)
    medido_transicao        API - curva     tipo III logo depois da quebra de 2021-03, enquanto a
                                            diferença mensal ainda for maior que o ruído (ver abaixo)
    zero_por_premissa       0               MMGD antes de 2019-02 (a API não tem; era < 0,5% da carga)
    incorporado_na_curva    0               a curva já traz o componente (tipo III depois da transição,
                                            MMGD desde 2023-05)
    nao_disponivel          NULL            tipo III antes de 2018-01: sem medida, e NÃO se inventa
  `carga_ajustada_mwmed` é NULL sempre que um dos dois componentes é `nao_disponivel` (hoje, antes de
  2018): a decisão sobre o histórico anterior a 2018 é da Sprint 5.

  RECONSTRUÇÃO 2015-2017 (Sprint 5, colunas `*_reconstruido*` e `carga_ajustada_reconstruida_mwmed`). Para
  treinar com janela de 72 meses desde dez/2020 é preciso o tipo III de 2015 a 2017. A Carga Mensal do ONS
  o inclui desde jan/2015, então tipo III = Carga Mensal - curva (status `reconstruido_carga_mensal`; seed
  `carga_mensal_ons`). Em 2018, onde a API também mede, o erro absoluto médio é 0,14% da curva no SE/CO
  (a razão sazonal média de 2018-2020 erra 0,31% fora da amostra; docs/decisoes.md). Antes de 2015 a
  diferença é ~0 e nada é reconstruído (`nao_disponivel`). As colunas `ajuste_tipo3_*` e
  `carga_ajustada_mwmed` NÃO mudam: continuam só com o medido, a partir de 2018.

  TRANSIÇÃO DO TIPO III (uma regra só, igual para os 4 submercados, definida pelo dado). Depois de
  2021-03 a curva ainda difere da API por alguns meses. O ajuste continua `medido_transicao`
  (carga líquida da API - curva) enquanto |diferença mensal| > `ruido_k_tipo3` x desvio-padrão da
  diferença mensal em `ano_ruido_tipo3` (2022: a curva já traz o tipo III e a MMGD ainda não, então
  o que sobra da diferença é ruído entre as duas fontes). A transição termina no primeiro mês que
  abre uma sequência de `meses_ruido_para_encerrar` (2) meses dentro do ruído, e dali em diante o
  ajuste é zero, sem voltar (`ajuste_tipo3_fim_transicao`). Todo mês anterior ao fim é transição.

  COMO SE MEDE O AJUSTE (a API de Carga Verificada, no seed `ajuste_definicao_carga`):
    tipo III = carga líquida da API - curva           (API inclui tipo III desde sempre; a curva não)
    MMGD     = r x MMGD da API                        (r = 1 é a sensibilidade: `carga_ajustada_r1_mwmed`)
  O fator `r` existe porque a MMGD que a curva incorporou (meteorologia PREVISTA) não é igual à da API
  (verificada): nos 12 meses seguintes à quebra, `r` = soma(curva - líquida da API) / soma(MMGD da API),
  por submercado. É a fração da MMGD da API que a curva de fato traz; aplicá-la ao passado mantém a
  série contínua na quebra de 2023.

  ARREDONDAMENTO NA ORIGEM (Sprint 5). Toda coluna de carga/ajuste em MWmed sai arredondada a
  `casas_decimais_carga` (3, ou seja, 1 kW). Motivo: o AVG paralelo do BigQuery soma em ordem variável e
  não é reproduzível bit a bit (medido: 3 a 5 de 322 meses mudam no último dígito a cada execução, até
  7e-12 MWmed); a série de treino da previsão mudava ~1e-10 a cada `dbt run`, e o SARIMA transformava
  isso em 30 MWmed na soma de 12 meses (docs/decisoes.md). Com 1 kW de resolução (3 ordens de grandeza
  acima do ruído e 4 abaixo do menor erro relevante) a série fica idêntica bit a bit entre execuções,
  salvo um valor exatamente na fronteira do arredondamento (~1e-7 por mês).

  MÊS INCOMPLETO x COBERTURA (dois conceitos separados):
    - `mes_incompleto`: o mês AINDA NÃO TERMINOU, ou seja, é o mês corrente (data de São Paulo no
      momento do `dbt run`). Definido pela data e não pela contagem de horas. Esse mês nunca é alvo
      nem treino da previsão.
    - `cobertura` = horas válidas / horas esperadas, com as horas esperadas contadas em HORA LOCAL
      (o ONS publica 24 valores por dia local, então o dia de 25 horas do fim do horário de verão
      tem 24 valores, e o de 23 horas, 23). Um mês fechado com lacuna não é "incompleto": é um mês
      com cobertura menor. Ele serve de alvo e de treino se a cobertura chegar ao limiar
      `cobertura_minima` (dbt_project.yml; 0,95, que aceita 1 dia faltando e recusa 2: a média do SE
      muda no máximo 0,9% por 1 dia faltando e até 1,7% por 2, contra um MAPE de ~3% do baseline).
    `mes_utilizavel` junta as duas regras: mês fechado com cobertura suficiente. A média usa só as
    horas válidas (soma / horas válidas), nunca soma / horas esperadas.
#}
with grade as (

    -- horas que o mês tem NO RELÓGIO LOCAL, que é como o ONS publica (24 valores por dia local).
    -- A dim_tempo tem uma linha por hora UTC, então o dia de 25 horas (fim do horário de verão, em
    -- fevereiro até 2019) repete a hora local; contar horas locais DISTINTAS dá 24 nesse dia e 23 no
    -- dia em que o relógio pula uma hora. Contar linhas da dim_tempo faria todo fevereiro de 2000 a
    -- 2019 parecer ter 1 hora faltando.
    select
        date_trunc(data_local, month) as mes,
        count(distinct unix_date(data_local) * 24 + hora_local) as horas_esperadas
    from {{ ref('dim_tempo') }}
    group by mes

),

mensal as (

    select
        codigo_submercado,
        date_trunc(date(instante_utc, 'America/Sao_Paulo'), month) as mes,
        count(*) as horas_com_linha,
        count(carga_mwmed) as horas_validas,
        -- ARREDONDADO NA ORIGEM a {{ var('casas_decimais_carga') }} casas (1 kW): o AVG paralelo do BigQuery não é
        -- reproduzível bit a bit (3 a 5 de 322 meses mudam no último dígito a cada execução, até
        -- 7e-12 MWmed) e o SARIMA amplifica isso (docs/decisoes.md). Todo consumidor do mart herda a conta estável.
        round(avg(carga_mwmed), {{ var('casas_decimais_carga') }}) as carga_original_mwmed
    from {{ ref('fct_carga_horaria') }}
    group by codigo_submercado, mes

),

api as (

    select
        cast(mes as date) as mes,
        codigo_submercado,
        api_liquida_mwmed,
        api_mmgd_mwmed,
        status_mmgd,
        status_tipo3
    from {{ ref('ajuste_definicao_carga') }}

),

-- Carga Mensal do ONS (2015 a 2018): inclui o tipo III desde jan/2015, então `Carga Mensal - curva`
-- mede o tipo III onde a API de Carga Verificada não tem dado (2015 a 2017)
carga_mensal as (

    select cast(mes as date) as mes, codigo_submercado, carga_mensal_ons_mwmed
    from {{ ref('carga_mensal_ons') }}

),

-- diferença mensal entre a carga líquida da API e a curva, onde a API existe
diferenca as (

    select
        m.codigo_submercado,
        m.mes,
        a.api_liquida_mwmed - m.carga_original_mwmed as dif
    from mensal as m
    inner join api as a using (codigo_submercado, mes)

),

-- ruído pós-incorporação por submercado: k x desvio-padrão da diferença no ano de referência
ruido as (

    select
        codigo_submercado,
        {{ var('ruido_k_tipo3') }} * stddev_samp(dif) as limiar
    from diferenca
    where extract(year from mes) = {{ var('ano_ruido_tipo3') }}
    group by codigo_submercado

),

-- meses da janela de transição (da quebra de 2021 até a da MMGD) em que a diferença cabe no ruído
janela_ruido as (

    select
        d.codigo_submercado,
        d.mes,
        abs(d.dif) <= r.limiar as dentro
    from diferenca as d
    inner join ruido as r using (codigo_submercado)
    where d.mes >= date '{{ var("mes_quebra_tipo3") }}'
        and d.mes < date '{{ var("mes_quebra_mmgd") }}'

),

-- um mês "encerra" a transição quando ele e os (n - 1) seguintes estão dentro do ruído, com n =
-- `meses_ruido_para_encerrar`. Com n = 1 bastaria um mês de sorte dentro do ruído (o SE com k = 4
-- encerraria em março e ignoraria abril e maio, que continuam acima do ruído); com n = 2 o fim é o
-- mesmo para k = 3 e k = 4 (docs/decisoes.md). A janela acaba na quebra da MMGD: sem mês seguinte,
-- `lead` dá nulo e o mês não encerra.
seguidos as (

    select
        codigo_submercado,
        mes,
        dentro
        {%- for i in range(1, var('meses_ruido_para_encerrar')) %}
        and coalesce(lead(dentro, {{ i }}) over (partition by codigo_submercado order by mes), false)
        {%- endfor %}
        as encerra
    from janela_ruido

),

-- primeiro mês que encerra a transição: dali em diante o ajuste de tipo III é zero, sem voltar
fim as (

    select
        codigo_submercado,
        min(mes) as fim_transicao
    from seguidos
    where encerra
    group by codigo_submercado

),

-- r por submercado: a fração da MMGD da API que a curva traz, medida nos 12 meses seguintes à quebra
fator as (

    select
        m.codigo_submercado,
        safe_divide(sum(m.carga_original_mwmed - a.api_liquida_mwmed), sum(a.api_mmgd_mwmed))
            as fator_r
    from mensal as m
    inner join api as a using (codigo_submercado, mes)
    where a.status_mmgd = 'incorporado_na_curva'
    group by m.codigo_submercado

),

juntado as (

    select
        m.codigo_submercado,
        m.mes,
        g.horas_esperadas,
        m.horas_com_linha,
        m.horas_validas,
        m.mes >= date_trunc(current_date('America/Sao_Paulo'), month) as mes_incompleto,
        safe_divide(m.horas_validas, g.horas_esperadas) as cobertura,
        m.carga_original_mwmed,
        f.fator_r as ajuste_mmgd_fator_r,
        -- tipo III: o status vem da data da quebra e da regra de transição (não do seed, que é um
        -- retrato da API e não enxerga a curva, que o ONS revisa)
        case
            when m.mes < date '{{ var("inicio_api_carga") }}' then 'nao_disponivel'
            when m.mes < date '{{ var("mes_quebra_tipo3") }}' then 'medido'
            when m.mes < coalesce(fi.fim_transicao, date '{{ var("mes_quebra_mmgd") }}')
                then 'medido_transicao'
            else 'incorporado_na_curva'
        end as ajuste_tipo3_status,
        r.limiar as ajuste_tipo3_limiar_mwmed,
        coalesce(fi.fim_transicao, date '{{ var("mes_quebra_mmgd") }}') as ajuste_tipo3_fim_transicao,
        coalesce(
            a.status_mmgd,
            case
                when m.mes >= date '{{ var("mes_quebra_mmgd") }}' then 'incorporado_na_curva'
                else 'zero_por_premissa'
            end
        ) as ajuste_mmgd_status,
        a.api_liquida_mwmed,
        a.api_mmgd_mwmed,
        cm.carga_mensal_ons_mwmed
    from mensal as m
    inner join grade as g using (mes)
    left join api as a using (codigo_submercado, mes)
    left join carga_mensal as cm using (codigo_submercado, mes)
    left join fator as f using (codigo_submercado)
    left join ruido as r using (codigo_submercado)
    left join fim as fi using (codigo_submercado)

),

ajustado as (

    select
        *,
        case ajuste_tipo3_status
            when 'medido' then round(api_liquida_mwmed - carga_original_mwmed, {{ var('casas_decimais_carga') }})
            when 'medido_transicao'
                then round(api_liquida_mwmed - carga_original_mwmed, {{ var('casas_decimais_carga') }})
            when 'incorporado_na_curva' then 0.0
        end as ajuste_tipo3_mwmed,
        case ajuste_mmgd_status
            when 'medido' then round(ajuste_mmgd_fator_r * api_mmgd_mwmed, {{ var('casas_decimais_carga') }})
            when 'medido_parcial'
                then round(ajuste_mmgd_fator_r * api_mmgd_mwmed, {{ var('casas_decimais_carga') }})
            else 0.0
        end as ajuste_mmgd_mwmed,
        -- sensibilidade: a MMGD da API inteira (r = 1), sem a calibração pela curva
        case ajuste_mmgd_status
            when 'medido' then round(api_mmgd_mwmed, {{ var('casas_decimais_carga') }})
            when 'medido_parcial' then round(api_mmgd_mwmed, {{ var('casas_decimais_carga') }})
            else 0.0
        end as ajuste_mmgd_r1_mwmed,
        -- reconstrução do tipo III antes da API: Carga Mensal - curva, de `inicio_reconstrucao_tipo3` até o
        -- mês anterior a `inicio_api_carga`. É um status NOVO, em colunas à parte: `ajuste_tipo3_*` e
        -- `carga_ajustada_mwmed` não mudam (a série medida continua só a partir de 2018).
        case
            when mes >= date '{{ var("inicio_reconstrucao_tipo3") }}' and mes < date '{{ var("inicio_api_carga") }}'
                then 'reconstruido_carga_mensal'
            else ajuste_tipo3_status
        end as ajuste_tipo3_reconstruido_status
    from juntado

)

select
    codigo_submercado,
    mes,
    horas_esperadas,
    horas_com_linha,
    horas_validas,
    mes_incompleto,
    cobertura,
    cobertura >= {{ var('cobertura_minima') }} as cobertura_suficiente,
    not mes_incompleto and cobertura >= {{ var('cobertura_minima') }} as mes_utilizavel,
    carga_original_mwmed,
    ajuste_tipo3_mwmed,
    ajuste_tipo3_status,
    ajuste_tipo3_limiar_mwmed,
    ajuste_tipo3_fim_transicao,
    ajuste_mmgd_mwmed,
    ajuste_mmgd_status,
    ajuste_mmgd_fator_r,
    round(carga_original_mwmed + ajuste_tipo3_mwmed + ajuste_mmgd_mwmed, {{ var('casas_decimais_carga') }})
        as carga_ajustada_mwmed,
    round(carga_original_mwmed + ajuste_tipo3_mwmed + ajuste_mmgd_r1_mwmed, {{ var('casas_decimais_carga') }})
        as carga_ajustada_r1_mwmed,
    ajuste_tipo3_reconstruido_status,
    case ajuste_tipo3_reconstruido_status
        when 'reconstruido_carga_mensal'
            then round(carga_mensal_ons_mwmed - carga_original_mwmed, {{ var('casas_decimais_carga') }})
        else ajuste_tipo3_mwmed
    end as ajuste_tipo3_reconstruido_mwmed,
    -- série para treinar com janela de 6 anos: original + tipo III (medido ou reconstruído) + MMGD.
    -- Nula antes de 2015 (nao_disponivel): ali o tipo III não foi medido e não se inventa.
    case ajuste_tipo3_reconstruido_status
        when 'reconstruido_carga_mensal'
            then round(carga_mensal_ons_mwmed + ajuste_mmgd_mwmed, {{ var('casas_decimais_carga') }})
        else round(carga_original_mwmed + ajuste_tipo3_mwmed + ajuste_mmgd_mwmed, {{ var('casas_decimais_carga') }})
    end as carga_ajustada_reconstruida_mwmed
from ajustado
