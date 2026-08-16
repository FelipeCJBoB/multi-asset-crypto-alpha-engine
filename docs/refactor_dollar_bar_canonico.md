# Redesenho para grade canônica *dollar bar* — investigação de arquitetura

**Data:** 2026-08-16 · **Tipo:** investigação pura (nenhum arquivo do repo escrito ou editado) · **Gatilho:** `config/constants.yaml::canonical_bar_type = "dollar"` (M2 fechado) + remoção do limitador T1 (`PLANO_MESTRE_PRINCE2.md` v3.5, linhas 1225-1247)

**Método:** varredura sistemática arquivo-a-arquivo de `src/` inteiro (12 pacotes), `config/constants.yaml`, `features/registry.yaml`, `audit/`, os 4 documentos-mestre e o layout real de `data/` em disco. Todo "onde muda" carrega `arquivo:linha`. Nenhum `.py`/`pytest`/`uv run` foi executado; os 2 scripts mecânicos rodados (`check_constants_provenance.py`, `check_constants_referenced.py`) estão na lista autorizada do `CLAUDE.md`. Medições de disco via `du`/`ls` (shell puro). Tudo que exigiria rodar Python está isolado na §7, com comando exato.

**Aviso de proveniência:** nenhuma opção abaixo vem com número inventado. Onde a decisão depende de um número que não existe medido, isso está dito e o comando para medi-lo está na §7.

---

## 0. Resumo executivo — 8 achados que reordenam o escopo

| # | achado | evidência |
|---|---|---|
| **A** | **Nenhuma dollar bar jamais foi construída sobre o histórico completo, de nenhum ativo.** O run canônico de M2 sobre a série inteira produziu **6 de 60 células**, todas `bar_type="time"` (SOL/XRP, só klines) — as 54 restantes ficaram `n_bars: 0`. As 5 janelas de 1 mês que decidiram M2 são a única evidência empírica existente. | `experiments/m2_bar_comparison_report.json` → `"partial": true`, 54/60 células com `"n_bars": 0` |
| **B** | **`canonical_bar_type` não é lido por nenhuma linha de código.** Grep no repo inteiro: só `config/constants.yaml`, `PLANO_MESTRE`, `CLAUDE.md` e docs. Zero `load_constant("canonical_bar_type")`. É registro de decisão puro — exatamente o padrão de `canonical_volatility_estimator`. | `check_constants_referenced.py --src src` → OK com 177 referências, nenhuma delas esta |
| **C** | **Existe um guarda que impede a migração de acontecer pela metade — e ele é uma barreira dura, não um aviso.** `assert_tf_consistent` (`src/validation/cpcv.py:288-304`, chamado incondicionalmente em `:359`) levanta `CPCVError` se a **mediana** do espaçamento de `t0` divergir de `step_ms(tf)` em >5%. Labels em dollar bars **não passam por CPCV nenhum** enquanto isso não for redesenhado. Isso é uma propriedade boa: o pipeline falha alto em vez de mentir. | `src/validation/cpcv.py:91,288-304,359` |
| **D** | **O contrato `estimate(bars, horizon_minutes=...)` de TODO estimador de volatilidade exige `horizon_minutes == bars.timeframe_minutes` e levanta `NotImplementedError` caso contrário.** Uma dollar bar não tem `timeframe_minutes`. É bloqueio de construção, não de resultado — atinge M1 (GK), Feature Engine (C01/C02/C06/C07) e Label Engine (dimensionamento de barreira) simultaneamente. | `src/features/volatility.py:49,83-90,120-125,147-152,179-184,211-216` |
| **E** | **A coerência cross-símbolo do repo hoje é, textualmente, uma coincidência de calendário — e o próprio código diz isso.** `src/models/dataset.py:119-122`: *"o join final … casava essas features com os LABELS do BTC (mesmo grid de 15m, timestamps batem por **coincidência de calendário**, não por serem do mesmo ativo)"*. Sob dollar bars a coincidência acaba — e a falha muda de "wrong-asset, frame cheio" para "join vazio, silencioso". | `src/models/dataset.py:113-135,151,155`; `side_subset` (`:207-213`) **filtra** as linhas nulas sem levantar erro |
| **F** | **A construção de dollar bar em produção não tem *nada* pronto — e não tem nada pra desfazer também.** `src/live/` é **1 arquivo de 3 linhas**, sem código. Nenhum stream de mercado é assinado em lugar nenhum (`build_combined_stream_url` tem zero callers de produção). Não existe reconexão em loop, nem número de sequência, nem detecção de gap, nem dedup. | `src/live/__init__.py` (3 linhas); `src/exchange/ws.py:53,58,229-247,278` |
| **G** | **`control_05_frescor_dados` bloqueia ordem se a última barra tem >90s.** Sob dollar bars um mercado legitimamente parado produz `FAIL` — e retorna `FAIL`, não `NOT_COMPUTABLE`, então é indistinguível de dado morto de verdade. É o único controle pré-trade que quebra de forma *ativa* (rejeita trades) sob a nova grade. | `src/risk/limits.py:144-153`, `:491-495`; `config/constants.yaml:977-980` |
| **H** | **Os limiares de HHI (0,25 / 0,30) são literais `# noqa: magic-number` em `pipeline.py`, não entradas de `constants.yaml`.** `grep -i hhi config/constants.yaml` → vazio. Um gate de Gate 3/4 sem proveniência declarada, na véspera de multiplicar o número de features por ~6. | `src/models/pipeline.py:531,536,537` |

---

## 1. Camada por camada

Ordem da hierarquia do `CLAUDE.md`. Camadas que **não mudam** estão declaradas com o porquê, não omitidas.

---

### 1.1 `exchange/` — **muda pouco hoje, mas ganha um requisito novo e inteiro**

**O que muda, mecanicamente.** Hoje o motor consome a barra **pré-agregada pela Binance** (`GET /fapi/v1/klines`). Sob dollar bars, a exchange deixa de entregar a barra: o motor precisa consumir o **feed de trades** e fechar a barra ele mesmo. Isso não altera nenhuma linha existente de `exchange/` — adiciona uma responsabilidade que não existe.

**Onde está codificado hoje:**
- `src/exchange/rest.py:224-235` — `params = {"symbol": symbol, "interval": interval, "limit": limit}` → `GET /fapi/v1/klines`. Única aquisição de barra do repo.
- `src/exchange/adapter.py:35-43` — `def get_klines(self, symbol, interval, ...)`. **O ABC `ExchangeAdapter` não expõe nenhum acessor trade-level** (métodos: `get_filters`, `get_klines`, `get_account_info`, `get_position_risk`, `get_open_orders`, `query_order`, `cancel_order`, `place_order` — `adapter.py:31-81`).
- `src/exchange/ws.py:53,58` — `build_combined_stream_url(streams: list[str], ...)` aceita uma lista arbitrária e **não codifica nenhum stream**. Zero callers em `src/`; os únicos literais `@aggTrade`/`@kline_15m` do repo estão em `tests/unit/test_exchange_ws.py:55`.
- `src/exchange/ws.py:278` — o único socket que se conecta de verdade é user-data: `self._transport.connect(build_user_data_stream_url(listen_key))`.
- `src/exchange/ws.py:40` — `class WebSocketTransport(Protocol)` — **não há implementação nem biblioteca de WebSocket no `pyproject.toml`** (declarado em `ws.py:13-14`).
- `src/exchange/ws.py:6-8` — *"Parsing de mensagem por tipo (kline, aggTrade, ORDER_TRADE_UPDATE, …) é Sprint 3+, quando os consumidores existirem"*. Nenhum parser existe.
- `src/exchange/ws.py:229-247` — `ReconnectPolicy.next_delay_s()` (`backoff_schedule_s = [1.0, 2.0, 4.0]`, `config/constants.yaml:523-528`) **não tem caller de produção**; só `.reset()` é chamado (`:279`).
- **Ausências de primeira classe:** zero `sequence`/`lastUpdateId`/`agg_id`/`resync`/`dedup` em `src/exchange/`. Nada garante nem mede continuidade de trade.

**O que NÃO muda:** rate limiting (`rate_limit.py`, orçamento por janela de relógio, `_HEADER_ORDER_COUNT_10S`/`_1M`), filtros versionados as-of (`filters.py:4-6`, B01), listenKey (`ws.py:118-177`), watchdogs de silêncio de socket (`ws.py:215-226`, 300s/60s) — todos são disciplina de *contato*, não de barra, e um feed de trade continua tickando mesmo quando nenhuma dollar bar fecha.

**Opções de redesenho** (detalhe completo na §5.1).

---

### 1.2 `data/` — **muda muito; é onde nasce a grade**

**O que muda:** hoje não existe *store* de barra nenhum. `lake.query_bars` lê parquet de 1m e reamostra **em toda chamada**; `tf` é argumento de runtime que nunca toca o disco. Sob dollar bars a barra precisa ser um artefato materializado (não é reconstruível barato a partir de klines — precisa reprocessar `aggTrades`), e `tf` deixa de ser um resample.

**Onde está codificado hoje:**

*Construtor de grade (o que é substituído):*
- `src/data/resample.py:107` — `df.with_columns((pl.col("open_time") // target_step_ms * target_step_ms).alias("_bucket"))` — bucket por divisão inteira. Não usa `group_by_dynamic`; grep confirma que `every=`/`offset=`/`label=`/`closed=` não existem no repo.
- `src/data/resample.py:126` — `close_time` é **sintetizado**: `(pl.col("open_time") + target_step_ms - 1)`. Sob dollar bars, `close_time` é o `transact_time` do último trade (`src/data/bars.py:170`).
- `src/data/resample.py:36-43` — `_TIMEFRAME_MINUTES = {"5m":5,"15m":15,"30m":30,"1h":60,"2h":120,"1d":1440}`; `:70-76` `step_ms()` levanta `UnsupportedTimeframeError` fora dessa tabela. **Comentário `:32-35`**: *"é a própria definição de calendário do timeframe nomeado (1h SEMPRE tem 60 minutos)"* — a premissa que a migração revoga.
- `src/data/resample.py:3-11` — **a prova de causalidade do resample é derivada da grade fixa**: *"Como o bucket é `floor(open_time / step_ms) * step_ms`, isso vale por construção"*. Não transfere para dollar bars; `src/data/bars.py:22-36` tem uma prova **própria** e independente (monotonicidade de `cumsum` sobre valores ≥0) que transfere.
- `src/data/resample.py:104,141-150` — `expected_bars_per_bucket = target_step_ms // _MS_PER_MINUTE` e o filtro `_n_constituent_bars == expected_bars_per_bucket`. Conceito sem análogo em dollar bar.

*Camada de armazenamento/consulta:*
- `src/data/lake.py:218,255-260` — `tf: str = "1m"`; `if tf == "1m" or df.is_empty(): return df` … `return resample.resample_klines(df, tf)`. **`tf` nunca é persistido.**
- `src/data/_paths.py:48-55` — `data/capacity/{source}/{symbol}/{yyyy-mm-dd}.parquet`. Sem segmento de `tf` nem de `bar_type`.
- `src/data/lake.py:83,98-106,115-124` — poda de arquivo por nome-como-data (dia ou mês). Um store de dollar bar particionado por data continua compatível; o que falta é o *writer*.
- `src/data/lake.py:18-20` — contrato de extensão declarado: *"adicionar o `DatasetSchema` em `schemas.py` e, se ela não for 'um arquivo por dia', um caso em `_list_files_in_range`"*.

*Data Quality Engine — dois checks quebram por construção:*
- `src/data/checks.py:139-141` — `check_close_time_convention`: `df.filter(pl.col("close_time") != (pl.col("open_time") + step_ms - 1))`. **Uma dollar bar viola em 100% das linhas.**
- `src/data/checks.py:161-184` — `check_grid_completeness`: `pl.arange(lo, hi + step_ms, step_ms)` + anti-join. Progressão aritmética literal; sem significado para barra event-driven.
- Consumidores: `src/data/validate.py:217` (`assert schema.grid_step_ms is not None`), `:283`, `:288`, `:295` (`classify_gaps` come a saída de `check_grid_completeness`), `:116-124` (`denom = rows + missing_bars` — o **score de qualidade é denominado na grade**).
- **O precedente da solução já existe no próprio repo:** `src/data/schemas.py:109` — `AGG_TRADES` tem `grid_step_ms=None,  # trades são event-driven — sem grade fixa`, e `validate.py:486-490` pula o check 9 com justificativa explícita. **Uma dollar bar é o mesmo caso: `grid_step_ms=None`.**
- `src/data/validate.py:394-458` — `validate_resampled_bars` é um stub que hardcoda `missing_bars=0`, `duplicates=0`, `invalid_rows=0`. Não protege nada hoje.

*O construtor de dollar bar que já existe:*
- `src/data/bars.py:219-293` — `dollar_bars_carry`/`threshold_bars_step`/`threshold_bars_finish`/`dollar_bars`. Streaming por construção, paridade lote↔streaming garantida pelo mesmo caminho de código (`:285-293`). Schema de saída `_BAR_OUTPUT_SCHEMA` (`:125-139`) é **coluna-a-coluna compatível** com o que `src/features/build.py:128-132,147-148` lê. Esse é o encaixe: a peça existe e o schema bate.

**Opções de redesenho:**

| opção | descrição | prós | contras |
|---|---|---|---|
| **D1 — novo `source` no lake** | `data/capacity/dollar_bars/{symbol}/{grade_id}/{yyyy-mm-dd}.parquet`, com `DatasetSchema(grid_step_ms=None)` novo em `schemas.py`; `query_bars` ganha despacho por `bar_type` | segue o contrato de extensão que `lake.py:18-20` já documenta; reusa poda por dia + pushdown; `grid_step_ms=None` reusa o precedente de `AGG_TRADES` | precisa de writer novo (não existe writer de barra hoje); `grade_id` vira parte do caminho e precisa de definição (ver bloqueador 2) |
| **D2 — materializar sob `data/processed/`** | usar o diretório já declarado em `_paths.py:43` e nunca criado | separa "derivado" de "capacity" (bruto) conceitualmente | zero código aponta pra lá hoje (`resample.py:98` só menciona em prosa); inventa uma 2ª convenção de layout |
| **D3 — não materializar, reconstruir on-the-fly** | espelhar o comportamento atual de `query_bars` | zero mudança de layout | **inviável**: reconstruir exige varrer `aggTrades` (61 GB, ~3,4 bi de trades só BTC); hoje o resample custa milissegundos. Ver §5.3 |
| **D4 — descontinuar o check 7/9 vs. torná-los condicionais** | opção (a): `if schema.grid_step_ms is None: skip` (padrão já usado); opção (b): substituir por invariantes próprias de dollar bar (`quote_volume ∈ [threshold, threshold + max_trade_value]`, `close_time` monotônico, nenhum trade órfão) | (b) é *mais* forte que a grade — o threshold dá uma invariante numérica exata que a barra de tempo nunca teve | (b) é código novo com sua própria superfície de bug; (a) reduz o `quality_score` a `1 − (dup+invalid)/rows` silenciosamente (`validate.py:121`) |

**Achado colateral, não solicitado:** `data/capacity/clocks/` contém 16 parquets de 2026-08-02 (**anteriores ao Sprint 1**), incluindo `dolar_5min.parquet` / `dolar_15min.parquet` / `dolar_30min.parquet` / `dolar_60min.parquet` (82 MB total), mais `tempo_*`, `volume_*`, `imbalance_*`. **Referenciados por zero arquivos do repo** — sem símbolo no caminho, sem manifesto, sem proveniência. Tratar como legado órfão, **não** como saída de M2. Se alguém os confundir com artefato de M2 numa sessão futura, isso é um bug de auditoria esperando acontecer.

---

### 1.3 `features/` — **muda muito; e o escopo dobrou com a 2ª decisão**

**O que muda, mecanicamente.** Duas coisas ao mesmo tempo:
1. Toda janela em contagem de barra que foi calibrada assumindo "1 barra = 15 min" perde a âncora de relógio.
2. `T1_FEATURE_IDS` deixa de ser o vetor; o registry inteiro passa a ser.

**Onde está codificado hoje — janelas em contagem de barra (todas `class: B`, `provenance: ASSUMED`):**

| constante | valor | `scaling_invariant` declarado | = relógio hoje (15m) | consumo |
|---|---|---|---|---|
| `feature_a05_ret_lookback_bars` (`constants.yaml:623`) | 4 | *(nenhum)* | 1h | `build.py:93` → `group_a.py:32,36-37` |
| `feature_a13_ema_window` (`:648`) | 48 | **`clock`** (`:653`) | 12h | `build.py:91` → `build.py:144` → `support.py:97-108` |
| `feature_b01_rsi_window` (`:665`) | 14 | **`clock`** (`:670`) | 3,5h | `build.py:92` → `group_b.py:10-13` |
| `feature_b07_efficiency_ratio_window` (`:678`) | 48 | `bar_count` (`:683`) | 12h | `build.py:99` → `support.py:300-316` |
| `feature_c06_vol_ratio_short_window` (`:697`) | 12 | `bar_count` (`:702`) | 3h | `build.py:94` → `group_c.py:30-38` |
| `feature_c06_vol_ratio_long_window` (`:717`) | 96 | `bar_count` (`:722`) | 24h | `build.py:95` |
| `feature_c07_vol_pctile_window` (`:732`) | 48 | `bar_count` (`:737`) | 12h | `build.py:96` → `group_c.py:41-47` |
| `feature_d06f_taker_imbalance_window` (`:746`) | 48 | `bar_count` (`:751`) | 12h | `build.py:97` → `group_d.py:22-30` |
| `feature_e10f_oi_change_window` (`:761`) | 48 | `bar_count` (`:766`) | 12h | `build.py:98` → `group_e.py:23-34` |
| `min_warmup_bars` (`:789`) | 200 (`DERIVED`) | *(nenhum)* | 50h | `build.py:102,174,178-191` |
| `atr_window` (`:173`) | 20 (`class: A`) | *(nenhum)* | 5h | `build.py:90,142`; `volatility.py:80` |

**O vocabulário certo já existe no repo e precisa de um 3º valor.** `scaling_invariant: clock | bar_count` foi criado em 2026-08-15 (AG-027 addendum) exatamente para responder "esta janela escala com o TF ou não?". `architecture_gaps_log.yaml:1457-1460` diz literalmente: *"bar-count vs clock-time **não tem resposta única**, cada classe escala diferente"*. Sob dollar bars aparece um terceiro eixo — janelas que deveriam ser comensuráveis a **atividade** (volume acumulado), não a relógio nem a contagem. Exemplo concreto: `feature_d06f_taker_imbalance_window` está marcada `bar_count` com justificativa *"NORMALIZAÇÃO … evita a baseline 'correr atrás' do próprio evento"* (`constants.yaml:754-759`) — sob dollar bars, `bar_count` **já é** proporcional a atividade, então essa feature ganha a propriedade desejada de graça. Já `feature_a13_ema_window` (marcada `clock`, justificativa *"span deve ser comensurável ao horizonte de RELÓGIO do label"*, `:656-663`) perde a âncora inteira.

**Onde está codificado — acoplamento duro a "15m":**
- `src/features/_sources.py:35` — `lake.query_bars(symbol, "15m", start, end, source="klines_1m", ...)`. **Literal.** Único ponto de entrada de barra do Feature Engine.
- `src/features/build.py:107,9,116,120,128-132,147-148,197,203-205,211,214` — parâmetro chamado `bars_15m`.
- `src/features/volatility.py:49,83-90,120-125,147-152,179-184,211-216` — o contrato `timeframe_minutes` + 5 guardas `if horizon_minutes != bars.timeframe_minutes: raise NotImplementedError`. **Achado D do resumo.**
- `src/features/support.py:283` — `out = std * np.sqrt(window)` — escalonamento √n dentro de `realized_vol` (alimenta C06 e C07). Sob dollar bars, √(nº de barras) deixa de ser √(tempo).
- `src/features/support.py:252-256` — `overnight[1:] = np.log(open_[1:] / close[:-1])` (Yang-Zhang). Em barra de tempo o gap barra-a-barra é 0 por construção; em dollar bar `open_time[i+1]` é o `transact_time` do *primeiro trade da próxima barra*, então o "overnight" vira gap tick-a-tick e o componente `V_o` colapsa.
- `src/features/build.py:178-191` — `apply_min_warmup_mask` corta por `_row_idx < min_warmup_bars`. Contagem de linha, não tempo nem $ acumulado.
- `src/features/groups/group_e.py:29-33` — `delta[1:] = np.diff(log_oi)` sobre OI amostrado a cada 5 min na fonte. Sob dollar bars, uma barra rápida produz Δ=0 (mesmo asof match duas vezes) e uma barra lenta agrega muitos ticks de OI. **Mesma classe de problema para funding** (`_sources.py:60-65`, `join_asof(..., strategy="backward")`): o join sobrevive, a *defasagem* do evento casado vira variável.
- `src/features/registry.yaml:47-59` — o registry **já documenta o perigo por escrito**: *"as janelas de lookback em barras … foram herdadas literalmente do PRD como CONTAGEM DE BARRAS, não recalibradas para preservar o intervalo de calendário original. A 30m, 48 barras = 1 dia; a 15m, as mesmas 48 barras = 12h."*

**Inconsistência viva encontrada de passagem (não é sobre dollar bars, mas está no caminho):** `min_warmup_bars` foi corrigido para **200** em `constants.yaml:790`, mas **as 13 entradas do registry ainda declaram `min_warmup_bars: 2000`** (`registry.yaml:68,84,100,116,137,154,171,187,203,229,245,261,287`), a docstring de `support.py:104` ainda diz 2000, e `tests/unit/test_features_build.py:70,87` ainda usa 2000. Vale corrigir junto, não depois.

**Escopo real da 2ª decisão (T1 → registry inteiro):**
- `src/features/build.py:29-40` — `T1_FEATURE_IDS` = 10 ids. `:45-49` `SUPPORT_FEATURE_IDS` = 3 (T2). `:51-56` `ALL_OUTPUT_COLUMNS`.
- **`features/registry.yaml` tem 13 entradas, não "dezenas"**: 10 T1 + 3 T2 (B07 `:110`, C01 `:131`, C02 `:148`). Por grupo: A=2, B=2, C=4, D=2, E=3. `registry.yaml:10-12` exclui explicitamente Grupo F e G-K.
- **`group_f.py` … `group_k.py` NÃO EXISTEM.** `src/features/groups/__init__.py:1-3` declara a taxonomia A–K, mas só A/B/C/D/E existem como arquivo. `src/regime/stress.py:143` referencia um `group_f.py` fantasma.
- **O pool não-curado está fora de `src/`**: `research/research_t2.py` tem **64 candidatas** (`group_a_research:112` 13 · `group_b_research:177` 10 · `group_c_research:237` 12 · `group_d_research:333` 9 · `group_e_research:375` 13 · `group_h_research:438` 5 · `group_k_research:479` 6). Nenhuma está no registry.
- **Portanto "todas as features do registry" = 13 hoje, não dezenas.** Se a intenção do Manager é o universo maior, a decisão implica *promover* de `research/` para `registry.yaml` — o que é escopo diferente (cada promoção exige `causal_proof`, teste de paridade, `lookback_bars`, entrada de registry: `tests/unit/test_features_build.py:180-197` `_REQUIRED_FIELDS`). **Esta ambiguidade precisa ser resolvida pelo Manager antes de qualquer estimativa de esforço.** Nota: `research/research_t2.py:316-319` contém `bars_per_year = 35_064.0` e `:306` `bvol_z_90d_window = 8640  # 90 dias x 96 barras/dia (15m)` — o Grupo K inteiro (`:479-521`) é derivado de calendário (`hour_of_day`, `day_of_week`, `days_since_halving`), o que sob dollar bars vira uma classe própria de feature (relógio real, não índice de barra).

**Teste de paridade lote↔streaming — sobrevive em lógica, quebra em fixture:**
- `tests/parity/test_features_parity.py:59-66` — o mecanismo é **prefix-slicing por índice de linha**, não por relógio: `sub_bars = bars.slice(0, row_idx + 1)`. **Agnóstico à cadência por construção.** Bom sinal.
- O que quebra: `:30-31` `_FIXTURE_END = "2024-02-10"  # 41 dias -> 3936 barras de 15m`; `:50` `assert bars.height > 2000 + _N_TAIL` (o 2000 velho); `:37` fixture vem de `klines_1m`, não de `aggTrades`; `:47-49` os 3 loaders são os de 15m; `:103` `row_idx = 2500` absoluto.

**Opções de redesenho:**

| opção | descrição | prós | contras |
|---|---|---|---|
| **F1 — reinterpretar todas as janelas como `bar_count` e não recalibrar** | 48 barras continuam 48 barras, agora em dollar bar | zero decisão nova, zero trial; e é a leitura *correta* para as janelas de agregação/estimação (erro amostral não conhece relógio — `constants.yaml:686-687`) | as 2 marcadas `clock` (A13, B01) ficam sem âncora, e a justificativa escrita delas (`:656-663`) passa a ser falsa |
| **F2 — converter as `clock` para relógio-equivalente medido** | A13/B01 ganham span derivado da duração mediana da dollar bar naquele símbolo/grade | preserva a semântica declarada; consistente com a decisão de horizonte do bloqueador 1 se ela for relógio | duração mediana é ela própria não-estacionária → reintroduz o problema do bloqueador 2 dentro da feature; e `support.ema` só aceita `span` inteiro fixo |
| **F3 — declarar `scaling_invariant: activity` como 3ª classe e reclassificar as 11 entradas** | vocabulário novo, uma passada de decisão por constante | resolve a pergunta *uma vez*, com registro auditável; é a extensão natural do que AG-027 já criou; 0 trials (é classificação, não sweep) | exige 11 decisões do Manager; nenhuma é automática |
| **F4 — adiar: congelar as janelas como estão e medir o efeito antes de decidir** | rodar o Feature Engine na grade dollar com as janelas atuais e comparar distribuições contra a grade tempo | mede antes de afirmar (`CLAUDE.md`); 0 trials se for só descritivo | consome o reprocessamento pesado (§5.3) antes de ter a decisão de grade do bloqueador 2 — provavelmente retrabalho |

**Regra de segurança orçamentária (obrigatória aqui):** `PLANO_MESTRE_PRINCE2.md:305` — `counter=45`, teto 60, **15 trials restantes**; critério de encerramento #5 (`PRD_V4_1.md:671`) é `N_lifetime > 60 sem Camada 2 fechada → encerrar`. Nenhuma das opções acima autoriza sweep. Interpretar "11 janelas sem âncora" como "varra as 11" gastaria o orçamento inteiro e poderia disparar o encerramento do projeto sozinho.

---

### 1.4 `labels/` — **muda muito; é o epicentro do bloqueador 1**

**O que muda:** o horizonte vertical, o timeout de fill, a unicidade e o `config_hash` — todos ancorados em `bar_ms = step_ms(cfg.tf)`, um fator único que deixa de existir.

**Onde está codificado hoje:**
- `src/labels/triple_barrier.py:699` — `bar_ms = step_ms(cfg.tf)` — **o único fator barra→ms do módulo inteiro.**
- `src/labels/triple_barrier.py:787` — `horizon_end_ms = t0 + cfg.time_stop_bars * bar_ms` — **a barreira vertical.** Ponto de quebra primário.
- `src/labels/triple_barrier.py:749` — `fill_horizon_ms = t_post + cfg.fill_timeout_bars * bar_ms`.
- `src/labels/triple_barrier.py:828` — `n_bars_held = int(np.ceil((t1 - t0) / bar_ms))` — conversão **inversa**. Sob dollar bars conta "unidades nominais de 15m decorridas", não barras.
- `src/labels/triple_barrier.py:212` — `step_ms(self.tf)` no `__post_init__`. **`LabelConfig(tf="dollar_…")` não pode nem ser construído hoje** — `UnsupportedTimeframeError`.
- `src/labels/triple_barrier.py:983` — `bars_15m = lake.query_bars(symbol, cfg.tf, start, end, source="klines_1m", ...)`. Sem parâmetro de tipo de barra.
- `src/labels/triple_barrier.py:985-989` — `horizon_ms = max(time_stop_bars, fill_timeout_bars) * step_ms(cfg.tf)` define a folga de prefetch de `mark_1m`. Sob dollar bars o horizonte real é **ilimitado a priori** → truncamento silencioso de cauda em `:750,788` (`n_incomplete_tail += 1; continue`).
- `src/labels/barrier_sweep.py:144,150,161-162,265` — **duplicata inteira da mesma aritmética**, mais o problema estrutural: `window_bars = time_stop_bars * bars_per_decision_bar + _WINDOW_SAFETY_MARGIN_BARS` alimenta `sliding_window_view` (`:180-184`), que exige largura **fixa**. Sob dollar bars o nº de candles de 1m cobrindo N dollar bars é ilimitado → `raise ValueError` em `:188-193` ou truncamento via `valid_mask` em `:186`.

**O que sobrevive intacto (e é uma boa notícia real):**
- `src/labels/triple_barrier.py:795-796` — o alinhamento com `mark_1m` é **por timestamp** (`np.searchsorted(mark_open_time, t_entry/horizon_end_ms)`), não por índice de barra. **B11 continua satisfeito por construção.**
- `src/labels/triple_barrier.py:987` — `mark_1m` é carregado sempre em 1m nativo, independente de `cfg.tf` (documentado em `:955-962`). Essa decisão de desenho atravessa a migração sem uma linha de mudança.
- `src/labels/fill_model.py:60-69,95-96,103,107-108` — `simulate_fill_arrays` é **ms-only**; a conversão barra→ms acontece no caller. Só o caller precisa mudar.

**Unicidade / `sample_weight` — híbrido, e é o ponto sutil:**
- `src/labels/weights.py:81` — `idx1 = np.searchsorted(t0, t1, side="right") - 1` — o **endpoint** é resolvido em TEMPO.
- `src/labels/weights.py:88-91,109-110` — mas a concorrência e a média são **por POSIÇÃO de barra**: `concurrency = np.cumsum(diff[:n])`, `span = (idx1 - idx0 + 1)`, `uniqueness = (prefix[idx1+1] - prefix[idx0]) / span`. Cada posição pesa igual, independente da duração de relógio dela.
- **Consequência:** sob dollar bars, um label que atravessa um pico de atividade cobre muitas posições (fino), um que atravessa madrugada parada cobre poucas (grosso). A unicidade muda de significado **sem nenhum erro de código e sem nenhuma invariante disparar**.
- **Risco novo, específico:** `weights.py:71-78` só valida `np.diff(t0) >= 0` (não-decrescente). Dollar bars podem emitir duas barras consecutivas com o **mesmo `close_time` em ms** durante uma rajada (`bars.py:170` `close_time = last(transact_time)`) → `t0` duplicado passa o guard e muda os empates de `searchsorted(..., side="right")` em `:81`.

**Invariante que presume espaçamento uniforme:**
- `src/labels/triple_barrier.py:330` — `assert (labels["n_bars_held"] <= time_stop_bars).all()`. Só vale porque `n_bars_held` (`:828`) e `horizon_end_ms` (`:787`) usam **o mesmo `bar_ms`**. Troque um dos dois por contagem real de barra numa grade variável e a invariante vira vácua ou falsa.
- Teto de dtype: `:539` `"n_bars_held": pl.Int16` (max 32.767) e `:540` `"n_funding_events": pl.Int8` (**max 127**). Uma posição segurada numa longa estiagem de dollar bars atravessa muito mais janelas de funding de 8h do que 32×15m jamais atravessou. `Int8` é um overflow esperando acontecer.
- `assert_label_invariants` **continua não sendo chamado no caminho real de escrita** (AG-029): só em `backfill_multi_symbol.py:102-108`, não em `triple_barrier`→`write_labels_atomic` (documentado em `weights.py:163-168`).

**`config_hash` (B15) — o achado mais perigoso da camada:**
- `src/labels/triple_barrier.py:267-277` — payload = `tp_atr_mult, sl_atr_mult, time_stop_bars, fill_timeout_bars, atr_window, maker_fee, taker_fee, estimator_id, tf`. **Sem campo de tipo de barra. Sem campo de threshold.**
- **Consequência direta:** um run em barra de tempo 15m e um run em dollar bar calibrada para ~a mesma frequência média, ambos com `tf="15m"`, produzem **o `config_hash` idêntico**. `verify_config_hash` (`:282-306`) não dispara. Isso é exatamente a falha que B15 existe para impedir.
- Agravante: o threshold de dollar não é constante versionada. `constants.yaml:1298-1300` já diz para o TIB: *"`exp_num_ticks_init` NÃO entra aqui — é calculado por símbolo em `m2_bar_comparison.py`"*. O mesmo vale para `dollar_threshold` (`m2_worker.py:437`). **O parâmetro que DEFINE a grade não é hasheável hoje.**
- `src/labels/experiment_log.py:42-71` — `_SCHEMA` registra `config_hash`, `time_stop_bars`, `fill_timeout_bars`, `atr_window`, mas **não tem coluna `tf`, `estimator_id` nem tipo de barra**. É a fonte do `N` para o DSR (`:3-5`) e não consegue distinguir os dois mundos.
- Precedente de como fazer certo, no próprio arquivo: `:676-682` — `if resolved_estimator.estimator_id != cfg.estimator_id: raise ValueError(... "o config_hash persistido mentiria ...")`. Falta o análogo para a grade.

**Caminho em disco:**
- `src/labels/_paths.py:43-45` — `data/labels/{symbol}/{tf}/{version}/`. `LABEL_COLUMNS` (`triple_barrier.py:545-573`) não tem `bar_type`, `tf` nem `bar_id`. A identidade da grade só existe no nome do diretório e no hash (que não a codifica).
- Resolver duplicado em 3 pacotes consumidores, todos com a mesma assinatura de TF-de-tempo: `src/validation/_paths.py:35,40`, `src/backtest/_paths.py:34`, `src/models/_paths.py:28`.
- Convenção de nome já cogitada em prosa: `constants.yaml:209-211` — *"reprocessar `labels/v2_gk/` (e agora também `v2_gk_dollar/`)"*.

**Opções de redesenho:** ver §2 (bloqueador 1) — é o mesmo problema.

---

### 1.5 `regime/` — **muda; e tem um gatilho de stress que quebra outright**

**O que muda:** a máquina de estados conta **barras**, não minutos, em três lugares; e um gatilho de stress exige grade fixa.

**Onde está codificado hoje:**
- `src/regime/classifier.py:145` — `is_warmup = t < thresholds.min_warmup_bars` → 200 barras = 50h a 15m, duração variável sob dollar bar.
- `src/regime/classifier.py:181-182,192-193` — `if trend_pending >= thresholds.confirmation_bars` / `if vol_pending >= ...`. `regime_confirmation_bars = 2` (`constants.yaml:842-845`, `LITERATURE`, *"mudança de regime só é efetivada após 2 barras consecutivas"*) → 30 min a 15m; sob dollar bar pode ser 40 segundos numa rajada.
- `src/regime/classifier.py:206-208` — `stress_exit_confirmation_bars = 4` (`constants.yaml:849-852`) → 1h a 15m.
- `src/regime/classifier.py:229,253` — `_bars_in_regime`, dwell-time exportado **em barras** (`out[t] = run if regime[t]=="R5" else max(run, 2)`).
- `src/regime/classifier.py:358-359` — comentário que faz a conversão explícita: *"int16 satura em 32.767 barras (~341 dias a 15m)"*.
- **Quebra dura:** `src/regime/stress.py:245,252` — S6 usa `data_checks.check_grid_completeness(df, "_ts", step_ms)` e `expected_prev = ts_list[i] - step_ms`; `:459` — `step_ms = inputs.step_ms or data_resample.step_ms("15m")`. Sob dollar bars, "barra esperada em `t - step_ms`" não tem significado — S6 dispararia em quase toda barra ou em nenhuma.
- `src/regime/stress.py:403` — S10 usa janela em **horas** (`stress_filters_hash_window_hours = 24`, `constants.yaml:877-881`) misturada num array indexado por barra. Duas unidades convivendo no mesmo módulo.
- **Footgun latente:** `src/regime/stress.py:352` — `symbol: str = "BTCUSDT"` como *default* em `discover_filters_hash_snapshots`. O caminho de produção passa explícito (`classifier.py:438`), mas um caller novo que omitir pega os filtros do BTC em silêncio.

**O que NÃO muda:** os eixos de quantil são **expansivos**, não janela fixa — `classifier.py:322,324` (`expanding_percentile_rank_strict`), cortes em nível de quantil (`regime_er_cutoff` etc., `constants.yaml:282-297,824-839`), terços econômicos (`classifier.py:71-72`, `1/3`/`2/3`). Isso é agnóstico à grade **por definição**. Mas ver AG-030 abaixo.

**Cross-símbolo:** o Regime Engine é **estritamente single-symbol** (`build.py:48-52`, `classifier.py:428,431-436`). Não usa BTC como driver de mercado para os outros. Confirmado por leitura, não presumido.

**AG-030 piora sob dollar bars, e vale registrar:** `er_quantile`/`econ_quantile`/`vol_pctile` são postos expansivos **desde a origem de cada ativo**. Hoje BTC acumula até 231.552 barras de 15m contra no máximo 164.256 dos alts (`architecture_gaps_log.yaml:1697-1699`). Sob dollar bars, a contagem de barras acumuladas passa a depender de **quanto volume cada ativo negociou**, não de quanto calendário viveu — o desbalanceamento entre BTC e os alts muda de magnitude e de natureza. AG-030 já está aberto e já exige decisão antes de qualquer comparação cross-asset estratificada por regime; a migração **não o resolve nem o agrava previsivelmente** — muda o eixo do viés. Precisa ser reavaliado junto, não depois.

**Opções:** as três confirmações em barra (`min_warmup_bars`, `confirmation_bars`, `stress_exit_confirmation_bars`) enfrentam exatamente a escolha do bloqueador 1, em escala menor. S6 tem 3 saídas honestas: (a) desligar sob grade não-uniforme (`NOT_COMPUTABLE`, não `FAIL` — há precedente em `stress.py:163,196,215`); (b) redefinir "gap" como *lacuna no feed de trades*, medida diretamente em `aggTrades`, o que é **mais** direto que a grade e detecta a coisa real; (c) manter uma grade de tempo paralela só para S6. (b) é conceitualmente mais forte, mas é código novo.

---

### 1.6 `models/` — **muda por dependência, e o gate de HHI precisa de revisão própria**

**O que muda:** o Alpha não conhece barra nenhuma diretamente — mas `build_modeling_frame` casa três engines por **igualdade exata de ms**, e o vetor de features vai mudar de tamanho.

**Onde está codificado — o join de três vias:**
- `src/models/dataset.py:151` — features × regime: `bar_table.join(regime_small, on="_open_time_ms", how="left")`
- `src/models/dataset.py:155` — barras × labels: `labels2.join(bar_table.select(join_cols), on="_close_time_ms", how="left")`
- `src/models/dataset.py:26-33` — as duas convenções: *"`src.labels.triple_barrier` usa `t0 = close_time` da barra de 15m; `src.regime.classifier` usa `t0 = open_time` da mesma barra"*.
- **Nenhum guard.** `:171-172` conta nulos e loga; `:189-191` retorna. Depois `side_subset` (`:207-213`) **filtra** as linhas nulas. Uma incompatibilidade de grade produz um frame quase vazio, silenciosamente, com log em nível `info`.
- `src/models/dataset.py:5` — contrato posicional adicional: *"os `train_idx`/`test_idx` posicionais de `cpcv.generate_splits` só são válidos se o frame que os consome tiver a mesma ordem que o frame que os gerou"*.

**Onde está codificado — acoplamento ao vetor de 10:**
- `src/models/alpha.py:63` — `DESIGN_COLUMNS = (*T1_FEATURE_IDS, *REGIME_DUMMY_COLUMNS)`; `:95` docstring *"10 features T1 + 4 dummies (14 colunas)"*.
- `src/models/alpha.py:275` — `DESIGN_COLUMNS[int(k[1:])]` — remapeamento **posicional** dos ganhos do XGBoost. Ordem é contrato.
- `src/models/alpha.py:225,251` — `monotone_constraints` é tupla posicional, uma por feature. `:220` `tuple(ic_results[f].constraint for f in T1_FEATURE_IDS)`.
- `src/models/alpha.py:329-332` e `dataset.py:210-213` — filtro `is_not_null` **encadeado sobre toda feature**. Com 13 (ou 64) features em vez de 10, a interseção de não-nulos encolhe monotonicamente — cada feature nova com warmup próprio corta linhas de treino. **Efeito de segunda ordem que ninguém mediu.**
- `src/models/baselines.py:793,819-821` — B4 embaralha exatamente as `n_t1` primeiras colunas.
- `src/analysis/faixa2_caminho_b.py:1079-1081,1177` — mesma fatia posicional.
- `src/analysis/faixa2_e2_research.py:56-66` — `CURRENT_T1` com **8 nomes hardcoded** (não 10); `faixa2_e3_stability.py:69` — `CANDIDATES_18`. Listas paralelas que vão divergir.

**HHI (§5.8) — ver §5.4 para a análise completa.** Localização: computado em `src/models/hhi.py:65` (nominal) e `:185` (efetivo); gate em `src/models/pipeline.py:531,536,537` com literais `0.25`/`0.30` marcados `# noqa: magic-number`. **Assimetria não documentada:** `alpha.py:279` computa o HHI nominal sobre as **14** `DESIGN_COLUMNS`, e `:286-288` o HHI efetivo sobre as **10** `T1_FEATURE_IDS` só — os dois números que aparecem lado a lado no relatório têm denominadores diferentes.

**Um número por-barra dentro do treino:** `src/models/alpha.py:266` — `tau = np.quantile(calibrated_train_all, 1.0 - target_signal_rate)`, com `target_signal_rate = 0.0189` (`constants.yaml:252`, `class: A`, `DERIVED` do orçamento de fees). Isso é uma **taxa de sinal por barra**. Se o nº de barras/ano mudar sob a nova grade, a mesma taxa produz outro nº de trades/ano — e o orçamento de fees (R3) é definido em trades/mês, não em fração de barras. **Este é um acoplamento R3↔grade que não aparece em nenhum documento.**

**O que NÃO muda:** `sample_weight` é consumido como coluna pronta (`alpha.py:229,258,262`); anualização de Sharpe em `backtest_lite.py:53-54` é por **calendário** (`span_seconds`), não por contagem de barra — sobrevive intacta.

---

### 1.7 `validation/` — **muda; e é onde a migração bate num muro por desenho**

- **Purge:** `src/validation/cpcv.py:383` — `purge_mask |= (t0_ms <= g_end) & (t1_ms >= g_start)`. **100% baseado em intervalo de tempo, usa o `t1` real.** Agnóstico a duração de barra. Nada a fazer. (Mesma lógica no checker, `:448`.)
- **Embargo:** `:255` `return config.embargo_bars * step_ms(config.tf)`; aplicado como distância temporal em `:385-386`. **Contagem de barra × duração assumida.** Ver §4.
- **Guarda dura:** `:288-304` `assert_tf_consistent`, chamada incondicional em `:359`, `_TF_CONSISTENCY_RTOL = 0.05` (`:91`). Achado C.
- **Partição de grupos é por largura de TEMPO igual, não por contagem de linha:** `:177` `edges = np.linspace(t_min, t_max, n_groups + 1)`; `:192` `searchsorted`. A justificativa está escrita e é exatamente a premissa que cai: `:13-20` — *"como a densidade de barras de 15m é ~constante ao longo dos ~6,6 anos do dataset … os dois critérios coincidem na prática"*. **Sob dollar bars a densidade é proporcional à atividade — os dois critérios divergem, e os 6 grupos ficam com contagens de linha muito diferentes.** Isso não é vazamento, mas desequilibra folds (um grupo cobrindo 2021 teria muito mais linhas que um cobrindo 2023).
- **Testes de leakage que ficam vácuos ou errados:** teste 4 (`leakage.py:319` grade literal `899_999/1_799_999/2_699_999`), teste 5 (`:356` `np.arange(n) * 900_000`), teste 9 (`:479-517`, cujo **sujeito inteiro é o resampler de tempo** — `:499` `resample_klines(df_1m, "30m")`; sob dollar bar esse teste passa a validar um componente que não está mais no caminho crítico), teste 14 (`:672` "últimas 500 barras", span de relógio variável). Testes 6/7/12 (`:402,435,607`) chamam `cpcv.generate_splits` e portanto **herdam a falha dura de C** — pior, `:405` só captura `AssertionError`, então um `CPCVError` escapa do runner inteiro em vez de virar linha FAIL.
- **Walk-forward:** `src/validation/volatility_walkforward.py:86,89,93` — a unidade de fold é o **trimestre civil**, e o treino inicial em **anos** (`initial_train_years * 4`). Índices derivados por `searchsorted`, comprimento variável por construção. **Sobrevive praticamente intacto** — é o componente mais bem posicionado do repo para a migração. Ressalva: `:113-122` `next_bar_realized_variance` é variância *por barra*, não por unidade de tempo; e `:233` justifica ausência de HAC com *"`horizon_minutes == timeframe_minutes`, uma barra"* — premissa que cai.
- **DSR:** `src/validation/dsr.py:131,166,172` — `trades_per_year` é **parâmetro injetado**, e a docstring `:17-26` é explícita: *"`sr_annualized` … é reportado só para leitura … nunca entra na conta interna"*. `n_obs` é contagem de trades (`:144`), não de barras. **Não muda nada.** Nenhum `sqrt(252)`/`35064`/`bars_per_year` no arquivo.

---

### 1.8 `backtest/` — **muda pouco; herda a falha de CPCV**

- **Não existe motor de backtest em `src/backtest/`** — só `fill_reconciliation.py` (860 linhas) e `_paths.py`. A anualização vem de `src/models/backtest_lite.py:53-54,59` e é **por calendário** (`DAYS_PER_YEAR = 365.25`, `SECONDS_PER_DAY = 86_400`). Sobrevive.
- **Nenhum resample de curva de equity para grade de tempo** existe (grep confirmado). Nenhum modelo de fee/latência por barra.
- **Onde entra a grade:** `fill_reconciliation.py:28-34` documenta o acoplamento — *"`labels.t_entry` é o timestamp de ABERTURA da barra seguinte … exatamente o ponto de grade que `fill_simulator._day_grid_ms` usa como `t_post`"*; o join está em `:274-279` (`left_on=["t_entry","side_hat"], right_on=["t_post","side"]`) e `:586-591`. Se o Label Engine mudar de grade e o fill simulator não, este join casa **zero linhas** — e o sintoma é `n_missing_order_data_gap` (`:280`), um contador, não uma exceção.
- `fill_reconciliation.py:205` — `cpcv.generate_splits(labels_all)` → herda a falha dura de C.
- Filtragem temporal é por **data civil** (`:248-249,583`) — agnóstica.

---

### 1.9 `risk/` — **muda em exatamente um ponto, mas é um ponto que bloqueia trades**

- **Nada em `src/risk/` é contado em barras.** Sem janela de vol-targeting, sem lookback de drawdown, sem cooldown "N barras". K01/K02 são fração de equity (`kill_switch.py:102-108,111-120`); perdas consecutivas contam **trades** (`:123-128`, `limits.py:314-318`).
- **A exceção — e é séria:** `src/risk/limits.py:144-153` `control_05_frescor_dados(bar_staleness_s, book_staleness_s)`, `bar_max_s = 90.0` (`constants.yaml:977-980`, *"PRD §8.3 controle 5 — 'barra < 90s'"*). Cabo em `:491-495` → `RejectionReason.DATA_STALE`, e `evaluate_all` **para no primeiro FAIL** (`:551`). Achado G.
- **Proveniência que fica indefinida:** `limits.py:201-207` — o limiar `N_req/unit >= 2,0` do controle 9b é justificado por *"tabela de dispersão risco p90/p10 por TF — a 2h, p90/p10 = 3,05x; a 15m, 1,33x"*. Uma dollar bar não tem TF; a justificativa deixa de ter referente. O **valor** pode continuar defensável, a **proveniência escrita** não.
- `limits.py:30-32` documenta que a cadência do engine é uma avaliação por barra (*"o próximo candidato reavalia do zero na próxima barra"*) — sob dollar bars, a frequência de reavaliação passa a ser proporcional à atividade. Isso é provavelmente **desejável** (mais avaliações quando o mercado se move), mas nunca foi decidido.

**Opções para o controle 05:** (a) reexpressar o limiar em **$ acumulado desde a última barra** em vez de segundos — mede a coisa certa (o feed está vivo?) na unidade da nova grade; (b) manter em segundos mas contra o **último trade recebido**, não a última barra fechada — separa "feed morto" de "mercado parado", e é a distinção que o controle realmente quer fazer; (c) retornar `NOT_COMPUTABLE` em vez de `FAIL` quando não há barra mas há trades. (b) parece a leitura mais honesta do §8.3, mas é mudança de semântica de um controle pré-trade — decisão do Manager, não minha.

---

### 1.10 `execution/` — **muda em um ponto estrutural**

- `src/execution/fill_simulator.py:469-473` — `_day_grid_ms(day, bar_ms)`: `n_bars = _MS_PER_DAY // bar_ms` + `start_ms + np.arange(n_bars) * bar_ms`. **Divisão inteira do dia por `bar_ms`** — assume duração constante **e** alinhamento à meia-noite. As duas premissas caem.
- `src/execution/fill_simulator.py:626` — `bar_ms = step_ms("15m")` **hardcoded** no caminho de produção.
- `src/execution/fill_simulator.py:465` — `# Grade de decisão a 15m (mesma grade da decisão real do sistema, §0.1)`. **É a única afirmação em código de paridade de grade backtest↔live, e é uma afirmação de relógio.**
- `src/execution/fill_simulator.py:627-631` — `fill_timeout_ms = timeout_bars * bar_ms`, com `fill_timeout_bars = 1` (`constants.yaml:804-810`) cuja semântica declarada é de relógio: *"quanto tempo uma ordem limite fica postada antes do timeout"*. Sob dollar bars, 1 barra = segundos numa rajada, horas numa madrugada. **O `on_timeout: CANCEL` (B13) muda de comportamento sem que uma linha mude.**
- `src/execution/fill_simulator.py:497-499` — a otimização "carrega só dia+1" é válida *enquanto* 1 barra ≪ 1 dia. Uma dollar bar atravessando um fim de semana parado viola em silêncio.
- **Sobrevive:** `_MARKOUT_HORIZONS_MS = {"1m":60_000,"5m":300_000,"30m":1_800_000}` (`:164`) — relógio puro.
- **Ausências:** `on_timeout: CANCEL` não tem implementação em lugar nenhum (só a string em `constants.yaml:807` e o regex do linter `tools/lint/banned_patterns.py:62,142-143`). `place_order` levanta `NotImplementedError` (`src/exchange/adapter.py:159-163`). Não há máquina de estados de ordem, TTL nem scheduler de cancelamento.

---

### 1.11 `live/` — **não muda: não existe**

`src/live/__init__.py` tem **3 linhas** (docstring + `from __future__`). `scripts/` está vazio. Zero `while True`/`asyncio`/`Thread` em `src/` fora dos injetores de `sleep_fn` de `ws.py:82,263`. O gatilho "fechou barra → rodar modelo" **não existe em nenhuma forma** — nem timer, nem `x: true`, nem poll. Referenciado como futuro em `src/exchange/rest.py:19` e `src/monitoring/logging.py:4`; designado dono do watchdog em `src/risk/kill_switch.py:145-146`.

**Consequência para o escopo:** nada precisa ser desmontado. Mas nada pode ser reaproveitado — inclusive warmup, buffer e estado. Isso é simultaneamente a melhor e a pior notícia do relatório: a migração não cria dívida no live, porque o live é greenfield; mas a construção de barra em tempo real é 100% trabalho novo.

---

### 1.12 `monitoring/` — **não muda hoje, porque está vazio**

`src/monitoring/` = `__init__.py` (3 linhas) + `logging.py` (64 linhas, só configuração de structlog + máscara de segredo). **Não há heartbeat, alerta, métrica nem dashboard.** A regra "sem barra há N minutos → alerta" **não existe** — o equivalente funcional vive em `src/risk/limits.py:149-153` e é *bloqueante*, não alerta (§1.9). K08 (Quality Gate em dado live) está declarado ausente: `kill_switch.py:184-186`, *"não há consumidor de streaming que rode o Quality Gate por barra ainda"*.

**Nota de desenho, não de mudança:** quando o monitoring existir, sob dollar bars ele precisará de dois relógios distintos — "feed vivo?" (contra o último *trade*) e "grade progredindo?" (contra a última *barra*) — porque sob a grade nova esses dois deixam de ser a mesma pergunta. Sob barra de tempo eles são a mesma pergunta, e é por isso que ninguém precisou separá-los até agora.

---

### 1.13 `analysis/` — **muda muito (é medição pós-hoc, mas toda ela)**

Fora da hierarquia formal (exceção documentada no `CLAUDE.md`), mas é onde mora quase toda a evidência do projeto.

- **`BARS_PER_YEAR` está hardcoded duas vezes, independentemente:** `src/analysis/faixa1_5_prerequisites.py:93-96` (`_BAR_SECONDS = 15*60`; `BARS_PER_YEAR = DAYS_PER_YEAR * SECONDS_PER_DAY / _BAR_SECONDS` = 35.064) e `src/analysis/faixa1_6_reconciliation.py:918` (`bars_per_year = DAYS_PER_YEAR * 24 * 4`). Consumidores: `faixa1_5_prerequisites.py:273`, `faixa1_7_edge_or_beta.py:212,243`, `faixa2_caminho_b.py:123`, `faixa2_vol_accelerator_test.py:270,413`, `faixa2_dsr_and_b2_check.py:87`, `tau_diagnostics.py:316,320`. **Todos ficam errados no instante em que uma barra deixa de ser 15 minutos** — inclusive a tradução do orçamento de fees (R3) em `target_signal_rate`.
- **Módulos que precisam de rerun completo** (via `build_modeling_frame` → labels + features + regime): `calibration_diagnostics.py:915`, `faixa1_5_prerequisites.py:806`, `faixa1_6_reconciliation.py:702,1112`, `faixa1_7_edge_or_beta.py:562`, `faixa2_caminho_b.py:1016,1284,1322`, `faixa2_dsr_and_b2_check.py:165`, `faixa2_e3_stability.py:79`, `faixa2_vol_accelerator_test.py:92,287,397`, `m6_common_factor_hypothesis.py:229`.
- **`timeframe_minutes` no harness de M1:** `volatility_comparison.py:320,223` — `Bars(frame=..., timeframe_minutes=...)` e `estimate(bars, horizon_minutes=bars.timeframe_minutes)`. **M1 inteiro é parametrizado por minutos.** Combinado com o achado D, isso significa: **o vencedor de M1 (Garman-Klass) foi medido exclusivamente em barra de tempo.** `docs/refactor_gk_canonico.md:198-201` já antecipou isso — *"M2 pode trocar o tipo de barra de decisão … qualquer um dos dois força um NOVO reprocessamento"* — mas a leitura mais forte é: **a vitória do GK é condicional à grade, e ninguém sabe se ela sobrevive à mudança.** Não é motivo para reabrir M1 agora; é motivo para não tratar `canonical_volatility_estimator` como resolvido quando o reprocessamento acontecer.
- `cost_surface.py:403` — `horizon_ms = max(time_stop_bars, fill_timeout_bars) * step_ms(cfg.tf)`; `:330` reconstrói labels ele mesmo.
- `faixa1_7_edge_or_beta.py:126` — `ret_48b[48:] = log_px[48:] - log_px[:-48]` (sinal de tendência de 48 barras).
- `faixa2_dsr_and_b2_check.py:178-181` — **alinhamento posicional, não por chave**, entre a série da estratégia e o B2 (`n_align = min(...)`, fatias por índice). Só é salvo hoje porque as duas pernas são agregadas em dia civil (`:151-156,173`).
- `m2_stats.py:244-245` — reusa `compute_concurrency_and_uniqueness` de produção (bom).

---

## 2. Bloqueador 1 — AG-031: horizonte do label sob dollar bars

### 2.1 O estado exato do achado

`time_stop_bars = 32` (`config/constants.yaml:164-171`, `provenance: ASSUMED`, `class: A`, `sweep_range: [16,48]`, `review_by: sprint_6`) é hoje interpretado de forma **mutuamente incompatível** por dois módulos, ambos deliberados e documentados:

- **Relógio fixo** — `src/analysis/m2_bar_comparison.py:227` (`TIME_STOP_REFERENCE_TF = "15m"`), `:241` e `:374` (`time_stop_ms = time_stop_bars_n * step_ms(TIME_STOP_REFERENCE_TF)`). 8h sempre, em qualquer TF medido. Docstring `:98-107` é explícita: *"`time_stop_ms` é FIXO, calculado 1x via `step_ms("15m")` — nunca recalculado por TF."*
- **Contagem de barra fixa** — `src/labels/triple_barrier.py:787` (`horizon_end_ms = t0 + cfg.time_stop_bars * bar_ms`, com `bar_ms = step_ms(cfg.tf)` em `:699`). 8h a 15m, 16h a 30m, 32h a 1h. Confirmado na docstring `:964-972`.

A 15m as duas convenções coincidem — por isso nunca gerou erro visível.

**O PRD já decidiu isso três vezes, e a favor de RELÓGIO.** As seções que AG-031 cita, verificadas verbatim:

| âncora | linha | texto |
|---|---|---|
| `PRD_V4_1.md` §2.7 (I2) | **174-185** | tabela `ATR(20) cobre / time_stop 32 barras` (M15 5,0h/8,0h · M30 10,0h/16,0h · H1 20,0h/32,0h) + *"Decisão de desenho que precede a implementação … com o **horizonte em relógio fixo** e a janela em barras derivada"* |
| `PRD_V4_1.md` §3.2 M1 | **368** | *"cada estimador é calibrado com horizonte em **relógio fixo** e janela em barras derivada por TF"* |
| `PRD_V4_1.md` §4.2 | **483** | *"**Meta-label:** triple barrier permanece. `time_stop` vira **relógio** (I2), não barras."* |
| `PRD_V4_1.md` registro V4.0→V4.1, item 7 | **779** | `| 7 | atr_window/time_stop em relógio, não em barras | horizontes divergem entre TFs |` |

AG-031 confirma por leitura de AG-005 (`architecture_gaps_log.yaml:252-317`) que *"a palavra 'relógio' não aparece nenhuma vez na entrada inteira"* — a convenção de contagem-de-barra em `triple_barrier.py` é **efeito colateral não examinado** de uma correção mínima de bug de unidade, não uma escolha entre as duas convenções.

**Custo de correção hoje ainda é zero** (`architecture_gaps_log.yaml:1811-1818`): só existem labels em 15m no disco (`data/labels/{SYMBOL}/15m/v1/labels.parquet`, 5 arquivos). Deixa de ser zero no primeiro `build_labels_for_symbol(tf="30m")`.

### 2.2 Por que dollar bars muda a pergunta

Em multi-TF, "32 barras" tinha *pelo menos* três valores de relógio conhecidos a priori (8h/16h/32h) — errados, mas determinísticos. Sob dollar bars, "32 barras" tem uma **distribuição** de durações de relógio, e ninguém mediu essa distribuição. O pior caso não tem teto: uma sequência de 32 dollar bars num fim de semana parado pode atravessar dias.

**Consequência imediata em código, não teórica:** `triple_barrier.py:985-986` pré-carrega `mark_1m` com folga `max(time_stop_bars, fill_timeout_bars) * step_ms(cfg.tf)`. Se o horizonte real ultrapassar essa folga, as linhas afetadas caem em `:750,788` (`n_incomplete_tail += 1; continue`) — **descarte silencioso, contado num log, sem exceção**. Sob barra de tempo isso só acontecia na cauda do dataset; sob dollar bars aconteceria toda vez que a atividade caísse.

### 2.3 As opções

#### Opção 1 — **Horizonte em contagem de barra** (`t1 = t0` + 32 dollar bars)

*Mecânica:* `horizon_end_ms` deixa de ser aritmética e passa a ser lookup — `close_time[i + 32]`.

- **Causalidade (B01-B06):** ✅ intacta. `close_time[i+32]` é estritamente futuro em relação a `t0`, e o purge do CPCV (`cpcv.py:383`) usa o `t1` real, então nada vaza. **Mas** `t1` deixa de ter cota superior conhecida a priori — e `cpcv_embargo_bars` foi dimensionado (AG-032) presumindo `time_stop_bars` como teto por construção. Ver §4.
- **Unicidade (§3.5):** ✅ é a opção **mais limpa** para `weights.py`. `idx1 - idx0` vira exatamente 32 por construção; `span` (`weights.py:109`) fica constante; concorrência máxima vira exatamente 32. A invariante `n_bars_held <= time_stop_bars` (`triple_barrier.py:330`) vira **verdadeira por definição** em vez de derivada.
- **Estabilidade de treino:** ⚠️ ambígua. O alvo passa a ser "retorno sobre os próximos $32·threshold negociados" — economicamente coerente com dollar bars (é *tempo de volume*, o relógio de negócio), mas o PnL realizado, os fees e o funding continuam vivendo em relógio civil.
- **Colisão com o PRD:** ❌ **contradiz diretamente** as 4 âncoras da §2.1. Adotar exige emenda formal ao PRD, não implementação silenciosa.
- **Colisão com R3:** ⚠️ o orçamento de fees (`fee_budget_monthly`, ~55 trades/mês) é mensal-civil. Um horizonte em barras torna a taxa de trades proporcional à atividade — mais trades em meses voláteis, exatamente quando o custo importa mais.
- **Achado empírico a favor:** M2 mostrou que dollar bars são drasticamente mais gaussianas (BTCUSDT 15m janela recente: `kurtosis_excess` 5,437 → **0,039**; `experiments/m2_report_recente.json`). Um horizonte em barras herda essa propriedade para o *rótulo*; um horizonte em relógio não necessariamente.

#### Opção 2 — **Horizonte em relógio fixo** (`t1 = t0 + 8h`, nº de barras variável dentro)

*Mecânica:* `horizon_end_ms = t0 + time_stop_ms`, com `time_stop_ms` constante lida de `constants.yaml`. É literalmente o que `m2_bar_comparison.py:241` já faz.

- **Causalidade:** ✅ intacta e trivialmente auditável (`t1` é aritmética pura sobre `t0`).
- **Unicidade:** ⚠️ **muda de significado sem erro.** `weights.py:81` resolve `idx1` por `searchsorted` no tempo, mas `weights.py:109-110` divide por `span` em **posições de barra**. Com horizonte de relógio fixo, o nº de barras dentro do horizonte varia com a atividade → `span` vira variável → a unicidade média passa a medir parcialmente "quão ativo estava o mercado", não só sobreposição.
  **Contra-evidência empírica direta, medida:** M2 calculou `avg_uniqueness` exatamente sob esta convenção (`time_stop_ms` fixo em 8h, `m2_bar_comparison.py:98-107`) e o resultado foi **essencialmente idêntico** entre grades — BTCUSDT 15m janela recente: `time` 0,030466 vs `dollar` 0,030496 (`experiments/m2_report_recente.json`). Isso é evidência real de que a Opção 2 preserva `N_eff`, **mas só nas 5 janelas de 1 mês medidas** e só porque `target_n_bars` foi calibrado para igualar a frequência média. Não generaliza automaticamente para o histórico completo.
- **Estabilidade de treino:** ✅ o alvo tem a mesma unidade dos custos (fees, funding em janelas de 8h, `adverse_selection_bps`) e do orçamento R3. Nenhum reajuste conceitual.
- **Colisão com o PRD:** ✅ **é o que o PRD já decidiu 3×.** Adotar aqui fecha AG-031 e a pendência I2 do §2.7 no mesmo pacote.
- **Custo colateral:** `n_bars_held` (`triple_barrier.py:828`) precisa virar contagem real de barras (não `ceil((t1-t0)/bar_ms)`), e a invariante `:330` precisa ser substituída por outra (o teto em barras deixa de existir). `Int16` continua folgado; **`n_funding_events: Int8` (`:540`, max 127) fica arriscado** se o horizonte for reexpresso em horas e alguém aumentar. Também exige decidir se `atr_window` acompanha (o PRD diz que sim — mesma I2).

#### Opção 3 — **Híbrido: relógio com piso/teto em barras** (`t1 = clamp(t0 + 8h, t0 + N_min barras, t0 + N_max barras)`)

*Mecânica:* horizonte de relógio como referência, com guardas em contagem de barra dos dois lados.

- **Causalidade:** ✅ intacta (todos os candidatos são futuros e determinísticos).
- **Unicidade:** ⚠️ intermediária — limita a variância de `span` sem fixá-la.
- **Estabilidade:** ✅ o argumento forte: elimina os dois casos patológicos que as opções puras deixam abertos — o label de 40 segundos numa rajada (Opção 2 num pico) e o label de 3 dias numa estiagem (Opção 1 numa madrugada).
- **Custo:** ❌ **dois hiperparâmetros novos** (`N_min`, `N_max`), ambos `class: A` por definição (definem amostra efetiva e teto de features, exatamente como `time_stop_bars`, `constants.yaml:167`), ambos nascendo `ASSUMED`, ambos exigindo varredura ±50% antes do Gate 3 (`CLAUDE.md` regra 4). **Custo em `N_lifetime`: não-zero e não estimado.** Com 15 trials restantes, isso é material.
- **Precedente contra:** o projeto já foi mordido três vezes por parâmetro que carrega escopo implícito (AG-004/005/017/027/031 — 6 ocorrências confirmadas). Adicionar dois parâmetros novos para resolver uma ambiguidade de unidade tem um cheiro conhecido.

#### Opção 4 — **Horizonte em $ acumulado** (`t1` = primeira barra em que o volume negociado desde `t0` excede `K × threshold`)

*Mecânica:* generalização natural da Opção 1, mas com a unidade da própria grade em vez da contagem de barra.

- É **matematicamente equivalente à Opção 1** quando toda barra fecha exatamente no threshold — mas dollar bars fecham quando *excedem* o threshold, não quando batem nele (achado documentado em `src/data/bars.py:200-210`, `base_value`). Ou seja: a Opção 4 é a Opção 1 sem o erro de arredondamento acumulado.
- **Prós:** unidade única em todo o pipeline (grade e horizonte na mesma métrica); imune a reparticionamento (se o threshold mudar, o horizonte em $ não muda de significado — só o nº de barras muda). **Isto interage diretamente com o bloqueador 2 e é a única opção que sobrevive a uma recalibração de threshold sem redefinir o label.**
- **Contras:** nenhuma implementação existe; exige uma coluna cumulativa de $ ao lado das barras; e herda todas as objeções da Opção 1 quanto ao descasamento com fees/funding/R3.

#### Consenso de literatura

AFML (López de Prado, cap. 3) define a barreira vertical em **número de barras** por padrão (`t1 = t0 + numDays` sobre o índice de barras), e mlfinlab implementa assim — mas ambos operam sobre barras de informação em que o autor **assume** que a grade é a unidade natural de amostragem. AFML cap. 2 argumenta explicitamente que barras de dólar têm melhores propriedades estatísticas *porque* amostram por atividade, o que é um argumento a favor de manter o horizonte na mesma unidade (Opções 1/4). **Contra isso:** o custo neste projeto é dominante e vive em relógio civil (fees mensais R3, funding 8h, `adverse_selection_bps`), e o PRD já decidiu relógio 3×. **A literatura não resolve; a economia do projeto e o registro de decisão apontam para a Opção 2. A decisão é do Manager.**

**Dependência que precisa ser dita:** qualquer opção escolhida aqui deve ser aplicada **no mesmo pacote de trabalho** que `atr_window` (mesma I2 do PRD §2.7/§3.2 M1) — AG-031 já recomenda isso, e resolver só metade deixa a barreira dimensionada numa unidade e o horizonte em outra.

---

## 3. Bloqueador 2 — o que "M15/M30/H1" significa sob dollar bars

### 3.1 Como M2 calibrou, exatamente

`src/analysis/m2_worker.py:437` — uma linha:

```python
dollar_threshold = totals.total_dollar / target_n_bars
```

com `target_n_bars = _target_n_bars(symbol, tf, baseline, ...)` = **nº de barras do baseline de klines naquele TF, naquela janela** (`m2_worker.py:140-148`), e `totals.total_dollar` somado em streaming sobre `aggTrades` da mesma janela (`:202-246`).

Ou seja: **o threshold é (volume total em $ da janela) ÷ (nº de barras de tempo da janela)**. Ele é uma função de três coisas — símbolo, TF e **janela** — e a docstring de `m2_bar_comparison.py:81-91` diz isso explicitamente, incluindo o motivo de não haver roll-up: *"dollar/volume/tick-imbalance bars calibradas pra 15m não são 'reagregáveis' em 30m/1h como barras de tempo seriam — roll-up hierárquico não existe pra barra particionada por threshold"* (`:28-31`).

**Medição de deriva que fiz (proxy, declarado como proxy):** bytes comprimidos de `aggTrades` de BTCUSDT por janela de M2 (`du -cb`, shell puro):

| janela | bytes | dias | MB/dia | vs. mínimo |
|---|---|---|---|---|
| LUNA 2022-05 | 530.199.742 | 31 | 17,10 | **2,14×** |
| ETF 2024-03 | 526.899.885 | 31 | 17,00 | 2,13× |
| FTX 2022-11 | 317.824.957 | 30 | 10,59 | 1,32× |
| winter 2023-06 | 308.174.127 | 30 | 10,27 | 1,28× |
| recente 2026-07 | 247.857.326 | 31 | 8,00 | 1,00× |

**Proveniência honesta:** isto mede **contagem de trades** (bytes ∝ linhas), **não** volume em dólar. O threshold real depende de `Σ price×quantity`, que também varia com o nível de preço do BTC (muito maior em 2024/2026 que em 2022) e com o tamanho médio do trade. A deriva real do threshold pode ser maior, menor **ou de sinal oposto** à tabela acima. O comando exato para medir de verdade está na §7 (P-1).

**O que já é certo sem medir:** o threshold **não é o mesmo** entre janelas, porque `total_dollar` obviamente difere e `target_n_bars` é ~fixo (2.976 para 31 dias, 2.880 para 30 dias — confirmado nos 5 relatórios). A pergunta aberta é a magnitude, não a existência.

### 3.2 Opção A — threshold fixo, travado numa data de calibração

*Mecânica:* uma constante por (símbolo, camada de resolução) em `constants.yaml`, calibrada uma vez sobre uma janela declarada, congelada.

- **Prós:** grade **estacionária por construção** — `t0` de uma barra de 2022 significa a mesma coisa que `t0` de uma barra de 2026. Zero risco de vazamento (nada olha para frente). `config_hash` fica trivialmente definível (o threshold entra no payload). Reprocessamento incremental é possível (append-only). É a única opção compatível com um pipeline live simples (o construtor de barra não precisa de estado de calibração).
- **Contras:** desliza silenciosamente. Se o volume estrutural dobrar, a mesma barra cobre metade do tempo de relógio — o nº de barras/dia deriva sem que nada avise. **E não há nenhum monitor para isso hoje** (`src/monitoring/` está vazio). Todo parâmetro em contagem de barra (as 11 janelas de feature, `min_warmup_bars`, `confirmation_bars`, `cpcv_embargo_bars`) herda essa deriva.
- **Sub-opção A′ — fixo + alarme de deriva:** trava o threshold **e** monitora `barras/dia` contra a faixa de calibração, escalando ao Manager quando sair de banda. Custa um monitor novo (que não existe), mas transforma deriva silenciosa em deriva observável. **Mitiga o único contra real da opção A.**

### 3.3 Opção B — recalibração periódica (expansiva ou rolante)

*Mecânica:* recalcular o threshold a cada N (mês/trimestre/ano) sobre a janela **anterior**, estritamente `< t`.

- **Prós:** o nº de barras/unidade de tempo fica ~estável; toda constante em contagem de barra mantém seu significado de relógio aproximado ao longo dos 6,6 anos.
- **Contras — e um deles é grave:**
  1. **Risco de vazamento (B02).** Fazer isso certo exige janela **expansiva estrita `< t`**, exatamente como `expanding_percentile_rank_strict`. Calibrar com dado da própria janela (que foi o que M2 fez — `_scan_trades_totals` soma a janela **inteira**, incluindo o futuro dela) é **B02 literal**. **M2 fez isso deliberadamente e sem problema, porque M2 é medição pós-hoc, não pipeline** — mas a mesma fórmula em produção seria um vazamento.
  2. **Não-estacionariedade de outra natureza.** A grade passa a ter degraus. Um label cujo `t0` está antes do degrau e `t1` depois vive sob duas definições de barra. O purge do CPCV não sabe disso.
  3. **`config_hash` vira uma série temporal**, não um escalar — B15 precisa de redesenho, não de um campo a mais.
  4. Reprocessamento vira não-incremental: mudar uma calibração invalida tudo depois dela.

### 3.4 Opção C — threshold como fração de uma média móvel causal de volume

*Mecânica:* `threshold_t = f(EWMA causal do volume em $)`, atualizado continuamente em vez de em degraus.

- **Prós:** sem degraus; causalidade auditável se a EWMA for estrita `< t`; adapta-se suavemente.
- **Contras:** a grade passa a depender de um hiperparâmetro novo (o span da EWMA) que é `class: A` por construção. **Barra deixa de ser reproduzível a partir só dos trades** — precisa do estado da EWMA, o que quebra a propriedade que `src/data/bars.py:22-36` documenta como sua garantia de causalidade ("`bar_id = floor(cumsum/threshold)` é monotônico"). Paridade lote↔streaming (hoje garantida **por construção**, `bars.py:285-293`) passa a exigir replay de estado. **Custo de engenharia desproporcional.**

### 3.5 Opção D — abandonar "M15/M30/H1" e adotar camadas de resolução

*Mecânica:* a decisão passa a ser "quantas barras por unidade de tempo, em média, na calibração" — três camadas (baixa/média/alta granularidade) nomeadas pelo que são, não por minutos.

**Argumento a favor, o mais forte desta seção:** hoje "M15" sob dollar bars é uma **mentira operacional**. `m2_worker.py:437` define a "dollar bar de M15" como "a que dá o mesmo nº de barras que M15 deu naquela janela". Não há 15 minutos em lugar nenhum — só um número de barras herdado. Manter o nome "M15" garante que alguém, em alguma sessão futura, vai reler "M15" como "15 minutos" e errar. **Este projeto já tem 6 ocorrências confirmadas dessa exata classe de defeito** (AG-004/005/017/027/031).

- **Prós:** o nome passa a descrever a coisa; força a declaração explícita do que cada camada significa; e o vocabulário `scaling_invariant` (`clock`/`bar_count`/+`activity`) encaixa naturalmente.
- **Contras:** `PRD_V4_1.md:72` diz literalmente *"**Três timeframes** — M15, M30, H1 — obrigatórios ponta a ponta"* e `:774` repete como decisão do Manager. Renomear é emenda formal ao PRD. Além disso, **M3 escolheu 15m medindo em barra de tempo** (`PRD_V4_1.md:398-406`, tabela `janela_viavel_fraction` por TF, com o achado de que BTC é não-monotônico e o ponto-doce fica em 30m) — a escolha de "qual camada" pode não sobreviver à mudança de grade, e M3 teria de ser reavaliado. Isso é escopo, não cosmética.
- **Meio-termo:** manter três camadas com o **nome atual** mas com uma constante explícita `dollar_bars_target_per_day` por camada, e uma nota permanente de que "M15" é rótulo histórico. Custo baixo, ganho parcial.

### 3.6 O que fica em aberto e precisa de decisão do Manager

1. Threshold **por símbolo** ou **compartilhado**? Hoje é por símbolo por construção (`m2_worker.py:437` roda por símbolo). Compartilhado é impensável (volume varia 3.700× entre os 5, `PRD_V4_1.md:162`). Mas **por símbolo significa que os 5 ativos fecham barras em instantes diferentes** — ver §5.2.
2. O `grade_id` (símbolo + camada + threshold + data de calibração) precisa existir como identidade versionada e entrar no `config_hash` (`triple_barrier.py:267-277`), no caminho em disco (`_paths.py:43-45`) e no `experiment_log` (`experiment_log.py:42-71`). **Sem isso, B15 fica furado.** Isto é pré-requisito de qualquer opção acima, não uma opção em si.
3. A opção do bloqueador 1 e a opção deste bloqueador **não são independentes**: se o horizonte do label for em $ (Opção 4 da §2), uma recalibração de threshold não redefine o label; se for em contagem de barra (Opção 1), redefine.

---

## 4. Bloqueador 3 — AG-032: embargo do CPCV sob dollar bars

### 4.1 Contexto quantificado

- Valor atual: `cpcv_embargo_bars = 175` (`config/constants.yaml:917-923`, `provenance: LITERATURE`, `class: C`, `sweep_required: false`, `review_by: sprint_10`).
- **175 barras × 15 min = 2.625 min = 43,75 h** (o próprio `source:` da constante já registra isso, junto com a discrepância de que o PRD anotou "≈88h", que só fecha a 30m).
- **Piso mecânico de AG-032: 128 barras = `time_stop_bars` (32) + `feature_c06_vol_ratio_long_window` (96).** **128 × 15 min = 1.920 min = 32,0 h.** 175 cobre com folga de 47 barras (~27%).
- Mecânica que produz o piso: `purge_mask` (`cpcv.py:383`) só atua sobre linhas com `t0 <= g_end`; qualquer linha com `t0 > g_end` **nunca é purgada** (porque `t1 > t0` sempre). A fronteira `g_end` vem só da partição de `t0` (`assign_time_groups`, `cpcv.py:161-194`) e **nunca referencia o `t1` real das linhas de teste**, que pode esticar até `g_end + time_stop_bars`. Esse resíduo só é removido pelo embargo. Somado ao lookback de feature (96), dá 128.
- **Lado esquerdo/trás** (`cpcv.py:386`) **não tem derivação mecânica** — continua o buffer heurístico de correlação serial ("1% do fold", López de Prado, `PRD_V3_2_UNIFICADO.md:3134`).
- AG-032 já registra um risco de multi-TF que a migração torna mais agudo: *"`embargo_bars` é hoje escalar único aplicado a M15/M30/H1 sem escalonamento — se M2/M3 rodar CPCV real em 30m/1h, o mesmo 175 produz 87,5h/175h de embargo real, nunca avaliados"*.

### 4.2 O que muda sob dollar bars

`_embargo_ms(cfg) = config.embargo_bars * step_ms(config.tf)` (`cpcv.py:255`) é **contagem de barra × duração assumida constante**, e o resultado é aplicado como **distância temporal** em `:385-386`. Sob dollar bars:

- `step_ms(tf)` não existe → o código **não roda** (`UnsupportedTimeframeError` já em `CPCVConfig.__post_init__`, `cpcv.py:138`).
- Mesmo resolvendo isso, a pergunta de fundo muda: **175 barras passam a ser uma duração variável de relógio**, e o embargo protege contra correlação serial, que é um fenômeno de **relógio** (informação vaza através do tempo, não através de contagem de amostra). Mas o resíduo não-purgado que o embargo cobre é medido em **contagem de barra** (32 + 96) — ou seja, o embargo tem que cobrir **duas coisas de unidades diferentes ao mesmo tempo**. Isso não é novo (AG-032 já registra as duas justificativas como *"CONCORRENTES e incompatíveis pro mesmo número"*), mas sob dollar bars deixa de ser reconciliável por coincidência.
- **Complicação adicional que a migração cria:** `assign_time_groups` (`cpcv.py:177`, `np.linspace`) parte por **largura de tempo igual**. A justificativa escrita (`cpcv.py:13-20`) é a densidade ~constante de barras de 15m. Sob dollar bars a densidade é proporcional à atividade → grupos com contagens de linha muito diferentes → o embargo de N barras remove uma fração muito diferente de cada grupo.

### 4.3 As opções

| # | opção | causalidade / cobertura | prós | contras |
|---|---|---|---|---|
| **E1** | **Embargo em relógio fixo** (`embargo_ms` vira constante direta, ex. 43,75h) | cobre correlação serial corretamente (fenômeno de relógio); **não** garante cobertura do resíduo de `time_stop` se o horizonte do label for em barras | conversão trivial (`_embargo_ms` vira `return config.embargo_ms`); imune a deriva de threshold; **é a única opção que não depende de `step_ms`** | se o horizonte do label for em barras (Opção 1 do bloqueador 1), o resíduo não-purgado deixa de ter cota de relógio → **pode subcobrir** |
| **E2** | **Embargo em contagem de barra** (175 dollar bars) | cobre o resíduo de `time_stop`+lookback por construção se ambos forem em barras; cobertura de relógio vira variável | mantém a fórmula 128 de AG-032 intacta e auditável; casa com `scaling_invariant: bar_count` de `feature_c06` | numa estiagem de atividade, 175 barras podem virar dias de embargo (remove treino demais); numa rajada, minutos (embargo insuficiente para correlação serial) |
| **E3** | **max(relógio, barras)** — as duas condições, aplicadas em conjunção | ✅ cobre as duas causas simultaneamente, sem escolher uma | é a única que responde honestamente ao fato de que existem **duas** justificativas incompatíveis para o mesmo número: em vez de escolher, satisfaz as duas | remove mais treino que qualquer uma isolada; introduz **dois** parâmetros — mas ambos derivados, nenhum novo em espírito |
| **E4** | **Corrigir o purge em vez do embargo** (`purge_mask` passa a usar o `t1` real das linhas de TESTE, não só `g_end`) | ✅ fecha o resíduo na origem; o embargo volta a ter uma única razão de existir (correlação serial), e aí E1 é obviamente a resposta | **resolve a ambiguidade em vez de administrá-la**; AG-032 já lista isso como decisão pendente do Manager; torna o piso 128 obsoleto por construção | é mudança de código de produção real em `cpcv.py`, com efeito sobre todo split já gerado; exige rerodar a suíte |

**Nota de sequenciamento:** E4 é a única opção que **reduz** a superfície de decisão em vez de aumentá-la, e ela é ortogonal à escolha do bloqueador 1 — ou seja, pode ser decidida antes, e simplifica as outras três. Não é recomendação; é registro de que a ordem importa.

**Interação com AG-032 que precisa ser dita:** a entrada recomenda hoje *"manter `provenance: LITERATURE`, NÃO reclassificar pra DERIVED"* e *"registrar 128 como piso mecânico mínimo a checar antes de qualquer redução no Sprint 10"*. **Sob dollar bars, o número 128 deixa de ser um piso computável a priori** — `feature_c06_vol_ratio_long_window` continua 96 barras, mas `time_stop_bars` pode deixar de ser expresso em barras (Opções 2/3/4 do bloqueador 1). A recomendação de AG-032 precisa ser reescrita junto com a decisão do bloqueador 1, não depois dela.

---

## 5. Os 4 pontos sinalizados pelo Manager

### 5.1 Construção de dollar bar em tempo real / produção

**O que existe:** `src/data/bars.py` inteiro — e é melhor do que se poderia esperar para o uso live, por acidente feliz do desenho de streaming:

- `dollar_bars_carry` / `threshold_bars_step` / `threshold_bars_finish` (`bars.py:219-283`) são **exatamente a forma de um agregador incremental**: estado inicial, passo sobre um chunk, finalização. Um feed WebSocket é só um chunk de tamanho 1..N.
- `bars.py:285-293` — a versão em lote é um wrapper fino sobre o mesmo caminho, então **paridade lote↔streaming é garantida por construção, não por teste**. Para um sistema em que "mesmo código em backtest e live" é requisito declarado, isso é a peça mais valiosa que já está pronta.
- `bars.py:22-29` — a prova de causalidade é sobre `cumsum` monotônico, válida trade-a-trade, não sobre grade.
- O `leftover` (`bars.py:261`) nunca cresce além dos trades de uma barra aberta — footprint de memória em live é trivial.

**O que falta — e é tudo o resto:**

| lacuna | evidência |
|---|---|
| **Nenhum stream de trade é assinado.** `build_combined_stream_url` (`ws.py:53,58`) tem zero callers de produção; os únicos literais `@aggTrade`/`@kline_15m` do repo estão em `tests/unit/test_exchange_ws.py:55` | grep repo-wide |
| **Nenhuma biblioteca de WebSocket e nenhum transporte.** `WebSocketTransport` é `Protocol` sem implementação; nada no `pyproject.toml` | `ws.py:13-14,40` |
| **Nenhum parser de payload.** Zero `"x"`, `is_closed`, `"k"]`, `ORDER_TRADE_UPDATE` em `src/` | `ws.py:6-8` |
| **Nenhum loop de reconexão.** `ReconnectPolicy.next_delay_s()` sem caller | `ws.py:229-247`, só `.reset()` em `:279` |
| **Nenhum número de sequência, gap detection, resync ou dedup.** Zero ocorrências de `agg_id`/`lastUpdateId`/`resync`/`dedup` em `src/exchange/` | grep |
| **Nenhum loop live.** `src/live/` = 3 linhas; `scripts/` vazio | `src/live/__init__.py` |
| **Nenhum consumidor que rode o Quality Gate por barra em live** | `kill_switch.py:184-186` (K08) |

**Por que isso é qualitativamente pior que com klines.** Uma barra de tempo é **auto-corretiva**: se você perder trades entre 14:00 e 14:15, a kline de 14:15 que a Binance entrega ainda está certa, porque a Binance agregou do lado dela. Uma dollar bar é **cumulativa e path-dependent**: um único trade perdido desloca `base_value` (`bars.py:268`) e **toda barra subsequente fecha no lugar errado, para sempre**, sem nenhum sintoma local. Não há como detectar isso a posteriori sem reconciliar contra o histórico. Esta é a diferença estrutural entre os dois mundos, e ela não aparece em nenhum documento do projeto hoje.

**Implicações concretas de desenho (sem escolher uma):**
- O contrato de reconexão precisa ser: reconectar → **rebaixar o `carry` e reconstruir a barra em aberto a partir do REST** (`aggTrades` histórico por `fromId`), não simplesmente retomar. Isso exige um endpoint que o `ExchangeAdapter` não expõe (`adapter.py:31-81`).
- `aggTrade` da Binance carrega `a` (aggregate id) contíguo — dá para detectar gap por continuidade de id, que é mais forte que timestamp. Mas nenhum código do repo lê esse campo.
- Precisa existir um teste de paridade **live↔backtest** sobre a construção de barra que hoje não existe em nenhuma forma (grep por `parid|parity|bit.exact` em `exchange/`,`live/`,`execution/`,`monitoring/`,`risk/` → **zero hits**). `fill_simulator.py:465` (*"mesma grade da decisão real do sistema"*) é a única afirmação de paridade de grade em código, e é uma afirmação de relógio que passa a ser falsa.
- `on_timeout: CANCEL` (B13), `time_in_force: GTX` e o timeout de fill (`fill_timeout_bars=1`) precisam ser reexpressos em relógio, não em barra — sob dollar bars "1 barra" pode ser 3 segundos.

### 5.2 Dessincronia entre os 5 ativos

**Resposta direta à pergunta: não encontrei nenhum módulo que faça join cross-símbolo por timestamp compartilhado.** Isso é um achado positivo, e verificado exaustivamente:

- **M6 (fator comum) não usa índice de tempo compartilhado.** `src/analysis/m6_common_factor_hypothesis.py:300-304` faz fan-out por símbolo em `ProcessPoolExecutor`; `:313-315` agrega **escalares** (`edge_bruto_atr` por `(symbol, side)`); `:193-202` é Cochran's Q sobre esses escalares. Nenhum timestamp é comparado entre símbolos.
- **O Regime Engine é estritamente single-symbol** (`src/regime/build.py:48-52`, `classifier.py:428,431-436`). Não usa BTC como driver.
- **`src/features/` é single-symbol** — zero ocorrências de `ETHUSDT|SOLUSDT|BNBUSDT|XRPUSDT|SYMBOLS` no pacote.
- **`src/validation/` e `src/backtest/` são single-symbol** — `cpcv.load_labels_v1(symbol=...)`, um símbolo por chamada.
- Todos os demais módulos multi-símbolo seguem o mesmo padrão: fan-out por processo, agregação por dicionário chaveado em símbolo.

**Mas há três coisas que não são "join cross-símbolo" e mesmo assim quebram ou degradam:**

1. **A coincidência de calendário INTRA-símbolo.** `src/models/dataset.py:113-135` documenta o bug histórico e o texto é o achado: *"timestamps batem por **coincidência de calendário**, não por serem do mesmo ativo"*. Hoje o `symbol=` já é passado corretamente aos três engines. **Mas os três engines precisam ser construídos sobre a MESMA grade dollar-bar do MESMO símbolo, e nada verifica isso.** O join é por igualdade exata de ms (`:151,155`), o resultado é `how="left"`, os nulos são apenas contados (`:171-172`) e depois **filtrados** por `side_subset` (`:207-213`). Uma incompatibilidade de `grade_id` entre features e labels produz um frame quase vazio, com log em `info`. Sob barra de tempo, um erro assim produzia um frame *errado mas cheio* (detectável em revisão); sob dollar bars produz um frame *vazio* (detectável só se alguém olhar `n_rows`). **É o risco de regressão mais provável de toda a migração.**

2. **Os pesos de meta-análise de M6 mudam sem que o edge mude.** `m6_common_factor_hypothesis.py:112-115` — `var_tp = frac_tp*(1-frac_tp)/n`, com `n` = nº de linhas de label do símbolo; `:200` — `w_i = 1/SE_i²`. Sob dollar bars, `n` por símbolo passa a ser função do volume negociado daquele ativo, não do calendário. **A ponderação relativa entre BTC e os alts em M6 muda por razão puramente aritmética.** O resultado atual de M6 (H0 rejeitada nos dois lados, `I² = 96,1%`/`97,8%`, `PRD_V4_1.md:446`) é robusto o bastante para provavelmente sobreviver, mas o número muda.

3. **O `N_eff` agregado de 5 ativos (§4.2 do PRD).** `PRD_V4_1.md:487` — *"a unicidade é calculada por série. Com 15 combinações, o mesmo movimento aparece em quinze — a `N_eff` agregada é ~1,15× a de uma série, não 15×"*, ancorado no fator efetivo medido de **1,15 de 5** (`PRD_V4_1.md:200,635`, participation ratio dos autovalores da correlação de log-retornos 15m, `:189`). **Essa correlação foi medida sobre log-retornos de 15m — barra de tempo.** Sob dollar bars, os retornos dos 5 ativos passam a ser amostrados em instantes diferentes, e correlação contemporânea entre séries amostradas em relógios diferentes **é sistematicamente atenuada** (efeito Epps). Ou seja: o `1,15` pode subir artificialmente (parecendo mais diversificação do que existe) sem nenhuma mudança econômica. Isso alimenta o teto de features (R4) e o `N_trial` ponderado (`PRD_V4_1.md:638`, *"1,15 × ~1,5 ≈ 1,7 trials por hipótese"*). **É um número de governança que ficaria enviesado na direção permissiva.**

**Opções para o item 3, se alguma comparação cross-asset for feita sob dollar bars:** (a) medir a correlação sobre uma grade de tempo comum derivada (reamostrar as dollar bars de cada símbolo para um relógio comum antes de correlacionar) — preserva a comparabilidade mas descarta o benefício da grade; (b) usar um estimador robusto a assincronia (Hayashi-Yoshida) — correto, mas é código novo e nenhum precedente no repo; (c) declarar como limitação conhecida e não usar `1,15` sob a grade nova até remedir. **Nenhuma é gratuita.**

**E AG-030 continua aberto e precede tudo isso** — o confundimento de janela expansiva entre ativos já exige decisão do Manager *antes* de qualquer comparação cross-asset estratificada por regime, independentemente da grade.

### 5.3 Custo de reprocessamento em escala real

**Medições diretas (disco, `du`/`ls`, shell puro):**

| fonte | tamanho | arquivos | janela |
|---|---|---|---|
| `data/capacity/agg_trades/` **total** | **60,998 GB** | 9.256 | — |
| ↳ BTCUSDT | 26,34 GB | 2.412 | 2019-12-31 → 2026-08-07 |
| ↳ ETHUSDT | 19,51 GB | 1.711 | 2021-12-01 → 2026-08-07 |
| ↳ SOLUSDT | 6,59 GB | 1.711 | idem |
| ↳ XRPUSDT | 4,35 GB | 1.711 | idem |
| ↳ BNBUSDT | 4,20 GB | 1.711 | idem |
| `data/capacity/klines_1m/` total | 0,507 GB | 9.246 | mesma cobertura |
| `data/` inteiro | ~144,6 GB | — | — |

**Multiplicador de entrada bruta: 120× (61 GB vs 0,507 GB) no agregado; 182× só para BTCUSDT** (26,34 GB vs 144,6 MB, mesmo intervalo de datas, mesmo nº de arquivos).

**Contagem de trades, medida (não extrapolada):** `src/data/bars.py:76-82` registra a medição real via `tools/diagnostics/measure_btcusdt_trade_rate.py` sobre os 2.412 arquivos: **3.385.807.729 trades** para BTCUSDT, taxa média **1.403.735 trades/dia**.

**A evidência que quantifica o risco melhor que qualquer estimativa — a tentativa real:**

- **O run canônico de M2 sobre o histórico completo nunca terminou.** `experiments/m2_bar_comparison_report.json` está com `"partial": true`, **6 de 60 células preenchidas**, 54 com `"n_bars": 0`. As 6 que completaram são **todas** `bar_type="time"` (SOLUSDT e XRPUSDT, 3 TFs cada) — ou seja, só o caminho barato de klines. **Zero células dependentes de trade jamais completaram sobre o histórico completo, para nenhum símbolo.**
- **Duas tentativas, duas causas raízes diferentes, nenhuma o mesmo bug:**
  - **AG-033** (**corrigido**): colisão de nome de arquivo de overflow do DuckDB entre os 12 processos — 9 de 20 tasks morreram. Corrigido com `temp_directory` único por PID (`lake.py:161-175`).
  - **AG-034** (**fechado por decisão do Manager sem corrigir, risco aceito**): travamento de 9h+ sem nenhuma linha de log nova, hipótese de esgotamento de RAM real — `SET memory_limit` não governa os DataFrames Polars/Arrow, nem o `carry`/`bar_frames` acumulado ao longo de até 81 chunks, nem 12 interpretadores Python. **Não foi verificada.** O status registra literalmente: *"o esgotamento de memória sob concorrência plena é uma restrição real da máquina que volta a valer se algum dia o histórico completo precisar ser reprocessado em dollar bars pra produção … Reabrir nesse momento, não antes."* **Esse momento é agora.**
- Orçamento de máquina de referência: ~28 GB livres, `os.cpu_count() = 12`. `m2_duckdb_memory_limit_gb = 2.0` × 12 = 24 GB — sem contar (a) os frames Polars materializados fora do DuckDB, (b) o estado acumulado do streaming, (c) 12 interpretadores + cache Numba.

**Escala do salto.** M2 mediu 5 janelas × ~31 dias ≈ **152 dias por símbolo**. O histórico é **2.412 dias** (BTC) e 1.711 (alts) — **~16× mais dias para BTC**, e M2 só conseguiu processar as janelas pequenas *uma de cada vez, com relatório separado por janela*. Custo observado ≈ **10 min por janela**. Uma extrapolação linear ingênua daria ~2,6 h por símbolo, **mas a extrapolação linear é exatamente o que não vale aqui**: as duas falhas reais foram de *memória e concorrência*, não de tempo de CPU, e ambas escalam com o tamanho do estado acumulado dentro de cada task, não com o nº de dias processados.

**Riscos concretos, não hipotéticos:**
1. Se AG-034 estiver certo, **rodar de novo com a mesma configuração reproduz o travamento**.
2. `carry.bar_frames` (`bars.py:216`) acumula **todas** as barras fechadas em memória Python até o `finish()`. Para o histórico completo de BTC a 15m-equivalente isso são ~231 mil linhas — pequeno. Mas o `carry` também vive ao lado de até 81 chunks de `aggTrades` sequenciais, e é o *pico* que mata, não o total.
3. O reprocessamento não é só `bars.py`: é `bars` → `features` → `regime` → `labels` → `predictions` para **5 símbolos × 3 camadas**, com o Feature/Label Engine ainda nunca tendo rodado para os 4 alts.

**Não é solução proposta — é quantificação.** Os três caminhos que AG-034 lista continuam válidos e nenhum foi escolhido: (1) reduzir concorrência; (2) medir RSS real durante a próxima tentativa (0 código); (3) descarregar `carry`/`bar_frames` em disco incrementalmente. A recomendação registrada em AG-034 é (2) primeiro. **Uma 4ª opção que a migração torna possível e que não existia quando AG-034 foi escrito:** um pipeline de produção precisa de escrita **incremental por dia** de qualquer jeito (para poder retomar), e isso resolve o problema de memória como efeito colateral do desenho correto, não como mitigação. Isso favorece a Opção A do bloqueador 2 (threshold fixo → append-only) e desfavorece a B (recalibração → invalidação retroativa).

### 5.4 HHI / concentração (§5.8) e orçamento de `N_lifetime`

**Onde estão os limiares, exatamente:**
- `src/models/pipeline.py:531` — `"gate3_4_hhi_lt_025": mean_hhi_effective < 0.25,  # noqa: magic-number`
- `src/models/pipeline.py:536` — `"gate3_4_hhi_nominal_lt_025_reference": mean_hhi_nominal < 0.25,  # noqa: magic-number`
- `src/models/pipeline.py:537` — `"gate3_4_max_share_lt_030": _mean_finite(max_share_values) < 0.30,  # noqa: magic-number`
- **`grep -i hhi config/constants.yaml` → vazio.** Nenhuma proveniência declarada, nenhuma classe, nenhum `sweep_required`. Para um critério de Gate 3/4, isso é uma lacuna independente da migração (achado H).

**A calibração original está escrita e é explicitamente para p=10:** `PRD_V3_2_UNIFICADO.md:1253` — *"HHI de importância | **< 0,25** | com 10 features, HHI uniforme = 0,10; 0,25 ≈ 4 features efetivas"*.

**Análise honesta — o limiar não é tão frágil quanto a pergunta sugere, mas o gate composto é:**

1. **O limiar 0,25 é invariante em p na leitura que importa.** `hhi_effective = 1/N_eff` (`hhi.py:234,319-320`), então `hhi_effective < 0,25 ⟺ N_eff > 4`, **independentemente de quantas features existam**. A leitura "≈ 4 features efetivas" não decai.
2. **O que decai é a exigência relativa ao piso alcançável.** Com p=10 o piso é 0,10, e passar exige ficar a no máximo 2,5× do piso. Com p=13 o piso é 0,077 (3,25×). Com p=64 o piso é 0,0156 (**16×**). Um modelo pode passar com `N_eff = 4,1` usando 6% do espaço que recebeu.
3. **O critério do PRD que existia justamente para pegar isso não é implementado como gate.** `PRD_V3_2_UNIFICADO.md:1253-1256` lista **quatro** critérios: HHI < 0,25 · maior share < 0,30 · **features com share > 1% ≥ 6** · **deriva de HHI entre janelas WF < 0,10**. O terceiro é *"o modelo usa o espaço que recebeu"* — exatamente a pergunta. Ele é **computado e reportado** (`pipeline.py:517` `mean_n_features_over_1pct`, via `hhi.py:131` `n_over_1pct`) mas **não tem booleano `gate3_4_*`**. O quarto (deriva WF) não aparece em `pipeline.py` de forma alguma.
4. **`max_share < 0,30` afrouxa mecanicamente com p.** Mais features competindo pelo mesmo `total_gain` derrubam o máximo por aritmética, não por diversificação.
5. **A defesa que já existe é real e vale registrar:** o gate decide sobre o HHI **efetivo**, não o nominal (D3, `pipeline.py:527-530`), e `hhi_effective = Σ_i w_i² + Σ_{i≠j} w_i w_j ρ_ij² ≥ hhi_nominal` **sempre** (prova em `hhi.py:237-248`). Ou seja: **adicionar features redundantes não dilui o HHI efetivo** — só adicionar features genuinamente ortogonais dilui. Isso protege contra a forma mais comum do artefato. O problema residual é (2)+(3): o gate deixa de discriminar entre "usa 4 de 10" e "usa 4 de 64", e o critério que faria essa distinção não está ligado.
6. **Assimetria de denominador não documentada:** `alpha.py:279` computa o HHI **nominal** sobre as 14 `DESIGN_COLUMNS` (features + dummies de regime), e `:286-288` o **efetivo** sobre as 10 `T1_FEATURE_IDS` só. Os dois números aparecem lado a lado no relatório com denominadores diferentes. Com o vetor expandido isso piora.

**Opções:** (a) manter 0,25 e **ligar** o 3º critério do PRD (`n_features_over_1pct >= 6`) como gate — custo zero, o número já é computado; (b) reexpressar o limiar como razão ao piso (`hhi_effective < k/p`), o que preserva a exigência relativa mas **muda o significado** de "4 features efetivas" e não tem base em lugar nenhum; (c) mover 0,25/0,30 para `constants.yaml` com `provenance: LITERATURE` e `review_by`, resolvendo a lacuna de governança independentemente da decisão numérica; (d) medir o HHI efetivo real sob o vetor expandido antes de mexer no limiar (0 trials — é medição descritiva sobre modelo já treinável, não busca).

**Orçamento de `N_lifetime`:**
- `audit/n_lifetime.yaml::counter = 45`; teto **60**; critério de encerramento #5 (`PRD_V4_1.md:671`): *"`N_lifetime > 60` sem Camada 2 fechada → encerrar — orçamento exaurido"*. **15 trials restantes.**
- **A expansão do vetor de features, por si só, não consome `N_lifetime`** — não é busca, é mudança de definição do vetor canônico. Precedente direto no ledger: id 11 (`n_lifetime.yaml`), 70 candidatas T2 avaliadas em bloco, *"Contado como 1 trial por instrução explícita do Manager ('conta como 1 trial, não um por feature') — não 70"*.
- **O que consome:** (i) o retreino do Alpha com o vetor novo é um retreino → o ledger diz *"Incrementa em: … cada retreino"*; (ii) qualquer sweep de janela de feature (§1.3) — 11 janelas × 3 valores seria 33 trials, **mais que o dobro do orçamento restante**; (iii) qualquer varredura de `time_stop_bars` (`sweep_range: [16,48]`, `class: A`) ou de `cpcv_embargo_bars`; (iv) qualquer varredura do threshold de dollar bar.
- **Ponto de tensão real:** as constantes `class: A` ainda `ASSUMED` são **13** (confirmado via `check_constants_provenance.py`): `cost_stop_ratio_max`, `fee_budget_monthly`, `tp_atr_mult`, `sl_atr_mult`, `time_stop_bars`, `atr_window`, `regime_er_cutoff`, `regime_vol_cutoff`, `adverse_selection_bps`, `regime_vol_cutoff_exit`, `regime_er_cutoff_exit`, `max_notional_multiple`, `alpha_stability_screen_limiar`. A regra 4 do `CLAUDE.md` exige varredura ±50% de **toda** classe A antes do Gate 3. **13 varreduras não cabem em 15 trials junto com um retreino.** Isso não é criado pela migração — é preexistente — mas a migração torna 2 delas (`time_stop_bars`, `atr_window`) urgentes por outro motivo, e adiciona pelo menos 1 candidata nova (o threshold da grade). **Vale escalar ao Manager como pergunta de Business Case, não resolver aqui.**
- **Dado que reforça a decisão de expandir o vetor (a favor):** o teto de features de R4 foi **medido** — `N_eff` (Σ unicidade) = **32.608 (long) / 32.236 (short)**, acima do topo da faixa que o PRD especulava (3.241–20.740), com teto de features resultante de **65-163** (`docs/SPRINT_LOG.md:180-182,1340`). O vetor de 10 é conservador por larga margem. **Ressalva importante:** esse `N_eff` foi medido sobre labels de barra de tempo com horizonte de 32 barras = 8h. Sob dollar bars ele muda — e a evidência de M2 (§2.3, Opção 2) sugere que **se o horizonte ficar em relógio fixo, `N_eff` é aproximadamente preservado**; se o horizonte virar contagem de barra, não há medição.

---

## 6. Débito de documentação

Trechos hoje contraditos pelas duas decisões. Só listados — não corrigidos.

### Contraditos pela decisão (A) `canonical_bar_type = "dollar"`

| arquivo:linha | trecho | por quê |
|---|---|---|
| `PRD_V4_1.md:72` | *"**Três timeframes** — M15, M30, H1 — obrigatórios ponta a ponta."* | "timeframe" pressupõe duração de relógio; sob dollar bars os três são camadas de resolução calibradas por threshold (bloqueador 2) |
| `PRD_V4_1.md:774` | `\| 2 \| 3 timeframes obrigatórios ponta a ponta \| decisão do Manager \|` | idem |
| `PRD_V4_1.md:23` | *"A restrição R1 (quantização), que escolheu 15m, eliminou 30m/1h/2h/4h, derivou `risk_per_trade = 0,50%`"* | toda a análise de R1/R2 foi feita sobre ATR de barra de tempo |
| `PRD_V4_1.md:37,45,47` | tabelas `ATR 15m` / *"série completa por ativo, `decision_tf=15m`"* | medições em grade de tempo |
| `PRD_V4_1.md:174-185` (§2.7 I2) | tabela `M15 5,0h / M30 10,0h / H1 20,0h` e *"o estimador precisa ser recalibrado por TF, com o horizonte em relógio fixo e a janela em barras derivada"* | a tabela pressupõe TFs de relógio; a decisão I2 continua válida em espírito mas o eixo mudou |
| `PRD_V4_1.md:398-406` (§3.2 M3) | tabela `janela_viavel_fraction` por TF + *"BTC é o único ativo em que subir de TF não melhora monotonicamente"* | M3 escolheu 15m medindo sobre barra de tempo; a escolha pode não sobreviver |
| `PRD_V4_1.md:446` (§3.2 M6) | *"`decision_tf=15m`"* no resultado de M6 | idem |
| `PRD_V4_1.md:487` (§4.2) | *"a `N_eff` agregada é ~1,15× a de uma série"* e `PRD_V4_1.md:200,635` (`fatores_efetivos = 1,15`) | medido sobre correlação de log-retornos **de 15m**; sob amostragem assíncrona sofre atenuação tipo Epps (§5.2 item 3) |
| `PRD_V3_2_UNIFICADO.md:824` | `time_stop_bars: 32  # 8h a 15m — uma janela de funding` | "8h a 15m" deixa de valer |
| `PRD_V3_2_UNIFICADO.md:829` | *"Com 16 barras (8 horas), a concorrência é `1 + (2×16 − 1) = 32`, a amostra efetiva é 3.240 e o teto sobe para 7–16 features"* | aritmética inteira presume barra de duração fixa (e já está superada por `N_eff` medido = 32.608) |
| `PRD_V3_2_UNIFICADO.md:1725,1733` | bloco YAML `bars: 32  # 8h a 15m` + a correção de auditoria de 2026-08-09 | idem |
| `PRD_V3_2_UNIFICADO.md:2090` | `bars: 175  # ~1% do fold, ≈ 88h` | 175 barras ≠ 88h a 15m (já registrado em `constants.yaml:920`); sob dollar bars nem tem valor único |
| `PRD_V3_2_UNIFICADO.md:2925` | *"IC entre cada feature e o retorno futuro de 32 barras (8h, igual ao `time_stop`)"* — §17.2 | a âncora 32b/8h que AG-031 discute |
| `PRD_V3_2_UNIFICADO.md:2198` | `\| 9 \| look-ahead em resample \| agregação 1m→30m fecha em close_time \| invalida \|` | o teste 9 dos 14 de leakage tem como sujeito um componente que sai do caminho crítico (`leakage.py:479-517`) |
| `PRD_V3_2_UNIFICADO.md:3160` | `\| time_stop_bars \| 32 (8h) \| justifiquei por "uma janela de funding" \|` | idem |
| `features/registry.yaml:47-59` | *"A 30m, 48 barras = 1 dia; a 15m, as mesmas 48 barras = 12h"* | a nota está **certa** e continua sendo o melhor aviso do repo, mas só enumera dois mundos; falta o terceiro |
| `features/registry.yaml` (13 entradas, campo `tf`) + `tests/unit/test_features_build.py:226-232` | `assert entry["tf"] == "15m"` para toda entrada | o teste falha assim que uma entrada mudar de grade |
| `src/execution/fill_simulator.py:465` | `# Grade de decisão a 15m (mesma grade da decisão real do sistema, §0.1)` | **é código, não doc, mas é a afirmação de paridade mais forte do repo e passa a ser falsa** |
| `src/data/resample.py:32-35` | *"é a própria definição de calendário do timeframe nomeado (1h SEMPRE tem 60 minutos), por isso não entra em `constants.yaml`"* | o raciocínio continua correto para o resample; o que muda é que o resample deixa de definir a grade canônica |
| `docs/refactor_gk_canonico.md:198-211` | *"adiar até M2 (barra) e M3 (timeframe) fecharem … M2 pode trocar o tipo de barra"* | o gate agora está satisfeito (`constants.yaml:203-211` já anota); o texto de `refactor_gk_canonico.md` não |
| `PRD_V4_1.md:368` (§3.2 M1) | *"cada estimador é calibrado com horizonte em relógio fixo e janela em barras derivada por TF"* | M1 rodou com `atr_window=20` **fixo em contagem de barra** nos 3 TFs (ressalva já herdada, `PRD_V4_1.md:378`); sob dollar bars a ressalva se agrava |

### Contraditos pela decisão (B) T1 → registry inteiro

| arquivo:linha | trecho |
|---|---|
| `PRD_V3_2_UNIFICADO.md:707` | cabeçalho de seção: *"## 2.13 O vetor T1 — **as 10 features do Alpha V1**"* |
| `PRD_V3_2_UNIFICADO.md:630` | *"T1 passa de 12 para 10 features, dentro do teto medido de N_eff (§0.2 R4)"* |
| `PRD_V3_2_UNIFICADO.md:1253` | *"com **10 features**, HHI uniforme = 0,10; 0,25 ≈ 4 features efetivas"* — **a calibração do gate de HHI** |
| `PRD_V3_2_UNIFICADO.md:2522` | *"5. 10 features T1 com registro completo e prova de causalidade"* (Definition of Done) |
| `PRD_V3_2_UNIFICADO.md:2563` | *"4 unidades de granularidade, 1,4 trade por dia de orçamento, **10 features de teto**"* |
| `PRD_V3_2_UNIFICADO.md:3488-3489` | *"T1: 12 → 10 features"* e *"`monotone_constraints`, bagging por grupo conceitual (Camada 3) e HHI de concentração **atualizados para 10 features**"* |
| `PRD_V3_2_UNIFICADO.md:2329` | *"Concentração (§5.8): HHI < 0,25 · maior share < 0,30 · ≥ 6 features com share > 1% · deriva de HHI < 0,10"* — os 2 últimos nunca foram gates |
| `CLAUDE.md:336` | `\| TF de decisão \| 15m — escolhido, T1 com **10 features** (v3.3; Grupo F saiu por quebra RPI, §2.7.1) \|` — **contradito pelas DUAS decisões**; note que `CLAUDE.md:338,356` **já registram** a decisão nova, então a linha 336 é agora auto-contraditória dentro do mesmo arquivo |
| `README.md:115` | `├── features/     Feature Engine — 10 features T1, registry, paridade lote/streaming` |
| `docs/SPRINT_LOG.md:51,113,929,1039,1396` | várias afirmações "as 10 features T1" |
| `docs/CODE_DISCOVERY.md:551` | *"`min_warmup_bars=2000` é aplicado como corte uniforme sobre as 10 features T1"* — **duplamente stale**: o valor é 200 desde 2026-08-15 (`constants.yaml:790`) |
| `src/models/alpha.py:95,108,173,281-282` · `src/models/dataset.py:2,82` · `src/models/baselines.py:786` · `src/models/pipeline.py:184` · `src/models/hhi.py:57-58` · `src/analysis/faixa1_6_reconciliation.py:1010,1095` · `faixa1_7_edge_or_beta.py:388` · `faixa2_caminho_b.py:3,1081` · `faixa2_e2_research.py:131` · `faixa2_e3_stability.py:74` | docstrings que dizem literalmente "10 features T1" / "14 colunas" (código, não doc — listadas porque são a mesma dívida) |

### Inconsistência viva, não causada por nenhuma das duas decisões (encontrada no caminho)

- `min_warmup_bars`: **200** em `config/constants.yaml:790` vs **2000** em `features/registry.yaml:68,84,100,116,137,154,171,187,203,229,245,261,287` (13 entradas), `src/features/support.py:104` (docstring) e `tests/unit/test_features_build.py:70,87`.
- `data/capacity/clocks/` — 16 parquets órfãos de 2026-08-02 incluindo `dolar_{5,15,30,60}min.parquet`, referenciados por zero arquivos do repo, sem símbolo nem manifesto. **Alto risco de serem confundidos com saída de M2 numa sessão futura.**

---

## 7. PENDENTE-DE-EXECUÇÃO-HUMANA

Tudo que não pôde ser verificado sem rodar Python, com o comando exato. Nenhum destes consome `N_lifetime` (todos são medição descritiva sobre dado já em disco).

**P-1 — Deriva real do threshold de dollar bar entre as 5 janelas de M2 (bloqueador 2, §3.1).**
O que a §3.1 tem é um proxy de *contagem de trades* (bytes). O número que decide é `Σ price×quantity` por janela. Não existe script para isso hoje; o mais barato é reusar a 1ª passada de M2, que já calcula exatamente `totals.total_dollar` e o loga por chunk. Rodar 1× por janela e ler `analysis.m2_worker.totals_chunk_done`:

```bash
uv run python -m src.analysis.m2_bar_comparison --start 2022-05-01 --end 2022-05-31 --dest-path experiments/m2_thr_luna.json --max-workers 4
uv run python -m src.analysis.m2_bar_comparison --start 2022-11-01 --end 2022-11-30 --dest-path experiments/m2_thr_ftx.json --max-workers 4
uv run python -m src.analysis.m2_bar_comparison --start 2023-06-01 --end 2023-06-30 --dest-path experiments/m2_thr_winter.json --max-workers 4
uv run python -m src.analysis.m2_bar_comparison --start 2024-03-01 --end 2024-03-31 --dest-path experiments/m2_thr_etf.json --max-workers 4
uv run python -m src.analysis.m2_bar_comparison --start 2026-07-01 --end 2026-07-31 --dest-path experiments/m2_thr_recente.json --max-workers 4
```

> **Ressalva de custo/honestidade:** isso re-roda M2 inteiro (5 × ~10 min) só para extrair um número que o código calcula e não persiste. Um script novo de ~30 linhas em `tools/diagnostics/` que só some `price*quantity` por janela via `lake.query_agg_trades` seria muito mais barato — mas escrever esse script está fora do escopo desta investigação. Registro como a opção preferível, para o Manager decidir.

**P-2 — Distribuição empírica de duração de relógio de uma dollar bar (bloqueador 1 e 3).**
Sem isso, todas as opções das §2 e §4 são discutidas sem magnitude. O que se quer: por (símbolo, camada), a distribuição de `close_time[i] − close_time[i−1]` (p1/p50/p90/p99/max) sobre pelo menos 2 janelas de regime distintas. Não existe script — requer um `tools/diagnostics/measure_dollar_bar_duration.py` novo, fora do escopo desta investigação.

**P-3 — Distribuição de `n_bars_held` sob grade dollar (bloqueador 1).**
O script análogo para barra de tempo **já existe**: `tools/diagnostics/measure_time_stop_slack.py`. Rodar hoje dá a linha de base contra a qual comparar:

```bash
uv run python tools/diagnostics/measure_time_stop_slack.py
```

**P-4 — Suíte completa após qualquer mudança (protocolo do usuário).**
Nenhuma alteração de `cpcv.py`/`triple_barrier.py`/`weights.py` pode ser considerada fechada sem:

```bash
uv run pytest -m "not slow"
uv run pytest
```

**P-5 — Verificar se `assert_tf_consistent` realmente bloqueia labels de dollar bar (achado C).**
Confirmado por leitura (`cpcv.py:288-304,359`), não por execução. A confirmação empírica só é possível depois que existir um `labels.parquet` em grade dollar — ou seja, é um teste a escrever no pacote de trabalho, não agora.

**P-6 — Medir RSS real por processo durante a próxima tentativa de reprocessamento (AG-034, §5.3).**
Zero código: Gerenciador de Tarefas durante o run, anotando pico de RSS por PID. É a recomendação já registrada em AG-034 e continua sendo o passo mais barato antes de gastar outra tentativa de 9h+.

---

## 8. O que não foi possível determinar

Registrado explicitamente para não virar falsa confiança:

1. **A magnitude real da deriva do threshold entre janelas** (P-1). Só um proxy de contagem de trades (2,14× de spread), não de volume em dólar. A direção pode diferir.
2. **A distribuição de duração de relógio de uma dollar bar** (P-2). Sem ela, "32 barras pode ser 20 minutos ou 3 dias" é qualitativamente correto mas sem número, e as opções dos bloqueadores 1 e 3 não podem ser comparadas quantitativamente.
3. **Se a vitória do Garman-Klass em M1 sobrevive à grade dollar.** M1 inteiro é parametrizado por `timeframe_minutes` e o contrato `estimate()` levanta `NotImplementedError` fora de `horizon_minutes == timeframe_minutes` (achado D). Não é reabertura de M1; é uma condicional que precisa estar visível quando o reprocessamento do GK for autorizado.
4. **Se "todas as features do registry" significa 13 (registry atual) ou ~77 (registry + `research/research_t2.py`).** As duas leituras têm ordens de grandeza de esforço diferentes. §1.3.
5. **Qual o impacto real do filtro encadeado `is_not_null` sobre o tamanho do conjunto de treino** com o vetor expandido (`alpha.py:329-332`). Cada feature nova com warmup próprio corta linhas; ninguém mediu.
