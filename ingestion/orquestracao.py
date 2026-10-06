"""Funções da DAG diária do Airflow que não dependem do Airflow: testáveis sem container.

Tudo aqui usa só a biblioteca padrão e `requests` (a DAG roda no Python do Airflow, que não tem
as dependências do projeto; o dbt e a ingestão rodam no venv `/opt/projeto-venv`).

- **Arquivo novo na pasta manual** (CCEE e INMET são baixados à mão): a "impressão digital" de
  cada arquivo (nome, tamanho e data de modificação) é comparada com a do último carregamento
  bem-sucedido, guardada em `data/estado/<fonte>.json`. Tamanho + data e não hash, porque os ZIPs
  do INMET somam 536 MB.
- **Alerta de falha** no webhook do Discord (`DISCORD_WEBHOOK_URL`, segredo: só no `.env`).

    uv run python -m ingestion.orquestracao registrar-estado ccee inmet
    uv run --env-file airflow/.env python -m ingestion.orquestracao testar-alerta
"""

import json
import os
import sys
from pathlib import Path

import requests

RAIZ = Path(__file__).resolve().parents[1]
PASTA_ESTADO = RAIZ / "data" / "estado"
FONTES_MANUAIS = {
    "ccee": (RAIZ / "data" / "manual" / "ccee", "*.csv"),
    "inmet": (RAIZ / "data" / "manual" / "inmet", "*.zip"),
}
LIMITE_DISCORD = 1900  # o Discord recusa mensagens com mais de 2000 caracteres


def impressao_digital(pasta: Path, padrao: str) -> dict[str, list[int]]:
    """Nome -> [tamanho em bytes, data de modificação em ns] de cada arquivo da pasta."""
    return {
        arquivo.name: [arquivo.stat().st_size, arquivo.stat().st_mtime_ns]
        for arquivo in sorted(pasta.glob(padrao))
        if arquivo.is_file()
    }


def _ler_estado(caminho: Path) -> dict | None:
    try:
        return json.loads(caminho.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def ha_arquivo_novo(pasta: Path, padrao: str, estado: Path) -> bool:
    """Verdadeiro se a pasta mudou desde o último carregamento registrado.

    Sem estado registrado, é verdadeiro (nunca carreguei por aqui). Pasta sem arquivos é falso:
    não há o que carregar (e a carga reclamaria dos arquivos ausentes).
    """
    atual = impressao_digital(pasta, padrao)
    if not atual:
        return False
    return _ler_estado(estado) != atual


def registrar_estado(pasta: Path, padrao: str, estado: Path) -> dict[str, list[int]]:
    """Grava a impressão digital atual (de forma atômica). Só chamar depois de a carga dar certo."""
    atual = impressao_digital(pasta, padrao)
    estado.parent.mkdir(parents=True, exist_ok=True)
    temporario = estado.with_suffix(".tmp")
    temporario.write_text(json.dumps(atual, indent=2, sort_keys=True))
    temporario.replace(estado)
    return atual


def montar_mensagem_falha(
    *,
    dag_id: str,
    task_id: str,
    run_id: str,
    tentativa: int,
    max_tentativas: int,
    erro: str,
    url: str,
) -> str:
    """Texto do alerta: o que quebrou, em qual execução, depois de quantas tentativas e o erro."""
    erro = " ".join(str(erro).split()) or "(sem mensagem)"

    def formatar(detalhe: str) -> str:
        return (
            f":red_circle: **Falha no pipeline** `{dag_id}`\n"
            f"- task: `{task_id}` (tentativa {tentativa} de {max_tentativas}, "
            "sem mais retentativas)\n"
            f"- execução: `{run_id}`\n"
            f"- erro: {detalhe}\n"
            f"- log: {url}"
        )

    texto = formatar(erro)
    if len(texto) > LIMITE_DISCORD:  # o erro é o único trecho de tamanho livre: é ele que encolhe
        corte = max(len(erro) - (len(texto) - LIMITE_DISCORD) - 3, 20)
        texto = formatar(erro[:corte] + "...")
    return texto[:LIMITE_DISCORD]


def enviar_discord(webhook: str, texto: str, *, timeout: float = 10.0) -> bool:
    """POST no webhook. Nunca levanta exceção (um alerta que quebra esconde a falha que ele avisa)
    e nunca imprime a URL, que é um segredo."""
    try:
        resposta = requests.post(
            webhook,
            json={"content": texto, "allowed_mentions": {"parse": []}},
            timeout=timeout,
        )
        resposta.raise_for_status()
        return True
    except requests.RequestException as erro:
        print(f"alerta no Discord não enviado: {type(erro).__name__}", file=sys.stderr)
        return False


def alertar_falha(contexto: dict) -> bool:
    """`on_failure_callback` do Airflow: roda quando a task falha de vez (sem retentativas)."""
    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook:
        print("DISCORD_WEBHOOK_URL vazia: alerta não enviado", file=sys.stderr)
        return False
    ti = contexto.get("task_instance")
    dag_id = getattr(ti, "dag_id", None) or getattr(contexto.get("dag"), "dag_id", "?")
    task_id = getattr(ti, "task_id", "?")
    run_id = getattr(ti, "run_id", None) or str(contexto.get("run_id", "?"))
    base = os.environ.get("AIRFLOW_UI_URL", "http://localhost:8080").rstrip("/")
    texto = montar_mensagem_falha(
        dag_id=dag_id,
        task_id=task_id,
        run_id=run_id,
        tentativa=int(getattr(ti, "try_number", 0) or 0),
        max_tentativas=int(getattr(ti, "max_tries", 0) or 0) + 1,
        erro=str(contexto.get("exception", "")),
        url=f"{base}/dags/{dag_id}/runs/{run_id}/tasks/{task_id}",
    )
    return enviar_discord(webhook, texto)


def main(argv: list[str]) -> int:
    comando, *args = argv or ["ajuda"]
    if comando == "registrar-estado" and args and set(args) <= set(FONTES_MANUAIS):
        for fonte in args:
            pasta, padrao = FONTES_MANUAIS[fonte]
            atual = registrar_estado(pasta, padrao, PASTA_ESTADO / f"{fonte}.json")
            print(f"{fonte}: estado registrado com {len(atual)} arquivos")
        return 0
    if comando == "testar-alerta":
        ok = alertar_falha({"exception": "teste do alerta (nenhuma falha de verdade)"})
        print("mensagem enviada" if ok else "mensagem NÃO enviada")
        return 0 if ok else 1
    print("uso: registrar-estado ccee|inmet [...] | testar-alerta")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
