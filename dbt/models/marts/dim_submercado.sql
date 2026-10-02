{#
  Os 4 submercados do SIN e a correspondência entre os códigos do ONS e os nomes da CCEE
  (docs/premissas.md): SE/CO = `SE` (ONS) = `SUDESTE` (CCEE), e assim por diante.

  Dado de referência escrito aqui mesmo (4 linhas que não mudam), sem `dbt seed`. A chave é o
  código do ONS, que é estável; o NOME do ONS não é: o `SE` se chamava `SUDESTE` até 31/12/2025 e
  passou a `SUDESTE/CENTRO-OESTE` a partir de 01/01/2026 (por isso `nomes_ons` é uma lista). As
  fontes se ligam por código (ONS: `id_subsistema`) ou por nome (CCEE: `submercado`).
#}
select *
from unnest([
    struct(
        'SE' as codigo_submercado,
        'SUDESTE' as nome_ccee,
        ['SUDESTE/CENTRO-OESTE', 'SUDESTE'] as nomes_ons,
        'SE/CO' as rotulo
    ),
    struct('S', 'SUL', ['SUL'], 'S'),
    struct('NE', 'NORDESTE', ['NORDESTE'], 'NE'),
    struct('N', 'NORTE', ['NORTE'], 'N')
])
