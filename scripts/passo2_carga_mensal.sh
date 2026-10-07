#!/usr/bin/env bash
# Sprint 4, Parte B, passo 2: carrega o seed do ajuste e constrói o `fct_carga_mensal` no BigQuery,
# testa e reconcilia com a investigação. GRAVA NA NUVEM (dataset staging: 1 seed; marts: 1 tabela),
# de forma idempotente (seed e tabela são recriados). Nada é apagado. Da raiz do repositório:
#
#   bash scripts/passo2_carga_mensal.sh          # tudo: seed, mart, testes, reconciliação, bytes
#   bash scripts/passo2_carga_mensal.sh mart     # só o mart e os testes dele (o seed já está lá)
#
# Cada etapa registra em data/logs/passo2_*.log (tee). Os testes que falham NÃO interrompem a
# reconciliação nem a medição de bytes: o script roda tudo e sai com o código dos testes no fim.
set -Eeuo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
mkdir -p data/logs
set -a
. ./.env
set +a

registrar_erro() { echo "### ERRO (código $1) em ${BASH_SOURCE[0]##*/}, linha $2: $3" >&2; }
trap 'registrar_erro "$?" "$LINENO" "$BASH_COMMAND"' ERR

MODO="${1:-tudo}"
case "$MODO" in tudo | mart) ;; *) echo "uso: $0 [tudo|mart]"; exit 2 ;; esac

DBT="uv run --env-file .env dbt"
ARGS="--project-dir dbt --profiles-dir dbt"
L=data/logs/passo2
INICIO=$(date -u +%Y-%m-%dT%H:%M:%S)

if [ "$MODO" = "tudo" ]; then
    echo "== seed (staging.ajuste_definicao_carga)"
    $DBT seed $ARGS --select ajuste_definicao_carga 2>&1 | tee "${L}_seed.log"
fi

echo "== mart (marts.fct_carga_mensal)"
$DBT run $ARGS --select fct_carga_mensal 2>&1 | tee "${L}_run.log"

echo "== testes do mart$([ "$MODO" = "tudo" ] && echo " e do seed")"
if [ "$MODO" = "tudo" ]; then SELECAO="ajuste_definicao_carga fct_carga_mensal"; else SELECAO="fct_carga_mensal"; fi
CODIGO_TESTES=0
$DBT test $ARGS --select $SELECAO 2>&1 | tee "${L}_test.log" || CODIGO_TESTES=$?

echo "== reconciliação com a investigação (só leitura)"
uv run --env-file .env python -m scripts.conferir_carga_mensal 2>&1 | tee "${L}_conferir.log"

echo "== bytes processados e faturados desde o início (UTC $INICIO)"
uv run --env-file .env python -m scripts.medir_bytes_bigquery --desde "$INICIO" 2>&1 | tee "${L}_bytes.log"

echo "== testes do dbt: código de saída $CODIGO_TESTES"
exit "$CODIGO_TESTES"
