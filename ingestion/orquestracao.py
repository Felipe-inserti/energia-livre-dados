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
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import requests

RAIZ = Path(__file__).resolve().parents[1]
PASTA_ESTADO = RAIZ / "data" / "estado"
FONTES_MANUAIS = {
    "ccee": (RAIZ / "data" / "manual" / "ccee", "*.csv"),
    "inmet": (RAIZ / "data" / "manual" / "inmet", "*.zip"),
}

# Seleção do dbt por fonte (Sprint 4, 4b). `fonte+` seleciona a fonte e TUDO que descende dela:
# modelos e testes, inclusive os que cruzam fontes (ex.: fct_submercado_horario e o teste que o
# confere descendem das três). Logo, quando QUALQUER fonte envolvida muda, o teste roda.
SELECAO_ONS = ["source:raw.ons_curva_carga+"]
SELECAO_INMET = ["source:raw.inmet_estacoes_horario+"]
SELECAO_CCEE = [
    "source:raw.ccee_pld_horario+",
    "source:raw.ccee_pld_semanal+",
    "source:raw.ccee_consumo_ramo_atividade+",
]
# O teste do alerta (3.7) não descende de fonte nenhuma, mas a DAG precisa dele sempre.
TESTE_ALERTA = "teste_alerta_falha_proposital"
LIMITE_DISCORD = 1900  # o Discord recusa mensagens com mais de 2000 caracteres


PADRAO_MES = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
VERDADEIROS = {"true", "1", "sim", "yes"}


def data_referencia(
    data_interval_end: datetime | None = None,
    logical_date: datetime | None = None,
    run_after: datetime | None = None,
) -> str:
    """Data (UTC, AAAA-MM-DD) que ancora a janela da execução (nunca o relógio da task).

    Na execução agendada vale o fim do intervalo de dados (`data_interval_end`); em execução manual
    o Airflow 3 pode não ter intervalo nem `logical_date`, e vale o `run_after` (o instante em que a
    execução foi criada, gravado na própria execução). Reexecutar (clear) a mesma execução dá, por
    isso, a mesma janela.
    """
    for candidato in (data_interval_end, logical_date, run_after):
        if candidato is not None:
            return candidato.astimezone(UTC).date().isoformat()
    raise ValueError("sem data_interval_end, logical_date nem run_after: não há data de referência")


def _verdadeiro(valor) -> bool:
    if isinstance(valor, str):
        return valor.strip().lower() in VERDADEIROS
    return bool(valor)


def _texto_ou_none(valor) -> str | None:
    texto = None if valor is None else str(valor).strip()
    return texto or None


def parametros_da_execucao(
    *,
    data_interval_end: datetime | None,
    logical_date: datetime | None,
    run_after: datetime | None,
    params: dict,
    conf: dict,
    run_id: str,
) -> dict:
    """Decide o modo da execução (janela diária ou backfill) a partir da data e da configuração.

    `conf` (o JSON do `airflow dags trigger -c`) vale mais que `params` (os padrões da DAG). O
    backfill é `desde`/`ate` (AAAA-MM, inclusive, os dois juntos). Tudo é VALIDADO aqui porque vira
    texto de linha de comando (a conf vem de quem dispara a execução). Devolve só texto e booleanos,
    para ir por XCom.
    """
    desde = _texto_ou_none(conf.get("desde", params.get("desde")))
    ate = _texto_ou_none(conf.get("ate", params.get("ate")))
    if bool(desde) != bool(ate):
        raise ValueError("backfill: informe 'desde' e 'ate' juntos (AAAA-MM)")
    if desde and not (PADRAO_MES.match(desde) and PADRAO_MES.match(ate)):
        raise ValueError(f"backfill: use AAAA-MM, recebi desde={desde!r} ate={ate!r}")
    if desde and ate < desde:
        raise ValueError(f"backfill: 'ate' ({ate}) anterior a 'desde' ({desde})")
    referencia = data_referencia(data_interval_end, logical_date, run_after)
    seguro = re.sub(r"[^A-Za-z0-9_.-]", "_", run_id)
    return {
        "modo": "backfill" if desde else "janela",
        "referencia": referencia,
        "desde": desde or "",
        "ate": ate or "",
        "argumentos_ons": f"--desde {desde} --ate {ate}"
        if desde
        else f"--data-referencia {referencia}",
        # um arquivo de vars POR execução: limpar só o dbt_run de uma execução antiga não lê as vars
        # de outra
        "arquivo_vars": f"data/estado/ons_vars_{seguro}.json",
        "completa": _verdadeiro(
            conf.get("execucao_completa", params.get("execucao_completa", False))
        ),
    }


def checar_arquivo_novo(pasta: Path, padrao: str, estado: Path, ti) -> bool:
    """`ha_arquivo_novo` que também GRAVA o resultado no XCom (chave `novo`) para a seleção do dbt.

    O XCom explícito evita depender de o ShortCircuitOperator guardar o booleano no `return_value`.
    """
    novo = ha_arquivo_novo(pasta, padrao, estado)
    ti.xcom_push(key="novo", value=bool(novo))
    return novo


# Previsão mensal (Sprint 5). A DAG roda no Python do Airflow, que não tem pandas nem statsmodels:
# a pergunta "fechou um mês novo?" vai ao venv do projeto (`python -m ml.previsao verificar`), que
# responde pelo código de saída: 0 = há mês novo, 10 = não há, qualquer outro = erro de verdade.
PYTHON_DO_PROJETO = "/opt/projeto-venv/bin/python"
SAIDA_MES_NOVO = 0
SAIDA_SEM_MES_NOVO = 10


def checar_mes_novo(
    python: str = PYTHON_DO_PROJETO, cwd: Path | str = "/opt/projeto", executar=subprocess.run, **_
) -> bool:
    """ShortCircuit da previsão: True só se o último mês completo é posterior à última origem."""
    r = executar(
        [python, "-m", "ml.previsao", "verificar"], cwd=cwd, capture_output=True, text=True
    )
    saida = (r.stdout or "").strip()
    if saida:
        print(saida)
    if r.returncode == SAIDA_MES_NOVO:
        return True
    if r.returncode == SAIDA_SEM_MES_NOVO:
        return False
    raise RuntimeError(
        f"ml.previsao verificar falhou (código {r.returncode}): {(r.stderr or '')[-800:]}"
    )


def selecao_da_execucao(
    ccee_novo: bool = False, inmet_novo: bool = False, completa: bool = False
) -> dict:
    """Argumentos `--select ...` do `dbt run` e do `dbt test` da execução.

    Normal: o ONS sempre (mais o INMET e a CCEE quando houve arquivo novo) e, nos testes, o teste
    do alerta. `completa=True` (conf `execucao_completa`): sem seleção, o dbt roda tudo, inclusive
    os 62 testes de calendário, seeds e dimensões estáticas que nenhuma fonte seleciona.
    """
    if completa:
        return {"run": "", "test": "", "fontes": "todas (execução completa)"}
    fontes = ["ons", *(["inmet"] if inmet_novo else []), *(["ccee"] if ccee_novo else [])]
    return {
        "run": "--select " + " ".join(selecao_dbt(ccee_novo, inmet_novo)),
        "test": "--select " + " ".join(selecao_dbt_teste(ccee_novo, inmet_novo)),
        "fontes": "+".join(fontes),
    }


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


def selecao_dbt(ccee_novo: bool = False, inmet_novo: bool = False) -> list[str]:
    """Seletores do `dbt run`/`build`: o ONS sempre (automático e diário); o INMET e a CCEE só
    quando houve arquivo novo (são manuais), para não reconstruir ~800 MB sem dado novo."""
    return [
        *SELECAO_ONS,
        *(SELECAO_INMET if inmet_novo else []),
        *(SELECAO_CCEE if ccee_novo else []),
    ]


def selecao_dbt_teste(ccee_novo: bool = False, inmet_novo: bool = False) -> list[str]:
    """Mesma seleção para o `dbt test`, mais o teste do alerta, que a DAG roda sempre."""
    return [*selecao_dbt(ccee_novo, inmet_novo), TESTE_ALERTA]


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
        print("alerta no Discord enviado", file=sys.stderr)  # prova no log da task; sem a URL
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
    if comando in ("selecao-dbt", "selecao-dbt-teste") and set(args) <= {"ccee", "inmet"}:
        funcao = selecao_dbt if comando == "selecao-dbt" else selecao_dbt_teste
        print(" ".join(funcao(ccee_novo="ccee" in args, inmet_novo="inmet" in args)))
        return 0
    if comando == "testar-alerta":
        ok = alertar_falha({"exception": "teste do alerta (nenhuma falha de verdade)"})
        print("mensagem enviada" if ok else "mensagem NÃO enviada")
        return 0 if ok else 1
    print(
        "uso: registrar-estado ccee|inmet [...] | selecao-dbt[-teste] [ccee] [inmet] "
        "| testar-alerta"
    )
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
