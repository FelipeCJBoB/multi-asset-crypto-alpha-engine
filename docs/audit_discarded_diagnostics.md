# Auditoria — diagnósticos calculados e descartados (padrão `gain_by_column`)

> Inventário gerado na task A3 (CLAUDE.md, item "Fase A3"). **Só lista, não
> corrige nada aqui** — decisão de corrigir (e em qual ordem) é de outra
> rodada.

## Contexto

`src/models/alpha.py::fit_side_model` calculava `gain_by_column` (gain
bruto do XGBoost por feature) a cada fold × lado, mas só o agregado
(`ConcentrationDiagnostics` → médias em `pipeline.py::run_layer1_sprint`)
sobrevivia — o dict bruto nunca saía de memória. Recuperar isso para uma
investigação custou um retreino completo (~117s). A1/A2 desta task
corrigiram esse caso específico (`models/{model_id}/diagnostics/
fold_{fold_id}_{side_label}.json`, ver `src/models/pipeline.py`).

Esta lista procura o MESMO padrão em outros lugares de `src/`: um valor
calculado DENTRO de uma função que só alimenta um agregado/resumo/gate
booleano e nunca é retornado bruto nem persistido em disco. Levantamento
por amostragem (`src/models/`, `src/regime/`, `src/labels/`,
`src/validation/`, checagem pontual em `src/execution/`, `src/backtest/`),
não exaustivo.

## Achados, por prioridade informal

### 1. `src/models/monotonic.py:49` — `FeatureICResult.ic_by_env` — **ALTA**

Calculado em `compute_ic_by_env` (linha 57, dentro de
`screen_monotone_constraints`, linha 96), chamado por `fit_side_model`
(`src/models/alpha.py:172`) a cada fold × lado. Alimenta `mean_ic`/
`n_consistent_envs`/`constraint` — a decisão da restrição monotônica em si.

`src/models/pipeline.py:380-397` (`monotone_constraints_example_fold0`)
persiste um resumo PARCIAL (`constraint`, `mean_ic`, `n_consistent` — sem
`ic_by_env`, sem `n_envs_with_data`, sem `forced_economic`) e só para o
**fold 0**, de 15 folds × 2 lados = 30 `SideModelResult.monotone` (10
features cada, 6 ambientes por feature) calculados por variante. O IC por
ambiente dos outros 28 side-models nunca é escrito em lugar nenhum.

**Este é o irmão exato do bug que motivou a task A1 — mesmo arquivo
(`alpha.py`), mesmo tipo de dado (diagnóstico por fold × lado calculado
mas nunca persistido bruto). A correção desta rodada (A1/A2) tratou
`gain_by_column` mas deixou `ic_by_env` passar batido.** Recuperação =
retreino completo do CPCV (~117s). Prioridade alta porque é o candidato
mais provável de ser pedido numa próxima investigação (mesma classe de
pergunta que gerou a task A1: "por que a Camada 1 pôs `0` de restrição em
tal feature, ambiente por ambiente?").

### 2. `src/regime/stress.py:449` — `StressResult.triggers` (por bar × trigger) — **MÉDIA-ALTA**

`compute_stress_triggers` (linhas 461-472) calcula o estado
(`TRIGGERED`/`NOT_TRIGGERED`/`NOT_COMPUTABLE`) de cada um dos 10 triggers
de stress, por barra. `classify_regimes` colapsa isso numa lista só com os
`TRIGGERED` (persistida em `regimes.parquet`). A distinção
`NOT_COMPUTABLE` vs `NOT_TRIGGERED` — que a própria docstring do módulo
marca como relevante hoje (S2/S4/S5/S7/S8/S9/S10 estão `NOT_COMPUTABLE`) —
só sobrevive como contagem agregada numa linha de log
(`n_computable_bars_by_trigger`), nunca em arquivo. Recuperação = rerodar
`build_regimes` sobre o histórico completo (~6,6 anos, vetorizado mas não
trivial).

### 3. `src/models/baselines.py` — distribuições nulas brutas (B1) — **MÉDIA**

`B1Result.null_sharpes` (1000 Sharpes por seed, linha 70/141-154) e
`B1PairedVarianceResult.null_replicate_means` (linha 236/283-288), mais os
draws por caminho em `run_b1_per_path`. Todos colapsam em `null_mean`/
`null_p50`/`null_p95`/`percentile_of_alpha` em `pipeline.py:367-369` (e
confirmado em `experiments/alpha_b1_refinement_report.json`) — nenhum
array bruto é escrito. Perde a forma real da distribuição nula
(assimetria/multimodalidade importa para julgar o quão informativo é um
percentil). Recuperação é barata (RNG determinística + sample puro sobre
pool de trades já materializado, segundos, sem retreino) — por isso não é
"alta": é fácil de refazer sob demanda, só não está persistido por
default.

### 4. `src/models/backtest_lite.py:79` — `realize_trades` (tabela de trade por trade) — **MÉDIA**

Junção completa por trade (t0, side_hat, fold_id, path_id, ret_net,
ret_gross, custo/funding bps) construída em `run_layer1_sprint`
(`pipeline.py:309`, variável `realized_c1`). Só alimenta
`backtest_by_path` (agregados — esses SÃO persistidos, ver seção
"descartado" abaixo) e `decomposition.decompose`. A tabela de trade nunca
vai para parquet. Parcialmente reconstruível a partir de
`predictions.parquet` + `labels.parquet` + remapeamento determinístico
fold→path do CPCV — não é caro, só não está instrumentado.

### 5. `src/models/decomposition.py:143-173` — séries de PnL por trade dentro de `decompose()` — **MÉDIA**

`pnl_direcional_series`/`pnl_carry_series`/`pnl_execucao_series` e
`long_carry`/`short_carry` por lado são somados em escalares de
`DecompositionResult` (esses SÃO persistidos em
`experiments/alpha_layer1_report.json`). Composto com o achado #4 — a
tabela de trades de entrada também não é persistida, então reconstruir a
série completa exige refazer os dois passos.

### 6. `src/labels/triple_barrier.py:649-650` — `touch.tie_break_used` por linha — **MÉDIA**

Booleano por linha (`_first_barrier_touch`, ~230k linhas × 2 lados) que
marca se o rótulo foi resolvido pelo heurístico "mais perto do open" (TP e
SL tocados na mesma vela de 1m). Só a contagem agregada `n_tie_break` é
logada (linha 694-701) — nem isso vai para um arquivo de relatório, e o
booleano por linha não é escrito em `labels.parquet`. Investigar se o
tie-break tem viés sistemático para um lado da barreira exige rerodar o
motor de labels inteiro.

### 7. `src/validation/cpcv.py:397` — `summarize_splits` descartado dentro do teste de leakage — **BAIXA**

Chamado dentro de `src/validation/leakage.py:386`
(`_test_06_contaminacao_label`) — só `total_purged`/`total_embargoed`
somados vão para `leakage_report.json` persistido; a tabela por split (15
linhas: grupos de teste/treino, `n_purged`, `n_embargoed` de cada um) é
descartada. Recuperação é trivial (`generate_splits` + `summarize_splits`,
< 1s, sem modelo nenhum) — prioridade baixa só por isso.

## Checados e descartados (já persistidos, não entram na lista)

- `camada1_backtest_by_path`/`camada0_backtest_by_path`
  (`src/models/pipeline.py:350-351`) — `PathBacktestResult` completo (via
  `asdict`) por caminho já vai para `experiments/alpha_layer1_report.json`.
- `gain_by_column`/`concentration.shares` em `alpha.py`/`pipeline.py` — já
  corrigido nesta mesma rodada (A1/A2, ver acima).
- Saída por barra do Regime Engine (`regime`, `regime_raw`, `er_quantile`,
  `vol_pctile`, `bars_in_regime`, `cost_atr_ratio`, `econ_regime`) — tudo
  persistido por barra em `regimes.parquet`.
- `concurrency`/`uniqueness` (`src/labels/weights.py`) — persistidos por
  linha em `labels.parquet`.
- `markout_{h}_bps` por ordem (`src/execution/fill_simulator.py`) —
  persistido por ordem em `orders.parquet`; o resumo de `summarize()` não
  substitui o bruto, só o complementa.
- `_by_path_breakdown` de `src/backtest/fill_reconciliation.py`
  (`GateResult` por caminho × gate, incluindo `DecompositionResult`
  aninhado) — serializado por inteiro via `asdict(report)` no JSON de
  reconciliação.

## Nota de escopo

Levantamento por amostragem, não cobre `src/data/`, `src/features/`,
`src/exchange/`, nem todo `src/risk/`/`src/execution/`/`src/backtest/`
linha a linha — esses não mostraram o padrão nas áreas verificadas, mas
não foram varridos exaustivamente. Se uma auditoria futura for atrás de
mais candidatos, esses diretórios ainda não foram descartados com
confiança alta, só não examinados a fundo aqui.
