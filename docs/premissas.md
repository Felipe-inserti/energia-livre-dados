# Premissas do projeto

Este documento reúne todas as premissas do consumidor-exemplo e do contrato de energia.
Elas existem porque o consumo de uma empresa específica não é público. Toda premissa
tem justificativa e, quando o resultado depende dela, entra na análise de sensibilidade.
Pendências estão marcadas com **[pendente]**.

---

## 1. Consumidor-exemplo

| Item | Premissa | Justificativa |
|---|---|---|
| Tipo | Supermercado de porte médio (1.500 a 3.000 m² de área de vendas) | Refrigeração 24h + operação de loja geram uma curva com padrão claro |
| Conexão | Média tensão (Grupo A) | Consumidores do Grupo A já podem migrar para o mercado livre |
| Submercado | Sudeste/Centro-Oeste. **Correspondência entre fontes: SE/CO = `SE` (ONS, `id_subsistema`) = `SUDESTE` (CCEE, `SUBMERCADO`)** | Maior submercado. A `dim_submercado` do dbt deve mapear os três nomes |
| Representação na CCEE | Por comercializadora varejista | Forma usual para consumidores desse porte |
| Consumo médio (caso base) | 100 MWh/mês (~0,137 MWm) | Ordem de grandeza de um supermercado médio. **[pendente]** confirmar com fonte pública (ex.: ABRAS, Procel ou estudos de eficiência energética no varejo) |

O consumo médio é um parâmetro de escala: a economia **em %** do backtest não depende dele,
só a economia em R$.

**O backtest de 2021–2023 é contrafactual.** Com ~137 kW de carga média, o consumidor não
atenderia o limite de carga exigido para migrar ao mercado livre nesses anos. Segundo a
regulação, o limite caiu em etapas até 500 kW (2023) e só em jan/2024 qualquer consumidor do
Grupo A passou a poder migrar. **[pendente]** confirmar os limites por ano na legislação (de
memória: ~1,5 MW em 2021, 1 MW em 2022, 500 kW em 2023). Os resultados desses anos mostram
o que o método teria feito, não o que um consumidor real poderia ter feito.

---

## 2. Curva de consumo sintética

O dataset de consumo por ramo da CCEE é mensal e agregado (ver `fontes.md`), então a curva
horária é construída por premissa, a partir da carga **real** do ONS:

```
consumo_h (MWh) = k × L_d × p(h, tipo_de_dia)
```

- `L_d`: carga média diária do SE/CO (MWmed), do ONS (`curva-carga`, `id_subsistema = SE`), no
  dia local `d`.
- `p(h, tipo_de_dia)`: perfil da loja, com **40% de refrigeração constante nas 24 h** e **60% de
  operação concentrada no horário de funcionamento**, normalizado para **média 1 em cada dia**.
  Em horas de funcionamento, `p = 0,4 + 0,6 × 24 / N`, e fora delas `p = 0,4`, onde `N` é o
  número de horas abertas no dia (a soma das 24 horas dá 24).
- `k`: um único fator para todo o período, ajustado para que o consumo médio seja de
  100 MWh/mês no período 2020–2025.

| Parâmetro | Valor | Observação |
|---|---|---|
| Participação da refrigeração | 40% | Valor inicial; **[pendente]** fonte |
| Horário de funcionamento | seg–sáb 7h–22h (15 h); dom 8h–20h (12 h) | Horário local; a curva é gerada no horário local e convertida para UTC (ver `decisoes.md`, fuso) |
| Tipo de dia | dia útil, sábado, domingo, feriado nacional | Feriado nacional opera como domingo (lib `holidays`). Feriados estaduais e municipais não são tratados |
| Ruído | nenhum | A curva é determinística (carga real × perfil), o que a deixa reprodutível e com uma premissa a menos |
| Temperatura | **não entra na curva** | Ver seção 3 |

**O que é o `k` (e por que não é vazamento no backtest).** O `k` é uma **definição do tamanho do cliente**,
calibrada no período 2020–2025 para que o consumo médio seja de 100 MWh/mês (~0,1369 MWm exatos: 7.200 MWh em
52.608 h; o "~0,137" da seção 1 é essa conta arredondada). Ele multiplica a curva inteira por uma constante, então
**escala o custo e a economia em R$ na mesma proporção** e não muda a economia em %, nem qual volume `V` é o ótimo
em relação ao consumo previsto. Por isso calibrá-lo com dados de 2020–2025 não carrega informação do futuro para a
decisão de nenhum ano do backtest: um cliente 2× maior daria o dobro de R$ e a mesma decisão em %. O valor está
congelado em `dbt_project.yml` (`k_consumo = 3,2752385e-6`, 2.192 dias completos) e um teste do dbt falha se uma
revisão do dado o afastar mais de 0,5% da calibração.

**Por que `k` único e não por ano ou por mês:** calibrar por mês removeria a sazonalidade e o
efeito de meses com 28 e 31 dias; calibrar por ano faria todos os anos terminarem com o mesmo
consumo, e a estratégia ingênua (média do ano anterior) acertaria o nível por construção.
Com um `k` único, o consumo anual varia como a carga real do SE/CO varia.

**Consequência da curva:** o consumo mensal do consumidor é `k` vezes a energia mensal do SE/CO
(o perfil tem média 1 por dia). Por isso prever a **carga mensal do SE/CO** é prever o consumo
mensal do consumidor, a menos do fator `k`.

**Qual definição de carga:** a **bruta** (consumo total, com a MMGD e as usinas não despachadas).
A MMGD de terceiros não reduz o que a loja consome; a carga líquida cai ao meio-dia só porque há
mais painéis. A curva do ONS não tem uma definição só (líquida de MMGD até abr/2023; sem as
usinas não despachadas até fev/2021), então a série usada é a **ajustada** de `fct_carga_mensal`
(`carga_ajustada_mwmed`), com a original preservada ao lado (pendência 6, resolvida).

**Sazonalidade como checagem de plausibilidade:** a sazonalidade mensal da curva é comparada
com a do ramo COMÉRCIO da CCEE (disponível de abr/2024 em diante, unidade **[pendente]**). Ela
não calibra nada; só indica se a forma é razoável.

**Limitação herdada:** a forma semanal e o nível diário vêm da carga do SE/CO, que cai nos
fins de semana por causa da indústria. Um supermercado vende mais nesses dias. Aceito por
simplicidade (ver seção 6).

### Calendário (`dim_tempo`)

A `dim_tempo` tem uma linha por hora UTC e traduz cada instante para o relógio e o calendário locais
(America/Sao_Paulo). Feriado, dia da semana, tipo de dia e estação usam sempre a **data local**.

| Atributo | Definição |
|---|---|
| `eh_feriado` | Feriado nacional da biblioteca `holidays` (a mesma lista de `raw.feriados`). Inclui o Dia da Consciência Negra a partir de 2024; **não** inclui Carnaval nem Corpus Christi |
| `tipo_dia` | `dia_util`, `sabado` ou `domingo_feriado`. Feriado (`eh_feriado`) e domingo valem `domingo_feriado`, inclusive o feriado que cai num sábado: é o "feriado nacional opera como domingo" da curva de consumo |
| `estacao_do_ano` | Estação meteorológica do hemisfério sul, fechada por mês: verão (dez a fev), outono (mar a mai), inverno (jun a ago), primavera (set a nov) |
| `eh_feriado_aneel` | Os **11 feriados nacionais que a ANEEL considera para o horário de ponta**: 1º de janeiro, terça-feira de Carnaval, Sexta-feira Santa, Tiradentes, 1º de maio, Corpus Christi, 7 de setembro, 12 de outubro, Finados, 15 de novembro e Natal. Não inclui a Consciência Negra |
| `eh_horario_ponta` | Premissa: 3 horas locais, das **18h às 20h59**, de segunda a sexta, fora dos feriados da ANEEL |

- **Dois conceitos de feriado, de propósito.** O `eh_feriado` serve ao calendário da curva e da
  previsão (inclui a Consciência Negra desde 2024, e a loja não fecha no Carnaval); o `eh_feriado_aneel`
  serve só ao horário de ponta. Eles divergem na Consciência Negra (só no primeiro), no Carnaval e no
  Corpus Christi (só no segundo).
- **A lista da ANEEL** está na página oficial de postos tarifários
  (https://www.gov.br/aneel/pt-br/assuntos/tarifas/entenda-a-tarifa/postos-tarifarios). A terça de
  Carnaval e o Corpus Christi não estão no `raw.feriados`; a `dim_tempo` os deriva da Sexta-feira
  Santa (Carnaval = −45 dias, Corpus Christi = +62), e um teste confere a aritmética contra a
  biblioteca de 2000 a 2030. A lista é a vigente: foi lida na página oficial atual, vale para
  2021–2025 e é aplicada a todos os anos de 2000 a 2030 sem ter sido verificada para o período
  anterior a 2021.
- **O horário de ponta é uma premissa.** A ANEEL define a ponta como "período diário de 3h
  consecutivas, com exceção feita aos sábados, domingos e feriados nacionais", e quem escolhe as 3
  horas é a **distribuidora**, na revisão tarifária (o padrão mais comum é 18h às 21h, mas varia por
  concessionária). O projeto adota 18h–20h59 em todo o SE/CO. É parametrizável (`hora_ponta_inicio` e
  `horas_de_ponta` no `dbt_project.yml`).
- **A ponta não entra no cálculo do contrato nem na curva de consumo** (a curva usa o horário de
  funcionamento da loja, e o contrato é modulado pela carga e liquidado pelo PLD ponderado pelo
  consumo). Ela só serve à **análise** (por exemplo, olhar a carga e o PLD na ponta e fora dela).

---

## 3. Previsão

### Previsão central: carga mensal do SE/CO, 12 meses à frente

O contrato é decidido **uma vez por ano, antes do início do ano**. Nesse horizonte não existe
previsão de temperatura nem defasagem de curto prazo. Por isso o alvo é a carga **mensal** do
SE/CO, 12 meses à frente, e não a horária.

- **Histórico:** ONS desde 2000 (carga horária agregada para mensal). A série ajustada para a
  definição bruta só existe a partir de 2018 (a API do ONS que mede os ajustes começa aí); antes
  de 2018 vale a série original (pendência 16).
- **Baseline:** mesmo mês do ano anterior (**sazonal ingênuo**), mais o sazonal multiplicado pelo
  crescimento dos últimos 12 meses. Medidos na Sprint 4 (`docs/metricas.md`, `docs/resultados/`).
- **Modelo (Sprint 5, fechado):** a **média simples de ETS, SARIMA e regressão ridge** (tendência local,
  mês, dias úteis efetivos e dias do mês) sobre a série reconstruída, com **janela móvel de 72 meses** e os
  meses de abr e mai/2020 imputados. Escolhido pelo critério congelado no desenvolvimento (2,66% contra
  2,92% do ingênuo, vitória de 0,255 pp, menor que 1 erro-padrão); o LightGBM perdeu. A Sprint 6 usa esta
  média **independentemente do resultado do teste final**, que só reporta desempenho (`decisoes.md`).
- **Validação:** backtest mensal em **rolling origin** com janela crescente, horizontes de 1 a
  12 meses, sempre só com informação anterior à origem (a previsão só recebe a série até a
  origem). Alvos: desenvolvimento 2012–2019 (escolha de modelos), 2020 à parte (estresse) e
  teste final 2021–2025 (usado uma vez, alinhado ao backtest da Sprint 6). Métricas: MAPE, MAE
  em MWmed e **viés com sinal** (por horizonte, geral e na origem de dezembro) e o erro do ano
  inteiro. Só entram meses fechados com cobertura de pelo menos 95% (`mes_utilizavel`).
- **O erro desse backtest gera os cenários de consumo** da otimização. O erro é medido na
  mesma escala da decisão (mensal), porque o erro horário subestimaria a incerteza do consumo
  anual.
- **Regra dos intervalos e dos cenários (Parte B, `decisoes.md`):** em **produção** (previsões além dos
  dados) os quantis e a reamostragem usam os erros do desenvolvimento e do teste final **juntos**. No
  **backtest da Sprint 6** a calibração é **crescente no tempo**: na origem `t` só entram os erros cujo
  mês-alvo é `<= t` (um vetor de 12 erros só quando o último mês-alvo dele é `<= t`). Usar erros de
  2023–2024 nos cenários da origem dez/2022 seria vazamento e deixaria a economia em R$ otimista.
  Implementada e testada em `ml/intervalos.py`. Os intervalos do desenvolvimento cobriram 70% (nominal
  80%) e 88% (nominal 95%) no teste final: o clima (σ ~1,5–1,8% do mês, não previsível a 12 meses) é o
  piso da incerteza.
- **Outliers:** os períodos de 2001–2002 (racionamento) e 2020 (pandemia) afetam o treino e a
  distribuição do erro. Na validação, 2020 é reportado à parte (estresse) e não entra na escolha
  de modelos. **[pendente, Sprint 5]** decidir o tratamento no treino (excluir, variável
  indicadora) e registrar em `decisoes.md`.

### Extra opcional: previsão horária D+1

LightGBM com temperatura e defasagens de curto prazo, para uso operacional diário. Não entra no
backtest do contrato e só é feito depois do resto.

### Temperatura (análise de erro)

A temperatura **não entra na curva nem na previsão central**. Ela serve para analisar onde o
erro da previsão é maior (ondas de calor) e para o extra horário D+1.

- **Dados:** INMET 2021 em diante.
- **Estações:** temperatura com pelo menos 95% de horas válidas em cada ano analisado (ver
  `fontes.md` e `decisoes.md`).
- **Estados incluídos:** ES, MG, RJ, SP, DF, GO e MS. **MT está excluído** (só 1 estação passa
  no critério, perto do limite). O peso dele é redistribuído proporcionalmente entre os demais.
- **Agregação em dois passos:** (1) média horária das estações de cada estado; (2) média entre
  estados ponderada pelo peso de cada estado no consumo de energia do SE/CO.
- **Pesos por estado:** de fonte oficial (ex.: Anuário Estatístico de Energia Elétrica da EPE),
  ano de referência e se são fixos ou variam no tempo. **[pendente]**
- **Falhas:** numa hora sem nenhuma estação com dado em um estado, a temperatura do estado é
  **imputada dentro do próprio estado** (hora anterior ou perfil típico daquele dia). Não se
  redistribui o peso, porque isso criaria saltos de vários graus na média. Se faltar dado em
  todos os estados numa hora, a hora fica marcada como ausente.

---

## 4. Contrato de energia (simplificado)

| Item | Premissa (caso base) | Sensibilidade |
|---|---|---|
| Formato | Contrato anual de volume `V` (MWm), **modulado pela carga**: dentro de cada mês, a energia contratada é distribuída no formato do consumo | — |
| Prazo | 1 ano civil (jan–dez), decidido antes do início do ano | — |
| Preço do contrato `P_t` | PLD médio do ano `t−1` + spread | Spread R$ 0, 20 e 40/MWh; caso base R$ 20 |
| Banda de flexibilidade `f` | ±10% do volume contratado, apurada por mês | ±5% e ±15% |
| Liquidação das diferenças | Pelo PLD do SUDESTE, ponderado pelo consumo do mês | — |

**Preço do contrato.** Não existe série pública confiável de preços de contratos para
2021–2025. Um preço fixo (ex.: R$ 200/MWh) faria o resultado depender de onde o PLD ficou: em
2022 ele ficou abaixo de R$ 200 em 100% das horas. Por isso `P_t` acompanha o mercado:
- `PLD médio do ano t−1` = média simples das horas do SUDESTE (2021 em diante).
- Para 2020 (que dá o preço de 2021), o dado vem do arquivo semanal 2001–2020 do portal da
  CCEE, **ponderando pelas horas de cada semana**, com a média simples dos 3 patamares de carga
  (o arquivo não identifica o patamar). Resultado: **R$ 178,03/MWh** no SUDESTE, com erro
  máximo de R$ 4,84 pelos extremos (aproximação aceita, limite de R$ 20; ver `fontes.md`).
  Logo, `P_2021` = R$ 198,03/MWh no caso base.

### Cálculo do custo de um mês

Para cada mês `m`:
- `C_m` = consumo do mês (MWh), da curva sintética.
- `V_m` = `V` × horas do mês (MWh contratados).
- Faixa de flexibilidade: `[V_m × (1 − f), V_m × (1 + f)]`.
- `E_m` = energia contratada efetivamente entregue = `C_m` limitado à faixa, isto é,
  `min(max(C_m, V_m × (1 − f)), V_m × (1 + f))`.
- `PLDp_m` = `Σ_h consumo_h × PLD_h / C_m` (PLD do mês ponderado pelo consumo).
- **`custo_m = E_m × P_t + (C_m − E_m) × PLDp_m`**. Se `C_m − E_m > 0` há compra do excedente
  pelo PLD; se `< 0` há venda da sobra pelo PLD.

| Situação | `E_m` | Efeito |
|---|---|---|
| `C_m` dentro da faixa | `C_m` | Paga `C_m × P_t`, sem exposição ao PLD |
| `C_m` acima da faixa | limite superior | Paga o limite superior × `P_t` e compra o excedente pelo PLD |
| `C_m` abaixo da faixa | limite inferior | Paga o limite inferior × `P_t` (compromisso mínimo) e vende a sobra pelo PLD |

**Por que o PLD ponderado pelo consumo vale para a compra e para a venda:** com o contrato
modulado pela carga, o volume entregue em cada hora é proporcional ao consumo da hora. A
diferença em cada hora também fica proporcional ao consumo, então a ponderação pelo consumo é
exata para excedente e para sobra. A simplificação é supor a modulação perfeita (seção 6).

**Custo anual** = soma dos 12 meses.

**Consequência a lembrar:** dentro da faixa o custo é `C_m × P_t` e não depende de `V`. As
estratégias só diferem nos meses em que o consumo sai da faixa de alguma delas.

### Lastro: cobertura de 100% do consumo e penalidade por insuficiência

O mercado livre exige cobertura contratual da carga. Resumo do que foi confirmado e do que não:

| Item | Situação |
|---|---|
| Consumidores não supridos integralmente em condições reguladas devem garantir **100% de suas cargas** por geração própria ou contratos registrados na CCEE (Decreto 5.163/2004, art. 2º, III) | **Confirmado** em fonte oficial (texto do decreto, versão da Câmara dos Deputados) |
| A CCEE afere o cumprimento **mensalmente** e aplica penalidade (Decreto 5.163/2004, art. 3º) | **Confirmado** (idem) |
| A penalidade por insuficiência de lastro se baseia em **histórico de 12 meses** | **Confirmado** na página de penalidades da CCEE |
| Valor anual de referência (VR) usado na penalidade; **VR de 2026 = R$ 290,12/MWh** | **Confirmado** na página de penalidades da CCEE |
| Fórmula exata: penalidade = maior valor entre o PLD e o VR, sobre a exposição média dos 12 meses; tolerância à insuficiência; VR dos anos 2021–2025 | **[pendente]**: aparece em fontes secundárias, e o documento oficial (Caderno de Regras nº 13, "Penalidades de Energia", da CCEE) não foi lido em texto |

**Decisão: limite inferior de `V` = `1/(1+f)` do consumo previsto.** A regra de lastro (Decreto
5.163/2004, art. 2º, III, e art. 3º) exige cobertura de 100% da carga, e contratar menos gera
penalidade. O VR (R$ 290,12 em 2026) fica bem acima do PLD médio de 2022–2024 (R$ 59 a
R$ 128), então comprar a diferença pelo PLD sairia bem mais caro do que o modelo de custo
indica. O menor `V` que ainda cobre o consumo médio usando toda a banda de flexibilidade é
`consumo previsto / (1 + f)`:

| Banda `f` | Limite inferior de `V` |
|---|---|
| ±5% | ≈ 95% do consumo previsto |
| ±10% (caso base) | ≈ 91% do consumo previsto |
| ±15% | ≈ 87% do consumo previsto |

O limite superior continua em **120%**. O limite inferior acompanha a banda da sensibilidade.

**Penalidade não modelada (extra).** Com esse limite, o modelo de custo não inclui a penalidade
de insuficiência. Modelá-la depende das pendências da tabela acima (fórmula, tolerância e VR
2021–2025) e está na lista de extras do planejamento. **Risco residual:** se o consumo real
superar a previsão a ponto de a cobertura média dos 12 meses ficar abaixo de 100%, haveria
penalidade que o modelo não captura; o backtest deve reportar quantos anos isso ocorreria
(consumo real maior que `V × (1 + f)`).

Fontes: https://www.ccee.org.br/penalidades (VR 2026 e histórico de 12 meses) e o texto do
Decreto 5.163/2004 (https://www2.camara.leg.br/legin/fed/decret/2004/decreto-5163-30-julho-2004-533148-normaatualizada-pe.html).

---

## 5. Estratégias comparadas no backtest

| Estratégia | Como define `V` para o ano `t` |
|---|---|
| Ingênua | Consumo médio do ano `t − 1`, sem limite |
| Previsão pontual | Consumo médio previsto para o ano `t` (previsão mensal, seção 3), sem limite |
| Otimizada | Minimiza `custo esperado + λ × CVaR95` sobre cenários de consumo e de PLD, com `V` **limitado a `[1/(1+f), 120%]` do consumo previsto** (só nesta estratégia; ≈ 91% a 120% com `f` = 10%). Caso base `λ = 0,5`; sensibilidade `λ = 0, 0,5, 1`. `CVaR95` = média do custo nos 5% piores cenários |

- Backtest de 2021 a 2025, com PLD real. **2021–2023 são contrafactuais** (seção 1).
- Em cada ano, a decisão usa só informação disponível antes do início do ano (sem olhar o futuro).
- O mesmo preço `P_t` vale para as três estratégias em cada ano.
- Regimes de preço muito diferentes: 2021 (crise hídrica), 2022–2024 (PLD no valor mínimo na
  maior parte das horas) e 2025 (preços altos). Ver `fontes.md`.

### Relatório do backtest (definido antes de ver os resultados)

Por estratégia e por ano:
1. **Custo total** (R$) e economia em R$ e % contra a estratégia ingênua.
2. **Pior ano**: o ano de menor economia (ou maior prejuízo) em relação à ingênua.
3. **CVaR95 do custo** sob os cenários usados na decisão (ex-ante), ao lado do custo realizado.
   **[pendente, Sprint 6]** confirmar a definição.
4. **Exposição ao PLD (MWh)**: energia comprada acima da faixa e energia vendida abaixo da
   faixa, separadas.
5. Anos em que o consumo real superaria `V × (1 + f)` (cobertura abaixo de 100%, risco residual da seção 4) e, se a penalidade for modelada (extra), o custo dela.

**O resultado será reportado mesmo que a economia seja pequena ou negativa.** Os números serão
lidos **ano a ano**, nunca só pela média, porque a média esconde que o resultado depende do
regime de preço de cada ano.

---

## 6. Limitações conhecidas

- A curva de consumo é sintética: valida o método, não um cliente real. Tem a forma semanal e o
  nível diário da carga do SE/CO, que cai nos fins de semana por causa da indústria.
- O contrato é simplificado (sem sazonalização contratual, encargos, impostos, tarifas de uso
  da rede ou custos de representação da varejista). Esses custos fora do modelo são iguais
  entre as estratégias, então afetam pouco a comparação **entre** elas.
- **Modulação perfeita:** supõe-se que o volume entregue acompanha o consumo hora a hora. Na
  prática a modulação é declarada com antecedência, e o descasamento horário viraria exposição
  ao PLD.
- O preço do contrato é uma regra (PLD do ano anterior mais spread), não um dado de mercado.
- A temperatura do submercado é uma média ponderada entre 7 estados. Ela suaviza ondas de calor
  locais e não representa a loja.
- O backtest de 2021–2023 é contrafactual (elegibilidade para o mercado livre).
- A penalidade por insuficiência de lastro não está no custo. O limite inferior de `V` evita a
  cobertura sistemática abaixo de 100%, mas um consumo real acima do previsto ainda poderia
  gerar penalidade não capturada (seção 4).

---

## Pendências

1. Fonte para o consumo médio de um supermercado médio (seção 1).
2. Fonte para a participação da refrigeração, 40% (seção 2).
3. Limites de carga para migrar ao mercado livre em 2021–2023 (seção 1).
4. Pesos por estado no consumo do SE/CO: fonte, ano de referência, fixos ou variáveis (seção 3).
5. ~~Perfil do arquivo PLD 2001–2020~~ (resolvido na tarefa 1.10: PLD 2020 do SUDESTE =
   R$ 178,03/MWh; ver `fontes.md`).
6. ~~Degrau de 2023 na carga do ONS: é mudança de definição, a decidir o tratamento.~~ (resolvido
   na Sprint 4, Parte B: o consumo segue a carga **bruta**; a série ajustada soma o tipo III
   e a MMGD medidos pela API de Carga Verificada, com a original preservada, e as quebras do
   dado são 01/03/2021 e 01/05/2023, e não 29/04; ver `decisoes.md` e `metricas.md`). Resta
   verificar com o ONS se há uma segunda fase da MMGD depois de mai/2023 (`fontes.md`).
7. ~~Tratamento dos outliers 2001–2002 e 2020 no treino da previsão mensal~~ (resolvido na Sprint 5,
   Parte A: janela móvel de 72 meses deixa 2001–2002 fora; 2020 tem os meses sinalizados pela regra
   de 2σ imputados, abr e mai/2020; o indicador abr–dez foi descartado; `decisoes.md`).
8. Lastro: fórmula da penalidade, janela, tolerância e VR 2021–2025. Só necessários se a
   penalidade for modelada (extra); o limite inferior de `V` já está decidido (seção 4).
9. Fuso do ONS (dicionário de dados; `fontes.md`).
10. Piso e teto do PLD por ano, na ANEEL: **valores encontrados e em uso** (seed `pld_limites`, teto horário); **[pendente]** só a conferência no texto oficial das resoluções e despachos de 2021 a 2026 (`fontes.md`). Em 08/10/2026: o teto horário não entra no modelo mensal (vale o estrutural); o piso de 2021–2026 foi confirmado nos dados pelo detector de repetição (`ml/piso_pld.py`), inclusive 2023.
11. Unidade do consumo por ramo da CCEE (`fontes.md`).
12. Número e método de geração dos cenários de PLD e de consumo (Sprint 5). **Consumo (5.6): feito** (vetores completos por origem, calibração crescente, independência do PLD como premissa, `decisoes.md`); **PLD (5.7): feito no código** (bootstrap simples e em blocos de 12 meses, piso por detector, transformação `PLD − piso_orig + piso_alvo`); N = 2.000; as tabelas esperam a execução do usuário (`decisoes.md`).
13. ~~Definição final do CVaR ex-ante no relatório do backtest~~ (resolvido na Sprint 6, Parte A: CVaR95 do custo de cada estratégia sobre os mesmos 2.000 cenários da decisão, ao lado do custo realizado e do PIT do realizado; `docs/planejamento/plano_sprint6a.md`, D7).
14. ~~Recalcular as estações do INMET com os anos 2021 a 2025~~ (resolvido: 37 estações; a
    lista caiu de 72 para 37; ver `fontes.md` e `decisoes.md`).
15. Estações do INMET que degradaram em 2026 (10 das 37 abaixo de 95% de horas válidas, 5 abaixo
    de 90%, em especial Silvânia-GO e Três Lagoas-MS): decidir na Sprint 2/3 como tratar nas
    análises que usarem 2026 e se vale um teste de completude mensal por estação (`fontes.md`).
16. ~~Tipo III antes de 2018~~ (resolvido na Sprint 5, Parte A: reconstruído em 2015–2017 com o vão
    Carga Mensal − curva, status `reconstruido_carga_mensal`, erro absoluto médio de 0,14% da curva em
    2018 no SE/CO; antes de 2015 não se reconstrói e a janela de 72 meses nunca passa de 2015-01;
    `decisoes.md`).
17. Out/2021 no SE/CO: a carga líquida da API fica ~972 MWmed (2,4%) acima da curva no mês
    inteiro, sem causa conhecida. Verificar com o ONS antes de usar o mês como alvo (`fontes.md`).
    Sprint 5: o modelo erra o mês em +8,3% (ingênuo +9,4%) e esse mês sozinho leva o MAPE de 2021 de
    0,95% para 1,89%; a anomalia de 2,4% explica só parte. Segue pendente (`metricas.md`).
