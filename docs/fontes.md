# Fontes de dados

Resultado da exploração da tarefa 1.4 (amostras em `data/amostras/`, ignorada pelo git;
perfil reproduzível com `uv run python scripts/explorar_fontes.py`).
Data da exploração: 02/10/2026 (tarefa 1.10 incluída: histórico do ONS 2000–2025 e PLD
2001–2020; `uv run python scripts/explorar_fontes.py pld-historico` e `ons-historico`).
Pendências estão marcadas com **[pendente]**.

## Resumo

| Fonte | Granularidade | Período | Fuso | Atualização | Tamanho | Formato |
|---|---|---|---|---|---|---|
| ONS, curva de carga | Horária, por subsistema | 2000–2026 (ingestão desde 2000) | Horário oficial local (com horário de verão até 2018) | 2x ao dia, com ~2 dias de atraso e revisões | ~1,5 MB/ano | CSV, Parquet, XLSX |
| CCEE, PLD horário | Horária, por submercado | 2021–2026 (+ arquivo 2001–2020) | Brasília | Mensal (publicação diária) | ~1 MB/ano | CSV |
| CCEE, consumo por ramo | Mensal, por ramo | abr/2024 em diante | n/a | Mensal | ~15 KB/ano | CSV |
| INMET, estações automáticas | Horária, por estação | 2000–2026 (usado: 2021+) | UTC | Anual (2026 parcial) | ~80–100 MB/ano (ZIP) | ZIP de CSVs |

Duas fontes em horário local (ONS, PLD) e uma em UTC (INMET): ver `decisoes.md` ("Fuso horário em séries horárias").

## Tabelas do raw (Sprint 1)

| Tabela em `raw` | Fonte | Linhas | Origem dos arquivos | Bronze no GCS |
|---|---|---|---|---|
| `ons_curva_carga` | ONS, curva de carga horária, 2000 a 2026 | 938.296 | download automático | `bronze/ons/curva_carga/ano=AAAA/` |
| `ccee_pld_horario` | CCEE, PLD horário, 2021 a 2026 | 201.696 | download manual | `bronze/ccee/pld_horario/ano=AAAA/` |
| `ccee_pld_semanal` | CCEE, PLD semanal por patamar, 2001 a 2020 | 12.312 | download manual | `bronze/ccee/pld_semanal/` |
| `ccee_consumo_ramo_atividade` | CCEE, consumo mensal por ramo, 2024 a 2026 | 435 | download manual | `bronze/ccee/consumo_ramo_atividade/ano=AAAA/` |
| `inmet_estacoes_horario` | INMET, 37 estações do SE/CO, 2021 a 2026 | 1.837.272 | download manual | `bronze/inmet/ano=AAAA/` |
| `feriados` | biblioteca `holidays`, 2000 a 2030 | 285 | gerada em código | n/a |

Todas as colunas das fontes estão como STRING (a tipagem é do dbt), mais `_arquivo_origem` e
`_carregado_em` (exceto `feriados`, só com `_carregado_em`). **Só a `ons_curva_carga` é particionada**
(desde a Sprint 4): por MÊS LOCAL, na coluna de controle `_mes_referencia` (DATE, o 1º dia do mês de
`din_instante`), para a carga incremental substituir só as partições da janela. As outras continuam sem
partição, carregadas inteiras.

---

## ONS: Curva de Carga Horária

- **Portal:** https://dados.ons.org.br/dataset/curva-carga
- **Acesso:** download direto por ano, sem API nem autenticação:
  `https://ons-aws-prod-opendata.s3.amazonaws.com/dataset/curva-carga-ho/CURVA_CARGA_{ANO}.csv`
  (também `.parquet` e `.xlsx`). Testado em 2021 e 2025.
- **Só existe o arquivo do ANO inteiro:** não há arquivo por mês (as URLs `CURVA_CARGA_AAAA-MM.csv` e
  `CURVA_CARGA_AAAAMM.csv` dão 404). O S3 aceita `Range` (HTTP 206), mas o CSV é ordenado por tempo e
  sem índice, e o arquivo do ano corrente tem ~1,2 MB: pegar só a cauda não compensa. O `ETag` do
  objeto é o MD5 do arquivo (upload simples), então um HEAD diz se um ano mudou sem baixá-lo (a
  ingestão confere os 26 anos fechados assim; `decisoes.md`, "HEAD/ETag dos anos fechados").
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
| `nom_subsistema` | texto | NORTE, NORDESTE, SUL e SUDESTE; **o `SE` passa a `SUDESTE/CENTRO-OESTE` a partir de 01/01/2026** (o arquivo de 2026 usa o nome novo; o `id_subsistema` não muda) |
| `din_instante` | texto `YYYY-MM-DD HH:MM:SS` | início da hora |
| `val_cargaenergiahomwmed` | decimal | carga média da hora em MWmed |

Formato do arquivo: CSV UTF-8, separador `;`, ponto decimal.

**Problemas e observações**
- Nenhum nulo, duplicata, buraco ou minuto diferente de zero em 2021 e 2025
  (4 subsistemas × 8.760 h por ano). Layout idêntico nos dois anos.
- Sem negativos nem zeros. Faixa em 2025, por subsistema e hora (os 4 juntos): 6.016 a
  62.150 MWmed.
- **Revisões retroativas:** primeira evidência medida em 02/10/2026. Entre duas cargas full feitas
  com cerca de 75 minutos de diferença (13:50 e 15:06 UTC), os arquivos de 2000 a 2025 ficaram
  iguais em tamanho de texto (e os de 2024 e 2025 idênticos em hash), mas o arquivo do ano
  corrente (2026, as mesmas 26.208 linhas) mudou: a consulta típica leu 69 bytes a menos. Não
  dá para ver o que mudou porque o bronze sobrescreve o arquivo. As revisões passaram a ser versionadas e medidas na tarefa 3.4 (abaixo): o arquivo de 2026 mudou, com 480 valores revisados.
- Veja abaixo o histórico 2000–2025 (layout, nulos, horário de verão e degraus de nível).
- **Carga no BigQuery (tarefa 1.6, 02/10/2026):** os campos vazios do CSV (259 em 2013–2018, os
  nulos documentados abaixo) chegam ao `raw.ons_curva_carga` como **`NULL`**, e não como string
  vazia (259 NULL e 0 strings vazias, conferidos contra os CSVs). Os testes `not_null` do
  dbt pegam esses casos. O raw tem 937.816 linhas (2000 a 01/10/2026).
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
- **Tratado no staging (tarefa 2.2):** o BigQuery converte a hora local inexistente para o mesmo
  instante UTC da hora real seguinte, então as 20 linhas inexistentes são descartadas antes da
  conversão (ver `decisoes.md`); o teste `ons_descarta_so_horas_conhecidas` avisa se aparecer
  outra. O `stg_ons__curva_carga` tem 937.796 linhas e 240 nulos.
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

**Anomalia sem causa conhecida: out/2021 no SE (a curva e a API divergem por 1 mês).** Em
outubro/2021 a carga líquida da API (`val_cargaglobalsmmgd`, área SECO) fica acima da curva horária do
ONS em **todos os dias do mês**, entre +609 e +1.468 MWmed (média mensal **+972 MWmed**, ~2,4% da carga),
depois de uma diferença de +202 em set/2021 e de −55 em nov/2021 (nos últimos dias de set e nos
primeiros de nov a diferença diária é de ~100 a 350 MWmed). A API tem 48 intervalos por dia e a curva 24 horas por dia, sem
falta de dado nos dois lados. Os dados mostram o quê, não o porquê: não sei dizer se é a curva ou a API que sai do
padrão, nem se é revisão, mudança de critério ou erro de publicação (**hipótese não verificada**). Não é a
transição do tipo III (que termina em jun/2021 pela regra de `decisoes.md`) nem a MMGD (que só entra na curva
em mai/2023). Efeito: nenhum ajuste foi feito (a regra de transição termina em jun/2021 e não volta), então
`carga_original_mwmed` e `carga_ajustada_mwmed` de out/2021 do SE valem o mesmo e, se a curva for a que está
errada, o alvo de out/2021 no teste final carrega esse erro. **[pendente]** perguntar ao ONS ou comparar com
a "Carga Mensal" e a "Carga Diária" de out/2021 antes de usar o mês como alvo.

### Revisões do ONS: como são versionadas e medidas (tarefa 3.4, revisado na Sprint 4)

Desde a Sprint 3 o bronze só é regravado quando o MD5 do arquivo muda, e a versão antiga vai para
`bronze/ons/curva_carga_versoes/ano=AAAA/carga=AAAAMMDDTHHMMZ/`. Cada mudança é comparada pela chave
(`id_subsistema`, `din_instante`) e registrada em `data/logs/revisoes_ons.jsonl`. Na Sprint 4 a comparação
passou a ter **tolerância absoluta de 1e-6 MWmed** e a registrar os meses de qualquer linha alterada,
adicionada ou removida (`meses_afetados`), que alimenta a guarda da ingestão incremental. A diferença de 69
bytes de 02/10 não é recuperável (o bronze foi sobrescrito).

**Padrão observado (três versões do arquivo de 2026: 02/10, 06/10 de madrugada e 06/10 à noite; detalhe e
tabela de idades em `metricas.md` e `decisoes.md`):**
- **Só o ano corrente muda.** Os arquivos de 2000 a 2025 ficaram idênticos (hash) nas duas comparações.
- **A revisão depende da IDADE do dado em relação à borda do arquivo (a última hora publicada), não do
  mês do calendário:** 87% das horas dos últimos 2 dias mudam, 36% das de 3 a 6 dias, 8% das de 7 a 13 dias,
  1,6% das de 14 a 27 dias (22 horas, até 5,2 MWmed) e **nenhuma das de 28 dias ou mais**. Nesta amostra
  **nenhuma revisão real passou de 27 dias**.
- **Correção (Sprint 4):** a versão anterior desta seção dizia que 5 linhas de agosto mostravam "revisão de
  dois meses atrás". Eram **ruído de ponto flutuante** (diferenças de até 7,3e-12 MWmed), contadas porque a
  comparação era exata. Com a tolerância elas somem.
- **A magnitude típica é pequena:** a comparação de 02/10 a 06/10 teve diferença máxima de 281,6 MWmed
  (**0,517%**), média absoluta de 9,2 MWmed e soma líquida de -545 MWmed. Só valores numéricos mudam;
  nenhuma linha removida, nenhum nulo virou valor.
- **A diferença de 93,8% (06/10) é valor provisório substituído:** todas as 150 alterações de outubro estão
  no **NE, nos dias 02 e 03/10** (a maior: 7.689 -> 14.902 MWmed), cuja média diária estava em ~10.500 a
  11.600 MWmed e passou para ~15.000, em linha com os dias vizinhos. Não houve hora faltante preenchida (sem
  nulo nem zero, e as 192 linhas novas são horas de 04 e 05/10) nem linha removida. As outras 178
  alterações (setembro) são de até 4,4 MWmed (0,008%). A causa dentro do ONS não é conhecida (backlog).
- **Limite:** são duas comparações em 5 dias, de um arquivo. Um fechamento mensal ou anual pode revisar
  mais e mais tarde; por isso a ingestão tem a guarda (recarrega o ano inteiro se uma alteração cair fora
  da janela de 3 meses) e confere os anos fechados por HEAD.
- **Atraso de publicação:** o arquivo traz dados até **2 dias antes do download** (a última hora é
  23:00 do dia D-2; em 06/10 às 22:00 UTC o arquivo já ia até 05/10), o que calibrou a freshness do ONS
  (`decisoes.md`).

### Testes de qualidade previstos para a Sprint 3 (ONS, curva de carga)

> **Implementados** na 3.2 (ver `decisoes.md`, "Severidade dos testes"): os casos 1 e 2 já são
> cobertos pelo descarte no staging e pelo teste do raw; o 3, pelos dois testes de nulos (error e
> warn); o 4 não virou teste (a lacuna de 1 h por ano até 2018 é aceita).

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
- **Período:** 2021-01-01 até 2026-10-02 (o arquivo de 2026 baixado em 02/10/2026 vai até esse
  dia e tem **26.400 linhas**, 275 dias × 96; ele inclui o dia corrente, porque o
  PLD é divulgado no dia anterior). O arquivo 2001–2020 é **semanal por patamar de carga**,
  não horário: ver a subseção "PLD histórico" abaixo. Dele vem o PLD de 2020, que define o
  preço de contrato de 2021 (`premissas.md`).
- **Atualização:** mensal, com publicação diária por dia de referência.
- **Carga no BigQuery (tarefa 1.7, 02/10/2026):** os três conjuntos da CCEE estão no raw
  (`ccee_pld_horario` com 201.696 linhas, `ccee_pld_semanal` com 12.312 e
  `ccee_consumo_ramo_atividade` com 435), **sem nenhum valor vazio** (0 NULL e 0 strings
  vazias), conferido arquivo a arquivo contra os CSVs.
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
  confirmado na ANEEL (fonte da seção 4 do planejamento): os mínimos batem com o piso de cada ano (ver tabela de limites abaixo). Consequências: (1) o backtest
  2021–2025 mistura regimes muito diferentes de preço (seca em 2021, piso em 2022–2024,
  preços altos em 2025); (2) os cenários de PLD (tarefa 5.7) não podem assumir distribuição
  estável; (3) o teste de faixa da tarefa 3.2 precisa do piso e do teto por ano. Parece haver
  um teto horário e um teto estrutural, com valores diferentes (confirmado: são dois limites, e o
  PLD horário usa o horário). Limites por ano (R$/MWh), guardados em `dbt/seeds/pld_limites.csv`:

  | Ano | Piso | Teto estrutural | Teto horário | Documento |
  |---|---|---|---|---|
  | 2021 | 49,77 | 583,88 | 1.141,85 | REH ANEEL 2.828 (15/12/2020) |
  | 2022 | 55,70 | 646,58 | 1.326,50 | REH ANEEL 2.994 (14/12/2021) |
  | 2023 | 69,04 | 684,73 | 1.404,77 | REH ANEEL (dez/2022, número por confirmar) |
  | 2024 | 61,07 | 716,80 | 1.470,57 | Despacho ANEEL (dez/2023, número por confirmar) |
  | 2025 | 58,60 | 751,73 | 1.542,23 | Despacho ANEEL 3.625 (17/12/2024) |
  | 2026 | 57,31 | 785,27 | 1.611,04 | Despacho ANEEL 3.850 (dez/2025) |

  **Fonte dos valores:** notícias e sites do setor (Abraceel, Cenário Energia, Brasil Energia, Agência
  Gov e a notícia da ANEEL de 2026, esta lida só na busca porque a página exige login); o texto das
  resoluções e despachos **não foi lido**. **[pendente]** conferir o texto oficial de cada ano
  (coluna `confirmado_em_fonte_oficial` do seed). Evidência cruzada com os dados: o mínimo
  observado de cada ano é igual ao piso, e em 2024 e 2026 o máximo observado é igual ao teto
  horário; em 2021 o máximo observado (1.128,72) passou do estrutural, o que mostra que o teto
  do PLD horário é o horário. Usado em `fct_pld_horario_dentro_dos_limites` (error).

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
  com um CSV por estação. **Não funcionou por script** na rede de desenvolvimento (`curl -4`
  devolve código 000, sem conexão), então os ZIPs são **baixados à mão, no navegador**, como os
  da CCEE (passo a passo mais abaixo). Não há API documentada para o histórico.
- **Granularidade:** horária, por estação.
- **Período:** 2000–2026. O ZIP de 2026 vai até 31/08/2026. O projeto usa 2021 em diante.
- **Atualização:** anual, em lote.
- **Tamanho:** ZIPs de 80,6 MB (2021), 90,4 (2022), 107,1 (2023), 102,8 (2024), 90,9 (2025) e
  64,2 MB (2026), 536 MB no total; ~0,8 MB por estação/ano.
- **Estações:** 588 (2021), 567 (2022), 567 (2023), 565 (2024), 594 (2025) e 639 (2026). A rede
  muda: no SE/CO há 271 estações em algum ano de 2021 a 2025 e 236 em todos os 5. Sem códigos
  repetidos dentro de um ano.
- **Fuso:** UTC (explícito na coluna `Hora UTC`).

**Layout: idêntico de 2021 a 2026.** Verificado em todos os arquivos dos ZIPs de 2021 a 2025
(588 + 567 + 567 + 565 + 594 estações) e, no de 2026, nas 37 estações usadas:

| Item | Todos os anos |
|---|---|
| Encoding | latin-1 (não decodifica como UTF-8) |
| Separador / decimal | `;` / vírgula |
| Metadados antes do cabeçalho | 8 linhas, mesmos campos (`REGIAO`, `UF`, `ESTACAO`, `CODIGO (WMO)`, `LATITUDE`, `LONGITUDE`, `ALTITUDE`, `DATA DE FUNDACAO`) |
| Linha de cabeçalho | 1 única variante em todos os arquivos e anos (19 colunas) |
| `Data` | `AAAA/MM/DD` |
| `Hora UTC` | `HHMM UTC` (ex.: `0000 UTC`) |
| Sentinela `-9999` na temperatura | nenhuma ocorrência |
| Cada linha termina com `;` | sim: gera um campo vazio a mais |

Diferenças que existem, todas sem efeito nos dados:
- **O ZIP de 2025 guarda os arquivos dentro de uma pasta `2025/`**; os demais não têm pasta. O
  extrator seleciona a estação pelo código no nome-base do arquivo.
- A precisão da latitude e da longitude nos metadados varia (6 casas em 2021, 8 em 2024).
- Os 19 nomes de coluna padronizam sem colisão.
- 17 medidas por hora; a usada no projeto é `TEMPERATURA DO AR - BULBO SECO, HORARIA (°C)`.

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

**Critério:** temperatura do ar com pelo menos **95% de horas válidas em cada ano de 2021 a
2025**. Horas válidas = horas distintas com temperatura não nula e diferente de `-9999`,
divididas pelas horas do ano (8.760 ou 8.784). Uma hora que falta no arquivo conta como
inválida. O ano de 2026 (parcial) não entra no critério. Escopo: estados do submercado SE/CO
que o projeto cobre: Sudeste (ES, MG, RJ, SP) e Centro-Oeste (DF, GO, MS, MT). Análise
reproduzível a partir dos ZIPs com `uv run python scripts/inmet_cmp.py` (gera
`data/amostras/inmet/completude_estacoes.csv`).

**Resultado: das 236 estações do SE/CO presentes nos 5 anos, 37 passam.** A lista caiu de 72
para 37: os 72 vinham do critério aplicado só a 2021 e 2024, e incluir 2022, 2023 e 2025 tirou
35 estações (as 72 antigas continham as 37 atuais).

| Região | UF | Presentes nos 5 anos | Passam |
|---|---|---|---|
| SE | ES | 11 | 4 |
| SE | MG | 68 | 14 |
| SE | RJ | 25 | 6 |
| SE | SP | 38 | 4 |
| CO | DF | 5 | 4 |
| CO | GO | 26 | 3 |
| CO | MS | 27 | 2 |
| CO | MT | 36 | **0** |

As 37 estão no ZIP de todos os anos, inclusive no de 2026. A lista é a constante `ESTACOES` em
`ingestion/inmet.py`. Percentual de horas válidas (2021 / 2022 / 2023 / 2024 / 2025):

- **DF:** A001 Brasilia (100,0/100,0/99,9/99,7/99,8); A042 Brazlandia (98,0/97,7/96,5/97,3/99,8); A046 Gama (Ponte Alta) (100,0/99,2/99,8/99,2/99,5); A047 Paranoa (Coopa-Df) (97,7/97,1/95,7/95,3/99,8).
- **ES:** A617 Alegre (97,2/100,0/100,0/100,0/96,5); A614 Linhares (100,0/100,0/100,0/100,0/99,9); A616 Sao Mateus (100,0/99,5/99,8/99,7/99,7); A633 Venda Nova Do Imigrante (98,9/99,4/98,8/97,8/99,8).
- **GO:** A034 Catalao (100,0/97,0/100,0/100,0/99,9); A036 Cristalina (100,0/97,7/99,5/100,0/99,8); A037 Silvania (100,0/95,3/99,3/97,9/99,8).
- **MG:** A508 Almenara (99,3/98,3/97,8/99,5/99,8); A502 Barbacena (99,8/99,5/96,9/99,8/99,4); A521 Belo Horizonte (Pampulha) (100,0/99,9/100,0/100,0/99,9); F501 Belo Horizonte - Cercadinho (98,4/99,1/100,0/100,0/99,6); A554 Caratinga (100,0/99,8/97,1/99,9/99,8); A520 Conceicao Das Alagoas (99,8/99,3/99,3/97,0/98,6); A540 Mantena (100,0/100,0/98,5/100,0/99,9); A531 Maria Da Fe (100,0/100,0/100,0/100,0/99,9); A539 Mocambinho (100,0/100,0/100,0/99,8/99,7); A509 Monte Verde (99,7/97,1/100,0/99,9/99,9); A506 Montes Claros (100,0/100,0/100,0/100,0/99,9); A570 Oliveira (100,0/100,0/95,5/98,2/99,8); A516 Passos (99,2/99,4/99,7/99,4/99,0); A507 Uberlandia (98,9/100,0/98,5/100,0/99,8).
- **MS:** A756 Agua Clara (100,0/95,4/99,9/99,8/99,9); A704 Tres Lagoas (100,0/100,0/100,0/100,0/99,9).
- **RJ:** A607 Campos Dos Goytacazes (100,0/99,5/99,8/100,0/99,9); A624 Nova Friburgo - Salinas (97,5/100,0/100,0/100,0/99,9); A626 Rio Claro (99,3/99,3/96,2/97,0/99,8); A621 Rio De Janeiro - Vila Militar (100,0/99,5/97,6/99,9/99,8); A601 Seropedica-Ecologia Agricola (100,0/100,0/99,9/99,9/99,9); A659 Silva Jardim (100,0/99,8/99,9/99,6/99,5).
- **SP:** A763 Marilia (100,0/100,0/98,7/99,7/99,8); A747 Pradopolis (100,0/100,0/100,0/97,8/99,9); A701 Sao Paulo - Mirante (100,0/100,0/97,6/99,8/99,5); A770 Sao Simao (98,6/98,6/97,2/96,3/97,8).

**Observações sobre o resultado**
- Com um limiar de 90% seriam **52** estações (SP 6, GO 5, MS 5, MG 18, RJ 9, DF 5, ES 4).
  15 estações ficam de fora por pouco, em 1 ou 2 anos (por exemplo Campo Grande, 90,4% em
  2022; Luziânia, 91,8% em 2023; Juiz de Fora, 90,8% em 2025). O raw guarda só as 37, mas o
  **bronze guarda todos os ZIPs com todas as estações**, então reprocessar com outra lista
  custa só uma nova carga.
- **Poucas estações em alguns estados:** MS tem 2, GO tem 3, SP e ES têm 4. A média do estado
  fica frágil nesses casos (uma estação com problema pesa muito). Reavaliar na Sprint 2 se
  vale afrouxar o critério.
- **Distribuição desigual:** MG tem 14 das 37 estações e SP só 4 (a capital só tem a A701
  Mirante). Uma média simples ficaria dominada por MG, embora SP seja o maior centro de carga.
  Por isso a agregação é em dois passos, com peso por estado (abaixo).
- **MT está excluído:** nenhuma das 36 estações do MT presentes nos 5 anos passa (com 2021 e
  2024 só havia uma, Alto Taquari, no limite). O peso do MT é redistribuído entre os outros 7
  estados (ES, MG, RJ, SP, DF, GO, MS).

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

### O que o staging do INMET revelou (tarefa 2.2)

Os metadados da estação **mudam entre os arquivos**, e cada linha do raw leva os do seu ZIP:
- **14 das 37 estações têm coordenadas diferentes entre os anos.** Na maioria é só precisão (6 casas em 2021, 8 em 2024), mas **duas mudaram de lugar**: a **A042 Brazlândia (DF) se mudou cerca de 9 km em 2026** (de −15,5997, −48,1311 para −15,6525, −48,2014) e a **A704 Três Lagoas (MS) cerca de 1,3 km em 2023** (de −20,7833 para −20,7950). Mudar de lugar quebra a continuidade da série da estação (outro microclima). A Três Lagoas é também uma das que degradaram em 2026.
- **A A521 BH Pampulha aparece com dois nomes** (`BELO HORIZONTE (PAMPULHA)` e `BELO HORIZONTE - PAMPULHA`).
- **Impacto na `dim_estacao` (tarefa 2.3):** a dimensão deve tomar o registro mais recente da estação (maior `instante_utc`), não um valor qualquer, e registrar que a Brazlândia (e, antes, a Três Lagoas) mudou de lugar.

### Carga no raw (`raw.inmet_estacoes_horario`, tarefa 1.8)

- **Só as 37 estações**, de todos os ZIPs (2021 a 2026): 1.837.272 linhas (324.120 por ano
  completo de 365 dias, 325.008 em 2024, que é bissexto, e 215.784 em 2026, até 31/08).
- **Colunas:** as 19 da fonte padronizadas (`data`, `hora_utc`, ..., `vento_velocidade_horaria_m_s`),
  mais `estacao_codigo`, `estacao_uf`, `estacao_nome`, `estacao_latitude`, `estacao_longitude`
  (dos metadados do arquivo), `_arquivo_origem` (o caminho do ZIP no bronze, por exemplo
  `bronze/inmet/ano=2024/2024.zip`) e `_carregado_em`. Tudo STRING (inclusive o decimal com
  vírgula, como `-23,49638888`), sem partição.
- **Temperatura vazia:** nas 37 estações há 24.781 horas sem valor de temperatura (1,35% de
  1.837.272). Os campos vazios chegam ao BigQuery como `NULL` (0 strings vazias), como no ONS, e
  a carga confirmou as contagens por ZIP e estação (222 grupos, validação ok).
- **Os nulos se concentram em 2026 e em poucas estações:**

| Ano | Temperatura vazia |
|---|---|
| 2021 | 0,49% |
| 2022 | 0,88% |
| 2023 | 1,10% |
| 2024 | 0,81% |
| 2025 | 0,41% |
| **2026 (jan–ago)** | **5,94%** |

  Por UF: GO 4,21%, MS 2,07%, DF 1,27%, MG 1,21%, SP 1,02%, ES 0,75%, RJ 0,68%. Nenhuma das 37
  estações tem 0 vazios.
- **O critério olha para trás e não garante o futuro.** Em 2026 (jan–ago, 5.832 horas), **10 das
  37 estações têm menos de 95% de horas válidas e 5 têm menos de 90%**: A037 Silvânia (GO) só
  13,6% válido, A704 Três Lagoas (MS) 72,5%, A554 Caratinga (MG) 77,6%, A516 Passos (MG) 81,6% e
  A502 Barbacena (MG) 83,8%. Para o GO, que só tem 3 estações, a média do estado em 2026 fica
  praticamente em 2 estações; para o MS, que tem 2, fica quase só na A756 Água Clara (a Três
  Lagoas tem 72,5% de horas válidas). Isso pesa nas análises que
  usarem 2026 (a análise de erro e o acompanhamento diário do contrato). Para a Sprint 3, vale um
  teste de completude mensal por estação (e por estado) no staging, que avise quando uma estação
  selecionada degrada.

---

## Feriados nacionais (biblioteca `holidays`)

- **Fonte:** biblioteca Python `holidays` (versão 0.105, travada no `uv.lock`), feriados
  nacionais do Brasil, **sem arquivo-fonte nem bronze**. Carregados por
  `uv run python -m ingestion.feriados`.
- **Escopo:** 2000 a 2030 (285 linhas; o histórico serve à previsão mensal desde 2000 e à curva
  do consumidor, e os anos futuros à projeção). Colunas no raw: `data` (texto `AAAA-MM-DD`), `nome`
  e `_carregado_em`. Só feriados nacionais (estaduais e municipais não são tratados).
- **Datas com dois feriados vêm numa linha só**, com os nomes separados por "; ". No intervalo
  carregado só há uma: 2000-04-21 ("Sexta-feira Santa; Tiradentes"). O staging desmembra, se
  precisar.
- **O resultado depende da versão da biblioteca.** Por exemplo, o Dia Nacional de Zumbi e da
  Consciência Negra é feriado nacional só a partir de 2024 (a lib não o lista em 2023). A
  versão fica registrada no log da carga.

---

## Download manual dos arquivos da CCEE

**Por quê:** o portal da CCEE devolve HTTP 403 ("Acesso bloqueado") para downloads e para a API
feitos por script, e informa que o bloqueio vem de política de segurança. Por isso **os
arquivos da CCEE são baixados à mão, no navegador**, e o projeto não tenta contornar o bloqueio
(ver `decisoes.md`). Os links de download também têm hash opaco e podem mudar, então não vale
guardá-los no código. O extrator (`ingestion/ccee.py`) lê uma pasta local; o INMET e o ONS não
precisam disso.

**Quem clonou o repositório precisa fazer isto uma vez** (e repetir para atualizar o ano
corrente):

1. **Instalar o ambiente e criar a pasta** (a pasta é ignorada pelo git):
   ```bash
   uv sync
   mkdir -p data/manual/ccee
   ```
2. **PLD horário, de 2021 até o ano atual.** Abrir
   https://dadosabertos.ccee.org.br/dataset/pld_horario no navegador. Na lista de recursos
   ("Dados e Recursos"), abrir o recurso de cada ano (2021, 2022, ... até o ano atual), usar o
   botão de download do CSV e salvar com o nome exato `pld_horario_AAAA.csv` em
   `data/manual/ccee/`.
3. **PLD histórico semanal.** Na mesma página, o recurso **"2001-2020"**. Salvar como
   `pld_historico_semanal_2001_2020.csv`. Este arquivo é semanal por patamar de carga, não
   horário (ver "PLD histórico semanal 2001–2020" acima).
4. **Consumo por ramo de atividade.** Abrir
   https://dadosabertos.ccee.org.br/dataset/consumo_ramo_atividade, baixar os recursos de 2024
   até o ano atual e salvar como `consumo_ramo_atividade_AAAA.csv`.
5. **Conferir** se tudo está no lugar (não usa a nuvem nem o `.env`):
   ```bash
   uv run python -m ingestion.ccee --verificar
   ```
   Se faltar arquivo, o comando diz qual, de qual página baixar e com que nome salvar.
6. **Carregar** (grava no GCS e no BigQuery, precisa do `.env` e do `gcloud auth
   application-default login`):
   ```bash
   uv run python -m ingestion.ccee
   ```

**Arquivos esperados** (nomes exatos; os de 2025 e 2026 têm layout diferente dos de 2021–2024,
o que o extrator aceita):

| Arquivo | Página | Recurso | Tamanho aprox. | Linhas |
|---|---|---|---|---|
| `pld_horario_2021.csv` a `pld_horario_AAAA.csv` | pld_horario | cada ano | 0,8 a 1,3 MB | ~35 mil por ano completo |
| `pld_historico_semanal_2001_2020.csv` | pld_horario | "2001-2020" | 0,45 MB | 12.312 |
| `consumo_ramo_atividade_2024.csv` a `..._AAAA.csv` | consumo_ramo_atividade | cada ano | 10 a 16 KB | 120 a 180 por ano |

**Atualizar:** o PLD é publicado todo dia, então o arquivo do ano corrente envelhece. Para
atualizar, baixe de novo o arquivo do ano corrente (e o consumo por ramo, que é mensal), troque
na pasta e rode o extrator outra vez. A carga é full: regrava tudo. O nome do arquivo não traz a
data do download; o extrator registra no log o tamanho e a data de modificação de cada arquivo.

**O que o extrator confere antes de tocar na nuvem** (para pegar erro de download manual):
cabeçalho com as colunas esperadas, arquivo sem linhas, e meses coerentes com o nome (o
`pld_horario_2024.csv` só pode ter meses de 2024; o semanal, meses entre 2001 e 2020). Um arquivo
baixado do recurso errado para antes da carga, com a mensagem do que está errado.

> **Nota para conferência:** os nomes dos botões e dos recursos acima foram escritos a partir da
> estrutura da página que consultei (lista de recursos por ano, mais o recurso "2001-2020"), não
> de uma sessão de download. Quem fez o download deve conferir o passo a passo.

---

## Download manual dos ZIPs do INMET

**Por quê:** o download por script não funcionou na rede de desenvolvimento (`curl -4` devolveu
código 000, sem conexão). Por isso **os ZIPs são baixados à mão, no navegador**, como os da
CCEE. O extrator (`ingestion/inmet.py`) lê a pasta local.

**Quem clonou o repositório precisa fazer isto uma vez** (e repetir para atualizar o ano
corrente):

1. **Criar a pasta** (ignorada pelo git):
   ```bash
   mkdir -p data/manual/inmet
   ```
2. **Baixar um ZIP por ano, de 2021 até o ano atual**, em
   https://portal.inmet.gov.br/dadoshistoricos (link "(AUTOMÁTICA)" de cada ano). A URL direta
   segue o padrão `https://portal.inmet.gov.br/uploads/dadoshistoricos/AAAA.zip`. Salvar com o
   nome exato `AAAA.zip` (por exemplo `2024.zip`) em `data/manual/inmet/`. Cada ZIP tem de 64
   a 107 MB, 536 MB no total.
3. **Conferir** se tudo está no lugar (não usa a nuvem nem o `.env`):
   ```bash
   uv run python -m ingestion.inmet --verificar
   ```
   Se faltar ZIP, o comando diz qual e de onde baixar.
4. **Carregar** (grava no GCS e no BigQuery; precisa do `.env` e do `gcloud auth
   application-default login`):
   ```bash
   uv run python -m ingestion.inmet
   ```

**Atualizar:** o ZIP do ano corrente é parcial (o de 2026 vai até 31/08/2026) e é atualizado
pelo INMET em lote. Para atualizar, baixe de novo o ZIP do ano corrente, troque na pasta e rode
o extrator outra vez (a carga é full).

**O que o extrator confere antes de gravar o ZIP na nuvem:** que o arquivo é um ZIP íntegro
(um download interrompido costuma gerar ZIP truncado), que as 37 estações selecionadas estão
nele, e, estação a estação, que o código e a UF dos metadados batem com os esperados, que o
cabeçalho tem as 19 colunas e que as datas são do ano do ZIP (pega ZIP baixado com nome
trocado).

**Mudar a lista de estações:** os ZIPs guardam todas as estações. Para recalcular o critério,
`uv run python scripts/inmet_cmp.py 2021 2022 2023 2024 2025`, e atualizar a constante
`ESTACOES` em `ingestion/inmet.py`.

> **Nota para conferência:** os nomes dos links acima foram escritos a partir da estrutura da
> página consultada, não de uma sessão de download. Quem fez o download deve conferir.

---

## Mapa dos fusos horários

| Fonte | Fuso original | Tratamento |
|---|---|---|
| ONS | Horário oficial local (confirmado pelo teste de horário de verão), com horário de verão até 2018 | Bronze e raw sem alteração; staging converte para UTC com `America/Sao_Paulo` (tratar linhas nulas de 00:00 em dias de início de horário de verão, 2014–2018) |
| CCEE PLD | Brasília | idem |
| INMET | UTC | Já em UTC; apenas montar o timestamp |
| CCEE consumo | n/a (mensal) | n/a |
