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

✅ **Injeção de estimador implementada (2026-08-12), migração em si NÃO.**
`build_labels`/`build_labels_both_sides`/`build_labels_for_symbol` agora
aceitam `estimator: VolatilityEstimator | None` (default `None` →
`ATRWilderEstimator(window=cfg.atr_window)`, bit-exato ao comportamento
anterior — `group_c.c01_atr_20`/`c02_atr_20_pct` não são mais chamados
daqui, o import de `group_c` foi removido do arquivo). `LabelConfig` ganhou
campo `estimator_id: str` OBRIGATÓRIO (sem default mágico — ver docstring
do módulo sobre por que um default auto-derivado de `atr_window` seria
inseguro sob `dataclasses.replace`), incluído em `config_hash` — **isso
muda o valor do hash mesmo para configs default** (intencional: antes o
hash não tinha como capturar "qual estimador"; `labels/v1/labels.parquet`
existente continua válido como está, só o hash formula mudou pra frente).
`build_labels` valida em runtime que `estimator.estimator_id ==
cfg.estimator_id`, levantando `ValueError` se não bater — fecha o risco de
`config_hash` mentir sobre qual estimador rodou.

Isso fecha a lacuna do item "ATRWilderEstimator (a classe)" abaixo: agora
o ponto de fan-in de maior criticidade (dimensiona `tp_price`/`sl_price`/
`mfe_atr_units`/`atr_at_t0` de produção) É injetável via a interface
`VolatilityEstimator` (T0.1), não mais hardcoded. **O que NÃO foi feito:**
ninguém chamou `build_labels_for_symbol(..., estimator=GarmanKlassEstimator(...))`
de verdade — `labels/v1/labels.parquet` no disco continua gerado por
ATRWilder, sem reprocessamento. O golden test
`test_atr_wilder_estimator_bate_bit_exato_com_labels_v1`
(`tests/unit/test_features_volatility.py`) continua batendo sem alteração
(não testa `build_labels`, reconstrói ATR independentemente e compara
contra o parquet persistido).

**Ainda pendente, não tocado:** `src/labels/experiment_log.py` persiste
`atr_window` como metadado de cada run em
`experiments/label_engine_runs.parquet` (schema Parquet já populado,
dado real acumulado) mas NÃO ganhou uma coluna `estimator_id` — decisão
deliberada de não migrar o schema de um arquivo com histórico real
acumulado sem tratar compatibilidade de leitura das linhas antigas
primeiro (risco de schema mismatch no read-modify-write). Fica como
próximo passo, não escondido.

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

## Ordem sugerida (atualizado 2026-08-12 — passo 0 concluído)

0. ✅ **`triple_barrier.py` aceita `VolatilityEstimator` injetado, default
   preserva comportamento atual bit-exato.** Feito nesta sessão — ver item 1
   acima. Pré-requisito para tudo abaixo; sem isso não dava pra sequer
   EXPERIMENTAR gerar labels com GK sem reescrever o Label Engine.
1. **Decidir formalmente** (registrar em `constants.yaml`/PRD, não só numa
   conversa): GK substitui ATR como produção, ou os dois coexistem por um
   tempo (rodar `build_labels_for_symbol(..., estimator=GarmanKlassEstimator(...),
   config=LabelConfig.from_constants(estimator_id="garman_klass_w20"))`
   pra um período de teste, comparando `labels/v1/` (ATR) vs uma versão
   nova lado a lado, ANTES de promover)?
2. Se promovido: reprocessar todo o histórico real → `labels/v2_gk/` (ou
   equivalente versionado, nunca sobrescrever `labels/v1/` — ele continua
   sendo o registro do que rodou até aqui), aposentar/reescrever o teste
   golden do item 1 pra apontar pro novo parquet, invalidar
   `barrier_sweep.py` até re-rodar sobre o novo `atr_at_t0` (que passaria a
   ser "GK at t0", nome de coluna mantido por compat de schema).
3. Propagar para `E27f_cost_atr_ratio`/`_economics_regime`/`econ_regime` —
   isso muda rótulos de regime histórico, o que por sua vez pode invalidar
   modelos/backtests já treinados sobre o regime antigo. Precisa de gate
   próprio antes de reabrir Camada 2/3.
4. `A05`/`A13` (Grupo A) mudam de valor mas não de definição estrutural —
   menor risco, mas ainda precisa retreinar qualquer modelo que já
   consumiu essas colunas.
5. `src/labels/experiment_log.py` — adicionar `estimator_id` ao schema,
   com plano de migração pras linhas já persistidas em
   `experiments/label_engine_runs.parquet` (ver nota no item 1).

Passo 0 executado nesta sessão. Passos 1-5 continuam pendentes — decisão
de promoção (passo 1) é do Manager, não confundir "dá pra fazer agora" com
"decidido fazer agora".

### Recomendação registrada (2026-08-12, resposta a pergunta direta do Manager)

**Recomendo: sim para "GK é canônico" como fato — não para "reprocessar
agora".** Duas perguntas diferentes que o passo 1 embaralha numa só:

1. **GK é o estimador certo?** Já está decidido e não precisa de mais
   teste lado a lado — M1 (14/15 QLIKE) + a extensão RS/YZ pós-M1 (GK
   segue vencendo 10/15, nenhum candidato novo supera) já são evidência
   robusta, redundante inclusive. Rodar um terceiro teste comparativo só
   pra confirmar de novo seria gastar tempo sem aprender nada novo —
   exatamente o oposto de "pare na primeira camada que funcionar"
   (`CLAUDE.md`, Comportamento esperado).
2. **Reprocessar `labels/` pra `labels/v2_gk/` agora?** Não — adiar até
   **M2 (barra) e M3 (timeframe) fecharem** (`PRD_V4_1.md` §3.2,
   roadmap V41-3). Razão: M2 pode trocar o tipo de barra de decisão
   (tempo → dollar/volume/tick-imbalance) e M3 pode trocar `decision_tf`
   (15m → 30m/1h) — qualquer um dos dois força um NOVO reprocessamento de
   `labels/` independente do estimador de volatilidade escolhido, porque
   muda o que `t0` significa. Reprocessar agora (por causa do GK) e de
   novo depois (por causa de M2/M3, se mudarem) é retrabalho duplicado —
   o próprio passo 3 acima já registra "precisa de gate próprio antes de
   reabrir Camada 2/3", o que já aponta na mesma direção. `PRD_V4_1.md`
   §3.0 também é explícito: "Nenhuma camada abre antes da anterior fechar
   com resultado registrado" — Camada 1 (M1-M6) ainda não fechou (M2, M3,
   M4, M5, M6 pendentes).

**Ação concreta, se aprovada:** registrar `garman_klass_w20` como
`estimator_id` DECIDIDO em `constants.yaml` agora (classe A, `provenance:
MEASURED`, fonte = M1 + extensão RS/YZ) — trava a decisão 1 sem pagar o
custo da decisão 2. O reprocessamento real (passos 2-5 acima) vira item
do roadmap logo após G-C1-1 (M2/M3/M5/M6 emitidos), não antes.
