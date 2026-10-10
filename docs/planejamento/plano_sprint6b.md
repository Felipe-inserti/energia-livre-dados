# Plano da Sprint 6, Parte B (6.4 sensibilidades, 6.5 `fct_recomendacao_contrato`)

Branch `sprint6/parte-b-sensibilidades`. **Pré-registro:** este plano só vale como pré-registro com o commit que o contém, **enviado ao GitHub antes de qualquer execução** (seção 4). Nenhum código novo foi escrito; nenhuma sensibilidade foi calculada, nem em parte.
Referências: `plano_sprint6a.md` (A), `decisoes.md` (D), `metricas.md` (M), `premissas.md` (P), sprints (S).

**Aviso de leitura (honestidade do pré-registro).** O caso base **já foi visto** (A, resultado em D e M). As expectativas da seção 3 são, portanto, **condicionais ao caso base visto**: elas usam o mecanismo do custo e os números do caso base já publicados (V, `P_t`, `r*`, exposição), não o realizado recalculado sob cada sensibilidade. Eu **não recalculei** nenhuma sensibilidade com o realizado para escrevê-las (o `backtest_caso_base_mensal.csv` permitiria recalcular spread e banda das estratégias ingênua e pontual à mão; não foi feito). O pré-registro garante que as sensibilidades **não serão ajustadas depois do resultado**; não garante que as expectativas sejam cegas.

---

## 1. Lista fechada de execuções

Fonte exclusiva: a lista da 6.4 (S 200; critério congelado 14 de A, com o clip reconciliado em D, "omissão de transcrição no item 14"). **Uma variável por vez** em relação ao caso base (f = 10%, λ = 0,5, α = 0,95, `r ∈ [1/(1+f); 1/(1−f)]`, PLD em blocos com deslocamento do piso, spread R$ 20, dispersão ×1, N = 2.000). **Sem combinações.**

| # | `sens_id` | Único parâmetro que muda | Valor (caso base) | Cenários |
|---|---|---|---|---|
| — | `caso_base` | (não roda de novo) | f = 0,10 | congelados `51cf99b073fe` |
| 1 | `f00` | banda f | 0 (0,10) | congelados `51cf99b073fe` |
| 2 | `f05` | banda f | 0,05 | congelados |
| 3 | `f15` | banda f | 0,15 | congelados |
| 4 | `spread00` | spread de `P_t` | R$ 0 (R$ 20) | congelados |
| 5 | `spread40` | spread de `P_t` | R$ 40 | congelados |
| 6 | `lam00` | λ | 0 (0,5) | congelados |
| 7 | `lam10` | λ | 1 (0,5) | congelados |
| 8 | `alfa90` | α do CVaR | 0,90 (0,95) | congelados |
| 9 | `rmax120` | limite superior de `r` | 1,20 (`1/(1−f)` = 1,1111) | congelados |
| 10 | `pldsimples` | método do bootstrap do PLD | `simples` (`blocos`) | congelados (o `execucao_id` já contém as linhas de método `simples`) |
| 11 | `disp125` | dispersão dos erros de consumo | ×1,25 (×1) | **novo `execucao_id`** |
| 12 | `disp150` | dispersão dos erros de consumo | ×1,5 (×1) | **novo `execucao_id`** |
| 13 | `clip` | transformação do histórico de PLD | clip simples (deslocamento do piso) | **novo `execucao_id`** |

**13 execuções, 10 sobre cenários congelados, 3 sobre cenários novos (3 `execucao_id` novos).** A linha `f = 10%` da análise principal é o **caso base lido dos arquivos já versionados**, não uma execução nova (o caso base nunca é sobrescrito nem repetido).

O registro legível por máquina (o código só aceita estes `sens_id`; um teste confere que o código e este bloco são iguais, seção 8):

```json
{"sensibilidades": [
 {"sens_id": "f00", "muda": {"f": 0.0}, "cenarios": "congelados"},
 {"sens_id": "f05", "muda": {"f": 0.05}, "cenarios": "congelados"},
 {"sens_id": "f15", "muda": {"f": 0.15}, "cenarios": "congelados"},
 {"sens_id": "spread00", "muda": {"spread": 0.0}, "cenarios": "congelados"},
 {"sens_id": "spread40", "muda": {"spread": 40.0}, "cenarios": "congelados"},
 {"sens_id": "lam00", "muda": {"lambda": 0.0}, "cenarios": "congelados"},
 {"sens_id": "lam10", "muda": {"lambda": 1.0}, "cenarios": "congelados"},
 {"sens_id": "alfa90", "muda": {"alfa": 0.9}, "cenarios": "congelados"},
 {"sens_id": "rmax120", "muda": {"r_max": 1.2}, "cenarios": "congelados"},
 {"sens_id": "pldsimples", "muda": {"metodo_pld": "simples"}, "cenarios": "congelados"},
 {"sens_id": "disp125", "muda": {"dispersao": 1.25}, "cenarios": "novos"},
 {"sens_id": "disp150", "muda": {"dispersao": 1.5}, "cenarios": "novos"},
 {"sens_id": "clip", "muda": {"transformacao_pld": "clip"}, "cenarios": "novos"}
]}
```

**Conferência da lista (o que falta, o que sobra):** nada falta e nada sobra em relação à 6.4. Observações, sem acrescentar:
1. `f = 10%` está na análise principal só como linha de comparação (o caso base).
2. `pldsimples` não exige cenários novos: as linhas `metodo = 'simples'` já estão na execução congelada (288.000 linhas = simples + blocos).
3. "Peso maior para anos recentes" **não entra** (D, "Pesos maiores…": não foi declarado antes de `02990fd`). Também fora: N, semente, sensibilidade do piso nas lacunas (já medida) e qualquer combinação (por exemplo, f = 5% com λ = 0).

---

## 2. Definições fixadas antes de rodar

### 2.1 Dispersão ×k (`disp125`, `disp150`)

Opções: (a) multiplicar o `log_razao` inteiro por k; (b) multiplicar só o desvio em torno da média de cada horizonte.

**Escolho (b).** Definição: na origem `t`, com o conjunto `V_t` dos vetores de 12 erros **conhecidos** (alvo `<= t`, a mesma calibração crescente do caso base, `vetores_completos_ate`), seja `m_h` a média de `log_razao` do horizonte `h` sobre `V_t`. Cada vetor sorteado vira

`e'_h = m_h + k · (e_h − m_h)`, e a carga do cenário é `previsto_h · exp(e'_h)`.

Por quê:
- **(a) também escala o viés.** Os erros têm viés (o modelo subestimou o nível em 2023, por exemplo; D "Salto do V_pont"). Multiplicar o `log_razao` por 1,5 aumentaria o viés em 50% junto com a dispersão, e o resultado misturaria "mais incerteza" com "mais erro sistemático". A sensibilidade perguntada é a da **dispersão**: D (linha 526) a define como "escala dos erros em torno do centro, **sem mudar a média**". (b) é a leitura literal disso.
- **Centro por horizonte, não por vetor.** "Centro do vetor" poderia ser a média dos 12 valores do próprio vetor; isso retiraria o **nível anual** de cada vetor (o erro que o ano inteiro compartilha), que é justamente o que gera o risco do custo anual. Centrar pela média do horizonte entre os vetores conhecidos preserva a correlação entre meses dentro do vetor (o mesmo fator `k` vale para os 12 horizontes) e só estica a distribuição.
- **Sem vazamento.** `m_h` usa só erros conhecidos na origem.
- **Mesmos sorteios.** Os índices de vetor sorteados são os do caso base (mesma semente por origem, mesma sequência): cada cenário é o do caso base **esticado**; só a dispersão difere (comparação pareada).
- **Efeito de Jensen:** `exp` é convexa, então a média da carga sobe um pouco com `k` (da ordem de `σ²/2`, com σ anual ~3%: menos de 0,1%). Será **medido e reportado** (média do consumo anual dos cenários contra o caso base); não é corrigido.
- Com `k = 1` o resultado é **idêntico** ao caso base (teste, seção 8).

### 2.2 `r` até 1,2 (`rmax120`)

**Sim, o limite inferior continua `1/(1+f)`** (= 0,9091 com f = 10%): `limites_de_r(f, r_max)` só troca o teto. A grade fica `[0,9091; 1,20]`, passo 0,25%, com `r = 1` e os dois limites, desempate pelo `r` mais próximo de 1 (~117 pontos, A 2.2). Só a **otimizada** muda; ingênua e pontual não têm limite de `r`, então seus custos são iguais aos do caso base.

### 2.3 Spread (`spread00`, `spread40`)

**Sim: muda o `P_t` das três estratégias igualmente.** `P_t = PLD médio simples do ano t−1 + spread`; o código calcula `P_t` uma vez por origem (`decidir`) e a avaliação usa o mesmo `d.preco` nas três. O spread também entra na decisão da otimizada (`P_t` contra `E[PLD]`). 2021 usa `178,03 + spread`.

### 2.4 f = 0 (`f00`)

**Confirmado: a otimizada coincide com a pontual por construção.** `limites_de_r(0)` = `[1; 1]`; `grade_de_r` devolve um ponto só (`r = 1`); `V* = 1·V_pont` exatamente. O custo realizado, as exposições e as colunas ex-ante da otimizada são **iguais** às da pontual (bit a bit, mesmo `V`), e o valor da otimização é **0 por construção**. Com f = 0 o contrato é fixo em MWm (`E_m = V_m`) e todo desvio é liquidado ao PLD.

### 2.5 Clip simples (`clip`)

**Confirmado.** A única diferença em relação ao caso base é a transformação do histórico:

| | Caso base | `clip` |
|---|---|---|
| PLD no ano-alvo | `min(max(PLD_orig − piso(ano orig) + piso(ano alvo), piso_alvo), teto_est_alvo)` | `min(max(PLD_orig, piso_alvo), teto_est_alvo)` |

Sem deslocamento do piso: só o corte do PLD **nominal** em `[piso, teto estrutural]` do ano-alvo (a seed `pld_limites`, a mesma do caso base; na origem de dezembro os limites do ano-alvo já são conhecidos). **Tudo o mais é igual:** histórico 2002 até a origem, blocos de 12 meses que começam no mesmo mês do calendário, semente por origem, N = 2.000, método `blocos` (o `simples` também é regerado, mas só o `blocos` é avaliado), consumo, `k`. Os meses históricos sorteados são os **mesmos** do caso base (mesma semente, mesmo histórico): comparação pareada. Os pisos interpolados (`pisos`) deixam de ser usados nessa transformação; entram só no `pisos_hash` por compatibilidade, e o `execucao_id` ganha o campo `transformacao = clip` (seção 6.1) para não colidir com o caso base.

---

## 3. Expectativas por sensibilidade (pré-registro da Parte B)

Escritas antes de rodar, **condicionais ao caso base visto** (aviso no topo). Valor da **previsão** = ingênua − pontual; valor da **otimização** = pontual − otimizada; ambos em R$ de custo evitado e % do custo da ingênua; lidos ano a ano. Leitura estrutural que organiza tudo:

- **Em qual sensibilidade cada coluna pode mudar.** `λ, α, r_max, método do PLD, dispersão e clip` **não mudam** `V` nem `P_t` nem `f` da ingênua e da pontual: o **custo realizado** delas é **idêntico** ao do caso base, e o **valor da previsão** também (em R$ e em %). Só a otimizada muda, e **só nos anos em que o `r*` muda**: onde o `r*` é o mesmo do caso base, a otimizada é a mesma e o valor da otimização é o mesmo. Esta é uma previsão **falsificável** (teste de invariância, seção 8). Apenas **f** e **spread** mudam o custo das três estratégias.
- **`r*` do caso base (D):** 2021 interior (0,9841), 2022 `r_min`, 2023–2025 `r_max`. O sentido do limite acompanha o sinal de `E[PLD] − P_t` (o PLD médio dos cenários contra o preço do contrato), não a previsão de consumo.

| `sens_id` | Valor da previsão | Valor da otimização e `r*` | Como seria refutada |
|---|---|---|---|
| `f00` | **Em módulo, o maior da análise**, ordem de ~1% do custo por ano. **O sinal não é "previsão ajuda"**: com f = 0 o custo é `C·PLDp + V·h·(P_t − PLDp)`, então a diferença ingênua−pontual é `(V_ing − V_pont)·Σh(P_t − PLDp)`. No caso base a ingênua tem `V` menor que a pontual em **todos** os anos; logo o valor da previsão **segue o sinal de `P_t − PLDp` do ano**: **negativo em 2022** (`P_t` ≈ 300 contra PLDp ≈ 59: a pontual contrata mais, ao preço caro) e **positivo** nos anos de `PLDp > P_t` (2021, 2024, 2025 pelos números do caso base; 2023 incerto, `PLDp` próximo de `P_t`). Isso é **aposta no PLD**, não mérito da previsão. | **0 por construção**, `r* = 1` em todos os anos. | Qualquer valor da otimização ≠ 0 (é erro de código); sinal do valor da previsão em 2022 positivo. |
| `f05` | Em módulo **maior** que o caso base (mais meses fora da faixa da ingênua e da pontual); o **sinal por ano** segue o mesmo raciocínio de `P_t − PLDp` (a assimetria vem de a ingênua ter `V` menor). | `r*` nos limites `[0,952; 1,053]` nos anos em que o caso base estava no limite (o sinal de `E[PLD] − P_t` não depende de f). **Refinamento de H4 (iv):** em `r_max` a borda inferior da faixa é a previsão para **qualquer** f, então a sobra vendida `(V_pont,m − C_m)⁺` é a mesma em f = 5%, 10% e 15%; o valor da otimização em R$ **não deve crescer com f** nos anos de `r_max` enquanto o erro de previsão for menor que f; com f pequeno, soma-se o ganho dos meses em que `C > (1+f)·V_pont`. Espero valor da otimização de f = 5% **igual ou maior** que o de f = 10% nos anos de `r_max`, o contrário do que H4 (iv) sugeria. | Valor da otimização em f = 5% claramente menor que em 10% em 2023–2025. |
| `f15` | **Perto de zero** e com menos meses fora da faixa que o caso base (a banda larga absorve o erro de previsão). | `r*` nos limites `[0,870; 1,176]` onde o caso base estava no limite; valor da otimização **próximo do de f = 10%** nos anos de `r_max`/`r_min` (mesmo argumento). Pode aparecer **cobertura abaixo de 100%** em `r_min` (2022) com `r_min = 0,870`. | Valor da previsão em módulo maior que no caso base. |
| `spread00` | Da ordem do caso base (alterações de **dezenas de R$ por ano**: o `P_t` muda 20 R$/MWh vezes os poucos MWh em que ingênua e pontual diferem). A conclusão "previsão não vale nada em f = 10%" **não deve mudar**. | `P_t` menor em 20: 2023, 2024, 2025 seguem em `r_max` (com mais folga); 2022 segue em `r_min`; **2021 é o ano a observar** (`P_t − E[PLD]` cai de +18,9 para ≈ −1,1: o `r*` pode ir de interior a outro ponto). Valor da otimização: sobe em R$ nos anos de `r_max` (cada MWh de `ΔE` rende 20 R$ a mais) e **cai em 2022** (`r_min`). | `r*` de 2022 sai de `r_min`; valor da otimização de 2023–2025 cai. |
| `spread40` | Idem `spread00`. | O espelho: `P_t` maior em 20: 2022 segue em `r_min` (com mais ganho em R$ por MWh de `ΔE`), 2023–2025 seguem em `r_max`, com **menos** ganho por MWh; **2025** (`P_t − E[PLD]` de −34,4 para −14,4) é onde o `r*` pode sair do limite; 2021 tende a `r_min`. | `r*` de 2023 ou 2024 sai de `r_max`. |
| `lam00` | Igual ao caso base (mesma ingênua e pontual). | Otimizada minimiza só o `E[custo]`: solução de canto em quase todo ano (o `E` é linear por trechos em `V`). **2021 deixa de ser interior** (`r_min`, pois `P_t > E[PLD]`). 2022–2025 iguais ao caso base. No realizado, 2021 passa a ter valor da otimização **negativo e pequeno** (PLDp realizado de 2021 muito acima de `P_t`; contratar o mínimo compra mais caro). | `r*` de 2022–2025 muda; valor da otimização de 2021 positivo. |
| `lam10` | Igual ao caso base. | Mais peso na cauda. 2023, 2024 e 2025 (`P_t` abaixo de `E[PLD]` e abaixo da cauda): **mesmo `r_max`**, resultado igual ao caso base. **2021 e 2022** (onde o `E` e a cauda puxam em sentidos opostos) são os anos que podem mudar. | `r*` de 2023–2025 sai de `r_max`. |
| `alfa90` | Igual ao caso base. | Cauda menos extrema (200 piores, não 100); com 19 a 23 blocos de PLD a cauda de 5% já é ~1 ano histórico, então a mudança é pequena: **`r*` igual ao caso base em 4 dos 5 anos** (2022–2025), 2021 pode andar um passo da grade. CVaR ex-ante **menor** (mesmo `V`). | `r*` muda em dois ou mais anos. |
| `rmax120` | Igual ao caso base. | `r_min` não muda: **2021 e 2022 iguais** ao caso base. 2023–2025: `r* = 1,20` (o `J` cai enquanto houver sobra a vender acima de `P_t`), **a aposta H3 amplificada**: ganho maior em 2025 (PLDp ≈ 218 contra `P_t` 148, vender a sobra no PLD alto) e **perda maior** em 2023 e 2024 (a sobra cai em meses de PLD baixo). Resultado total mais disperso, de sinal incerto; **cobertura de 100% não é problema** (contrata a mais). Sobrando (MWh) maior que no caso base nos três anos. | `r*` de 2023–2025 fica em 1,1111; valor da otimização de 2023 melhora. |
| `pldsimples` | Igual ao caso base. | As médias de `E[PLD]` do `simples` (182 a 202) ficam do mesmo lado de `P_t` que as dos `blocos` (179 a 208): **`r*` igual ao caso base em 2022–2025**, valor da otimização igual nesses anos; 2021 pode andar. A variância do PLD anual é ~9× menor: **CVaR ex-ante bem menor** e **PIT de 2022 e 2023 em 0,000** (o realizado fora de todos os cenários, D linha 549). A conclusão: o resultado do caso base não vem do bootstrap em blocos. | `r*` de 2022–2025 diferente do caso base em dois ou mais anos. |
| `disp125`, `disp150` | Igual ao caso base. | A decisão é guiada pelo sinal de `E[PLD] − P_t`, e a dispersão do **consumo** não o altera: **`r*` igual ao caso base em 2022–2025**, resultado realizado **igual** nesses anos. Muda o **ex-ante**: CVaR95 maior, mais meses fora da faixa nos cenários, e o **PIT de 2023** (consumo acima de todos os cenários do caso base, PIT ≈ 1,000) **se afasta de 1** com `k` maior. 2021 pode andar. Efeito de Jensen na média do consumo < 0,1%. | `r*` de dois ou mais anos muda; PIT de 2023 continua 1,000 em ×1,5. |
| `clip` | Igual ao caso base. | Sem o deslocamento do piso, os meses do histórico acima do piso ficam **mais baratos** (o deslocamento somava `piso_alvo − piso_orig`, ordem de R$ 10 a 55) e todo valor nominal abaixo de `piso_alvo` vira piso: **mais massa no piso e `E[PLD]` menor** que no caso base (mais perto do regime de 2022–2023, que o caso base subestimava). `E[PLD]` dos cenários cai (espero 10% a 25%). **2022** segue `r_min`; **2023 e 2024** (`P_t` 79 e 92) seguem `r_max`; **2021** (`E[PLD]` de 179 para menos que `P_t` = 198) e **2025** (`E[PLD]` de 183 para perto de `P_t` = 148) são os anos que podem mudar. Os cenários continuam mais caros que 2022–2023 realizados. | `E[PLD]` do `clip` maior que o do caso base; `r*` de 2022 diferente de `r_min`. |

**Análise principal (f), leitura conjunta pré-registrada.** (i) Com f = 10%: economia de décimos de % (confirmado no caso base). (ii) O **módulo** do valor da previsão cresce quando f diminui; o **sinal** é o de `P_t − PLDp` do ano (confusão com aposta de preço; não é medida pura de acerto de previsão). (iii) f = 0: valor da otimização exatamente 0. (iv) Valor da otimização: **não monótono em f** nos anos em que `r*` está no limite (a sobra vendida independe de f); H4 (iv) fica **registrada como estava**, com este refinamento ao lado dela. (v) A flexibilidade não tem preço no modelo (D, decisões ex-ante, (c)): uma banda maior parece de graça; o valor da otimização em f maior é **teto**, não estimativa.

**O que vale para todas:** 5 anos, sem teste de significância; 2021–2023 contrafactuais; os números valem como ordem de grandeza.

### 3.1 Resultado analítico e limitação principal (registrados antes de rodar qualquer sensibilidade)

**Resultado analítico.** Com liquidação linear ao PLD (f = 0, `E_m = V_m`), o custo do mês é `C_m·PLDp_m + V_m·(P_t − PLDp_m)`. A diferença de custo entre duas estratégias é

`custo(V₁) − custo(V₂) = (V₁ − V₂) · Σ_m h_m (P_t − PLDp_m)`

e o custo é **linear em `V`**. Logo, o custo **esperado** de uma estratégia depende só do `V` que ela escolhe (e do `E[PLDp]` e do `P_t`), e **a precisão da previsão não entra**: um `V` com erro simétrico em torno do melhor `V` custa, em média, o mesmo que o `V` exato. O que decide o sinal é `(ΔV)·Σ(P_t − PLDp)`: um viés de nível contra o sentido de `P_t − PLDp`, não a dispersão do erro. **O valor da previsão só aparece com assimetria de custo** (ou não linearidade que a gere). No modelo, a única não linearidade é a faixa `[V_m(1−f), V_m(1+f)]`, que é **simétrica** (sobrar e faltar são liquidados ao mesmo PLD, sem penalidade), e por isso ela **dá pouco valor à previsão**; é o que se espera de f = 10% e é o que a análise de f vai mostrar. Isso reforça B10: o valor da previsão com f pequeno é o termo `(ΔV)·Σ(P_t − PLDp)`, não acerto de previsão.

**Principal limitação do modelo: não há penalidade por insuficiência de lastro.** No mercado real há exigência de **cobertura contratual de 100% do consumo, verificada em janela móvel na CCEE**; faltar lastro gera penalidade, e sobrar não. É essa **assimetria** (faltar custa mais que sobrar) que dá valor à previsão e ao viés para cima do volume contratado no mercado real. **Regra exata a confirmar na CCEE** (periodicidade e janela da verificação, base de cálculo e forma da penalidade); nenhum valor é assumido aqui.
- **Registrada como limitação e próximo passo, não incluída no modelo agora.** Incluí-la depois de o caso base ser conhecido e de a expectativa ser escrita seria mudar o critério depois do resultado (as seções 4 e 5 do plano A congelaram um modelo sem penalidade). Fica: (i) o `cobertura_abaixo_de_100` já reportado (anual e mensal, plano A, D8) é o **indicador** dos casos em que a penalidade seria acionada, sem custo associado; (ii) se for implementada, deve ser **declarada antes de olhar o resultado de qualquer período que a use**, com a regra confirmada na CCEE, e avaliada em período ainda não visto ou como nova versão do modelo (`v2`) com o caso base preservado.
- **Consequência para a leitura da Parte B:** com f pequeno e sem a penalidade, as sensibilidades **não medem** o valor da previsão que o mercado real daria. A economia da otimizada é um **teto** (a flexibilidade não tem preço, D, decisões ex-ante, (c)), e o valor da previsão é um **piso** (a assimetria que o valorizaria não está no modelo).

---

## 4. Pré-registro da Parte B e protocolo de rodada única

### 4.1 Sequência (os commits são seus)

1. **Commit A (pré-registro):** este plano + o `decisoes.md` da Parte B. **Enviado ao GitHub (push)**. O hash de A vira `PREREGISTRO_6B` no código.
2. **Commit B:** código novo e testes (nada executado contra o realizado). Mudanças nos módulos do caso base só com **padrão idêntico ao atual** (dispersão = 1, transformação = deslocamento), cobertas por teste de igualdade bit a bit.
3. **Geração dos 3 conjuntos de cenários novos** (local, seção 6): `execucao_id` novos gravados em `ml/congelado_6b_<sens_id>.json`. **Commit C**: esses arquivos. Nada do realizado é lido nesta etapa.
4. **Execução:** `uv run python -m ml.sensibilidades todas --so-travas` e depois `todas`. **Commit D:** resultados.

### 4.2 Travas (qualquer falha aborta antes de calcular)

1. `PREREGISTRO_6B` é **ancestral do HEAD** **e** já está em uma referência remota (`origin/...`): o plano foi enviado.
2. Árvore limpa (`git status --porcelain -uall` vazio) **no início do lote**.
3. Dados conferidos: cenários congelados contra `ml/congelado_6a.json` (os 10 de cenários congelados) ou contra `ml/congelado_6b_<sens_id>.json` (os 3 novos); parquets de realizado (`pld_mensal`, `consumo_mensal`, `pld_2020`, `previstos`) com os **mesmos hashes** do `manifest.json` do caso base.
4. **O caso base não foi tocado:** o hash (sha256) dos três CSV do caso base e do log do caso base é igual ao registrado em `backtest_execucoes.jsonl` (`saidas`). Se diferir, aborta.
5. **Rodada única por `sens_id`:** log append-only **próprio**, `docs/resultados/sensibilidades_execucoes.jsonl` (o log do caso base **não** é aberto para escrita: gravar nele alteraria um arquivo do caso base). Uma linha por execução, com `sens_id`, data/hora UTC, `head`, `preregistro`, `config_hash`, os critérios completos, o **diff contra o caso base** (`muda`), a impressão digital dos cenários e os hashes das saídas. Um `sens_id` com `config_hash` já no log é **recusado** (sem flag de repetição nesta Parte: uma repetição seria nova versão, `v2`, com a anterior preservada).
6. **Saídas nunca sobrescritas:** se um arquivo `sens_<sens_id>_*` existe, aborta. As saídas são escritas num nome temporário, e o log é gravado **por último**; saída sem linha no log (queda no meio) aborta e exige decisão sua.

**Uma trava só para o lote.** A árvore limpa é checada **uma vez**, no início de `todas` (depois da primeira sensibilidade a árvore fica suja pelos próprios resultados, e exigir commit entre as 13 seria artificial). Dentro do lote, cada sensibilidade tem a sua trava de repetição. Se o lote cair no meio, uma nova chamada de `todas` executa só as que **não** estão no log (retomada, não repetição). Sem flag para rodar uma `sens_id` isolada além de `--so-travas`.

**Permitido sem violar o compromisso:** `--so-travas`, a decisão ex-ante (`otimizar`, sem realizado) e testes com dados sintéticos. **Não permitido:** reexecutar a avaliação depois de ver um resultado para ajustar parâmetro. Bug achado depois de ver o realizado: `v2`, com a anterior preservada e a história contada.

---

## 5. Saídas

Por sensibilidade, em `docs/resultados/`, **o `sens_id` no nome** (o caso base mantém os nomes `backtest_caso_base_*`, intocados):

- `sens_<sens_id>_mensal.csv`, `sens_<sens_id>_anual.csv`, `sens_<sens_id>_economia.csv`: o mesmo esquema do caso base (`ml/backtest.py`): custo por estratégia, valor da previsão (R$ e %), valor da otimização (R$ e %), economia total, **por ano e nos recortes 2021–2025 e 2022–2025 (com e sem 2021)**, exposição (descoberto e sobrando, MWh), pior ano, `r*`, `V`, meses fora da faixa, cobertura abaixo de 100%, CVaR ex-ante e PIT. Mais as colunas `sens_id` e `config_hash`.

Agregados (função pura dos arquivos acima e do caso base lido; sem BigQuery; podem ser regerados, pois não são avaliação; nunca tocam os arquivos individuais):

- **`sens_resumo.csv`**: uma linha por (`sens_id`, recorte), com `caso_base` na primeira linha. Colunas: parâmetro que mudou, valor da previsão e da otimização (R$ e %), economia total, pior ano e economia nele, exposição (descoberto, sobrando) da otimizada, e `r*` de cada ano. Lado a lado, na mesma ordem da seção 1.
- **`sens_resumo_por_ano.csv`**: (`sens_id`, ano) com valor da previsão, valor da otimização, `r*`, `V`, meses fora da faixa e cobertura. É nele que se lê "igual ao caso base neste ano".
- **`sens_banda_f.csv`** (análise principal): `f ∈ {0, 5, 10, 15%}` (`f00`, `f05`, `caso_base`, `f15`) × (cada ano, 2021–2025, 2022–2025): valor da previsão (R$, %), valor da otimização (R$, %), economia total, `r*`, meses fora da faixa, descoberto e sobrando por estratégia. Colunas `f` e limites de `r`.
- **`sens_invariancias.csv`**: para cada sensibilidade, quais colunas do caso base permanecem idênticas (a verificação da seção 3 e do teste 8.b), para o relatório não depender de leitura a olho.

**Todos os resultados são reportados**, inclusive os desfavoráveis. Nenhuma escolha do "melhor": o relatório não ordena sensibilidades por economia nem destaca a mais favorável; a tabela segue a ordem da seção 1. Cabeçalho obrigatório (o mesmo do caso base, com o mesmo destaque): 5 anos e nenhum teste de significância; 2021–2023 contrafactuais; `P_t` defasado; modulação perfeita; penalidade de lastro não modelada; cenários subestimam o regime de piso; a flexibilidade não tem preço no modelo. As sensibilidades **não são combinações**: nada aqui diz o que acontece com duas coisas mudando juntas.

---

## 6. Cenários novos: quantos, tempo e bytes

### 6.1 Quantos

**3 `execucao_id` novos:** `disp125`, `disp150`, `clip`. O consumo de `clip` é igual ao do caso base e o PLD de `disp125`/`disp150` é igual ao do caso base (os mesmos valores, sob outro `execucao_id`). Para o `execucao_id` não colidir com o do caso base, o hash ganha os campos `dispersao` e `transformacao` **só quando diferentes do padrão** (com os padrões o id continua `51cf99b073fe`; teste).

### 6.2 Geração (estimativa, a confirmar com `--dry-run`)

Proposta: **um comando, uma leitura, três conjuntos**, **só as 5 origens do backtest** (dez/2020 a dez/2024). A origem de produção (2026-09) **fica fora**: a 6.4 não a usa e ela **muda** quando outubro fechar (a "última origem de produção" é lida de `fct_previsao_carga`; regerar depois mudaria o plano e o id).

| Item | Estimativa | Base da estimativa |
|---|---|---|
| Tempo | ~15 a 25 s para os 3 conjuntos (leitura ~10 a 12 s uma vez + sorteio em memória) | caso base: leitura 7,3 a 12,0 s; gravação em BigQuery foi o resto dos 58,8 s |
| Memória | ~600 MiB (pico do RSS do caso base) | M, "Gravação dos cenários" |
| Bytes lidos do BigQuery | **~40 MiB faturados no total** (4 consultas no piso de 10 MiB: erros de previsão, PLD semanal, PLD ponderado mensal, previsão de produção — esta pode sair, pois a origem de produção fica fora, e então ~30 MiB) | piso de 10 MiB por tabela, A 7 |
| Bytes gerados por conjunto | ~28,6 MB (consumo 10,08 MB + PLD 20,30 MB) × 5/6 origens ≈ **~25 MB por conjunto, ~75 MB nos 3** | `numBytes` do caso base (M) |
| Leitura na avaliação | **0 bytes do BigQuery**: parquet em disco (`data/cenarios_6b/<sens_id>/`, fora do git, ~1,2 MB cada) | os 10 de cenários congelados e o realizado já estão em `data/cenarios_6a/` |

Todas as 13 execuções leem do disco: **0 bytes de BigQuery e menos de ~5 s por execução** (5 origens × até 117 pontos de grade × 2.000 × 12; o caso base inteiro cabe em segundos).

### 6.3 Gravar no BigQuery? E o custo do MERGE

O `MERGE` lê a tabela temporária **e o destino inteiro** (M, "Causa da diferença de bytes"; `numBytes` do destino é o que o MERGE seguinte lê), então cada `execucao_id` gravado acrescenta ~28,6 MB e encarece os seguintes. Se os 3 fossem gravados **em sequência** (cada um com o `MERGE` do caso base, medido: 79 MiB na 2ª execução):

| `MERGE` (ordem) | `fct_cenario_consumo` (temp + destino) | `fct_cenario_pld` (temp + destino) | `fct_cenario_execucao` (piso) | Faturado (MiB, estimado) |
|---|---|---|---|---|
| 2º id (medido, 2ª execução do caso base) | 20,16 MB | 40,61 MB | 20 | **79,0** |
| `disp125` (2º id novo) | 20,16 MB → 20 | 40,61 MB → 39 | 20 | ~79 |
| `disp150` (3º) | 30,24 MB → 29 | 60,91 MB → 58 | 20 | ~107 |
| `clip` (4º) | 40,32 MB → 39 | 81,22 MB → 78 | 20 | ~137 |
| **Soma** | | | | **~323 MiB** (+ ~40 de leitura) ≈ **~0,03% de 1 TiB** |

(O primeiro caso, 79 MiB, é o mesmo do 2º id do caso base, medido; os demais são **cálculo** a partir do `numBytes` medido, **não medidos**. Pisos de 10 MiB por tabela aplicados.) É pequeno, mas cresce com o histórico de ids.

**Particionamento por origem: continua no backlog.** O número: **todos os `execucao_id` cobrem as mesmas 6 (ou 5) origens**, então um filtro por `origem` no `ON` do MERGE **não elimina nenhuma partição** (cada partição contém as linhas de todos os ids); a economia seria **zero**. O que cortaria a leitura do destino seria agrupar (cluster) por `execucao_id`, ou não gravar. Mesmo no melhor caso, o ganho seria ~100 MiB no 4º id (de ~137 para ~30 MiB), ~0,01% da cota mensal gratuita, e as tabelas têm 10 a 20 MB (muito abaixo de onde partição ajuda, e cada tabela referenciada paga o piso de 10 MiB de qualquer jeito). Não vale mexer em tabela de produção por isso.

**Proposta (decisão D-B6, seção 9): os 3 conjuntos de sensibilidade ficam em disco (parquet), com o `execucao_id` e as impressões digitais no `congelado_6b_*.json` e no log; não vão para o BigQuery.** Custo de gravação 0 e nenhuma tabela de produção cresce. A `fct_cenario_execucao` do BigQuery continua só com o caso base. O resultado das sensibilidades entra no BigQuery de forma resumida (6.5, seção 7), que é o que o dashboard usa.

---

## 7. Tarefa 6.5: `fct_recomendacao_contrato`

### 7.1 Esquema proposto

Tabela em `marts`, escrita por `ml/recomendacao.py` (MERGE por chave natural, como `ml/cenarios.py`), **construída a partir dos CSV versionados** do caso base e das sensibilidades (0 bytes de leitura do BigQuery para o backtest) e, para a prévia de produção, dos cenários já gravados da origem 2026-09 e da previsão de produção.

**Chave natural:** (`sens_id`, `origem`, `estrategia`). **Grão:** uma decisão de volume, por sensibilidade, por origem e por estratégia.

| Coluna | Tipo | Significado |
|---|---|---|
| `sens_id` | STRING | `caso_base` ou o id da seção 1 |
| `origem` | DATE | mês da origem (dezembro, ou 2026-09 na prévia) |
| `estrategia` | STRING | `ingenua`, `pontual`, `otimizada` |
| `tipo` | STRING | `backtest` (origem de dezembro, 2020–2024), `producao` (origem de dezembro de produção) ou `previa` (qualquer outra origem) |
| `ano_contrato` | INT64 | ano-calendário decidido; **NULL na prévia** |
| `janela_inicio`, `janela_fim` | DATE | os 12 meses cobertos (iguais ao ano-calendário nas origens de dezembro) |
| `v_mwm`, `razao_v_pontual` | FLOAT64 | volume em MWm e `r` |
| `preco_contrato_rs_mwh` | FLOAT64 | `P_t` |
| `banda_f`, `spread_rs_mwh`, `lambda`, `alfa` | FLOAT64 | parâmetros da decisão |
| `custo_esperado_rs`, `cvar_rs`, `objetivo_j_rs` | FLOAT64 | ex-ante, sobre os cenários da decisão |
| `custo_realizado_rs`, `descoberto_mwh`, `sobrando_mwh`, `meses_fora_da_faixa`, `pit_custo_realizado` | FLOAT64/INT64 | **só `backtest`** (NULL em `producao` e `previa`) |
| `execucao_id` | STRING | cenários usados (`51cf99b073fe` ou o novo) |
| `limites_assumidos` | BOOL | os limites do PLD do ano-alvo foram repetidos do ano anterior |
| `config_hash`, `preregistro`, `commit`, `codigo_hash`, `gerado_em` | STRING/TIMESTAMP | proveniência (como `fct_cenario_execucao`) |

Testes dbt/Python: chave única; `estrategia` e `tipo` em listas aceitas; `custo_realizado_rs` NULL se `tipo != 'backtest'`; `ano_contrato` NULL só se `tipo = 'previa'`; `limites_assumidos` coerente com a seed; contagem esperada de linhas.

### 7.2 O que entra

- **Entra o caso base** (5 origens × 3 estratégias = 15 linhas) com `sens_id = 'caso_base'`.
- **Entram as 13 sensibilidades** (13 × 5 × 3 = 195 linhas), com `sens_id`: o grão é o mesmo (uma decisão de volume) e permite o painel "como a recomendação muda com f, λ, spread". Total: 210 linhas de backtest; **o dashboard filtra `caso_base` por padrão**, e nenhuma sensibilidade substitui o caso base (a chave inclui `sens_id`). Bytes: a escrita é um único MERGE de ~poucos KB, **piso de 20 MiB**.
- A **prévia de produção** entra **só no caso base** (3 linhas): as sensibilidades não foram rodadas sobre a origem de produção.

### 7.3 Origem de produção 2026-09

A decisão do contrato é por **ano-calendário** e sai em dezembro; a origem 2026-09 tem horizontes out/2026 a set/2027, que **não** são um ano-calendário. **Regra proposta:**

1. **Só origem de dezembro gera `tipo = producao`** (recomendação oficial do ano seguinte, `ano_contrato = ano da origem + 1`, janela jan–dez). É o mesmo desenho do backtest (12 horizontes = o ano-calendário inteiro). Em produção isso quer dizer rodar quando o **dezembro** fecha (início de janeiro); como no backtest (origem de dezembro com dezembro conhecido, A seção 0), há uma defasagem de semanas em relação a "sai em dezembro": **registrada como limitação**; a alternativa (origem de novembro e horizontes 2 a 13) exige 13 horizontes e fica fora do escopo.
2. **Qualquer outra origem, inclusive 2026-09, gera `tipo = previa`**: `ano_contrato = NULL`, janela de 12 meses (out/2026–set/2027), sem rótulo de ano-calendário. A prévia responde "qual volume eu contrataria hoje para os próximos 12 meses", **não** "o contrato de 2027". O dashboard a mostra com o rótulo "prévia (janela móvel)", nunca como a decisão de 2027.
3. **`P_t` generalizado para a janela:** `P` = média simples **ponderada pelas horas dos 12 meses fechados até a origem** + spread (para uma origem de dezembro é exatamente "o ano `t−1`" do caso base: teste de igualdade com `pld_medio_do_ano`). Para 2026-09: out/2025–set/2026. A ingênua da prévia usa o consumo realizado dos mesmos 12 meses. Os limites de 2027 são **assumidos** (repetem 2026): `limites_assumidos = true`, como na tabela de execução.
4. **Histórico:** a prévia de cada origem é uma linha nova (a chave inclui `origem`); a de 2026-09 **não** é sobrescrita pela de 2026-10. Quando a origem 2026-12 existir, entra a linha `producao` de 2027.

Mantenho a convenção de informação do backtest (a origem entra como mês conhecido); em produção, o mês da origem pode estar incompleto, e a prévia só é gerada com mês **completo** (`mes_completo`).

---

## 8. Testes (pytest, antes de qualquer execução)

**a) f = 0.** A otimizada é igual à pontual: `V*` = `V_pont`, custos, exposição, CVaR e PIT iguais (comparação exata), `r* = 1`, valor da otimização = 0. Grade de um ponto.

**b) Cada sensibilidade difere do caso base só no parâmetro declarado.**
- O diff entre os `criterios` do caso base e os da sensibilidade (campo `muda` do log) tem **exatamente** as chaves declaradas no registro (`f`, `spread`, `lambda`, `alfa`, `r_max`, `metodo_pld`, `dispersao` ou `transformacao_pld`) e mais nada; os demais (N, semente, passo, desempate, modelo, anos, estratégias, `execucao_id` quando congelado) iguais.
- Invariância (a leitura estrutural da seção 3): para `lam00, lam10, alfa90, rmax120, pldsimples, disp125, disp150, clip`, o `custo_rs`, o `V` e a exposição da **ingênua e da pontual** são **idênticos** ao CSV do caso base (e `lam00, lam10, rmax120` também as colunas ex-ante); a otimizada é idêntica **nos anos em que `r*` é igual** ao do caso base. Para `f*` e `spread*` o diff é esperado em todas as estratégias.
- `rmax120`: o limite inferior continua `1/(1+f)`; a grade contém a do caso base.
- Cada parâmetro é lido do **registro**; a linha de comando só aceita `sens_id` do registro. **Teste de plano:** o bloco JSON da seção 1 deste arquivo (lido do disco) é igual ao registro do código.

**c) Dispersão e clip.** `k = 1` reproduz **bit a bit** os cenários de consumo do caso base (impressão digital por origem igual à de `congelado_6a.json`); `k > 1` mantém a **média por horizonte** de `log_razao` do conjunto sorteado em torno de `m_h` (a propriedade `m_h + k(e − m_h)`), os mesmos vetores sorteados do caso base, e a razão dos desvios é `k`; sem vazamento (alterar erros com alvo posterior à origem não muda os cenários); `execucao_id` com os padrões continua `51cf99b073fe`, e dispersão/clip dão ids diferentes entre si e do caso base. `clip`: todo valor em `[piso_alvo, teto_est_alvo]`; igual a `min(max(PLD_orig, piso), teto)` e **sem** subtrair o piso de origem; os meses históricos sorteados são os mesmos do caso base; consumo igual ao do caso base.

**d) Determinismo.** Mesma entrada, saída idêntica bit a bit (hash); embaralhar linhas dos cenários não muda nada; gerar os cenários duas vezes dá o mesmo `execucao_id` e as mesmas impressões.

**e) Trava contra repetição e guardas.** `sens_id` já no log: recusado; saída existente: recusada; saída sem linha no log: aborta; pré-registro não ancestral ou não enviado ao remoto: aborta; árvore suja: aborta; cenários diferentes do congelado: aborta; `sens_id` fora do registro: recusado; retomada do lote executa só as que faltam.

**f) Nenhum arquivo do caso base é alterado.** O hash dos três CSV do caso base e do `backtest_execucoes.jsonl` antes e depois da execução da suíte e do lote é o mesmo; nenhum código novo escreve em `backtest_caso_base_*` nem no log do caso base (teste de caminho: o nome de saída sempre começa com `sens_`).

**g) 6.5.** Esquema e chave única; `P` generalizado igual ao do caso base nas origens de dezembro; a prévia (2026-09) sai com `ano_contrato` nulo e custo realizado nulo; só origem de dezembro vira `producao`; reexecutar não duplica (MERGE idempotente).

A suíte atual (a partir de 593 testes, mais os da Parte A) segue passando. Arquivos previstos: `ml/sensibilidades.py` (registro, travas, execução), ajustes mínimos em `ml/cenarios_consumo.py` (`sortear` com `dispersao`), `ml/cenarios_pld.py` (`transformar`/`bootstrap` com `transformacao`), `ml/cenarios.py` (gerar local dos 3 conjuntos, campos no `execucao_id`), `ml/recomendacao.py`; `tests/test_ml_sensibilidades.py`, `tests/test_ml_recomendacao.py` e ajustes nos de cenários.

---

## 9. Decisões para o `decisoes.md` (opções e recomendação)

| # | Decisão | Opções | Recomendação |
|---|---|---|---|
| B1 | Dispersão ×k | (a) multiplicar o `log_razao` inteiro; (b) multiplicar o desvio em torno da média do horizonte; (c) em torno da média do próprio vetor | **(b)**: não escala o viés (D 526, "sem mudar a média"), preserva o nível anual do vetor e a correlação entre meses; `k = 1` reproduz o caso base |
| B2 | Limite inferior em `r` até 1,2 | (a) `1/(1+f)`; (b) outro | **(a)**: só o teto muda, uma variável por vez |
| B3 | Spread | (a) muda o `P_t` das três estratégias e a decisão; (b) só da otimizada | **(a)**: é como o contrato funciona (um preço para todos) |
| B4 | `f = 10%` da análise principal | (a) rodar de novo como `f10`; (b) ler o caso base | **(b)**: o caso base nunca é repetido nem sobrescrito; a linha da tabela vem dos arquivos versionados |
| B5 | Definição do clip | (a) cortar o PLD nominal em `[piso, teto estrutural]` do ano-alvo (sem deslocamento); (b) cortar depois do deslocamento | **(a)**, a variante declarada em D (omissão do item 14); só a transformação muda; novo `execucao_id` |
| B6 | Onde ficam os cenários das sensibilidades | (a) BigQuery (~323 MiB de MERGE, +75 MB armazenados, tabelas crescendo); (b) só disco (parquet) com ids e hashes no `congelado_6b_*` e no log; (c) só a `fct_cenario_execucao` | **(b)**: custo 0, nenhuma tabela de produção cresce; o resultado resumido vai ao BigQuery pela 6.5. Particionamento por origem **continua no backlog** (economia zero: todos os ids cobrem as mesmas origens) |
| B7 | Origens dos cenários novos | (a) as 6 do caso base; (b) só as 5 do backtest | **(b)**: a de produção não é usada na 6.4 e **muda** quando outubro fechar; `k = 1` é testado por origem, não pelo id |
| B8 | Log e trava do lote | (a) gravar no log do caso base; (b) log próprio `sensibilidades_execucoes.jsonl`; árvore limpa checada uma vez por lote, trava de repetição por `sens_id` | **(b)**: (a) alteraria um arquivo do caso base; exigir commit entre as 13 execuções seria artificial |
| B9 | Estatuto das expectativas | (a) declará-las cegas; (b) declará-las **condicionais ao caso base visto**, sem recalcular nenhuma sensibilidade | **(b)**: é o que aconteceu; o que o pré-registro protege é não ajustar depois |
| B10 | Leitura do valor da previsão com f pequeno | (a) tratá-lo como acerto da previsão; (b) tratá-lo como `(V_ing − V_pont)·Σh(P_t − PLDp)`, **confundido com aposta de preço** | **(b)**, registrado com a análise de f; **sem execução adicional** (nada fora da lista) |
| B11 | Registro `H4 (iv)` | (a) editar H4; (b) manter H4 como estava e registrar ao lado o refinamento da seção 3 (a sobra vendida independe de f) | **(b)**: não se reescreve pré-registro |
| B12 | Sensibilidades em `fct_recomendacao_contrato` | (a) só o caso base; (b) caso base e sensibilidades, com `sens_id` na chave | **(b)**: mesmo grão, 210 linhas, dashboard filtra `caso_base` |
| B13 | Origem 2026-09 | (a) tratá-la como decisão de 2027; (b) `previa` com janela móvel e `ano_contrato` nulo, `producao` só para origem de dezembro; (c) esperar dezembro e não publicar nada | **(b)**, com `P_t` generalizado para os 12 meses fechados (igual ao caso base nas origens de dezembro). Registrar a defasagem de dezembro como limitação |
| B14 | Resumo e relatório | (a) destacar a melhor sensibilidade; (b) ordem fixa da seção 1, sem ranking | **(b)** |

---

## 10. O que medir e o que atualizar (ao fim)

- **Negócio:** valor da previsão e valor da otimização (R$ e %), por sensibilidade, ano e recorte (com e sem 2021); `r*`; exposição; a tabela em função de f.
- **Engenharia:** bytes lidos na geração (o `--dry-run` primeiro), tempo e memória da geração dos 3 conjuntos, tempo de cada execução (esperado: segundos, 0 bytes de BigQuery), bytes da escrita da `fct_recomendacao_contrato` (um MERGE, piso de 20 MiB).
- **Ciência:** quantos `r*` mudaram contra o caso base por sensibilidade; a média do consumo dos cenários com dispersão ×k (Jensen); a média do PLD dos cenários do clip contra o caso base.

Atualizar ao fim (você commita): `docs/metricas.md` (seção da Parte B), `docs/decisoes.md` (B1 a B14 antes de rodar; resultado depois), `docs/premissas.md` se a definição de `P` por janela for aprovada, marcar 6.4 e 6.5 em `sprints-projeto-energia.md`, e `docs/diario.md`.
