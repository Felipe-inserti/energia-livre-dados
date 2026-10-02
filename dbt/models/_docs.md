{# Blocos de documentação das colunas que se repetem em vários modelos. Use nos YAML com
   description: '{{ doc("nome_do_bloco") }}'. Assim a definição vive num lugar só. #}

{% docs instante_utc %}
Início da hora, em UTC. Chave estrangeira da `dim_tempo` (que traz o relógio local, o dia da semana
e o tipo de dia). Nos fatos horários também é a coluna de partição (mensal).
{% enddocs %}

{% docs codigo_submercado %}
Código do submercado no ONS (`id_subsistema`): SE (Sudeste/Centro-Oeste), S, NE ou N. Chave
estrangeira da `dim_submercado`, que também traduz o nome usado pela CCEE.
{% enddocs %}

{% docs nome_ccee_submercado %}
Nome do submercado como a CCEE o escreve: SUDESTE, SUL, NORDESTE ou NORTE. A `dim_submercado`
traduz para o código do ONS.
{% enddocs %}

{% docs pld_rs_mwh %}
Preço de Liquidação das Diferenças (PLD) em R$/MWh, tipo NUMERIC.
{% enddocs %}

{% docs carga_mwmed %}
Carga média da hora em MWmed (megawatt médio), do ONS. Nula nos dias inteiros sem dado (2013-12-01,
2014-02-01 e 2015-04-09). A partir de 29/04/2023 a carga passou a incluir a micro e minigeração
distribuída (degrau de definição, não de consumo).
{% enddocs %}

{% docs uf %}
Sigla da UF da estação do INMET (DF, ES, GO, MG, MS, RJ ou SP).
{% enddocs %}

{% docs estacao_codigo %}
Código da estação meteorológica (WMO), ex.: A701. Chave estrangeira da `dim_estacao`.
{% enddocs %}

{% docs arquivo_origem %}
Caminho do arquivo original no bronze do GCS, de onde a linha foi carregada (rastreabilidade).
{% enddocs %}

{% docs carregado_em %}
Momento (UTC) em que a carga full gravou a linha no raw. Na deduplicação, vence a linha mais
recente (revisões da fonte).
{% enddocs %}

{% docs periodo_comercializacao %}
Hora sequencial dentro do mês, como a CCEE publica (1 a 744). No PLD semanal é a hora do mês em que
a semana começa, `(dia - 1) * 24 + 1`.
{% enddocs %}

{% docs ordem_preco_na_semana %}
Posição do preço entre as 3 linhas da semana, do menor ao maior preço (1 a 3). O arquivo da CCEE
não diz qual patamar de carga (leve, médio ou pesado) cada linha é; por isso isto não é um
patamar, é só uma ordem determinística que dá chave única.
{% enddocs %}

{% docs data_inicio_semana %}
Data local do primeiro dia da semana operativa (a semana começa no sábado, com poucas semanas
curtas no início do mês).
{% enddocs %}

{% docs inmet_temperatura_orvalho %}
Temperatura do ponto de orvalho em °C.
{% enddocs %}
