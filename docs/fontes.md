# Fontes de dados

Resultado da exploração da tarefa 1.4 (amostras em `data/amostras/`, ignorada pelo git;
perfil reproduzível com `uv run python scripts/explorar_fontes.py`).
Data da exploração: 02/10/2026 (tarefa 1.10 incluída: histórico do ONS 2000–2025 e PLD
2001–2020; `uv run python scripts/explorar_fontes.py pld-historico` e `ons-historico`).
Pendências estão marcadas com **[pendente]**.

## Resumo

| Fonte | Granularidade | Período | Fuso | Atualização | Tamanho | Formato |
|---|---|---|---|---|---|---|
| ONS, curva de carga | Horária, por subsistema | 2000–2026 (ingestão desde 2000) | Horário oficial local (com horário de verão até 2018) | 2x ao dia, com revisões | ~1,5 MB/ano | CSV, Parquet, XLSX |
| CCEE, PLD horário | Horária, por submercado | 2021–2026 (+ arquivo 2001–2020) | Brasília | Mensal (publicação diária) | ~1 MB/ano | CSV |
| CCEE, consumo por ramo | Mensal, por ramo | abr/2024 em diante | n/a | Mensal | ~15 KB/ano | CSV |
| INMET, estações automáticas | Horária, por estação | 2000–2026 (usado: 2021+) | UTC | Anual (2026 parcial) | ~80–100 MB/ano (ZIP) | ZIP de CSVs |

Duas fontes em horário local (ONS, PLD) e uma em UTC (INMET): ver `decisoes.md` ("Fuso horário em séries horárias").

---

## ONS: Curva de Carga Horária

- **Portal:** https://dados.ons.org.br/dataset/curva-carga
- **Acesso:** download direto por ano, sem API nem autenticação:
  `https://ons-aws-prod-opendata.s3.amazonaws.com/dataset/curva-carga-ho/CURVA_CARGA_{ANO}.csv`
  (também `.parquet` e `.xlsx`). Testado em 2021 e 2025.
- **Granularidade:** horária, por subsistema (N, NE, S, SE).
- **Período:** 2000–2026. A ingestão é **desde 2000**: a previsão mensal da carga do SE/CO (12
  meses à frente) precisa do histórico longo, e a curva do consumidor usa a carga real de
  2020 em diante (ver `premissas.md`). Os 26 arquivos de 2000 a 2025 foram perfilados
  (tarefa 1.10); 1999 não existe (404).
- **Atualização:** 2x ao dia (12:00 e 19:00 UTC). O portal avisa que os dados passam por
  "processo de consistência recorrente", ou seja, **valores já publicados podem ser revisados**.
- **Tamanho:** ~1,5 MB por ano (35.040 linhas); 38 MB para os 26 anos.
- **Fuso:** o dado não declara, mas o teste de horário de verão (abaixo) mostra que a série
  está no **horário oficial local, acompanhando o relógio, com horário de verão até 2018**.
  A confirmação documental no dicionário de dados do ONS não foi feita.

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
- Veja abaixo o histórico 2000–2025 (layout, nulos, horário de verão e degraus de nível).
- Fora do escopo da Sprint 1: "Balanço de Energia nos Subsistemas" (inclui geração por fonte),
  item de corte da lista "Se atrasar".

### ONS, histórico 2000–2025 (tarefa 1.10)

**Layout: idêntico nos 26 anos.** Mesmo cabeçalho de 4 colunas, UTF-8 sem BOM, LF, `;`,
`din_instante` no formato `AAAA-MM-DD HH:MM:SS`, sempre os 4 subsistemas (N, NE, S, SE) e
minuto sempre 0. Sem duplicatas em nenhum ano. Não há mudança de layout para tratar.

**Completude.** O problema não é o layout, é o que acontece em algumas datas:

| Anos | O que falta ou vem nulo |
|---|---|
| 2000–2012 | 1 linha **ausente** por subsistema por ano: 00:00 do dia de início do horário de verão |
| 2013 | idem (2013-10-20 00:00) + **2013-12-01 inteiro com valor nulo** nos 4 subsistemas (96 nulos) |
| 2014 | 2014-02-01 inteiro sem dado (nulo em NE, S e SE; linhas ausentes no N) + 00:00 de 2014-10-19 **nulo** |
| 2015 | 2015-04-09 inteiro sem dado (mesmo padrão) + 00:00 de 2015-10-18 nulo |
| 2016–2017 | só o 00:00 do início do horário de verão, **nulo** nos 4 subsistemas |
| 2018 | 00:00 de 2018-11-04 nulo em N, NE e SE e **valor 0,0 no S** (único valor <= 0 de toda a série) |
| 2019–2025 | completos: sem nulos, sem linhas ausentes |

Nulos e dias sem dado precisam de tratamento no staging (média mensal ignora nulos; testes de
`not_null` e de carga positiva vão capturar esses casos).

**Teste de horário de verão (confirma a inferência do fuso).** Para cada ano, o perfil diário
médio do SE (dias úteis) nas 3 semanas antes e nas 3 semanas depois do início do horário de
verão foi comparado, procurando o deslocamento em horas que melhor os alinha:
- **Deslocamento 0 em todos os 25 anos testados (2001–2025).** Se a série estivesse em horário
  fixo (UTC−3 sem horário de verão), o perfil depois do início andaria ~1 hora; se estivesse em
  UTC, o mínimo da carga às 03h seria meia-noite local, o que não faz sentido. A série
  acompanha o relógio oficial.
- **A lacuna de 00:00 coincide com o início do horário de verão.** Em 2000–2013 a linha de
  00:00 do dia de início (domingo de outubro ou novembro, ex.: 2002-11-03, 2006-11-05,
  2012-10-21) simplesmente não existe, porque esse horário não existe no relógio local (o
  relógio salta de 00:00 para 01:00). Em 2014–2018 a linha existe, com valor nulo. As datas de
  2014–2018 que usei de memória (2014-10-19, 2015-10-18, 2016-10-16, 2017-10-15, 2018-11-04)
  foram confirmadas pelos nulos nessas mesmas datas.
- **Fim do horário de verão:** a hora repetida (23:00 que ocorre duas vezes) aparece **uma
  vez só** (zero duplicatas). Um dos dois instantes UTC fica sem dado.
- **O mínimo da carga do SE é às 03h** antes e depois (o 04h de 2016 e 2020 é ruído).
- **A inferência de "horário de Brasília" está confirmada, com uma precisão:** é o horário
  oficial local, que no Sudeste e no Centro-Oeste teve horário de verão (UTC−2) até 2018. O
  `America/Sao_Paulo` do tzdata tem esse histórico, então a decisão de converter com o fuso
  nomeado (e não com offset fixo) está certa.
- **Consequências para a conversão a UTC no staging (Sprint 2):** (1) as linhas de 00:00 nulas
  de 2014–2018 caem num horário local que **não existe**; precisam ser descartadas ou tratadas
  antes da conversão; (2) para cada ano com horário de verão há uma hora UTC sem dado (a
  repetida), então a série em UTC terá 1 buraco por ano até 2018.

**Carga média anual do SE (MWmed), variação anual e participação do SE no total dos 4
subsistemas:**

| Ano | MWmed | Var. | SE/total | Ano | MWmed | Var. | SE/total |
|---|---|---|---|---|---|---|---|
| 2000 | 25.727 | n/d | 63,0% | 2013 | 34.625 | −2,1% | 58,9% |
| 2001 | 23.292 | −9,5% | 61,7% | 2014 | 36.277 | +4,8% | 58,9% |
| 2002 | 25.002 | +7,3% | 63,1% | 2015 | 35.936 | −0,9% | 58,6% |
| 2003 | 26.155 | +4,6% | 62,6% | 2016 | 35.617 | −0,9% | 57,8% |
| 2004 | 27.253 | +4,2% | 62,3% | 2017 | 36.130 | +1,4% | 57,6% |
| 2005 | 28.361 | +4,1% | 62,0% | 2018 | 36.494 | +1,0% | 57,7% |
| 2006 | 29.359 | +3,5% | 61,8% | 2019 | 37.162 | +1,8% | 57,5% |
| 2007 | 30.846 | +5,1% | 62,0% | 2020 | 36.311 | −2,3% | 57,3% |
| 2008 | 31.478 | +2,0% | 61,7% | 2021 | 39.188 | +7,9% | 57,2% |
| 2009 | 31.089 | −1,2% | 61,4% | 2022 | 39.688 | +1,3% | 57,7% |
| 2010 | 33.278 | +7,0% | 61,5% | 2023 | 41.886 | +5,5% | 56,8% |
| 2011 | 34.525 | +3,7% | 61,6% | 2024 | 44.465 | +6,2% | 56,3% |
| 2012 | 35.379 | +2,5% | 60,9% | 2025 | 44.268 | −0,4% | 55,5% |

A tabela mensal (26 anos × 12 meses) sai do script e fica em
`data/amostras/ons/carga_mensal_se.csv` (ignorado pelo git).

**Quebras de nível (degraus).** Critério: mês com variação superior a ±5% contra o mesmo mês
do ano anterior, lendo os blocos de meses seguidos. Muitos meses passam do limite; os blocos
longos são:
- **Eventos conhecidos, não mudança de definição:** jun/2001 a abr/2002 (de −22,5% a −5,3%,
  seguido de +13% a +29% em jun/2002–fev/2003, coincidindo com o racionamento e a
  recuperação); abr–mai/2020 (−14,5% a −12,6%, pandemia) e o rebote de mar–set/2021 (+5,4% a
  +22,0%); dez/2008–jan/2009 (−7,6% a −5,2%); nov/2009–set/2010 (+5,9% a +13,1%).
- **Degrau no N em jul–ago/2013:** a carga média do N passa de ~3.900–4.100 MWmed (2012 e
  1º semestre de 2013) para ~5.100 em ago/2013 (+25%) e fica nesse nível (2013: +13,2% no
  ano; 2014: +11,9%). O SE não tem degrau (−2,1% em 2013). A participação do SE no total
  cai de 60,9% (2012) para 58,9% (2013) em grande parte por isso. A causa não pode ser
  determinada pelos dados (**hipótese não verificada:** entrada de uma nova região no
  sistema). Afeta só a série do N e as participações, não a carga do SE.
- **Degrau em 2023, nos 4 subsistemas: confirmado como mudança de definição (ver abaixo),
  misturada com crescimento real.** A variação anual, que no SE, NE e S estava em torno de 0%
  (ou negativa) no início de 2023, sobe para +7% a +19% entre mai/2023 e abr/2024 (SIN, soma
  dos 4: +12,7% a +18,1% de set/2023 a mar/2024). No SE a carga sobe +6,2% em ago/2023 e +6,5%
  em set/2023 (mês contra mês) e o nível se mantém: média anual de 39.688 (2022) para 41.886
  (2023) e 44.465 (2024); 2025 fica em 44.268. Entre abr e mai/2023 a variação anual salta
  +7,5 p.p. no SE (−3,5% para +4,0%), +8,0 no NE, +5,5 no S e +2,9 no N, a época em que a
  documentação diz que a MMGD estimada entrou na carga. O que vem depois (set–dez/2023) soma
  esse degrau com crescimento real (calor e economia), que os dados não permitem separar.
  **Impacto:** a curva do consumidor é proporcional à carga do SE (`premissas.md`), então
  herda o degrau em 2023–2025, e a estratégia ingênua e a previsão mensal são afetadas nesses
  anos. **[pendente]** decidir o tratamento (ver `premissas.md`, pendência 6).

**O que a documentação do ONS diz sobre mudanças de definição da carga** (pesquisa da
tarefa 1.10):
- **A página do dataset da curva horária não documenta nada.** Em
  https://dados.ons.org.br/dataset/curva-carga há só a descrição ("perfil de consumo de energia
  elétrica com discretização horária") e o aviso de que os dados passam por "processo de
  consistência recorrente". Não há definição de "carga", menção a MMGD, histórico de mudanças
  ou fuso. O dicionário de dados em JSON
  (https://ons-aws-prod-opendata.s3.amazonaws.com/dataset/curva-carga-ho/DicionarioDados_CurvaCarga.json)
  só traz os 4 campos (`din_instante` como "Data de referência", `val_cargaenergiahomwmed`
  como "Valor da Carga de Energia, em MWmed"), sem tipos, fuso ou histórico.
- **A página do dataset "Carga de Energia Diária" documenta as mudanças** (resumo da página,
  https://dados.ons.org.br/dataset/carga-energia): até fev/2021 a carga cobre as usinas
  despachadas ou programadas pelo ONS, medidas pelo sistema de supervisão; de mar/2021 a
  abr/2023 passam a entrar também as usinas não despachadas (por geração prevista); e **a
  partir de 29/04/2023 "passou a ser incorporado o valor estimado da micro e minigeração
  distribuída (MMGD), com base em dados meteorológicos previstos"**.
- **A página do dataset "Carga de Energia Mensal" diz o mesmo para a MMGD** (com base em
  "dados meteorológicos verificados", https://dados.ons.org.br/dataset/carga-mensal) e acrescenta
  que, nesse dataset, até dez/2014 os números vêm do sistema de supervisão, que a partir de
  jan/2015 as usinas não despachadas foram incluídas e que desde mar/2021 vêm do sistema de
  medição para faturamento da CCEE.
- **A curva horária tem a mesma definição da carga diária.** Comparei a média diária da curva
  horária com a "Carga de Energia Diária" nos 26 anos (`scripts/explorar_fontes.py
  ons-historico`): as diferenças são da ordem de 1e-12, exceto nos dias de transição de
  horário de verão (4 a 9 subsistema-dias por ano em 2001–2012 e 2017–2018, até 4,4% por causa
  do dia de 23 horas). Portanto as mudanças documentadas na carga diária valem para a curva
  horária, **embora a página dela não as cite**.
- **Mudanças documentadas na série (datas aproximadas):** mar/2021 (inclusão de usinas não
  despachadas) e 29/04/2023 (MMGD estimada). A de mar/2021 coincide com o rebote da pandemia
  (variação anual de +10,6% no SE em mar/2021, com base baixa em mar/2020), então o degrau de
  definição dessa data não é isolável. A de jan/2015 é citada só na página do dataset mensal;
  para a curva horária não há evidência.
- **Não confirmado (aparece só em resultados de busca, sem fonte oficial lida):** uma segunda
  fase da MMGD na carga, com a expansão projetada, depois de mai/2023. **[pendente]** verificar,
  porque alteraria a definição de novo.
- **Magnitude:** a documentação diz o que mudou, não quanto. O tamanho do degrau (cerca de
  +3 a +8 p.p. de variação anual entre abr e mai/2023, com ruído de feriados) é só uma
  estimativa dos dados, não do ONS.

### Testes de qualidade previstos para a Sprint 3 (ONS, curva de carga)

Cada item é um caso real encontrado na exploração. Os testes devem sinalizá-lo e, onde o caso é
conhecido e permanente, ter uma lista de exceções esperadas para não parar o pipeline por algo
que já foi investigado.

| # | Caso encontrado | Onde acontece | Teste previsto |
|---|---|---|---|
| 1 | **Linhas de 00:00 nulas no início do horário de verão** | 2014-10-19, 2015-10-18, 2016-10-16, 2017-10-15 (nulo nos 4 subsistemas) e 2018-11-04 (nulo em N, NE e SE). Esse horário não existe no relógio local. Em 2000–2013 a mesma linha **não existe** (ausente) | `not_null` em `val_cargaenergiahomwmed` com exceção para essas datas às 00:00, ou descartar essas linhas no staging antes da conversão para UTC. Completude horária: as linhas ausentes de 2000–2013 são conhecidas |
| 2 | **Valor 0,0 no S em 2018-11-04 00:00** | único valor <= 0 de toda a série 2000–2025 (os outros subsistemas têm nulo nessa hora) | teste de faixa (carga > 0) deve capturar; tratar como o caso 1 (hora inexistente) |
| 3 | **Dias inteiros sem valor** | 2013-12-01 (nulo nos 4 subsistemas, 96 nulos), 2014-02-01 e 2015-04-09 (nulo em NE, S e SE; linhas ausentes no N) | `not_null` e completude por dia; exceções conhecidas; decidir se esses dias são imputados ou ficam ausentes (afetam a média mensal do SE) |
| 4 | **Hora repetida do fim do horário de verão ausente** | uma hora UTC sem dado por ano com horário de verão, no fim (fev/2001 a fev/2019); a série traz o 23:00 repetido uma vez só | completude em UTC no staging: espera-se **uma** hora faltante por ano até 2018; o teste não pode exigir 8.760 horas UTC contínuas nesses anos. A partir de 2019 a série deve estar completa |

Outros testes a prever com base no mesmo perfil: subsistemas fixos (N, NE, S, SE), minuto sempre
0, sem duplicatas em (`id_subsistema`, `din_instante`), e um alerta de degrau (variação anual
do SE acima de ±5% por vários meses) que ajude a perceber futuras mudanças de definição como a
de 2023.

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
  PLD é divulgado no dia anterior). O arquivo 2001–2020 é **semanal por patamar de carga**,
  não horário: ver a subseção "PLD histórico" abaixo. Dele vem o PLD de 2020, que define o
  preço de contrato de 2021 (`premissas.md`).
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

### PLD histórico semanal 2001–2020 (tarefa 1.10)

- **Arquivo:** `pld_historico_semanal_2001_2020.csv` (baixado manualmente do mesmo dataset,
  452 KB, 12.312 linhas). Não é horário: **a ingestão deve tratá-lo como tabela à parte**
  (`pld_semanal`), sem misturar com o `pld_horario`.
- **Layout:** mesmas 6 colunas e mesma formatação dos arquivos 2021–2024 (aspas, CRLF, `DIA`
  e `HORA` com zero à esquerda), **mas a semântica é outra**:
  - cada linha é o preço de **um patamar de carga de uma semana operativa**;
  - **3 linhas por (mês de referência, submercado, início da semana)**: 4.104 chaves × 3;
  - `HORA` é sempre `00`; `DIA` é o dia em que a semana **começa**; `PERIODO_COMERCIALIZACAO`
    é a hora do mês em que a semana começa (igual a `(DIA − 1) × 24 + 1` em 100% das linhas);
  - a semana pertence ao mês em que começa (a semana de 28/12/2019 está em `201912`).
- **Período:** jun/2001 a dez/2020 (235 meses; não começa em jan/2001). 4 submercados,
  3.078 linhas cada. Sem nulos.
- **O patamar não é identificável.** Não há coluna de patamar (leve, média, pesada), as horas de
  cada patamar não estão no arquivo, e a ordem das 3 linhas não os identifica (só 51,3% das
  semanas têm linha 1 <= linha 2 <= linha 3).
- **4.118 linhas são duplicatas exatas**, mas não são erro: são patamares com o mesmo preço
  (por exemplo, 3 linhas iguais de R$ 684 em jun/2001). **Não deduplicar** e não usar
  `unique` do dbt sobre as 6 colunas; uma chave única precisaria de uma coluna sintética de
  ordem dentro da semana.
- **Semanas:** começam em sábado (12.216 linhas) e duram 7 dias, exceto 8 semanas curtas que
  começam no dia 1 do mês fora de sábado: 2001-08-24, 2002-01-01, 2002-03-01, 2003-04-01,
  2003-12-01, 2015-06-01, 2016-09-01 e 2016-11-01. A duração de uma semana deve ser o
  intervalo até o início da seguinte, e não 7 dias fixos. As 53 semanas que tocam 2020 são
  todas de sábado a sexta.
- **PLD médio de 2020, ponderado pelas horas de cada semana** (a semana de 28/12/2019
  contribui com 72 h de 2020 e a de 26/12/2020, com 144 h; as 53 semanas cobrem exatamente as
  8.784 h do ano). Como o patamar não é identificável, usa-se a **média simples dos 3
  patamares** de cada semana, com o erro máximo medido pelos extremos (só o menor ou só o
  maior patamar de cada semana):

| Submercado | Média ponderada (R$/MWh) | Piso | Teto | Erro máximo |
|---|---|---|---|---|
| **SUDESTE** | **178,03** | 173,19 | 181,12 | **4,84** |
| NORDESTE | 135,27 | 132,50 | 138,66 | 3,39 |
| NORTE | 165,55 | 163,09 | 167,25 | 2,46 |
| SUL | 187,87 | 173,19 | 196,04 | 14,68 |

  O erro máximo do SUDESTE (R$ 4,84) é menor que o limite aceito de R$ 20: **aproximação
  aceita**. Sem ponderar pelas horas (média simples das semanas) o SUDESTE daria R$ 179,38.
- **Consequência para o preço de contrato:** `P_2021` = 178,03 + spread de R$ 20 =
  **R$ 198,03/MWh** (caso base; R$ 178,03 e R$ 218,03 na sensibilidade 0 e 40).

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
  2021 e 1 só em 2024; 145 do Sudeste estão nos dois anos, e 240 se somado o Centro-Oeste). Sem códigos repetidos dentro do
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
arquivo conta como inválida. Escopo: estados do submercado SE/CO que o projeto cobre:
Sudeste (ES, MG, RJ, SP) e Centro-Oeste (DF, GO, MS, MT). Análise reproduzível com
`uv run python scripts/inmet_cmp.py` (gera `data/amostras/inmet/completude_estacoes.csv`).

**Resultado:** das 240 estações do SE/CO presentes nos dois anos, **73 passam**; **72 são
usadas**, porque o MT foi excluído (abaixo).

| Região | UF | Presentes nos 2 anos | Passam |
|---|---|---|---|
| SE | ES | 12 | 5 |
| SE | MG | 68 | 30 |
| SE | RJ | 25 | 12 |
| SE | SP | 40 | 7 |
| CO | DF | 5 | 4 |
| CO | GO | 26 | 9 |
| CO | MS | 27 | 5 |
| CO | MT | 37 | **1** (excluído) |

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
- **DF:** A001 Brasília (100,0/99,7); A042 Brazlândia (97,9/97,3); A046 Gama Ponte Alta
  (100,0/99,2); A047 Paranoá Coopa-DF (97,7/95,3).
- **GO:** A034 Catalão (100,0/100,0); A036 Cristalina (100,0/100,0); A002 Goiânia
  (98,5/99,3); A015 Itapaci (100,0/95,8); A016 Jataí (99,9/99,9); A012 Luziânia
  (100,0/100,0); A027 Paraúna (100,0/100,0); A033 Pires do Rio (100,0/99,9); A037 Silvânia
  (100,0/97,9).
- **MS:** A756 Água Clara (100,0/99,8); A702 Campo Grande (99,2/100,0); A703 Ponta Porã
  (98,2/100,0); A743 Rio Brilhante (97,5/100,0); A704 Três Lagoas (100,0/100,0).
- **MT (excluído):** A934 Alto Taquari (97,5/95,6).

**Observações sobre o resultado**
- A lista só pode **encolher** quando 2022, 2023 e 2025 entrarem (o critério vale em cada
  ano). Ela precisa ser recalculada com os anos 2021 a 2025 antes de ser usada nos
  extratores. O INMET é usado de 2021 em diante, então o ano 2020 não entra no critério.
- Muitas estações ficam de fora por completude baixa em 2021 (mediana de 92,6% no
  Sudeste, contra 98,1% em 2024). Perto do limite há estações como Casa Branca, Itapira
  ou Cachoeira Paulista (0% em 2021, entre 91% e 96% em 2024).
- **Distribuição geográfica desigual:** 30 das 73 estações são de MG e só 7 de SP, quase
  todas no interior (a capital só tem a A701 Mirante). Uma média simples entre todas as
  estações ficaria dominada por MG, embora SP seja o maior centro de carga do submercado.
  Por isso a agregação é em dois passos, com peso por estado (abaixo).
- **MT está excluído:** só 1 estação passa (Alto Taquari, com 95,6% em 2024, perto do
  limite), de 37 presentes nos dois anos. A média do estado dependeria de uma única estação.
  O peso do MT é redistribuído proporcionalmente entre os outros 7 estados (ES, MG, RJ, SP,
  DF, GO, MS).

**Papel da temperatura:** o INMET é usado de 2021 em diante como **variável de análise de
erro** (onde a previsão erra mais, como em ondas de calor). Ela não entra na curva do
consumidor nem na previsão central de 12 meses (ver `premissas.md`, seção 3).

**Temperatura do submercado (agregação em dois passos, a implementar na Sprint 2):**
1. **Média das estações dentro de cada estado**, hora a hora, **tolerante a falhas**: numa
   hora, a média usa só as estações com dado, e uma falha numa estação não anula as demais.
   Se um estado ficar sem nenhuma estação com dado numa hora, a temperatura do estado é
   **imputada dentro do próprio estado** (hora anterior ou perfil típico do dia).
2. **Média entre estados (ES, MG, RJ, SP, DF, GO, MS), ponderada pelo peso de cada estado no
   consumo de energia do submercado SE/CO.** Pesos de fonte oficial (ex.: Anuário Estatístico
   de Energia Elétrica da EPE), a definir em `docs/premissas.md`. **[pendente]** definir
   fonte, ano de referência e valores dos pesos. Se faltar dado em todos os estados numa
   hora, a hora fica ausente.

Ver `decisoes.md` ("Estações do INMET e temperatura do submercado").

---

## Mapa dos fusos horários

| Fonte | Fuso original | Tratamento |
|---|---|---|
| ONS | Horário oficial local (confirmado pelo teste de horário de verão), com horário de verão até 2018 | Bronze e raw sem alteração; staging converte para UTC com `America/Sao_Paulo` (tratar linhas nulas de 00:00 em dias de início de horário de verão, 2014–2018) |
| CCEE PLD | Brasília | idem |
| INMET | UTC | Já em UTC; apenas montar o timestamp |
| CCEE consumo | n/a (mensal) | n/a |
