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
Escolha: B, com conversão no staging do dbt usando o fuso `America/Sao_Paulo` (não offset fixo). UTC não tem horário de verão nem ambiguidade; o fuso nomeado continua correto se o horário de verão voltar (foi abolido em 2019, então 2021+ não tem hora faltando nem repetida). Conversão para horário local só na apresentação. O ONS está no horário oficial local, acompanhando o relógio e com horário de verão até 2018: confirmado na tarefa 1.10 porque o perfil diário da carga não se desloca no início do horário de verão em nenhum dos 25 anos testados, e a linha de 00:00 do dia de início não existe (2000–2013) ou vem nula (2014–2018). Isso reforça a escolha do fuso nomeado em vez de offset fixo. A confirmação no dicionário de dados do ONS não foi feita.
Resultado: três fontes em dois fusos alinhadas sem ambiguidade. A bronze e o raw guardam o horário original.

## Formato do bruto no GCS: arquivo original, sem alteração
Contexto: o layout da CCEE muda entre anos (2021–2024 usa aspas, CRLF e zeros à esquerda; 2025–2026 não), e ONS e CCEE revisam dados antigos.
Opções: (A) guardar o arquivo original (CSV/ZIP); (B) converter para Parquet antes de gravar.
Escolha: A. A bronze mantém o arquivo exatamente como veio da fonte, o que permite reprocessar quando o layout mudar ou quando eu errar uma regra de limpeza, sem baixar de novo (os portais bloqueiam parte dos downloads). Parquet exigiria normalizar antes de salvar, e isso apagaria justamente a evidência que preciso guardar. O Python faz só o mínimo para carregar no BigQuery `raw`: pular as 8 linhas de metadados do INMET, padronizar nomes de colunas, e adicionar `_arquivo_origem` e `_carregado_em`. Tipagem e limpeza ficam no dbt (staging).
Resultado: bronze auditável e `raw` sem lógica de negócio. O custo é armazenar mais bytes (CSV é maior que Parquet), irrelevante neste volume (~2,5 MB/ano para ONS e CCEE).

## Consumo do consumidor-exemplo: perfil sintético
Contexto: a seção 2 do planejamento previa usar o consumo por ramo da CCEE se estivesse em granularidade horária.
Opções: (A) usar o dado da CCEE como curva; (B) construir um perfil sintético; (C) procurar outra fonte.
Escolha: B. Na exploração, o dataset `CONSUMO_RAMO_ATIVIDADE` mostrou ser mensal, agregado por ramo (15 ramos) e disponível só de abr/2024 em diante, então não gera curva horária. A curva é `consumo_h = k × carga média diária do SE/CO (ONS, real) × perfil_loja(hora, tipo de dia)`, com perfil de 40% refrigeração constante e 60% operação no horário da loja, normalizado para média 1 no dia, e um único `k` para todo o período (100 MWh/mês em média). Sem ruído aleatório e sem temperatura na curva. O ramo COMÉRCIO da CCEE serve só como checagem de plausibilidade da sazonalidade. Toda premissa vai para `docs/premissas.md`.
Resultado: o risco da seção 13 se confirmou antes de escrever qualquer extrator. Como a curva é proporcional à carga real, prever a carga mensal do SE/CO é prever o consumo do consumidor (ver "Alvo da previsão").

## Dados da CCEE por download manual no histórico
Contexto: o portal da CCEE devolve 403 "Acesso bloqueado" para downloads e para a API CKAN feitos por script.
Opções: (A) contornar o bloqueio (por exemplo, simulando um navegador); (B) baixar o histórico manualmente e automatizar só a atualização; (C) pedir liberação à CCEE.
Escolha: B para o histórico 2021–2025 (arquivos fechados que não mudam de layout nem de conteúdo). A página diz que o bloqueio decorre de política de segurança, então não vou burlá-lo. A atualização automática do ano corrente fica para a tarefa 1.7, onde se testa o acesso de verdade e se decide o plano se continuar bloqueado.
Resultado: o histórico não depende do bloqueio. Risco aceito: se o acesso automático não funcionar, o pipeline diário (Sprint 3) precisa de outra forma de obter o PLD do ano corrente.

## Estações do INMET e temperatura do submercado
Contexto: o INMET publica ~565 estações por ano, com completude muito diferente entre elas (na temperatura de 2024: 0% de nulos em Bauru, 36,6% no Rio Copacabana) e a rede muda de um ano para o outro. Uma estação boa pode degradar: a A652 (Copacabana) tinha 100% de horas válidas em 2021 e 63,4% em 2024. Além disso, o número de estações por estado é muito desigual (30 em MG contra 7 em SP, entre as que passam no critério), então uma média simples entre estações distorceria o resultado.
Opções: (A) escolher estações por cidade (as capitais); (B) escolher por completude e tirar a média simples de todas; (C) escolher por completude e agregar em dois passos, com peso por estado; (D) usar todas as estações e deixar a falta para o modelo.
Escolha: C. Entram as estações do Sudeste (ES, MG, RJ, SP) e do Centro-Oeste (DF, GO, MS) com pelo menos 95% de horas válidas de temperatura em cada ano analisado (hora ausente no arquivo conta como inválida). O **MT fica excluído**: só 1 estação passa no critério (Alto Taquari, 95,6% em 2024), então a média do estado dependeria dela; o peso do MT é redistribuído entre os demais. A temperatura do submercado sai em dois passos: (1) média horária das estações dentro de cada estado, tolerante a falhas, com imputação dentro do próprio estado quando faltar dado numa hora (hora anterior ou perfil típico do dia), em vez de redistribuir pesos, o que criaria saltos de temperatura; (2) média entre estados ponderada pelo peso de cada estado no consumo de energia do submercado, com pesos de fonte oficial (ex.: Anuário Estatístico de Energia Elétrica da EPE). Escolher por cidade deixaria de fora estações confiáveis e incluiria estações que falham meses seguidos; a média simples daria a MG um peso desproporcional ao seu consumo. O INMET é usado de 2021 em diante, como **variável de análise de erro** da previsão (ondas de calor), e não como insumo da curva nem da previsão de 12 meses. A implementação fica para a Sprint 2, e a agregação com pesos é candidata a corte (ver "Se atrasar" nas sprints).
Resultado: com 2021 e 2024, 73 de 240 estações do SE/CO passam (ES 5, MG 30, RJ 12, SP 7, DF 4, GO 9, MS 5, MT 1); 72 são usadas, sem o MT. A lista ainda será recalculada com 2021 a 2025 e só pode encolher. Pendente: fonte, ano e valores dos pesos por estado (vão para `docs/premissas.md`).

## Alvo da previsão: carga mensal do SE/CO, 12 meses à frente
Contexto: o contrato é decidido uma vez por ano, antes do início do ano. O planejamento original previa um LightGBM horário com temperatura e defasagens. Nesse horizonte, a temperatura do ano seguinte não existe e as defasagens de curto prazo também não. Um modelo horário alimentado com a temperatura real do próprio ano daria um erro irrealmente baixo, e o erro horário (que se cancela na média de 8.760 horas) subestimaria a incerteza do consumo anual, deixando o otimizador confiante demais.
Opções: (A) previsão horária ou diária com LightGBM; (B) previsão mensal 12 meses à frente, com tendência, calendário e defasagens de pelo menos 12 meses; (C) previsão anual direta.
Escolha: B, sobre a carga mensal do SE/CO com histórico do ONS desde 2000. Como o consumo do consumidor é proporcional à carga real do SE/CO (ver "perfil sintético"), prever essa carga é prever o consumo mensal. Baseline: mesmo mês do ano anterior. Modelo: regressão linear regularizada primeiro (a solução simples, que gera o "antes"); LightGBM entra como desafiante, porque com ~300 pontos mensais não é certo que ele ganhe. Validação em rolling origin mensal, sempre com informação anterior ao início de cada ano; o erro desse backtest gera os cenários de consumo. A previsão horária D+1 com LightGBM vira extra opcional. Os períodos 2001–2002 (racionamento) e 2020 (pandemia) são outliers a tratar na Sprint 5.
Resultado: a previsão passa a ter a mesma escala e o mesmo horizonte da decisão que ela informa. Ponto de atenção: como o consumo é suave e proporcional à carga real, o erro anual da previsão tende a ser pequeno, então o ganho do backtest virá mais da escolha de `V` frente ao PLD do que da previsão em si.

## Preço do contrato: PLD médio do ano anterior mais spread
Contexto: não existe série pública confiável de preços de contratos para 2021–2025. Um preço fixo de R$ 200/MWh em todos os anos faria o backtest medir o regime de preço e não a decisão: em 2022 o PLD do SUDESTE ficou abaixo de R$ 200 em 100% das horas (média de R$ 59,0), em 2021 a média foi R$ 280,5 e em 2025, R$ 224,3.
Opções: (A) preço fixo; (B) preço fixo com sensibilidade em faixa; (C) preço atrelado ao PLD do ano anterior mais um spread.
Escolha: C. `P_t` = PLD médio do ano `t−1` (média simples das horas do SUDESTE; para 2020, o arquivo semanal 2001–2020 ponderado pelas horas de cada semana, com a média simples dos 3 patamares de carga, que o arquivo não identifica: R$ 178,03/MWh, erro máximo de R$ 4,84 pelos extremos piso/teto, dentro do limite aceito de R$ 20) + spread de R$ 20/MWh no caso base (sensibilidade R$ 0, 20 e 40). O mesmo `P_t` vale para as três estratégias. Isso imita um preço de mercado que acompanha o spot do ano anterior sem pretender ser uma série real. O resto do contrato (banda de ±10%, modulado pela carga, diferenças ao PLD ponderado pelo consumo, `V` da estratégia otimizada limitado a `[1/(1+f), 120%]` do consumo previsto, CVaR95 com λ = 0,5) está em `docs/premissas.md`.
Resultado: o preço deixa de depender de uma escolha arbitrária de nível, mas a economia do backtest pode sair pequena ou negativa em anos de mudança brusca de regime (por exemplo 2022, com `P_t` ≈ R$ 300 e PLD ≈ R$ 59); isso será reportado ano a ano.

## Limite inferior de V pela regra de lastro
Contexto: o desenho inicial limitava `V` da estratégia otimizada a 80–120% do consumo previsto. Na pesquisa, o Decreto 5.163/2004 (art. 2º, III) mostrou que o consumidor do mercado livre deve garantir 100% da carga com contratos registrados na CCEE, com aferição mensal e penalidade (art. 3º); a página de penalidades da CCEE indica penalidade por insuficiência de lastro com base em histórico de 12 meses e VR de R$ 290,12 em 2026. Com `V` a 80% e banda de +10%, a cobertura máxima seria de 88% do consumo, e o VR fica bem acima do PLD médio de 2022–2024 (R$ 59 a R$ 128), então o modelo premiaria contratar menos do que o consumo, algo que o mercado penaliza.
Opções: (a) elevar o limite inferior para o menor volume que ainda cobre o consumo médio usando toda a banda, `1/(1+f)`; (b) manter 80% e modelar a penalidade no custo.
Escolha: (a). Limite inferior de `V` = `consumo previsto / (1 + f)` (≈ 95% com f = 5%, ≈ 91% com f = 10%, ≈ 87% com f = 15%) e limite superior de 120%. É a opção simples (sem depender de uma fórmula que ainda não foi confirmada em fonte oficial) e evita o resultado enganoso. Modelar a penalidade fica como extra (lista "Extras" do planejamento), dependente de confirmar a fórmula, a tolerância e o VR de 2021–2025 no Caderno de Regras nº 13 da CCEE.
Resultado: o backtest não depende de uma penalidade não modelada para as estratégias com contratação sistematicamente baixa. Risco residual: se o consumo real superar a previsão além da banda, a cobertura média cairia abaixo de 100% e o modelo não captura a penalidade; o relatório do backtest conta esses anos.
