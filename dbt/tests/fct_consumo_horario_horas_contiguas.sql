{{ config(severity='error') }}
-- Sem buracos: da primeira à última hora da curva há uma linha por hora UTC. Dias incompletos do ONS só podem
-- ficar no FIM da série (o dia corrente e o atraso de ~2 dias); no meio, seriam uma hora perdida.
select count(*) as linhas, timestamp_diff(max(instante_utc), min(instante_utc), hour) + 1 as horas_esperadas
from {{ ref('fct_consumo_horario') }}
having count(*) != timestamp_diff(max(instante_utc), min(instante_utc), hour) + 1
