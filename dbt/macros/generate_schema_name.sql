{#
  Por padrão o dbt grava em "<dataset do perfil>_<schema do modelo>" (ex.: staging_staging).
  Aqui o schema definido no modelo (staging, marts) é o NOME DO DATASET, sem prefixo, porque os
  datasets raw, staging e marts já existem no BigQuery (decisão de infraestrutura da Sprint 1).
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
