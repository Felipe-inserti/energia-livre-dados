# Plano da Sprint 6, Parte A (6.1 modelo de custo, 6.2 otimização, 6.3 backtest)

Branch `sprint6/parte-a-custo-backtest`. **Pré-registro:** este plano só vale como pré-registro com o commit que o contém feito **antes** da execução do backtest (6.3). Código da 6.1 (`ml/custo.py`) e da 6.2 (`ml/otimizacao.py`) e testes prontos; o dado realizado ainda não foi lido.
Referências: `premissas.md` (P), `decisoes.md` (D), `metricas.md` (M), sprints (S).

## 0. Insumos que já existem (conferidos na leitura)

| Insumo | Onde | O que traz |
|---|---|---|
| Cenários de consumo | `marts.fct_cenario_consumo` | por (execucao_id, origem, cenario, horizonte): `consumo_mwh` do supermercado (k × carga × horas). 144.000 linhas = 6 origens × 2.000 × 12 |
| Cenários de PLD | `marts.fct_cenario_pld` | por (execucao_id, origem, **metodo**, cenario, horizonte): `pld_rs_mwh`. 288.000 linhas (simples e blocos) |
| Execução | `marts.fct_cenario_execucao` | N, semente, `k`, hashes dos erros, do PLD e dos pisos, commit. **`execucao_id` = `51cf99b073fe`** (M 1315) |
| PLD realizado | `marts.fct_pld_ponderado_mensal` | PLDp mensal (`pld_ponderado_rs_mwh`), PLD simples (`pld_medio_simples_rs_mwh`), `horas`, `consumo_mwh`, `mes_completo`; 2021-01 em diante |
| Consumo realizado | `marts.fct_consumo_horario` | curva horária de 2020-01 em diante (o 2020 serve ao ingênuo de 2021) |
| Previsão pontual | `marts.fct_erro_previsao_carga` | `previsto_mwmed` por (origem, horizonte), modelo `comb_ets_sarima_regressao_v1` |
| Piso e preço de 2020 | `marts.fct_pld_semanal` | R$ 178,03/MWh (P 205–209) |

Origens de decisão: dez/2020 a dez/2024 (decidem 2021 a 2025). A origem de produção (2026-09) **não entra** aqui (é da 6.5).

**Convenção de informação (vale para tudo, herdada da 5.6/5.7):** na origem `t` (dezembro do ano `t−1`) o mês `t` já é conhecido (mês `<= origem`). Logo o ano `t−1` inteiro é conhecido: consumo, PLD e erros com mês-alvo `<= origem`.

---

## 1. Tarefa 6.1: modelo de custo

### 1.1 Fórmula mensal (P 211–234)

Para o mês `m` do ano decidido, com `f` = banda (0,10) e `V` em MWm:

| Símbolo | Definição | Linha de P |
|---|---|---|
| `C_m` | consumo do mês (MWh) | 214 |
| `V_m = V × horas_m` | energia contratada (MWh); contrato **plano em MWm** e modulado pela carga dentro do mês | 195, 215 |
| faixa | `[a, b] = [V_m(1−f), V_m(1+f)]`, apurada por mês | 198, 216 |
| `E_m = min(max(C_m, a), b)` | energia contratada entregue | 217–218 |
| `PLDp_m` | PLD do mês ponderado pelo consumo (R$/MWh) | 199, 219 |
| **`custo_m = E_m·P_t + (C_m − E_m)·PLDp_m`** | `C_m − E_m > 0` compra pelo PLD; `< 0` vende a sobra pelo PLD | 220–221 |
| custo anual | soma dos 12 meses | 234 |

Formas equivalentes úteis para teste: `custo_m = C_m·PLDp_m + E_m·(P_t − PLDp_m)`; e, se `P_t = PLDp_m`, `custo_m = C_m·P_t` **para qualquer V**.

Exposição (item 4 do relatório, P 299–300), por mês: **descoberto** = `max(C_m − b, 0)` (comprado acima da faixa) e **sobrando** = `max(a − C_m, 0)` (vendido abaixo da faixa). Dentro da faixa, as duas valem 0 e o custo não depende de `V` (P 236).

**Por que a otimização não é um problema convexo** (justifica a busca em grade, 1.3 de 6.2): `E_m(V)` tem inclinação `(1+f)`, depois 0, depois `(1−f)` à medida que `V` cresce, e o sinal de `(P_t − PLDp_m)` muda de cenário para cenário. Há patamares planos e quebras. Uma grade em uma variável é simples, robusta e defensável.

Implementação prevista: funções puras e vetorizadas em `ml/custo.py` (entrada em arrays `(N, 12)`; o mesmo código serve a um cenário, ao realizado e à grade).

### 1.2 Preço de contrato do caso base (P 197, 201–209; D "Preço do contrato")

`P_t = PLD médio simples das horas do SUDESTE no ano t−1 + R$ 20/MWh`. O mesmo `P_t` vale para as três estratégias.

- **Origem dos números.** 2021: R$ 178,03 (semanal 2001–2020, ponderado pelas horas, erro máximo R$ 4,84) + 20 = **R$ 198,03**. 2022 a 2025: `Σ(pld_medio_simples_mes × horas_mes) / Σ horas` do ano `t−1`, lido de `fct_pld_ponderado_mensal` (idêntico à média simples das horas, sem varrer o fato horário). Ordem de grandeza (M e D): 2021 ≈ 280,5; 2022 ≈ 59,0; 2024 ≈ 128; logo `P_2022 ≈ 300`, `P_2023 ≈ 79`, `P_2025 ≈ 148` (valores exatos saem da execução).
- **Só informação `<= t`?** Sim. Usa só o ano `t−1`, fechado na origem (dez/`t−1`). Teste: trocar o PLD de qualquer mês de `t` em diante por um valor absurdo não muda `P_t` (6.b).
- **Inconsistência a registrar (não a corrigir):** P usa a média **simples** (como está em P 201) e a liquidação usa o PLDp (ponderado). A diferença média é 1,6% ao mês (M 1136); fica nas limitações.
- Em `P_t`, o spread de R$ 20 é do caso base; 0 e 40 são da 6.4.

---

## 2. Tarefa 6.2: otimização

### 2.1 Problema (por origem `t`)

Escolher `V` (MWm) para minimizar

`J(V) = E[custo(V)] + λ · CVaR_α[custo(V)]`

sobre os **2.000 cenários conjuntos** da origem `t`:

- **Pareamento:** cenário `s` de consumo com cenário `s` de PLD (mesmo `cenario`, mesma origem, método `blocos`). Como consumo e PLD foram sorteados de forma independente (D, decisão 9; sementes distintas), o pareamento por índice é uma amostra conjunta válida de tamanho 2.000. O produto cartesiano (4 milhões) não acrescentaria informação (os mesmos 2.000 vetores e 2.000 blocos) e só encareceria. Verificação: `mes_alvo` igual nas duas tabelas e dentro do ano `t`.
- **CVaR de custo (perda):** média dos `(1−α)` piores (maiores) custos anuais. Reaproveita `cvar_superior` de `ml/cenarios_consumo.py` (exato com fração do último valor; com N = 2.000 e α = 0,95, são os 100 piores).
- **Custo anual do cenário** = soma dos 12 meses com `P_t` conhecido (não é cenário).

### 2.2 Variável e grade

`V = r × V_pont`, onde `V_pont` é o consumo médio **previsto** do ano `t` em MWm (`Σ k·prev_h·horas_h / Σ horas_h`, a mesma conta da estratégia pontual).

- **Limites do caso base, SIMÉTRICOS (decisão do usuário, ver D13):** `r ∈ [1/(1+f); 1/(1−f)]` = `[0,9091; 1,1111]` com `f = 0,10`. Nos dois extremos a borda da faixa encosta na previsão: em `r_min` a borda superior `V_m(1+f)` é igual ao previsto; em `r_max` a borda inferior `V_m(1−f)` é igual ao previsto. Assim a banda contratada **sempre contém a previsão** e a otimização não vira aposta no PLD. O limite inferior continua o da regra de lastro (P 251–264). **`r` até 1,20 (o limite antigo de P 264) fica só como sensibilidade da 6.4.** Casos extremos: `f = 0` dá `r ∈ [1; 1]` (a otimizada é igual à pontual por construção, o que é informação para a 6.4); `f = 0,05` dá `[0,9524; 1,0526]`.
- **Passo: 0,25% de `V_pont`** (~81 pontos com os limites simétricos; ~117 se `r` for até 1,2 na sensibilidade), mais os pontos `r = 1,0` e os dois limites incluídos explicitamente. Justificativa: os pontos de quebra do custo estão onde um cenário cruza a borda da faixa; com 117 pontos o erro de grade é muito menor que a incerteza dos cenários. Em MWm (consumo médio ~0,137), 0,25% ≈ 0,0003 MWm. O custo computacional é desprezível (5 origens × 117 × 2.000 × 12 ≈ 14 milhões de operações, menos de 1 s em numpy).
- **Desempate:** `J` é plano onde todos os cenários caem dentro da faixa. Regra: entre os `r` com `J` igual (tolerância de 1e-9 relativo), escolher o **mais próximo de 1,0** (a previsão pontual); persistindo o empate, o menor `r`. Assim "otimizada = pontual" quando a otimização não tem o que dizer, em vez de um canto arbitrário da grade.
- **Sem refinamento contínuo.** O ótimo da grade é o `V` da estratégia.

### 2.3 λ e α (proposta: manter P 284 e S 198)

| Parâmetro | Caso base | Por quê |
|---|---|---|
| α | **0,95** | já definido em P e nas sprints; é o CVaR padrão. **Limite honesto:** com 19 a 23 blocos de PLD, a cauda de 5% do PLD é praticamente **1 ano histórico** (o pior), e N não reduz esse erro (M 1196, 1288). α = 0,90 **entra como sensibilidade da 6.4** (decisão do usuário); o caso base continua α = 0,95 |
| λ | **0,5** | `J = E + 0,5·CVaR` equivale a 2/3 do valor esperado + 1/3 do CVaR. É um peso moderado: a otimização não ignora a cauda (λ = 0), nem a domina (λ = 1). Sensibilidade λ = 0, 0,5, 1 na 6.4 (P 284). Escolha de risco do projeto, não calibrada em resultado |
| N | **2.000** | decisão do usuário, 08/10/2026 (D 523) |
| método do PLD | **blocos de 12 meses** | o simples subestima a variância anual em ~9× (razão 0,11; M 1288); recomendação registrada em D 549. O simples roda depois, como o "antes" do método |

### 2.4 Saídas da 6.2 (ex-ante, sem dado realizado)

Por origem: `r*`, `V*` (MWm), `J`, `E[custo]`, `CVaR95` e a curva `J(r)` inteira (vira gráfico no dashboard). A 6.2 **não lê nenhum dado do ano decidido ou posterior**; é uma função de (cenários, `V_pont`, `P_t`, `f`, `λ`, `α`).

---

## 3. Tarefa 6.3: backtest 2021–2025

### 3.1 As três estratégias (P 282–284)

| Estratégia | `V` do ano `t` | Observação |
|---|---|---|
| Ingênua | consumo **realizado** médio do ano `t−1` em MWm (`Σ C / Σ horas`), sem limite | usa a mesma convenção de informação (ano `t−1` fechado em dez/`t−1`). Em 2021 usa 2020 (COVID); é o que a regra dá, e fica registrado |
| Previsão pontual | `V_pont` (`r = 1`), sem limite | média ETS+SARIMA+regressão, **independente do teste final** (D 442) |
| Otimizada | `r*` da 6.2 | só ela tem os limites simétricos `[1/(1+f); 1/(1−f)]` |

### 3.2 Avaliação (única parte que toca o realizado)

Para cada (ano, estratégia, mês), com `C_m` realizado (curva) e `PLDp_m` realizado (`fct_pld_ponderado_mensal`): `V_m`, `a`, `b`, `E_m`, `custo_m`, descoberto, sobrando. Agregados por ano e no total (soma dos 5 anos).

- Realizado: 60 meses completos (`mes_completo`). Checagem cruzada: o `consumo_mwh` da curva mensal (soma de `fct_consumo_horario` por mês local) bate com o `consumo_mwh` de `fct_pld_ponderado_mensal` em 1e-6.
- A economia é lida **ano a ano** (P 303–305). A média dos 5 anos nunca aparece sozinha.
- **Decomposição que ajuda a entender:** `ingênua → otimizada = (ingênua → pontual) + (pontual → otimizada)`. O primeiro termo é o valor da previsão; o segundo, o valor da otimização.

### 3.3 Hipóteses registradas ANTES de rodar (para não racionalizar depois; são palpites, não resultados)

- **H1.** A economia será **pequena** (décimos de %, não dezenas). Dentro da faixa o custo não depende de `V` (P 236), e o erro de previsão (1 a 4%) é bem menor que a banda de ±10%. As estratégias só diferem nos meses em que o consumo sai da faixa de alguma delas.
- **H2.** Onde `J(r)` é plano, a otimizada é igual à pontual (`r = 1` pelo desempate). Fora disso, `r*` tende aos extremos quando o PLD médio dos cenários fica longe de `P_t`.
- **H3 (risco que motivou os limites simétricos).** Com limite até 1,2, a otimizada viraria uma **aposta em `PLD(t)` contra `P_t`**: com `P_t` baixo e cenários de PLD altos (média ~190 a 208 nos blocos, M 1259–1263; cenários mais caros que o regime atual, D 550 e M 1271), ela iria a `r_max` em 2023–2025 só para vender sobra ao PLD "caro" do cenário. Os limites simétricos reduzem isso: com a previsão sempre dentro da banda, o que sobra de apostável é pouco. **Mesmo assim `r*` ainda pode ir ao extremo** nos anos em que `P_t` está longe da média dos cenários (2022: `P_t ≈ 300` contra ~195 tende a `r_min`; 2023 a 2025 tendem a `r_max`), e a subcobertura do regime de piso (10 a 15% dos meses no piso nos cenários contra 58 a 67% em 2022–2023) pesa nesses anos. O relatório explica e não esconde.
- **H4 (expectativa da análise principal da 6.4, banda `f ∈ {0%, 5%, 10%, 15%}`).** A pergunta é **quanto valem a previsão e a otimização em função da flexibilidade contratada**. Registro antes de rodar: (i) **com f = 10% a economia é pequena** (décimos de %), porque o erro de previsão cabe na banda; (ii) o valor da **previsão** (ingênua → pontual) e o da **otimização** (pontual → otimizada) **crescem quando f diminui**, porque uma banda estreita faz mais meses saírem da faixa; (iii) com **f = 0 a otimizada é igual à pontual por construção** (`r ∈ [1; 1]`), então o valor da otimização ali é zero e o da previsão é o maior; (iv) com f = 5% os limites ficam em `[0,952; 1,053]` e com f = 15% em `[0,870; 1,176]`; a otimização pode valer algo, mais com f maior (mais espaço para `r`), mas a banda larga também esconde o erro de previsão, então a leitura é pelo par (previsão, otimização) e não por um só. São palpites registrados, não resultados, e a leitura é ano a ano.

---

## 4. Critérios CONGELADOS antes de rodar

Tudo abaixo é fixado **antes** de qualquer leitura do dado realizado de 2021–2025 e registrado no `decisoes.md`.

| # | Critério | Valor |
|---|---|---|
| 1 | Cenários | `execucao_id = 51cf99b073fe`; N = 2.000; semente-base 0; calibração crescente; `k = 3,2752385e-6`. O código confere os hashes por origem (`erros_hash`, `pld_hash`, `pisos_hash` de `fct_cenario_execucao`) e **recusa** outro id |
| 2 | Método do PLD | `blocos` (caso base); `simples` só como "antes" depois |
| 3 | Pareamento e independência | índice do cenário; consumo e PLD independentes (decisão 9) |
| 4 | Objetivo | `J = E + λ·CVaR_α`; **λ = 0,5; α = 0,95**; CVaR exato da cauda superior do custo |
| 5 | Grade | **`r ∈ [1/(1+f); 1/(1−f)]` (simétrica)**, passo 0,25%, com `r = 1` e os limites; desempate pelo mais próximo de 1. `r` até 1,2 só na sensibilidade |
| 6 | Contrato | **`f = ±10%` no caso base (não muda)**; contrato plano em MWm, modulado dentro do mês; liquidação pelo PLDp |
| 7 | Preço | `P_t` = PLD médio simples das horas do ano `t−1` + **R$ 20**; 2021 = 198,03 |
| 8 | Estratégias | ingênua = média do consumo realizado do ano `t−1`; pontual = `V_pont` (`r = 1`); otimizada = `r*` |
| 9 | Informação | origem em dez/`t−1`; meses `<= origem` conhecidos |
| 10 | Realizado | `fct_consumo_horario` e `fct_pld_ponderado_mensal`, com impressão digital (hash) da série gravada na saída |
| 11 | Relatório | exatamente o de P 292–305 (custo, economia R$ e %, pior ano, CVaR ex-ante, exposição, anos com cobertura abaixo de 100%) |
| 12 | Modelo de previsão | `comb_ets_sarima_regressao_v1`, sem nova seleção |
| 13 | Ingênua de 2021 | consumo de 2020 (COVID), mantida (D12). **Visão secundária fixada agora:** totais **com e sem 2021** (sem 2021: 2022–2025), lado a lado; o caso base continua sendo os 5 anos |
| 14 | Sensibilidades pré-declaradas (6.4) | **análise principal: banda `f ∈ {0%, 5%, 10%, 15%}`**, com expectativa H4 registrada antes. Demais: spread 0 e 40; λ 0 e 1; **α = 0,90**; `r` até 1,2; PLD `simples`; dispersão dos erros ×1,25 e ×1,5 (regera cenários). **Regra: o que não está nesta lista está fora; nada é "opcional".** `f = 15%` (planejamento anterior) |

**CVaR ex-ante no relatório (fecha a pendência 13, P 351):** para cada ano e **cada** estratégia, o CVaR95 do custo sobre os mesmos 2.000 cenários da decisão (com o `V` da estratégia, `P_t` e `f`), ao lado do custo realizado e de **onde o realizado cai na distribuição dos cenários (PIT)**. Comparável entre as três estratégias e entre o ex-ante e o realizado.

**Cobertura abaixo de 100% (P 301):** ano em que `Σ C_m > (1+f)·Σ V_m` (consumo anual acima do teto da faixa). Também conto os **meses** acima da faixa.

### Compromisso de rodar o caso base UMA vez

1. Antes da execução real, o código passa nos testes (seção 6) e **você commita código + este plano + o `decisoes.md`**; a execução grava o `commit` na saída (como `ml/cenarios.py`).
2. O subcomando do caso base **recusa** rodar de novo se já existe resultado para a mesma impressão digital da configuração (os 12 critérios acima), a não ser com uma flag explícita que fica registrada num log append-only (`data/logs/backtest_execucoes.jsonl`).
3. Dentro do que pode ser repetido sem violar o compromisso: a 6.2 (ex-ante), testes com dados sintéticos e a leitura em modo `--dry-run`. **Não** repito a avaliação 6.3 depois de ver o resultado para ajustar parâmetro.
4. Se um bug for achado **depois** de ver o realizado, a correção é uma nova versão (`v2`) com a anterior preservada e a história contada, nunca uma substituição silenciosa.
5. Sensibilidades (critério 14) rodam **depois**, cada uma com a sua identidade, e nunca substituem o caso base. Para `f` diferente de 0,10 a otimização usa os mesmos cenários (eles não dependem de `f`); só a grade e o custo mudam.

---

## 5. Saídas do backtest

Para cada estratégia, ano a ano e no total 2021–2025:

1. Custo anual (R$) por estratégia.
2. Economia contra a ingênua em R$ e em % (da pontual e da otimizada; mais a decomposição de 3.2).
3. Pior ano (a menor economia ou o maior prejuízo) por estratégia.
4. Exposição ao PLD em MWh, **separada** em descobertos (comprados) e sobrando (vendidos), por ano e no total.
5. CVaR95 ex-ante ao lado do custo realizado e o PIT do realizado.
6. `r*` e `V*` por ano; anos com cobertura abaixo de 100%; meses fora da faixa.
7. Rótulo "contrafactual" em 2021–2023 (P 286); a leitura ano a ano, nunca só a média.
8. **Visão secundária (D12):** os totais de custo, economia e exposição **com 2021 (5 anos) e sem 2021 (2022–2025)**, porque a ingênua de 2021 parte do consumo de 2020 (COVID).

Cabeçalho obrigatório do relatório, com o mesmo destaque do resultado: 5 anos (não há teste de significância), contrafactual 2021–2023, `P_t` defasado, modulação perfeita, penalidade de lastro não modelada, cenários subestimam o regime de piso e a subcobertura dos intervalos de consumo (D 524–525).

---

## 6. Testes (pytest, antes de qualquer execução real)

**a) Custo à mão (6.1).** `f = 0,10`, `V = 0,15 MWm`, mês de 30 dias (720 h): `V_m = 108` MWh, faixa `[97,2; 118,8]`, `P = 200`.

| Caso | C (MWh) | PLDp | E | Conta | Custo | Exposição |
|---|---|---|---|---|---|---|
| acima | 120 | 300 | 118,8 | 118,8·200 + 1,2·300 | **24.120** | descoberto 1,2 |
| abaixo | 90 | 50 | 97,2 | 97,2·200 + (−7,2)·50 | **19.080** | sobrando 7,2 |
| dentro | 100 | 123 | 100 | 100·200 | **20.000** | 0 |

Anual dos 3 meses = **63.200**. Mais: C exatamente na borda (sem exposição); `f = 0` (`E = V_m`); `V = 0`; propriedade `P = PLDp ⇒ custo = C·P` para qualquer `V`; homogeneidade (dobrar `C` e `V` dobra o custo e mantém o %); identidade `custo = C·PLDp + E·(P − PLDp)`; `Σ(C − E) = descoberto − sobrando`.

**b) Sem vazamento.**
- Alterar o PLD de qualquer mês `>= t` (por 1e6) não muda `P_t`, nem `V*`, nem a decisão da ingênua (e vice-versa para o consumo realizado de `t` em diante).
- **Truncamento de ponta a ponta:** decidir a origem `o` com os dados realizados truncados em `<= o` dá o **mesmo** `V` das três estratégias que com os dados completos.
- A 6.2 só lê linhas com `origem == o` (alterar as outras origens não muda `r*`); `mes_alvo` dos cenários cai no ano `t`; o `execucao_id` e os hashes conferem.
- A ingênua usa só o ano `t−1`; a pontual só `previsto` da origem.

**c) Otimizada nunca pior.** O enunciado precisa de uma correção importante: com λ > 0 a otimizada minimiza `J`, **não** o `E[custo]`; logo o `E[custo]` dela pode ser maior que o da pontual. O teste correto é:
- `J(otimizada) <= J(pontual)` sempre (a grade contém `r = 1`), e `<= J(ingênua)` quando o `V` da ingênua cabe nos limites; fora dos limites, comparar contra a ingênua **limitada** aos limites (e relatar que ela estava fora).
- Com **λ = 0**, `E[custo](otimizada) <= E[custo]` das outras (nas mesmas condições).
- Força bruta: o `r*` entrega o menor `J` da grade, e o desempate escolhe o mais próximo de 1.
- Casos sintéticos de resposta conhecida: **cenários com consumo simétrico em torno da previsão** (metade em 0,8·V_pont, metade em 1,2·V_pont, nas 12 posições): PLD > `P` → `r = 1/(1−f)`; PLD < `P` → `r = 1/(1+f)` (em ambos, `E` cresce com `r` nos cenários fora da faixa). **Correção do plano anterior:** com `C = V_pont` em todos os cenários o `J` é **plano** (a previsão está dentro da faixa em todo `r` da grade), e o resultado é `r = 1` pelo desempate, não um extremo. Esse é o teste de desempate; outro: `C = 0,85·V_pont`, PLD < `P` → plano em `r ≤ 0,944` e o desempate escolhe o ponto da grade mais próximo de 1 dentro do plano (não o menor `r`). Mais: com `f = 0` a grade tem um ponto só (`r = 1`); os limites são simétricos e a faixa contratada contém a previsão em todo `r` da grade (`V_m(1−f) <= previsto <= V_m(1+f)`).
- CVaR de vetor conhecido e `CVaR >= média`.

**d) Determinismo.** Mesma entrada → saída idêntica bit a bit (hash do resultado); **embaralhar as linhas** da tabela de cenários (o BigQuery não garante ordem) não muda nada; reexecutar o caso base com o mesmo `execucao_id` dá o mesmo resultado. Como os cenários já vêm de semente fixa (`SEMENTE_BASE = 0`, derivada por origem), a 6.2 não sorteia nada.

**e) Guardas.** Recusa de `execucao_id` diferente; recusa da segunda execução do caso base; falha se faltar mês realizado (60 meses completos) ou se a soma mensal da curva divergir do `fct_pld_ponderado_mensal`.

Arquivos previstos: `ml/custo.py`, `ml/otimizacao.py`, `ml/backtest.py`, `tests/test_ml_custo.py`, `tests/test_ml_otimizacao.py`, `tests/test_ml_backtest.py`. A suíte atual (593 testes) segue passando.

---

## 7. Onde gravar e custo em bytes

**Gravação (proposta):**
- `docs/resultados/backtest_caso_base.csv` (+ `.meta.json` com a configuração, hashes e commit): versionado, 180 linhas (3 estratégias × 60 meses), **0 bytes** de BigQuery; é o que o relatório e o `metricas.md` leem.
- `marts.fct_backtest_mensal` (grão: id da execução, ano, estratégia, mês) e `marts.fct_backtest_decisao` (grão: id, ano, estratégia; `r`, `V`, `J`, `E`, CVaR ex-ante, PIT). A curva `J(r)` vai numa terceira pequena (`fct_otimizacao_grade`, ~585 linhas) se o dashboard a usar. Mesmo padrão de `ml/cenarios.py` (MERGE idempotente com chave natural e proveniência: commit, hash do código, hashes dos insumos).
- A `fct_recomendacao_contrato` (6.5) é construída **a partir** dessas, na 6.5.

**Bytes (estimativa por tabela; a confirmar por `--dry-run`, teto de 200 MiB por consulta como no resto do projeto):**

| Leitura | Estimativa processada | Faturado (piso 10 MiB por tabela) |
|---|---|---|
| `fct_cenario_consumo` (5 colunas, filtro por id e origem; sem partição lê tudo) | ~6,6 MB | ~10 MiB |
| `fct_cenario_pld` (6 colunas) | ~15,6 MB | ~15 a 16 MiB |
| `fct_pld_ponderado_mensal`, `fct_consumo_horario`, `fct_erro_previsao_carga`, `fct_cenario_execucao` | <2 MB cada | 10 MiB cada |
| **Leitura completa** | ~25 MB | **~65 MiB (estimativa)**, 0,006% de 1 TiB |
| Gravação das tabelas pequenas (MERGE lê temporária e destino) | bytes desprezíveis | ~20 MiB por tabela (o piso, como em M 1335): ~40 a 60 MiB |

A leitura é feita **uma vez** e guardada em disco local (fora do git); o resto roda de graça e rápido. Meço de verdade na execução (processados e faturados por consulta) e registro no `metricas.md`, com tempo e memória, como na Parte B.

---

## 8. Decisões para o `decisoes.md` (opções e recomendação)

| # | Decisão | Opções | Recomendação |
|---|---|---|---|
| D1 | Método do PLD do caso base | (a) blocos; (b) simples | **(a)**. O simples subestima a variância em ~9× e o CVaR seria artificialmente baixo; o simples vira o "antes" depois |
| D2 | Pareamento consumo × PLD | (a) por índice (2.000 pares); (b) produto cartesiano; (c) sortear de novo | **(a)**. Independência já aceita (decisão 9); (b) não acrescenta informação |
| D3 | Preço do contrato | (a) média simples das horas do ano `t−1` + 20 (P 201); (b) PLDp (ponderado) do ano `t−1` | **(a)**, o definido; registra a inconsistência com a liquidação (1,6% ao mês) como limitação |
| D4 | Método de otimização | (a) grade em `r`; (b) programação linear de Rockafellar-Uryasev | **(a)**: uma variável, custo não convexo, é o pedido da sprint e é fácil de explicar |
| D5 | Grade e desempate | passo 0,25% ou 0,5% ou 1%; desempate pelo mais próximo de 1, menor `V` ou maior `V` | **0,25%** e **mais próximo de 1** (aprovado) |
| D6 | λ e α | λ ∈ {0; 0,5; 1}; α ∈ {0,90; 0,95} | **λ = 0,5; α = 0,95** no caso base; **α = 0,90 é sensibilidade da 6.4** (aprovado). Registrar o limite de cauda do PLD (≈ 1 ano) |
| D7 | Definição do CVaR ex-ante (pendência 13) | (a) CVaR95 do custo nos cenários da decisão, para as 3 estratégias, com PIT do realizado; (b) só da otimizada | **(a)**: é comparável entre estratégias |
| D8 | Cobertura abaixo de 100% | (a) anual `Σ C > (1+f)·Σ V_m`; (b) mensal; (c) as duas | **(c)**, reportando as duas, e dizendo que a penalidade não é modelada |
| D9 | Teste "otimizada nunca pior" | (a) no `E[custo]`; (b) no `J`, e no `E` só com λ = 0 | **(b)**, porque com λ > 0 a otimizada não minimiza o `E` |
| D10 | Compromisso de rodada única | (a) só disciplina; (b) disciplina + trava no código + commit antes + log | **(b)** |
| D11 | Onde gravar | (a) só CSV; (b) só BigQuery; (c) CSV versionado + tabelas | **(c)** |
| D12 | Ingênua de 2021 com o consumo de 2020 (ano de COVID) | (a) seguir a regra; (b) outra base | **(a)** (aprovado); registrar que isso a sub-contrata e favorece as outras, **com a visão secundária de totais com e sem 2021 desde já** |
| D13 | Limites de `r` do caso base (decisão do usuário) | (a) `[1/(1+f); 1,20]` (P 264); (b) simétricos `[1/(1+f); 1/(1−f)]` | **(b)**: a banda contratada sempre contém a previsão; sem isso a otimização especula sobre o PLD, e os cenários de PLD são mais caros que o regime atual (risco da 5B, D 550 e M 1271). `r` até 1,2 vira sensibilidade |
| D14 | Análise principal da 6.4 (decisão do usuário) | (a) spread, λ e banda com o mesmo peso; (b) a banda `f ∈ {0%, 5%, 10%, 15%}` como principal | **(b)**, com a pergunta "quanto valem a previsão e a otimização em função da flexibilidade contratada" e a expectativa H4 registrada antes de rodar. Caso base `f = 10%` não muda |

Atualizações de documentos ao fim da tarefa (você commita): `metricas.md` (tabela do backtest, linha "Negócio" do topo e os bytes de leitura e gravação), `decisoes.md` (D1 a D12 e a lista congelada), `premissas.md` (pendência 13 resolvida; a definição de exposição e de cobertura), marcar 6.1 a 6.3 em `sprints-projeto-energia.md`.

## 9. O que medir (métricas, CLAUDE.md)

- **Negócio:** custo anual por estratégia, economia em R$ e %, exposição (descobertos e sobrando) em MWh.
- **Engenharia:** bytes processados e faturados por consulta e por gravação; tempo e memória da 6.2 e da 6.3.
- **Ciência:** estabilidade do `r*` quando muda a semente dos cenários (diagnóstico **ex-ante**, sem dado realizado, definido antes: se `r*` mudar mais de um passo da grade ao trocar a semente, a grade e o N são insuficientes e isso é registrado, **sem** mudar o caso base).

## 10. Aprovações do usuário (decididas antes de rodar o backtest)

D1, D5, D9, D10, D11 e D12 aprovados; D13 (limites simétricos) e D14 (banda como análise principal da 6.4) decididos pelo usuário; α = 0,90 entra como sensibilidade da 6.4. Ordem de trabalho: `ml/custo.py` e os testes da 6.1; depois 6.2 e 6.3, cada uma com o seu aviso.
