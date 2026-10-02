# Diário

Três linhas por sprint (ou por bloco de tarefas): o que entreguei, o que aprendi, o que travou.

## Sprint 1, tarefas 1.1 a 1.4 (02/10/2026)

- **Entreguei:** estrutura de pastas da seção 9, ambiente Python com uv (3.12), `pyproject.toml`,
  ruff e pytest funcionando, LICENSE MIT, GCP configurado (orçamento, cota, bucket, datasets) e a
  exploração das quatro fontes: `docs/fontes.md`, `scripts/explorar_fontes.py` e
  `scripts/inmet_cmp.py`, mais 6 decisões novas em `docs/decisoes.md`.
- **Aprendi:** os dados abertos têm armadilhas que só aparecem olhando o dado, não a
  documentação: o layout do PLD da CCEE muda entre 2024 e 2025 (aspas, quebra de linha, zeros à
  esquerda), em 2022–2024 a maior parte das horas do PLD ficou no piso (até 98,3% em 2023), o
  consumo por ramo da CCEE é mensal e não horário, e a completude das estações do INMET varia
  de 0% a 100% de nulos e muda de um ano para o outro. Também aprendi a decidir fuso horário
  (UTC no staging, com `America/Sao_Paulo`) e a medir antes de concluir (por exemplo, escolher
  estações por completude e não por cidade).
- **Travou:** o portal da CCEE bloqueia downloads e a API por script (403), e a conexão ao INMET
  caiu no teste; baixei esses arquivos à mão e deixei a automação para a 1.7 e a 1.8, sem
  tentar burlar o bloqueio. Ficaram pendentes: fuso do ONS (dicionário de dados), piso e
  teto do PLD por ano (ANEEL), unidade do consumo por ramo e os pesos por estado da
  temperatura.
