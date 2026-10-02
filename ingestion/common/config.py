"""Configuração lida do .env.

O .env guarda só IDs não sensíveis (projeto, bucket, região). A autenticação é por ADC
(`gcloud auth application-default login`): não existe arquivo de chave.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parents[2]

VARIAVEIS_OBRIGATORIAS = ("GCP_PROJECT_ID", "GCS_BUCKET", "BQ_LOCATION")

# Datasets do BigQuery (decisão já tomada: não mudam por ambiente)
DATASET_RAW = "raw"
DATASET_STAGING = "staging"
DATASET_MARTS = "marts"


@dataclass(frozen=True)
class Config:
    projeto: str
    bucket: str
    localizacao: str

    def tabela(self, dataset: str, nome: str) -> str:
        """Identificador completo de uma tabela: projeto.dataset.nome."""
        return f"{self.projeto}.{dataset}.{nome}"


def carregar_config(ambiente: Mapping[str, str] | None = None) -> Config:
    """Lê a configuração do ambiente (e do .env, quando `ambiente` não é passado).

    Falta de variável gera erro que lista só os NOMES ausentes, nunca valores.
    """
    if ambiente is None:
        load_dotenv(RAIZ / ".env")  # variáveis já definidas no ambiente têm prioridade
        ambiente = os.environ
    faltando = [v for v in VARIAVEIS_OBRIGATORIAS if not ambiente.get(v, "").strip()]
    if faltando:
        raise ValueError(
            "Variáveis de ambiente ausentes ou vazias: "
            + ", ".join(faltando)
            + " (copie .env.example para .env e preencha)"
        )
    return Config(
        projeto=ambiente["GCP_PROJECT_ID"].strip(),
        bucket=ambiente["GCS_BUCKET"].strip(),
        localizacao=ambiente["BQ_LOCATION"].strip(),
    )
