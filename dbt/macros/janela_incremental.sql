{#
  Janela do incremental do ONS (Sprint 4). As vars chegam de `python -m ingestion.janela
  --formato dbt-vars ...` (ou do `--saida-vars` da ingestão): é o ÚNICO lugar que as calcula, com as
  5 regras do docstring de ingestion/janela.py. Aqui só se valida e se usa.

  Vars (datas AAAA-MM-DD, sempre dia 1):
    utc_inicio, utc_fim        intervalo UTC [inicio, fim), alinhado a meses UTC inteiros
    particoes_utc              lista dos meses UTC que o insert_overwrite apaga e recria
    raw_mes_inicio/raw_mes_fim meses LOCAIS do raw que o modelo lê (ambos inclusive)

  Regra de ouro: a lista de partições e o filtro do modelo cobrem EXATAMENTE o mesmo intervalo, e o
  raw lido cobre todas as horas das partições sobrescritas. Se não cobrisse, o MERGE apagaria a
  partição e inseriria só uma parte dela (perda de dado).
#}

{% macro janela_particoes() %}
    {#- Literais das partições estáticas do insert_overwrite. Lista vazia se a var não existe (o
        parse do projeto e o --full-refresh não precisam dela); `janela_incremental()` recusa a
        execução incremental nesse caso, antes de qualquer SQL, para NUNCA cair no modo dinâmico. -#}
    {% set literais = [] %}
    {% for p in var('particoes_utc', []) %}
        {% do literais.append("timestamp('" ~ p ~ "')") %}
    {% endfor %}
    {{ return(literais) }}
{% endmacro %}


{% macro janela_incremental() %}
    {#- Valida as vars e devolve a janela. Chamar só em execução incremental. -#}
    {% set obrigatorias = ['utc_inicio', 'utc_fim', 'particoes_utc', 'raw_mes_inicio', 'raw_mes_fim'] %}
    {% set faltam = [] %}
    {% for nome in obrigatorias %}
        {% if not var(nome, none) %}
            {% do faltam.append(nome) %}
        {% endif %}
    {% endfor %}
    {% if faltam %}
        {{ exceptions.raise_compiler_error(
            "Execução INCREMENTAL de " ~ model.name ~ " sem as vars da janela: " ~ faltam | join(', ')
            ~ ". Gere-as com `uv run python -m ingestion.janela --formato dbt-vars"
            ~ " --data-referencia AAAA-MM-DD` (ou --desde/--ate) e passe em --vars."
            ~ " Para reconstruir a tabela inteira use --full-refresh."
        ) }}
    {% endif %}

    {% set datas = [var('utc_inicio'), var('utc_fim'), var('raw_mes_inicio'), var('raw_mes_fim')] %}
    {% set particoes = var('particoes_utc') %}
    {% if particoes is string or particoes | length == 0 %}
        {{ exceptions.raise_compiler_error("particoes_utc precisa ser uma lista não vazia") }}
    {% endif %}
    {#- só datas AAAA-MM-01 entram no SQL: nada de texto arbitrário interpolado -#}
    {% for d in datas + particoes %}
        {% if not modules.re.match('^[0-9]{4}-[0-9]{2}-01$', d | string) %}
            {{ exceptions.raise_compiler_error("Data inválida na janela do " ~ model.name ~ ": '" ~ d ~ "' (use AAAA-MM-01)") }}
        {% endif %}
    {% endfor %}
    {% if particoes[0] != var('utc_inicio') %}
        {{ exceptions.raise_compiler_error("particoes_utc[0] (" ~ particoes[0] ~ ") deve ser igual a utc_inicio (" ~ var('utc_inicio') ~ ")") }}
    {% endif %}
    {% for p in particoes %}
        {% if p < var('utc_inicio') or p >= var('utc_fim') %}
            {{ exceptions.raise_compiler_error("A partição " ~ p ~ " está fora de [utc_inicio, utc_fim): a lista e o filtro não cobririam o mesmo intervalo") }}
        {% endif %}
    {% endfor %}
    {% if var('raw_mes_inicio') >= var('utc_inicio') or var('raw_mes_fim') < particoes[-1] %}
        {#- a primeira hora de utc_inicio (00h UTC) é 21h do dia anterior no horário local, então o raw
            lido começa num mês ESTRITAMENTE anterior; e a última hora da última partição cai no mês
            local dela: o raw lido tem de cobrir as partições inteiras -#}
        {{ exceptions.raise_compiler_error("O raw lido [" ~ var('raw_mes_inicio') ~ ", " ~ var('raw_mes_fim') ~ "] não cobre todas as horas das partições sobrescritas") }}
    {% endif %}

    {{ return({
        'utc_inicio': var('utc_inicio'),
        'utc_fim': var('utc_fim'),
        'raw_mes_inicio': var('raw_mes_inicio'),
        'raw_mes_fim': var('raw_mes_fim'),
    }) }}
{% endmacro %}
