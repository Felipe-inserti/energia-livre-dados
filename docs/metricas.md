# Registro de métricas

Nunca otimizar antes de medir a versão simples. Preencher "Antes" na versão ingênua e "Depois" após a melhoria.

| Nível | Métrica | Antes (versão simples) | Depois | Fase |
|---|---|---|---|---|
| Negócio | Custo anual de energia do consumidor-exemplo (backtest) | estratégia ingênua: R$ __ | estratégia otimizada: R$ __ | 6 |
| Negócio | Economia | — | R$ __ / __% | 6 |
| Negócio | Exposição ao PLD (MWh descobertos ou sobrando) | __ | __ | 6 |
| Ciência | MAPE da previsão de carga | baseline: __% | modelo: __% | 5 |
| Engenharia | Dados lidos por consulta típica | __ GB | __ GB | 1 → 2 |
| Engenharia | Tempo de carga diária | full: __ min | incremental: __ min | 1 → 4 |
| Engenharia | Tempo do backfill completo (2021–hoje) | — | __ min | 4 |
| Engenharia | Problemas de dados capturados pelos testes | — | __ registros (tipos: __) | 3 |
| Engenharia | Idempotência | — | 2 execuções → mesma contagem: sim/não | 4 |
