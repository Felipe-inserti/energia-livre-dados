{{ config(severity='error') }}
-- Teste de alerta (Sprint 3, tarefa 3.7): não devolve linha nenhuma, a não ser que a execução peça a
-- falha com FORCAR_FALHA=true. A DAG do Airflow liga a variável quando é disparada com
-- {"falha_proposital": true}, e o resultado prova o caminho inteiro: este teste vermelho, a
-- interrupção do pipeline (as etapas seguintes ficam `upstream_failed`) e o alerta no Discord.
-- Não lê tabela nenhuma: custa 0 bytes.
select 'falha proposital pedida pela variável FORCAR_FALHA' as motivo
from unnest([1])  -- o BigQuery não aceita WHERE sem FROM
where {{ env_var('FORCAR_FALHA', 'false') }}
