# Mapa de refatoração — produção 100% dollar bar (R1) + Parkinson como estimador canônico

> Renomeado de `refactor_gk_canonico.md` em 2026-08-17 (`git mv`, histórico
> preservado). Motivo: o plano antigo nunca passou do "passo 1 de 5" — GK foi
> DECIDIDO (2026-08-12) mas nunca IMPLANTADO em produção (`LabelConfig.
> from_constants()` seguiu default ATRWilder). Agora o Manager decidiu que
> **Parkinson** é o novo estimador canônico (medido sob dollar bar, `AG-036`/
> `AG-065`/`AG-074`) e pediu pra tratar isso JUNTO com a comutação real de
> produção pra grade dollar-bar — os dois planos que nunca saíram do papel
> (`refactor_gk_canonico.md` e `refactor_dollar_bar_canonico.md`) viram um só.
> Este documento reflete o ESTADO REAL do código mapeado em 2026-08-17 (2
> rodadas de investigação independente + revisão `project_assurance` do plano),
> não uma cópia da estrutura antiga.

## Contexto — como chegamos aqui

1. M1 original (grade de tempo, `experiments/volatility_comparison_report.json`,
   commit `2410bc1`) elegeu Garman-Klass. Decisão travada em `constants.yaml`
   2026-08-12 — nunca implantada.
2. M1 remedido sob dollar bar (`AG-065`, `AG-036`, `AG-074`, 2026-08-17,
   `experiments/volatility_dollar_bar_report.json`): **Parkinson bate GK,
   estatisticamente significativo, em 12/15 combinações** (5 símbolos × R1/R2/
   R3, 6 candidatos: RealizedVol/ATRWilder/Parkinson/RogersSatchell/HAR-RV/
   EGARCH-acoplado vs. baseline GK). Empate técnico em 2/15, GK vence sem
   contestação em 1/15 (SOLUSDT×R3).
3. Manager decidiu (2026-08-17, mesma conversa): **Parkinson é o novo
   estimador canônico**, e a migração deve comutar produção real pra grade
   dollar-bar (`resolution_id=R1`, mesma decisão de TF que M3 já travou em
   15m) ao mesmo tempo — não faz sentido implantar Parkinson sob grade de
   tempo, onde ele NÃO venceu (extensão RS/YZ original: GK 10/15, Parkinson
   4/15).
4. `audit/n_lifetime.yaml::counter=63`, acima do orçamento total da V4.1
   (`PRD_V4_1.md:625`, `N_lifetime final = 60`) e do critério de encerramento
   §6.5 item 5 ("`N_lifetime` > 60 sem Camada 2 fechada → encerrar"). Manager
   autorizou explicitamente estourar o orçamento pra esta migração
   especificamente (ledger, `type: budget_override_manager`).

## Estado real mapeado (não suponha o que os docs antigos diziam — isto foi verificado linha a linha, 2 rodadas independentes)

### Bloqueadores do `refactor_dollar_bar_canonico.md` — 2 dos 3 já resolvidos

| bloqueador | status real |
|---|---|
| 1 (AG-031, horizonte em relógio fixo) | ✅ implementado — `LabelConfig.time_stop_ms`, `triple_barrier.py:914` |
| 3 (AG-032, purge 2 direções + embargo relógio) | ✅ implementado — `cpcv.py:505-538`, `max_feature_lookback_ms` existe (sem caller de produção ainda) |
| 2 (AG-042, `grade_id`/`resolution_id`) | ⚠️ parcial — ver seção dedicada abaixo, é o item central desta migração |

### Bloqueador 2 — o problema central, desenho corrigido

`CPCVConfig.grade_id` existe, mas `assert_grade_consistent` levanta
`NotImplementedError` pra qualquer `grade_id` fora de `step_ms` (`cpcv.py:
385-409`, confirmado por teste real). O mecanismo atual verifica identidade
de grade comparando a mediana do espaçamento real de `t0` contra
`step_ms(grade_id)` — um conceito de RELÓGIO FIXO que dollar bar não tem por
definição.

**`resolution_id` não existe em NENHUM `DataFrame`** (nem `_DOLLAR_BARS_
COLUMNS` de `schemas.py`, nem labels) — só no sidecar `_calibration.json`,
indexado por símbolo (`DollarBarCalibration`, escrito por `build_dollar_
bars.write_dollar_bars_and_calibration`). Por isso `assert_grade_consistent`/
`generate_splits` precisam ganhar parâmetro `symbol: str` (mudança de
assinatura pública) — sem isso não há como localizar a calibração certa.

**Desenho**: sob `grade_id` dollar-bar, verificar que a calibração existe e
que `threshold_usdt`/`resolution_id` batem com o esperado — nunca comparar
espaçamento de `t0` contra `step_ms` (não aplicável). Sob grade de tempo,
comportamento bit-exato preservado (branch, mesmo padrão já usado em
`Bars.__post_init__`/`ParkinsonEstimator.estimate()`).

**Decisão do Manager sobre `calibration_scope` (2026-08-17,
`AG-042::addendum_decisao_calibration_scope_2026_08_17`)**: aceitar a
calibração `"validation"` já existente (a mesma do M1) como base da
produção real — a regra formal de recalibração (AG-042 item 3) segue em
aberto, mitigada pelo alarme de deriva já implementado (item 2,
`src/monitoring/dollar_bar_drift.py`). `build_dollar_bars.py` continua, por
construção, nunca escrevendo `"frozen_production"` — a aceitação é decisão
de USO, não mudança de código nesse módulo.

### Label Engine (`src/labels/triple_barrier.py`) — nunca ganhou fan-in de dollar bar

- `Bars(frame=bars, timeframe_minutes=tf_minutes)` sempre construído — nenhum
  caminho de código passa `resolution_id=`, mesmo com Parkinson já pronto na
  camada de features (`ParkinsonEstimator` já readaptado, AG-036).
- `source="klines_1m"` hardcoded em `build_labels_for_symbol` (linha 1134),
  sem parâmetro.
- Estimador default: `ATRWilderEstimator` hardcoded (linhas 806-810) — GK
  nunca substituiu isso, apesar de "decidido" desde 12/08.
- `labels_symbol_tf_dir(symbol, version, *, tf="15m")` deriva o path em
  disco da STRING `tf` — **risco real de colisão** se `resolution_id` for
  setado mas `tf` continuar `"15m"` como rótulo remanescente: o path bateria
  com `data/labels/{symbol}/15m/v1/`, onde vivem os labels reais dos 5
  `model_id` já treinados.
- `experiment_log.py` não grava `tf`/`grade_id` no schema — perde
  rastreabilidade de qual grade gerou cada linha.

### Feature Engine (`src/features/`)

- `build_t1_features(..., bar_source: str = "time_15m")` já tem o parâmetro
  pra trocar fonte (`"dollar_r1"` já funciona pra CARREGAR barras) — mas
  `group_c.c01_atr_20`/`c02_atr_20_pct` chamam `support.atr_wilder`
  hardcoded, cegas a qual fonte foi carregada e a qualquer estimador
  configurado.
- `support.parkinson_vol(high, low, window)` só recebe `high`/`low` (sem
  `close`), sai em FRAÇÃO normalizada — diferente de `atr_wilder` (precisa
  `close`, sai em preço ABSOLUTO). `A13_dist_ema48_atr` consome a forma
  absoluta. `parkinson_vol(...) * close` é dimensionalmente correto
  (verificado), mas muda a distribuição numérica REAL de C01/A13 — mudança
  de verdade, não um re-rótulo cosmético.
- `min_common_history_bars_15m` (AG-030) já auto-documentado como gap sob
  `bar_source="dollar_r1"` — densidade de barras/dia varia por símbolo sob
  dollar bar, corte por contagem fixa deixa de garantir comparabilidade
  cross-asset. Mesma constante usada em `regime/classifier.py:104`.
- `registry.yaml` C01/C02 (e A05/A13/E27f, que citam a fórmula no próprio
  texto) precisam de atualização textual — sem detecção automática de drift
  entre código e YAML.

### Regime Engine — precisa de código, não só teste (correção de mapeamento anterior)

- Eixo principal (`vol_state`, R0-R5) NÃO depende de ATR — usa
  `C07_vol_pctile_expanding` (`realized_vol`), já dollar-bar-safe.
- Eixo econômico (`econ_regime`/`cost_atr_ratio`) depende de
  `E27f_cost_atr_ratio` → herda a mudança de C01/C02.
- **Achado real**: `src/regime/build.py::build_regimes` **não tem parâmetro
  de grade nenhum** — chama `build_t1_features(symbol, start, end,
  apply_warmup_mask=False)` sem `bar_source`. Sem adicionar esse parâmetro
  não há NENHUM caminho de código pra computar regime sobre dollar bar.

### Orquestração — peça que faltava no mapeamento original

- `src/models/dataset.py::build_modeling_frame` chama `build_t1_features`/
  `build_regimes` **sem `bar_source`** — mesmo se `tf="R1"` chegasse até
  aqui, o resultado seria labels R1 casados com features/regime 15m,
  incoerente e silencioso.
- `src/models/pipeline.py::run_layer1_sprint` — bug real: parâmetro `tf`
  validado (`step_ms(tf)`) mas nunca repassado a `build_modeling_frame`/
  `generate_splits` — cai sempre no default 15m.
- `src/validation/leakage.py` — 3+ chamadas a `generate_splits`/
  `load_labels_v1` sem `config`/`symbol`/`tf`. É o módulo de produção dos
  "14 testes de vazamento" (`CLAUDE.md`) — precisa parametrização igual.
- `src/backtest/fill_reconciliation.py:205` — `cpcv.generate_splits
  (labels_all)` também sem `symbol`/`config`, mesma classe de bug.

### O que está confirmado FORA do blast radius

- `src/risk/kill_switch.py` — nenhuma referência a ATR/volatilidade.
- `src/live/` — vazio (só docstring), greenfield.
- `src/execution/`/`src/backtest/` (exceto `fill_reconciliation.py:205`
  acima) — zero referência a estimador de volatilidade.
- `src/risk/sizing.py::compute_sizing` — recebe `atr_pct` como parâmetro
  puro, agnóstico de estimador; sem caller de produção hoje.
- `src/analysis/*` (faixa1_5/6/7, faixa2_*, calibration_diagnostics,
  m6_common_factor, cost_surface, etc.) — 10+ arquivos chamam config/splits
  com grade default, mas `analysis/` não pode virar insumo de treino
  (`CLAUDE.md`, `importlinter`) — excluídos deste plano por desenho, não
  por omissão.

## Fases de execução (ver plano completo da sessão pra detalhe fase a fase)

0. Decisão registrada no repo (`AG-036`/`AG-065`/`constants.yaml` — feito,
   este documento faz parte disso) + fundação compartilhada
   (`step_ms`/branch de grade, `assert_grade_consistent` corrigido).
1. Label Engine — `LabelConfig.resolution_id`, `Bars(resolution_id=...)`,
   path de escrita novo com guarda anti-colisão, `experiment_log.py`,
   `barrier_sweep.py`.
2. Feature Engine — `group_c.py` com Parkinson, `bar_source` default,
   `min_common_history_bars_15m` sob dollar bar, `registry.yaml`.
3. Regime Engine — `build_regimes` ganha `bar_source`, `min_common_history_
   bars` mesma decisão do item 2.
4. Orquestração — `dataset.py`, `pipeline.py` (corrige o bug real),
   `validation/leakage.py`, `backtest/fill_reconciliation.py`.
5. `constants.yaml` (`value` finalmente muda) + reprocessamento real +
   retreino (consome `N_lifetime`, autorizado).
6. Docs/governança — este documento, `PLANO_MESTRE_PRINCE2.md`, artefatos
   publicados, ledgers.

## O que NÃO é decidido aqui

- Regra formal de recalibração de threshold (AG-042 item 3) — aceita como
  dívida documentada, não resolvida.
- `R2`/`R3` como grade de decisão de produção — só `R1` (mesma decisão de
  M3, TF=15m↔R1).
- Retreinar Camada 2 (Meta-Model) — fora de escopo desta migração.
