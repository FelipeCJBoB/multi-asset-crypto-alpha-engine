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

### Feature Engine (`src/features/`) — Fase 2 IMPLEMENTADA (2026-08-17)

- `group_c.c01_atr_20_parkinson(high, low, close, window)` nova —
  `support.parkinson_vol(high, low, window) * close`, denormaliza fração
  pra preço absoluto (mesma unidade de `c01_atr_20`/ATR de Wilder,
  confirmado dimensionalmente correto por `project_assurance`). Muda a
  distribuição numérica REAL de C01 (e, por herança, A05/A13/C02/E27f) —
  mudança de verdade, testada em
  `tests/unit/test_features_groups.py::test_c01_atr_20_parkinson_diverge_de_atr_wilder`,
  não um re-rótulo cosmético.
- `compute_t1_features`/`build_t1_features` ganham `vol_estimator_id: str
  | None = None` — `None` (default) preserva ATR de Wilder bit-exato
  (`f"atr_wilder_w{atr_window}"` explícito é equivalente); `f"parkinson_w
  {atr_window}"` troca C01 pra Parkinson. Qualquer outro valor levanta
  `ValueError` — nunca cai num estimador não pedido silenciosamente.
- **Correção ao plano original nesta fase**: o item "`bar_source` default
  muda de `time_15m` pra `dollar_r1`" NÃO foi implementado como escrito —
  flipar o default de `build_t1_features` agora trocaria a fonte de dado
  de TODO caller existente que ainda não passa `bar_source` explicitamente
  (`regime/build.py::build_regimes`, que hoje não tem parâmetro de grade
  nenhum — ver Fase 3 abaixo), silenciosamente, ANTES desses callers
  estarem prontos/testados pra dollar bar. Mesma disciplina de "default
  bit-exato, opt-in explícito" usada em `Bars`/`CPCVConfig`/`LabelConfig`
  nas Fases 0/1 — o flip real de produção (`bar_source`/
  `vol_estimator_id` passados explicitamente por `dataset.py`/
  `pipeline.py`) fica pra Fase 5, depois que Regime Engine (Fase 3) e
  orquestração (Fase 4) também suportarem a grade nova.
- `min_common_history_bars_15m` (AG-030) — decisão tomada: `build_t1_
  features` desabilita o cap (`windows.min_common_history_bars = None`)
  sempre que `bar_source != "time_15m"`, em vez de herdar silenciosamente
  um número calibrado em contagem de barra de TEMPO. Medir um equivalente
  nativo pra dollar bar é trabalho de medição novo, fora de escopo desta
  migração (aplica decisão já medida, não abre uma nova) — dívida
  registrada, não bloqueia. Mesma constante em `regime/classifier.py:104`
  ainda usa o valor de `constants.yaml` sem branch — ver Fase 3.
- `registry.yaml` C01/C02/A05/A13/E27f atualizados com nota sobre a
  dependência do estimador selecionado.
- Testes novos: `tests/unit/test_features_groups.py` (3) +
  `tests/unit/test_features_build.py` (4) — dimensional, causal, isolamento
  de coluna (Parkinson só muda C01/C02/A05/A13/E27f, mais nenhuma outra),
  `ValueError` em id inválido, e desabilitação do cap sob dollar bar via
  monkeypatch (determinístico, não depende de backfill local).

### Regime Engine — Fase 3 IMPLEMENTADA (2026-08-17)

- Eixo principal (`vol_state`, R0-R5) NÃO depende de ATR — usa
  `C07_vol_pctile_expanding` (`realized_vol`), já dollar-bar-safe.
- Eixo econômico (`econ_regime`/`cost_atr_ratio`) depende de
  `E27f_cost_atr_ratio` → herda a mudança de C01/C02.
- `src/regime/build.py::build_regimes` ganhou `bar_source`/
  `vol_estimator_id`, repassados bit-a-bit pra `build_t1_features` (mesmo
  default `"time_15m"`/`None`, bit-exato) — sem isso não havia NENHUM
  caminho de código pra computar regime sobre dollar bar (achado G3 da
  revisão `project_assurance`, corrigiu a suposição original de "Regime
  não muda").
- `RegimeThresholds.min_common_history_bars` (mesma constante
  compartilhada de AG-030) — mesma decisão da Fase 2: quando `bar_source
  != "time_15m"` E o chamador NÃO passou `thresholds` explícito,
  `build_regimes` desabilita o cap antes de repassar pro classificador.
  Um `thresholds` explícito nunca é sobrescrito.
- Teste de integração (`test_build_regimes_bar_source_dollar_r1_produz_
  saida_sa`) confirma `econ_regime`/`cost_atr_ratio` e as invariantes §4.8
  saem sãs sob a nova fonte (dado real, `data/capacity/dollar_bars_r1/`) +
  3 testes determinísticos via monkeypatch (fiação, desabilitação do cap,
  não-sobrescrita de `thresholds` explícito).
- Achado colateral (não relacionado a esta migração, mesma classe de bug
  de `test_features_build.py::test_warmup_uniforme_todas_nulas_antes_do_
  corte`): `test_build_regimes_distribuicao_historico_completo` tinha
  `assert counts.get("R0", 0) == 2000` obsoleto desde AG-027 (2026-08-15,
  `min_warmup_bars` recalculado por fórmula, valor real 200) — nunca tinha
  sido re-rodado até esta migração tocar o arquivo. Corrigido.

### Orquestração — Fase 4 IMPLEMENTADA (2026-08-17)

- `src/models/dataset.py::build_modeling_frame` ganhou `resolution_id`/
  `vol_estimator_id` — UM parâmetro de grade (`resolution_id`), não
  `bar_source`/`resolution_id` independentes: `bar_source` é DERIVADO de
  `resolution_id` via `_BAR_SOURCE_BY_RESOLUTION` (`{"R1": "dollar_r1"}`,
  fechado — só R1 é produção) e propagado pra `build_t1_features` E
  `build_regimes` ao mesmo tempo que `resolution_id` vai pra `load_labels_
  v1`. Decisão de desenho corrigida em relação ao texto original do plano
  (que sugeria dois parâmetros): dois parâmetros que pudessem divergir
  reintroduziriam a incoerência silenciosa que este item existe pra
  fechar. `resolution_id` fora do mapa levanta `ValueError` explícito.
- `src/models/pipeline.py::run_layer1_sprint` — bug real corrigido: `tf`
  era validado (`step_ms(tf)`) mas nunca repassado a `build_modeling_
  frame`/`generate_splits`, caía sempre no default 15m (sem efeito
  prático até agora — nenhum caller real passava `tf` != `None`/`"15m"`).
  Ganhou `resolution_id`/`vol_estimator_id` também; `path_tf` (destino em
  disco) usa `resolution_id` quando setado MESMO com `tf=None`, pra nunca
  cair no caminho legado plano que colidiria com os 5 `model_id` de
  produção já treinados (mesma guarda de `labels_symbol_tf_dir`, Fase 1).
- `src/validation/leakage.py::run_all_leakage_tests` — ganhou `symbol`/
  `tf`/`resolution_id`; testes 6/7/12 (os que chamam `generate_splits`)
  ganharam `config`/`symbol`. Achado extra: `_test_06_contaminacao_label`
  só capturava `AssertionError`, mas `generate_splits`/`assert_grade_
  consistent` levantam `CPCVError` em divergência de grade — corrigido
  pra capturar os dois, senão escaparia como crash não tratado em vez de
  FAIL reportado.
- `src/backtest/fill_reconciliation.py::reconstruct_fold_to_path_id` —
  ganhou `config`/`symbol` opcionais (mesma classe de bug do item acima,
  achado da varredura final própria — nenhum dos 2 agentes nem a revisão
  PA pegou este). `run_fill_reconciliation` continua BTCUSDT/15m
  hardcoded ponta a ponta (não tem `symbol` nem em `load_labels`/
  `load_predictions`/`load_orders`) — estender esse módulo pra multi-
  símbolo/dollar-bar é trabalho à parte, fora do escopo desta migração;
  os parâmetros novos existem pra um futuro chamador direto.
- Testes novos: 3 em `test_validation_leakage.py`, 1 em
  `test_fill_reconciliation.py`, 3 em `test_models_dataset.py` (fiação +
  `ValueError` de `resolution_id` não mapeado) — todos via monkeypatch/spy
  determinístico, sem depender de backfill local. 2 testes pré-existentes
  em `test_models_dataset.py` (fakes de `load_labels_v1`/`build_t1_
  features`/`build_regimes`) precisaram de assinatura atualizada pros
  kwargs novos — mesma classe de manutenção mecânica das Fases 1-3.

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
