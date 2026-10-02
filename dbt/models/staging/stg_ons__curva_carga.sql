{#
  Curva de carga horária do ONS por subsistema, em UTC.

  O raw está em horário local (America/Sao_Paulo, com horário de verão até 2018).
  1. Tipa o instante local e a carga (CAST: valor mal formatado derruba o modelo).
  2. Converte para UTC com o fuso nomeado.
  3. DESCARTA as horas locais que não existem (00:00 do dia de início do horário de verão em
     2014-2018, onde o raw traz uma linha nula; em 2018 o S traz 0,0). O BigQuery converte uma
     hora inexistente para o MESMO instante UTC da hora real seguinte (2016-10-16 00:00 e
     01:00 viram 03:00Z), então manter a linha criaria uma chave duplicada e a deduplicação
     poderia escolher a linha nula no lugar da real. Detectar: converter para UTC, voltar para
     local e comparar. O teste `ons_descarta_so_horas_conhecidas` garante que só as horas
     conhecidas saem.
  4. Deduplica pela chave natural, mantendo a carga mais recente (revisões do ONS).

  Ficam como estão: os valores nulos dos dias inteiros sem dado (2013-12-01, 2014-02-01 e
  2015-04-09; tratar é papel dos testes da Sprint 3) e a hora UTC que falta no fim de cada
  horário de verão (a hora repetida aparece uma vez só na fonte).
#}
with raw as (

    select
        id_subsistema,
        nom_subsistema as nome_subsistema,
        cast(din_instante as datetime) as instante_local,
        cast(nullif(val_cargaenergiahomwmed, '') as float64) as carga_mwmed,
        _arquivo_origem,
        _carregado_em
    from {{ source('raw', 'ons_curva_carga') }}

),

com_utc as (

    select
        *,
        timestamp(instante_local, 'America/Sao_Paulo') as instante_utc
    from raw

),

horas_que_existem as (

    select *
    from com_utc
    where datetime(instante_utc, 'America/Sao_Paulo') = instante_local

),

deduplicada as (

    select *
    from horas_que_existem
    qualify row_number() over (
        partition by id_subsistema, instante_utc
        order by _carregado_em desc
    ) = 1

)

select
    id_subsistema,
    nome_subsistema,
    instante_utc,
    carga_mwmed,
    _arquivo_origem,
    _carregado_em
from deduplicada
