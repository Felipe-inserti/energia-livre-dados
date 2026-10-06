# Imagem do Airflow do projeto. Duas camadas de Python, de propósito:
#  - o Python do Airflow (3.3.2) roda só o orquestrador e as funções de ingestion/orquestracao.py;
#  - o venv /opt/projeto-venv, criado do uv.lock (as MESMAS versões testadas na máquina), roda a
#    ingestão e o dbt. O dbt-bigquery exige google-cloud-storage<3.2 e protobuf<7, que brigariam com
#    as restrições do Airflow se ficassem no mesmo ambiente (docs/decisoes.md).
# Contexto de build: a raiz do repositório (o .dockerignore deixa passar só o que o build usa).
FROM apache/airflow:3.3.2-python3.12

ENV UV_PROJECT_ENVIRONMENT=/opt/projeto-venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy

USER root
RUN mkdir -p /opt/projeto-venv && chown airflow:0 /opt/projeto-venv && chmod -R g=u /opt/projeto-venv
USER airflow

RUN pip install --no-cache-dir uv

COPY --chown=airflow:0 pyproject.toml uv.lock .python-version /tmp/projeto/
# Só o grupo `dbt` mais as dependências de execução; sem pytest, ruff nem notebook
RUN cd /tmp/projeto \
    && uv sync --frozen --no-default-groups --group dbt \
    && rm -rf /tmp/projeto \
    && chmod -R g=u /opt/projeto-venv
