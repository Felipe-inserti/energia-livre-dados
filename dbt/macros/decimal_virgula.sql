{#
  Converte um texto com vírgula decimal (INMET: '19,5') para FLOAT64. Vazio vira NULL.
  É CAST (e não SAFE_CAST) de propósito: um valor mal formatado derruba o modelo em vez de virar
  NULL em silêncio.
#}
{% macro decimal_virgula(coluna) -%}
    cast(nullif(replace({{ coluna }}, ',', '.'), '') as float64)
{%- endmacro %}
