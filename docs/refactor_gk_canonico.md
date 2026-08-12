# Mapa de refatoração — ATRWilder → Garman-Klass como estimador canônico

> Gerado 2026-08-12. Descoberta pura — nenhum arquivo de produção foi alterado
> por este mapeamento. Serve de insumo para uma futura sessão de engenharia
> de refatoração decidir ORDEM e ESCOPO, não é a refatoração em si.

## Contexto

M1 (PRD_V4_1.md §3.2) escolheu **Garman-Klass** como vencedor entre os 6
candidatos declarados (venceu 9/15 combinações reais, quase empatado com
Parkinson 5/15; ver `experiments/volatility_comparison_report.json`, commit
`2410bc1`). Uma extensão pós-M1 testou Rogers-Satchell/Yang-Zhang contra o
GK e não achou nada melhor (`experiments/volatility_rs_yz_vs_gk_report.json`,
commit `2436b33`). Decisão do Manager, 2026-08-11: **GK é canônico**.

O harness de comparação (`src/analysis/volatility_comparison.py`) já foi
atualizado para refletir isso — GK é o baseline lá. Este documento mapeia o
que MAIS precisa mudar para GK virar o estimador de volatilidade **de
produção** (hoje ainda é ATR de Wilder em todo lugar que importa).

**Achado que muda a leitura do escopo:** já existe um catálogo mecânico de
135 pontos de fan-in para os identificadores ATR (`docs/CODE_DISCOVERY.md`,
Estágio 2 — Volatilidade, linhas 122-223; artefato companheiro
`experiments/code_discovery.json`, `code_version: ddc0362`, 2026-08-09). A
migração já é gate reconhecido do PRD: `G-C0-2 — 135 + 350 pontos de fan_in
migrados` (`PRD_V4_1.md:334`). Esse catálogo é a lista-fonte exaustiva; este
documento é a **síntese de blast radius**, não uma redescoberta.

## Blast radius, ordenado por criticidade

### 1. `src/labels/triple_barrier.py` — CRÍTICO, o Label Engine

`atr_at_t0`/`tp_price`/`sl_price`/`mfe_atr_units` são todos dimensionados
por ATR de Wilder hoje:

- `triple_barrier.py:576-577` — `atr_abs = group_c.c01_atr_20(...)`;
  `atr_pct = group_c.c02_atr_20_pct(atr_abs, close)`.
- `triple_barrier.py:602` — barras sem ATR válido (warmup) são PULADAS do
  label engine inteiro.
- `triple_barrier.py:662-663` — `tp_price`/`sl_price` calculados direto de
  `atr_pct_i × tp_atr_mult`/`sl_atr_mult`.
- `triple_barrier.py:700-709` — `mfe_atr_units` também normalizado por
  `atr_pct_i`.
- `triple_barrier.py:729-730` — persistência final em `labels.parquet`.

**Trocar para GK aqui invalida `data/labels/*/v1/labels.parquet` inteiro —
não é hot-swap, exige reprocessamento completo do histórico.** Também
quebra por design o teste golden `test_atr_wilder_estimator_bate_bit_exato_
com_labels_v1` (`tests/unit/test_features_volatility.py`) — esperado, não
é regressão: esse teste hoje prova que `ATRWilderEstimator` é bit-idêntica
ao que gerou o `labels.parquet` ATUAL (baseado em ATR). Precisa virar um
teste equivalente para GK depois da migração (ou ser aposentado com
justificativa registrada).

### 2. `src/features/build.py` + `src/features/groups/group_c.py`/`group_a.py`/`group_e.py` — Feature Engine

`build.py:142-168` expõe `C01_atr_20`/`C02_atr_20_pct` como colunas T2 e
alimenta 3 features T1 que entram no vetor de treino real:

| Feature | Arquivo:linha | Usa |
|---|---|---|
| `A05_ret_vol_norm_4` | `group_a.py:32-39`, chamada em `build.py:149` | `atr_20_pct` |
| `A13_dist_ema48_atr` | `group_a.py:43-46`, chamada em `build.py:150` | `atr_20_abs` (unidade US$, não %) |
| `E27f_cost_atr_ratio` | `group_e.py:52-56`, chamada em `build.py:152-153` | `atr_20_pct` |

**Achado lateral, não assuma o oposto:** `C06_vol_ratio_12_96`/
`C07_vol_pctile_expanding` (`group_c.py:30-47`) **NÃO usam ATR** — usam
`support.realized_vol` sobre `log_return_1`. O docstring de topo de
`group_c.py` (linhas 3-7) e `docs/CODE_DISCOVERY.md:128` sugerem
acoplamento a C01/C02 que o código não confirma — é imprecisão de
documentação preexistente, não uma dependência real. Confirmado também pelo
próprio PRD (`PRD_V4_1.md:380`): "`vol_state` deriva de `C07`, que é posto
expansivo de `realized_vol(48)`".

### 3. `src/regime/classifier.py` — Regime Engine (eixo econômico, não o eixo de volatilidade)

`_economics_regime` (`classifier.py:259-324`) calcula `econ_regime`/
`cost_atr_ratio` a partir de `E27f_cost_atr_ratio` (item 2), que É derivado
de ATR. **Migrar ATR→GK muda `econ_regime`/`cost_atr_ratio`.**

O eixo `vol_state` (R2/R4 do regime) **NÃO muda** — usa `C07`
(`realized_vol`, item 2). O eixo `trend_state` também não muda — usa
`B07_efficiency_ratio_48`. Confirmado por leitura de `stress.py:123-129`
(`s01_vol_extreme`, mesma base `realized_vol`) e por grep vazio de ATR em
`src/risk/kill_switch.py`.

### 4. `src/labels/barrier_sweep.py` — pesquisa/produção híbrida

Lê `atr_at_t0` já persistido em `labels.parquet` para varrer
`tp_atr_mult`/`sl_atr_mult` sem re-rodar o Label Engine
(`barrier_sweep.py:123`, confirmado por `docs/CODE_DISCOVERY.md:167`). Fica
**obsoleto silenciosamente** se `labels.parquet` for regravado com GK e o
sweep não for re-rodado — sem nenhum erro, só um resultado desatualizado.

### 5. `src/risk/sizing.py::compute_sizing` — pronto, mas sem caller de produção hoje

`stop_pct = sl_atr_mult × atr_pct` (`sizing.py:137`), onde `atr_pct` é
**parâmetro injetado pelo chamador**, não recomputado. Grep confirma:
nenhum caller de produção existe ainda (`src/execution/`/`src/backtest/`
não chamam `compute_sizing`/`compute_sizing_asof` hoje, só
`tests/unit/test_risk_sizing.py`). **Verificar antes de assumir "morto"** —
quando `execution`/`backtest` forem implementados e passarem a chamar isso,
a decisão "o que vira `atr_pct`" (ATR ou GK) precisa estar tomada.

### 6. `src/analysis/faixa2_caminho_b.py`, `faixa2_e2_research.py` — não-produção, mas influenciam `constants.yaml`

Não fazem parte do pipeline real, mas sustentam as decisões atuais de
`tp_atr_mult`/`sl_atr_mult` (via `edge_atr_closed_form` sobre `atr_at_t0`
persistido) que SÃO produção (`constants.yaml`). `faixa2_e2_research.py:118`
tem um achado à parte, não relacionado a esta migração: usa `window=20`
**literal** em vez de `load_constant("atr_window")` (usado corretamente na
linha 119 do mesmo arquivo — inconsistência interna, candidato a
`banned_patterns.py` achado B01-adjacente se alguém for auditar esse
arquivo depois).

### `ATRWilderEstimator` (a classe) — boa notícia, sem acoplamento de produção

Grep exaustivo confirma: os únicos usos de `ATRWilderEstimator` (a classe
Python, não a função `support.atr_wilder`) são `src/features/volatility.py`
(definição), `src/analysis/volatility_comparison.py` (já tratado nesta
sessão), e testes (inclusive o golden do item 1). **A classe em si não tem
blast radius de produção** — o acoplamento real está na FUNÇÃO
`support.atr_wilder`/`group_c.c01_atr_20`, não no wrapper `VolatilityEstimator`
que o M1 usa para comparação. Trocar o `_baseline_estimator()` do harness
de M1 (já feito) não tocou produção nenhuma — foi seguro por construção.

## O que NÃO precisa mudar (confirmado por leitura, não suposição)

- `src/risk/kill_switch.py` — nenhuma referência a ATR.
- `src/regime/classifier.py` eixo `trend_state` (`B07_efficiency_ratio_48`).
- `src/regime/classifier.py`/`stress.py` eixo `vol_state`/`s01_vol_extreme`
  (`realized_vol`, não ATR).
- `config/constants.yaml::atr_window` não tem leitor em `src/risk/`,
  `src/regime/` ou `src/execution/` — só em `src/labels/`, `src/features/`
  (M1) e scripts de análise.

## Ordem sugerida (não é decisão tomada, é ponto de partida)

1. **Decidir formalmente** (registrar em `constants.yaml`/PRD, não só nesta
   conversa): GK substitui ATR em `group_c.c01_atr_20`/`c02_atr_20_pct`, ou
   entra como feature NOVA ao lado das antigas (ambas coexistindo por um
   tempo)? A segunda opção é mais segura (não quebra `labels.parquet`
   existente de imediato) mas duplica manutenção.
2. Se substituição direta: reprocessar `labels/v1/` → `labels/v2/` (ou
   equivalente versionado) com GK, atualizar `triple_barrier.py`,
   aposentar/reescrever o teste golden do item 1, invalidar
   `barrier_sweep.py` até re-rodar.
3. Propagar para `E27f_cost_atr_ratio`/`_economics_regime`/`econ_regime` —
   isso muda rótulos de regime histórico, o que por sua vez pode invalidar
   modelos/backtests já treinados sobre o regime antigo. Precisa de gate
   próprio antes de reabrir Camada 2/3.
4. `A05`/`A13` (Grupo A) mudam de valor mas não de definição estrutural —
   menor risco, mas ainda precisa retreinar qualquer modelo que já
   consumiu essas colunas.

Nenhum destes passos foi executado nesta sessão — é mapa, não implementação.
