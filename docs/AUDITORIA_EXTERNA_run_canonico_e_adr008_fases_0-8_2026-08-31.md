# Auditoria ponta a ponta — Run Canônico (5 candidatos) e ADR-008 (Fases 0-8)

**Motor Quant Multi-Ativo — Camada Alpha (Binance USDⓈ-M Futures)**
**Documento gerado em:** 2026-08-31
**Escopo:** transcrição completa e sequencial das duas abas "Run Canônico — 5
Candidatos" e "ADR-008 — Fases 0-8" do artefato ao vivo "ADR-007 — Painel de
Execução", mais o contexto mínimo indispensável (ADR-007) para que um leitor
sem acesso prévio ao projeto consiga entender e auditar cada número. Nenhum
dado das duas abas fonte foi resumido, arredondado além do que a fonte já
mostrava, ou omitido.
**Fontes primárias:**
`docs/ADR-007_medicao_producao_hiperparametro_optuna_15_combos_2026-08-30.md` ·
`docs/ADR-008_auditoria_ml_alpha_institucional_score_quality_walkforward_2026-08-31.md` ·
artefato "ADR-007 — Painel de Execução" (abas "Run Canônico — 5 Candidatos" e
"ADR-008 — Fases 0-8") · `config/constants.yaml::alpha_production_hyperparam_override` ·
`audit/architecture_gaps_log.yaml` (`AG-391`, `AG-392`) ·
`experiments/alpha_walk_forward_{symbol}_{resolution_id}.json` (5 arquivos) ·
commit `e812ab1` (auditoria de engenharia).

---

## 0. Como ler este documento

Este projeto é um motor de trading quantitativo multi-ativo (BTC, ETH, SOL,
BNB, XRP na Binance USDⓈ-M Futures) que tenta prever, para cada barra de
mercado, se vale a pena abrir uma posição comprada (*long*) ou vendida
(*short*). O modelo é um LightGBM binário por lado (`Camada1`/`C1` = vetor
completo de 36 features; `Camada0`/`C0` = subconjunto restrito, usado como
*baseline* de comparação — a diferença entre C1 e C0 é uma ablação de
**restrição monotônica**, não de conjunto de features).

Termos que aparecem sem explicação nas tabelas originais e são traduzidos
aqui uma única vez, no início, para não interromper a leitura depois:

| Termo | Significado prático |
|---|---|
| **Combo** | Um par símbolo/resolução, ex. `BTCUSDT/R2`. `R1`/`R2`/`R3` são identidades de grade (resolução de barra por volume em dólar), não timeframes de relógio — não presumir "R1=15min". |
| **C1 / Camada1** | Modelo com o vetor completo de 36 features, sem restrição monotônica. |
| **C0 / Camada0** | Modelo baseline, restrição monotônica ativa — usado só para comparação relativa (`n_better`, `C1>C0`). |
| **CPCV** | *Combinatorial Purged Cross-Validation* — validação cruzada que combina trechos históricos de forma combinatória (múltiplos "caminhos"/*paths*), com purga para impedir vazamento temporal entre treino e teste. É o mecanismo que embasou a promoção original dos 5 candidatos (`ADR-007`). |
| **Walk-forward** | Validação sequencial: o modelo treina só com o passado e testa só no futuro imediato, avançando no tempo (aqui, trimestre a trimestre, "âncorado" — o treino nunca encolhe, só cresce). É o mecanismo desta ADR-008, deliberadamente diferente do CPCV — a divergência entre os dois é o achado central deste documento. |
| **Sharpe** | Razão retorno/risco do backtest (maior é melhor; não tem unidade). |
| **Edge (líquido/bruto), em bps** | Retorno médio por trade, em pontos-base (1bps = 0,01%), já líquido de custo quando indicado. |
| **DSR** | *Deflated Sharpe Ratio* — Sharpe corrigido pelo número de tentativas já gastas na busca (penaliza garimpagem de hiperparâmetro). Varia de 0 a 1; mais perto de 1 é mais confiável. |
| **`n_better` / "C1>C0 (paths)"** | De quantos caminhos do CPCV (de um total, tipicamente 5) o modelo C1 supera o C0 em Sharpe. |
| **AUC (ROC-AUC)** | Poder discriminativo de classificação binária. 0,50 = equivalente a moeda honesta (sem informação); 1,00 = discriminação perfeita. |
| **IC (Spearman) / Rank IC / IC IR** | Correlação de posto entre a confiança do modelo e o retorno realizado. IC IR = IC médio / desvio-padrão do IC entre folds — mede estabilidade do sinal, não só sua força pontual. |
| **Q10−Q1 (bps)** | Diferença de retorno médio entre o decil de maior confiança do modelo (Q10) e o de menor confiança (Q1) — quanto maior, mais o modelo separa trades bons de ruins. |
| **`tau`** | Limiar de confiança acima do qual o modelo de fato abre uma posição (sinaliza). Confiança abaixo de `tau` = o modelo fica "calado". |
| **SHAP** | Método que atribui, por predição individual, o quanto cada feature CONTRIBUIU para o valor final — diferente do "gain" nativo do LightGBM, que só conta quantas vezes uma feature foi usada para DIVIDIR um nó da árvore. As duas métricas podem discordar sobre qual feature "importa mais", e neste projeto discordam. |
| **`n_lifetime`** | Contador cumulativo, nunca decrescente, de todo trial/retreino de otimização já gasto no projeto — usado para controlar viés de múltiplas comparações (quanto mais se testa, maior a chance de achar um "vencedor" por acaso). |
| **Proveniência (`MEASURED`/`DERIVED`/`LITERATURE`/`ASSUMED`)** | Toda constante numérica do projeto declara de onde veio: `MEASURED` = medida em dado real deste projeto; `DERIVED` = calculada a partir de outra medição/regra; `LITERATURE` = convenção de fonte externa (ex. nível de significância 0,05 de Fisher 1925); `ASSUMED` = escolhida sem base, sinalizada como tal e sujeita a revisão. |
| **Gate duplo** | Critério de promoção original do `ADR-007`: Sharpe relativo C1-vs-C0 (`n_better≥4/5`) **E** edge bruto absoluto (`>0bps`, cobertura mínima de trades). |

---

## 1. Contexto de origem — de onde vêm os "5 candidatos" (resumo do ADR-007)

*(Este bloco não é uma das duas abas pedidas — é o mínimo de contexto sem o
qual as tabelas das seções 2-8 não fazem sentido para quem não acompanhou o
projeto. Fonte: `docs/ADR-007_..._2026-08-30.md` +
`config/constants.yaml::alpha_production_hyperparam_override`.)*

### 1.1 Por que o ADR-007 existiu

Uma campanha anterior (`AG-382`/`AG-383`) tinha rodado Optuna real pela
primeira vez no projeto — 900 trials de busca + 450 retreinos de confirmação
multi-seed + 450 retreinos sob gate duplo + 75 de diagnóstico — sobre 15
combos (5 símbolos × 3 resoluções). Resultado bruto: **apenas 1 de 15 combos**
(`BTCUSDT/R3`) sobrevivia ao gate duplo. Analisando os 15 resultados juntos,
dois padrões concentrados de fraqueza apareceram: `BNBUSDT` com edge bruto
negativo nas 3 resoluções sem exceção, e a resolução `R1` com o pior edge
médio entre as 3 resoluções em todos os símbolos.

O Manager pediu, explicitamente, "cuidado com falsos positivos" — e o
ADR-007 nasceu para (a) expandir o orçamento de busca nos combos mais
promissores, (b) confirmar com mais rigor estatístico, (c) medir a própria
taxa de falso-positivo do gate, (d) corrigir por múltiplas comparações, e
(e) formalizar um critério de poda operacional.

### 1.2 Correção de validação, feita antes de qualquer execução

Ao revalidar a lista original de "8 combos promissores", uma inconsistência
real foi encontrada: a lista excluía `BNBUSDT`/`R1` mecanicamente, sem
recalcular a média de edge por símbolo — e isso deixava `ETHUSDT/R2`
(-1,66bps) e `ETHUSDT/R3` (-13,19bps, o PIOR edge de todas as 15
combinações) dentro do orçamento expandido, enquanto `SOLUSDT/R1` (+1,17bps,
individualmente positivo) ficava fora só por ser R1.

| Símbolo | Edge médio (3 resoluções) | Padrão |
|---|---:|---|
| `ETHUSDT` | **-6,98 bps** | negativo nas 3, sem exceção — pior que `BNBUSDT` |
| `BNBUSDT` | -5,51 bps | negativo nas 3, sem exceção |
| `BTCUSDT` | +2,61 bps | 2 de 3 positivas |
| `XRPUSDT` | +6,66 bps | 2 de 3 positivas |
| `SOLUSDT` | +10,51 bps | 3 de 3 positivas |

Correção aplicada: `BNBUSDT` **e** `ETHUSDT` saem do orçamento expandido
(mesma regra, aplicada de forma consistente); `R1` continua fora mesmo
recalculado só sobre BTC/SOL/XRP (média R1=-3,30bps, ainda a pior das 3
resoluções). **Item 1 passa de 8 para 6 combos**: `BTCUSDT/R2`,
`BTCUSDT/R3`, `SOLUSDT/R2`, `SOLUSDT/R3`, `XRPUSDT/R2`, `XRPUSDT/R3`.

### 1.3 Itens 1-5 do ADR-007 — resultado real

| Item | O quê | Resultado |
|---|---|---|
| 1 | Busca expandida (30→150 trials/study), 6 combos × 2 camadas | 1.800/1.800 trials, 0 falhas, 2h32m18s. Achado: `SOLUSDT/R2` com as DUAS camadas em `best_value` extremo (C1=22,2236, C0=8,9603, vs. p95≈0,824 da campanha inteira) — sinalizado como possível anomalia de screening, não tratado como sinal real até o Item 2. |
| 2 | Confirmação profunda (top-3→top-6 candidatos, 5→10 seeds) | 720/720 confirmações, 0 falhas, 1h00m51s. **ZERO dos 6 combos passam o gate duplo.** `BTCUSDT/R3` — o único combo que já tinha passado o gate em algum momento — cai de `n_better=4,0` para `median_n_better=2,5` sob o orçamento maior. A anomalia de `SOLUSDT/R2` (Item 1) confirma-se como ruído puro de screening: viés de seleção medido em **+8,356**, o maior já registrado no projeto. |
| 3 | Calibração do gate (`AG-220`) sob os 36 features atuais, 3 combos representativos | 300/300 retreinos. Taxa de falso-positivo do gate duplo sob ruído puro: `BTCUSDT/R3`=8,0%, `ETHUSDT/R1`=0,0%, `BNBUSDT/R1`=0,0% — todos abaixo do piso de confiança de 20%. **O gate não é impossível de passar por acaso** — logo, "ZERO combos passam" no Item 2 reflete ausência real de sinal, não um instrumento quebrado. |
| 4 | Correção de múltiplas comparações (FDR, Benjamini-Hochberg/Benjamini-Yekutieli) | Aplicada à tabela de taxa-base (H0-H7, 15 z-scores reais): 7/15 significativos sem correção → 4/15 sob BH → 3/15 sob BY. Ainda não aplicada ao resultado dos Itens 1-2 (estatística de teste correta não decidida — lacuna registrada, `AG-389`). |
| 5 | Critério operacional de poda | Registrado (`alpha_prune_min_edge_bps_threshold=0,0`, `alpha_prune_max_gate_fpr=0,20`), as duas pré-condições agora satisfeitas por dado real — decisão de aplicar (mudar o escopo de treino do Alpha) fica com o Manager, não é automática. |

**Veredito consolidado do ADR-007 (Itens 1-5):** nenhum dos 6 combos com edge
de screening positivo produz uma vantagem C1-vs-C0 estatisticamente estável
sob confirmação profunda — 0/6 passam o gate duplo. A ausência de sinal não
é explicada por um gate quebrado (Item 3 mediu FPR real, baixo). O que falha
consistentemente é o Sharpe RELATIVO C1-vs-C0 sob reamostragem de seed, não
necessariamente o sinal econômico bruto em si (a maioria dos combos mantém
edge bruto positivo).

### 1.4 A decisão de override — por que 5 candidatos foram promovidos mesmo com ZERO/6 no gate

Apesar do resultado acima, o Manager tomou uma decisão explícita, registrada
em `config/constants.yaml::alpha_production_hyperparam_override` (2026-08-31,
`provenance: ASSUMED`), promovendo **5 dos 6** combos à produção canônica —
**não automaticamente pelo gate duplo**, e sim por um critério de segunda
ordem: **menor viés de seleção de Camada1** (screening menos mediana
confirmada) entre duas medições reais disponíveis por combo — H10 (a
campanha anterior: top-3, 5 seeds, busca de 30 trials) **vs.** o Item 2 desta
ADR-007 (top-6, 10 seeds, busca de 150 trials) — **salvo quando o gap de
viés é trivial e o gap de edge líquido é real**, caso em que o Item 2 vence
mesmo sem menor viés.

| Combo | Hiperparâmetro usado | Motivo (dado real, não regra cega) |
|---|---|---|
| `BTCUSDT/R2` | H10 (`antes`) | H10 vence em edge E em viés, sem ambiguidade. |
| `SOLUSDT/R2` | H10 (`antes`) | H10 vence em edge E em viés, sem ambiguidade. |
| `XRPUSDT/R2` | H10 (`antes`) | H10 vence em edge E em viés, sem ambiguidade. |
| `SOLUSDT/R3` | Item 2 (`depois`) | Gap de viés desprezível entre as duas medições (0,172 vs. 0,185) — mas ganho de edge real e robusto no Item 2 (**+6,3bps**, 9/10 seeds positivas, faixa 16,6-39,3bps) — usa a medição mais recente. |
| `XRPUSDT/R3` | H10 (`antes`) | Caso oposto: o ganho de edge do Item 2 é ruído (+0,6bps) contra um gap de viés real (0,216→0,467) e distribuição por seed mais dispersa/instável (3/10 seeds abaixo de 6bps, 1 seed negativa) — usa a medição anterior. |
| `BTCUSDT/R3` | **excluído deliberadamente** | Único combo que já passou o gate H10 em algum momento — decisão do Manager de focar nos 5, não nos 6 medidos. |

Timestamps de origem do artefato usado em produção: `SOLUSDT_R3` =
`20260831T024607Z` (retreinado separadamente, mais recente — reflete a
escolha "Item 2/depois"); os outros 4 combos = `20260830T143204Z`.

**Nota crítica para o leitor externo:** esta promoção é uma decisão humana
explícita de tolerância a risco (0/6 no gate duplo automático, promovido
mesmo assim por um critério de segunda ordem), não uma aprovação automática
do pipeline. É exatamente esse conjunto de 5 combos — promovidos apesar do
gate duplo reprovar todos — que o ADR-008 (seções 3-8 abaixo) audita de
forma independente, com um mecanismo de validação diferente (walk-forward
real, sequencial no tempo, em vez de CPCV combinatório).

---

## 2. Aba "Run Canônico — 5 Candidatos" (transcrição completa)

> Nota de proveniência original da aba: *"Run canônico de produção
> (`run_layer1_sprint`, seed única de produção — `alpha_random_seed`, sem
> busca/confirmação multi-seed) sob os 5 candidatos promovidos por decisão
> explícita do Manager (`alpha_production_hyperparam_override`). Todas as
> métricas abaixo vêm direto dos relatórios reais gerados nesta execução
> (2026-08-31, 11:18-11:24) — nenhuma estimada."*

### 2.1 KPIs agregados da execução

| Métrica | Valor |
|---|---:|
| Combos | 5/5 |
| Falhas | 0 |
| Tempo total | 358,8s |
| Trades totais (C1) | 6.554 |
| Win rate médio (C1) | 57,2% |
| `N_lifetime` | 5.510 → 5.515 |

### 2.2 Resultado por combo (produção, seed única)

| Combo | Sharpe C1 | Edge líq. C1 | Win rate C1 | Trades/dia C1 | Trades (total) | Fill rate | C1>C0 (paths) | DSR | SR/trade | Período de treino |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `BTCUSDT/R2` | 0,865 | **+13,61bps** | 57,0% | 0,32 | 2.763 | 99,1% | 2/5 | 0,901 | 0,0930 | 2020-01-04 → 2026-08-10 |
| `SOLUSDT/R2` | 0,543 | **+16,65bps** | 56,1% | 0,10 | 844 | 98,6% | 4/5 | 0,021 | 0,0586 | 2021-12-05 → 2026-08-10 |
| `SOLUSDT/R3` | 0,705 | **+30,06bps** | 60,9% | 0,06 | 571 | 98,9% | 2/5 | 0,542 | 0,1642 | 2021-12-06 → 2026-08-10 |
| `XRPUSDT/R2` | 0,889 | **+16,49bps** | 56,9% | 0,25 | 1.579 | 99,1% | 2/5 | 0,039 | 0,0489 | 2021-12-05 → 2026-08-10 |
| `XRPUSDT/R3` | 0,636 | **+21,02bps** | 55,1% | 0,11 | 797 | 99,6% | 3/5 | 0,027 | 0,0618 | 2021-12-05 → 2026-08-10 |

> **Nota real, não escondida (do painel original):** esta é **1 seed única de
> produção** (`alpha_random_seed`), não a mediana de 10 seeds do Item 2 —
> os números acima PODEM divergir do Item 2 combo a combo, e divergem de
> fato: `SOLUSDT/R3` mostra Camada0 (Sharpe 1,056) superando Camada1
> (0,705) SOB ESTA SEED especificamente, mesmo sendo o candidato com sinal
> mais robusto entre os 5 no Item 2 (10 seeds). `XRPUSDT/R3` mostra o mesmo
> padrão (C0 edge +45,82bps vs. C1 +21,02bps). Isso não invalida a
> promoção — reforça a variância entre seeds já medida no ADR-007 inteiro.
> **Nenhum dos 5 combos passa `n_better≥4/5` sob esta seed**, consistente
> com o Item 2.

### 2.3 Ranking de gain por feature — todas as 36, Camada1

Participação de cada feature no `gain` total do booster (long+short, média
entre folds), por combo — leitura direta dos diagnostics reais gravados
nesta execução. Ordenado pela média entre os 5 candidatos (maior para
menor).

| # | Feature | BTCUSDT/R2 | SOLUSDT/R2 | SOLUSDT/R3 | XRPUSDT/R2 | XRPUSDT/R3 | **Média** |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | `A04_log_return_12` | 0,2093 | 0,0387 | 0,2548 | 0,2686 | 0,2069 | **0,1957** |
| 2 | `E16f_global_ls_ratio` | 0,1440 | 0,2204 | 0,2319 | 0,0404 | 0,0457 | **0,1365** |
| 3 | `E14f_toptrader_ls_ratio` | 0,1113 | 0,0482 | 0,1127 | 0,0618 | 0,1987 | **0,1065** |
| 4 | `A11_true_range_pct` | 0,1640 | 0,0994 | 0,0501 | 0,0724 | 0,1449 | **0,1062** |
| 5 | `E05f_time_to_funding_h` | 0,0449 | 0,0919 | 0,0580 | 0,2425 | 0,0602 | **0,0995** |
| 6 | `A13_dist_ema48_atr` | 0,0567 | 0,2572 | 0,0392 | 0,0528 | 0,0541 | **0,0920** |
| 7 | `A19_log_range` | 0,1756 | 0,0677 | 0,0594 | 0,0266 | 0,1056 | **0,0870** |
| 8 | `E01f_funding_last` | 0,0911 | 0,1058 | 0,1109 | 0,0166 | 0,0662 | **0,0781** |
| 9 | `E27f_cost_atr_ratio` | 0,0424 | 0,1093 | 0,0530 | 0,0989 | 0,0447 | **0,0696** |
| 10 | `A03_log_return_4` | 0,0680 | 0,0262 | 0,0487 | 0,0208 | 0,1829 | **0,0693** |
| 11 | `A20_log_duration` | 0,0188 | 0,0854 | 0,0661 | 0,0837 | 0,0876 | **0,0683** |
| 12 | `A21_log_dollar_velocity` | 0,0510 | 0,1025 | 0,0187 | 0,0758 | 0,0730 | **0,0642** |
| 13 | `E10f_oi_change_z_48` | 0,0291 | 0,0380 | 0,0177 | 0,1578 | 0,0726 | **0,0630** |
| 14 | `C06_vol_ratio_12_96` | 0,0392 | 0,0469 | 0,0383 | 0,1640 | 0,0202 | **0,0617** |
| 15 | `A16_return_3` | 0,0260 | 0,0142 | 0,1358 | 0,0920 | 0,0253 | **0,0587** |
| 16 | `C12_vol_of_vol_48` | 0,1222 | 0,0141 | 0,0577 | 0,0478 | 0,0496 | **0,0583** |
| 17 | `B14_rejection_after_extension` | 0,0488 | 0,1157 | 0,0287 | 0,0360 | 0,0601 | **0,0579** |
| 18 | `A06_ret_vol_norm_12` | 0,0540 | 0,0557 | 0,1051 | 0,0196 | 0,0336 | **0,0536** |
| 19 | `B01_rsi_14` | 0,0567 | 0,0944 | 0,0262 | 0,0528 | 0,0354 | **0,0531** |
| 20 | `A02_log_return_2` | 0,0703 | 0,0237 | 0,0441 | 0,0712 | 0,0498 | **0,0518** |
| 21 | `D08f_trade_count_z_48` | 0,0203 | 0,0842 | 0,0439 | 0,0328 | 0,0682 | **0,0499** |
| 22 | `B18_engulfing_atr` | 0,0474 | 0,0347 | 0,0472 | 0,0316 | 0,0429 | **0,0407** |
| 23 | `A17_log_tr_per_overshoot_ratio` | 0,0307 | 0,0516 | 0,0442 | 0,0265 | 0,0248 | **0,0356** |
| 24 | `A05_ret_vol_norm_4` | 0,0605 | 0,0083 | 0,0301 | 0,0278 | 0,0321 | **0,0318** |
| 25 | `A01_log_return_1` | 0,0515 | 0,0072 | 0,0296 | 0,0381 | 0,0290 | **0,0311** |
| 26 | `D06f_taker_imbalance_z_48` | 0,0277 | 0,0069 | 0,0782 | 0,0086 | 0,0254 | **0,0294** |
| 27 | `D05f_taker_buy_ratio` | 0,0287 | 0,0618 | 0,0125 | 0,0253 | 0,0030 | **0,0263** |
| 28 | `A18_body_log` | 0,0603 | 0,0027 | 0,0175 | 0,0197 | 0,0284 | **0,0257** |
| 29 | `B12_close_location_h3` | 0,0072 | 0,0209 | 0,0287 | 0,0076 | 0,0640 | **0,0257** |
| 30 | `B13_extension_h3` | 0,0112 | 0,0155 | 0,0475 | 0,0392 | 0,0100 | **0,0247** |
| 31 | `B16_log_range_ratio_1` | 0,0173 | 0,0300 | 0,0191 | 0,0164 | 0,0088 | **0,0183** |
| 32 | `B15_efficiency_ratio_h3` | 0,0039 | 0,0021 | 0,0118 | 0,0128 | 0,0360 | **0,0133** |
| 33 | `B17_directional_pressure_h3` | 0,0031 | 0,0167 | 0,0283 | 0,0084 | 0,0085 | **0,0130** |
| 34 | `K04_session_asia` ⚠ | 0,0044 | 0,0017 | 0,0032 | 0,0020 | 0,0017 | **0,0026** |
| 35 | `E12f_price_oi_divergence` ⚠ | 0,0020 | 0,0002 | 0,0010 | 0,0010 | 0,0000 | **0,0008** |
| 36 | `K03_is_weekend` ⚠ | 0,0004 | 0,0000 | 0,0000 | 0,0000 | 0,0000 | **0,0001** |

> **Candidatas reais a poda — gain médio <1% nos 5 candidatos:**
> `K04_session_asia`, `E12f_price_oi_divergence`, `K03_is_weekend`.
> `K03_is_weekend` é literalmente 0,00% em 4 dos 5 combos. Achado de dado
> real, não estimativa — próximo passo real desta linha de trabalho
> (análise de poda formal), ainda não executado.

---

## 3. ADR-008 — por que esta auditoria existiu, e como foi desenhada

*(A partir daqui, o documento cobre a aba "ADR-008 — Fases 0-8" do painel,
mais o texto de Contexto/Decisão do documento-fonte, que a aba resume mas
não substitui integralmente.)*

### 3.1 Motivação

Depois de promover os 5 candidatos descritos na Seção 1.4, o Manager trouxe
uma especificação de auditoria institucional de ML/Alpha (14 blocos +
prioridade explícita, formato "Training Run Report": IC/Rank IC,
walk-forward obrigatório, gates codificados, auditoria de vazamento, SHAP,
"cartão" final PASS/FAIL) e pediu validação contra o motor real antes de
decidir o que construir.

Um agente de auditoria mapeou os 14 blocos contra o código real, com citação
de arquivo:linha. Achado central: **a infraestrutura de base já existia,
espalhada em módulos nunca consolidados** — auditoria de vazamento (14
testes já existentes), análise de decil/quantil (2 implementações
independentes já existentes), estratificação por regime (já existente),
auditoria de trajetória de HPO (Optuna SQLite + viés de seleção já medido em
produção real). O gap real era estreito: **duas classes de métrica nunca
calculadas para o SCORE do modelo** (classificação formal — AUC/PR-AUC/
LogLoss/Brier — e IC/Rank IC/IC IR do score contra retorno, antes só
existente por FEATURE individual, propósito diferente), mais walk-forward
real nunca ligado ao motor de treino (embora um splitter de janela ancorada
reutilizável já existisse, usado só para comparação de estimador de
volatilidade), mais SHAP (ausência total).

Isto também fechou uma lacuna deixada aberta pelo próprio ADR-007: o Item 6
("walk-forward real") tinha ficado registrado como risco residual explícito,
fora de orçamento — o ADR-008 é exatamente esse item, agora com a peça
reutilizável identificada, com esforço real MÉDIO, não ALTO como o ADR-007
presumia sem ter investigado.

### 3.2 As 9 fases, por dependência (não pela ordem que o consultor listou)

```
Fase 0 ── correção pontual (proveniência do relatório)
   │
Fase 1 ── métricas fundamentais do SCORE (IC/Rank IC/IC IR, AUC/PR-AUC/LogLoss/Brier, Q10-Q1)
   │         │                                    │
   │         ├──────────────► Fase 3 (gap fit/stop/calib)
   │         │                                    │
   │         └──────────────► Fase 4 (walk-forward real) ◄── Fase 2 (paralela, independente)
   │                                    │
   │                                    ├──────► Fase 5 (stability matrix, parcial)
   │                                    │
Fase 6 (gates) ◄── precisa das métricas de Fase 1/3/4 existirem primeiro
   │
Fase 7 (SHAP) ── independente, pode entrar em paralelo a qualquer momento após Fase 1
   │
Fase 8 (cartão final / model card) ◄── consolida 0-7
```

A ordem foi escolhida deliberadamente diferente da lista original do
consultor (que colocava walk-forward antes de qualquer métrica de IC/
classificação) porque construir walk-forward antes da Fase 1 produziria
folds reportando só o que já existia (Sharpe/edge), sem as métricas que dão
ao walk-forward seu valor real — teria exigido re-rodar depois. Duas opções
alternativas foram consideradas e rejeitadas: expandir todos os 14 blocos na
ordem do consultor (retrabalho), e fazer só o item de maior prioridade
isolado (walk-forward sem Fase 1 pronta, mesmo problema de retrabalho).

### 3.3 KPIs agregados da auditoria completa

| Métrica | Valor |
|---|---:|
| Fases concluídas | 9/9 |
| Testes novos | 131+ |
| Bugs reais corrigidos em campo (durante a execução, não hipotéticos) | 3 |
| `N_lifetime` (Fase 4) | 5.515 → 5.520 |
| Combos nos 3 gates (ambos os lados) | **0/10** |
| Lados nos 3 gates (cartão final, granularidade completa) | **0/20** |

---

## 4. Fases 0-3 — infraestrutura de medição (zero custo de retreino)

Todas reusam predições/artefatos já materializados — nenhuma treina modelo
novo. Commits `b03109c`..`404a7dd`.

| Fase | Entrega | Achado/nota real |
|---|---|---|
| **0** | Paridade de proveniência (`report_provenance()` no relatório principal) | Pré-requisito das demais fases. |
| **1** | `score_quality.py` novo — ROC-AUC/PR-AUC/LogLoss/Brier + Pearson IC/Spearman IC/IC IR/Q10-Q1 sobre o `confidence` calibrado — nunca medido antes para o output final do modelo (só por feature individual) | Base estatística de todo o resto da ADR. |
| **2** | 4 itens independentes: feature audit (mean/std/percentis por coluna) · label audit (distribuição ternária/binária, momentos, autocorrelação) · export completo da trajetória Optuna (não só o vencedor) · estratificação hora/dia-semana/mês/trimestre | 29 testes novos, sweep 2.699 testes: 2.698 verdes (1 falha pré-existente não relacionada). |
| **3** | `compute_train_val_test_gap` — mesmas métricas da Fase 1 aplicadas aos sub-splits IN-SAMPLE (`fit`/`stop`/`calib`) que treinaram o modelo, contra o OOF já medido — mede o "generalization gap" clássico | `SideModelResult` ganhou 3 campos opcionais; 11 testes novos. |

---

## 5. Fase 4 — Walk-forward real

Walk-forward ancorado (`initial_train_years=2`, passo trimestral civil, o
treino nunca encolhe — só cresce a cada trimestre) sobre os mesmos 5
candidatos do run canônico (Seção 2) — Camada1 e Camada0, hiperparâmetro
CONFIRMADO (sem busca nova). Medição prévia de 1 fold real
(`BTCUSDT/R2` fold_id=0): 0,6s — a campanha completa foi então autorizada
sob a política "Orçamento = Completo": 10 runs (5 combos × 2 camadas), ~117s
de treino real + ~100s de IO, 0 falhas. Artefatos:
`experiments/alpha_walk_forward_{symbol}_{resolution_id}.json` (5 arquivos).

### 5.1 Assimetria de histórico entre ativos

> **Correção (2026-08-31, achado real H1 da auditoria adversarial externa,
> `AG-393` item 1 / roadmap "Caso 0/20" item 13):** a versão original desta
> seção afirmava "1º trimestre testado (**todos os combos**) = 2023-10-01"
> — falso para `BTCUSDT/R2`. Verificado direto contra o artefato real
> (`experiments/alpha_walk_forward_BTCUSDT_R2.json`, fold_id=0):
> `test_start=2022-01-01`, não 2023-10-01. `BTCUSDT/R2` é o único dos 5
> candidatos cuja janela de teste alcança 2022 — os outros 4 (base SOL/XRP)
> começam em 2023-10, como a versão original descrevia corretamente só
> para eles. Tabela e texto abaixo corrigidos; valor errado riscado, não
> apagado (rastreabilidade).

| Métrica | Valor |
|---|---:|
| Histórico BTCUSDT (treino disponível desde) | 2020-01-07 |
| Histórico SOL/XRP (treino disponível desde) | 2021-12-08 |
| 1º trimestre testado — `BTCUSDT/R2` | **2022-01-01** (verificado, não ~~2023-10-01~~) |
| 1º trimestre testado — `SOLUSDT/R2`, `SOLUSDT/R3`, `XRPUSDT/R2`, `XRPUSDT/R3` | 2023-10-01 |
| Último trimestre testado (todos os combos) | 2026-08-07 |

O treino do fold 0 sempre começa no início do histórico do ATIVO (não é o
mesmo ponto para os 5 candidatos) — `initial_train_years=2` depois disso é
quando o teste começa. **BTCUSDT tem ~2 anos a mais de histórico nesta
pipeline que SOL/XRP** (2020 vs. dezembro/2021) — por isso `BTCUSDT/R2`
gera 19 folds trimestrais contra só 12 dos outros 4 combos, cobrindo ~4,6
anos de teste real (2022-01 a 2026-08) contra ~2,85 anos (2023-10 a
2026-08) dos outros 4. Todos os combos convergem no MESMO trimestre final
de teste (2026-Q3, truncado em 07/08) porque o dado real da pipeline
termina aí — só o INÍCIO da janela diverge, não o fim.

### 5.2 O que cada coluna da tabela significa, na prática

- **Folds totais** — quantos trimestres civis de teste o walk-forward gerou
  para aquele combo, do 1º trimestre depois dos 2 anos de treino inicial até
  o fim do dado real disponível. É um número de DESENHO (depende só do
  histórico do ativo), não de qualidade do modelo.
- **Usados** — de "Folds totais", quantos tiveram trades REALIZADOS
  suficientes (≥10, `alpha.MIN_OCCURRENCES_ABOVE_TAU`) para que o
  Sharpe/edge daquele trimestre seja estatisticamente confiável. Um
  trimestre pode ter milhares de barras de teste e ainda assim virar
  "não-usado" se o modelo quase não sinalizou nele.
- **Degenerados** — "Folds totais" menos "Usados": trimestres descartados do
  agregado por terem poucos trades (na prática, quase sempre porque o
  modelo raramente cruzou o limiar de confiança `tau` naquele período — não
  é falta de dado de mercado, é o modelo ficando calado).
- **Sharpe (usados)** — Sharpe médio calculado SÓ sobre os trimestres
  "Usados" (nunca sobre os degenerados, que distorceriam o número — foi
  exatamente um Sharpe de 47.163,5 sobre 2 trades que motivou excluir os
  degenerados do agregado, ver 5.3).

### 5.3 Três correções reais, achadas rodando de verdade (não hipotéticas)

1. `mf.data` tem 2 linhas por barra (uma por lado) e não é globalmente
   monótono em `t0` — quebrava a geração de splits na primeira execução
   real; corrigido trabalhando por timestamp em vez de posição.
2. Um fold com 0 barras de teste válidas (gap real de dado, ex.
   `E14f_toptrader_ls_ratio` quase 100% nulo num trimestre específico) fazia
   `alpha.run_fold` quebrar dentro do `predict_proba` do LightGBM — DEPOIS
   de já ter treinado os dois lados; corrigido checando antes de treinar.
3. O critério original de "fold degenerado" gateava em barras de teste
   (população de inferência) em vez de trades realizados — um fold de
   `SOLUSDT/R2` com 2.097 barras válidas mas só 2 trades produziu
   **Sharpe=47.163,5** (estatisticamente sem sentido), distorcendo o
   agregado inteiro daquele combo. Corrigido para gatear em
   `n_filled_trades < 10` (mesma constante que `alpha.MIN_OCCURRENCES_ABOVE_TAU`
   já usa para o mesmo princípio).

### 5.4 Resultado real, 10 linhas (5 combos × 2 camadas)

| Combo | Camada | Folds totais | Usados | Degenerados | Sharpe (usados) | Edge líq. | Win rate |
|---|---|---:|---:|---:|---:|---:|---:|
| `BTCUSDT/R2` | Camada1 | 19 | 8 | 11 | 0,992 | **+7,90bps** | 56,1% |
| `BTCUSDT/R2` | Camada0 | 19 | 7 | 12 | 0,380 | **+1,35bps** | 55,4% |
| `SOLUSDT/R2` | Camada1 | 12 | **1** | 11 | **-4,077** | **-57,66bps** | 35,1% |
| `SOLUSDT/R2` | Camada0 | 12 | **1** | 11 | **-4,077** | **-57,66bps** | 35,1% |
| `SOLUSDT/R3` | Camada1 | 12 | 4 | 8 | **-0,924** | **-17,00bps** | 46,5% |
| `SOLUSDT/R3` | Camada0 | 12 | 3 | 9 | **-3,657** | **-32,82bps** | 41,2% |
| `XRPUSDT/R2` | Camada1 | 12 | 6 | 6 | **-1,271** | **-28,25bps** | 48,7% |
| `XRPUSDT/R2` | Camada0 | 12 | 4 | 8 | **-1,459** | **-17,55bps** | 44,3% |
| `XRPUSDT/R3` | Camada1 | 12 | 4 | 8 | **-5,322** | **-34,54bps** | 44,0% |
| `XRPUSDT/R3` | Camada0 | 12 | 6 | 6 | 1,503 | **+26,34bps** | 60,6% |

> **Achado bruto (Fase 4):** taxa de fold degenerado alta nos 5 candidatos —
> `SOLUSDT/R2` fica com só 1 de 12 folds usável nas DUAS camadas
> (hiperparâmetro confirmado idêntico entre Camada1/Camada0 para este combo,
> verificado no JSON de confirmação — não é bug de carregamento). Sharpe/
> edge agregados majoritariamente NEGATIVOS — diferente do quadro CPCV
> (`n_lifetime id=41`, todos positivos). `BTCUSDT/R2` é o único combo com
> edge positivo nas 2 camadas.

### 5.5 Investigação — por que `SOLUSDT/R2` "travou" (pergunta do Manager, respondida com dado real)

> **Correção (2026-08-31, achado da auditoria adversarial — Seção 15, `AG-393` item 2):**
> o texto abaixo, publicado originalmente nesta seção e no painel ao vivo, cita o
> hiperparâmetro ERRADO. O candidato efetivamente promovido e testado no
> walk-forward para `SOLUSDT/R2` é o de `run_stamp=20260830T143204Z` ("H10",
> top-3/5-seeds — ver `config/constants.yaml::alpha_production_hyperparam_override`),
> não o do Item 2 do ADR-007 (top-6/10-seeds) de onde vinha o "recorde +8,356"
> citado abaixo. O candidato real tem viés de seleção medido em apenas **+0,357**
> — uma ordem de grandeza menor — e ainda assim mostra a MAIOR divergência
> CPCV-vs-walk-forward dos 5 candidatos. Recomputando com o artefato CPCV
> canônico correto (o texto original usava um artefato genérico desatualizado,
> anterior ao run de produção), os gaps CPCV-vs-WF ficam MAIORES em todos os 5
> combos (+5,7 a +74,3bps), e não há correlação entre viés medido e tamanho do
> gap em NENHUM dos 5 (Spearman ≈0,10-0,40, n=5, não significativo). **A
> pergunta "por que CPCV diverge do walk-forward real" segue SEM explicação
> medida para nenhum dos 5 candidatos** — mais fraco do que o texto abaixo
> sugeria. Isso não muda o achado "0/20" (nenhum dos 6 ângulos testados pela
> auditoria adversarial encontrou motivo para revertê-lo ou enfraquecê-lo — ver
> Seção 15) — só corrige a causa-raiz atribuída à divergência de `SOLUSDT/R2`
> especificamente. Texto original mantido abaixo por transparência histórica.

Não é bug do walk-forward — é a confirmação fora-da-amostra de um achado
que o ADR-007 já tinha marcado como suspeito ANTES desta auditoria rodar.
Fold a fold, `SOLUSDT/R2` tem `n_signals=0` em 8 dos 12 trimestres — o
modelo simplesmente não sinaliza (`confidence` quase nunca cruza `tau`) na
maior parte do período real.

Mas o MESMO hiperparâmetro, sob confirmação CPCV
(`experiments/alpha_optuna_confirmation_SOLUSDT_R2_*.json`), gerou **675
trades** com edge médio de apenas **+0,32bps** — e o Item 2 do ADR-007
(confirmação com 10 seeds) já tinha medido ali o **maior viés de seleção já
registrado no projeto (+8,356)**: o hiperparâmetro foi escolhido durante a
busca do Optuna porque encaixou em ruído específico da janela de screening
CPCV (`best_value`=22,22, ~27× o p95 da campanha inteira).

CPCV combina trechos históricos de forma combinatória — um hiperparâmetro
que se encaixa bem numa fatia específica do passado ainda mistura essa
fatia com outras no *confirmation set*, escondendo o problema. Walk-forward
é sequencial e nunca revisita essa janela — por isso o mesmo modelo "trava"
(quase não sinaliza) no período real 2023-2026.

`SOLUSDT/R3` é diferente: confirmação CPCV com edge saudável (+27,08bps, 918
trades, viés de seleção BAIXO, +0,185) e sinaliza em TODOS os 12 trimestres
reais — mas ainda assim tem edge agregado negativo (-17 a -33bps), o mesmo
achado geral desta ADR (CPCV não prevê o real), não um problema específico
do par.

**Fator adicional, não a causa principal:** SOL/XRP têm ~2 anos a menos de
histórico nesta pipeline que BTC — menos folds totais (12 vs. 19), mas isso
sozinho não explica o "quase zero sinal" de `R2`.

---

## 6. Fase 5 — Stability matrix (cruza Fold × IC/AUC/gain/decile)

Consome o artefato da Fase 4 (os 4 eixos já existem lá), mede DISPERSÃO
entre folds (um IC médio "bom" com desvio-padrão maior que a própria média
é ruído, não sinal estável) e frequência de top-feature-por-gain (a mesma
feature domina todo fold, ou o ranking muda?). Só folds NÃO-degenerados
entram — por isso `n` (folds com IC computável) é às vezes 0 ou 1 mesmo
quando "usados" (Fase 4) é maior: o IC por fold exige variância suficiente
DENTRO do fold, uma exigência a mais além de ter ≥10 trades.

### 6.1 Como ler uma linha desta tabela — exemplo real, `SOLUSDT/R3/C1/short` (177,12bps)

**NÃO é** "treinar só com `A04_log_return_12` dá 177bps" — o modelo usa as
36 features de sempre. O `Q10-Q1` é o SPREAD DE RETORNO entre o decil de
MAIOR confiança e o decil de MENOR confiança do modelo COMPLETO, medido em 2
dos 4 trimestres usáveis (folds 4 e 5: 193,99bps e 160,25bps — média
177,12, desvio-padrão 23,86 — os outros 2 folds usáveis não entram: fold 0
não teve nenhum trade *short*, fold 9 teve só 9 trades, abaixo do piso de
10 para o bucketing por decil funcionar).

**"A04_log_return_12 (50%)"** não é "50% do poder preditivo vem dessa
feature" — é a FREQUÊNCIA: das 4 vezes que o lado *short* treinou com gain
disponível, essa feature foi a #1 por gain nativo em 2 delas (50%). Nos
outros 2 folds o #1 foi outra feature (`E05f_time_to_funding_h` no fold 0,
`E16f_global_ls_ratio` no fold 4) — o ranking MUDA fold a fold, não é fixo.

**Por que `n (IC)`=1 e não 4?** IC de Spearman precisa de variação real na
`confidence` dentro do fold para existir. Nos folds 4 e 5, o modelo devolveu
`confidence` praticamente constante para o lado *short* (por isso
`AUC=0,500` exato nos dois — sem poder discriminativo, mas ainda dá para
medir Q10-Q1 pela pequena variação residual). Só no fold 9 a `confidence`
variou o suficiente para o IC existir (0,779) — e é sobre 9 trades só,
amostra minúscula. **Não é CPCV mal calibrado** — esta tabela é WALK-FORWARD
(Fase 4/5), um mecanismo diferente do CPCV que promoveu os candidatos no
ADR-007; a divergência entre os dois é justamente o achado central desta
ADR-008.

### 6.2 Resultado real, 20 linhas (5 combos × 2 camadas × 2 lados)

| Combo | Camada | Lado | n (IC) | IC médio (±dp) | AUC médio (±dp) | Q10-Q1 bps (±dp) | Top feature por gain |
|---|---|---|---:|---|---|---|---|
| `BTCUSDT/R2` | C1 | long | 6 | 0,035 (±0,512) | 0,495 (±0,271) | 39,60 (±46,88) | `E16f_global_ls_ratio` (50%) |
| `BTCUSDT/R2` | C1 | short | 3 | -0,114 (±0,194) | 0,471 (±0,094) | -31,87 (±69,66) | `A04_log_return_12` (62,5%) |
| `BTCUSDT/R2` | C0 | long | 4 | 0,154 (±0,592) | 0,579 (±0,248) | 23,75 (±97,28) | `A04_log_return_12` (42,9%) |
| `BTCUSDT/R2` | C0 | short | 2 | 0,190 (±0,137) | 0,538 (±0,048) | -37,79 (±81,88) | `A04_log_return_12` (57,1%) |
| `SOLUSDT/R2` | C1 | long | 0 | — | — | — | `E16f_global_ls_ratio` (100%) |
| `SOLUSDT/R2` | C1 | short | 0 | — | 0,500 | 94,08 | `E16f_global_ls_ratio` (100%) |
| `SOLUSDT/R2` | C0 | long | 0 | — | — | — | `E16f_global_ls_ratio` (100%) |
| `SOLUSDT/R2` | C0 | short | 0 | — | 0,500 | 94,08 | `E16f_global_ls_ratio` (100%) |
| `SOLUSDT/R3` | C1 | long | 0 | — | 0,500 (±0,000) | 85,84 (±240,75) | `A04_log_return_12` (50%) |
| `SOLUSDT/R3` | C1 | short | 1 | 0,779 | 0,619 (±0,206) | **177,12 (±23,86)** | `A04_log_return_12` (50%) |
| `SOLUSDT/R3` | C0 | long | 0 | — | 0,500 (±0,000) | 31,83 (±136,90) | empate a 3 (33,3%) |
| `SOLUSDT/R3` | C0 | short | 0 | — | 0,500 (±0,000) | -127,57 (±35,04) | empate a 3 (33,3%) |
| `XRPUSDT/R2` | C1 | long | 2 | 0,028 (±0,016) | 0,553 (±0,080) | -106,81 (±81,52) | `A04_log_return_12` (66,7%) |
| `XRPUSDT/R2` | C1 | short | 3 | 0,096 (±0,258) | 0,519 (±0,033) | 124,53 (±173,05) | `A04_log_return_12` (66,7%) |
| `XRPUSDT/R2` | C0 | long | 1 | -0,360 | 0,481 (±0,032) | -55,83 (±155,52) | `A04_log_return_12` (75%) |
| `XRPUSDT/R2` | C0 | short | 2 | -0,232 (±0,109) | 0,439 (±0,057) | 6,98 (±107,43) | `E05f_time_to_funding_h` (100%) |
| `XRPUSDT/R3` | C1 | long | 1 | 0,204 | 0,450 (±0,071) | 12,69 | `A04_log_return_12` (75%) |
| `XRPUSDT/R3` | C1 | short | 1 | 0,143 | 0,504 (±0,006) | 165,36 (±256,87) | `A04_log_return_12` (75%) |
| `XRPUSDT/R3` | C0 | long | 3 | 0,019 (±0,322) | 0,480 (±0,218) | 129,19 (±81,12) | `A19_log_range` (33,3%) |
| `XRPUSDT/R3` | C0 | short | 1 | 0,165 | 0,522 (±0,031) | 28,30 | empate a 6 (16,7%) |

### 6.3 Achado bruto (Fase 5) — quadro mais sério que a Fase 4 sozinha

- **AUC out-of-time perto de 0,50 na maioria dos combos/lados** — às vezes
  exatamente 0,500 com desvio-padrão 0,000 (`SOLUSDT/R3` long/C0 long/C0
  short) — sem poder discriminativo detectável fora da amostra, mesmo nos
  poucos folds que sobraram após filtrar degenerados.
- **Dispersão de IC entre folds tipicamente MAIOR que a própria média** —
  ex. `BTCUSDT/R2` C1 long: IC médio=0,035, desvio-padrão=0,512 (15× a
  média) — assinatura de ruído, não de sinal estável.
- **Gain concentrado em 1-2 features na maioria dos combos** —
  `A04_log_return_12` domina (50-75% do gain) em quase todos;
  `E16f_global_ls_ratio`/`E05f_time_to_funding_h` aparecem repetidamente
  como segunda opção. Pouca diversificação de sinal.

> **Síntese honesta, ainda sem decisão de como agir (nota original do
> painel):** combinando Fase 4 (taxa alta de fold degenerado, poucos trades
> reais) com Fase 5 (AUC≈0,50, IC é ruído, gain concentrado), sob avaliação
> estritamente fora-da-amostra no tempo (walk-forward) não há evidência
> estatística forte de que os 5 candidatos generalizem — quadro bem
> diferente do que embasou a promoção original via CPCV (`n_lifetime
> id=41`, todos com edge positivo). Reportado ao Manager como achado bruto —
> nenhuma decisão sobre os candidatos foi tomada unilateralmente nesta fase.

---

## 7. Fase 6 — Gates codificados (Data/Model/Alpha)

Mesmo padrão já usado em outros pontos do motor (núcleo puro + threshold em
`constants.yaml` + campo no relatório). Definições, na forma JÁ CORRIGIDA
(ver Seção 9 — a forma original, aposentada, é descrita ali para
transparência histórica):

- **Data:** número ABSOLUTO de folds walk-forward usáveis (Seção 5, coluna
  "Usados") deve ser ≥10.
- **Model:** teste-t unicaudal (H0: AUC médio ≤ 0,5) ao nível α=0,05, por
  lado.
- **Alpha:** edge líquido médio > 0,0bps (comparação estrita).

O combo/lado só é aprovado se os 3 gates passarem simultaneamente.

### 7.1 Resultado real, 10 linhas (5 combos × 2 camadas)

| Combo | Camada | Data (usados/piso) | Alpha | Model long (AUC, n folds) | Model short (AUC, n folds) | Veredito |
|---|---|---|---|---|---|---|
| `BTCUSDT/R2` | C1 | FALHA (8/10) | passa (+7,90bps) | FALHA (0,495, n=8) | FALHA (0,471, n=4) | **REPROVADO** |
| `BTCUSDT/R2` | C0 | FALHA (7/10) | passa (+1,35bps) | FALHA (0,579, n=5) | FALHA (0,538, n=4) | **REPROVADO** |
| `SOLUSDT/R2` | C1 | FALHA (1/10) | falha (-57,66bps) | FALHA (nan, n=0) | FALHA (0,500, n=1) | **REPROVADO** |
| `SOLUSDT/R2` | C0 | FALHA (1/10) | falha (-57,66bps) | FALHA (nan, n=0) | FALHA (0,500, n=1) | **REPROVADO** |
| `SOLUSDT/R3` | C1 | FALHA (4/10) | falha (-17,00bps) | FALHA (0,500, n=2) | FALHA (0,619, n=3) | **REPROVADO** |
| `SOLUSDT/R3` | C0 | FALHA (3/10) | falha (-32,82bps) | FALHA (0,500, n=2) | FALHA (0,500, n=2) | **REPROVADO** |
| `XRPUSDT/R2` | C1 | FALHA (6/10) | falha (-28,25bps) | FALHA (0,553, n=3) | FALHA (0,519, n=3) | **REPROVADO** |
| `XRPUSDT/R2` | C0 | FALHA (4/10) | falha (-17,55bps) | FALHA (0,481, n=3) | FALHA (0,439, n=3) | **REPROVADO** |
| `XRPUSDT/R3` | C1 | FALHA (4/10) | falha (-34,54bps) | FALHA (0,450, n=2) | FALHA (0,504, n=3) | **REPROVADO** |
| `XRPUSDT/R3` | C0 | FALHA (6/10) | passa (+26,34bps) | FALHA (0,480, n=4) | FALHA (0,522, n=2) | **REPROVADO** |

> **0 de 10 combo×variant passam os 3 gates simultaneamente** — sob
> thresholds MEDIDOS (`DERIVED`/`LITERATURE`, ver Seção 9), não mais
> arbitrários. O gate Data reprova TODOS os 10 (nenhum atinge 10 folds
> usáveis, teto real=8) — teto do desenho walk-forward atual é
> estruturalmente insuficiente. O gate Model também reprova TODOS sob
> teste-t real (nenhum AUC médio é estatisticamente distinguível de 0,5
> dado o `n` de folds disponível).

---

## 8. Fase 7 — SHAP × gain nativo (concordância de atribuição de feature)

Dependência `shap>=0.49.1` aprovada pelo Manager (única peça sem
reaproveitamento — não existia no repo). `shap.TreeExplainer` (exato, não
amostrado) por fold — custo medido antes de rodar em escala: 0,005s sobre
672 linhas × 36 features, desprezível sobre o treino (0,68s). Gain nativo do
LightGBM mede USO DE SPLIT; SHAP mede CONTRIBUIÇÃO REAL À PREDIÇÃO — podem
discordar sobre qual feature "importa mais", e discordam.

### 8.1 Resultado real, 20 linhas

| Combo | Camada | Lado | Concordância gain×SHAP | Top por Gain | Top por SHAP |
|---|---|---|---:|---|---|
| `BTCUSDT/R2` | C1 | long | 0,62 | `E16f_global_ls_ratio` (50%) | `E16f_global_ls_ratio` (37,5%) |
| `BTCUSDT/R2` | C1 | short | 0,25 | `A04_log_return_12` (62,5%) | `E16f_global_ls_ratio` (50%) |
| `BTCUSDT/R2` | C0 | long | 0,43 | `A04_log_return_12` (42,9%) | `E16f_global_ls_ratio` (57,1%) |
| `BTCUSDT/R2` | C0 | short | 0,43 | `A04_log_return_12` (57,1%) | `E16f_global_ls_ratio` (42,9%) |
| `SOLUSDT/R2` | C1 | long | 1,00 | `E16f_global_ls_ratio` (100%) | `E16f_global_ls_ratio` (100%) |
| `SOLUSDT/R2` | C1 | short | 1,00 | `E16f_global_ls_ratio` (100%) | `E16f_global_ls_ratio` (100%) |
| `SOLUSDT/R2` | C0 | long | 1,00 | `E16f_global_ls_ratio` (100%) | `E16f_global_ls_ratio` (100%) |
| `SOLUSDT/R2` | C0 | short | 1,00 | `E16f_global_ls_ratio` (100%) | `E16f_global_ls_ratio` (100%) |
| `SOLUSDT/R3` | C1 | long | 0,50 | `A04_log_return_12` (50%) | `E05f_time_to_funding_h` (25%) |
| `SOLUSDT/R3` | C1 | short | 0,25 | `A04_log_return_12` (50%) | `E16f_global_ls_ratio` (100%) |
| `SOLUSDT/R3` | C0 | long | **0,00** | `A21_log_dollar_velocity` (33,3%) | `E05f_time_to_funding_h` (66,7%) |
| `SOLUSDT/R3` | C0 | short | 0,33 | `E05f_time_to_funding_h` (33,3%) | `E16f_global_ls_ratio` (100%) |
| `XRPUSDT/R2` | C1 | long | 0,33 | `A04_log_return_12` (66,7%) | `E05f_time_to_funding_h` (83,3%) |
| `XRPUSDT/R2` | C1 | short | 0,33 | `A04_log_return_12` (66,7%) | `E05f_time_to_funding_h` (100%) |
| `XRPUSDT/R2` | C0 | long | 0,25 | `A04_log_return_12` (75%) | `E05f_time_to_funding_h` (100%) |
| `XRPUSDT/R2` | C0 | short | 1,00 | `E05f_time_to_funding_h` (100%) | `E05f_time_to_funding_h` (100%) |
| `XRPUSDT/R3` | C1 | long | **0,00** | `A04_log_return_12` (75%) | `A19_log_range` (50%) |
| `XRPUSDT/R3` | C1 | short | 0,25 | `A04_log_return_12` (75%) | `E16f_global_ls_ratio` (25%) |
| `XRPUSDT/R3` | C0 | long | 0,50 | `A19_log_range` (33,3%) | `A19_log_range` (33,3%) |
| `XRPUSDT/R3` | C0 | short | 0,33 | `B18_engulfing_atr` (16,7%) | `E05f_time_to_funding_h` (50%) |

> **Achado real (Fase 7):** concordância gain×SHAP varia de 0,00 a 1,00
> entre combos/lados — nada perto de um padrão consistente. Em 6 de 20
> linhas o gain nativo e o SHAP apontam features DIFERENTES como #1 (ex.
> `SOLUSDT/R3/C0/long` e `XRPUSDT/R3/C1/long`, concordância 0,00).
> `E05f_time_to_funding_h` aparece como #1 via SHAP em vários combos onde o
> gain nativo aponta `A04_log_return_12` — os dois métodos medem coisas
> diferentes (uso de split vs. contribuição real à predição) e aqui
> divergem sobre qual é o sinal dominante.

### 8.2 "LightGBM está viciado em 2 features?" (pergunta do Manager, respondida com contagem real)

Contando qual feature é #1 nas 20 linhas combo×camada×lado:

- **Por GAIN NATIVO:** `A04_log_return_12` vence em 10/20 (50%) e
  `E16f_global_ls_ratio` em 5/20 (25%) — juntas, **75%** das linhas.
- **Por SHAP:** quadro diferente — `E16f_global_ls_ratio` vence em 11/20
  (55%) e `E05f_time_to_funding_h` em 7/20 (35%) — juntas, **90%**.
  **`A04_log_return_12` nunca vence por SHAP (0/20)**, apesar de dominar o
  gain.

Isso é MAIS informativo que "viciado em 2 features": o gain nativo conta
quantas vezes uma feature é usada para DIVIDIR um nó da árvore —
`A04_log_return_12` divide muito, mas contribui pouco ao valor final da
predição (SHAP nunca a elege). Quem de fato move a predição, segundo SHAP,
é sempre `E16f_global_ls_ratio` (razão long/short) ou
`E05f_time_to_funding_h` (tempo até o funding) — 2 features de
POSICIONAMENTO/CICLO DE FUNDING, não de retorno de preço. Concentração real
existe, mas em features diferentes das que "parecem" dominar pelo gain — e
restrita a só 3 features no total (contra as 36 do vetor completo).

---

## 9. Fase 8 — Cartão final (consolida Fases 0-7)

Um cartão por (combo, camada, lado), com 8 métricas do formato de auditoria
pedido pelo Manager. 6 REAIS extraídas dos artefatos já escritos nas fases
anteriores; 2 ficam `TBD` deliberadamente (regra B23 do projeto: nunca
inventar faixa esperada) — `regime_stability_pct`/`generalization_gap_pct`
nunca foram medidos para estes candidatos em nenhuma fase desta ADR, medir
exigiria retreino real fora do orçamento autorizado. Veredito = AND
codificado dos 3 gates da Fase 6, nunca julgamento manual.

### 9.1 Resultado real, 20 linhas

| Combo | Camada | Lado | AUC | IC | IC/IR | Q10-Q1 bps | OOS folds | Feature stab. | Veredito |
|---|---|---|---:|---:|---:|---:|---|---:|---|
| `BTCUSDT/R2` | C1 | long | 0,495 | 0,035 | 0,068 | 39,60 | 8/19 | 50% | **REPROVADO** |
| `BTCUSDT/R2` | C1 | short | 0,471 | -0,114 | -0,589 | -31,87 | 4/19 | 62% | **REPROVADO** |
| `BTCUSDT/R2` | C0 | long | 0,579 | 0,154 | 0,260 | 23,75 | 5/19 | 43% | **REPROVADO** |
| `BTCUSDT/R2` | C0 | short | 0,538 | 0,190 | 1,387 | -37,79 | 4/19 | 57% | **REPROVADO** |
| `SOLUSDT/R2` | C1 | long | — | — | — | — | 0/12 | 100% | **REPROVADO** |
| `SOLUSDT/R2` | C1 | short | 0,500 | — | — | 94,08 | 1/12 | 100% | **REPROVADO** |
| `SOLUSDT/R2` | C0 | long | — | — | — | — | 0/12 | 100% | **REPROVADO** |
| `SOLUSDT/R2` | C0 | short | 0,500 | — | — | 94,08 | 1/12 | 100% | **REPROVADO** |
| `SOLUSDT/R3` | C1 | long | 0,500 | — | — | 85,84 | 2/12 | 50% | **REPROVADO** |
| `SOLUSDT/R3` | C1 | short | 0,619 | 0,779 | — | 177,12 | 3/12 | 50% | **REPROVADO** |
| `SOLUSDT/R3` | C0 | long | 0,500 | — | — | 31,83 | 2/12 | 33% | **REPROVADO** |
| `SOLUSDT/R3` | C0 | short | 0,500 | — | — | -127,57 | 2/12 | 33% | **REPROVADO** |
| `XRPUSDT/R2` | C1 | long | 0,553 | 0,028 | 1,682 | -106,81 | 3/12 | 67% | **REPROVADO** |
| `XRPUSDT/R2` | C1 | short | 0,519 | 0,096 | 0,372 | 124,53 | 3/12 | 67% | **REPROVADO** |
| `XRPUSDT/R2` | C0 | long | 0,481 | -0,360 | — | -55,83 | 3/12 | 75% | **REPROVADO** |
| `XRPUSDT/R2` | C0 | short | 0,439 | -0,232 | -2,128 | 6,98 | 3/12 | 100% | **REPROVADO** |
| `XRPUSDT/R3` | C1 | long | 0,450 | 0,204 | — | 12,69 | 2/12 | 75% | **REPROVADO** |
| `XRPUSDT/R3` | C1 | short | 0,504 | 0,143 | — | 165,36 | 3/12 | 75% | **REPROVADO** |
| `XRPUSDT/R3` | C0 | long | 0,480 | 0,019 | 0,060 | 129,19 | 4/12 | 33% | **REPROVADO** |
| `XRPUSDT/R3` | C0 | short | 0,522 | 0,165 | — | 28,30 | 2/12 | 17% | **REPROVADO** |

> Coluna "OOS folds" corrigida (auditoria de engenharia, Seção 11) — antes
> lia o total de folds usáveis do COMBO inteiro (mesmo valor nos 2 lados);
> agora lê quantos folds tinham AUC computável PARA AQUELE LADO
> especificamente (ex. `BTCUSDT/R2/C1/short`: 8→4).

> **Achado final (Fase 8) — consolidação real, não estimativa:** **0 de 20**
> linhas (combo×camada×lado) passa os 3 gates simultaneamente (corrigido de
> "1 de 20" — ver Seção 10). Conclusão honesta desta ADR: sob avaliação
> walk-forward estritamente fora-da-amostra no tempo, **nenhum dos 5
> candidatos promovidos em ADR-007 demonstra edge robusto** — cobertura de
> dado insuficiente (muitos folds degenerados, nenhum combo atinge o piso
> de 10 folds usáveis), poder discriminativo indistinguível de moeda
> honesta sob teste-t real, e atribuição de feature instável (gain e SHAP
> frequentemente discordam sobre qual sinal domina). Reportado ao Manager
> como achado consolidado — nenhuma decisão sobre os 5 candidatos foi
> tomada unilateralmente.

---

## 10. Correção pós-Fase-8 — "investigar e medir os thresholds corretamente"

Os 2 thresholds da Fase 6 nasceram `ASSUMED`, explicitamente marcados
"arbitrário por ora" no `source:` original de `constants.yaml` — nenhuma
medição os embasava. Depois do cartão final fechado, o Manager pediu
explicitamente para medi-los contra dado real antes de aceitar o veredito.
Medir contra os **62 fold-lado reais** desta campanha revelou que a FORMA
de cada gate, não só o número escolhido, estava errada.

| Métrica | Valor |
|---|---:|
| Fold-lado medidos | 62 |
| `n_trades` mediana / p25 | 20,5 / 10 |
| SE(AUC\|H0=0,5) por fold | 0,13 – 0,19 |
| Piso Data (novo) | n≥10 folds |
| Gate Model (novo) | teste-t, α=0,05 |
| Combos com ≥10 folds usáveis | 0/10 (máx. real = 8) |

| Eixo | Forma original (aposentada) | Forma corrigida | Motivo medido |
|---|---|---|---|
| **Model** | `AUC_médio ≥ 0,52` (fixo, `ASSUMED`) | teste-t unicaudal, H0: `AUC_médio≤0,5`, α=0,05 (`LITERATURE`) | Hanley-McNeil (1982): `SE(AUC\|H0)` entre 0,13 (mediana `n_trades`=20,5) e 0,19 (p25=10) POR FOLD — 0,52 fica a menos de 1 desvio-padrão de amostragem de UM fold, sem poder estatístico real. |
| **Data** | `n_usados/n_total ≥ 0,5` (fração, `ASSUMED`) | `n_usados ≥ 10` (piso absoluto, `DERIVED`) | Fração penaliza desigual combos com `n_folds_total` diferente (12 vs. 19) para o MESMO requisito real. Piso 10 = mesma ordem de grandeza já adotada no repo em `alpha.MIN_OCCURRENCES_ABOVE_TAU` (a nível de trade — aqui a nível de fold). |

> **Consequência medida, honesta — o achado FICA MAIS FORTE, não é uma
> reversão de sorte:** sob a forma corrigida, **0 de 20** combo×camada×lado
> passa (era "1 de 20" sob o threshold fixo antigo). O único caso que
> passava antes (`XRPUSDT/R3/camada0/short`, AUC=0,522) tinha só `n=2`
> folds computáveis — não sobrevive à exigência de significância
> estatística real. Registrado em `AG-391` (adendo 2026-08-31): o teto de
> folds do desenho walk-forward atual (`initial_train_years=2` + passo
> trimestral, 12-19 folds totais) é estruturalmente insuficiente para o
> piso de 10 — nenhum dos 10 combo×variant chega perto (máximo real = 8).
> Walk-forward real segue como auditoria PÓS-HOC (não gate obrigatório no
> pipeline de promoção) por enquanto, confirmado pelo Manager.

---

## 11. Decisão final — thresholds travados + os 4 achados do AG-392

O Manager delegou explicitamente ("decida sobre os thresholds propostos e
os 4 achados do AG-392") ao Chief Architect, na mesma sessão. Um sweep de
sensibilidade ±50%+ (exigido por regra do projeto para toda constante
classe A antes de travar — 0 trials, reavaliação do mesmo dado já
computado, sem retreino novo) foi rodado contra os 10 combo×variant reais.

### 11.1 Sweep de sensibilidade

| Threshold | Sweep testado | Resultado |
|---|---|---|
| Data (`min_folds`) | 5, 8, 10, 15, 20 | Gate Data isolado: 4/10 (min=5) → 1/10 (min=8) → 0/10 (min≥10). **Veredito composto: 0/10 em TODA a grade.** |
| Model (`significance_level`) | 0,01 / 0,025 / 0,05 / 0,075 / 0,10 | **0/10 combo×variant com sequer 1 lado passando o gate Model, em QUALQUER α testado.** |

> **DECIDIDO:** `alpha_gate_data_min_folds_usados=10` e
> `alpha_gate_model_significance_level=0,05` travados — o veredito é
> insensível à escolha exata do limiar dentro do range plausível, sem
> justificativa para mudar.

### 11.2 Os 4 achados do `AG-392`

| Item | Achado | Decisão |
|---|---|---|
| 1 | Teste-t assume folds i.i.d., mas walk-forward ancorado tem treino sobreposto — direção do efeito não estava medida | **MEDIDO:** autocorrelação lag-1 do AUC entre folds, 5 séries reais — 4/5 NEGATIVAS (média=-0,216). Não sustenta a hipótese de teste anti-conservador. Resolvido, sem correção adicional (amostra pequena, reabrir se campanha maior existir). |
| 2 | Denominadores Data (nível combo) vs. Model (nível lado) desalinhados | Resolvido por decisão — *not-a-bug*, já documentado nos 2 níveis desde a correção de `model_card.py` (Seção 12). |
| 3 | `MIN_OCCURRENCES_ABOVE_TAU=10` reusado sem validação própria para o papel de confiabilidade de Sharpe | **MEDIDO:** |Sharpe| máximo cai monotonicamente com `n` (buckets 10-14: máx=23,0 → 50+: máx=5,5), sem *blow-up* patológico em nenhum bucket ≥10 (contra 47.163,5 em n=2). Piso validado empiricamente também para o papel de Sharpe. |
| 4 | `Metric`/`Unit` (padrão de tipagem do projeto) não adotado nos 5 módulos novos — inconsistência sistêmica | Adiado deliberadamente — refator estrutural sem defeito funcional, backlog de baixa prioridade. |

---

## 12. Auditoria de engenharia (`audit_engineering`) — verificação adversarial

Um workflow com 5 agentes (1 por módulo novo da ADR-008) aplicou 4 lentes de
auditoria (falhas estatísticas, de implementação, tecnológicas, de contrato
negativo) mais pesquisa web crítica sobre as bibliotecas usadas — cada
relatório revisado por um SEGUNDO agente cético independente antes de
qualquer correção ser aplicada. Pedido explícito do Manager: "máxima
criticidade e engenharia".

| Métrica | Valor |
|---|---:|
| Módulos auditados | 5 |
| Achados confirmados (não falsos-positivos) | 6 |
| Achados corrigidos | 6/6 |
| Testes novos | 9 |
| Veredito final muda? | **Não (0/20)** |
| Achados de metodologia mais profundos, registrados em aberto | `AG-392` (Seção 11.2) |

### 12.1 Os 6 achados confirmados e corrigidos

| Módulo | Achado confirmado | Correção aplicada |
|---|---|---|
| `score_quality.py` | Bucketing de decil não-determinístico entre execuções (join do Polars sem ordem garantida + desempate por ordem de chegada) | `.sort([confidence, t0])` antes de devolver, mesmo padrão já usado em `attribution.py` |
| `score_quality.py` | Correlação/AUC computada com n=2 (sempre degenerada em ±1,0/0,0/1,0) — achado real materializado: `n_trades=2, roc_auc=1.0` num fold real | Piso `n≥5`, mesmo já adotado em `monotonic._MIN_OBS_PER_ENV` |
| `walk_forward.py` | `n_train_bars` media linhas dos 2 lados PRÉ-filtro (unidade errada); a população REAL por lado (`n_train_long`/`n_train_short`) já existia internamente e era descartada | Campo renomeado (honesto sobre o que mede) + 2 campos novos lidos de `FoldResult` |
| `walk_forward_gates.py` | Teste-t sem correção de múltiplas comparações, p-valor nem exposto; `std==0,0` aprovava automaticamente (divergia da convenção do módulo-irmão citado como espelho) | `model_gate_p_value`/`apply_fdr_to_model_gates` novos; `std==0,0` agora sempre falha |
| `model_card.py` | `oos_folds_usados` de nível COMBO exibido junto de métricas por LADO — materializado no único candidato que passava a auditoria original (mostrava 6, o `n` real que sustentava o AUC=0,522 era 2) | Lê `n_folds_auc_by_side[side]`, não mais o payload bruto |
| `stability_matrix.py` | `None` (JSON `null` — o serializador `orjson` grava `NaN` como `null`) vazava para um campo tipado `float` sem normalização | `_float_or_nan` novo, aplicado aos 4 campos afetados |

> **Veredito final não muda (0/20), mas fica mais rigoroso e mais
> confiável.** Mecânico limpo, sweep completo: 2811 testes passando (+9
> novos). Re-rodado contra os 10 combo×variant reais — mesma conclusão, mas
> `oos_folds_usados` por lado agora reflete o `n` real (tabela da Seção 9.1
> já está atualizada com a correção). **Nota importante:** o fix de
> `score_quality.py` (piso de amostra, ordenação determinística) só afeta
> PRÓXIMOS retreinos — os artefatos JSON reais em disco foram escritos pelo
> código ANTIGO, não foram retreinados nesta rodada de correção (exigiria
> nova campanha real, fora do escopo de correção de auditoria).

---

## 13. Síntese para o leitor externo

**O que este documento mostra, em uma frase:** 5 combinações símbolo/
resolução foram promovidas à produção canônica por decisão explícita do
Manager mesmo depois de ZERO delas passarem o gate automático de validação
cruzada combinatória (CPCV) do ADR-007; uma auditoria independente
subsequente (ADR-008), usando um mecanismo de validação estruturalmente
diferente e mais rigoroso (walk-forward sequencial, verdadeiramente
fora-da-amostra no tempo), não encontrou evidência estatística de que
nenhuma das 5 generalize — **0 de 20 combinações combo×camada×lado passam
os 3 gates codificados (Data, Model, Alpha) simultaneamente**, mesmo depois
de (a) os thresholds terem sido remedidos a partir de dado real (o achado
FICOU mais forte, não mais fraco), (b) um sweep de sensibilidade ±50%+
confirmar que o veredito é robusto à escolha exata dos limiares, e (c) uma
auditoria de engenharia adversarial confirmar e corrigir 6 defeitos reais de
implementação sem alterar o veredito final.

**O que NÃO este documento afirma:**
- Não afirma que os 5 candidatos são inúteis em qualquer sentido absoluto —
  a maioria mantém edge bruto positivo sob CPCV e mesmo sob produção com
  seed única (Seção 2.2); o que falha é a evidência de generalização
  temporal fora-da-amostra sob o padrão de rigor desta auditoria.
- Não decide, por si só, remover os 5 candidatos da produção — cada
  seção que reporta um achado "bruto" registra explicitamente que nenhuma
  decisão sobre os candidatos foi tomada unilateralmente; o walk-forward
  real permanece como auditoria PÓS-HOC (não gate obrigatório de
  promoção) por decisão confirmada do Manager.
- Não trata "0/20" como resultado definitivo e imutável: o próprio
  documento registra uma limitação estrutural conhecida (nenhum combo
  atinge o piso de 10 folds usáveis; o teto real do desenho atual é 8) e 2
  campos (`regime_stability_pct`/`generalization_gap_pct`) deliberadamente
  não medidos (`TBD`), por exigirem retreino fora do orçamento já
  autorizado.

**Pontos ainda em aberto, registrados explicitamente para quem for auditar
mais a fundo** (não escondidos, listados aqui para facilitar o trabalho de
quem continuar):
- `AG-391` (aberto): o pipeline de promoção do ADR-007 não inclui
  walk-forward real fora-da-amostra antes de promover — os mesmos 5
  candidatos promovidos não sobrevivem ao gate duplo desta auditoria. 2
  decisões seguem pendentes do Manager: se walk-forward vira gate
  obrigatório de promoção, e se o desenho atual (12-19 folds totais) deve
  ser estendido para atingir o piso de 10 folds usáveis.
- `AG-392` item 4 (adiado deliberadamente): os 5 módulos novos desta ADR
  não adotam o padrão de tipagem `Metric`/`Unit` já usado em outras partes
  do motor — inconsistência sistêmica, sem defeito funcional, backlog de
  baixa prioridade.
- `AG-393` (aberto, ver Seção 15): gap de dado real em `BTCUSDT/R2` (2022)
  ainda não corrigido; bug de calibrador isotônico colapsando para
  constante em `SOLUSDT/R2` ainda não corrigido. Nenhum dos dois muda
  "0/20", mas ambos precisam de ação de código/dado, não só de texto.

---

## 14. Referências e proveniência

| Fonte | Papel |
|---|---|
| `docs/ADR-007_medicao_producao_hiperparametro_optuna_15_combos_2026-08-30.md` | Origem dos 5 candidatos — campanha de busca/confirmação Optuna, gate duplo, ZERO/6 combos aprovados automaticamente. |
| `docs/ADR-008_auditoria_ml_alpha_institucional_score_quality_walkforward_2026-08-31.md` | Documento-fonte desta auditoria — Contexto/Decisão/Options/Consequences/Action Items completos das 9 fases. |
| Artefato "ADR-007 — Painel de Execução" (abas "Run Canônico — 5 Candidatos" e "ADR-008 — Fases 0-8") | Fonte direta de todas as tabelas numéricas transcritas neste documento. |
| `config/constants.yaml::alpha_production_hyperparam_override` | Registro formal da decisão de promoção dos 5 candidatos (Seção 1.4) — inclui critério por combo e timestamps de origem. |
| `config/constants.yaml::alpha_gate_data_min_folds_usados` / `alpha_gate_model_significance_level` | Constantes travadas dos 2 gates corrigidos (Seções 10-11). |
| `audit/architecture_gaps_log.yaml` (`AG-391`, `AG-392`, `AG-393`) | Furos de arquitetura/metodologia registrados por esta auditoria, com status de resolução. |
| `audit/n_lifetime.yaml` (`id=38` a `id=42`) | Orçamento de trials/retreinos gasto nas campanhas do ADR-007 e ADR-008. |
| `experiments/alpha_walk_forward_{symbol}_{resolution_id}.json` (5 arquivos) | Artefatos brutos da campanha walk-forward real (Fase 4) — fonte de todas as tabelas das Seções 5-9. |
| Commit `e812ab1` | Auditoria de engenharia adversarial (Seção 12) — 6 correções aplicadas. |
| Workflow adversarial `wf_84bd452c-67a` (2026-08-31) | Auditoria adversarial do RESULTADO desta ADR (Seção 15) — 6 investigadores + segundo revisor cético cada. |

---

## 15. Adendo — Auditoria adversarial do RESULTADO (pós-publicação, 2026-08-31)

Depois da publicação inicial deste documento, o Manager pediu uma segunda
camada de auditoria — não sobre a qualidade do CÓDIGO que produziu "0/20"
(isso já tinha sido feito, Seção 12), mas sobre se a própria CONCLUSÃO
estatística é confiável. Um workflow com **6 investigadores independentes**
tentou ativamente REFUTAR "0/20, nenhum dos 5 candidatos sobrevive",
cobrindo Fase 4 (mecânica do walk-forward), Fase 5 (stability matrix), Fase
6 (gates) e a decisão final — cada achado revisado por um **segundo agente
cético independente** antes de aceito, mesmo padrão de dupla verificação já
usado na Seção 12.

### 15.1 Os 6 ângulos testados

| # | Ângulo | O que tentou refutar | Veredito |
|---|---|---|---|
| 1 | Vazamento temporal (*purge*) | Purge por `t1`, causalidade das 36 features do vetor T1, isolamento do calibrador/`tau` entre treino e teste | **Sustenta.** Purge reproduzido fold a fold fora do código auditado, bate exatamente. Nenhuma feature não-causal encontrada. Único ponto fraco identificado (hiperparâmetro selecionado sob CPCV com visibilidade da própria janela de teste) empurra a favor de aprovação, não de reprovação — logo reprovar mesmo assim é achado *mais* forte, não mais fraco. |
| 2 | Viés de sobrevivência (exclusão de fold degenerado) | Recalcular o agregado sem excluir os folds com poucos trades | **Sustenta**, por um mecanismo diferente do hipotetizado: excluir folds degenerados é **conservador** (esconde edge, nunca infla) — incluí-los todos inverteria o sinal em 4 dos 10 combos. Mesmo assim "0/20" sobrevive porque o gate Model (não o Data) reprova as 20 células sob qualquer convenção de agregação testada — p-valor mínimo 0,062 mesmo no cenário mais favorável possível aos candidatos. |
| 3 | AUC out-of-time ≈ 0,50 | Inversão de sinal/rótulo entre `y_true` e `y_score` | **Sustenta.** Sem inversão em nenhuma das 3 camadas de código verificadas (rótulo, decisão de lado, agregação). Achado colateral: quase metade dos AUCs (38/76) são exatamente 0,500 porque o score do modelo colapsou para um valor constante nesses folds — não é "sem sinal medido", é "sem sinal *possível* de medir" ali. Irrelevante para o veredito: o gate Data (máximo real de 8 folds usáveis, piso é 10) já reprova as 20 linhas por conta própria, independente de qualquer valor de AUC. |
| 4 | Divergência CPCV vs. walk-forward | Se o viés de seleção (*winner's curse*) explica por que o CPCV via edge positivo e o walk-forward real não | **Sustenta o veredito, mas corrige uma explicação já publicada** — ver Seção 15.2. |
| 5 | Integridade de dado na janela de teste (2023-2026) | Gaps/nulos em features explicando sinais ausentes | **Sustenta na janela original pedida**, mas achou um problema real fora dela — ver Seção 15.2. |
| 6 | Recomputo independente do "0/20" | Reimplementar os 3 gates do zero, sem importar nenhum código já auditado, e comparar | **Sustenta, célula por célula, inclusive sob o cenário mais permissivo possível** (incluindo todos os folds degenerados no agregado). O resultado é **sobredeterminado**: o gate Data e o gate Model, cada um sozinho, já reprovam as 20 linhas — não é preciso os dois concordarem para chegar em "0/20". |

**Síntese do painel:** nenhum dos 6 ângulos encontrou um defeito que revertesse ou enfraquecesse "0/20, nenhum dos 5 candidatos sobrevive". A conclusão da ADR-008 é robusta a esta segunda camada de ceticismo.

### 15.2 Três achados novos e reais (não estavam na ADR-008 original) — registrados em `AG-393`

1. **`BTCUSDT/R2` tem um bug real de qualidade de dado em 2022, ainda não corrigido.** Um bloco de coluna nula em `data/capacity/metrics/BTCUSDT` (banda de tamanho de arquivo cai de ~15,8KB para ~9-11KB por cerca de 4 meses, mesmo padrão nos 4 símbolos, schema de parquet idêntico — assinatura de coluna nula, não de dia de coleta faltando) degrada, via um filtro de exclusão já existente no motor (barra sai da população de teste se qualquer uma das 36 features do vetor T1 for nula), 4 dos 19 folds de teste desse combo especificamente — o único dos 5 candidatos cuja janela de walk-forward alcança 2022 (os outros 4 começam em outubro de 2023, com população de teste saudável em 100% dos folds). **Não muda "0/20" hoje** (mesmo recuperando os 4 folds, os gates Model/Alpha continuariam improváveis para este combo) — mas o gate Data de `BTCUSDT/R2` (hoje 7-8 de 10 folds usáveis, o mais próximo do piso entre os 5 candidatos) não é uma medição definitiva até esse dado ser corrigido e a campanha ser re-rodada.

2. **A explicação publicada para a divergência de `SOLUSDT/R2` citava o hiperparâmetro errado — já corrigido na Seção 5.5 acima.** O texto original (e o painel ao vivo, no momento da publicação inicial deste documento) atribuía a queda de sinal do walk-forward ao viés de seleção "recorde do projeto" (+8,356) medido no Item 2 do ADR-007 — mas esse não é o candidato que foi promovido nem testado no walk-forward real. O candidato efetivamente usado tem viés de seleção de apenas +0,357, uma ordem de grandeza menor, e ainda assim mostra a maior divergência CPCV-vs-walk-forward dos 5 candidatos. Recomputando com o artefato CPCV canônico correto, a divergência não tem correlação mensurável com o viés de seleção em **nenhum** dos 5 candidatos (Spearman ≈0,10-0,40, não significativo, n=5) — a pergunta "por que CPCV diverge do real" segue genuinamente em aberto para todos os 5, não só para 4 como o ADR-008 original supunha.

3. **Bug de pipeline real e ainda não corrigido: o calibrador isotônico de `SOLUSDT/R2` colapsa para uma saída constante em pelo menos 1 fold real.** No fold de teste do 3º trimestre de 2024 (lado *short*), Camada0 e Camada1 produzem `score_quality` byte-idêntico (Brier, log-loss, PR-AUC, perfil de decil — tudo igual a 16 dígitos significativos) apesar de terem boosters diferentes com gain real e distinto — só é possível se as duas calibradoras isotônicas colapsarem para a mesma constante (mesmos rótulos/linhas de treino entre as camadas, só as features mudam). Consistente com "zero sinal" nesse fold específico (não resgata o candidato), mas é um defeito de pipeline distinto do já corrigido em `score_quality.py` (piso de amostra n≥5) e ainda não corrigido.

**Nenhum dos 3 achados muda "0/20".** O item 2 já foi corrigido no corpo deste documento (Seção 5.5). Os itens 1 e 3 são correções de código/dado, não de texto — registradas em `AG-393`, status ABERTO, nenhuma decisão de correção tomada unilateralmente.

*Fim do documento.*
