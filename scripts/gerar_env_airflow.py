"""Gera o `airflow/.env` com chaves aleatórias (o arquivo real fica fora do git).

    uv run python -m scripts.gerar_env_airflow

Não sobrescreve um arquivo existente (trocar as chaves invalidaria as sessões e os segredos que o
Airflow já cifrou). A URL do webhook do Discord fica vazia: cole-a no arquivo.
"""

import base64
import os
import secrets
import sys
from pathlib import Path

DESTINO = Path(__file__).resolve().parent.parent / "airflow" / ".env"


def gerar_conteudo(uid: int) -> str:
    fernet = base64.urlsafe_b64encode(os.urandom(32)).decode()  # formato da chave Fernet
    return (
        f"AIRFLOW_UID={uid}\n"
        f"AIRFLOW__CORE__FERNET_KEY={fernet}\n"
        f"AIRFLOW__API_AUTH__JWT_SECRET={secrets.token_urlsafe(48)}\n"
        f"AIRFLOW__API__SECRET_KEY={secrets.token_urlsafe(48)}\n"
        "DISCORD_WEBHOOK_URL=\n"
    )


def main() -> int:
    if DESTINO.exists():
        print(f"{DESTINO} já existe; não foi alterado.")
        return 0
    DESTINO.write_text(gerar_conteudo(os.getuid()))
    DESTINO.chmod(0o600)
    print(f"criado {DESTINO} (permissão 600). Cole a URL do webhook em DISCORD_WEBHOOK_URL.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
