{#
  Por padrão o dbt grava em "<dataset do perfil>_<schema do modelo>" (ex.: staging_staging).
  Aqui o schema definido no modelo (staging, marts) é o NOME DO DATASET, sem prefixo, porque os
  datasets raw, staging e marts já existem no BigQuery (decisão de infraestrutura da Sprint 1).

  Validação fora da produção (Sprint 4): com `--vars '{dataset_verificacao: verificacao_incremental}'`
  TODOS os modelos da execução vão para esse dataset, e os `ref` entre eles também. O raw continua
  sendo lido de onde está (só leitura). Só esse nome é aceito, para a var nunca desviar uma
  execução para outro dataset por engano.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- set verificacao = var('dataset_verificacao', none) -%}
    {%- if verificacao is not none -%}
        {%- if verificacao != 'verificacao_incremental' -%}
            {{ exceptions.raise_compiler_error("dataset_verificacao só aceita 'verificacao_incremental', não '" ~ verificacao ~ "'") }}
        {%- endif -%}
        {{ verificacao }}
    {%- elif custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
