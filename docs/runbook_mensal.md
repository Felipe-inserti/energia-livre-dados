# Runbook mensal: a recomendação de contrato da origem de produção

Quando um mês **fecha** (o ONS publica o mês inteiro e a cobertura chega a 100%), a recomendação precisa ser atualizada. Sequência (Sprint 6, Parte C1), **manual por decisão** (sem DAG e sem rebuild de imagem; `decisoes.md`, "Sprint 6, Parte C"): **previsão → `gerar-producao` → `producao` → snapshot**. Tudo na raiz do repositório, com o ADC e o `.env` (`gcloud auth application-default login`; ver `docs/runbook_airflow.md`). Todo comando que grava tem `--dry-run` e é **idempotente** (MERGE por chave natural): repetir é seguro.

## 0. Antes
- Confirme que o mês fechou e há previsão nova: `uv run --env-file .env python -m ml.previsao verificar` (saída 0: mês novo para gerar; 10: nada novo). Normalmente a DAG já gerou (`previsao_mensal`).
- **Em dezembro:** a seed `dbt/seeds/pld_limites.csv` precisa dos limites do ano seguinte (a ANEEL os publica em dezembro). Sem isso a recomendação sai com `limites_assumidos = true` (repete os do último ano). Atualize a seed, `dbt seed` e o teste de faixa antes do passo 2.

## 1. Previsão (se a DAG ainda não gerou)
```bash
uv run --env-file .env python -m ml.previsao gerar --dry-run
uv run --env-file .env python -m ml.previsao gerar
```

## 2. Cenários só da origem nova
```bash
uv run --env-file .env python -m ml.cenarios gerar-producao --dry-run 2>&1 | tee data/logs/cenarios_producao_dry_run.log
uv run --env-file .env python -m ml.cenarios gerar-producao 2>&1 | tee data/logs/cenarios_producao.log
```
- Gera 24.000 linhas de consumo, 48.000 de PLD e 1 de execução da **origem mais recente**, com `execucao_id` próprio. **Nunca** escreve as 5 origens do backtest (recusa qualquer origem até 2024-12).
- O dry-run diz o estado: "ainda não gravada", "já gravada com este id (idempotente)", ou **"mesmos insumos … o id difere só pelo escopo"** / **"insumos DIFERENTES (campo)"** (só este indica insumo que mudou de fato; é um conjunto novo).
- Se a origem já está na execução congelada (é o caso de **2026-09**), ele termina com "nada a gravar". Nada a fazer; siga para o passo 3.
- Custo esperado (cache frio, estimativa): ~113 MiB faturados (`metricas.md`).

## 3. A prévia (ou a recomendação, em dezembro)
```bash
uv run --env-file .env python -m ml.recomendacao producao --dry-run 2>&1 | tee data/logs/recomendacao_producao_dry_run.log
uv run --env-file .env python -m ml.recomendacao producao 2>&1 | tee data/logs/recomendacao_producao.log
```
- Usa a **origem mais recente com previsão e cenários**, lê tudo do BigQuery e grava **só 3 linhas** (caso base) em `marts.fct_recomendacao_contrato`: `tipo = previa` (janela móvel de 12 meses, `ano_contrato` nulo) ou, se a origem é um dezembro, `tipo = producao` (`ano_contrato` = ano seguinte).
- **Leia os avisos.** `AVISO DE DEFASAGEM` (aparece no começo e se repete no fim): (a) "a previsão mais recente é de X, mas não há cenários para ela": volte ao passo 2; (b) "o último mês fechado é X, mas a previsão mais recente é de Y": volte ao passo 1. O comando grava a prévia da origem que tem cenários e avisa; o dashboard mostra o mesmo aviso.
- Conferência da contagem: a tabela cresce **3 linhas por origem nova** (213 hoje; 216 depois de 2026-10):
  `bq query --use_legacy_sql=false "SELECT COUNT(*) n FROM marts.fct_recomendacao_contrato" 2>&1 | tee data/logs/recomendacao_producao_contagem.log` (o mesmo comando que gerou o log de 213 linhas)
- Custo esperado (cache frio): ~108 MiB, dos quais 88 MiB de leitura (medido) e 20 MiB do MERGE.

## 4. Snapshot do dashboard (Parte C2; ainda não implementado)
```bash
uv run --env-file .env python -m dashboard.snapshot --dry-run
uv run --env-file .env python -m dashboard.snapshot
```
Regenera os CSV de `dashboard/dados/` e o `manifest.json` (lê o BigQuery, o `run_results.json` local e o Postgres do Airflow); depois **commite** o snapshot: o Community Cloud reimplanta a cada push. Mensal, junto com os passos acima.

## Se algo falhar
- `ABORTADO, nada foi gravado: … backtest`: a origem pedida é do backtest; a cadeia só grava origens posteriores a 2024-12.
- `nenhuma origem de produção tem previsão e cenários`: rode o passo 2 (e o 1, se faltar a previsão).
- `a previsão da origem … não tem os 12 horizontes`: a previsão está incompleta; rode `ml.previsao gerar --forcar` e repita.
- Qualquer erro no meio: reexecute o mesmo comando; as tabelas temporárias `staging.tmp_fct_*` são apagadas no `finally` e o MERGE não duplica.
