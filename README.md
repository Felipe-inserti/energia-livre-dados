# energia-livre-dados

## Como configurar o ambiente

```bash
uv sync                      # cria .venv e instala as dependências (Python 3.12)
cp .env.example .env         # preencha GCP_PROJECT_ID e GCS_BUCKET
gcloud auth application-default login
uv run pytest                # testes
uv run ruff check .          # lint
uv run ruff format .         # formatação
```

### dbt

```bash
cp dbt/profiles.yml.example dbt/profiles.yml   # perfil local (fica fora do git)
uv run --env-file .env dbt deps  --project-dir dbt --profiles-dir dbt   # instala o dbt_utils
uv run --env-file .env dbt debug --project-dir dbt --profiles-dir dbt   # confere a conexão
```
