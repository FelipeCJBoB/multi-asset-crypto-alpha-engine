# Contexto do setup — Alpha LightGBM, Motor Quant Multi-Ativo

Documento de resposta ao checklist pedido (2026-08-24) pra dimensionar
`N_trials_per_k` e `sweep_range` de `max_depth`/`num_leaves`. Todo número
abaixo vem de código/config/artefato real do repo, com citação — onde não
foi medido, está marcado `TBD` (nunca inventado, `CLAUDE.md` B23).

---

## 1. O que é `k`

**Número de features T2 incluídas no vetor de treino do Alpha** — nenhuma
das outras opções.

- Não é horizonte de previsão (isso é fixo: barreira tripla com
  `time_stop_bars`, não varia por k).
- Não é top-k ativos (o universo é fixo: 5 ativos — BTC/ETH/SOL/BNB/XRP).
- Não é número de regimes (fixo: k=4, HMM Gaussiano canônico,
  `hmm_gaussian_k4_v1`).
- **É top-k features**, especificamente: hoje o Alpha treina só com 7
  features fixas (`T1_FEATURE_IDS`, `src/features/build.py`). Existem
  mais 62 features T2 já computadas/testadas mas fora do vetor de treino
  (`SUPPORT_FEATURE_IDS`). A pergunta de pesquisa é: qual o maior `k`
  (features T2 promovidas, ordenadas por importância) que ainda passa
  `PBO < 0,30` dentro do CPCV — metodologia do PRD histórico §2.0.1,
  `k ∈ {6, 9, 12, 16, 24}`.

## 2. Objetivo do modelo

**Classificação binária, dois modelos separados por lado** — não é
previsão de retorno, não é ranking cross-sectional, não é previsão de
volatilidade direta.

- `M_long` e `M_short` (LightGBM `objective="binary"`, `src/models/
  alpha.py::fit_side_model`), um por lado, treinados sobre
  sub-populações diferentes.
- `y = 1` sse `barrier_hit == "TP"` (P(TP antes de SL), rótulo de
  barreira tripla) — `y = 0` para SL ou TIME.
- Threshold de decisão (`tau`) fixado IN-FOLD a priori pela taxa de
  sinal orçada (`target_signal_rate = 0,0189`, `constants.yaml`,
  DERIVED de `fee_budget_monthly`) — nunca escolhido por métrica OOS
  (banned pattern B20).
- Existe uma camada Meta downstream (fora do escopo desta ablação —
  `alpha` não pode importar `meta`, `CLAUDE.md` layer hierarchy).

**AUC real medido (pré-calibração), 15 combinações símbolo×resolução,
2026-08-23/24**: média 0,5086, mínimo 0,5050 (BTCUSDT/R2), máximo 0,5131
(XRPUSDT/R3) — `audit/evidence_ledger.yaml::alpha-lightgbm-decomposicao-
pnl-auc-calibracao-2026-08-24`. **Sinal muito fraco e estável em toda a
superfície** (não é 1-2 combinações ruins puxando a média) — isso é o
dado mais importante pra calibrar risco de overfitting de hiperparâmetro.

## 3. Como valida

**CPCV (Combinatorial Purged Cross-Validation)** — não é walk-forward
simples, não é expanding/rolling window de janela única.

- `src/validation/cpcv.py`: `n_groups=6` (partição cronológica, ~1
  ano/grupo), `n_test_groups=2` → `C(6,2) = 15` splits combinatórios,
  `φ = C(5,1) = 5` caminhos completos de reconstrução (round-robin).
- Purge pelo `t1` REAL de cada linha (não margem fixa) + `g_end_
  effective` (AG-032) + embargo de 96,39h medido (`cpcv_embargo_ms`,
  relógio fixo).
- Cada "trial" (1 config de features×hiperparâmetro) = 15 splits × 2
  lados = **30 fits de LightGBM**.
- Dentro do treino de cada split: sub-split de calibração isotônica,
  holdout `alpha_calibration_holdout_frac = 0,25` (ASSUMED, convenção
  75/25, nunca varrido — `constants.yaml:1986-1990`).
- Critério de permanência atual (Camada1 vs Camada0): `n_better ≥ 4`
  dos 5 paths de backtest → passa. Limiar empírico, não é constante
  declarada em `constants.yaml` (achado de risco registrado no ledger).

## 4. Quantidade de dados

| item | valor | fonte |
|---|---|---|
| Ativos | 5 (BTC/ETH/SOL/BNB/XRP) | escopo do projeto |
| Resoluções | R1/R2/R3 (dollar-bar, `canonical_bar_type=dollar` — **não** clock-time 15m/30m/1h, AG-042) | `PLANO_MESTRE_PRINCE2.md` §11.5 |
| Combinações símbolo×resolução | 15 | `n_lifetime.yaml` id 18 |
| Período histórico | 2020-01 → 2026-08 (~6,6 anos) | `cpcv.py` docstring |
| Linhas de `labels.parquet` (histórico, regime de barra de RELÓGIO, provavelmente desatualizado p/ dollar-bar) | 462.682 (2 lados) | `cpcv.py:5` |
| Linhas BTCUSDT/R1 (dollar-bar, medido 2026-08-23) | 223.172 barras | achado AG-202 desta sessão |
| Linhas por símbolo/resolução nas outras 14 combinações | **TBD** — não consolidado num único lugar nesta sessão | — |
| Features T1 ativas hoje | 7 | `T1_FEATURE_IDS` |
| Features T2 disponíveis (candidatas à ablação) | 62 | `SUPPORT_FEATURE_IDS` |
| `k` sob teste | 6, 9, 12, 16, 24 | PRD §2.0.1 (metodologia histórica) |

## 5. Como o Optuna está configurado

**Não está.** Confirmado por busca no código-fonte real (`grep "import
optuna|optuna\."` em `src/` → zero arquivos) — apesar de `CLAUDE.md`
citar Optuna como stack obrigatório ("Optuna com orçamento declarado"),
**nunca foi usado de verdade neste repo**. Não há sampler, não há
pruning, não há trials rodados, não há timeout configurado. Todo
hiperparâmetro hoje é valor FIXO lido de `constants.yaml`
(`LGBMHyperparams.from_constants()`).

## 6. Espaço atual do LightGBM (produção)

`config/constants.yaml::alpha_lgbm_*`, carregado por
`src/models/alpha.py::LGBMHyperparams`:

| hiperparâmetro | valor | provenance | `sweep_required` | `sweep_range` declarado |
|---|---|---|---|---|
| `max_depth` | 3 | DERIVED (herdado do XGBoost, ressalva: papel diferente sob leaf-wise) | `false` | — |
| `num_leaves` | 8 (=2^max_depth) | ASSUMED | `true` | `[4, 64]` |
| `n_estimators` | 300 | DERIVED | `false` | — |
| `learning_rate` | 0,03 | DERIVED | `false` | — |
| `subsample` (bagging_fraction) | 0,8 | DERIVED | `false` | — |
| `subsample_freq` (bagging_freq) | 1 | ASSUMED | `true` | `[1, 10]` |
| `feature_fraction` | 1,0 | DERIVED (deliberado — bagging por grupo/Camada 3 não implementado; `<1,0` seria banned pattern B19) | `false` | — |
| `lambda_l2` | 5,0 | DERIVED | `false` | — |
| `lambda_l1` | não declarado (default LightGBM = 0) | — | — | — |

Fixos adicionais (não hiperparâmetros de busca, mas relevantes pro
comportamento do fit): `objective="binary"`, `monotone_constraints`
(restrições de sinal econômico por feature, Camada 1 — `src/models/
monotonic.py`), `scale_pos_weight` (calculado por fold a partir do
desbalanceamento real), `deterministic=True` + `force_row_wise=True`
(exigido junto, doc oficial LightGBM), `n_jobs=-1`.

## 7. Função objetivo (proposta — Optuna ainda não implementado)

Ainda não existe uma função objetivo real rodando. Proposta de desenho
(`docs/t2_t1_promotion_ablation_design_doc_2026-08-24.md` §5.3, ainda
não implementada):

- **Alvo do sampler** (se/quando um sampler for usado): Sharpe OOS
  pooled sobre os `n_backtest_paths` do CPCV (`directional_sharpe`,
  já calculado em `src/models/decomposition.py`).
- **PBO** (Probability of Backtest Overfitting, Bailey et al.) — **não
  implementado** (`src/validation/dsr.py:8`, citação literal: "DSR/PSR/
  PBO ainda não implementados"). Proposto como avaliação PÓS-HOC sobre o
  conjunto de trials já rodados (reusa os `n_backtest_paths` do CPCV como
  substrato CSCV), não como alvo direto do sampler — PBO precisa de
  população de trials pra ser calculado, não é gradiente-amigável
  trial-a-trial.
- **DSR** (Deflated Sharpe Ratio) — implementado (`src/validation/
  dsr.py`), mas hoje só avalia UMA configuração já medida contra
  `N_lifetime` auditado, não integrado a um loop de otimização.
- Métrica de retorno líquido pooled também disponível
  (`ret_net`/decomposição de PnL), mas não é o alvo proposto (Sharpe
  já normaliza por variância, mais robusto no regime de sinal fraco
  medido no item 2).

## 8. Custos de execução

| item | valor | fonte |
|---|---|---|
| Tempo de 1 treino completo (15 splits × 2 variantes Camada1/Camada0) | **~2 min** | `tests/unit/test_models_alpha.py` docstring, medido no Sprint 8 |
| Tempo de 1 trial de hiperparâmetro isolado (15 splits × 1 config, ~30 fits) | **TBD** — não medido isoladamente, só o par completo acima | — |
| Paralelismo dentro de 1 fit | `n_jobs=-1` (todos os cores disponíveis) | `alpha.py`, `LGBMClassifier` |
| `device_type` em produção | `"cuda"` (GPU obrigatória, decisão do Manager, D-18) — mas `deterministic=True` só garante bit-exatidão sob CPU (doc oficial LightGBM), testes/sintético usam `"cpu"` | `alpha.py` docstring |
| RAM/CPU/GPU do ambiente real | **TBD** — não documentado nesta sessão | — |
| Quantos trials rodam em paralelo (infra de execução do sweep) | **TBD** — não existe infra de paralelização de trials ainda; hoje cada retreino roda sequencial | achado desta sessão |

## 9. Tabela de melhores trials por `k`

**Não existe — a ablação T2→T1 ainda não rodou nenhuma vez.** O que
existe hoje é o retreino de 2026-08-23 com `k=7` fixo (T1 atual, sem
variação de `k` nem de hiperparâmetro), 15 combinações símbolo×resolução:

| resultado | valor |
|---|---|
| Combinações testadas | 15 (5 símbolos × R1/R2/R3) |
| Passam gate de permanência (`n_better≥4/5`) | 3/15 (20%) — ETHUSDT/R1, SOLUSDT/R2, SOLUSDT/R3 |
| AUC pré-calibração (média / min / max) | 0,5086 / 0,5050 / 0,5131 |
| Gate de retorno direcional absoluto positivo | **False nas 15, sem exceção** — perda é 63,2% direcional, 38,9% execução |
| Fonte | `audit/evidence_ledger.yaml::alpha-lightgbm-sweep-15-combinacoes-2026-08-23` + `alpha-lightgbm-decomposicao-pnl-auc-calibracao-2026-08-24` |

Isto não é uma tabela de trials de hiperparâmetro — é o único ponto de
dado real disponível hoje (k fixo, hiperparâmetro fixo, sem busca).
