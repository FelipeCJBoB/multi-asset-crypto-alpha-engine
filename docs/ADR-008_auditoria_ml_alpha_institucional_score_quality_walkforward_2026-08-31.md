# ADR-008: Camada de auditoria ML/Alpha institucional — qualidade de score, walk-forward real, gates codificados

**Status:** Fases 0-6 concluídas 2026-08-31 (commits `b03109c`..`a821801`,
lista completa nos Action Items) — Fase 4 rodou a campanha real sobre os
5 candidatos (`n_lifetime` id=42) e achou taxa alta de fold degenerado.
Fase 5 (stability matrix) cruzou Fold × {IC, AUC, gain, decile} sobre
esse mesmo artefato e achou um quadro mais sério: AUC out-of-time perto
de 0,5 (sem poder discriminativo real) em quase todos os candidatos,
dispersão de IC entre folds muito maior que a média (ruído, não sinal
estável), e gain concentrado em 1-2 features na maioria dos combos. Fase
6 codificou 3 gates (Data/Model/Alpha) com thresholds `ASSUMED`
(decisão de limiar pendente do Manager) e rodou contra os 5 candidatos:
**0 de 10 combo×variant passam os 3 gates simultaneamente**. Achado
bruto, ainda sem decisão de como agir. Fase 7 aguarda decisão do Manager
(dependência `shap` nova).
**Date:** 2026-08-31
**Deciders:** Manager (Felipe)

## Context

Depois de promover 5 candidatos à produção canônica (`ADR-007`, decisão
explícita do Manager que reabre o gate duplo automático — ver
`config/constants.yaml::alpha_production_hyperparam_override`), o
Manager trouxe uma especificação de auditoria institucional de ML/Alpha
(14 blocos + lista de prioridade 10, formato "Training Run Report" com
IC/Rank IC, walk-forward obrigatório, gates codificados, leakage audit,
SHAP, "cartão" final PASS/FAIL) e pediu validação contra o motor real
antes de decidir o que construir.

Um agente de auditoria (`general-purpose`, investigação completa de
`src/models/`, `src/validation/`, `src/analysis/`) mapeou os 14 blocos
contra código real, com citação de arquivo:linha — não opinião. Achado
central: **a infraestrutura de base já existe, espalhada em módulos
nunca consolidados**. Blocos já robustos: leakage audit (14 testes,
`src/validation/leakage.py`), decile/quantile analysis (2 implementações
independentes, `src/analysis/attribution.py` +
`src/analysis/calibration_diagnostics.py`), regime stratification
(`stratified_by_regime`/`stratified_by_cost_tercile`), auditoria de
trajetória de HPO (Optuna SQLite + `selection_bias_estimate` já medido
em produção real, `ADR-002` mediu +0,772 no pior caso). O gap real é
estreito: **duas classes de métrica nunca calculadas para o SCORE do
modelo** (classificação formal — AUC/PR-AUC/LogLoss/Brier — e IC/Rank
IC/IC IR do score contra retorno, hoje só existente por FEATURE
individual em `src/models/monotonic.py`, propósito diferente apesar da
mesma fórmula), mais walk-forward real nunca ligado ao `alpha.run_fold`
(embora um splitter de janela ancorada REUTILIZÁVEL já exista em
`src/validation/volatility_walkforward.py::generate_anchored_walk_forward_splits`,
hoje usado só para comparação de estimador de volatilidade), mais SHAP
(ausência total — zero import, zero dependência declarada).

Isto também fecha uma lacuna que ficou aberta desde a `ADR-007`: o Item
6 dessa ADR ("walk-forward real") foi registrado como risco residual
explícito, fora de orçamento, "construção de infraestrutura nova, não
'rodar mais'". Esta ADR-008 trata esse mesmo item, agora com a peça
reutilizável identificada — o esforço real é MÉDIO, não ALTO como
`ADR-007` presumia sem ter investigado.

**Restrições que vêm de fora desta ADR** (`CLAUDE.md`, já vigentes):
nenhum threshold numérico novo sem proveniência declarada; retreino real
custa `N_lifetime`, orçamento declarado antes de rodar; nenhuma
dependência nova (SHAP) sem passar pela disciplina de stack do projeto;
reaproveitar primitiva existente é regra, não otimização (mesma lição
de `AG-371`).

## Decision

Adotar **9 fases sequenciadas por dependência**, não pela ordem em que
o consultor listou os 14 blocos — a maioria dos blocos depende de duas
métricas fundamentais (IC do score, classificação formal) que hoje não
existem em lugar nenhum do motor.

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

### Fase 0 — Correção pontual de proveniência

`experiments/alpha_layer1_report_*.json` é o único relatório do projeto
sem `generated_at`/`code_version` — todo outro relatório
(`leakage_report.json`, `faixa1_calibration_diagnostic.json`) já chama
`report_provenance()` (`src/core/provenance.py:39`). Não é feature nova,
é paridade com o padrão já estabelecido.

- Custo: trivial, zero retreino, zero `N_lifetime`.

### Fase 1 — Métricas fundamentais do score

Reaproveita `spearman_ic`/`se_spearman_fisher` (`src/analysis/ic_by_horizon.py:158`,
`src/models/monotonic.py:149-167` — já existem, nunca chamados com o
score do modelo como entrada) e `predictions.parquet`
(`confidence`/`raw_score`/`is_oof` já gravados por observação).
Novo, sem precedente no repo: AUC/PR-AUC/LogLoss/Brier via
`sklearn.metrics` (mesmo padrão que `roc_auc_score` já usado em
`src/models/baselines.py::run_b4_feature_shuffle`).

**Schema novo** — `report["score_quality"]`:

```json
{
  "classification": {
    "roc_auc": float, "pr_auc": float, "log_loss": float,
    "brier_score": float, "computed_on": "oof", "n_obs": int
  },
  "ic": {
    "pearson_ic_mean": float, "spearman_ic_mean": float,
    "spearman_ic_median": float, "spearman_ic_std": float,
    "ic_ir": float, "pct_ic_positive": float, "ic_tstat": float,
    "n_folds": int
  },
  "decile_spread": {
    "q10_mean_ret_bps": float, "q1_mean_ret_bps": float,
    "q10_minus_q1_bps": float
  }
}
```

- Calculado sobre predições OOF já materializadas — **zero retreino,
  zero custo de `N_lifetime`**.
- Tratamento de erro: se um fold não tiver as duas classes presentes
  (AUC indefinida) ou `ess` insuficiente pro erro-padrão de Fisher
  (mesma trava que `se_spearman_fisher` já aplica, `ess<=3` levanta
  `ValueError`), falha alto com mensagem acionável — nunca `NaN`/default
  silencioso (Regra Zero, mesma disciplina do resto do repo).

### Fase 2 — Ganhos paralelos e independentes

Não depende de nada, não trava nada. 4 entregas:

- **Feature audit** (mean/std/percentis por feature) — anexar a
  `src/analysis/feature_null_census.py` (já tem `ColumnNullStats`,
  falta só `df.select(feature_ids).describe()` do polars).
- **Label audit** (N/%positivo-negativo/mean/std/skew/kurtosis/
  percentis do target, autocorrelação, overlap) — novo módulo pequeno
  sobre `labels.parquet`. Overlap em si já é auditado estruturalmente
  (`cpcv.py::assert_no_train_t1_leaks_into_test`) — aqui é só reportar
  a estatística descritiva que falta.
- **Export de trajetória completa do Optuna** — `study.trials_dataframe()`
  (nativo do Optuna, zero lógica nova) → artefato Parquet
  (`experiments/alpha_optuna_trials_{symbol}_{resolution}_{variant}.parquet`).
- **Regime stratification por tempo** (hora/dia-semana/mês/trimestre) —
  extensão de `calibration_diagnostics.py::stratified_by_regime`, mesma
  função, mais um eixo de corte.

- Custo: trivial-baixo, zero retreino, zero `N_lifetime`.

### Fase 3 — Gap fit/stop/calib

Aplica as métricas da Fase 1 aos 3 sub-splits que já existem
(`alpha.py::_temporal_purged_three_way_split`) e reporta o gap
explícito — mesmo padrão que `selection_bias_estimate`
(`hyperparams_optuna.py:846`) já usa pra Sharpe, generalizado.

**Schema novo** — `report["train_val_test_gap"]`: mesma forma de
`score_quality` repetida para `fit`/`stop`/`calib`, mais
`gap_fit_minus_stop` (deltas).

- Custo: baixo, zero retreino (reusa predições já geradas na Fase 1),
  zero `N_lifetime`.

### Fase 4 — Walk-forward real

Fecha o Item 6 da `ADR-007`. `generate_anchored_walk_forward_splits`
(`src/validation/volatility_walkforward.py:61-105`) já produz
`(train_end_idx, test_start_idx, test_end_idx)` sobre janela expansiva
com passo configurável — falta (a) adaptar `alpha.run_fold` pra
consumir esse formato (hoje amarrado a `CPCVSplit`; generalizar a
interface pra aceitar qualquer objeto com `train_idx`/`test_idx`, ou
escrever um adaptador fino), (b) aplicar as métricas de Fase 1+3 por
fold, (c) agregar mean/median/std/min/max entre folds.

**Schema novo** — `experiments/alpha_walk_forward_{symbol}_{resolution}.json`:

```json
{
  "fold_results": [
    {"fold_id": int, "train_start": str, "train_end": str,
     "test_start": str, "test_end": str, "sharpe": float,
     "edge_bps": float, "win_rate": float, "score_quality": {...}}
  ],
  "aggregate": {"mean": {...}, "median": {...}, "std": {...},
                "min": {...}, "max": {...}}
}
```

- **Diferente das Fases 1-3, envolve RETREINO REAL** — cada fold
  ancorado é um treino completo. Custo de `N_lifetime` real.
- **Orçamento não estimado aqui sem medir 1 fold primeiro** (mesma
  disciplina de `AG-371-ADDENDUM-17`/`ADR-007` — nunca comprometer
  tempo total antes de medir uma amostra real).

### Fase 5 — Stability matrix (parcial, sem SHAP)

Cruza Fold × {IC, AUC/LogLoss, feature gain, decile returns} — todos os
eixos exceto SHAP já existem depois da Fase 4. Versão completa só após
a Fase 7.

- Custo: baixo (agregação sobre dado já produzido nas Fases 1/4), zero
  `N_lifetime`.

### Fase 6 — Gates codificados

O PADRÃO já existe no repo — `constants.yaml` com threshold declarado +
função `_passes` + campo no `report`, exatamente como `permanence_pass`/
`edge_gate_pass`/`hhi.gate3_4_passes` já funcionam hoje. O trabalho real
não é código — é **decisão do Manager sobre os limiares**, porque
nenhuma constante nasce sem proveniência (`CLAUDE.md` §Proveniência).
Sem decisão explícita, os 3 gates pedidos (Data/Model/Alpha) entram
como `provenance: ASSUMED` + `sweep_required: true`, mesmo padrão já
usado em `alpha_prune_max_gate_fpr` (`ADR-007`).

- Custo: baixo (código), decisão de threshold pendente do Manager.

### Fase 7 — SHAP

Único bloco sem nenhuma peça reaproveitável — dependência nova (`shap`,
hoje ausente de `pyproject.toml`), `TreeExplainer` sobre os boosters já
persistidos (`persistence.py::write_model_bundle` já salva o booster).
Independente de todas as outras fases — pode entrar em paralelo a
qualquer momento após a Fase 1, mas faz mais sentido depois da Fase 4
("SHAP by fold" só é interessante sobre os folds de walk-forward, não
só CPCV).

- Custo: médio — decisão de dependência nova primeiro (fora do escopo
  desta ADR decidir sozinha, mesma disciplina de qualquer adição de
  stack).

### Fase 8 — Cartão final / model card

Mesmo padrão de `permanence_pass_criterio` (regra codificada, nunca
julgamento manual) — agora cobrindo as 8 métricas-chave do consultor
(Test AUC, Test Rank IC, IC IR, Q10-Q1, OOS folds X/X, feature
stability%, regime stability%, generalization gap%), não só Sharpe
relativo. Depende de todas as fases anteriores.

- Custo: médio, consolidação — sem custo de `N_lifetime` novo.

### Integração com o artefato ao vivo

Cada fase, ao fechar, alimenta a aba "Run Canônico — 5 Candidatos" do
artefato "ADR-007 — Painel de Execução"
(`https://claude.ai/code/artifact/ed42926f-90e2-4acd-bf61-58a9e05d9604`)
— mesmo artefato, não um novo, pra manter a auditoria ponta a ponta dos
5 candidatos já promovidos num único lugar. Republicação incremental
por fase, mesmo padrão já usado em toda a `ADR-007`.

## Options Considered

### Option A: Construir os 14 blocos na ordem do consultor — REJEITADA

O consultor lista walk-forward (bloco 4) antes de qualquer métrica de
IC/classificação (bloco 2). Construir nessa ordem produziria folds de
walk-forward reportando só o que já existe (Sharpe/edge via
`backtest_lite`), sem as métricas que dão à walk-forward seu valor real
("o Rank IC se mantém positivo fold a fold, ou só funcionou numa
janela?"). Rejeitada por gerar retrabalho — teria que voltar e re-rodar
walk-forward depois que a Fase 1 existisse.

### Option B: Só o item de maior prioridade (walk-forward, #2 da lista) — REJEITADA

Mais rápida pra fechar o Item 6 pendente da `ADR-007` isoladamente, mas
ignora que blocos de custo trivial (Fases 0/2) e blocos que DESBLOQUEIAM
o resto (Fase 1) ficam pra depois sem motivo — o orçamento de `N_lifetime`
gasto em walk-forward sem as métricas de Fase 1 prontas produziria um
artefato que precisaria ser refeito.

### Option C (escolhida): 9 fases sequenciadas por dependência, custo trivial primeiro

Fases 0-2 (sem retreino, sem decisão pendente) liberadas imediatamente;
Fase 4 (a única com custo de `N_lifetime` real) só depois da Fase 1
existir, pra que o resultado já saia completo; Fases 6/7 explicitamente
bloqueadas em decisão do Manager (threshold, dependência nova), não
decididas por conta própria.

## Trade-off Analysis

| Decisão | Ganho | Custo/risco | Revisitar quando |
|---|---|---|---|
| Fase 1 antes de tudo | Desbloqueia 6 dos 8 blocos restantes, zero retreino | Nenhum | — |
| Fase 4 só depois da Fase 1 | Walk-forward sai completo (Sharpe + IC + AUC por fold), não em 2 rodadas | Adia o item #2 de prioridade do consultor por N dias | Se quiser walk-forward SÓ com Sharpe/edge (o que já existe hoje) antes das métricas novas, é escolha de sequência, não bloqueio técnico — furar a fila é possível |
| Gates (Fase 6) sem threshold pré-decidido | Não repete o erro já queimado neste projeto (regra sem definição operacional, `AG-114`/`118`/`122`) | Trava até decisão, ou nasce `ASSUMED` (convenção já aceita) | Quando threshold real existir/for decidido |
| SHAP por último | Evita gastar dependência nova antes de saber se o resto já responde à pergunta | Furar a fila é possível se a prioridade for explicabilidade, não descoberta de sinal | Decisão do Manager |
| Mesmo artefato da `ADR-007`, não um novo | Auditoria ponta a ponta num único lugar, sem fragmentar contexto | Artefato cresce — pode precisar de reorganização visual (mais abas) depois da Fase 8 | Se o artefato ficar denso demais pra navegar |

## Consequences

- **Fica mais fácil**: separar "o classificador funciona" de "o sinal
  tem valor econômico" — hoje o motor mede quase só a segunda pergunta
  (Sharpe/edge/win_rate), a Fase 1 fecha a primeira. Interpretar
  qualquer resultado futuro (inclusive os 5 candidatos já promovidos)
  com o gap train/val/test e a robustez por fold explícitos, não só um
  número solto.
- **Fica mais difícil**: obter o cartão final completo rápido — depende
  de 8 fases fechadas, não é uma tarefa de tarde.
- **Precisa ser revisitado**: orçamento real da Fase 4 (só sai depois
  de medir 1 fold, `B23` — nunca inventar faixa esperada); limiares dos
  gates da Fase 6 (Manager decide ou aceita `ASSUMED`); dependência
  `shap` da Fase 7 (aprovação de stack).
- **Achado que já vale registrar**: o gap real do motor não é "falta
  medir robustez" — é 2 classes de métrica nunca calculadas pro score
  final. A maior parte da "auditoria institucional" pedida já roda, só
  nunca foi consolidada num único relatório.

## Action Items

1. [x] Fase 0 — `report_provenance()` em `alpha_layer1_report_*.json` —
   CONCLUÍDO, commit `b03109c`.
2. [x] Fase 1 — `score_quality` (IC/Rank IC/IC IR do score, AUC/PR-AUC/
   LogLoss/Brier, Q10-Q1) no `report` de `run_layer1_sprint` —
   CONCLUÍDO, commit `b03109c`. Módulo vive em `src/models/score_quality.py`
   (não `src/analysis/` — import-linter proíbe `src.models` de importar
   `src.analysis`). 10 testes, zero custo de `N_lifetime`.
3. [x] Fase 2 — CONCLUÍDO, 4/4 itens:
   - `column_distribution_stats` (feature audit, mean/std/percentis) —
     commit `62453b8`.
   - `label_audit.py` (distribuição ternária + binária do target,
     momentos de `ret_net`, autocorrelação lag-1) — commit `5189923`.
   - `export_trial_trajectory` (trajetória completa do Optuna, não só o
     vencedor) — commit `33e8e10`.
   - `stratified_by_time` (hour/day_of_week/month/quarter) — commit
     `5bb5224`.
   29 testes novos no total, zero custo de `N_lifetime`. Sweep completo
   do repo (2.699 testes) — 2.698 verdes, 1 falha pré-existente não
   relacionada (artefato local já modificado antes desta ADR existir).
4. [x] Fase 3 — `train_val_test_gap` sobre `fit`/`stop`/`calib` — commit
   `404a7dd`. `InSampleSegmentScores` (novo) + 3 campos opcionais em
   `SideModelResult` (`fit_segment`/`stop_segment`/`calib_segment`),
   populados em `fit_side_model` sem retreino extra;
   `score_quality.compute_train_val_test_gap` aplica as mesmas fórmulas
   de `compute_score_quality` aos 3 sub-splits, `y_true`=vitória
   econômica (mesma convenção do OOF); `report["train_val_test_gap"]`
   wireado em `pipeline.py`. 11 testes novos (multiset de `ret_net`
   reconstruído a mão, cross-check sklearn, prova explícita da
   convenção `ret_net>0`). Sweep completo (2.745 testes) — 2.742 verdes,
   1 falha pré-existente não relacionada (mesmo artefato local do item
   3), 2 skipped, 2 xfailed — zero regressão.
5. [x] Fase 4 — commits `8df739c`/`f63f6ce`/`095a920`/`60ad4bd`/`d5dd85d`/
   `c836435`. `walk_forward_split_to_cpcv_split` (adaptador fino,
   `WalkForwardSplit`→`CPCVSplit`, purge por `t1`) +
   `run_walk_forward_for_combo` (driver: gera splits ancorados, roda
   `alpha.run_fold` por fold, reusa `backtest_lite.backtest_by_path` +
   `score_quality.compute_score_quality`, agrega mean/median/std/min/max
   sobre folds não-degenerados). Critério operacional de fold degenerado
   definido pelo Manager (2026-08-31): `n_filled_trades <
   alpha.MIN_OCCURRENCES_ABOVE_TAU` (10) — corrigido em campo real depois
   de um primeiro critério (por `n_test_bars`) produzir um Sharpe
   patológico (47.163,5 sobre 2 trades, `SOLUSDT/R2` fold_id=9). 2 bugs
   reais adicionais corrigidos por execução real (não hipotética):
   `mf.data` com 2 linhas/barra não-monótono em `t0`; fold com 0 barras
   de teste válidas quebrando `alpha.run_fold` dentro do `predict_proba`.
   19 testes novos. Medição de 1 fold real: 0,6s — campanha completa
   sobre os 5 candidatos autorizada ("Orçamento = Completo"): 10 runs
   (5 combos × 2 camadas), ~117s de treino + ~100s de IO, zero falha.
   **Achado bruto, sem decisão de como agir**: taxa de fold degenerado
   alta em TODOS os 5 candidatos (`SOLUSDT/R2`=1/12 usável nas 2
   camadas), Sharpe/edge_bps agregados majoritariamente negativos —
   quadro bem diferente do CPCV (`n_lifetime` id=41, todos positivos).
   `n_lifetime` id=42 (delta=5). Artefatos: `experiments/alpha_walk_
   forward_{symbol}_{resolution_id}.json` (5 arquivos).
6. [x] Fase 5 — commits `b3959c7`/`365f104`. `score_quality.compute_
   decile_profile` (perfil completo de 10 decis, não só o spread Q10-Q1)
   + `WalkForwardFoldMetrics.gain_by_column_by_side`/`decile_profile_
   by_side` (Fase 4 já calculava tudo isso internamente, só faltava
   expor) + `src.analysis.stability_matrix.build_stability_matrix`
   (cruza Fold × {IC, AUC/LogLoss, gain, decile}, mede DISPERSÃO entre
   folds e frequência de top-feature-por-gain, não só tabula). 16
   testes novos, zero regressão (2771 testes da suíte completa).
   **Achado real, rodado contra os 5 artefatos regenerados**: AUC
   out-of-time perto de 0,5 (às vezes exatamente 0,500, std=0,000) na
   maioria dos combos/lados — sem poder discriminativo real detectável
   fora da amostra; dispersão de IC entre folds tipicamente MAIOR que a
   própria média (ex. `BTCUSDT/R2` long: mean=0,035 std=0,512) — ruído,
   não sinal estável; gain concentrado em 1-2 features na maioria dos
   combos (`A04_log_return_12` domina em quase todos). Quadro mais
   sério que o "bruto" da Fase 4 — ainda sem decisão de como agir.
7. [x] Fase 6 — commit `a821801`. `src/analysis/walk_forward_gates.py` —
   3 gates (Data/Model/Alpha), mesmo padrão de `backtest_lite.
   permanence_pass_criterion`/`hhi.gate3_4_passes` (núcleo puro +
   threshold em `constants.yaml` + campo no report). **Decisão do
   Manager sobre threshold PENDENTE** — 2 constantes novas entram
   `ASSUMED`+`sweep_required` (`alpha_gate_data_min_frac_folds_usados`=
   0,5; `alpha_gate_model_min_auc`=0,52); o gate Alpha reusa
   `alpha_layer1_permanence_min_edge_bps` (já `DERIVED`). **As
   DEFINIÇÕES dos 3 gates (não só os limiares) também são proposta
   minha na ausência de especificação do Manager sobre o que cada gate
   mede** — documentado como tal na docstring do módulo, sujeito a
   correção. 14 testes novos. Rodado contra os 5 candidatos: **0 de 10
   combo×variant passam os 3 gates simultaneamente** sob os thresholds
   propostos — consistente com os achados brutos das Fases 4/5.
8. [ ] Fase 7 — SHAP — **aguarda aprovação de dependência nova do
   Manager**.
9. [ ] Fase 8 — cartão final / model card, consolidação de 0-7.
10. [ ] Alimentar cada fase concluída na aba "Run Canônico — 5
    Candidatos" do artefato "ADR-007 — Painel de Execução", republicação
    incremental.
11. [ ] `audit/architecture_gaps_log.yaml` — referenciar esta ADR ao
    fechar cada fase, se algum gap novo for descoberto no caminho.
12. [ ] `docs/SPRINT_LOG.md` — nova seção ao fechar a primeira fase real.
