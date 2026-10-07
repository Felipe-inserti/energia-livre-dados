{{ config(severity='error') }}
-- Todo mês fechado precisa ter cobertura (horas válidas / horas esperadas em hora local) de pelo menos
-- `cobertura_minima`, e nunca acima de 100% (se passasse, a contagem das horas esperadas estaria
-- errada, como estava quando fevereiro parecia ter 1 hora faltando). Abaixo do limiar, o mês não
-- serve de alvo nem de treino e a causa tem de ser investigada, não escondida.
select codigo_submercado, mes, horas_esperadas, horas_com_linha, horas_validas, cobertura
from {{ ref('fct_carga_mensal') }}
where not mes_incompleto
    and (cobertura < {{ var('cobertura_minima') }} or cobertura > 1)
