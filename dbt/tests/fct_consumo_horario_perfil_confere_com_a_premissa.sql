{{ config(severity='error') }}
-- Valores do perfil escritos À MÃO a partir de premissas.md (40% de refrigeração, 60% de operação):
--   aberta, seg a sáb (N = 15 h): 0,4 + 0,6 × 24 / 15 = 1,36
--   aberta, domingo/feriado (N = 12 h): 0,4 + 0,6 × 24 / 12 = 1,6
--   fechada: 0,4
-- Independente da fórmula do modelo, de propósito. Se a premissa mudar, mude aqui e em premissas.md.
select
    instante_utc, data_local, hora_local, tipo_dia, loja_aberta, perfil
from {{ ref('fct_consumo_horario') }}
where abs(perfil - case
        when not loja_aberta then 0.4
        when tipo_dia = 'domingo_feriado' then 1.6
        else 1.36
    end) > 1e-9
