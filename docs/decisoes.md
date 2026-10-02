# Registro de decisões

## Região do GCP: us-central1
Contexto: o projeto precisa de GCS e BigQuery com custo próximo de zero (teto pessoal de R$ 10/mês).
Opções: southamerica-east1 (São Paulo, mais perto dos dados) ou us-central1.
Escolha: us-central1, porque o armazenamento gratuito do GCS só vale em regiões dos EUA. Latência não importa para um pipeline batch diário.
Resultado: GCS e BigQuery na mesma região (necessário para carregar do bucket direto no BigQuery), dentro da camada gratuita.

## Autenticação local sem arquivo de chave
Contexto: scripts locais precisam acessar GCS e BigQuery.
Opções: chave JSON de conta de serviço ou Application Default Credentials (gcloud auth application-default login).
Escolha: ADC. Não existe arquivo de chave, então não há risco de vazar credencial no GitHub.
Resultado: nenhuma credencial no repositório; .env guarda apenas IDs não sensíveis.

## Controle de custo
Contexto: alerta de orçamento só avisa, não bloqueia gastos.
Opções: só alerta de orçamento, ou alerta + limite rígido de consultas.
Escolha: alerta de R$ 10/mês (50%, 90%, 100%) + cota de ~51 GiB/dia de consultas no BigQuery (antes: 200 TiB/dia, o padrão).
Resultado: pior caso limitado mesmo com uma consulta mal feita rodando em loop.

## Gerenciador de ambiente: uv, sem empacotar o projeto
Contexto: precisa de ambiente Python reprodutível, com dependências travadas, e simples de recriar em outra máquina e no CI.
Opções: pip + venv + requirements.txt, poetry, ou uv.
Escolha: uv. Um só comando (`uv sync`) cria o ambiente a partir do `uv.lock` versionado, é bem mais rápido que pip/poetry e baixa a versão de Python fixada em `.python-version` (3.12). Usei `package = false` porque o projeto é um conjunto de scripts, não uma biblioteca; assim não há `src/` nem build-system. Python 3.12 e não o 3.14 do sistema porque Airflow e dbt costumam demorar a suportar versões recentes. Dependências de desenvolvimento (pytest, ruff) ficam num grupo `dev`, separadas das de runtime.
Resultado: ambiente reproduzível com `uv sync`; lint e testes via `uv run`.

## Fuso horário em séries horárias
Contexto: ONS e PLD publicam em horário de Brasília; o INMET publica em UTC. Para juntar carga, PLD e temperatura na mesma hora, é preciso um fuso único.
Opções: (A) tudo em horário de Brasília; (B) tudo em UTC; (C) offset fixo de -3h.
Escolha: B, com conversão no staging do dbt usando o fuso `America/Sao_Paulo` (não offset fixo). UTC não tem horário de verão nem ambiguidade; o fuso nomeado continua correto se o horário de verão voltar (foi abolido em 2019, então 2021+ não tem hora faltando nem repetida). Conversão para horário local só na apresentação. A origem do ONS é Brasília por inferência (mínimo da carga às 03–04h); a confirmação no dicionário de dados do ONS está pendente.
Resultado: três fontes em dois fusos alinhadas sem ambiguidade. A bronze e o raw guardam o horário original.

## Formato do bruto no GCS: arquivo original, sem alteração
Contexto: o layout da CCEE muda entre anos (2021–2024 usa aspas, CRLF e zeros à esquerda; 2025–2026 não), e ONS e CCEE revisam dados antigos.
Opções: (A) guardar o arquivo original (CSV/ZIP); (B) converter para Parquet antes de gravar.
Escolha: A. A bronze mantém o arquivo exatamente como veio da fonte, o que permite reprocessar quando o layout mudar ou quando eu errar uma regra de limpeza, sem baixar de novo (os portais bloqueiam parte dos downloads). Parquet exigiria normalizar antes de salvar, e isso apagaria justamente a evidência que preciso guardar. O Python faz só o mínimo para carregar no BigQuery `raw`: pular as 8 linhas de metadados do INMET, padronizar nomes de colunas, e adicionar `_arquivo_origem` e `_carregado_em`. Tipagem e limpeza ficam no dbt (staging).
Resultado: bronze auditável e `raw` sem lógica de negócio. O custo é armazenar mais bytes (CSV é maior que Parquet), irrelevante neste volume (~2,5 MB/ano para ONS e CCEE).

## Consumo do consumidor-exemplo: perfil sintético
Contexto: a seção 2 previa usar o consumo por ramo da CCEE se estivesse em granularidade horária.
Opções: (A) usar o dado da CCEE como curva; (B) construir um perfil sintético; (C) procurar outra fonte.
Escolha: B. Na exploração, o dataset `CONSUMO_RAMO_ATIVIDADE` mostrou ser mensal, agregado por ramo (15 ramos) e disponível só de abr/2024 em diante, então não gera curva horária. O perfil sintético será construído a partir da carga do SE/CO, horário de funcionamento do supermercado e sensibilidade à temperatura (refrigeração), com o nível e a sazonalidade mensal calibrados pelo ramo COMÉRCIO da CCEE. Toda premissa vai para `docs/premissas.md`.
Resultado: o risco da seção 13 se confirmou antes de escrever qualquer extrator, e a premissa fica explícita e defensável em vez de escondida num dado que não serve.

## Dados da CCEE por download manual no histórico
Contexto: o portal da CCEE devolve 403 "Acesso bloqueado" para downloads e para a API CKAN feitos por script.
Opções: (A) contornar o bloqueio (por exemplo, simulando um navegador); (B) baixar o histórico manualmente e automatizar só a atualização; (C) pedir liberação à CCEE.
Escolha: B para o histórico 2021–2025 (arquivos fechados que não mudam de layout nem de conteúdo). A página diz que o bloqueio decorre de política de segurança, então não vou burlá-lo. A atualização automática do ano corrente fica para a tarefa 1.7, onde se testa o acesso de verdade e se decide o plano se continuar bloqueado.
Resultado: o histórico não depende do bloqueio. Risco aceito: se o acesso automático não funcionar, o pipeline diário (Sprint 3) precisa de outra forma de obter o PLD do ano corrente.

## Estações do INMET e temperatura do submercado
Contexto: o INMET publica ~565 estações por ano, com completude muito diferente entre elas (na temperatura de 2024: 0% de nulos em Bauru, 36,6% no Rio Copacabana) e a rede muda de um ano para o outro. Uma estação boa pode degradar: a A652 (Copacabana) tinha 100% de horas válidas em 2021 e 63,4% em 2024. Além disso, o número de estações por estado é muito desigual (30 em MG contra 7 em SP, entre as que passam no critério), então uma média simples entre estações distorceria o resultado.
Opções: (A) escolher estações por cidade (as capitais); (B) escolher por completude e tirar a média simples de todas; (C) escolher por completude e agregar em dois passos, com peso por estado; (D) usar todas as estações e deixar a falta para o modelo.
Escolha: C. Entram as estações do Sudeste (ES, MG, RJ, SP) e do Centro-Oeste (DF, GO, MS, MT) com pelo menos 95% de horas válidas de temperatura em cada ano analisado (hora ausente no arquivo conta como inválida). A temperatura do submercado SE/CO sai em dois passos: (1) média horária das estações dentro de cada estado, tolerante a falhas (numa hora, usa só as estações com dado, em vez de anular o valor se uma falhar); (2) média entre estados ponderada pelo peso de cada estado no consumo de energia do submercado, com pesos de fonte oficial (ex.: Anuário Estatístico de Energia Elétrica da EPE). Escolher por cidade deixaria de fora estações confiáveis e incluiria estações que falham meses seguidos; a média simples entre estações daria a MG um peso desproporcional ao seu consumo. A implementação fica para a Sprint 2 (staging/intermediate).
Resultado: com 2021 e 2024, 73 de 240 estações do SE/CO passam (ES 5, MG 30, RJ 12, SP 7, DF 4, GO 9, MS 5, MT 1). A lista ainda será recalculada com 2022, 2023 e 2025 e só pode encolher. Pendente: fonte, ano e valores dos pesos por estado (vão para `docs/premissas.md`). Risco conhecido: o MT tem uma única estação aprovada (Alto Taquari, 95,6% em 2024), então a média do estado depende dela; e falta definir a renormalização dos pesos quando um estado ficar sem dado numa hora.
