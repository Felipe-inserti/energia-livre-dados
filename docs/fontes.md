# Fontes de dados

Resultado da exploração da tarefa 1.4 (amostras em `data/amostras/`, ignorada pelo git;
perfil reproduzível com `uv run python scripts/explorar_fontes.py`).
Data da exploração: 02/10/2026. Pendências estão marcadas com **[pendente]**.

## Resumo

| Fonte | Granularidade | Período | Fuso | Atualização | Tamanho | Formato |
|---|---|---|---|---|---|---|
| ONS, curva de carga | Horária, por subsistema | 2000–2026 | Brasília (a confirmar) | 2x ao dia, com revisões | ~1,5 MB/ano | CSV, Parquet, XLSX |
| CCEE, PLD horário | Horária, por submercado | 2021–2026 | Brasília | Mensal (publicação diária) | ~1 MB/ano | CSV |
| CCEE, consumo por ramo | Mensal, por ramo | abr/2024 em diante | n/a | Mensal | ~15 KB/ano | CSV |
| INMET, estações automáticas | Horária, por estação | 2000–2026 | UTC | Anual (2026 parcial) | ~80–100 MB/ano (ZIP) | ZIP de CSVs |

Duas fontes em horário de Brasília e uma em UTC: ver `decisoes.md` ("Fuso horário em séries horárias").

---

## ONS: Curva de Carga Horária

- **Portal:** https://dados.ons.org.br/dataset/curva-carga
- **Acesso:** download direto por ano, sem API nem autenticação:
  `https://ons-aws-prod-opendata.s3.amazonaws.com/dataset/curva-carga-ho/CURVA_CARGA_{ANO}.csv`
  (também `.parquet` e `.xlsx`). Testado em 2021 e 2025.
- **Granularidade:** horária, por subsistema (N, NE, S, SE).
- **Período:** 2000–2026. A Sprint 1 usa 2021 em diante.
- **Atualização:** 2x ao dia (12:00 e 19:00 UTC). O portal avisa que os dados passam por
  "processo de consistência recorrente", ou seja, **valores já publicados podem ser revisados**.
- **Tamanho:** ~1,5 MB por ano (35.040 linhas).
- **Fuso:** o dado não declara. A curva média do SE tem mínimo às 03–04h e pico às 18–19h,
  compatível com horário de Brasília. **[pendente]** confirmar no dicionário de dados do ONS.

| Coluna | Tipo | Descrição |
|---|---|---|
| `id_subsistema` | texto | N, NE, S, SE |
| `nom_subsistema` | texto | NORTE, NORDESTE, SUL, SUDESTE |
| `din_instante` | texto `YYYY-MM-DD HH:MM:SS` | início da hora |
| `val_cargaenergiahomwmed` | decimal | carga média da hora em MWmed |

Formato do arquivo: CSV UTF-8, separador `;`, ponto decimal.

**Problemas e observações**
- Nenhum nulo, duplicata, buraco ou minuto diferente de zero em 2021 e 2025
  (4 subsistemas × 8.760 h por ano). Layout idêntico nos dois anos.
- Sem negativos nem zeros. Faixa em 2025, por subsistema e hora (os 4 juntos): 6.016 a
  62.150 MWmed.
- Revisões retroativas: não medidas, a amostra é um retrato único. Serão investigadas na
  tarefa 3.4.
- Fora do escopo da Sprint 1: "Balanço de Energia nos Subsistemas" (inclui geração por fonte),
  item de corte da lista "Se atrasar".

---

## CCEE: PLD horário

- **Portal:** https://dadosabertos.ccee.org.br/dataset/pld_horario (CKAN, licença CC-BY-4.0)
- **Acesso:** um CSV por ano (2001–2020 num arquivo só; depois 2021 a 2026). Os links de
  download têm hash opaco (`pda-download.ccee.org.br/<hash>/content`), então a descoberta
  deve ser feita pela API CKAN (`package_show`). **O portal e a API devolvem 403 "Acesso
  bloqueado" para downloads automáticos.** O histórico 2021–2025 foi baixado manualmente;
  a atualização automática é tema da tarefa 1.7 (ver `decisoes.md`).
- **Granularidade:** horária, por submercado (NORDESTE, NORTE, SUDESTE, SUL).
- **Período:** 2021-01-01 até 2026-10-02 (o arquivo de 2026 inclui o dia corrente, porque o
  PLD é divulgado no dia anterior).
- **Atualização:** mensal, com publicação diária por dia de referência.
- **Tamanho:** 0,8 a 1,3 MB por ano.
- **Fuso:** horário de Brasília (portal). Não há horário de verão desde 2019, então 2021+ não
  tem hora faltando nem repetida.

| Coluna | Descrição |
|---|---|
| `MES_REFERENCIA` | `AAAAMM` |
| `SUBMERCADO` | NORDESTE, NORTE, SUDESTE, SUL |
| `PERIODO_COMERCIALIZACAO` | hora sequencial dentro do mês (1 a 744) |
| `DIA` | dia do mês |
| `HORA` | hora do dia (0 a 23) |
| `PLD_HORA` | preço em R$/MWh |

Não há coluna de timestamp. Ele se monta com `MES_REFERENCIA` + `DIA` + `HORA`.

**Problemas e observações**
- **Mudança de layout entre 2024 e 2025** (as colunas são as mesmas):

| | 2021–2024 | 2025–2026 |
|---|---|---|
| Aspas nos campos | sim (`"01"`) | não |
| Fim de linha | CRLF | LF |
| `DIA` e `HORA` | com zero à esquerda (`01`, `00`) | sem zero (`1`, `0`) |

  Em 2025 o `DIA` aparece nos dois formatos (`1` e `01`: 40 valores distintos). Nos primeiros
  4 meses só vi o formato sem zero, então a mistura parece ser entre meses, sem verificação
  completa. **O parse deve converter para inteiro, nunca comparar texto.**
- **Ordem das linhas não é confiável:** o arquivo de 2025 começa em jul–dez e depois traz
  jan–jun. Ordenar por timestamp antes de usar.
- **Séries completas:** todos os anos têm todas as horas dos 4 submercados, sem nulos nem
  duplicatas. 2024 tem 8.784 h (bissexto).
- **PLD no piso em 2022–2024:** o valor mínimo do ano concentra a maior parte das linhas:

| Ano | Mínimo (R$/MWh) | % das linhas no mínimo | Mediana | Máximo |
|---|---|---|---|---|
| 2021 | 49,77 | 6,5% | 194,82 | 1.128,72 |
| 2022 | 55,70 | **81,6%** | 55,70 | 306,64 |
| 2023 | 69,04 | **98,3%** | 69,04 | 620,95 |
| 2024 | 61,07 | **65,0%** | 61,07 | 1.470,57 |
| 2025 | 58,60 | 33,6% | 245,01 | 1.421,87 |
| 2026 (até 02/10) | 57,31 | 24,6% | 186,59 | 1.611,04 |

  Esses mínimos parecem coincidir com o piso regulatório de cada ano, mas isso precisa ser
  confirmado na ANEEL (fonte da seção 4 do planejamento). Consequências: (1) o backtest
  2021–2025 mistura regimes muito diferentes de preço (seca em 2021, piso em 2022–2024,
  preços altos em 2025); (2) os cenários de PLD (tarefa 5.7) não podem assumir distribuição
  estável; (3) o teste de faixa da tarefa 3.2 precisa do piso e do teto por ano. Parece haver
  um teto horário e um teto estrutural, com valores diferentes. **[pendente]** confirmar
  piso e teto por ano na ANEEL.

---

## CCEE: consumo por ramo de atividade

- **Portal:** https://dadosabertos.ccee.org.br/dataset/consumo_ramo_atividade
- **Acesso:** um CSV por ano, mesmo mecanismo e mesmo bloqueio do PLD. Baixado manualmente.
- **Granularidade:** **mensal**, por ramo de atividade (15 ramos). **Não é horária.**
- **Período:** abr/2024 em diante (2024: 9 meses; 2025: 12; 2026: até ago).
- **Atualização:** mensal.
- **Tamanho:** 10 a 16 KB por ano (120 a 180 linhas).
- **Fuso:** não se aplica.

| Coluna | Descrição |
|---|---|
| `MES_REFERENCIA` | `AAAAMM` |
| `RAMO_ATIVIDADE` | ramo (ex.: COMÉRCIO, SERVIÇOS, METALURGIA E PRODUTOS DE METAL) |
| `CONSUMO_CL_ESP_ACL` | consumo de consumidores livres e especiais no ACL |
| `CONSUMO_AUTOP_ACL` | consumo de autoprodutores no ACL |
| `CONSUMO_PONTO_CONEXAO_CL_ESP_ACL` | idem, medido no ponto de conexão |
| `CONSUMO_PONTO_CONEXAO_AUTOP_ACL` | idem, autoprodutores no ponto de conexão |

Unidade: a confirmar no dicionário de dados do portal. **[pendente]**

**Problemas e observações**
- É o total do setor por ramo, sem granularidade de consumidor nem de hora. **Não permite
  construir a curva horária do consumidor-exemplo** (risco previsto na seção 13).
  Uso previsto: calibrar o nível e a sazonalidade mensal do ramo COMÉRCIO/SERVIÇOS, que
  entram no perfil sintético (ver `decisoes.md`).
- Sem nulos nem duplicatas (mês, ramo). Sem mudança de layout entre 2024 e 2026.
- `CONSUMO_AUTOP_ACL` tem muitos zeros (ramos sem autoprodução).

---

## INMET: estações meteorológicas automáticas

- **Portal:** https://portal.inmet.gov.br/dadoshistoricos
- **Acesso:** um ZIP por ano em `https://portal.inmet.gov.br/uploads/dadoshistoricos/{ANO}.zip`,
  com um CSV por estação. Em um teste do ambiente de desenvolvimento a conexão foi derrubada
  (erro 56); os ZIPs de 2021 e 2024 foram baixados manualmente. **[pendente]** verificar se o
  extrator consegue baixar sem bloqueio. Não há API documentada para o histórico.
- **Granularidade:** horária, por estação.
- **Período:** 2000–2026. 2026 vai até 31/08/2026.
- **Atualização:** anual, em lote.
- **Tamanho:** ZIP de 80,6 MB (2021) e 102,8 MB (2024); ~0,8 MB por estação/ano.
- **Estações:** 588 em 2021 e 565 em 2024 (a rede muda: 4 estações do Sudeste só existem em
  2021 e 1 só em 2024; 145 do Sudeste estão nos dois anos). Sem códigos repetidos dentro do
  mesmo ano.
- **Fuso:** UTC (explícito na coluna `Hora UTC`).

**Layout (2021 comparado com 2024): idêntico.** Verificado em todos os arquivos dos dois ZIPs
(588 e 565):

| Item | 2021 | 2024 |
|---|---|---|
| Encoding | latin-1 (não decodifica como UTF-8) | latin-1 |
| Separador / decimal | `;` / vírgula | `;` / vírgula |
| Metadados antes do cabeçalho | 8 linhas, mesmos campos (`REGIAO`, `UF`, `ESTACAO`, `CODIGO (WMO)`, `LATITUDE`, `LONGITUDE`, `ALTITUDE`, `DATA DE FUNDACAO`) | idem |
| Linha de cabeçalho | 1 única variante em todos os arquivos | 1 única variante, **igual à de 2021** (19 colunas) |
| `Data` | `AAAA/MM/DD` em todos | idem |
| `Hora UTC` | `HHMM UTC` (ex.: `0000 UTC`) em todos | idem |
| Sentinela `-9999` na temperatura | nenhuma ocorrência | nenhuma |
| Quebra de linha | LF | LF |

A única diferença observada é a precisão da latitude e longitude nos metadados (6 casas em
2021, 8 em 2024), sem efeito prático. O `;` no fim de cada linha gera uma coluna vazia ao
ler. Escopo: só 2021 e 2024 foram comparados; os anos intermediários e 2026 não foram
verificados. 17 medidas por hora; a usada no projeto é
`TEMPERATURA DO AR - BULBO SECO, HORARIA (°C)`.

**Completude varia muito entre estações.** Nulos na temperatura em 2024 nas estações do
teste inicial:

| Estação | Nulos em 2024 |
|---|---|
| A701 São Paulo Mirante | 0,2% |
| A705 Bauru | 0% |
| A521 BH Pampulha | 0,02% |
| A652 Rio Copacabana | **36,6%** (mar a jul quase todo ausente) |

A A652 tinha 100% em 2021 e 63,4% em 2024: **uma estação boa num ano pode degradar no
seguinte**, por isso o critério vale por ano (abaixo).

### Estações escolhidas para a temperatura

**Critério:** temperatura do ar com pelo menos **95% de horas válidas em cada ano** analisado
(por enquanto 2021 e 2024). Horas válidas = horas distintas com temperatura não nula e
diferente de `-9999`, divididas pelas horas do ano (8.760 ou 8.784). Uma hora que falta no
arquivo conta como inválida. Estações do Sudeste (ES, MG, RJ, SP).

**Resultado:** das 145 estações do Sudeste presentes nos dois anos, **54 passam**.

| UF | Presentes nos 2 anos | Passam |
|---|---|---|
| ES | 12 | 5 |
| MG | 68 | 30 |
| RJ | 25 | 12 |
| SP | 40 | 7 |

Percentual de horas válidas (2021 / 2024):

- **ES:** A617 Alegre (97,2/100,0); A615 Alfredo Chaves (100,0/99,9); A614 Linhares
  (100,0/100,0); A616 São Mateus (100,0/99,7); A633 Venda Nova do Imigrante (98,9/97,8).
- **MG:** A549 Águas Vermelhas (95,1/100,0); A534 Aimorés (100,0/98,9); A508 Almenara
  (99,3/99,5); A505 Araxá (99,5/99,3); A502 Barbacena (99,8/99,8); A521 Belo Horizonte
  Pampulha (100,0/100,0); F501 Belo Horizonte Cercadinho (98,4/100,0); A530 Caldas
  (99,9/99,8); A554 Caratinga (100,0/99,9); A520 Conceição das Alagoas (99,8/97,0);
  A564 Divinópolis (100,0/99,9); A524 Formiga (99,9/100,0); A533 Guanhães (99,2/100,0);
  A555 Ibirité Rola Moça (99,7/99,4); A550 Itaobim (99,5/99,8); A518 Juiz de Fora
  (100,0/99,9); A540 Mantena (100,0/100,0); A531 Maria da Fé (100,0/100,0); A539 Mocambinho
  (100,0/99,8); A509 Monte Verde (99,7/99,9); A506 Montes Claros (100,0/100,0); A570
  Oliveira (100,0/98,2); A571 Paracatu (100,0/99,3); A516 Passos (99,2/99,4); A551 Rio Pardo
  de Minas (99,7/100,0); A514 São João del Rei (100,0/100,0); A547 São Romão (99,7/97,7);
  A507 Uberlândia (98,9/100,0); A515 Varginha (100,0/100,0); A510 Viçosa (100,0/99,9).
- **RJ:** A606 Arraial do Cabo (100,0/97,0); A607 Campos dos Goytacazes (100,0/100,0); A624
  Nova Friburgo Salinas (97,5/100,0); A609 Resende (99,8/99,9); A626 Rio Claro (99,3/96,9);
  A636 Rio de Janeiro Jacarepaguá (98,9/100,0); A621 Rio de Janeiro Vila Militar
  (100,0/99,9); A602 Rio de Janeiro Marambaia (99,7/100,0); A601 Seropédica Ecologia
  Agrícola (100,0/99,9); A659 Silva Jardim (100,0/99,6); A625 Três Rios (95,6/99,9); A611
  Valença (99,5/100,0).
- **SP:** A705 Bauru (98,8/100,0); A763 Marília (100,0/99,6); A747 Pradópolis (100,0/97,8);
  A707 Presidente Prudente (99,6/97,6); A701 São Paulo Mirante (100,0/99,8); A770 São Simão
  (98,6/96,3); A768 Tupã (95,9/95,7).

**Observações sobre o resultado**
- A lista só pode **encolher** quando 2022, 2023 e 2025 entrarem (o critério vale em cada
  ano). Ela precisa ser recalculada com os 5 anos antes de ser usada nos extratores.
- Muitas estações ficam de fora por completude baixa em 2021 (mediana de 92,6% no
  Sudeste, contra 98,1% em 2024). Perto do limite há estações como Casa Branca, Itapira
  ou Cachoeira Paulista (0% em 2021, entre 91% e 96% em 2024).
- **Distribuição geográfica desigual:** 30 das 54 estações são de MG e só 7 de SP, quase
  todas no interior (a capital só tem a A701 Mirante). Uma média simples entre estações
  ficaria dominada por MG, embora SP seja o maior centro de carga do submercado.
  **[pendente]** decidir se a média é simples ou ponderada por estado (por exemplo, pela
  carga).
- O submercado SE/CO inclui estados do Centro-Oeste, que não entram na lista (escopo
  Sudeste). Aceito por simplicidade.

**Temperatura do submercado:** média horária das estações escolhidas, **tolerante a falhas**:
uma hora sem medida numa estação não anula a média das demais (a média usa só as estações
com dado naquela hora). Ver `decisoes.md` ("Estações do INMET e temperatura do submercado").

---

## Mapa dos fusos horários

| Fonte | Fuso original | Tratamento |
|---|---|---|
| ONS | Brasília (a confirmar) | Bronze e raw sem alteração; staging converte para UTC com `America/Sao_Paulo` |
| CCEE PLD | Brasília | idem |
| INMET | UTC | Já em UTC; apenas montar o timestamp |
| CCEE consumo | n/a (mensal) | n/a |
