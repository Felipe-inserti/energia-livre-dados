# Projeto: Plataforma de Dados do Mercado Livre de Energia

Projeto de portfólio para vagas de estágio em engenharia de dados.
O plano completo está em docs/planejamento/ (planejamento e sprints). Siga as sprints na ordem.

## Regras
- NUNCA faça git commit, push, merge ou abra PR. Eu faço todos os commits manualmente.
- Você pode usar git status e git diff para conferir mudanças.
- Antes de criar ou alterar vários arquivos, diga o que vai fazer e espere meu ok.
- Explique o porquê de cada decisão técnica; quero conseguir defender tudo numa entrevista.
- Prefira a solução simples primeiro (ela é o "antes" das métricas).
- Ao fim de cada tarefa, diga o que medir e lembre de atualizar docs/metricas.md e docs/decisoes.md.
- Nunca coloque credenciais, chaves ou IDs sensíveis no código. Use variáveis de ambiente (.env, fora do git).
- Responda em português.

## Stack
Python 3.11+, uv, ruff, pytest, GCS, BigQuery, dbt-bigquery, Airflow (Docker), LightGBM, Streamlit.
GCP na região us-central1. Autenticação local via gcloud application-default login (sem arquivo de chave).
