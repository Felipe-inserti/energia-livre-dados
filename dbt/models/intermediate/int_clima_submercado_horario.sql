{#
  Temperatura do submercado por hora UTC: segundo passo da agregação em dois passos.

  PROVISÓRIO: média SIMPLES entre os estados. O desenho final pondera cada estado pelo seu peso no
  consumo de energia do submercado (Anuário Estatístico da EPE), mas esses pesos ainda não existem
  (docs/premissas.md, pendência 4). É o fallback já previsto na lista "Se atrasar" (item 3); quando
  houver os pesos, só este modelo muda. Como a temperatura serve à análise de erro (não entra na
  curva nem na previsão central), o impacto é pequeno.

  Todas as estações do INMET selecionadas ficam no SE/CO (ES, MG, RJ, SP, DF, GO e MS; o MT foi
  excluído), então o submercado é sempre `SE` (o código do ONS).
#}
select
    'SE' as codigo_submercado,
    instante_utc,
    avg(temperatura_c) as temperatura_c,
    count(temperatura_c) as n_estados_com_dado,
    countif(temperatura_imputada) as n_estados_imputados
from {{ ref('int_clima_estado_horario') }}
group by instante_utc
