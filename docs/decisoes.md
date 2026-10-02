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
