#!/usr/bin/env bash
# Sprint 5, Parte A: carrega o seed carga_mensal_ons, reconstrói fct_carga_mensal e roda os testes do
# modelo. GRAVA NA NUVEM (seed e mart de produção; mudança aditiva: colunas novas, nenhuma alterada).
# Uso: bash scripts/passo_sprint5_dbt.sh   (log em data/logs/sprint5_dbt.log)
set -Eeuo pipefail
cd "$(dirname "$0")/.."
mkdir -p data/logs
trap 'echo "FALHOU: linha $LINENO: $BASH_COMMAND (código $?)" | tee -a data/logs/sprint5_dbt.log' ERR
{
  echo "== $(date -u +%FT%TZ) dbt seed carga_mensal_ons"
  uv run --env-file .env dbt seed --project-dir dbt --profiles-dir dbt --select carga_mensal_ons
  echo "== dbt run fct_carga_mensal"
  uv run --env-file .env dbt run --project-dir dbt --profiles-dir dbt --select fct_carga_mensal
  echo "== dbt test (modelo e seed)"
  uv run --env-file .env dbt test --project-dir dbt --profiles-dir dbt --select fct_carga_mensal carga_mensal_ons
} 2>&1 | tee -a data/logs/sprint5_dbt.log
