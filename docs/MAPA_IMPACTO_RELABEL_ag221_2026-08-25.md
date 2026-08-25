# Mapa de impacto — relabel sob `entry_fill_source = agg_trades` (AG-221)

**Data:** 2026-08-25 · **Status:** MAPA, nenhuma execução
**Origem:** autorização do Manager — *"medir 3 combinações antes de relabel
completo, e mapear quais arquivos sofrem esse impacto do novo output para
consumi-los corretamente dentro da cadeia de produção"*

---

## §0. O que muda no output

O schema de `labels.parquet` **não muda**. Mudam os **valores** de:
`t_entry`, `entry_price_fill`, `barrier_hit`, `t1`, `ret_gross`,
`cost_exit_bps`, `ret_net`, `n_bars_held`, `concurrency`, `uniqueness`,
`sample_weight` e **`config_hash`**.

Magnitude medida (4 combinações, 200 dias, amostragem por dia):

| combinação | P(TP) base → novo | `ret_gross` base → novo | Δ | NOFILL novo |
|---|---|---|---|---|
| BTCUSDT/R1 | 0,4541 → 0,4935 | −3,88 → −0,71 bps | **+3,17** | 2,23 % |
| XRPUSDT/R1 | 0,4469 → 0,4895 | −8,52 → −3,60 bps | **+4,92** | 1,19 % |
| BTCUSDT/R3 | 0,4749 → 0,4964 | −4,18 → −0,97 bps | **+3,21** | 1,89 % |
| XRPUSDT/R3 | 0,4666 → 0,4965 | −9,23 → −1,77 bps | **+7,46** | 1,17 % |

As quatro convergem para `P(TP) ≈ 0,49–0,50`, o valor teórico de martingale
sob payoff simétrico. `P(TIME)` permanece `~0,0001–0,002` em todas.

---

## §1. Camada 1 — protegido por `config_hash` (falha ALTA, desejável)

`LabelConfig.config_hash` já inclui `barrier_fill_policy_id` (criado em
`AG-205`). Um campo novo `entry_fill_source` entra no mesmo dict e o hash
muda — **é o comportamento correto** (B15).

| consumidor | proteção |
|---|---|
| `src/models/dataset.py::build_modeling_frame` (linha 315) | `verify_config_hash` → `ConfigHashMismatchError` |

Isso protege **toda a cadeia de treino**: `build_modeling_frame` → CPCV →
`alpha.run_all_folds` → `predictions.parquet` → `backtest_lite` →
baselines → relatório.

**Uma linha protege a cadeia inteira.** Nada a fazer aqui além de garantir
que `entry_fill_source` entre no dict de hash.

---

## §2. Camada 2 — consumidores SEM proteção (silenciosos) ⚠️

**`verify_config_hash` é chamado em UM ÚNICO ponto de produção.** Todo
módulo abaixo lê `labels.parquet` direto e **não verifica hash nenhum** —
sob relabel, cada um consome dado novo com premissas antigas, sem erro.

| módulo | risco sob relabel |
|---|---|
| `src/analysis/feasibility.py` | **Gate 0** — decisão de viabilidade |
| `src/analysis/cost_surface.py` | superfície de custo |
| `src/analysis/attribution.py` | atribuição de PnL |
| `src/analysis/calibration_diagnostics.py` | calibração |
| `src/analysis/faixa1_5_prerequisites.py` | pré-requisitos / `tau` |
| `src/analysis/faixa2_caminho_b.py` | caminho B |
| `src/analysis/gate_efficiency.py` | eficiência de gate |
| `src/analysis/m4_critical_windows.py` | janelas críticas |
| `src/analysis/m4_regime_comparison.py` | comparação de regime |
| `src/analysis/m6_common_factor_hypothesis.py` | **fator comum / `I²`** |
| `src/analysis/s1_tp_sl_sensitivity.py` | sweep TP/SL |
| `src/analysis/volatility_comparison.py` | comparação de vol |
| `src/backtest/fill_reconciliation.py` | reconciliação de fill |

**Ação recomendada antes do relabel:** estender `verify_config_hash` a
estes 13 pontos, ou centralizar o carregamento num único loader que
verifique. Sem isso, o relabel produz números novos consumidos por lógica
calibrada no regime antigo, sem nenhum sinal de erro.

---

## §3. Camada 3 — artefatos em disco a regenerar

| artefato | escopo |
|---|---|
| `data/labels/{5 símbolos}/{R1,R2,R3}/v1/labels.parquet` | 15 arquivos |
| `data/label_engine_runs/label_engine_runs.parquet` | append (histórico preservado) |
| `predictions/**/predictions.parquet` | todos |
| `models/**/diagnostics/*.json` | ~30 versionados no git |
| `experiments/*.json` | **83 arquivos** |

`experiments/` é o maior volume e o mais perigoso: são resultados datados,
sem `config_hash` embutido, que continuam legíveis e plausíveis depois do
relabel. Precisam ser **movidos para um sufixo de regime** (ex.
`_pre_ag221`) em vez de sobrescritos, para que nenhuma comparação cruze
regimes silenciosamente. Ver `AG-218` — o repo já tem um caso real de
artefato de `experiments/` sendo lido como se fosse de outra combinação.

---

## §4. Camada 4 — constantes DERIVADAS de labels ⚠️ ACHADO NOVO

Constantes cujo valor foi **medido a partir de `labels.parquet`** e que,
portanto, ficam obsoletas com o relabel.

### `round_trip_cost_bps_maker_prob = 0,4206` — **já obsoleta hoje**

`provenance: MEASURED`, e a própria fonte declara:

> *"Ruína do apostador (**`tp_atr_mult=2.0`**/`sl_atr_mult=1.5`) prevê
> P(TP primeiro) = 1,5/3,5 = 42,9% analítico; medição empírica real (…)
> confirma 42,06% pooled"*

Mas `tp_atr_mult` foi alterado para **1,5** em 2026-08-24 (sweep S1). Com
`tp = sl = 1,5` a ruína do apostador prevê **50%**, não 42,9% — e os labels
R1 atuais medem `P(TP) = 0,4541` (`0,4935` corrigido por `AG-221`).

**A constante foi medida sob uma geometria de barreira que não existe
mais.** É `MEASURED`, o que a faz parecer confiável — o pior tipo de erro
de proveniência. Registrado como `AG-222`.

**7 call sites**, três deles críticos:

| call site | criticidade |
|---|---|
| `src/features/groups/group_e.py::round_trip_cost_bps` | **feature `E27f_cost_atr_ratio`, no vetor T1 de treino** |
| `src/analysis/feasibility.py` | **Gate 0** |
| `src/risk/limits.py` | **controle de risco de produção** |
| `src/analysis/cost_surface.py` | análise |
| `src/analysis/volatility_operational_effect.py` | análise |
| `src/analysis/m3_timeframe_choice.py` | análise |
| `src/analysis/s1_tp_sl_sensitivity.py` | análise |

**Não há circularidade direta** — verificado: o Label Engine usa
`maker_fee`/`taker_fee` por desfecho, nunca esta constante. Mas existe uma
dependência de mão única que precisa ser atualizada em conjunto:

```
labels.parquet ──medido──> round_trip_cost_bps_maker_prob
                                    │
                                    ├──> E27f_cost_atr_ratio (feature T1) ──> treino do Alpha
                                    ├──> feasibility (Gate 0)
                                    └──> risk/limits (produção)
```

Impacto quantitativo em `round_trip_cost_bps = maker + p·maker + (1−p)·taker`:

| `p` | custo | fonte |
|---|---|---|
| 0,4206 | 5,738 bps | constante atual (geometria tp=2,0, extinta) |
| 0,4541 | 5,638 bps | labels atuais (tp=1,5, `mark_1m`) |
| 0,4935 | 5,520 bps | corrigido (`AG-221`) |

Superestimação atual: **0,218 bps**. Pequena em magnitude — mas está numa
feature de treino, no Gate 0 e no risco de produção, e o selo `MEASURED`
esconde que a medição é de outro regime.

---

## §5. Camada 5 — números registrados em governança

Ficam obsoletos, mas **não devem ser editados** (append-only):

| documento | tratamento |
|---|---|
| `audit/evidence_ledger.yaml` (178 entradas) | entrada NOVA marcando o regime; nunca editar as antigas |
| `audit/architecture_gaps_log.yaml` (223) | `addendum_*` nas entradas que citam `ret_net`/edge |
| `audit/n_lifetime.yaml` | decidir se relabel + retreino contam trials |
| `docs/SPRINT_LOG.md` | seção nova |
| `docs/ADR-002` / `ADR-003` | ponteiro de 1 linha: veredito medido em regime pré-`AG-221` |
| `docs/ADR-004` | já revisado (§4.1, §8) |

Atenção específica: **`ADR-003`** (feature set completo, ratificado
2026-08-25) selecionou as *"10 piores combinações"* por `ret_net` médio
lido de `experiments/alpha_deep_analysis_2026-08-24.json` — números do
regime antigo. Com o relabel, **o ranking pode mudar**, e com ele a lista
das 10.

---

## §6. Ordem de execução recomendada

1. **Fechar `AG-222`** — remedir `round_trip_cost_bps_maker_prob` sob a
   geometria vigente. Independe do relabel e corrige um erro que já existe.
2. **Estender `verify_config_hash`** aos 13 pontos da Camada 2. Sem isso o
   relabel é silencioso onde mais importa.
3. **Versionar `experiments/`** com sufixo de regime.
4. **Wiring de `entry_fill_source`** em `LabelConfig` + dict de `config_hash`
   (default `mark_1m`, bit-exato).
5. **Relabel** das 15 combinações → `label_engine_runs` (append).
6. **Remedir** `round_trip_cost_bps_maker_prob` de novo (agora sob o
   regime novo) — é a única constante que precisa de duas passadas.
7. **Retreino** + regeneração de `predictions`/`models`/`experiments`.
8. **Governança**: entrada nova no ledger, addenda nos AGs, ponteiros nos
   ADRs.

Os passos 1–3 são **pré-requisitos** e não dependem da decisão de relabel:
corrigem defeitos que já existem hoje.
