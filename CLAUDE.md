# CLAUDE.md — BTCUSDT Quant Engine

> Instruções persistentes para Claude Code rodando neste repo.
> Atualizado: 2026-08-08 | Sprint atual: **0** | Versão: v1.0
> Documento mestre: `docs/PRD_V3_2_UNIFICADO.md` (3.329 linhas, 19 partes)
> Toda regra abaixo é ancorada em §X.Y do PRD. Regra sem âncora é dívida técnica.

---

## Contexto

Motor quantitativo local para **BTCUSDT perpétuo na Binance USDⓈ-M**, capital de **R$ 1.000 (US$ 196,85)**, decisão a **15m**, execução **maker post-only**. Solo developer, grau prop desk.

**A V1 não existe para provar que BTCUSDT pode ser previsto.** Existe para construir infraestrutura em que uma hipótese quantitativa possa ser formulada → testada → invalidada ou aprovada → simulada → monitorada → executada → auditada. Com US$ 196,85, isso é a única leitura honesta do projeto.

**O capital não é um parâmetro — é a restrição estrutural que determina o desenho.** Lote mínimo de 0,001 BTC = US$ 64,94 = 33% do equity. Tudo neste repo decorre disso.

---

## As 5 restrições invioláveis (§0.2)

Qualquer código que as viole é rejeitado, mesmo que passe nos testes.

| # | restrição | valor operacional |
|---|---|---|
| R1 | erro de quantização ≤ `quantization_tolerance` **e** `N_req/unit ≥ 2` | stop ≤ 0,758% |
| R2 | custo round-trip ≤ `cost_stop_ratio_max` × stop | stop ≥ 0,275% |
| R3 | fees mensais ≤ `fee_budget_monthly` × equity | ~55 trades/mês |
| R4 | teto de features = medido, **nunca estipulado** | ver §0.2 R4 |
| R5 | alavancagem **não é** controle de risco; nocional é | `max_notional_multiple` |

**Janela viável atual:** stop ∈ [0,275% ; 0,758%], escolhido 0,458% = 1,5 × ATR(20,15m).
**Teto de preço do BTC:** US$ 107.568. Acima disso a granularidade morre e o Gate 0 contínuo bloqueia (§16.11).

---

## Regra zero: proveniência (§16.10, PARTE XVIII)

**70% das constantes do PRD original não tinham base.** Este repo existe para não repetir isso.

```yaml
# config/constants.yaml — TODA constante tem esta estrutura
cost_stop_ratio_max:
  value: 0.20
  provenance: ASSUMED        # MEASURED | DERIVED | LITERATURE | ASSUMED
  source: "sem base; escolhido por conveniência"
  class: A                   # A=invalida desenho | B=hiperparâmetro | C=guardrail | D=cosmético
  sweep_required: true
  sweep_range: [0.10, 0.40]
```

Regras de enforcement:

1. **Nenhum literal numérico em código de pipeline.** Lint quebra o build.
2. **CI bloqueia build de produção com classe A em `provenance: ASSUMED`.**
3. **Guardrails classe C são quantis, não números redondos.** `p95(spread, 90d)`, não `3.0`.
4. **Classe A exige varredura de sensibilidade ±50% antes do Gate 3.** Critério não é "Sharpe bom no valor escolhido" — é **robusto na vizinhança**. Pico estreito significa que o número faz o trabalho que deveria ser do modelo.
5. **`N_lifetime` é arquivo versionado.** Toda constante classe B otimizada, todo retreino, todo challenger incrementa. O DSR usa `N_lifetime`, não o `N` de uma busca isolada.

---

## Banned patterns

Lint via `tools/lint/banned_patterns.py` em pre-commit. Build quebra se violado.

### Vazamento temporal

| # | proibido | correto | âncora |
|---|---|---|---|
| B01 | filtros de instrumento atuais em dado histórico | `load_filters_asof(t)` | §1.4 |
| B02 | quantil/z-score com índice ≥ `t` | janela expansiva estrita `< t` | §2.0 |
| B03 | scaler ajustado no dataset inteiro | expansivo ou por fold | §11.5 #8 |
| B04 | seleção de feature fora do fold | dentro de cada fold de treino | §11.5 #12 |
| B05 | HMM/regime ajustado na série toda e "predito" barra a barra | reajustar por fold com purge | §5.2 |
| B06 | usar a tabela de IC 7 anos (§17.2) para configurar modelo | triagem in-fold | §5.3 |

### Vazamento estrutural

| # | proibido | correto | âncora |
|---|---|---|---|
| B07 | treinar Meta em predição do Alpha sem `is_oof` | `assert df_meta.is_oof.all()` | §5.12 |
| B08 | calibrador ajustado sobre o próprio OOF | sub-split interno do treino | §5.9 passo 9 |
| B09 | split de CV sem purge por `t1` | purge + embargo 175 barras | §11.4 |
| B10 | treinar sem `sample_weight` de unicidade | sempre com peso | §3.5 |

### Label e execução

| # | proibido | correto | âncora |
|---|---|---|---|
| B11 | avaliar barreira em high/low da barra de 15m | `mark_1m`, primeiro toque cronológico | §3.4 |
| B12 | stop com `working_type: CONTRACT_PRICE` | `MARK_PRICE` | §9.1 |
| B13 | converter ordem limite em market no timeout | `on_timeout: CANCEL` | §9.1 |
| B14 | postar TP antes do SL após fill | SL **sempre** primeiro | §16.2 |
| B15 | `config_hash` do label ≠ o da execução | teste de CI | §3.4 |
| B16 | enviar ordem com outra em `UNKNOWN` | resolver antes | §9.7 |
| B17 | cache local de equity | reconciliação é a única fonte | §8.7 |

### Modelo

| # | proibido | correto | âncora |
|---|---|---|---|
| B18 | `multi:softprob` | dois binários `M_long`/`M_short` | §5.2 |
| B19 | `colsample_bytree < 1.0` com bagging por grupo ativo | `1.0` — camada 3 substitui | §5.10 |
| B20 | threshold escolhido por métrica OOS | a priori pelo orçamento de fees | §5.6 |
| B21 | `hmmlearn` | determinístico por quantis; `dynamax` na V1.1 | §14.1 |
| B22 | retreinar após sequência de perdas | cadência fixa declarada a priori | §16.4 |
| B23 | faixa esperada inventada em doc ou teste | `TBD — medir no Sprint N` | §16.10 M4 |
| B24 | `N_eff = n/h` ou `1+s(2h−1)` como constante | medir `Σ uniqueness` | §0.2 R4 |
| B25 | presumir ATR de volatilidade anualizada | medir dos klines | §0.4 |

### Stack e operação

| # | proibido | correto | âncora |
|---|---|---|---|
| B26 | Pandas no core | Polars lazy; Pandas só em interop de borda | §14.1 |
| B27 | `pip`/`venv`/`conda` | `uv` + lockfile | §14.1 |
| B28 | `print()` | `structlog` + orjson | §14.1 |
| B29 | escrita não-atômica | `.tmp` → `fsync` → rename | §1.2 |
| B30 | `enable_withdraw: true` na chave de API | jamais, em nenhuma circunstância | §16.7 |
| B31 | chave em código, config versionada, log ou mensagem de erro | env fora do repo + mascaramento | §16.7 |
| B32 | assinar REST sem percent-encode antes | ordem correta, senão `-1022` | §9.4 |

---

## Layer hierarchy

```
exchange → data → features → labels → regime → models → validation
                                                    ↓
                          backtest ← risk ← execution ← live
```

Verificada estaticamente. Violações que quebram o build:

- `features/` **não pode** importar `labels/`
- `models/` **não pode** importar `execution/`
- Ninguém além de `models/`, `validation/`, `backtest/` lê `labels/`
- `alpha` **não pode** importar `meta` (zero realimentação, §5.8)

---

## Stack 2026

**Obrigatório:** Python 3.12+ · `uv` · Polars (lazy, Arrow) · DuckDB · Parquet+zstd · XGBoost `binary:logistic` · scikit-learn (calibração isotônica) · Optuna com orçamento declarado · structlog+orjson · Pydantic+YAML · pytest+hypothesis · ruff · mypy strict

**Avaliar antes de escrever motor próprio:** NautilusTrader (backtest event-driven, mesmo código em backtest e live) · `binance-futures-connector` oficial atrás de interface própria

**Proibido:** `hmmlearn` · Pandas no core · pip/venv/conda · `print()`

---

## Definition of Done por tipo de tarefa

### Código de feature
- [ ] Entrada em `features/registry.yaml` com fórmula, fonte, lookback, `causal_proof`
- [ ] Teste de causalidade: nenhum índice ≥ `t0`
- [ ] Teste de paridade lote↔streaming < 1e-8 nas últimas 500 barras
- [ ] Teste de determinismo: mesmo input → mesmo hash
- [ ] Warmup declarado e respeitado

### Código de modelo
- [ ] `sample_weight` de unicidade aplicado
- [ ] Predições marcadas com `is_oof`
- [ ] `monotone_constraints` derivadas **in-fold**
- [ ] HHI de importância < 0,25, maior share < 0,30
- [ ] Métricas estratificadas por regime R1..R4 **e** por regime econômico

### Código de execução
- [ ] `time_in_force: GTX` na entrada
- [ ] SL antes de TP no handler de fill, com timeout de 2s
- [ ] `client_order_id` determinístico e idempotente
- [ ] Teste de fill parcial na entrada **e** na saída
- [ ] Teste de reinício com posição aberta

### Qualquer PR
- [ ] Nenhum literal numérico novo fora de `constants.yaml`
- [ ] `provenance` declarada para toda constante nova
- [ ] `N_lifetime` incrementado se houve otimização
- [ ] Âncora §X.Y do PRD no commit message

---

## Comandos

```bash
uv run quant feasibility          # Gate 0 — roda em segundos, ANTES de tudo
uv run quant data download        # 15 fontes, checksums
uv run quant data validate        # → quality_report.json
uv run quant features build       # + paridade
uv run quant regime build
uv run quant labels build         # → t1, uniqueness, NOFILL
uv run quant validation leakage   # 14 testes
uv run quant models train         # camadas 1→5 com ablação
uv run quant validation cpcv
uv run quant validation walkforward   # G-WF-1..6, mede meia-vida
uv run quant backtest run         # + reconciliação vs ret_net
uv run quant validation dsr       # com N_lifetime
uv run quant stress run           # 19 cenários
uv run quant testnet run
uv run quant paper run
uv run quant live run
```

---

## Comportamento esperado

**Meça antes de afirmar.** Este projeto já perdeu três decisões para números plausíveis escritos com confiança: ATR presumido de volatilidade anualizada (estava no percentil 13 do real), fórmula de concorrência trocada (fator 2 de erro), e um "≥ 3 unidades" inventado que restringiu 50% mais que o necessário. Os dados estão em `data.binance.vision`, são públicos e não exigem chave. Baixe e meça.

**Declare proveniência ao escrever qualquer número.** Se você não sabe de onde veio, marque `ASSUMED` e classifique. Não invente faixas esperadas — escreva `TBD — medir no Sprint N`.

**Trate lote mínimo como restrição física.** Não é arredondamento; é o que determina timeframe, tipo de ordem, número de features e risco por trade. Se uma mudança de parâmetro viola R1 ou R2, a mudança está errada, não a restrição.

**Nunca "otimize" de volta o que foi derivado.** `risk_per_trade = 0,005` não é escolha estética — é consequência de R1 e R2. Código que o parametriza como livre viola o desenho.

**Discorde do Manager quando os dados discordarem.** Este PRD melhorou porque erros foram apontados, não porque foram acomodados. Se uma instrução contradiz uma medição, apresente a medição.

**Não escreva motor próprio antes de avaliar o de prateleira.** O backtest engine é o componente caseiro de maior risco do projeto.

**Pare na primeira camada que funcionar.** As cinco camadas do §5.11 são ordenadas por razão ganho/custo, com critério de parada explícito. Cinco camadas custam cinco entradas no `N_lifetime` e cinco fontes de bug.

---

## Estado atual

| item | valor |
|---|---|
| Sprint | 0 — Gate 0 (planilha de viabilidade) |
| TF de decisão | 15m a priori; 30m como robustez |
| Meta Model | **fora da V1** (§6.8 define o critério de entrada) |
| Pendências P0 | snapshots `exchangeInfo` iniciar hoje · verificar acesso empírico à conta · MMR tier 1 não confirmado |
| Primeiras medições | ATR sobre série completa (Sprint 3) · varredura 2D `tp_atr_mult` × `sl_atr_mult` (Sprint 6) |

---

## Changelog

- v1.0 (2026-08-08) — criação. Ancorado no PRD V3.2 unificado. 32 banned patterns derivados dos 8 erros documentados na PARTE XIX.
