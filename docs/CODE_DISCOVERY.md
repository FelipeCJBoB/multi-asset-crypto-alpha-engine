# Code Discovery — 11 estágios do pipeline (+ Meta-Model)

**generated_at:** 2026-08-09 · **code_version:** `ddc0362`

Discovery de código dos estágios do pipeline do motor BTCUSDT, preparação pro PRD V4.
Isto é leitura de código, não avaliação — nenhuma decisão de arquitetura, nenhuma
medição, nenhuma refatoração. `n_lifetime`: +0 (leitura de código não é trial).

## Regra de verdade

O código é a fonte. `PRD_V3_2_UNIFICADO.md` é referência de comparação. Onde
divergirem, o comportamento do CÓDIGO é o catalogado como real, com a divergência
registrada explicitamente na seção 12.7 de cada estágio (localização exata nos dois
lados). Isso já havia acontecido 2 vezes antes desta rodada (ambientes de triagem
do `environments.py` vs. regimes R1..R4 do PRD; unanimidade 6/6 de
`alpha_monotonic_consistency_min_envs` não descrita no PRD original) — esta rodada
encontrou **54 divergências adicionais** catalogadas estágio por estágio abaixo.

## Metodologia

9 agentes em paralelo, cada um com escopo de arquivo não sobreposto. VOLATILIDADE
e REGIME tiveram fan-in EXAUSTIVO (grep no repo inteiro — `src/`, `tests/`,
`research/`, `docs/`, `config/`, `audit/`, PRD — não amostral), por serem os dois
estágios de maior conectividade suspeita do projeto.

## Resumo

| | |
|---|---|
| Estágios catalogados | 12 (11 do pipeline + Meta-Model) |
| Presentes | 11 |
| Ausentes | 1 (Meta-Model — confirmado, sem divergência entre PRD/CLAUDE.md/código sobre a ausência) |
| Funções/classes catalogadas | 304 |
| Divergências PRD↔código encontradas | 54 |
| Observações do executor (fora do catálogo) | 53 |

Artefato estruturado equivalente: `experiments/code_discovery.json`.

---

## Estágio 1 — BARRA

**Status:** presente. Escopo: `src/data/resample.py` (255 linhas), `src/data/lake.py` (212), `src/data/schemas.py` (173), `src/data/checks.py` (460), `src/data/validate.py` (856), `src/data/_util.py` (41), `src/data/_paths.py` (55), `src/data/_constants.py` (47) — 2.099 linhas no total.

### 12.1 Superfície

53 funções catalogadas (52 funções de módulo + 1 método público, `QualityReport.to_dict`). Por arquivo:

- **`resample.py`** (6 funções): `supported_timeframes`, `step_ms`, `resample_klines` (núcleo do estágio — agrega 1m→timeframe alvo), `assert_no_lookahead` (helper de causalidade, reexecuta a verificação do zero para não virar "a função concorda consigo mesma"), `find_native_klines`, `compare_resample_to_native` (check 16 do §1.3).
- **`lake.py`** (10 funções): camada analítica fina sobre DuckDB — poda de arquivo por nome (`_list_day_files`/`_list_month_files`) seguida de poda de predicado dentro do DuckDB (`_read_files`), depois `query_bars`/`query_agg_trades`/`query_metrics`/`query_funding` como fachada pública por fonte. `query_bars` é o único ponto de composição com `resample` (import local dentro da função, para não criar ciclo a nível de módulo).
- **`schemas.py`** (1 função pública, `get_schema`): registro de 6 `DatasetSchema` (`KLINES_1M`, `MARK_PRICE_KLINES_1M`, `PREMIUM_INDEX_KLINES_1M`, `AGG_TRADES`, `METRICS`, `FUNDING`), cada um com dtypes medidos do parquet real, não do que se "esperaria" de um kline — `open/high/low/close` de klines-like são `Utf8`, não `Float64`.
- **`checks.py`** (17 funções): primitivas atômicas, uma por check do §1.3 (schema, duplicatas, nulos, monotonicidade, convenção de close_time, completude de grade, classificação de gaps, coerência OHLC, preços positivos, volume não-negativo, taker_buy≤volume, outliers, desvio de preço entre fontes, intervalo de funding, cobertura, quebra semântica de venue). Nenhuma sabe de JSON de saída nem de gate — isso é responsabilidade de `validate.py`.
- **`validate.py`** (12 funções + 1 método): orquestra as primitivas de `checks.py` por formato de dataset (`validate_klines_like`, `validate_resampled_bars`, `validate_agg_trades`, `validate_metrics`, `validate_funding`), monta `QualityReport`, grava atomicamente (`write_report_atomic`) e expõe `assert_ready_for_training` como invariante do consumidor.
- **`_util.py`/`_paths.py`/`_constants.py`** (6 funções): helpers sem estado (`cast_price_columns`, `ms_to_iso`, `metrics_timestamp_to_ms`), resolução de caminhos (`capacity_symbol_dir`) e loader de `constants.yaml` com cache em memória (`load_constant`).

Nenhuma classe de domínio — só dataclasses `frozen`/`slots` como tipo de retorno (`ParityResult`, `SchemaCheckResult`, `DuplicatesResult`, etc.) e uma dataclass mutável (`QualityReport`, usada como builder). Todas as funções de negócio são livres, a nível de módulo.

### 12.2 Matemática implementada

**Agregação OHLCV (`resample.py:107-127`).** Bucket = `floor(open_time / step_ms) * step_ms`. Dentro do bucket: `open` = primeira constituinte, `high` = máximo, `low` = mínimo, `close` = última constituinte, `volume`/`quote_volume`/`count`/`taker_buy_volume`/`taker_buy_quote_volume` = soma. O `close_time` da barra agregada é **recomputado** como `open_time + step_ms - 1` (convenção herdada de `klines_1m`), não herdado da última constituinte.

**Janela fechada à esquerda.** Cada barra de 1m pertence ao bucket `[bucket, bucket+step)` por seu `open_time` (`resample.py:107`). Por construção, a última constituinte de um bucket sempre fecha exatamente em `bucket + step_ms - 1` — mesmo valor do `close_time` recomputado da barra agregada.

**Sem conceito de warmup nesta camada.** Grep pelas 8 arquivos não encontra nenhuma ocorrência de "warmup". O único mecanismo próximo é `drop_incomplete_tail` (default `True`, `resample.py:83`), que descarta o **último** bucket se ele não tiver o número completo de constituintes — é sobre a cauda da série, não sobre o início. Todo bucket completo é emitido sem supressão nem NaN-fill de warmup; isso é conceito de Feature Engine (`min_warmup_bars=2000`, PRD §2.0.1/R0), fora deste estágio.

**Duplicatas e gaps (Data Quality Engine).** `check_duplicates` conta linhas "em excesso" sobre a chave primária; em `validate_klines_like`/`validate_agg_trades`/`validate_funding`, excesso > 0 reprova o gate. `check_grid_completeness` materializa a grade esperada inteira via `pl.arange` e faz anti-join contra os timestamps observados — lista **todos** os ausentes, não só conta. `classify_gaps` então classifica cada ausente como `maintenance` (só se cair numa janela de manutenção real, vazia por padrão) ou `unknown` — nunca `collection` sem uma fonte independente. Achado notável: em `validate_klines_like` (linhas 288-299) e na grade nativa de 5m de `validate_metrics` (634-639), gaps são reportados mas **não** reprovam o gate — só afetam `quality_score`. Apenas o check 20 (metrics alinhado à grade de 30m, linhas 646-647) é gating por causa de lacuna.

**Alinhamento causal explícito, em três camadas redundantes:** (1) construção do bucket por `floor()`; (2) assert interno em `resample_klines` que compara `_max_constituent_close_time` contra o `close_time` da barra agregada e levanta `AssertionError` se algo "vazar" do futuro (linhas 129-139); (3) `assert_no_lookahead`, helper independente que reexecuta a verificação do zero para uso em teste de paridade (155-178). `lake._day_bounds_ms` reforça isso no eixo de fuso horário: força `tzinfo=UTC` explícito ao converter datas em limites ms, evitando bug de deslocamento de fuso local silencioso.

### 12.3 Onde a escolha de desenho está codificada

- **Tolerância de paridade cross-source** (`resample_cross_source_parity_tolerance = 1e-8`, LITERATURE, classe C) — `config/constants.yaml:459-464`, lida em `resample.py:227` e `validate.py:107`.
- **Limiar de outlier** (`outlier_log_return_sigma_threshold = 8.0`, LITERATURE, classe C) — `checks.py:287`.
- **Desvio máximo de mark price** (`mark_price_deviation_max_pct = 2.0`, LITERATURE, classe C) — `validate.py:328`.
- Minutos por timeframe (`_TIMEFRAME_MINUTES`, `resample.py:36-43`) e passos de grade (`grid_step_ms` em `schemas.py`) ficam **fora** de `constants.yaml` deliberadamente — documentados como definição de calendário/medição direta do dado, não hiperparâmetro (mesma isenção que "60 segundos por minuto").
- `_MAX_MISSING_TIMESTAMPS_LISTED = 500` (`validate.py:53`) é um literal sem entrada em `constants.yaml` nem proveniência declarada — ver observação do executor.

### 12.4 Acoplamento

**Fan-in — 15 pontos de import em 9 arquivos fora de `src/data/`:** `src/features/_sources.py` (lake, `_util.metrics_timestamp_to_ms`), `src/labels/triple_barrier.py` (lake, `resample.step_ms`), `src/execution/fill_simulator.py` (lake, `resample.step_ms`), `src/validation/leakage.py` (resample, import local), `src/validation/cpcv.py` (`resample.step_ms`), `src/analysis/faixa2_caminho_b.py`, `faixa2_dsr_and_b2_check.py`, `faixa2_e2_research.py`, `cost_surface.py` (todos `lake`), `src/regime/stress.py` (`checks`, `resample`), `src/models/baselines.py` (`lake`). `schemas.py` e `validate.py` **não** são importados por nenhum consumidor externo hoje — só usados dentro do próprio pacote `data/` e por sua CLI.

**Fan-out — zero para outros pacotes `src.*`.** Todo fan-out do escopo é intra-pacote (`resample`↔`lake`↔`checks`↔`validate`↔`_util`↔`_paths`↔`_constants`) ou biblioteca externa (`polars`, `duckdb`, `orjson`, `structlog`, `yaml`, `argparse`). Notável: `src/data/__init__.py` declara "Importa apenas exchange/", mas nenhuma importação real de `src.exchange` existe nos 8 arquivos — `_paths.py`/`_constants.py` duplicam deliberadamente os equivalentes de `exchange/` em vez de importar (ver §12.7 observações).

**Import-linter.** Único contrato formal que toca este estágio: `"labels só é lido por models, validation, backtest"` (`pyproject.toml:132-139`) lista `src.data` entre os módulos proibidos de importar `src.labels` — confirmado, nenhuma violação. Não existe contrato formal "data só importa exchange" hoje; é só uma convenção de docstring.

### 12.5 Substituibilidade

Sem interface abstrata (`Protocol`/ABC). Funções livres, chamadas diretamente pelos consumidores (`lake.query_bars(...)`, `resample.resample_klines(...)`, `validate.validate_klines_like(...)`). Extensão para nova fonte = novo `DatasetSchema` + (se necessário) caso em `_list_files_in_range` + nova função `validate_<formato>`.

Impedimentos a troca de implementação: acoplamento direto a `pl.DataFrame` em toda a superfície pública (sem abstração de dataframe); `lake._read_files` instancia DuckDB diretamente, sem parâmetro de injeção; `_constants.py` usa cache global de processo (`_cache`, module-level) — testes contornam com `monkeypatch.setattr` em vez de construtor; `_paths.py` resolve caminhos uma vez no import a partir de `__file__`; nomes de coluna hardcoded espelhando o schema exato da Binance espalhados por `resample.py`/`checks.py`/`validate.py`.

### 12.6 Testes

6 arquivos: `tests/unit/test_data_resample.py`, `tests/parity/test_resample_parity.py`, `tests/unit/test_data_lake.py`, `tests/unit/test_data_schemas.py`, `tests/unit/test_data_checks.py`, `tests/unit/test_data_validate.py`. Cobertura ampla das funções públicas de `resample`/`lake`/`schemas`/`checks`/`validate`. Sem teste dedicado: `resample.supported_timeframes`, `lake._list_files_in_range`/`_as_date`/`_read_files` (só indireto), `validate._empty_report`/`_default_t1_source_dirs`/`_load_venue_changelog_events`/`_run_cli` (sem teste de CLI), `QualityReport.to_dict`, `_util.ms_to_iso`/`metrics_timestamp_to_ms` (só indireto), `_paths.capacity_symbol_dir`, `checks._stem_to_iso_date`.

Testes que fixam comportamento (valor literal ou tolerância zero): agregação OHLCV exata de 5 barras sintéticas; determinismo bit-a-bit (`out1.equals(out2)`); paridade dentro/fora de `1e-8`; conservação de volume 1m→30m com `rel=1e-9` sobre dado real; `_day_bounds_ms` contra epoch ms literal (`1705276800000`); conjunto de chaves top-level do JSON contra o schema literal do §1.3; `outlier_log_return_sigma_threshold == 8.0`; contagens de linha exatas em testes de integração contra fixture real de 3 dias.

### 12.7 Divergências com o PRD

7 divergências encontradas, todas com âncora dupla (PRD + código):

1. **Layout do Data Lake** (PRD §1.2, linhas 294-335) — PRD descreve `data/raw/{fonte}/{yyyy}/{mm}/` + `data/processed/bars_{tf}/` versionado. Código real usa `data/capacity/{source}/{symbol}/{yyyy-mm-dd}.parquet` (um arquivo por dia), rotulado no próprio código como "layout provisório do Sprint 1". `PROCESSED_DIR` existe (`_paths.py:43`) mas **nunca é usado** — barras agregadas nunca são persistidas, são recalculadas em memória a cada `lake.query_bars(tf=...)`.
2. **Bloco INVARIANTES do §1.3** (linhas 413-419) lista o assert de `effective_start` como se fosse gate do relatório. Código resolve deliberadamente como invariante do **consumidor** (`assert_ready_for_training`, `validate.py:98-113`), não do relatório — decisão documentada porque a leitura literal quebra no próprio exemplo do PRD (`start` < `effective_start` nas linhas 397/407).
3. **Check 2 (checksum, PRD linha 346)** — não implementado; `validate.py:222-230` documenta como `checks_skipped` até `src/data/download.py` existir.
4. **Check 6 (UTC, PRD linha 352)** — não há computação real, só uma nota descritiva fixa (`validate.py:278-281` e `628-632`); para `metrics`, o código admite que a string `create_time` "não é verificável isoladamente".
5. **Check 9 (grade completa) não reprova o gate** — resolvido de forma consistente com o próprio exemplo do PRD (`missing_bars: 41` + `gate: PASS`, linhas 399/409), mas não declarado em prosa: gaps genéricos nunca entram em `failed_checks` (`validate.py:288-299`), só o check 20 (alinhamento de metrics a 30m) reprova por lacuna (linhas 646-647).
6. **Cobertura por feature vs. por fonte (checks 21/22, PRD linha 406)** — exemplo do PRD mostra `coverage_by_feature` chaveado por ID de feature (`E01_funding_z`). Código implementa por FONTE T1 (`D01_agg_trades`, `D03_klines_1m`, ...), documentado como provisório até `features/registry.yaml` existir.
7. **Nomenclatura de dataset** — PRD nomeia diretórios `mark_price_1m`/`premium_index_1m` (§1.2, linhas 303-304); código usa `mark_price_klines_1m`/`premium_index_klines_1m` (`schemas.py:72-92`).

### Observações do executor

- `src/data/__init__.py` declara "Importa apenas exchange/." mas nenhum dos 8 arquivos do escopo importa `src.exchange` de fato — `_paths.py`/`_constants.py` duplicam deliberadamente os equivalentes de `exchange/` em vez de importar, com TODO de consolidação pós-Sprint 3. Autoinconsistência docstring-vs-código, não PRD-vs-código.
- `_MAX_MISSING_TIMESTAMPS_LISTED = 500` (`validate.py:53`) é um literal numérico sem entrada em `constants.yaml` nem proveniência — potencial tensão com a Regra Zero do CLAUDE.md, ainda que seja um teto de formatação de JSON, não um limiar que muda o gate.
- `_constants.py`/`validate.py` fazem parsing de YAML cru (`yaml.safe_load`), sem modelo Pydantic — stack declarado no CLAUDE.md cita "Pydantic+YAML", mas nenhum dos 8 arquivos importa `pydantic`.
- `tests/parity/test_resample_parity.py` lê dado real de backfill em todas as suas funções (via `_skip_if_missing()`) mas nenhuma carrega `@pytest.mark.integration`, ao contrário da própria convenção de marcadores do CLAUDE.md (que `test_data_lake.py`/`test_data_schemas.py` seguem corretamente).
- `resample.supported_timeframes()` não tem nenhum teste dedicado nos 6 arquivos revisados.
- Cache global em `_constants.py` e caminhos resolvidos uma única vez em `_paths.py` são singletons de processo — não são bugs, mas explicam por que os testes usam `monkeypatch.setattr` em vez de injeção via construtor.


---

## Estágio 2 — VOLATILIDADE

### 12.1 Escopo e arquivos

Leitura integral dos dois arquivos de escopo:

- `src/features/groups/group_c.py` (48 linhas) — as 4 funções de volatilidade do GRUPO C implementadas no Sprint 4: `c01_atr_20`, `c02_atr_20_pct`, `c06_vol_ratio_12_96`, `c07_vol_pctile_expanding`. O docstring do módulo já declara explicitamente que C01/C02 "não são T1 isoladas... são insumo de A05, A13, C06, C07, E27f".
- `src/features/support.py` (269 linhas) — primitivas causais compartilhadas. Das 11 funções do arquivo, 5 são o núcleo matemático de volatilidade: `true_range`, `_first_valid_index`, `wilder_smooth`, `atr_wilder`, `realized_vol`, `expanding_percentile_rank_strict` (6, incluindo o helper privado). As demais (`ema`, `rsi_wilder`, `rolling_zscore`, `efficiency_ratio`, `expanding_zscore_strict`) não são volatilidade — não aprofundadas, exceto para notar que `rsi_wilder` reusa `wilder_smooth` bit-a-bit com `atr_wilder`.

Status: **presente**. Das 17 features do GRUPO C listadas no PRD §2.4 (C01-C17), apenas 4 estão implementadas em produção (C01, C02, C06, C07) — consistente com o escopo declarado no próprio docstring do módulo ("Escopo do Sprint 4"), não uma lacuna silenciosa.

### 12.2 Funções catalogadas

| função | arquivo:linha | pública | carrega decisão |
|---|---|---|---|
| `c01_atr_20(high, low, close, window)` | group_c.py:18 | sim | sim |
| `c02_atr_20_pct(atr_20_abs, close)` | group_c.py:23 | sim | sim |
| `c06_vol_ratio_12_96(log_return_1, short_window, long_window)` | group_c.py:30 | sim | sim |
| `c07_vol_pctile_expanding(log_return_1, window)` | group_c.py:41 | sim | sim |
| `true_range(high, low, close)` | support.py:32 | sim | sim |
| `_first_valid_index(values)` | support.py:51 | não | não (helper interno) |
| `wilder_smooth(values, window)` | support.py:59 | sim | sim |
| `atr_wilder(high, low, close, window)` | support.py:91 | sim | sim |
| `realized_vol(log_return, window)` | support.py:137 | sim | sim |
| `expanding_percentile_rank_strict(values)` | support.py:209 | sim | sim |

10 funções catalogadas (4 em group_c.py + 6 em support.py, incluindo o helper privado `_first_valid_index`).

### 12.3 Matemática

- **Wilder vs. SMA:** ATR é de Wilder — EMA recursiva com `alpha = 1/window`, não média móvel simples de True Range. `wilder_smooth` (support.py:59) usa laço explícito, não `ewm_mean`, porque o seed de Wilder é a média SIMPLES da primeira janela — diferente (não bit-idêntico) do seed de `ewm_mean(adjust=False)`, documentado explicitamente na docstring da função.
- **Seed:** média simples (`np.mean`) dos primeiros `window` valores válidos de TR a partir do primeiro índice não-NaN. Como `true_range()[0] = high[0]-low[0]` é sempre definido, o seed cai no índice `window-1` (para `window=20`, na 20ª barra). Antes do seed: NaN — nunca zero, nunca valor parcial.
- **Janela:** rolante FIXA (padrão 20 barras, `constants.yaml::atr_window`), não expansiva. O módulo declara explicitamente duas famílias de janela na docstring de topo — ATR/realized_vol usam janela rolante fixa; C07 combina isso com uma camada expansiva estrita por cima (`expanding_percentile_rank_strict` sobre `realized_vol_48`).
- **Fechamento (t participa da própria janela?):** SIM — fechada à direita. `true_range(t)` usa `high[t]`/`low[t]` (dado da própria barra); `wilder_smooth` em `t` usa `values[t]` diretamente na recursão. Isso é causal (H/L de `t` fecham junto com o candle), mas significa que `atr_at_t0` na barra `t0` de `triple_barrier.py` é calculado incluindo o high/low da MESMA barra cujo close vira `entry_ref`.
- **Warmup:** natural do ATR = `window` barras de NaN (19 para `atr_window=20`). SEPARADAMENTE, o Feature Engine aplica um corte uniforme de `min_warmup_bars=2000` sobre TODO o vetor T1/T2 (`apply_min_warmup_mask`, build.py:178-191) — ~100x maior que o warmup natural do ATR, dimensionado pela feature mais lenta a convergir (janela expansiva/EMA48), não pelo ATR.
- **Unidade:** AMBAS, como colunas separadas. `C01_atr_20` = preço absoluto (US$); `C02_atr_20_pct` = fração adimensional (`atr_abs/close`). Uso é estritamente dividido: absoluto alimenta `A13_dist_ema48_atr` (numerador em US$); percentual alimenta `A05_ret_vol_norm_4`, `E27f_cost_atr_ratio`, e TODO o dimensionamento de barreiras TP/SL/MFE em `triple_barrier.py` — o Label Engine nunca usa a forma absoluta diretamente.

### 12.4 Fan-in — EXAUSTIVO

**135 pontos de uso individuais** catalogados via grep no repo inteiro (`src/`, `tests/`, `research/`, `docs/`, `config/`, `audit/`, PRD raiz) para os identificadores exatos confirmados nos arquivos de escopo: `c01_atr_20`, `c02_atr_20_pct`, `c06_vol_ratio_12_96`, `c07_vol_pctile_expanding`, `atr_wilder`, `wilder_smooth`, `true_range`, `realized_vol`, `expanding_percentile_rank_strict`, e as colunas/strings `atr_20_abs`, `atr_20_pct`, `atr_at_t0`, `C01_atr_20`, `C02_atr_20_pct`, `C06_vol_ratio_12_96`, `C07_vol_pctile_expanding`, `vol_pctile_expanding`, `vol_ratio_12_96`. Cada ocorrência está listada individualmente com arquivo:linha no JSON (`fan_in`), não amostrada nem resumida.

Cadeias de consumo confirmadas, por camada:

1. **Feature Engine** (`src/features/build.py`) — `c01_atr_20`/`c02_atr_20_pct` chamadas na linha 142-143; os resultados alimentam diretamente `A05_ret_vol_norm_4` (149), `A13_dist_ema48_atr` (150) e `E27f_cost_atr_ratio` (152), além de serem expostas como colunas de saída `C01_atr_20`/`C02_atr_20_pct` (167-168). `c06_vol_ratio_12_96`/`c07_vol_pctile_expanding` chamadas em 155/158, direto para o vetor T1.
2. **Label Engine** (`src/labels/triple_barrier.py`) — reusa `group_c.c01_atr_20`/`c02_atr_20_pct` (576-577, "Reuso, não reimplementação"); `atr_pct_i` dimensiona `tp_price`/`sl_price` (662-663) e `mfe_atr_units` (704), e é persistido como coluna `atr_at_t0` em `labels.parquet` (729, schema em 436/463).
3. **Faixa 2 E1 — varredura de barreiras** (`src/labels/barrier_sweep.py:123`) — NÃO recomputa ATR; lê `atr_at_t0` já persistido em `labels.parquet` para varrer `tp_atr_mult`/`sl_atr_mult` sem re-rodar o Label Engine.
4. **Regime Engine** (`src/regime/build.py:47,55,65` → `classifier.py:277,300,106,327` → `stress.py:123,129,440,462`) — `C07_vol_pctile_expanding` é lido do output do Feature Engine (não recalculado) e alimenta o eixo de histerese de volatilidade da máquina de estados R1-R4 E o gatilho de stress S1 (vol extrema, threshold `stress_vol_pctile_threshold=0.98`).
5. **Validation/Leakage** (`src/validation/leakage.py`) — `_HIGH_LOW_FEATURES` (164-170) classifica A05/A13/C01/C02/E27f como consumidoras transitivas de high/low via ATR; `_test_05_regime_futuro` (344-396) reexecuta `classify_regimes` com `vol_pctile`/`cost_atr` sintéticos perturbados para provar causalidade; `_test_08_normalizacao_global` (459-470) audita o `causal_proof` de C07 no registry.
6. **Diagnóstico de modelo** (`src/models/hhi.py:10,194`, `src/models/pipeline.py:409`) — citam a correlação medida ρ=-0,913 entre `E27f_cost_atr_ratio`×`C07_vol_pctile_expanding` como caso de referência do diagnóstico de concentração (HHI).
7. **Pesquisa** (`src/analysis/faixa2_e2_research.py`, `faixa1_7_edge_or_beta.py`, `faixa2_vol_accelerator_test.py`, `faixa2_e3_stability.py`, `faixa2_caminho_b.py`, `research/research_t2.py`) — 8 arquivos usam `C07_vol_pctile_expanding` como proxy de volatilidade para ranquear/filtrar candidatas T2, ou recomputam ATR/realized_vol/true_range diretamente via `support.*` com janelas literais (fora do wrapper `group_c`, fora de `load_constant`).
8. **Registry e testes** — `src/features/registry.yaml` (4 entradas dedicadas + 2 que citam ATR na fórmula) e 9 arquivos de teste (`test_features_support.py`, `test_features_groups.py`, `test_features_build.py`, `test_labels_triple_barrier.py`, `test_labels_barrier_sweep.py`, `test_regime_stress.py`, `test_regime_classifier.py`, `test_validation_leakage.py`, `test_features_parity.py`).

**Fora da contagem de 135** (por serem artefatos de dado gerado, não código): 90 arquivos `models/*/diagnostics/*.json` e 7 arquivos `experiments/*.json` também contêm as strings das features de volatilidade (listas de importância/correlação por fold de modelo treinado) — evidência de consumo real pelos modelos, mas não pontos de código. Contados por completude, não enumerados linha a linha.

### 12.5 Parâmetros e proveniência

| parâmetro | valor | categoria | proveniência |
|---|---|---|---|
| `atr_window` | 20 | constants.yaml:148-155 | ASSUMED, classe A, sweep [10,30], review sprint_6 |
| `feature_c06_vol_ratio_short_window` | 12 | constants.yaml:539-545 | ASSUMED, classe B |
| `feature_c06_vol_ratio_long_window` | 96 | constants.yaml:547-553 | ASSUMED, classe B |
| `feature_c07_vol_pctile_window` | 48 | constants.yaml:555-561 | ASSUMED, classe B |
| `min_warmup_bars` | 2000 | constants.yaml:579-585 | ASSUMED, classe B (não específico de volatilidade, mas corta C01/C02/C06/C07) |
| `tp_atr_mult` | 2.0 | constants.yaml:121-128 | ASSUMED, classe A — consome `atr_at_t0` diretamente |
| `sl_atr_mult` | 1.5 | constants.yaml:130-137 | ASSUMED, classe A — consome `atr_at_t0` diretamente |
| `window=20` (literal) | 20 | literal_codigo | `research/research_t2.py:132`, `src/analysis/faixa2_e2_research.py:116` — bypassam `load_constant("atr_window")` |
| `short/long_window=12/96` (literal) | 12, 96 | literal_codigo | `research/research_t2.py:264-266`, testes |
| `window=48` (literal) | 48 | literal_codigo | `research/research_t2.py:267`, testes |
| `10000` (bps) | 10000 | derivado | fator de conversão fração→bps, aplicado sobre `atr_20_pct` em `E27f`/`_BPS_PER_UNIT` |

Nenhum dos parâmetros de volatilidade em `constants.yaml` tem proveniência `MEASURED`/`DERIVED` — todos são `ASSUMED` herdados do PRD original, com `review_by: sprint_6` ou `sprint_8` ainda não cumpridos (Sprint atual = 4).

### 12.6 Fan-out, contratos e substituibilidade

Fan-out interno: `c01_atr_20` → `atr_wilder` → `true_range` + `wilder_smooth` → `_first_valid_index`; `c06_vol_ratio_12_96`/`c07_vol_pctile_expanding` → `realized_vol`; `c07_vol_pctile_expanding` → `expanding_percentile_rank_strict`. Nota de acoplamento: `wilder_smooth` é compartilhada bit-a-bit entre `atr_wilder` (C01) e `rsi_wilder` (B01) — qualquer mudança na suavização de Wilder afeta os dois.

Contratos de `import-linter` (pyproject.toml:117-157) relevantes: "features não importa labels" (satisfeito — o reuso de ATR flui de `labels` para `features`, nunca o inverso); "labels só é lido por models/validation/backtest"; "features não importa analysis"; "models não importa analysis" (`src/models/hhi.py`/`pipeline.py` só citam a correlação C07×E27f em comentário, não importam `src.analysis`).

Substituibilidade: **nenhuma interface/Protocol/ABC de "estimador de volatilidade" existe em `src/`** — as 4 funções são puras, chamadas por nome direto em cada ponto de uso. Impedimentos identificados no código: (1) `research/research_t2.py:132` chama `support.atr_wilder` diretamente, fora do wrapper `group_c.c01_atr_20`, com janela literal; (2) `src/analysis/faixa2_e2_research.py:116` chama `group_c.c01_atr_20(..., 20)` com janela literal em vez de `load_constant`; (3) `src/labels/barrier_sweep.py` não recalcula ATR — lê `atr_at_t0` já persistido, então uma troca de estimador exigiria reprocessar `labels.parquet` inteiro para propagar.

### 12.7 Testes

9 arquivos de teste tocam volatilidade. Funções com cobertura direta: `true_range`, `wilder_smooth`, `atr_wilder`, `realized_vol`, `expanding_percentile_rank_strict`, `c06_vol_ratio_12_96`, `c07_vol_pctile_expanding`; `c01_atr_20` tem cobertura indireta (via testes de escala/causalidade de A05/A13/E27f e via paridade/ortogonalidade sobre o vetor T1 inteiro). Sem teste dedicado: `_first_valid_index` (só exercitada indiretamente) e `c02_atr_20_pct` — esta última por decisão DOCUMENTADA em `src/validation/leakage.py:159` (`_DERIVATION_ONLY_CAUSAL_PROOF`), não uma lacuna silenciosa.

Testes que fixam comportamento: `test_wilder_smooth_seed_e_recursao` (valor literal do seed/recursão), `test_true_range_valor_conhecido` (3 valores calculados à mão), `test_e27f_round_trip_cost_bps_reproduz_0_055_pct` (fixa 5,5 bps do PRD §0.2 R2), `test_registry_tf_e_15m_em_todas_as_entradas` (fixa `tf=='15m'` para C01/C02/C06/C07 — é o teste que ENFORCE a resolução da divergência de TF vs. PRD §2.2-2.6), o teste de B15 em `test_labels_triple_barrier.py` (tolerância zero — `config_hash` tem que divergir se só `tp_atr_mult` mudar entre label e execução), e `test_paridade_lote_streaming_ultimas_500_barras` (tolerância 1e-8 sobre todo o vetor T1+support, `slow`+`integration`).

### Divergências PRD × código

1. **TF 30m (PRD) vs. 15m (código), já auto-documentado no repo.** PRD §2.4 (linhas 532-538) anota C01/C02/C06/C07 com TF="30m". O código (`registry.yaml`, `tf: 15m` em cada entrada; `test_registry_tf_e_15m_em_todas_as_entradas`) calcula tudo a 15m. **Não é achado novo desta auditoria** — `registry.yaml` linhas 14-60 ("NOTA DE TF") já documenta isso explicitamente como resíduo textual do PRD não atualizado quando `decision_tf` mudou de 30m→15m entre v3.0 e v3.1, citando §0.1/§0.4/§0.5/§5.9/§3.3 do próprio PRD como evidência de que 15m é a leitura correta. Recatalogado aqui por estar diretamente no escopo VOLATILIDADE.
2. **Convenção de nomes não seguida.** PRD §2.1 declara `{grupo}{nn}_{nome}_{parametro}_{tf}`, exemplo `C03_atr_pct_20_30m`. As 4 colunas reais são `C01_atr_20`, `C02_atr_20_pct`, `C06_vol_ratio_12_96`, `C07_vol_pctile_expanding` — nenhuma tem sufixo `_tf`, e C07 não tem parâmetro numérico no nome.
3. **Janelas de barra não recalibradas para calendário (auto-documentado em registry.yaml:47-59).** C06 (12/96) e C07 (48) usam as mesmas contagens de barra do PRD (calibradas implicitamente para 30m) aplicadas literalmente a 15m — 48 barras deixou de ser "1 dia" e passou a ser "12h". Registrado como pergunta em aberto para a ablação do Sprint 8, não corrigido silenciosamente.
4. **Ambiguidade de unidade "ATR_20" em A05 vs. A13 (PRD §2.2, linhas 497/505).** O PRD usa o mesmo rótulo "ATR_20" nas fórmulas de A05 (`.../ (ATR_20 × 2)`) e A13 (`.../ ATR_20`) sem diferenciar unidade. O código resolve por análise dimensional (`group_a.py` docstring): A05 precisa da forma percentual (`atr_20_pct`), A13 precisa da forma absoluta (`atr_20_abs`) — confirmado numericamente por teste, já que a leitura trocada produz ordens de grandeza absurdas (1e-5 ou 1e5).

### Observações do executor

- O fan-in de 135 pontos é exaustivo para os identificadores confirmados nos dois arquivos de escopo, grepado no repo inteiro. Ficaram FORA da contagem (mencionados só agregadamente): 90 arquivos `models/*/diagnostics/*.json` + 7 `experiments/*.json` que citam os nomes das features de volatilidade em listas de importância/correlação — são artefatos de saída de pipeline, não pontos de código.
- `research/research_t2.py` chama `support.atr_wilder`/`realized_vol`/`true_range`/`expanding_percentile_rank_strict` diretamente, fora do wrapper `group_c.py`, com janelas passadas como literais Python (20, 12, 96, 48) em vez de via `load_constant`. `src/analysis/faixa2_e2_research.py:116` tem o mesmo padrão (`window=20` literal) mesmo estando dentro de `src/` (escopo do lint `banned_patterns.py --path src`). Registrado como fato objetivo — sem avaliar se é ou não um problema, fora do escopo desta tarefa.
- `support.py` contém primitivas não relacionadas a volatilidade (`ema`, `rsi_wilder`, `rolling_zscore`, `efficiency_ratio`, `expanding_zscore_strict`) — não aprofundadas por instrução de escopo, exceto para notar que `rsi_wilder` reusa a MESMA `wilder_smooth` que `atr_wilder`, acoplando B01 e C01 na mesma primitiva.
- A natureza de "insumo transitivo" de C01/C02 (não são T1 isoladas, alimentam A05/A13/C06/C07/E27f) já é documentada no próprio docstring de `group_c.py` — não é descoberta desta auditoria, catalogada aqui por instrução de exaustividade.
- Nenhuma classe/Protocol/interface abstrata de "estimador de volatilidade" existe em `src/` — todas as 4 funções do GRUPO C são funções puras chamadas por nome direto, sem injeção de dependência.


---

## Estágio 3 — REGIME

### 12.1 Arquivos lidos

| arquivo | linhas |
|---|---|
| `src/regime/classifier.py` | 379 |
| `src/regime/build.py` | 104 |
| `src/regime/stress.py` | 501 |
| `src/regime/_constants.py` | 45 |
| `src/regime/_paths.py` | 31 |
| `src/models/environments.py` | 93 |

`status: presente`. O Regime Engine (§4 do PRD) e a Camada 2 de ambientes do Alpha (§5.4) estão implementados e testados. Não há placeholder/stub no núcleo — os únicos "ausentes" são os 7 de 10 gatilhos de stress (S2/S4/S5/S7/S8/S9/S10) que resolvem `NOT_COMPUTABLE` por falta de dado-fonte, documentado função a função em `stress.py`.

### 12.2 Funções catalogadas (26)

**`src/regime/classifier.py`** — núcleo puro (sem IO):
- `RegimeThresholds.from_constants` (linha 91, pública) — lê 7 constantes de `constants.yaml`.
- `_run_state_machine` (linha 105, privada, **carrega decisão**) — laço sequencial O(n) que implementa histerese Schmitt + confirmação (§4.5) e a precedência R0>R5>R4>R3>R2>R1.
- `_bars_in_regime` (linha 228, privada) — run-length com piso 2 (exceto R5).
- `_economics_regime` (linha 257, privada, **carrega decisão**) — tercil via posto percentil expansivo (§4.3.1).
- `classify_regimes` (linha 274, pública, **carrega decisão**) — orquestra os três eixos e produz o DataFrame de saída.

**`src/regime/build.py`** — wrapper com IO:
- `build_regimes` (linha 25, pública, **carrega decisão**) — carrega as 4 features do Feature Engine (`apply_warmup_mask=False`) e chama `classify_regimes`.
- `write_regimes_atomic` (linha 80, pública) — persistência atômica (B29).

**`src/regime/stress.py`** — 10 gatilhos + composição:
- `TriggerState` (Enum puro, linha 60) — tri-valorado, deliberadamente NÃO `(str, Enum)` (bug de comparação vetorizada numpy confirmado empiricamente neste Sprint).
- `_not_computable`, `_threshold_gt`, `_threshold_abs_gt` (privadas, helpers genéricos).
- `s01_vol_extreme` .. `s10_filters_hash_changed` (10 funções públicas, uma por gatilho, todas **carregam decisão**). Só S1, S3, S6 são de fato computáveis hoje; S2/S4/S5/S7/S8/S9/S10 são `NOT_COMPUTABLE` por falta de dado-fonte (documentado individualmente em cada docstring).
- `compute_filters_hash` / `discover_filters_hash_snapshots` (públicas, suporte a S10 — e reusadas por `src.risk.kill_switch` K12).
- `compute_stress_triggers` (pública, **carrega decisão**) — agrega os 10 em `StressResult` (`triggered_mask` = OR lógico → alimenta R5).

**`src/models/environments.py`** — Camada 2 (§5.4), fora de `src/regime/` mas parte do mesmo eixo de discovery:
- `_structural_group` (privada, **carrega decisão**) — RANGE=R1∪R2, TREND=R3∪R4, R0/R5→null.
- `assign_environments` (pública, **carrega decisão**) — tercil ESTÁTICO de `cost_atr_ratio` sobre o DataFrame recebido × grupo estrutural = 6 células.

### 12.3 Matemática

**`trend_state` (eixo estrutura):** `er_quantile = expanding_percentile_rank_strict(er_48)`, onde `er_48 = B07_efficiency_ratio_48 = |C_t − C_{t−48}| / rolling_sum(|ΔC|, window=48)` — janela FIXA de 48 barras (`feature_b07_efficiency_ratio_window`, `constants.yaml:531`, ASSUMED classe B, "convenção herdada do PRD §18.5.2 'ER (16,48)', nunca testada"). O POSTO é expansivo estrito. `is_trend_raw = er_q >= 0.60`; estado confirmado usa histerese Schmitt (entrada 0.60 / saída 0.55) + `confirmation_bars=2`. `src/regime/classifier.py:163,309` · `src/features/support.py:161` (`efficiency_ratio`) · `src/features/groups/group_b.py:17-22`.

**`vol_state`/tercil de custo — DOIS métodos diferentes sob o mesmo rótulo "tercil":**
1. `vol_state` (regime R2/R4): `vol_pctile = C07_vol_pctile_expanding = expanding_percentile_rank_strict(realized_vol(log_return_1, window=48))`, onde `realized_vol = rolling_std(window=48, ddof=1) × √48` (janela FIXA, `feature_c07_vol_pctile_window`, `constants.yaml:555`, ASSUMED classe B). `src/features/groups/group_c.py:41-47`.
2. Tercil de custo dos 6 ambientes (`environments.py:69-74`): `df[cost_col].quantile(1/3, interpolation="linear")` / `.quantile(2/3, interpolation="linear")` — quantil ESTÁTICO com interpolação linear clássica, sobre a distribuição do DataFrame recebido (tipicamente o treino de UM fold do CPCV), recalculado do zero a cada chamada. **Não é expansivo, não é causal-online.**

**Interpolação de quantil — método exato:** `expanding_percentile_rank_strict` (usada por `er_quantile`, `vol_pctile` e `econ_quantile`) NÃO é interpolação clássica — é um POSTO/RANK via Fenwick tree sobre o posto denso GLOBAL (`argsort(kind="stable")`), com empates desfeitos por ORDEM DE CHEGADA (não mid-rank). `environments.py` usa `interpolation="linear"` do Polars — método totalmente diferente. `src/features/support.py:209-231` vs `src/models/environments.py:73-74`.

**Combinação lógica de R1..R5/R0:** `regime_raw` instantâneo: `trend&vol→R4`, `trend→R3`, `vol→R2`, `nenhum→R1`; `is_warmup→R0` tem precedência sobre `is_stress_instant→R5`. `regime` confirmado (com histerese): `is_warmup→R0` (precedência sobre tudo, inclusive R5) → `stress_state→R5` → `trend_state&vol_state→R4` → `trend_state→R3` → `vol_state→R2` → senão `R1`. R5 entra sem confirmação e sai só após `stress_exit_confirmation_bars=4` barras sem gatilho. `src/regime/classifier.py:143-223`.

**`cost_atr_ratio` — cálculo e sobreposição com o proxy de VOLATILIDADE:** `E27f_cost_atr_ratio = round_trip_cost_bps(maker_fee, taker_fee) / (ATR_20_pct × 10000)`, onde `ATR_20_pct = ATR_wilder(20)/close` — o MESMO ATR usado como proxy de volatilidade no estágio VOLATILIDADE (Grupo C). Por construção, `cost_atr_ratio` é inversamente proporcional ao ATR: o PRD (linha 1156) reconhece isso textualmente ("`cost_atr_ratio` é proxy de vol"). `src/features/groups/group_e.py:37-57` · `src/features/groups/group_c.py:18-27`.

**Normalização/threshold — por fold, expansiva ou global?** Duas disciplinas coexistem: o classificador (`R0-R5`, `econ_regime`) é 100% causal/expansivo (só índices `< t`, uso ao vivo barra a barra); os 6 ambientes de `environments.py` são um corte ESTÁTICO sobre QUALQUER subconjunto de DataFrame que o chamador passar (tipicamente in-fold, nunca o dataset inteiro) — a própria docstring do módulo declara essa diferença como intencional, não acidental.

### 12.4 Fan-in — EXAUSTIVO

**350 pontos de uso individuais** foram enumerados (arquivo:linha) no `fan_in` do JSON — busca rodada sobre o repositório inteiro (`src/`, `tests/`, `docs/`, `data/`, `experiments/`, `CLAUDE.md`), não amostral. Distribuição aproximada por família de identificador:

- `classify_regimes`/`build_regimes`/`write_regimes_atomic`/`RegimeThresholds`/`REGIME_LABELS`/`TRADEABLE_REGIMES`: ~55 pontos (destaque: `src/risk/limits.py` reusa `TRADEABLE_REGIMES` diretamente como veto duro do Risk Engine; `src/validation/leakage.py` usa `classify_regimes` no teste central de causalidade do projeto).
- `TriggerState`/`compute_stress_triggers`/`StressInputs`/`StressResult`/`compute_filters_hash`/`discover_filters_hash_snapshots`: ~95 pontos — a maior fatia é `src/risk/kill_switch.py` (13 kill switches K01-K13 reusam o `Enum` tri-valorado inteiro, e K12 reusa `compute_filters_hash` literalmente) + `tests/unit/test_risk_kill_switch.py`.
- `assign_environments`/`ENVIRONMENTS`/`RANGE_REGIMES`/`TREND_REGIMES`/`ENV_COL`: ~55 pontos — consumidores diretos são `src/models/monotonic.py` (Camada 1, §5.3) e `src/models/stability.py` (Camada 2, §5.4), mais 6 scripts de pesquisa em `src/analysis/faixa1_5/faixa1_6/faixa2_*`.
- Coluna `"regime"`/`"regime_raw"`/`"tradeable"`/`"cost_atr_ratio"`/`"econ_regime"`/`"bars_in_regime"`/`"stress_triggers"` lida via `pl.col(...)`/`df[...]`, incluindo `STRUCTURAL_REGIMES`/`_STRUCTURAL_REGIMES`/`REGIME_COL`: ~145 pontos — maior concentração em `src/analysis/faixa1_7_edge_or_beta.py`, `src/analysis/faixa1_6_reconciliation.py` e `src/analysis/faixa2_caminho_b.py` (scripts de pesquisa que re-declaram `_STRUCTURAL_REGIMES = ("R1","R2","R3","R4")` de forma independente em CADA um dos 5 arquivos, em vez de importar de um único lugar); consumidor de produção principal é `src/models/alpha.py` (`REGIME_ONEHOT_LEVELS`/`DESIGN_COLUMNS`, one-hot de regime no vetor de treino) e `src/models/dataset.py` (`REGIME_COL`, junção regime↔features↔labels).

### 12.5 Fan-out e import-linter

`src/regime/classifier.py` importa só de `src.features` (support) e do próprio pacote (`stress`, `_constants`). `src/regime/build.py` importa de `src.features.build` (reuso do Feature Engine, zero recomputação) e do próprio pacote. `src/regime/stress.py` importa de `src.data.checks`/`src.data.resample` (S6 reusa `check_grid_completeness`) e `src.exchange.filters` (S10 reusa `parse_exchange_info_snapshot`). `src/models/environments.py` não importa nada de `src.regime` — só `polars`, consumindo a coluna `"regime"` por nome de string (contrato implícito, não import).

Hierarquia declarada (`exchange → data → features → labels → regime → models → validation`) é respeitada nos imports lidos: `regime` importa de `features`/`data`/`exchange`, nunca de `labels`/`models`. `risk` (abaixo de `regime` na cadeia `backtest ← risk ← execution ← live`) importa `TriggerState`/`compute_filters_hash`/`TRADEABLE_REGIMES` de `regime` — direção consistente com a hierarquia, não é violação.

### 12.6 Substituibilidade

Núcleo puro (`classify_regimes`) e wrapper de IO (`build_regimes`) são funções, não classes — sem `Protocol`/ABC injetável. `RegimeThresholds`/`StressInputs`/`StressResult` são `dataclass(frozen=True, slots=True)` simples, contrato de dados sem lógica. Impedimentos relevantes para qualquer substituição: (1) `_run_state_machine` é um laço Python sequencial O(n) — um substituto vetorizado precisaria reproduzir bit-a-bit a MESMA ordem de avaliação de histerese+confirmação; (2) `classify_regimes` recalcula `er_quantile`/`econ_quantile` internamente mas reusa `vol_pctile` já pronto — assimetria que impede injetar um `er_quantile` pré-calculado sem chamar `_run_state_machine` diretamente (como os testes de histerese fazem); (3) o artefato em disco `data/regimes/regime_v1/regimes.parquet` está desatualizado frente a `labels/v1/labels.parquet` — um substituto que só lesse o parquet sem recomputar devolveria cobertura incompleta (ver `src/models/dataset.py`, que decidiu recomputar em memória por esse motivo).

### 12.7 Testes e divergências PRD

**4 arquivos de teste dedicados** (902 linhas): `test_regime_classifier.py` (13 testes), `test_regime_build.py` (6 testes), `test_regime_stress.py` (25 testes), `test_models_environments.py` (5 testes) — mais `test_risk_kill_switch.py` (indireto, reusa `TriggerState`/`compute_filters_hash`) e um teste de causalidade em `src/validation/leakage.py` que chama `classify_regimes` diretamente. Funções privadas sem teste NOMEADO direto: `_bars_in_regime`, `_economics_regime`, `_structural_group`, `_not_computable`/`_threshold_gt`/`_threshold_abs_gt` (todas cobertas só indiretamente via a função pública que as chama).

Testes que **fixam comportamento** (não apenas verificam): `test_thresholds_from_constants_bate_com_prd` (pina os 7 thresholds numéricos), `test_r0_tem_precedencia_sobre_r5_durante_warmup` (pina a DIVERGÊNCIA deliberada do PRD §4.3), `test_invariantes_484_sobre_serie_sintetica`/`test_build_regimes_invariantes_484_dado_real` (tolerância zero sobre as 4 asserções literais do §4.8), `test_build_regimes_colunas_e_dtypes` (pina `bars_in_regime` como `Int32`, não o `int16` do PRD), `test_causalidade_perturbar_futuro_nao_muda_passado` (golden de não-vazamento).

**6 divergências PRD × código catalogadas** (detalhe completo no JSON, campo `divergencias_prd`):
1. **R5 vs R0 — precedência invertida.** PRD §4.3 (linha 981): "R5 tem precedência sobre todos os outros." Código (`classifier.py:121-131,151-154,212-215`): R0/warmup vence R5, deliberado e testado.
2. **Schema de output — 12 colunas vs 10.** PRD §4.6 lista 10 colunas; código adiciona `cost_atr_ratio` e `econ_regime` (§4.3.1), documentado como "extensão, não silenciosa".
3. **`bars_in_regime` dtype — Int32 vs int16.** PRD §4.6 diz `int16`; código usa `pl.Int32` por risco de overflow medido (>32.767 barras em 6,6 anos de histórico).
4. **Denominador de consistência — 6 vs 7, e o PRD se contradiz internamente.** §5.3 (linha 1146, não corrigido) ainda diz "≥ 6 de 7 ambientes"; §5.4 (linha 1156, corrigido 2026-08-09) e `constants.yaml::alpha_monotonic_consistency_min_envs` (DERIVED, classe B) resolvem para 6 de 6 (unanimidade), com investigação documentada concluindo que "7" é resíduo de contaminação com a tabela de IC anual de 7 anos do §17.2. Não é só PRD-vs-código: são DUAS seções do PRD discordando entre si.
5. **R1..R4 (regime de reporte) vs 6 ambientes (RANGE/TREND × tercil de custo) — já catalogado como conhecido na task, confirmado no código:** dois eixos ortogonais, implementados em pacotes diferentes (`src.regime` vs `src.models.environments`), nunca cruzados.
6. **Fórmula do regime econômico — comparação de valor vs comparação de posto.** PRD §4.3.1 escreve a regra como "`cost_atr_ratio < p33 expansivo`" (comparação de VALOR contra quantil); código calcula o POSTO percentil expansivo de `cost_atr_ratio` e compara o posto contra 1/3 — equivalente por definição, mas método (Fenwick tree/rank, não interpolação de quantil) diferente do que a redação sugere.

### Observações do executor

- **Discarded diagnostics tocando este estágio** (`docs/audit_discarded_diagnostics.md`): achado #2 (MÉDIA-ALTA) — `StressResult.triggers` (array por-bar × por-gatilho) nunca é persistido, só colapsa em log agregado; achado #1 (ALTA) — `FeatureICResult.ic_by_env` (consumidor direto de `assign_environments`) só persiste parcialmente e só do fold 0 de 15.
- `data/regimes/regime_v1/regimes.parquet` (o artefato canônico nomeado pelo PRD §4.6) está desatualizado: cobre 2019-12-31→2024-03-30 (148.992 linhas) vs `labels/v1/labels.parquet` 2020-01-01→2026-08-06 (462.682 linhas). `src/models/dataset.py` contorna isso recomputando o regime em memória a cada chamada em vez de confiar no parquet.
- `cost_atr_ratio` (eixo econômico + tercil de custo dos 6 ambientes) é algebricamente o inverso do ATR (proxy de volatilidade do estágio VOLATILIDADE) — o próprio PRD (linha 1156) chama isso de "proxy de vol". A "terceira dimensão econômica" carrega, portanto, informação redundante com o eixo de volatilidade R2/R4 já usado no regime estrutural.
- Duplicação literal (não reuso) das constantes de tercil 1/3, 2/3: declaradas independentemente em `classifier.py` (`_ECON_TERCILE_LOW/HIGH`) e `environments.py` (`_TERCILE_LOW/HIGH`) — mesmo valor, métodos de aplicação propositalmente diferentes, mas risco de dessincronia se um mudar sem o outro.
- PRD §11.3.1 descreve um `estado(t)` futuro incluindo `regime_estrutural(t)` para ponderação por similaridade — nenhuma implementação encontrada em `src/`; é trabalho de Sprint futuro (walk-forward §11.4.1), não uma divergência hoje.
- `src/risk/kill_switch.py`/`src/risk/limits.py` reusam `TriggerState`/`compute_filters_hash`/`TRADEABLE_REGIMES` diretamente de `src.regime` — qualquer mudança de API pública em `stress.py`/`classifier.py` quebra também o Risk Engine (13 kill switches), não só o Regime Engine.
- `src/models/alpha.py::REGIME_ONEHOT_LEVELS = ("R2","R3","R4","R5")` implementa o "one-hot de 5 níveis" do PRD §4.7 como 4 colunas dummy (R1 = referência implícita, R0 nunca aparece pós-warmup) — leitura padrão de codificação categórica k-1, não uma divergência, mas fácil de ler errado como "5 colunas".
- Nos scripts de pesquisa (`src/analysis/faixa1_5/1_6/1_7/2_caminho_b/2_vol_accelerator`), a constante `_STRUCTURAL_REGIMES = ("R1","R2","R3","R4")` é redeclarada de forma independente em pelo menos 5 arquivos diferentes (mesmo valor de `src.regime.classifier.TRADEABLE_REGIMES` menos R5) em vez de importada de um único lugar — não é bug funcional (mesmo valor em todos), mas é fan-in que a busca exaustiva expõe como redundância de definição.


---

## Estágio 4 — META-LABEL

### 12.1 Arquivos
| caminho | linhas |
|---|---|
| `src/labels/triple_barrier.py` | 864 |
| `src/labels/_constants.py` | 45 |
| `src/labels/_paths.py` | 34 |

### 12.2 Funções catalogadas
16 funções/classes catalogadas em `triple_barrier.py`/`_constants.py`, incluindo `LabelConfig` (dataclass + `from_constants` + `config_hash`), `ConfigHashMismatchError`, `verify_config_hash`, `assert_label_invariants`, `_first_barrier_touch`, `build_labels`, `build_labels_both_sides`, `build_labels_for_symbol`, `write_labels_atomic`, `load_constant`. Detalhe completo (assinatura, docstring literal, linha, pública/privada, se carrega decisão) no JSON companheiro.

### 12.3 Matemática
- **`t1` = primeiro toque cronológico real sobre `mark_1m`** (B11 respeitado, `_first_barrier_touch`, linha 362): `np.argmax` sobre máscara booleana de high/low de cada candle de 1m, nunca high/low agregado de janela maior. Sem toque, `t1 = horizon_end_ms` exato.
- **Desempate TP=SL no mesmo candle de 1m**: por proximidade ao `open` do candle (`dist_tp <= dist_sl` favorece TP). Contado em `n_tie_break`, nunca escondido. Resolve uma ambiguidade residual de B11 em escala menor que o próprio PRD não cobre.

### 12.4 Parâmetros
`tp_atr_mult=2.0`, `sl_atr_mult=1.5`, `time_stop_bars=32`, `fill_timeout_bars=1`, `atr_window=20`, `maker_fee=0.0002`, `taker_fee=0.0005`, `adverse_selection_bps=1.5` — todos de `config/constants.yaml`, classe A ASSUMED (exceto fees, classe C MEASURED). `decision_tf_minutes=15` é default de assinatura. Literais de engenharia documentados (`_BAR_MS`, `_BPS_PER_UNIT`, tolerância `1e-6`) não são constantes de domínio — comentário explícito no código.

### 12.5 Fan-in / Fan-out
- **Fan-in real**: `src/analysis/cost_surface.py` (import direto + chamada a `build_labels_both_sides`), `src/analysis/faixa2_caminho_b.py` (import direto). `src/validation/cpcv.py`, `src/models/dataset.py`, `src/models/pipeline.py` só REFERENCIAM em docstring/comentário — consomem `labels.parquet` já materializado via `lake`, não importam o módulo.
- **Fan-out**: `fill_model.simulate_fill_arrays` (fora de escopo), `weights.apply_weights`, `src.exchange.filters.load_filters_asof`, `src.features.groups.group_c.c01_atr_20`/`c02_atr_20_pct`, `src.data.lake.query_bars`/`query_funding`.
- **import-linter**: `features não importa labels` e `labels só é lido por models/validation/backtest` (pyproject.toml linhas 121-139). `src.analysis` NÃO está na lista de proibidos e de fato importa `src.labels` diretamente — único pacote de produção fora de models/validation/backtest a fazer isso hoje.

### 12.6 Substituibilidade
Nenhuma interface/ABC — funções puras chamadas diretamente. `LabelConfig` é injetável por parâmetro opcional. **Achado relevante**: nenhum CLI (`quant labels build`, listado em CLAUDE.md) foi encontrado no repo — o único chamador de produção real de `build_labels_for_symbol`/`write_labels_atomic` é `src/analysis/cost_surface.py` (ferramenta de varredura) e a suíte de testes. O artefato `labels/v1/labels.parquet` e `data/label_engine_runs/label_engine_runs.parquet` (movido de `experiments/` em 2026-08-22 -- nome do diretório antigo sinalizava exploratório/descartável, incompatível com um log de produção lido de volta pelo próprio pipeline) já existem em disco.

### 12.7 Testes
`tests/unit/test_labels_triple_barrier.py` — cobre `round_to_tick`, `config_hash`/`verify_config_hash` (parametrizado sobre os 8 campos), `build_labels` nos 4 desfechos × ambos os lados com valores conferidos à mão, `assert_label_invariants`, e 4 testes `integration` sobre recorte real 2024-01-01/15 (invariantes, determinismo bit-exato via `.equals()`, cobertura dos 4 desfechos). Sem teste: `_as_date`, `_ms_to_date`, `_ms_epoch_to_utc`, `write_labels_atomic` (sem teste unitário dedicado neste arquivo).

### Divergências PRD × código (6)
1. **TF de decisão 30m (PRD, prosa) vs 15m (PRD YAML + código)** — §3.1/§3.3(prosa)/§3.4/§3.6 do PRD ainda descrevem "barra de 30m" e "time_stop=16 barras/8h"; o próprio bloco YAML de §3.3 (linha 824) e `constants.yaml`/código já usam 15m/32 barras. Inconsistência interna do PRD — código e `constants.yaml` são a fonte consistente. Mesma classe de erro já documentada em `environments.py`/`alpha_monotonic_consistency_min_envs`.
2. **`t_post`**: PRD diz `t0 + latência_decisão` (§3.1); código sempre usa `t_post = t0` — simplificação explícita e documentada (nenhuma constante de latência existe ainda em `constants.yaml`).
3. **Coluna `t_exit`**: PRD schema (§3.5) lista `t_exit` como coluna própria; código não tem essa coluna — não documentada como decisão, parece simplesmente não implementada.
4. **`adverse_selection_bps`**: PRD descreve como "markout pós-fill" (medido); código escreve o MESMO valor constante (`constants.yaml`, 1.5 bps ASSUMED) em toda linha, e nunca subtrai de `ret_net` — decisão conservadora explicitamente documentada no código. Uma medição real de markout já existe (`src/execution/fill_simulator.py`, nota em `constants.yaml` linhas 247-253) mas é reservada para calibração futura (§9.5, Sprint 15-16), não alimenta esta coluna hoje.
5. **`mfe_atr_units`**: coluna existe no código (Faixa 2, "D3") mas não está no schema §3.5 do PRD — código à frente da documentação, não erro de comportamento.
6. **`side`**: PRD diz `int8`, domínio "−1/0/+1"; código só aceita `+1`/`-1` (`ValueError` para `side=0`) — interpretado no código como artefato de copy-paste da coluna `label` adjacente, documentado explicitamente (item 1 da docstring do módulo).

### Observações do executor
- Nenhum CLI real (`quant labels build`) foi localizado no repo — comando listado em CLAUDE.md parece aspiracional neste ponto do Sprint.
- `src.analysis` não consta no import-linter como proibido de importar `src.labels`, ao contrário do que a hierarquia de camadas do PRD (§14.2, "exchange→data→features→labels→...") poderia sugerir para um pacote de análise fora do pipeline principal.

---

---

## Estágio 5 — PESOS

### 12.1 Arquivos
| caminho | linhas |
|---|---|
| `src/labels/weights.py` | 126 |

### 12.2 Funções catalogadas
2 funções públicas: `compute_concurrency_and_uniqueness`, `apply_weights`.

### 12.3 Matemática
- **Fórmula de unicidade**: implementação EXATA do procedimento do PRD §0.2 R4 — `uniqueness[i] = mean(1/concorrência)` sobre as posições `[idx0_i, idx1_i]` que o label `i` ocupa. A posição no array ordenado por `t0` faz o papel do `idx()`/`closeIdx` do AFML (inclui gaps de dado de graça, sem grid de tempo físico reconstruído — decisão documentada). Concorrência calculada em O(n) via array de diferenças + `cumsum` (sem matriz n×n); unicidade via soma de prefixos de `1/concorrência` dividida pelo span. `N_eff = Σ uniqueness` é medido a jusante (`experiment_log.summarize_labels`), nunca fórmula fechada — B24 citado nominalmente no cabeçalho do módulo.
- **`sample_weight` final**: `(uniqueness * |ret_gross|) / mean(uniqueness*|ret_gross|)` (AG-452 — era `|ret_net|`; o custo não é propriedade do sinal e injetava 30% de peso extra na classe negativa). Concorrência/unicidade calculadas POR LADO (long e short separados — overlap entre lados diferentes no mesmo `t0` não conta); normalização para média 1 feita sobre o dataset COMBINADO (os dois lados juntos), porque a invariante §3.8 é verificada sobre `labels.parquet` inteiro. `ValueError` em dataset degenerado (média zero/não-finita) em vez de `NaN`/`inf` silencioso.

### 12.4 Parâmetros
Nenhum parâmetro de `constants.yaml` — módulo é puramente algorítmico sobre os dados de entrada (`t0`/`t1`/`side`/`ret_net`).

### 12.5 Fan-in / Fan-out
- **Fan-in**: `src/labels/triple_barrier.py` (`build_labels_both_sides` chama `weights.apply_weights` sobre o conjunto combinado), reexportado em `src/labels/__init__.py`.
- **Fan-out**: nenhum — módulo autocontido (só numpy/polars).

### 12.6 Substituibilidade
Duas funções puras, sem estado. Acoplamento a `triple_barrier.py` é só por CONTRATO DE SCHEMA (`_PRE_WEIGHT_SCHEMA`: colunas `side`/`t0`/`t1`/`ret_net`), não por import — a dependência de import vai na direção oposta (triple_barrier importa weights, não o inverso).

### 12.7 Testes
`tests/unit/test_labels_weights.py` — `compute_concurrency_and_uniqueness` com exemplo calculado à mão (3 labels sobrepostos, concorrência/unicidade travadas por valor literal), caso sem sobreposição, array vazio, propriedade estrutural `uniqueness ∈ (0,1]`. `apply_weights`: média 1 (tolerância 1e-9, mais apertada que os `1e-6` de §3.8), concorrência por lado, dataset vazio, `ValueError` em dataset degenerado. Sem função sem teste.

### Divergências PRD × código (1)
1. **§0.2 R4, armadilha 1** — o PRD contrasta em prosa "concorrência pontual" (LdP padrão) vs "vizinhança de sobreposição" (`1+s(2h-1)`) e explicitamente REJEITA a segunda. Não é uma divergência de fato: `compute_concurrency_and_uniqueness` implementa fielmente a concorrência pontual que o PRD elege como correta — registrado aqui só porque a task pediu grep exaustivo de "uniqueness"/"concurrency" contra o PRD; não há erro, é confirmação de conformidade (com uma pequena escolha de implementação documentada: índice de posição no array em vez de mapeamento explícito tempo→índice de barra).

### Observações do executor
- `N_eff` (`Σ uniqueness`) não é calculado dentro de `weights.py` — fica em `src/labels/experiment_log.py::summarize_labels` (lido para este relatório como suporte, não como quarto estágio próprio).

---

## Resumo consolidado

| estágio | arquivos | funções catalogadas | divergências PRD |
|---|---|---|---|
| META-LABEL | triple_barrier.py, _constants.py, _paths.py | 16 | 6 |
| BARREIRAS | triple_barrier.py (trecho), barrier_sweep.py | 8 | 2 |
| PESOS | weights.py | 2 | 1 |

Nenhum bloqueio de leitura. `fill_model.py` não foi lido, conforme instrução de escopo.

---

## Estágio 6 — BARREIRAS

### 12.1 Arquivos
| caminho | linhas |
|---|---|
| `src/labels/triple_barrier.py` | 864 (trecho relevante: precificação/toque de barreira) |
| `src/labels/barrier_sweep.py` | 249 |

### 12.2 Funções catalogadas
8 funções/classes: `round_to_tick`, `_mfe_price`, `_first_barrier_touch` (compartilhada com META-LABEL), o trecho de precificação `tp_price`/`sl_price` dentro de `build_labels`, `ResolvedBarriers` (dataclass), `_pad_for_windows`/`_pad_int_for_windows`, `resolve_barriers_vectorized`.

### 12.3 Matemática
- **Separação por lado**: `tp_atr_mult`/`sl_atr_mult`/`time_stop` são hoje o MESMO multiplicador para os dois lados (`side * sl_atr_mult`, sinal invertido) — simetria herdada, nunca medida; o próprio PRD (§18.7.2) já registra isso como pendência de teste na Faixa 2. Não há `tp_atr_mult_long`/`tp_atr_mult_short` no código hoje.
- **Valores e origem**: `tp_atr_mult=2.0`, `sl_atr_mult=1.5`, `time_stop_bars=32`, `atr_window=20` — todos de `constants.yaml`, classe A ASSUMED, sem literal solto em código de pipeline.
- **Avaliação de toque**: long — TP se `high >= tp_price`, SL se `low <= sl_price`; short — invertido. Fonte de preço SEMPRE `mark_1m` (B11/B12), nunca a barra de 15m nem last price. `tp_price`/`sl_price` calculados a partir de `fill_px` (preço de preenchimento real, não `entry_ref`).
- **`triple_barrier.py` vs `barrier_sweep.py`**: `build_labels` é o MOTOR CANÔNICO DE PRODUÇÃO (laço Python por barra, ~50-60s/lado/config, medido). `resolve_barriers_vectorized` é FERRAMENTA DE VARREDURA (Faixa 2 E1, §18.7.1) que reproduz a MESMA semântica via `sliding_window_view`, explorando que o FILL não depende de tp/sl — reusa `t_entry`/`entry_price_fill`/`atr_at_t0` de `labels/v1/labels.parquet` e só recalcula a barreira por célula de grid. Equivalência exata verificada por teste dedicado, incluindo 1 ano de dado real (tolerância <1e-6 em `ret_net`, zero mismatch em `barrier_hit`).

### 12.4 Parâmetros
Mesmos `tp_atr_mult`/`sl_atr_mult`/`time_stop_bars`/`atr_window` do estágio META-LABEL (compartilhados, `constants.yaml`). Específico de `barrier_sweep.py`: `_WINDOW_SAFETY_MARGIN_BARS=60` (literal de engenharia, não de domínio, documentado), `_BAR_MS` duplicado localmente.

### 12.5 Fan-in / Fan-out
- **Fan-in**: `src/analysis/faixa2_caminho_b.py` (E1, varredura 3x3 por lado), `tests/unit/test_labels_barrier_sweep.py`.
- **Fan-out**: `numpy.lib.stride_tricks.sliding_window_view`. `barrier_sweep.py` deliberadamente NÃO chama `fill_model` (por design — fill não depende de tp/sl).

### 12.6 Substituibilidade
Funções puras. `resolve_barriers_vectorized` recebe todos os parâmetros de barreira como argumentos explícitos (sem acoplar a `LabelConfig`/`constants.yaml` internamente). Levanta `ValueError` se algum trade não tiver janela completa até `horizon_end_ms` — assume implicitamente que o chamador já filtrou `filled` para trades com cauda completa.

### 12.7 Testes
`test_labels_triple_barrier.py` (barreiras dentro de `build_labels`) + `test_labels_barrier_sweep.py` (equivalência escalar↔vetorizado nos 4 desfechos + múltiplos trades simultâneos + 1 ano real). Sem teste direto: `_mfe_price` isolada, caminho de padding de `_pad_for_windows`/`_pad_int_for_windows` (nenhum teste força `start_idx + window_bars > tamanho do array`).

### Divergências PRD × código (2)
1. **Vetorização "pendente" (PRD §18.7.1/§18.7.2) vs já implementada (código)**: PRD descreve em tom prospectivo ("Escopo do Sprint 6: rodar o grid 2D uma vez por lado") algo que `barrier_sweep.py` já entrega e testa — texto desatualizado, não erro de comportamento (git log confirma commit "FASE 2 E1 — varredura de barreiras vetorizada via sliding_window_view").
2. **Varredura de `tp_atr_mult`/`sl_atr_mult` "pendente" (PRD §3.3/§18.5.1) vs em andamento**: `constants.yaml` já declara `sweep_required: true`/`sweep_range`, e `src/analysis/faixa2_caminho_b.py` já roda grid 3x3 por lado — mesmo item de pendência do PRD sendo fechado pelo código atual, informativo.

### Observações do executor
- A simetria long/short de tp/sl é limitação estrutural atual, não bug — o PRD já a registra como pendência de teste, então não foi catalogada como divergência (o PRD não afirma que a assimetria já existe).

---

---

## Estágio 7 — FEATURES

Status: **presente**. Escopo lido integralmente: `src/features/build.py` (215 linhas), `src/features/_sources.py` (202), `src/features/support.py` (268), `src/features/groups/{group_a,group_b,group_c,group_d,group_e}.py` (47/22/47/30/57), `src/features/_constants.py` (44), `src/features/_paths.py` (36), `src/features/registry.yaml` (302), `src/features/__init__.py` (27).

### 12.1 Arquivos e superfície de funções

40 funções catalogadas (assinatura completa + docstring literal + arquivo:linha + pública/privada + se carrega valor de decisão):

- **build.py** (5): `_to_numpy` (privada), `FeatureWindows.from_constants` (classmethod, lê os 13 hiperparâmetros de janela de `constants.yaml` uma única vez), `compute_t1_features` (núcleo puro sem IO — L106), `apply_min_warmup_mask` (corte uniforme, invariante 5 do §2.15 — L178), `build_t1_features` (entrypoint com IO — L194).
- **_sources.py** (7): `_as_date` (privada), `load_bars_15m` (delega a `src.data.lake.query_bars`), `asof_align_backward` (asof-join causal `backward`, L38 — primitiva de alinhamento reusada por funding e OI), `load_funding_aligned`, `_list_metrics_day_files` (privada), `load_oi_series_deduped` (dedup determinístico de `create_time` duplicado + tratamento de `sum_open_interest<=0`, L95), `load_oi_aligned`.
- **support.py** (11): `true_range`, `_first_valid_index` (privada), `wilder_smooth`, `atr_wilder`, `ema`, `rsi_wilder`, `realized_vol`, `rolling_zscore`, `efficiency_ratio`, `expanding_zscore_strict`, `expanding_percentile_rank_strict`. `true_range`/`atr_wilder`/`realized_vol` são especificamente de ATR/volatilidade — documentadas aqui só com assinatura+docstring (ver estágio VOLATILIDADE para a matemática funda); as demais (inclusive `wilder_smooth`, compartilhada entre ATR e RSI) recebem análise completa porque alimentam também features não-volatilidade (RSI/B01, z-scores de D/E).
- **groups/group_a.py** (2): `a05_ret_vol_norm_4`, `a13_dist_ema48_atr` — resolvem uma ambiguidade de unidade do PRD (ver §12.6).
- **groups/group_b.py** (2): `b01_rsi_14` (T1), `b07_efficiency_ratio_48` (T2, insumo do Regime Engine §4.2, não do vetor de treino do Alpha V1).
- **groups/group_c.py** (4): `c01_atr_20`, `c02_atr_20_pct` (ambas T2, mas insumo direto de A05/A13/C06/C07/E27f), `c06_vol_ratio_12_96`, `c07_vol_pctile_expanding`.
- **groups/group_d.py** (2): `d03f_volume_z_expanding`, `d06f_taker_imbalance_z_48`.
- **groups/group_e.py** (4): `e02f_funding_z_expanding`, `e10f_oi_change_z_48`, `round_trip_cost_bps` (reproduz `c_médio(assimétrico)=0,055%` de §0.2 R2), `e27f_cost_atr_ratio`.
- **_constants.py** (2): `_load_all` (privada, cache em memória), `load_constant` (levanta `KeyError` acionável, nunca default silencioso).
- **_paths.py** (1): `capacity_symbol_dir` (levanta `FileNotFoundError` cedo).

`FeatureWindows` é um `dataclass(frozen=True, slots=True)` com 13 campos (10 janelas + `maker_fee`/`taker_fee`/`min_warmup_bars`) — não é uma função, mas é a estrutura central de configuração do módulo.

### 12.2 Matemática (perguntas específicas da task)

- **T1_FEATURE_IDS (ordem completa, build.py:29-40):** `A05_ret_vol_norm_4`, `A13_dist_ema48_atr`, `B01_rsi_14`, `E27f_cost_atr_ratio`, `C06_vol_ratio_12_96`, `C07_vol_pctile_expanding`, `D03f_volume_z_expanding`, `D06f_taker_imbalance_z_48`, `E02f_funding_z_expanding`, `E10f_oi_change_z_48`. Idêntica em ordem à tabela §2.13 do PRD. `SUPPORT_FEATURE_IDS` (T2, não entram no vetor de treino): `C01_atr_20`, `C02_atr_20_pct`, `B07_efficiency_ratio_48`.
- **Rolante vs expansiva:** rolante fixa (inclui a barra `t`) — A05, A13, B01, C06, D06f, E10f, E27f. Expansiva estrita (só índices `< t`) — C07 (posto da vol realizada), D03f, E02f. Distinção declarada explicitamente na docstring de `support.py` (L11-20) como "duas famílias de janela, deliberadamente distintas (banned pattern B02)".
- **Método de interpolação de quantil:** único uso em T1 é C07, via `expanding_percentile_rank_strict` (support.py:209). NÃO é interpolação estatística padrão nem convenção de mid-rank — é `rank_t = #{i<t : x_i < x_t} / #{i<t : x_i não-NaN}`, calculado com Fenwick tree sobre posto denso GLOBAL (`argsort(kind="stable")`, uma vez), empates desfeitos por ordem de chegada (não por metade).
- **Normalização — por fold, expansiva ou global:** expansiva CAUSAL sobre a série completa passada à função (não reseta por fold de CPCV — essa responsabilidade é de camadas consumidoras). Não há normalização global banida (estatística fixa reaplicada retroativamente); as duas primitivas expansivas usam Welford online (`expanding_zscore_strict`) e Fenwick tree (`expanding_percentile_rank_strict`), ambas O(n)/O(n log n) de um único passe.
- **Teste de paridade lote↔streaming:** `tests/parity/test_features_parity.py`, tolerância `1e-8`. Dois testes: (1) últimas 500 barras, streaming = chamadas sucessivas de `compute_t1_features` sobre prefixos crescentes (`bars.slice(0, row_idx+1)`), comparado contra a linha correspondente do lote (`max_abs_dev < 1e-8`); (2) ponto único `row_idx=2500`, mais barato, `np.isclose(atol=1e-8, rtol=0)`.
- **`causal_proof` no registry:** campo de texto livre, obrigatório, formato observado (não schema tipado): prosa do mecanismo + citação `"testado em tests/ARQUIVO.py::NOME_TESTE"`. **Achado:** não há verificação automática de que a função citada exista — `test_features_groups.py::test_a13_causalidade` documenta no próprio docstring um caso histórico em que o registry citava essa função antes dela existir (gap fechado, mas sem trava estrutural contra recorrência).

### 12.3 Parâmetros e proveniência

13 constantes de janela/custo lidas de `config/constants.yaml` via `load_constant`, todas classe B `ASSUMED` ("convenção herdada do PRD §18.5.2, nunca testada", `review_by: sprint_8`) exceto `atr_window` (classe A, `sweep_required: true`, `sweep_range: [10,30]`, `review_by: sprint_6`) e `maker_fee`/`taker_fee` (classe C `MEASURED`, tabela de fees Binance VIP 0): `feature_a05_ret_lookback_bars=4`, `feature_a13_ema_window=48`, `feature_b01_rsi_window=14`, `feature_b07_efficiency_ratio_window=48`, `feature_c06_vol_ratio_short_window=12`, `feature_c06_vol_ratio_long_window=96`, `feature_c07_vol_pctile_window=48`, `feature_d06f_taker_imbalance_window=48`, `feature_e10f_oi_change_window=48`, `atr_window=20`, `min_warmup_bars=2000`, `maker_fee=0.0002`, `taker_fee=0.0005`.

Literais de código (não em `constants.yaml`): peso `0.5` (round_trip_cost_bps, cenário 50/50 TP/SL) e fator `2.0` (A05) — ambos na whitelist `_ALLOWED_NUMERIC_LITERALS` do lint; `50.0`/`100.0` (RSI, escala fixa) com `# noqa: magic-number` explícito; **`10000`** (conversão para bps, group_e.py:49 e :56) sem entrada em constants.yaml e sem `noqa` — ver §12.7 sobre por que passa despercebido pelo lint.

### 12.4 Fan-in / fan-out

**Fan-in** (quem consome `src.features`): `src/labels/triple_barrier.py:88` (group_c, mesmas primitivas de ATR do Feature Engine), `src/models/alpha.py:39`, `src/models/baselines.py:66`, `src/models/dataset.py:43-44` (T1_FEATURE_IDS + build), `src/regime/build.py:17` (carrega T1/T2 prontas via `build_t1_features`), `src/regime/classifier.py:45-46` (support/FloatArray), `src/regime/stress.py:48` (support/FloatArray + citações de c07/e02f), `src/risk/limits.py:53` (round_trip_cost_bps), `src/validation/leakage.py:92` (lê `registry.yaml` diretamente), `src/analysis/cost_surface.py:82`, `src/analysis/faixa2_e2_research.py:40-42`, `src/analysis/faixa2_caminho_b.py:40,402,578`, `src/analysis/faixa1_6_reconciliation.py:963`. `research/research_t2.py` (fora de `src/`) consome indiretamente via testes mas reimplementa primitivas próprias.

**Fan-out** (o que `src.features` consome): `src.data.lake.query_bars` e `src.data._util.metrics_timestamp_to_ms` (únicas dependências externas ao pacote, ambas em `_sources.py:17-18`); todo o resto é fan-out interno ao próprio pacote (`build.py` → `_sources`, `support`, `_constants`, `groups.*`).

### 12.5 Import-linter e hierarquia

`pyproject.toml` declara 3 contratos `forbidden` que tocam `src.features`: "features não importa labels" (L120-124), "labels só é lido por models/validation/backtest" (L132-139, `src.features` está na lista `source_modules`), "features não importa analysis" (L153-157). `root_packages = ["src"]` — `research/` fica fora da varredura do import-linter.

### 12.6 Substituibilidade

Sem interface/protocolo formal — `compute_t1_features` é o único ponto de entrada, função pura sem classe. `FeatureWindows` permite injeção explícita de configuração (parâmetro `windows`) só para bypassar `constants.yaml` em teste, sem abstração de "motor de features" plugável. Impedimentos: acesso a colunas de `bars_15m` por nome fixo sem validação de schema formal dentro da função; `T1_FEATURE_IDS`/`SUPPORT_FEATURE_IDS` são tuplas module-level, não parametrizáveis por instância.

### 12.7 Testes

Arquivos: `test_features_support.py`, `test_features_sources.py`, `test_features_groups.py`, `test_features_build.py`, `tests/parity/test_features_parity.py`. Nenhum teste marcado `golden` no escopo (o único `golden` do repo é `tests/golden/test_sprint8_reproducibility.py`, fora de FEATURES).

Sem teste direto: `_to_numpy`, `FeatureWindows.from_constants`, `apply_min_warmup_mask` (só indireta via `test_warmup_uniforme_*`), `load_bars_15m`, `load_funding_aligned`, `load_oi_aligned` (só a primitiva `asof_align_backward` é testada isoladamente), `_as_date`/`_list_metrics_day_files`/`_first_valid_index`/`_load_all` (privadas), **`load_constant`/`_constants.py` inteiro** (nenhum teste exercita o `KeyError` de constante ausente), `capacity_symbol_dir` (`FileNotFoundError` não testado diretamente).

Testes que travam comportamento (tolerância zero, valor literal ou não-enforcement deliberado):

| teste | tipo | nota |
|---|---|---|
| `test_paridade_lote_streaming_ultimas_500_barras` | tolerância zero | `max_abs_dev < 1e-8`, 13 colunas |
| `test_paridade_streaming_bate_com_recompute...` | tolerância zero | ponto único, `atol=1e-8` |
| `test_determinismo_bit_a_bit` | tolerância zero | `.equals(null_equal=True)` |
| `test_determinismo_hash` | tolerância zero | hash exato |
| `test_e27f_round_trip_cost_bps_reproduz_0_055_pct` | valor literal | `5.5` bps, reproduz §0.2 R2 |
| `test_registry_tf_e_15m_em_todas_as_entradas` | valor literal | trava correção de dívida documental |
| `test_registry_parity_tested_true_em_todas_as_entradas` | valor literal | — |
| `test_registry_cobre_todo_o_vetor_t1` | valor literal | set(T1 registry) == set(T1_FEATURE_IDS) |
| `test_wilder_smooth_seed_e_recursao` | valor literal | cálculo manual |
| `test_true_range_valor_conhecido` | valor literal | cálculo manual |
| `test_rsi_wilder_todo_ganho_da_100`/`_flat_da_50` | valor literal | extremos 100.0/50.0 |
| `test_t1_ortogonalidade_spearman_2anos` | valor literal (parcial) | **não falha o build** em violação — ver §12.8 |

### 12.8 Divergências código vs PRD

1. **§2.15 invariante 6 (ortogonalidade T1) é um `assert` no PRD, mas o teste não impõe.** `PRD_V3_2_UNIFICADO.md:774-775` escreve a invariante como assert rígido (`<= 0.70` sempre). `tests/unit/test_features_build.py:121-174` (`test_t1_ortogonalidade_spearman_2anos`) calcula a matriz real sobre ~2 anos e deliberadamente só *reporta* violações (print/log), nunca falha — decisão ancorada em §2.13 ("resolução por permutação é tarefa do Sprint 6+"). Medido em 2026-08-08: 2 pares violam (`A13_dist_ema48_atr` × `B01_rsi_14` = 0,947; `E27f_cost_atr_ratio` × `C07_vol_pctile_expanding` = -0,913), presentes no T1 atual sem remoção.

2. **Nome do arquivo de registry e `tf` do exemplo em §2.14.** PRD (`PRD_V3_2_UNIFICADO.md:734-753`) diz `features/registry_v{n}.yaml` e o próprio exemplo de schema usa `tf: 30m`. Código real é `src/features/registry.yaml` (sem sufixo de versão — confirmado como o path lido em produção por `src/validation/leakage.py:92`), com `tf: 15m` em todas as 13 entradas. A divergência de TF já é extensivamente autodocumentada na "NOTA DE TF" do próprio `registry.yaml` (L15-60), mas essa nota só menciona as tabelas §2.2-2.6 como residuais em "30m" — não menciona que o exemplo de schema do próprio §2.14 também está em 30m.

3. **Ambiguidade de unidade de `ATR_20` em A05/A13 (§2.2).** PRD usa o rótulo genérico `ATR_20` nas fórmulas de A05 (`ln(C_t/C_{t−4}) / (ATR_20 × 2)`) e A13 (`(C_t − EMA_48) / ATR_20`) sem distinguir absoluto (C01) de percentual (C02). `src/features/groups/group_a.py` (docstring do módulo, L1-23) resolve por análise dimensional — A05 usa `atr_20_pct`, A13 usa `atr_20_abs` — auditável contra §0.4 (ATR mediana 15m = 0,305%), mas é uma interpretação do código sobre texto ambíguo do PRD, do mesmo padrão dos 2 casos já conhecidos (`environments.py`, `alpha_monotonic_consistency_min_envs`).

4. **Lookback de A05 (§2.2): PRD tabula "4+20", registry lista só "4".** `PRD_V3_2_UNIFICADO.md:497` declara lookback combinado `4+20` (retorno + ATR embutido no denominador). `src/features/registry.yaml:67` (`A05_ret_vol_norm_4`) declara `lookback_bars: 4`, sem contabilizar os 20 do `atr_20_pct` usado na normalização.

### Observações do executor

- **Gap objetivo no lint de proveniência.** `tools/lint/banned_patterns.py:121-128` (Regra 1, §16.10.2 — "nenhum literal numérico solto fora de constants.yaml") só inspeciona `isinstance(node.value, float)`. Em `src/features/groups/group_e.py:49` e `:56`, o literal `10000` (conversão para bps, usado em `round_trip_cost_bps` e `e27f_cost_atr_ratio`) é escrito como `int` Python (sem ponto decimal), não `float` — passa despercebido pela Regra 1 sem estar em `constants.yaml` e sem `# noqa: magic-number`, apesar de CLAUDE.md descrever a regra como "nenhum literal numérico", não "nenhum literal float". Observação de cobertura do lint, verificável lendo o AST-check; não avaliada quanto a mérito de correção.
- **Padrão de divergência registry-vs-teste já ocorreu e foi autocorrigido, mas sem trava contra recorrência.** `test_features_groups.py::test_a13_causalidade` (docstring L86-96) documenta que `registry.yaml` citava esse teste como `causal_proof` de A13 antes da função existir de fato no arquivo (só `test_a05_causalidade` existia). Gap fechado, mas nada impede que `registry.yaml` volte a citar uma função inexistente — é convenção textual, não verificada por CI.
- `research/research_t2.py` (fora do escopo direto de leitura, fora de `src/`) reimplementa primitivas próprias (`log_return_n`, `rolling_corr`) em vez de reusar `support.py`, para as ~70 features candidatas T2/T3. Segunda base de código de features em paralelo a `src/features/`, não sujeita aos mesmos banned patterns por não estar em `src/`. Registrado só como observação de superfície.
- Claim numérica "142 testes" na docstring de `src/features/_sources.py::load_bars_15m` (L34) não tem corroboração localizável: contagem direta de `def test_` em `tests/parity/test_resample_parity.py` + `tests/unit/test_data_resample.py` dá 20 (6+14), e nenhuma outra ocorrência de "142" aparece em `.py`/`.md` do repo, incluindo `docs/SPRINT_LOG.md`.
- `min_warmup_bars=2000` é aplicado como corte uniforme sobre as 10 features T1 (`apply_min_warmup_mask`), mas o valor vem de convenção herdada do PRD (§18.5.2), `provenance: ASSUMED`, nunca testada contra a convergência numérica real das séries expansivas/EMA48 — já sinalizado como pendência aberta pelo próprio `constants.yaml`, reforçado aqui por não haver, no escopo desta task, nenhuma medição de convergência real.


---

## Estágio 8 — LEARNER

### 12.1 Localização e volume
- `src/models/alpha.py` — 519 linhas. Núcleo de treino: `XGBHyperparams`, `build_design_matrix`, `fit_side_model`, `SideModelResult`, `run_fold`, `run_all_folds`, `FoldResult`, `assemble_predictions_table`, `PREDICTIONS_SCHEMA_COLUMNS`.
- `src/models/monotonic.py` — 227 linhas. Camada 1 (restrições monotônicas): `screen_monotone_constraints`, `compute_ic_by_env`, `_assign_from_ic`, `_forced_constraint_for`.
- `src/models/pipeline.py` — 484 linhas. Orquestração ponta a ponta (`run_layer1_sprint`) + escrita atômica de `predictions.parquet`, `alpha_layer1_report.json`, diagnósticos por fold×lado.
- `src/models/dataset.py` — 156 linhas. `build_modeling_frame` (junta labels + features T1 + regime), `side_subset` (filtra NOFILL/warmup por lado).
- 27 funções/classes catalogadas no total (ver `cd_06_learner.json`).

### 12.2 Funções públicas vs privadas, o que carrega decisão
Públicas que carregam decisão de modelo: `fit_side_model`, `run_fold`, `run_layer1_sprint`, `screen_monotone_constraints`, `compute_ic_by_env`. Privadas que carregam decisão: `_assign_from_ic` (atribui sinal ±1/0 da restrição monotônica), `_forced_constraint_for` (sobrescreve por identidade contábil), `_stratified_calib_split` (define a população de calibração). Puramente mecânicas/I-O, sem decisão: `build_design_matrix`, `_derived_seed`, `_unique_test_bars`, `assemble_predictions_table`, todas as `write_*_atomic`.

### 12.3 Matemática
- **Objetivo XGBoost:** `objective="binary:logistic"` em dois `xgb.XGBClassifier` independentes (`M_long` treinado só sobre `side_subset(side=1)`, `M_short` só sobre `side_subset(side=-1)`) — nunca `multi:softprob`. Confirma B18/§5.2 do PRD. `src/models/alpha.py:242`.
- **Hiperparâmetros:** nenhum literal solto em `alpha.py` — todos vêm de `XGBHyperparams.from_constants()` → `config/constants.yaml` (`alpha_xgb_max_depth=3`, `n_estimators=300`, `learning_rate=0.03`, `subsample=0.8`, `colsample_bytree=1.0`, `min_child_weight=30`, `reg_lambda=5.0`, todos classe B `ASSUMED` exceto `colsample_bytree`, classe B `DERIVED`). `scale_pos_weight` é calculado em runtime (`n_neg/n_pos` de `y_fit`, o subconjunto **pós**-holdout de calibração — não do `train_side_df` inteiro). `tree_method="hist"` e `eval_metric="logloss"` são literais de código sem entrada em `constants.yaml`. Nenhum uso de Optuna neste sprint.
- **Derivação de `monotone_constraints`:** por feature T1 × lado — `compute_ic_by_env` calcula IC de Spearman(feature, `ret_net`) dentro de cada um dos 6 ambientes fixos de `src.models.environments` (RANGE/TREND × tercil de `E27f_cost_atr_ratio`), `NaN` se `n_valid < 5` ou variância nula. `_assign_from_ic` tira a média dos ICs válidos → sinal dominante; conta `n_consistent` = quantos ICs válidos concordam em sinal com o dominante; atribui esse sinal só se `n_consistent >= alpha_monotonic_consistency_min_envs` (constants.yaml = **6**, i.e. exige unanimidade entre os ambientes com dado), senão `0`. `_forced_constraint_for` **sobrescreve** esse resultado estatístico para 2 features por identidade contábil (IC medido ainda reportado, só não decide): `E27f_cost_atr_ratio = -1` fixo nos dois lados; `E02f_funding_z_expanding = -1` no long / `+1` no short. As 4 dummies de regime recebem `0` sempre.
- **Equivalência com `stability.py` (Camada 2):** `stability.py` importa e reusa `monotonic.compute_ic_by_env` — mesma fonte de IC por ambiente. Mas a fórmula de decisão diverge: `monotonic._assign_from_ic` compara uma contagem absoluta (`n_consistent`) contra um limiar de contagem; `stability._score_from_ic` normaliza por denominador FIXO 6 (`consistencia = n_consistent/6`, `forca = Σ|IC válido|/6`) e combina em `estabilidade = forca * consistencia**2` contra um limiar contínuo (`alpha_stability_screen_limiar`, classe A, ainda não varrido). Mesma fonte de dado, perguntas diferentes: monotonic decide SINAL (restrição binária); stability decide SOBREVIVÊNCIA (triagem contínua) — exatamente como o próprio docstring de `stability.py` documenta. **Camada 2 não é chamada por `pipeline.run_layer1_sprint` nesta rodada** (ver Observações).
- **`n_estimators`/early stopping:** 300 árvores fixas, sem early stopping implementado — `best_iteration` é sempre gravado `null` com nota explícita (`_BEST_ITERATION_NOTE`).
- **Seed/determinismo:** `alpha_random_seed=42` (classe D). `_derived_seed(base_seed, *parts)` compõe uma seed determinística por (fold, lado, propósito) via aritmética modular. Reprodutibilidade bit-a-bit fixada por `tests/golden/test_sprint8_reproducibility.py` (fold 0, tolerância zero em `hhi`/`gain_by_column`/`concentration_shares`/`n_trees`).

### 12.4 Parâmetros e proveniência
Todos os hiperparâmetros XGBoost + `alpha_calibration_holdout_frac` + `target_signal_rate` + `alpha_monotonic_consistency_min_envs` + `alpha_random_seed` + `alpha_layer1_permanence_min_paths` vêm de `config/constants.yaml` com proveniência declarada (a maioria `ASSUMED` classe B, `target_signal_rate` é classe A `DERIVED` com `sweep_range` declarado). Literais de código sem entrada em `constants.yaml`, tratados explicitamente como "não constante de domínio" nos comentários: `tree_method`, `eval_metric`, `_MIN_OBS_PER_ENV=5` (mínimo matemático para Spearman não degenerar), `_DATE_BUFFER_DAYS=3` (folga de I/O), `REGIME_ONEHOT_LEVELS` (convenção de codificação categórica, R1 = referência drop-first).

### 12.5 Fan-in / Fan-out
- **Fan-in:** `src/models/pipeline.py::run_layer1_sprint` chama `alpha.run_all_folds` duas vezes (Camada 1 e Camada 0); `src/models/backtest_lite.py` e `src/models/baselines.py` consomem `FoldResult`; `src/analysis/faixa1_5_prerequisites.py` e `faixa1_6_reconciliation.py` reusam `monotonic.compute_ic_by_env`/`screen_monotone_constraints`/`alpha.fit_side_model` sem retreinar produção; `src/validation/leakage.py` lê o schema de `predictions.parquet` para o teste de vazamento #10.
- **Fan-out:** `alpha.py` depende de `src.validation.cpcv.CPCVSplit`, `src.models.monotonic`, `src.models.dataset`, `src.models.hhi`, `src.features.build.T1_FEATURE_IDS`. `dataset.py` depende de `src.features.build.build_t1_features`, `src.regime.build.build_regimes`, `src.validation.cpcv.load_labels_v1`. `monotonic.py` depende de `src.models.environments.assign_environments` e `scipy.stats.spearmanr`.

### 12.6 Import-linter e substituibilidade
Contratos ativos relevantes: `"models não importa execution"` e `"models não importa analysis"` (ambos `forbidden`, `pyproject.toml`). `"labels só é lido por models, validation, backtest"` permite `src.models` ler `src.labels`. **A regra "alpha não pode importar meta" (CLAUDE.md) ainda é só um TODO comentado em `pyproject.toml:159-161`** — não formalizada porque `src.models.meta` não existe como arquivo.

Substituibilidade: `xgb.XGBClassifier` é instanciado diretamente dentro de `fit_side_model`, sem interface/Protocol de "Learner" abstrata. Qualquer substituto precisaria expor `.fit`/`.predict_proba` (contrato sklearn-like) e aceitar `monotone_constraints`/`scale_pos_weight` como kwargs nativos — do contrário a Camada 1 inteira precisaria ser removida. `build_design_matrix` devolve numpy puro sem nomes de coluna, contando com a ordem posicional de `DESIGN_COLUMNS` coincidir com a ordem de `monotone_constraints` — acoplamento implícito não garantido por tipo.

### 12.7 Testes
19 comportamentos testados listados em `cd_06_learner.json`. Destaques:
- **Golden, tolerância zero:** `tests/golden/test_sprint8_reproducibility.py::test_fold_0_reproduz_diagnostico_commitado_bit_a_bit` — compara `hhi`, `max_share`, `n_features_over_1pct`, `n_trees`, `gain_by_column`, `concentration_shares` via `==` exato contra `models/{model_id}/diagnostics/fold_0_*.json` commitado.
- **Valor literal esperado:** `test_assign_constraint_5_de_6_nao_passa_no_limiar_6` fixa que 5/6 ambientes consistentes NÃO atribui restrição sob o limiar de produção (6, unanimidade); `test_fit_side_model_e02f_forcado_*` fixa a restrição econômica por lado de `E02f_funding_z_expanding`.
- Sem teste unitário dedicado encontrado (no escopo lido): `run_all_folds` isolado, `assemble_predictions_table` isolado, `date_bounds`.

### Observações do executor
- `src.models.stability` (Camada 2) tem testes próprios num arquivo separado, mas **não é chamada por `pipeline.run_layer1_sprint`** — confirmado também pelo comentário `"Camada 2 não implementada nesta rodada"` em `tests/unit/test_models_alpha.py:276`.
- `run_fold` calcula `tau` aplicando o calibrador sobre `X_all` (fit_idx + calib_idx), não só sobre o holdout de calibração — para as linhas de `calib_idx` isso é a mesma população que ajustou o calibrador. Documentado como intencional no docstring do módulo (linhas 21-25), registrado aqui só por ser um detalhe matemático não óbvio de fora.

---

---

## Estágio 9 — CALIBRAÇÃO

### 12.1 Localização e volume
Não é um arquivo dedicado — vive dentro de `src/models/alpha.py` (bloco de `fit_side_model`, linhas ~231-266, e `run_fold`, linhas ~376-379) e é persistida por `src/models/pipeline.py::write_predictions_atomic`.

### 12.2 Funções
- `fit_side_model` (bloco de calibração): `IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(raw_calib, y_calib, sample_weight=w_calib)` — `alpha.py:260-262`.
- `_stratified_calib_split` — define a população de calibração (holdout estratificado do treino do fold).
- `run_fold` — aplica `calibrator.predict` sobre as saídas cruas do modelo no conjunto de teste do fold, produzindo `p_long`/`p_short`/`confidence`.

### 12.3 Matemática
- **Biblioteca:** `sklearn.isotonic.IsotonicRegression` — import direto de scikit-learn, sem implementação própria.
- **Ajustada sobre qual conjunto:** um sub-split do TREINO do fold (`X_calib`/`y_calib`, `holdout_frac=alpha_calibration_holdout_frac=0.25`), nunca o OOF nem o teste — consistente com B01/B08 do CLAUDE.md e com §5.9 passo 9 do PRD ("sub-split interno do fold").
- **`confidence` vs `confidence_rank`:** `confidence = max(p_long, p_short)`, sempre a saída CALIBRADA aplicada ao conjunto de teste do fold, em `src/models/alpha.py`. **`confidence_rank` não é calculado em nenhum lugar de `src/models/`** — só existe em `src/analysis/faixa1_5_prerequisites.py::add_confidence_rank(predictions)`, que recebe uma CÓPIA em memória do `predictions.parquet` já escrito, adiciona a coluna, e nunca regrava o parquet de produção. `confidence` e `confidence_rank` **não são colunas persistidas juntas** no artefato oficial — `confidence_rank` existe só como saída de análise pós-hoc.

### 12.4 Parâmetros
`alpha_calibration_holdout_frac=0.25` (`constants.yaml`, ASSUMED classe B). `out_of_bounds="clip"`, `y_min=0.0`, `y_max=1.0` são literais de código do `IsotonicRegression`. `tau` é derivado (`np.quantile(calibrated_train_all, 1 - target_signal_rate)`).

### 12.5 Fan-in / Fan-out
`pipeline.write_predictions_atomic` persiste `p_long`/`p_short`/`confidence` sem `confidence_rank`. `src/analysis/faixa1_5_prerequisites.py`, `src/analysis/calibration_diagnostics.py` e `src/analysis/attribution.py` consomem `confidence`/`raw_score` já persistidos para diagnóstico pós-hoc — `calibration_diagnostics.py` se autodeclara "PÓS-HOC, EXPLORATÓRIO, NUNCA INSUMO DE TREINO" no próprio docstring.

### 12.6 Import-linter e substituibilidade
Sem contrato específico violado — `analysis` importa de `models`, nunca o contrário, coerente com `"models não importa analysis"`. `IsotonicRegression` é instanciada diretamente sem abstração de "Calibrator" injetável; qualquer substituto (ex. Platt scaling) exigiria editar `fit_side_model` diretamente. Contrato implícito: `SideModelResult.calibrator` precisa expor `.predict(array) -> array`.

### 12.7 Testes
`test_predictions_parquet_real_schema_e_invariantes` fixa `tuple(preds.columns) == alpha.PREDICTIONS_SCHEMA_COLUMNS` — confirma por teste que `confidence_rank` NÃO está no schema real persistido. Não há teste unitário dedicado ao `IsotonicRegression` isolado no escopo lido; `add_confidence_rank` é testado em `tests/unit/test_analysis_faixa1_5_prerequisites.py`, fora do escopo de leitura direta desta task.

### Divergência PRD × código (headline deste estágio)
**PRD §5.12 (linha 1350)** lista `confidence_rank` como coluna OFICIAL do schema de `predictions/alpha/{model_id}/predictions.parquet`. **`PREDICTIONS_SCHEMA_COLUMNS` (código, `alpha.py:500-518`) tem 17 colunas e não inclui `confidence_rank`** — a coluna só existe como função de pós-processamento em `src/analysis/faixa1_5_prerequisites.py`, aplicada a uma cópia em memória, nunca regravada no parquet oficial. A FÓRMULA descrita no PRD (`rank(score_raw)/count(), .over(fold_id)`) bate exatamente com a implementação em `add_confidence_rank` — a divergência é de LOCALIZAÇÃO/PERSISTÊNCIA (análise vs. produção), não de fórmula.

Segunda divergência: PRD §5.12 descreve `ensemble_std`/`n_models_agree` como métricas reais de discordância entre 12 modelos (Camada 3, bagging). Como só existe 1 modelo por lado/fold (Camada 3 ausente), o código grava `ensemble_std=None` e `n_models_agree=1` sempre — colunas presentes no schema, valores degenerados/placeholder (`alpha.py:415-416`).

### Observações do executor
A ausência de `confidence_rank` em produção não é um bug escondido — o próprio `faixa1_5_prerequisites.py` diz explicitamente que Bloco 4 "ADICIONA uma COLUNA nova a uma CÓPIA de `predictions.parquet` sem ajustar calibrador nenhum" (`n_lifetime += 1` documentado). Hoje não existe recalibração/monitoramento de deriva de calibração em produção — só diagnóstico manual sob demanda via `calibration_diagnostics.py`.

---

---

## Estágio 10 — VALIDAÇÃO (CPCV, leakage, DSR, baselines, backtest, decomposição)

Coberto por dois agentes de discovery em paralelo, por volume de arquivo — as duas partes formam um único estágio.

### Parte A — CPCV, purge, embargo, DSR

#### 12.1 Arquivos e status

| arquivo | linhas |
|---|---|
| `src/validation/cpcv.py` | 455 |
| `src/validation/leakage.py` | 899 |
| `src/validation/dsr.py` | 261 |
| `src/validation/_constants.py` | 47 |
| `src/validation/_paths.py` | 38 |
| `src/validation/__init__.py` | 63 |

Status: **presente**. Os três núcleos (CPCV, leakage runner, DSR/PSR) são implementação real, executada contra dado sintético e — na maioria dos casos — contra `labels/v1/labels.parquet` real (462.682 linhas). PBO e walk-forward, ambos ancorados em §11.6/§11.4.1, estão confirmados **ausentes**, exatamente como já documentado em `src/validation/__init__.py:7-9` — não é achado novo desta leitura, é a confirmação pedida pela task.

#### 12.2 Funções catalogadas

46 funções/classes catalogadas no total: 13 em `cpcv.py` (splitter combinatório, purge, embargo, 1-fatoração round-robin, IO de labels), 24 em `leakage.py` (14 funções `_test_NN_*` uma por linha da tabela §11.5, mais orquestração/relatório/scan estatístico), 8 em `dsr.py` (PSR/DSR/bootstrap de diferença de Sharpe), 1 em `_constants.py` (`load_constant`). Lista completa com assinatura, arquivo:linha, docstring literal e flags `publica`/`carrega_decisao` está no JSON irmão (`cd_07_validacao_a.json::funcoes`).

Destaques de `carrega_decisao: true` (funções cujo retorno alimenta diretamente um PASS/FAIL ou gate): `generate_splits` (levanta `CPCVError`), `assert_no_train_t1_leaks_into_test`/`assert_embargo_respected` (levantam `AssertionError`), as 14 `_test_NN_*`, `run_all_leakage_tests`, `compute_dsr`, `dsr_passes_conventional_threshold`. `scan_feature_target_correlation` é deliberadamente `carrega_decisao: false` — a própria docstring do módulo diz "não decide nada... quem chama decide o que fazer".

#### 12.3 Matemática — CPCV, purge, embargo, leakage, DSR

**CPCV — combinatória.** `n_groups=6` e `n_test_groups=2` (`constants.yaml::cpcv_n_groups`/`cpcv_n_test_groups`) produzem `n_splits = C(6,2) = 15` e `n_backtest_paths = C(5,1) = 5`, ambos calculados como `@property` via `math.comb` em `CPCVConfig` (`cpcv.py:107-120`) — **não** são constantes próprias de `constants.yaml`; o próprio arquivo de constantes comenta que declará-las separadas arriscaria inconsistência.

**Reconstrução dos backtest paths.** 1-fatoração de K₆ pelo "circle method" round-robin (`_round_robin_1_factorization`, `cpcv.py:172-195`): 5 rodadas de 3 pares disjuntos, cobrindo os 15 pares `C(6,2)` exatamente uma vez ao longo das rodadas. `_path_assignment` (`cpcv.py:198-206`) mapeia cada par de `test_groups` ao `path_id` (índice da rodada). Implementado **só** para `n_test_groups=2` — `generate_splits` levanta `CPCVError` para qualquer outro valor (`cpcv.py:251-255`).

**Embargo — 175 barras, nos dois lados.** `cpcv_embargo_bars=175` (`constants.yaml:707`), convertido para `embargo_ms = 175 * step_ms('15m') = 43,75h`. Aplicado simetricamente: `embargo_mask` acumula a janela à direita `(t0 > g_end) & (t0 <= g_end + embargo_ms)` **e** à esquerda `(t0 < g_start) & (t0 >= g_start - embargo_ms)` de cada grupo de teste (`cpcv.py:280-282`).

**Purge — por `t1` real, não margem fixa.** `purge_mask = (t0_ms <= g_end) & (t1_ms >= g_start)` (`cpcv.py:278-279`): qualquer linha cujo intervalo `[t0,t1]` REAL cruze a janela de tempo do grupo de teste é removida do treino candidato. Não usa `time_stop_bars` nem nenhuma margem fixa — decisão deliberada, autodocumentada no item 2 da docstring do módulo.

**Leakage — 14 testes, todos existem como função testável.** `_test_01_close_futuro` até `_test_14_paridade_lote_streaming` (`leakage.py:272-692`), orquestrados por `run_all_leakage_tests` na ordem 1..14. Estado atual: teste 1 = `PENDING_SPRINT_8`, teste 10 = `NOT_APPLICABLE_V1_1`, os outros 12 = `PASS`. Zero `FAIL` no estado atual do repo.

**Gate estatístico Bonferroni/Spearman.** `scan_feature_target_correlation` (`leakage.py:795-865`, NÃO um dos 14 testes numerados) calcula `spearmanr(feature, ret_net)` por feature. `bonferroni_threshold = (feature_leakage_bonferroni_factor / sqrt(n_total)) * sqrt(n_features)` com fator `2.0` (classe D, só informativo) → seta `elevated`. `hard_fail_threshold = feature_leakage_hard_fail_threshold = 0.30` (classe C, `sweep_required`) → seta `hard_fail`, o único campo que de fato bloqueia. Confirmado contra `SPRINT_LOG.md:761-774`: o threshold Bonferroni ingênuo marcaria 4 das 10 T1 como suspeitas (falso positivo por correlação estrutural via ATR); por isso o `hard_fail_threshold` foi calibrado em 2× o maior `|rho|` causal já medido (0,142 de `E27f_cost_atr_ratio`).

**DSR — Euler-Mascheroni.** `expected_max_sharpe_under_n_trials` (`dsr.py:55-75`) implementa literalmente Bailey & López de Prado (2014) eq. 5-6: `E[max SR] = sigma_sr * ((1-gamma)*Z⁻¹(1-1/N) + gamma*Z⁻¹(1-1/(N*e)))`, com `gamma = 0.5772156649015329` (`_EULER_MASCHERONI`, linha 41).

**DSR — proxy de sigma_SR.** `compute_dsr` (`dsr.py:131-179`) usa `sigma_sr = sharpe_ratio_standard_error(sr_per_trade, n_obs, skewness, excess_kurtosis)` (linha 162) — ou seja, o erro-padrão do PRÓPRIO Sharpe observado (Bailey & López de Prado 2012, eq. 2) como proxy para `sigma_sr`, em vez do desvio-padrão real entre os `n_trials` trials (que exigiria rastrear o Sharpe de cada trial individualmente — `N_lifetime` só audita contagem). Confirmado por leitura direta do código, batendo com a descrição do SPRINT_LOG.

#### 12.4 Parâmetros

13 parâmetros catalogados. Os 5 vindos de `constants.yaml` (`cpcv_n_groups=6`, `cpcv_n_test_groups=2`, `cpcv_embargo_bars=175`, `feature_leakage_bonferroni_factor=2.0`, `feature_leakage_hard_fail_threshold=0.30`) têm proveniência declarada (LITERATURE/DERIVED) e classe A-D atribuída, conforme Regra Zero. Os 8 literais de `dsr.py` (`_EULER_MASCHERONI`, `_MIN_TRIALS`, `_MIN_OBS_FOR_MOMENTS`, `_PSR_KURTOSIS_TERM_DIVISOR`, `_SKEWNESS_POWER`, `_NORMAL_KURTOSIS`, `_DSR_CONVENTIONAL_THRESHOLD=0.95`, `_MIN_OBS_CORRELATION_SCAN` em `leakage.py`) são literais de código marcados `# noqa: magic-number`, justificados no próprio arquivo como "constante matemática, não de domínio" — **nenhum** tem entrada em `constants.yaml`. Detalhe relevante: `_DSR_CONVENTIONAL_THRESHOLD=0.95` é o número que o Gate 6 do PRD usa como critério de aprovação ("DSR > 0,95"), e é o único limiar de gate lido nesta task sem entrada em `constants.yaml`.

#### 12.5 Fan-in / Fan-out

**Fan-in** (14 pontos de consumo em `src/`, fora de testes): `src/backtest/fill_reconciliation.py`, `src/models/dataset.py`, `src/models/baselines.py`, `src/models/alpha.py`, `src/models/pipeline.py`, `src/models/backtest_lite.py` (referência de docstring, sem import próprio), `src/analysis/faixa1_7_edge_or_beta.py`, `src/analysis/faixa2_vol_accelerator_test.py`, `src/analysis/faixa2_dsr_and_b2_check.py`, `src/analysis/faixa1_5_prerequisites.py`, `src/analysis/faixa2_caminho_b.py`, `src/analysis/faixa1_6_reconciliation.py`, `src/analysis/calibration_diagnostics.py`, `src/analysis/faixa2_e3_stability.py`. `cpcv.generate_splits`/`cpcv.load_labels_v1` são de longe os pontos mais consumidos — praticamente todo script de `src/analysis/faixa*` chama `cpcv.generate_splits(mf.data)` para reconstruir os 15 splits reais antes de qualquer medição.

**Fan-out**: `cpcv.py` depende de `src.data.resample.step_ms`, `_constants.load_constant`, `_paths.LABELS_OUTPUT_DIR`. `leakage.py` depende de `src.regime.classifier`/`src.regime.stress` (recheck do teste 5), `cpcv` (testes 6/7/12), `_constants`/`_paths`, e importa `src.data.resample` localmente dentro do teste 9. `dsr.py` é o único dos três sem nenhum fan-out para dentro de `src/` — só `numpy`/`scipy.stats.norm`/`math`/`dataclasses`.

#### 12.6 Import-linter e substituibilidade

Nenhum contrato de `pyproject.toml::[tool.importlinter]` nomeia `src.validation` explicitamente. O contrato "labels só é lido por models, validation, backtest" restringe outros pacotes (`exchange`, `data`, `features`, `regime`, `risk`, `execution`, `live`, `monitoring`) de importar `src.labels` — `validation` fica implicitamente fora dessa lista de restrição (permissão que existe mas não é exercida por nenhum dos três arquivos lidos: nenhum importa `src.labels` diretamente).

Substituibilidade: sem interface abstrata — instanciação/chamada direta de função, sem DI. Impedimentos relevantes para qualquer substituto: `CPCVConfig.__post_init__` valida bounds e levanta `CPCVError`; `generate_splits` só reconstrói paths para `n_test_groups=2`; `dsr.py` opera estritamente em escala per-trade (anualizar antes da fórmula é tratado como erro de unidade pelo próprio módulo); os testes 6/7/12 de leakage acoplam ao schema `t0`/`t1`/`sample_weight` de `labels/v1/labels.parquet`.

#### 12.7 Testes

3 arquivos, 873 linhas: `tests/unit/test_validation_cpcv.py` (386), `tests/unit/test_validation_leakage.py` (382), `tests/unit/test_validation_dsr.py` (105). Cobertura é ampla — praticamente toda função pública tem teste direto, incluindo dois testes `@pytest.mark.integration` que rodam CPCV/leakage contra `labels/v1/labels.parquet` real e um `@pytest.mark.integration @pytest.mark.slow` que roda o scan de correlação sobre as 10 features T1 reais.

**Sem teste**: `dsr_passes_conventional_threshold` (usada em produção só em `src/analysis/faixa2_dsr_and_b2_check.py:123`, mas sem teste unitário próprio), `_period_sharpe` (só indireta via `sharpe_difference_block_bootstrap`), `load_constant` de `_constants.py` (sem arquivo de teste dedicado, só coberta indiretamente), os blocos `__main__`/`_run_cli` de `cpcv.py`/`leakage.py` (marcados `pragma: no cover`), e os helpers `_grep_source`/`_select_rows`/`_load_known_gap_ids` de `leakage.py` (exercitados indiretamente via `_test_08`/`_test_13`, sem teste isolado).

**Testes que travam comportamento** (11 catalogados no JSON): destaque para `test_cpcv_sobre_dataset_real_15_splits_zero_vazamento` (tolerância zero sobre dado real de produção, 462.682 linhas), `test_1_fatoracao_k6_cobre_todos_os_15_pares_exatamente_uma_vez` (prova exaustiva da 1-fatoração), `test_run_all_leakage_tests_sentinelas_corretos_sobre_sintetico`/`test_run_all_leakage_tests_sobre_dataset_real` (travam os status exatos 1/10/11/6/7/12), e `test_sharpe_se_normal_reduz_a_formula_classica`/`test_psr_e_meio_quando_observado_igual_benchmark` (casos fechados analíticos do DSR/PSR, tolerância `1e-9`).

#### Observações do executor

- `dsr.py` não importa `_constants.py`/`load_constant` em lugar nenhum — todas as suas constantes numéricas são literais de código com `# noqa: magic-number`. Isso as isenta na prática de qualquer varredura automatizada de `constants.yaml` para proveniência classe A `ASSUMED`, mas `_DSR_CONVENTIONAL_THRESHOLD=0.95` é exatamente o número usado pelo Gate 6 do PRD ("DSR > 0,95") — ao contrário de praticamente todo outro limiar de gate no repo, este não tem entrada em `constants.yaml`. Não avaliei se isso é aceitável (fora do meu regime de leitura); só registro o fato.
- `leakage.py` exclui explicitamente `{'validation','execution','__pycache__'}` de `_AUDITED_PIPELINE_ROOTS` (linhas 104-110) para os greps estáticos dos testes 8 e 13. A exclusão de `execution/` é justificada no código como cautela temporária de um agente paralelo trabalhando em `src/execution/fill_simulator.py` na época em que este código foi escrito; o próprio teste 13 nota que "todo o caminho" precisa ser reavaliado quando `risk`/`execution` existirem de fato. Não li `src/execution/` nesta task (fora de escopo) para confirmar se a exclusão ainda é apropriada hoje.
- Os testes 2, 3 e 8 (`_audit_registry_causal_proofs`) são auditorias ESTÁTICAS — confirmam que a referência textual `testado em <arquivo>::<função>` no registry aponta para uma função que existe, mas não reexecutam o teste citado nem verificam que o corpo dessa função ainda prova o que o texto alega. Autodocumentado no módulo; registrado aqui como limite de evidência para quem for usar esses `PASS` como prova forte no PRD V4.
- `audit/n_lifetime.yaml` (fora do escopo de leitura direta desta task, mas referenciado pela docstring de `dsr.py::compute_dsr`) tem `counter=45` no momento desta leitura — usado como contexto para a divergência de `N_effective` (960 estático do PRD §11.6 vs 45 do ledger real) reportada em `divergencias_prd`.


---

### Parte B — Baselines, backtest, decomposição

**Status: presente.** Escopo lido integralmente: `src/models/baselines.py` (846 linhas), `src/models/backtest_lite.py` (202 linhas), `src/models/decomposition.py` (259 linhas), `src/models/hhi.py` (350 linhas). 26 funções catalogadas (19 públicas, 7 privadas), 4 arquivos de teste (`tests/unit/test_models_{baselines,backtest_lite,decomposition,hhi}.py`, 1186 linhas somadas), 4 divergências código-vs-PRD localizadas com precisão de linha.

#### 12.1 Inventário de arquivos e funções

| arquivo | linhas | funções públicas | funções privadas |
|---|---|---|---|
| `src/models/baselines.py` | 846 | 12 | 5 |
| `src/models/backtest_lite.py` | 202 | 5 | 0 |
| `src/models/decomposition.py` | 259 | 1 | 1 |
| `src/models/hhi.py` | 350 | 2 | 0 |

**`baselines.py`** implementa 5 baselines nulos (B1 `run_b1_random_entry`, B2 `run_b2_buy_and_hold`, B3 `run_b3_regime_only`, B4 `run_b4_feature_shuffle`, B5 `run_b5_short_permanent`) mais 4 variantes de refinamento estatístico do B1 pós-Sprint-8, todas reusando a mesma mecânica de sorteio/Sharpe de `run_b1_random_entry` sem lógica nova: `run_b1_per_path` (percentil por caminho de CPCV, não a média dos 5), `run_b1_paired_variance_null` (nulo com a mesma estrutura de promediação do Alpha), `run_b1_carry_stripped`/`strip_carry` (T2 — percentil sem o termo de carry), `run_b1_side_shuffle` (T3/B1' — sorteia só o lado, mantendo barra/timing real fixa).

**`backtest_lite.py`** é declarado explicitamente na própria docstring do módulo (linhas 1-4) como "harness de avaliação mínimo desta rodada — NÃO é o motor de backtest do projeto", ancorado em §11.1/§14.1 do CLAUDE.md ("não escreva motor próprio antes de avaliar o de prateleira"). Não resimula barreiras, custos, quantização ou funding — só agrega `ret_net` já calculado por `src.labels.triple_barrier`.

**`decomposition.py`** implementa a decomposição de PnL carry vs. direcional vs. execução (§16.6), com reconciliação exata verificada (`pnl_direcional + pnl_carry + pnl_execucao == ret_net`, tolerância 1e-6).

**`hhi.py`** implementa o diagnóstico de concentração (§5.8) em duas camadas: `compute_concentration` (HHI nominal, `Σ share²`) e `compute_effective_concentration` (HHI efetivo, correção por correlação entre features — achado D1 do Sprint 4, não presente no PRD original).

#### 12.2 Matemática exata

**Baselines existentes (nomes reais no código).** 5 no total: B1 `run_b1_random_entry` (entrada aleatória, pool não-NOFILL dos dois lados, 1000 sementes por default), B2 `run_b2_buy_and_hold` (buy-and-hold diário sem alavancagem), B3 `run_b3_regime_only` (long em R3/R4 com `A13_dist_ema48_atr > 0`, sem Alpha), B4 `run_b4_feature_shuffle` (AUC real vs. AUC com as 10 colunas T1 embaralhadas independentemente, reusando modelos já treinados da Camada 1 — nenhum retreino), B5 `run_b5_short_permanent` (short permanente, isola carry puro).

**`sharpe_naive` — duas convenções de anualização coexistem, ambas documentadas no código:**
1. `backtest_lite.sharpe_naive(trade_returns, span_seconds)` (linha 45) = `mean(ret)/std(ret,ddof=1) * sqrt(trades_per_year)`, com `trades_per_year = n / (span_seconds/(365.25*86400))` — anualização pela frequência REAL de trade observada na amostra, nunca um fator fixo. Usada por Alpha, B1 (e todas as 4 variantes de refinamento), B3, B5, e por `decomposition.decompose` (`total_sharpe`/`directional_sharpe`).
2. `run_b2_buy_and_hold` (baselines.py:686) calcula Sharpe direto sobre retornos log DIÁRIOS do close, com `sqrt(DAYS_PER_YEAR)` = `sqrt(365.25)` fixo — não usa `trades_per_year` porque a série de entrada já é diária. `DAYS_PER_YEAR = 365.25` é pública em `backtest_lite.py` justamente para as duas convenções citarem a mesma constante de calendário.

**Decomposição de PnL (`decomposition.py:97-258`):**
```
pnl_direcional_series = ret_gross
pnl_carry_series      = -funding_bps / 1e4
pnl_execucao_series   = -(cost_entry_bps + cost_exit_bps) / 1e4
```
`total_sharpe = sharpe_naive(ret_net, span)`; `directional_sharpe = sharpe_naive(pnl_direcional_series, span)` (mesmo `span`, calculado uma vez sobre `t0`). `carry_share = safe_ratio(pnl_carry, pnl_total, require_den_positive=True, ...)` — o guard de `src/core/metric.py:244` (`safe_ratio`) faz `carry_share.valid=False`/`value=nan` sempre que `pnl_total <= 0` ou não-finito, **nunca calcula a razão nesse caso**. Isto é o fix já documentado no SPRINT_LOG ("carry_share inválido", achado nº1 de auditoria anterior — com dado real `pnl_total` é negativo, e a fórmula ingênua do PRD passaria o gate por acidente). `gate3_directional_positive = directional_sharpe.value > 0` (finito); `gate3_carry_share_ok = carry_share.valid AND abs(carry_share.value) < alpha_gate3_carry_share_max(=0.30)` — um `Metric` inválido **reprova** o gate, nunca passa por ausência de evidência (decisão B3 documentada no próprio código, linhas 224-233).

**HHI nominal vs. efetivo (`hhi.py`):**
- `compute_concentration` (linha 65): `shares[col] = max(gain_by_column.get(col,0),0)/total_gain`; `hhi = Σ shares²`; se `total_gain <= 0`, fallback para `shares=0.0` em todas as colunas e `hhi=0.0` (valor definido, `valid=True`, não NaN).
- `compute_effective_concentration` (linha 185): pesos `w_i` = gain-share renormalizado no subconjunto `all_columns` (soma 1); se `total_gain <= 0` no subconjunto, fallback para peso **uniforme** `w_i = 1/p` (linha 295-301, mesma disciplina espelhada de `compute_concentration`). `M = D @ C @ D` (`D = diag(√w)`, `C` = matriz de correlação sanitizada: NaN/inf→0.0 fora da diagonal, diagonal forçada a 1.0, simetrizada). `hhi_effective = Σλ²`; `n_eff_factors = (Σλ)²/Σλ² = 1/Σλ²`, com `λ` = autovalores de `M` clipados em `[0,∞)`. Prova algébrica na docstring (verificada em teste, `abs=1e-9`): `hhi_effective = Σw_i² + Σ_{i≠j} w_i w_j ρ_ij²` = HHI nominal + termo de correlação ≥ 0 → `hhi_effective >= hhi_nominal` sempre, com igualdade exata quando a matriz de correlação é identidade.

#### 12.3 Parâmetros e proveniência

| parâmetro | categoria | valor | proveniência |
|---|---|---|---|
| `alpha_b1_n_seeds` | constants.yaml (`config/constants.yaml:1026`) | 1000 | LITERATURE — "PRD §16.1 — B1 roda 1.000 sementes" (classe C) |
| `alpha_random_seed` | constants.yaml (`:1001`) | 42 | ASSUMED — "convenção arbitrária, sem significado estatístico" (classe D) |
| `alpha_gate3_carry_share_max` | constants.yaml (`:1035`) | 0.30 | LITERATURE — "PRD §16.6" (classe C) |
| `_BPS_PER_UNIT` | literal código, duplicado em `baselines.py:89` e `decomposition.py:54` | 10000 | "definição matemática, não constante de domínio" |
| `DAYS_PER_YEAR` | literal código, `backtest_lite.py:40`, pública | 365.25 | "constante matemática de calendário" |
| `_SHARE_PCT_THRESHOLD` | literal código, `hhi.py:32` | 0.01 | "literal do próprio §5.8 do PRD" |
| `1e-6` | literal código, `decomposition.py:149` | tolerância de reconciliação | "mesma de §3.8" |
| `sample_size_b1` | **derivado em runtime** (não é constante) — `src/models/pipeline.py:360` | `max(1, round(n_filled_c1/n_paths))` | ver divergência 12.6.4 |

#### 12.4 Fan-in / fan-out

**Fan-in.** `src/models/pipeline.py` (linha 28) é o único orquestrador de produção que junta os 4 módulos — chama `backtest_lite.backtest_by_path`/`permanence_count`/`realize_trades`, `baselines.run_b1_random_entry`/`run_b2_buy_and_hold`/`run_b3_regime_only`/`run_b4_feature_shuffle`/`run_b5_short_permanent`, e `decomposition.decompose` (pooled e por caminho). `src/models/alpha.py` (linha 45) importa `compute_concentration`/`compute_effective_concentration` de `hhi.py`, chamadas por fold×lado dentro de `fit_side_model`. `src/backtest/fill_reconciliation.py` importa `backtest_lite`/`decomposition`. Uma cadeia de 8 scripts em `src/analysis/faixa1_*.py`/`faixa2_*.py` (fora do escopo de leitura direta) reusa fortemente as convenções destes módulos, seja por import direto (`decompose`, `compute_effective_concentration`, `run_b3_regime_only`, `run_b5_short_permanent`, `DAYS_PER_YEAR`) seja por replicar a mecânica de RNG de `run_b1_random_entry` em código próprio.

**Fan-out.** `baselines.py` é o mais acoplado dos 4: importa `backtest_lite`, `dataset`, `alpha` (FoldResult, build_design_matrix — dependência estrutural de B4), `_constants`, `_paths`, além de `src.data.lake`, `src.features.build.T1_FEATURE_IDS`, `src.validation.cpcv.CPCVSplit` e `sklearn.metrics.roc_auc_score`. `hhi.py` é o mais isolado: só `numpy` e `src.core.metric` — nenhuma dependência de outro módulo de `src/models/`.

#### 12.5 Contratos de import-linter e hierarquia de camadas

Três contratos formalizados em `pyproject.toml:120-151` tocam este pacote: "models não importa execution", "labels só é lido por models/validation/backtest", "models não importa analysis". Os 4 arquivos do escopo respeitam todos os três por observação direta (nenhum importa `execution`/`analysis`; consomem colunas originadas em `src.labels` só via DataFrame já materializado, nunca via import direto de `src.labels`). O comentário do próprio `pyproject.toml` (linhas 109-115) registra que a hierarquia completa do CLAUDE.md/PRD ("exchange → data → ... → validation") é "ordem de pipeline", não necessariamente contrato de import formalizado — só 4 regras têm contrato hoje, e a 5ª regra do CLAUDE.md ("alpha não pode importar meta") está marcada como `TODO(Sprint 8)` não formalizada (linhas 159-161).

#### 12.6 Divergências código vs. PRD

**1. Âncora do módulo `baselines.py` agrega §16.1 e §16.6 sob uma citação só.** O docstring de topo (linha 1) anuncia "Cinco baselines nulos — §16.1, RF-024" para B1-B5, mas o PRD define literalmente só 4 baselines "obrigatórios" em §16.1 (linha 2581: "Quatro baselines obrigatórios"); B5 (short permanente) só é introduzido em §16.6 (linha 2710), motivado pela decomposição de PnL. O comportamento em si não contradiz o PRD (B5 existe e está corretamente ancorado a §16.6 na docstring de `run_b5_short_permanent`, linha 743) — é só a citação-guarda-chuva do módulo que funde as duas seções.

**2. Gate 3.4 (HHI) decide sobre o HHI efetivo, não o nominal do §5.8.** O PRD (§5.8, linha 1253) define literalmente só o HHI nominal (`Σ share²`) como critério: "HHI de importância < 0,25". Não há menção a nenhuma correção por correlação. `src/models/hhi.py` implementa uma segunda métrica, `compute_effective_concentration` (achado D1 do Sprint 4 — features do top-4 por gain com ρ=-0,913 e ρ=0,947). O consumidor de produção, `src/models/pipeline.py:416-425` (fora do escopo de leitura direta, mas único call-site real), decide explicitamente usar o efetivo como gate real (`"gate3_4_hhi_lt_025": mean_hhi_effective < 0.25`), mantendo o nominal só como `"gate3_4_hhi_nominal_lt_025_reference"` — comentado no código como "NUNCA usado pelo gate" (decisão D3). Extensão pós-PRD, não contradição direta, mas o texto do §5.8 sozinho não permite prever qual dos dois números decide o gate.

**3. `carry_share` ganhou guard estrutural que o texto do §16.6 não previa — e existe uma segunda fórmula informal em uso.** PRD (linha 2704) define `carry_share = PnL_carry / PnL_total`, divisão simples. `decomposition.py:182-189` calcula via `safe_ratio(..., require_den_positive=True, ...)` — a razão nunca é calculada quando `pnl_total <= 0` (fix documentado no SPRINT_LOG, achado nº1 de auditoria anterior). O próprio código documenta (linhas 178-181) que reescrever a fórmula em si foi "deliberadamente adiada para outra rodada" — e o SPRINT_LOG (linhas 642-644) confirma que uma fórmula ALTERNATIVA, `pnl_carry/(pnl_direcional+pnl_carry)`, já circula informalmente em `src/analysis/attribution.py`/relatórios ad hoc precisamente para contornar a invalidação do módulo canônico.

**4. `sample_size_b1` real de produção é uma média por caminho, não a contagem real que a docstring de `run_b1_random_entry` exige.** Tanto o PRD (§16.1, linha 2585) quanto o docstring da própria função (linhas 146-149) afirmam que o tamanho de amostra do nulo B1 deve refletir a contagem REAL de trades preenchidos do Alpha. O único call-site de produção (`pipeline.py:360`, fora do escopo direto) passa `max(1, round(n_filled_c1 / n_paths))` — uma média entre os 5 caminhos de CPCV, não uma contagem real única. O próprio módulo já reconhece essa tensão na docstring de topo (linhas 6-26, "Refinamento estatístico do B1 pós Sprint 8") e endereça com `run_b1_per_path`/`run_b1_paired_variance_null` — não é uma divergência escondida, mas o texto de `run_b1_random_entry` isoladamente não qualifica que o call-site real usa uma média.

#### 12.7 Cobertura de testes

4 arquivos de teste, 1186 linhas somadas, todos sintéticos e rápidos (nenhum marker `golden`/`slow`/`integration`, nenhum toca `labels/v1/labels.parquet` real — confirmado nas próprias docstrings dos arquivos de teste).

**Testes que fixam comportamento com tolerância zero ou valor literal esperado:**
- `test_strip_carry_reconciliacao_bate_com_ret_net_original` — tolerância zero, `max_abs_diff < 1e-6`.
- `test_decompose_reconcilia_exatamente_com_ret_net` — tolerância zero, `< 1e-9`.
- `test_hhi_uniforme_com_10_features` — valor literal, HHI uniforme = 0,10 ("texto literal do §5.8").
- `test_hhi_gate_3_4_thresholds` — valor literal, os 3 thresholds do §5.8 (HHI<0,25, max_share<0,30, n≥6 features >1%).
- `test_effective_concentration_dois_correlacionados_um_independente` — valor literal exato, `N_eff = 9/5 = 1,8` e `hhi_effective = 5/9`, "verificado exatamente (não só por range) para travar a fórmula".
- `test_effective_concentration_sem_correlacao_reduz_ao_hhi_nominal` — tolerância zero, prova algébrica da docstring verificada numericamente (`abs=1e-9`).
- `test_decompose_carry_share_invalido_quando_pnl_total_negativo` — valor literal, fixa o comportamento do guard `safe_ratio` (fix do achado nº1 da auditoria).

**Funções sem teste direto (grep confirmado, zero matches em `tests/`):**
- `baselines.run_b2_buy_and_hold`, `run_b3_regime_only`, `run_b5_short_permanent`, `run_b4_feature_shuffle` — nenhum dos 4 baselines "clássicos" (B2-B5) tem teste unitário; `test_models_baselines.py` cobre exclusivamente o refinamento do B1 (confirmado no próprio docstring do arquivo de teste: "foco no refinamento estatístico do B1").
- `baselines._static_rule_result`, `baselines._pool_auc` — helpers privados de B3/B5 e B4, também sem teste.
- `backtest_lite.realize_trades`, `backtest_lite.backtest_by_path` — sem teste direto; `test_models_backtest_lite.py` testa `permanence_count` com `PathBacktestResult` construído manualmente, nunca passando pelas duas funções que de fato materializam trades/backtest por caminho.

#### Observações do executor

- `compute_effective_concentration` (HHI efetivo) é funcionalidade inteiramente nova em relação ao PRD — §5.8 não a menciona em nenhuma forma. Se a intenção do PRD V4 é oficializar o efetivo como critério de gate, §5.8 precisa ser reescrito para descrevê-lo, não só o nominal.
- `hhi.py` é o mais isolado dos 4 arquivos do escopo (só `numpy` + `src.core.metric`); `baselines.py` é o mais acoplado (6 dependências internas de `src/models/` + 3 de outros pacotes).
- A cadeia de scripts `src/analysis/faixa1_*.py`/`faixa2_*.py` (fora do escopo de leitura direta) é um consumidor tão intenso das convenções destes 4 módulos quanto `pipeline.py`, mas por serem scripts de investigação ad hoc, não passam pela mesma disciplina formal de import-linter/contrato de pipeline declarado.
- `pyproject.toml:159-161` registra como TODO(Sprint 8) não formalizado o contrato "alpha não pode importar meta" citado no CLAUDE.md como banned pattern de hierarquia de camadas — não afeta os 4 arquivos deste estágio diretamente, mas é um gap de enforcement na mesma família dos 3 contratos formalizados listados em 12.5; registrado para quem consolidar o capítulo de layer hierarchy completo do relatório final.


---

## Estágio 11 — EXECUÇÃO

Escopo lido integralmente: `src/execution/fill_simulator.py` (1061 linhas), `src/labels/fill_model.py` (146 linhas), `src/risk/sizing.py` (215 linhas), `src/backtest/fill_reconciliation.py` (862 linhas), `src/backtest/_paths.py` (46 linhas). Status: **presente**.

### 12.1 Arquivos e papel estrutural

Nota estrutural confirmada por leitura (não presumida): existem DOIS módulos de "fill" com papéis distintos.

- **`src/labels/fill_model.py`** implementa o pseudocódigo `fill_model(...)` do PRD §3.3/§3.4 — modelo SIMPLIFICADO/OTIMISTA ("toque de `[low,high]` em `mark_1m` = preenchimento", sem fila, sem profundidade). É chamado SINCRONAMENTE dentro do laço quente de `src.labels.triple_barrier.build_labels` (`src/labels/triple_barrier.py:624`) — único caller de produção, decide o `barrier_hit`/label de cada barra. `src/labels/barrier_sweep.py` documenta (não chama) essa relação: o fill não depende de `tp_atr_mult`/`sl_atr_mult`, então a varredura de grade reusa o fill já persistido em `labels/v1/labels.parquet` em vez de recalcular.
- **`src/execution/fill_simulator.py`** implementa o simulador de fila do PRD §9.5 — modelo REALISTA/PESSIMISTA (fila FIFO reconstruída de `bookTicker` tick-level + `aggTrades`, cancelamento NÃO modelado). NÃO é chamado pelo Label Engine; roda como artefato de análise OFFLINE separado, com CLI própria, escrevendo em `execution/fill_simulator/{version}/orders.parquet`.
- Os dois são consumidos juntos por **`src/backtest/fill_reconciliation.py`**, que compara o gate OTIMISTA (`barrier_hit != NOFILL`, Label Engine) contra o gate REALISTA (`filled == True`, simulador de fila) sobre a MESMA janela e os MESMOS sinais — Módulo A (reconciliação) e Módulo B (seletividade do fill real sobre TODOS os candidatos do simulador, não só os sinais do Alpha).
- **`src/risk/sizing.py`** é independente dos dois — traduz `risk_usd`/distância de stop em `qty` quantizada, sem nenhuma dependência de fill.
- **`src/backtest/_paths.py`** só resolve caminhos (5 constantes: `REPO_ROOT`, `LABELS_OUTPUT_DIR`, `PREDICTIONS_OUTPUT_DIR`, `FILL_SIMULATOR_OUTPUT_DIR`, `EXPERIMENTS_DIR`); as datas de janela real (`BOOK_TICKER_WINDOW_START/_END`, `RPI_BREAK_DATE`) são deliberadamente NÃO duplicadas ali — importadas direto de `src.execution.fill_simulator`.

### 12.2 Funções catalogadas

39 funções catalogadas nos 5 arquivos (18 em `fill_simulator.py`, 2 em `fill_model.py`, 3 em `sizing.py`, 16 em `fill_reconciliation.py`, 0 em `_paths.py` — só constantes de path). Lista completa com assinatura, docstring literal, linha e se carrega decisão de desenho está no JSON companheiro (`cd_09_execucao.json::funcoes`).

Funções que carregam decisão de desenho (não mecânicas): `_simulate_one_order`, `_compute_markouts`, `_simulate_one_order_price_improved`, `simulate_window` (fill_simulator.py); `simulate_fill_arrays` (fill_model.py); `compute_sizing` (sizing.py); `_assert_window_within_measured_coverage`, `reconstruct_fold_to_path_id`, `build_reconciliation_base`, `_evaluate_gate`, `_by_path_breakdown`, `compute_fill_selectivity` (fill_reconciliation.py); e `calibrate_against_real_fills`, cuja "decisão" é levantar `NotImplementedError` sempre.

### 12.3 Matemática — respostas específicas

**Fonte de dado do simulador de fila.** `bookTicker` — colunas `transaction_time`, `best_bid_price`, `best_bid_qty`, `best_ask_price`, `best_ask_qty` (`_BOOK_TICKER_COLUMNS`, fill_simulator.py:166-172), lido de `data/raw/book_ticker/{symbol}/yyyy-mm-dd.parquet`. `aggTrades` — colunas `transact_time`, `price`, `quantity`, `is_buyer_maker` (`_trade_arrays`, linhas 522-528), obtido via `src.data.lake.query_agg_trades` (confirmado o schema real em `src/data/lake.py:180-187`, `ts_col="transact_time"`).

**Posição na fila (FIFO).** `queue_ahead_initial` = volume já existente no nível exato (`best_bid_qty`/`best_ask_qty`) no instante do post — assume-se o PIOR caso, fim da fila, FIFO estrito (fill_simulator.py:263-268). Decrementada só por volume TAKER casado em `aggTrades` (filtro de direção via `is_buyer_maker` + tolerância de preço `tick_size/2`), via soma cumulativa; preenche no primeiro índice onde `cum_qty >= queue_ahead` (linhas 280-306). Cancelamento NÃO é modelado — decisão estrutural documentada (linhas 37-51), não uma taxa calibrada — por isso `p_fill` medido é um LIMITE INFERIOR pessimista.

**Seleção adversa (markout).** `_compute_markouts` (linhas 324-348): para cada horizonte {1m, 5m, 30m}, `markout_bps = side * (mid(t_entry+h) - fill_price) / fill_price * 10000`, `mid = (best_bid+best_ask)/2` asof em `t_entry+h`. Retorna `None` (não stale) se o horizonte ultrapassa o último bookTicker carregado. Reportado como 3 dicts por horizonte, nunca um escalar único — e nunca escrito de volta em `constants.yaml:adverse_selection_bps.value`.

**Sizing — fórmula de quantização.** `qty_raw = notional_req / mark_price_d`; `qty = filters.floor_to_step(qty_raw)` (sizing.py:148-149), que delega a `Filters.floor_to_step` (`src/exchange/filters.py:81-88`): `steps = (quantity/step_size).to_integral_value(rounding=ROUND_FLOOR)`; `qty = steps*step_size`. **Só arredonda para baixo** — pode dar `qty == Decimal("0")`. `sizing.py` **não trava/clampa num mínimo**: não chama `meets_min_notional` nem eleva `qty` até `min_qty` — essa checagem é um controle SEPARADO e downstream, `control_06_qty_minima` em `src/risk/limits.py:163-165`, que só lê `SizingResult.qty`/`filters.min_qty` e retorna PASS/FAIL.

**Custo round-trip (maker+maker ou fallback taker).** Nenhum dos 5 arquivos do escopo calcula fee. A lógica real está em `src/labels/triple_barrier.py:688-689` (fora do escopo de leitura direta, citado porque a pergunta exige): `cost_entry_frac = cfg.maker_fee` (entrada sempre maker/GTX); `cost_exit_frac = cfg.maker_fee if barrier_hit == "TP" else cfg.taker_fee` (SL via `STOP_MARKET` e TIME via `MARKET reduce_only` saem a taker). Round-trip é maker+maker **só** quando a saída é TP; SL/TIME têm fallback taker explícito — consistente com o pseudocódigo do PRD §3.4 (`c_exit = MAKER if barrier=="TP" else TAKER`).

### 12.4 Parâmetros

| nome | categoria | valor | proveniência |
|---|---|---|---|
| `tick_size` | constants_yaml | 0.10 | MEASURED, class C |
| `fill_timeout_bars` | constants_yaml | 1 | ASSUMED, class B, review_by sprint_6 |
| `adverse_selection_bps` | constants_yaml | 1.5 | ASSUMED, class A, sweep [0.0, 5.0] (só logado como placeholder de comparação em `record_experiment`, nunca usado para calcular) |
| `risk_per_trade` | constants_yaml | 0.005 | DERIVED (circular até sweep de R1/R2), class A |
| `sl_atr_mult` | constants_yaml | 1.5 | ASSUMED, class A, sweep [0.75, 2.25] |
| `RPI_BREAK_DATE` | literal_codigo | 2025-11-20 | fato de venue verificado 2026-08-08; não vive em constants.yaml |
| `BOOK_TICKER_WINDOW_START/_END` | literal_codigo | 2023-05-16 / 2024-03-30 | MEASURED, cobertura real de `data/raw/book_ticker/BTCUSDT/` |
| `_BPS_PER_UNIT` | literal_codigo | 10 000 | fator de conversão matemático, não constante de domínio |
| `_MARKOUT_HORIZONS_MS` | literal_codigo | {1m,5m,30m} | citado literalmente do PRD §9.5 |
| `step_size`/`min_qty`/`min_notional` | derivado (via `Filters`) | versionado por data | resolvido por `load_filters_asof(t0)` |

`quantization_tolerance` (0.25) e `maker_fee`/`taker_fee` NÃO são carregados por nenhum dos 5 arquivos — vivem em `src/risk/limits.py` e `src/labels/triple_barrier.py` respectivamente (ver observações).

### 12.5 Fan-in / fan-out / import-linter

**Fan-in real de produção:** `src/labels/triple_barrier.py:624` chama `fill_model.simulate_fill_arrays` (único caller de produção). `src/risk/limits.py:58` importa `SizingResult` e consome nos controles 6-15. `fill_simulator.py` e `fill_reconciliation.py` não têm caller de produção fora de si mesmos — só CLI própria e testes; `fill_reconciliation.py` em particular não é importado por nenhum outro módulo `src/`.

**Fan-out:** `fill_simulator.py` reusa `src.data.lake.query_agg_trades` e `src.data.resample.step_ms` (não reimplementa aggTrades). `sizing.py` reusa `src.exchange.filters.Filters`/`load_filters_asof` (decisão explícita no docstring de não duplicar a mecânica de `floor_to_step`). `fill_reconciliation.py` importa `src.core.metric`, `src.core.provenance`, `src.execution.fill_simulator`, `src.models.{backtest_lite,decomposition,pipeline}`, `src.validation.cpcv` — é o arquivo com mais fan-out do estágio. `fill_model.py` é folha — zero imports de `src/`.

**Import-linter (pyproject.toml:120-161):** contrato "labels só é lido por models, validation, backtest" proíbe `src.execution`/`src.risk` (entre outros) de importar `src.labels` — confirmado que nem `fill_simulator.py` nem `sizing.py` fazem isso. Contrato "risk não importa execution nem models" — confirmado, `sizing.py` não importa nenhum dos dois. `src.backtest` não tem contrato `forbidden` próprio — livre para importar `execution`/`models`/`validation`.

### 12.6 Substituibilidade

Sem ABC/Protocol formal em nenhum dos 5 arquivos — funções puras + dataclasses `frozen(slots=True)`. Ponto de injeção real: `simulate_window(..., _order_simulator: _OrderSimulator = _simulate_one_order)` (fill_simulator.py:586,596), usado por `simulate_window_price_improved` para trocar o núcleo sem duplicar IO/orquestração. `compute_sizing` recebe `filters: Filters` já resolvido (injeção manual pelo chamador); `compute_sizing_asof` é quem instancia via `load_filters_asof(t0)` diretamente — sem porta/abstração, import direto de `src.exchange.filters`. `fill_reconciliation.py` importa `src.models.pipeline.MODEL_ID_CAMADA1`, `src.models.backtest_lite`, `src.models.decomposition`, `src.validation.cpcv` diretamente — nenhum é injetado via parâmetro (só `model_id` é overridable).

### 12.7 Testes e divergências PRD

**Testes:** 4 arquivos, ~1455 linhas (`test_fill_simulator.py` 635, `test_labels_fill_model.py` 175, `test_risk_sizing.py` 295, `test_fill_reconciliation.py` 350). Destaques que fixam comportamento: `test_stop_2pct_floor_rejeita_em_vez_de_arredondar_para_cima` (fixa floor-only, nunca round-up); `test_simulate_window_recusa_janela_pos_quebra_rpi` e `test_calibrate_against_real_fills_levanta_not_implemented` (tolerância zero); `test_wrapper_polars_concorda_com_versao_numpy` (paridade exata entre os dois núcleos de `fill_model.py`); `test_reconstruct_fold_to_path_id_mapeia_15_splits_para_5_caminhos` (valor literal esperado). Sem teste direto encontrado para `compute_sizing_asof`, `run_fill_reconciliation`, `run_fill_selectivity`, `build_report`, `write_report_atomic`, `_run_cli` de `fill_reconciliation.py`.

**4 divergências PRD-vs-código catalogadas** (detalhe completo com âncora dupla no JSON):

1. **PRD §8.3 "Controle 9 explicado" (linhas 1600-1607) vs `sizing.py:148-149`.** A tabela ilustrativa do PRD mostra, para stop=2,00%, "1 unidade" alocada com erro +31,9% (✗). O código (`floor_to_step`, ROUND_FLOOR) nunca arredonda para cima — produz `qty=0`, não 1 unidade. Já documentado e testado pelo próprio autor em `tests/unit/test_risk_sizing.py:1-24,150-165`; o código segue a fórmula §8.2 (`floor_to_step`), não a leitura round-nearest implícita na tabela §8.3.
2. **PRD §3.1/§3.3 (linhas 793, 815-829) vs `fill_simulator.py:626`.** O texto do Label Engine ainda descreve `t0` como fechamento de barra de 30m; o código opera exclusivamente em grade de 15m (`step_ms("15m")`), consistente com CLAUDE.md/estado atual. O PRD já corrigiu isso parcialmente noutro ponto (linha 1733, nota de auditoria 2026-08-09) mas não em §3.1/§3.3.
3. **PRD §9.5 `fill_model.logic` (linha 1809) vs `fill_simulator.py:37-51`.** PRD lista "decrementa por cancelamentos estimados (taxa calibrada)"; o código explicitamente NÃO modela cancelamento — decisão estrutural autodocumentada, não taxa inventada.
4. **PRD §9.5 `fill_model.outputs` (linha 1812) vs `fill_simulator.py:735-736,804-816`.** PRD especifica `adverse_selection_bps` escalar único; o código reporta 3 horizontes separados (1m/5m/30m) e nunca escreve de volta em `constants.yaml`.

### Observações do executor

- A relação fill_model.py/fill_simulator.py (item 12.1) é exatamente o tipo de "onde a escolha de desenho está codificada" pedido pela task — os dois formam, por design documentado no próprio código, um INTERVALO (limite superior otimista vs limite inferior pessimista de `p_fill` real), não uma duplicação acidental.
- `sizing.py` não trava/clampa a quantidade num mínimo — só `floor`. A garantia "nunca abrir posição abaixo do lote mínimo" é responsabilidade de `src.risk.limits.control_06_qty_minima`, fora do escopo de leitura direta desta task mas citado no fan-in por ser o único consumidor real de `SizingResult` no repo.
- A pergunta sobre custo round-trip exigiu ler além do escopo formal (`src/labels/triple_barrier.py:688-689`) porque nenhum dos 5 arquivos designados calcula fee — sinalizado explicitamente para não confundir com um dado "descoberto dentro do escopo".
- `calibrate_against_real_fills` (fill_simulator.py:839-854) sempre levanta `NotImplementedError` — o bloco `calibration` do §9.5 não está implementado neste estado do repo.
- `src/backtest/_paths.py` não define nenhuma função — só 5 constantes de path — e não tem teste dedicado encontrado.
- `tests/unit/test_risk_sizing.py` já documenta em sua própria docstring (linhas 1-24) a divergência #1 acima — não é achado novo desta rodada, é achado já registrado em código/teste, aqui apenas catalogado com âncora exata.


---

## Estágio 12 — META-MODEL

### 12.1 a 12.7 — ausente, confirmado por leitura direta

**Status: AUSENTE.** Grep case-insensitive em `src/`, `tests/`, `research/` por `meta_model` / `Meta Model` / `MetaModel` / `is_oof` não encontrou nenhuma classe `MetaModel`, nenhum módulo `src/models/meta.py`, nenhum produtor de `predictions/meta/`. As ocorrências de `is_oof` fora de `src/models/alpha.py` são todas em módulos que **consomem/testam** a coluna `is_oof` do ALPHA (`src/analysis/*`, `src/validation/leakage.py`, `src/backtest/fill_reconciliation.py`, `src/models/baselines.py`) — nenhuma é implementação de Meta.

`arquivos: []`, `funcoes: []`, `parametros: []`, `fan_in: []`, `fan_out: []` — nada a catalogar.

**Onde a ausência está declarada:**
- **CLAUDE.md** ("Estado atual"): "Meta Model — fora da V1 (§6.8 define o critério de entrada)".
- **PRD §6.1** (linha 1378-1380): "O Meta entra na V1.1, não na V1. A justificativa é aritmética." §6.3 detalha a conta de amostra efetiva insuficiente (~1.590 observações efetivas, teto de 3-8 features).
- **§6.8** (linha 1459-1471): lista as 5 condições de entrada (obs_efetivas ≥ 3.000; modelo de fila J01-J05 calibrado e validado; ganho de precisão > 5pp estável em ≥4 folds; DSR com Meta > DSR sem Meta; Brier < 0,22) — nenhuma tem infraestrutura de medição em código no escopo lido.
- **Código**, `src/validation/leakage.py:520-532` — teste de vazamento #10 (`encadeamento de modelo`, §11.5 #10) retorna status `NOT_APPLICABLE_V1_1` com nota literal: *"O Meta sai do MVP (§6.1) — vai para a V1.1. Não existe `df_meta` nem `is_oof` em nenhum artefato real hoje... Documentado como N/A, não simulado com um dataframe fictício — simular `is_oof=True` para um Meta que não existe produziria um PASS que não prova nada."*

As três fontes (CLAUDE.md, PRD, código) concordam — **sem divergência a reportar neste estágio**.

### Observações do executor
Import-linter não formaliza nenhum contrato envolvendo "meta" hoje (só o TODO comentado citado no Estágio 8) — irrelevante enquanto o módulo não existe, mas relevante para o PRD V4 saber que o guardrail de CI para "alpha não pode importar meta" precisará ser criado quando `src/models/meta.py` nascer.

---

## DoD

- [x] 11 estágios catalogados (12 com Meta-Model, marcado ausente com justificativa)
- [x] VOLATILIDADE e REGIME com enumeração EXAUSTIVA de fan-in (135 e 350 pontos de uso individuais, respectivamente)
- [x] toda decisão matemática de §12.2 localizada em arquivo:linha, por estágio
- [x] todo parâmetro classificado em uma das 4 categorias de §12.3
- [x] tabela de divergências PRD↔código preenchida por estágio (54 no total, nenhum estágio com tabela vazia sem justificativa)
- [x] os dois artefatos gerados (`docs/CODE_DISCOVERY.md`, `experiments/code_discovery.json`), com `generated_at`/`code_version`
- [x] nenhuma recomendação no catálogo — observações do executor isoladas em seção própria por estágio, 53 no total
