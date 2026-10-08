#!/usr/bin/env bash
# Sprint 5: rebuild do fct_carga_mensal com o arredondamento na origem (3 casas = 1 kW), testes do mart e
# prova de estabilidade bit a bit. GRAVA NA NUVEM (a tabela marts.fct_carga_mensal é recriada, 2 vezes).
# Da raiz do repositório:  bash scripts/passo_sprint5_estabilidade.sh   (log em data/logs/sprint5_estabilidade*.log)
set -Eeuo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
mkdir -p data/logs
set -a
. ./.env
set +a
trap 'echo "### ERRO (código $?) na linha $LINENO: $BASH_COMMAND" >&2' ERR
L=data/logs/sprint5_estabilidade
DBT="uv run --env-file .env dbt"
ARGS="--project-dir dbt --profiles-dir dbt"
py() { uv run --env-file .env python -m "$@"; }
{
  echo "== 0) foto ANTES (a tabela ainda tem as colunas sem arredondar)"
  py scripts.provar_estabilidade_carga_mensal foto "${L}_foto_0.json"
  echo "== 1) dbt run (1ª vez) + foto"
  $DBT run $ARGS --select fct_carga_mensal
  py scripts.provar_estabilidade_carga_mensal foto "${L}_foto_1.json"
  echo "== 2) dbt run (2ª vez) + foto"
  $DBT run $ARGS --select fct_carga_mensal
  py scripts.provar_estabilidade_carga_mensal foto "${L}_foto_2.json"
  echo "== 3) dbt run (3ª vez) + foto"
  $DBT run $ARGS --select fct_carga_mensal
  py scripts.provar_estabilidade_carga_mensal foto "${L}_foto_3.json"
  echo "== 4) as fotos 1, 2 e 3 têm de ser IDÊNTICAS bit a bit"
  py scripts.provar_estabilidade_carga_mensal comparar "${L}_foto_1.json" "${L}_foto_2.json" "${L}_foto_3.json"
  echo "== 4b) para comparação: a foto 0 (sem arredondar) contra a 1"
  py scripts.provar_estabilidade_carga_mensal comparar "${L}_foto_0.json" "${L}_foto_1.json" || true
  echo "== 5) o ARREDONDADO sobre a carga horária, 6 rodadas sem cache"
  py scripts.provar_estabilidade_carga_mensal avg 6
  echo "== 6) testes do mart (inclui a reconciliação com a horária na tolerância do arredondamento)"
  $DBT test $ARGS --select fct_carga_mensal
} 2>&1 | tee "${L}.log"
