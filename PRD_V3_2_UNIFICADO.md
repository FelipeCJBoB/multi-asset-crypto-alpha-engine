# PRD TÉCNICO V3.3 — BLUEPRINT OPERACIONAL UNIFICADO
## BTCUSDT Perpetual · Binance USDⓈ-M · Motor Quantitativo Local

**Versão:** 3.3 — documento único: blueprint + estudo de não-estacionariedade + registro de proveniência + fato de venue RPI (2026-08-08)
**Data:** 2026-08-08
**Status:** Blueprint de implementação — ponta a ponta
**Substitui:** PRD Técnico V2 Consolidado
**Unifica:** blueprint v3.1 · `ESTUDO_NAO_ESTACIONARIEDADE.md` · `AUDITORIA_PROVENIENCIA.md`
**Mapa de rastreabilidade:** PARTE XIX — 54 requisitos, 9 erros corrigidos

---

## Como ler este documento

Cada estágio do pipeline aparece com **cinco blocos fixos**:

| bloco | conteúdo |
|---|---|
| **INPUT** | o que entra, de onde, com qual granularidade |
| **PROCESSO** | a regra, enumerada item a item |
| **OUTPUT** | schema de saída, coluna a coluna, com tipo |
| **CONSUMIDORES** | quem lê, e o que **não** pode ler |
| **INVARIANTES** | asserts que quebram o build se violados |

Nada neste documento é "a ser definido". Onde há incerteza legítima, há um valor default declarado e o critério de revisão.

---

# PARTE 0 — RESTRIÇÕES INVIOLÁVEIS

## 0.1 Constantes do sistema

```yaml
venue:
  exchange:          BINANCE_USDM
  rest_base:         https://fapi.binance.com
  ws_base:           wss://fstream.binance.com
  symbol:            BTCUSDT
  contract:          PERPETUAL
  margin_asset:      USDT
  pnl:               linear    # qty × (exit − entry)

account:
  capital_inicial_brl:   1000.00
  usd_brl_ref:           5.08
  capital_inicial_usd:   196.85
  base_currency:         USDT

instrument_filters:            # snapshot 2026-08-08 — versionado, ver §1.4
  tick_size:             0.10        # PRICE_FILTER
  step_size:             0.001       # LOT_SIZE  ← RESTRIÇÃO DOMINANTE
  min_qty:               0.001
  min_notional:          50.0        # reduzido de 100 em 2026-04-14
  unit_notional_usd:     64.94       # 0.001 × 64940 (referência, recalcular sempre)

fees:
  maker:                 0.0002
  taker:                 0.0005
  bnb_discount:          0.90
  funding_interval_h:    8           # VERIFICAR no dado, não assumir (§1.4)

timing:
  decision_tf:           15m         # v3.1: era 30m; ver §0.4
  context_tf:            [1h, 4h, 1d]
  feature_source_tf:     [1m, 5m, 15m]
```

## 0.2 As cinco restrições que determinam o desenho

Estas não são preferências. São aritmética. Qualquer mudança de parâmetro que as viole é rejeitada pelo Gate 0.

**R1 — Granularidade de lote.** *(Corrigido na v3.1 — o "≥ 3 unidades" da versão anterior não tinha base.)*

A restrição real é o **erro de quantização**, não uma contagem de unidades. Arredondar `N_req/unit` para o inteiro mais próximo produz erro máximo de meia unidade, logo:

```
erro_máx = 0,5 × unit / N_req ≤ quantization_tolerance
N_req ≥ 0,5 × unit / quantization_tolerance

com quantization_tolerance = 0,25:   N_req ≥ 2 × 64,94 = US$ 129,88
                                     stop% ≤ risk$ / 129,88 = 0,758%
```

O teto anterior de 0,505% vinha de um "≥ 3 unidades" arbitrário e era **50% mais restritivo que o necessário**.

**R2 — Eficiência de custo.** O custo de round-trip precisa ser ≤ `cost_stop_ratio_max` da distância de stop.

```
stop% ≥ c_médio / cost_stop_ratio_max
c_médio(assimétrico) = 0,055%,  cost_stop_ratio_max = 0,20  ⟹  stop% ≥ 0,275%
```

⚠️ **`cost_stop_ratio_max = 0,20` é premissa, não resultado.** Ver §16.10 — sujeita a varredura de sensibilidade obrigatória antes do Gate 3.

**R3 — Orçamento de fees.** O custo mensal de corretagem não pode passar de `fee_budget_monthly` do equity.

```
trades/mês ≤ (fee_budget_monthly × equity) / (N × c)
com fee_budget_monthly = 0,03:  5,91 / 0,1072 = 55,1
→ 1,84 trades/dia · 661 trades/ano · 1,89% das barras de 15m
```

⚠️ **`fee_budget_monthly = 0,03` é premissa arbitrária.** Ver §16.10.

**R4 — Teto de features.** *(Reescrito na v3.1 — era uma constante derivada de fórmula errada; virou procedimento de medição.)*

Labels de triple barrier ocupam um intervalo `[t0, t1]`, não um instante. Labels que se sobrepõem compartilham o mesmo caminho de preço e carregam informação redundante. Isso é sólido e está em AFML cap. 4.

**O que NÃO é sólido é qualquer fórmula fechada para o número resultante.** Três armadilhas:

1. **Duas quantidades diferentes são confundidas.** Concorrência *pontual* `c_t = s·h` (quantos labels cobrem um instante — é a definição do LdP) versus vizinhança de *sobreposição* `1 + s(2h−1)` (com quantos labels um label se correlaciona). A primeira dá `N/h`; a segunda dá `N/(2h−1)`. Fator 2 de diferença.
2. **A checagem por inflação de variância confirma a primeira.** Para janelas sobrepostas, `ρ_k ≈ (h−k)/h`, logo `VIF = 1 + 2Σρ_k = h`, e `N_eff = N/h`. O `2h−1` só valeria se `ρ_k = 1` em toda a vizinhança — pior caso impossível.
3. **`h` é o teto do span, não o típico.** O span real é `min(primeiro toque de barreira, time_stop)`. Se o holding mediano for 6 barras em vez de 16, `N_eff` triplica.

Faixa resultante conforme a premissa, com `N = 103.700` e `h = 16`:

| premissa | N_eff | teto de features |
|---|---|---|
| vizinhança de sobreposição, span = h | 3.241 | 6 a 16 |
| LdP padrão, span = h | 6.481 | 13 a 32 |
| LdP, span médio 8 | 12.962 | 26 a 65 |
| LdP, span médio 5 | 20.740 | 42 a 104 |

**Procedimento obrigatório (Sprint 6, após os labels existirem):**

```python
# 1. concorrência pontual observada
c = np.zeros(n_bars)
for i in labels.itertuples():
    c[idx(i.t0):idx(i.t1)] += 1

# 2. unicidade média por label — AFML cap.4
for i in labels.itertuples():
    labels.loc[i, "uniqueness"] = np.mean(1.0 / c[idx(i.t0):idx(i.t1)])

# 3. número efetivo de observações independentes
N_eff = labels["uniqueness"].sum()

# 4. teto de features
feature_ceiling = (N_eff / 500, N_eff / 200)
```

**A regra "1 parâmetro por 200–500 observações" também não é teorema.** Vem da regra de *events per variable* (~10 EPV) da bioestatística, inflada por praticantes para a razão sinal-ruído de mercado. Não tem derivação. E para XGBoost, "número de features" ≠ "número de parâmetros livres": 300 árvores de profundidade 3 têm capacidade muito maior que 12 coeficientes. A regra é um prior, e está declarada como tal.

**Restrição concorrente, possivelmente mais dura:** para significância do Sharpe — que é o que o DSR mede — o que conta é **contagem de trades**, não de barras. Com o orçamento de fees de 496 trades/ano × 5,9 anos ≈ **2.900 trades**, e esse número não melhora com unicidade.

**Valor operacional até a medição:** `N_eff = desconhecido, entre 6.500 e 26.000`. O tamanho de T1 é decidido no Sprint 6, não agora.

**R5 — Alavancagem não é controle de risco.** Testada de 3x a 20x, a janela de stop não se move. O controle real é `max_notional_multiple`. A alavancagem da exchange serve só para liberar buffer de margem.

## 0.3 A janela viável resultante

```
risk_per_trade = 0,50%  (US$ 0,984)
caminho de execução = maker entrada · maker TP · taker SL

stop ∈ [0,275% (custo) ; 0,758% (quantização)]
stop escolhido = 1,5 × ATR(20, 15m) = 0,458%
```

| verificação | valor | limite | ok |
|---|---|---|---|
| stop | 0,458% | [0,275 ; 0,758] | ✓ |
| N exigido | US$ 215,1 | — | — |
| unidades | 3 | ≥ 2 | ✓ |
| nocional real | US$ 194,82 | — | — |
| erro de quantização | 9,4% | ≤ 25% | ✓ |
| risco real | 0,453% | ≤ 0,60% | ✓ |
| alavancagem efetiva | 0,99x | ≤ 3,0x | ✓ |
| breakeven win rate | 48,1% | ≤ 55% | ✓ |
| **teto de preço do BTC** | **US$ 107.568** | hoje US$ 64.940 | ✓ 66% de folga |

## 0.4 Por que 15m e não 30m — ATR medido, não presumido

A v3.0 usava `ATR(20, 30m) = 0,272%`, derivado de vol anualizada de 40% presumida. Medição sobre klines reais (8 meses distribuídos entre 2021 e 2026, 4 timeframes):

| TF | ATR p25 | **ATR mediana** | ATR p75 | stop | unidades | q_err | BE WR | % barras na janela |
|---|---|---|---|---|---|---|---|---|
| 5m | 0,108 | **0,163** | 0,280 | 0,245% | 6,20 | 3,1% | 52,4% | 37,7% |
| **15m** | 0,218 | **0,305** | 0,484 | 0,458% | 3,32 | 9,4% | **48,1%** | **60,9%** |
| 30m | 0,334 | **0,440** | 0,669 | 0,659% | 2,30 | 13,0% | 46,5% | 56,5% |
| 1h | 0,494 | **0,626** | 0,943 | 0,939% | 1,61 | 23,9% | 45,4% | 26,7% |

A premissa de 0,272% a 30m estava no **percentil 13** da distribuição real. A mediana verdadeira é 0,440%.

**Teto de preço do BTC por TF** — acima dele, a unidade mínima de 0,001 BTC vira fração grande demais do equity e a granularidade morre:

```
 5m  →  US$ 201.156      (210% de folga)
15m  →  US$ 107.568      ( 66% de folga)   ← escolhido
30m  →  US$  74.630      ( 15% de folga)
 1h  →  US$  52.420      (JÁ ABAIXO do preço de hoje)
```

**Consequência de desenho: o Gate 0 não pode rodar uma vez.** O preço do BTC é variável aleatória, não parâmetro. O Gate 0 vira verificação contínua (§16.11), e o teto de preço vira alerta operacional.

⚠️ **Esta medição é ela própria parcial:** 8 meses de 71 disponíveis, escolhidos por conveniência. Precisa ser refeita sobre a série completa no Sprint 3. Ver §16.10.

## 0.5 Timeframes eliminados no Gate 0

A eliminação é **aritmética, não empírica** — não usa modelo, não usa lucro. Aplicando §0.2 sobre o ATR medido:

| TF | falha em | eliminação |
|---|---|---|
| 5m | stop 0,245% < piso de custo 0,275% | ⚠️ **condicional** — depende de `cost_stop_ratio_max = 0,20`, constante classe A inventada (§18). Se a varredura mover para 0,30, o piso cai para 0,183% e 5m retorna |
| **15m** | — | **sobrevive — escolhido a priori** |
| **30m** | — | **sobrevive — verificação de robustez** |
| 1h | risco real 0,619% > teto 0,60% | sólida |
| 2h | 1,14 unidades; risco varia 3,05x entre p10 e p90 | sólida |
| 4h | 0,80 unidades — **abaixo do lote mínimo** | sólida |

**Capital que destrava cada TF** (`N_req ≥ 2 unidades`, `risk 0,50%`, BTC US$ 64.940):

```
 5m  R$    323        1h  R$ 1.239
15m  R$    603        2h  R$ 1.748
30m  R$    870        4h  R$ 2.509
```

**Regra de seleção:** 15m é escolha **a priori**, registrada no pré-registro (§16.9). 30m é **verificação de robustez**, não competidor. Escolher entre os dois pelo maior Sharpe seria seleção por ruído — exatamente o que o DSR pune. Resultados parecidos entre os dois é evidência de sinal real; divergência grande é o achado, não critério de escolha. A dimensão "timeframe" contribui com fator **1** para o `N_lifetime`, não 6.

## 0.6 Escopo

**Dentro:** BTCUSDT perpétuo · long / short / flat · uma posição por vez · **decisão a 15m** · execução maker · dois arquétipos de estratégia (reversão à média, rompimento de volatilidade) · Alpha supervisionado · regime determinístico · backtest com custos completos · CPCV · testnet · paper · live.

**Fora da V1:** múltiplos pares · múltiplas posições simultâneas · arbitragem entre exchanges · opções · spot · market making · reinforcement learning · Transformer · LSTM · otimização de portfólio · alta frequência · **Meta Model** (rebaixado, §6) · sizing dinâmico · Kelly.

---

# PARTE I — DADOS

## 1.1 Catálogo completo de fontes

### A. Dumps públicos `data.binance.vision` (sem chave de API)

| # | fonte | caminho | granularidade | início | status | prio |
|---|---|---|---|---|---|---|
| D01 | `aggTrades` | `futures/um/daily/aggTrades/BTCUSDT/` | tick agregado | 2019-09 | ✓ coletado | — |
| D02 | `bookDepth` | `futures/um/daily/bookDepth/BTCUSDT/` | snapshot | 2023-01 | ✓ coletado | — |
| D03 | `klines` 1m | `futures/um/daily/klines/BTCUSDT/1m/` | 1m | 2019-09 | ✓ coletado | — |
| D04 | `metrics` | `futures/um/daily/metrics/BTCUSDT/` | **5m** | **2020-09-01** | ✓ coletado | — |
| D05 | `BVOLIndex` | `option/daily/BVOLIndex/BTCBVOLUSDT/` | diário | 2021 | ✓ coletado | — |
| D06 | `klines` trimestral | `futures/um/daily/klines/BTCUSDT_{YYMMDD}/` | 1m | vários | ✓ coletado | — |
| D07 | `fundingRate` | `futures/um/monthly/fundingRate/BTCUSDT/` | 8h | 2019-09 | ✓ coletado | — |
| D08 | `bookTicker` | `futures/um/daily/bookTicker/BTCUSDT/` | tick | 2022-01 | ✓ coletado | — |
| D09 | `bookTicker` tick | idem, sem agregação | tick | 2022-01 | ✓ coletado | — |
| **D10** | **`markPriceKlines`** | `futures/um/daily/markPriceKlines/BTCUSDT/1m/` | 1m | 2020-01 | **✗ FALTA** | **P0** |
| **D11** | **`premiumIndexKlines`** | `futures/um/daily/premiumIndexKlines/BTCUSDT/1m/` | 1m | 2020-01 | **✗ FALTA** | **P0** |
| D12 | `indexPriceKlines` | `futures/um/daily/indexPriceKlines/BTCUSDT/1m/` | 1m | 2020-01 | ✗ falta | P1 |
| D13 | `spot/klines` | `spot/daily/klines/BTCUSDT/1m/` | 1m | 2017-08 | ✗ falta | P1 |
| D14 | `EOHSummary` | `option/daily/EOHSummary/` | hora | 2022 | ✗ falta | P2 |
| D15 | `trades` bruto | `futures/um/daily/trades/BTCUSDT/` | tick | 2019-09 | ✗ falta | P3 |

**Justificativa dos P0:**

- **D10 `markPriceKlines`** — a Binance dispara **stop-loss, liquidação e funding pelo mark price**, não pelo last. Sem esta série o Label Engine avalia barreiras no preço errado e o backtest fica sistematicamente enviesado. Não é enriquecimento, é corretude.
- **D11 `premiumIndexKlines`** — é o insumo do cálculo do funding. Com ele, `funding_next` vira **estimativa antes do settlement**; sem ele, funding só existe retrospectivamente e a feature perde metade do valor. Valores típicos na ordem de `-0.00023142`.

**Conteúdo de D04 `metrics`** (a fonte que resolve o Open Interest — o limite de 30 dias é da API REST, não do dump):

```
create_time, symbol, sum_open_interest, sum_open_interest_value,
count_toptrader_long_short_ratio, sum_toptrader_long_short_ratio,
count_long_short_ratio, sum_taker_long_short_vol_ratio
```
289 linhas/arquivo · 5 minutos · desde 2020-09-01.

### B. Coleta forward — não backfillável, iniciar no Sprint 2

| # | fonte | endpoint / stream | frequência | por que |
|---|---|---|---|---|
| F01 | `exchangeInfo` snapshot | `GET /fapi/v1/exchangeInfo` | diário | `MIN_NOTIONAL` caiu 100→50 em 2026-04-14; tick/lot mudaram no histórico. **O filtro de lote é a restrição dominante deste projeto** — usar o filtro de hoje num backtest de 2020 é anacronismo que infla a granularidade de sizing |
| F02 | `leverageBracket` snapshot | `GET /fapi/v1/leverageBracket` | diário | MMR por faixa de nocional muda |
| F03 | `forceOrder` stream | `wss ...@forceOrder` | tick | liquidações; não há dump |
| F04 | fee tier da conta | `GET /fapi/v1/commissionRate` | semanal | backtest precisa da fee que **você** paga |
| F05 | `openInterest` live | `GET /fapi/v1/openInterest` | 30m | paridade com D04 (§1.5) |
| **F06** | **`rpiDepth` snapshot + stream** | `GET /fapi/v1/rpiDepth` (REST) e `Diff-Book-Depth-RPI` (WS, 500ms) | 500ms | Desde 2025-11-20 existem ordens RPI post-only que NÃO aparecem em `bookTicker` nem em `/fapi/v1/depth`. Sem esta coleta o simulador de fila (§9.5) subestima `queue_ahead` sistematicamente e superestima o fill rate. **Não há dump histórico — só coleta forward.** |

### C. Externas

| # | fonte | origem | granularidade | cobertura | prio |
|---|---|---|---|---|---|
| E01 | on-chain | CoinMetrics CSV | diário | 6.351 dias × ~35 métricas | ✓ coletado |
| E02 | fluxo líquido ETF spot BTC | SoSoValue / Farside | diário | desde 2024-01 (~2,5a) | P1 |
| E03 | calendário de eventos | FOMC · CPI · NFP · vencimento de opções | evento | longo | **P1** |
| E04 | macro | FRED: DXY, UST 2a/10a, real yield, VIX | diário | longo | P2 |
| E05 | funding/OI cross-venue | Bybit · OKX · Hyperliquid | 1h | variável | P2 |
| E06 | DVOL + skew 25Δ | Deribit | 1h | desde 2019 | P2 |

**E03 é P1 e não é feature preditiva — é gatilho de bloqueio.** Com stop de 0,408%, entrar posicionado numa janela de FOMC ou CPI é doar prêmio de volatilidade. O Risk Engine consome isso (§8.4).

## 1.2 Data Lake

```
data/
├── raw/                              # imutável, hash verificado, nunca reescrito
│   ├── agg_trades/{yyyy}/{mm}/
│   ├── book_depth/{yyyy}/{mm}/
│   ├── book_ticker/{yyyy}/{mm}/
│   ├── klines_1m/{yyyy}/{mm}/
│   ├── mark_price_1m/{yyyy}/{mm}/     # D10
│   ├── premium_index_1m/{yyyy}/{mm}/  # D11
│   ├── index_price_1m/{yyyy}/{mm}/    # D12
│   ├── spot_klines_1m/{yyyy}/{mm}/    # D13
│   ├── metrics_5m/{yyyy}/{mm}/        # D04
│   ├── funding/{yyyy}/
│   ├── bvol/{yyyy}/
│   ├── options_eoh/{yyyy}/{mm}/       # D14
│   ├── onchain/                       # E01
│   └── snapshots/                     # F01, F02, F04 — versionado por data
│       ├── exchange_info/{yyyy-mm-dd}.json
│       ├── leverage_bracket/{yyyy-mm-dd}.json
│       └── fee_tier/{yyyy-mm-dd}.json
│
├── processed/                         # barras alinhadas, timezone UTC, sem gaps mascarados
│   ├── bars_1m/    bars_5m/    bars_30m/    bars_2h/    bars_1d/
│   ├── mark_1m/                       # série de referência das barreiras
│   └── funding_events/                # timestamps reais, intervalo derivado
│
├── features/{feature_version}/        # imutável por versão
├── labels/{label_version}/
├── predictions/
│   ├── alpha/{model_id}/              # com coluna is_oof
│   └── meta/{model_id}/
├── backtests/{run_id}/
├── experiments/                       # log de TODAS as variantes — insumo do DSR
└── live/
    ├── decisions/    orders/    fills/    reconciliation/    audit/
```

**Formato:** Parquet, compressão zstd, particionado por ano/mês.
**Camada analítica:** DuckDB sobre os arquivos. Nunca carregar `raw` inteiro em memória.
**Escrita:** atômica — grava em `.tmp`, `fsync`, renomeia. Nenhum arquivo parcial visível.

## 1.3 Data Quality Engine — RF-003

### INPUT
Qualquer dataset de `raw/` ou `processed/`.

### PROCESSO — 23 verificações

**Integridade estrutural**
1. Schema bate com o contrato declarado (nomes, tipos, ordem)
2. Checksum do arquivo confere com o `.CHECKSUM` da Binance
3. Sem linhas duplicadas por chave primária
4. Sem valores nulos em colunas não-anuláveis

**Temporal**
5. Timestamps estritamente monotônicos
6. Todos em UTC, sem ambiguidade de fuso
7. `close_time = open_time + intervalo − 1ms` (convenção Binance)
8. Sem barras fora de ordem
9. Grade temporal completa — **listar os timestamps ausentes, não só contar**
10. Gaps classificados: manutenção anunciada · falha de coleta · ausência real de negócio

**Valores**
11. `low ≤ open ≤ high`, `low ≤ close ≤ high`
12. Preços > 0
13. Volume ≥ 0
14. `taker_buy_volume ≤ volume`
15. Sem saltos incompatíveis: `|log(close_t / close_{t−1})| > 8σ` marcado para inspeção manual, não descartado automaticamente

**Consistência entre fontes**
16. `bars_30m` reagregado de `bars_1m` bate com o kline nativo de 30m dentro de 1e-8
17. `mark_price` dentro de ±2% do `close` do perpétuo
18. `index_price` dentro de ±2% do spot
19. Timestamps de funding espaçados consistentemente — **derivar o intervalo do dado, nunca assumir 8h**
20. `metrics` a 5m alinha na grade de 30m sem interpolação para frente

**Cobertura por feature**
21. Toda feature declarada tem série contínua ≥ período de treino. Feature sem cobertura **não entra no dataset**, e a falha é nomeada — não silenciosa
22. Data de início efetiva do dataset = máximo das datas de início de todas as fontes T1

**Consistência entre fontes (cont.)**
23. **Quebra semântica de fonte.** Cruzar o changelog da exchange contra as datas do dataset. Um campo pode manter schema, checksum e continuidade e ainda assim mudar de significado. Manter `config/venue_changelog.yaml` com data, endpoint afetado e features derivadas; o validador falha se houver feature T1 cuja série atravesse uma data de quebra sem tratamento declarado.

Entrada inicial obrigatória:

```yaml
- date: 2025-11-20
  event: "Binance Futures lança ordens RPI"
  endpoints_afetados: [depth, bookTicker, bookDepth]
  semantica: "book visível deixa de ser book completo; níveis cruzados ocultos"
  features_contaminadas: [F01f, F02f, F03f, F04f, F05f, F06f, F07f, F08f, F09f, F10f, F12f]
  tratamento: ver §2.7.1
```

### OUTPUT — `quality_report_{dataset}_{version}.json`

```json
{
  "dataset": "bars_30m",
  "version": "v1",
  "rows": 103700,
  "start": "2020-09-01T00:00:00Z",
  "end": "2026-08-01T00:00:00Z",
  "missing_bars": 41,
  "missing_timestamps": ["2021-03-14T08:30:00Z", "..."],
  "gap_classification": {"maintenance": 38, "collection": 3, "unknown": 0},
  "duplicates": 0,
  "invalid_rows": 0,
  "outliers_flagged": 7,
  "cross_source_max_deviation": 2.1e-9,
  "coverage_by_feature": {"E01_funding_z": "2020-09-01", "F01_ob_imbalance": "2022-01-01"},
  "effective_start": "2022-01-01T00:00:00Z",
  "quality_score": 0.9987,
  "gate": "PASS"
}
```

### INVARIANTES
```python
assert report["gate"] == "PASS"                        # senão não treina
assert report["duplicates"] == 0
assert report["cross_source_max_deviation"] < 1e-8
assert dataset_start >= report["effective_start"]
```

## 1.4 Filtros versionados — o detalhe que corrompe backtest antigo

O `LOT_SIZE` é a restrição dominante deste projeto (§0.2 R1). Ele **mudou** ao longo dos 6 anos, e o `MIN_NOTIONAL` mudou de 100 para 50 USDT em 2026-04-14.

**Regra:** o backtest resolve o filtro **pela data da barra**, não pelo snapshot de hoje.

```python
filters = load_filters_asof(bar.timestamp)   # nunca load_filters_current()
qty = floor_to_step(notional / price, filters.step_size)
assert qty * price >= filters.min_notional
```

Para o período anterior ao início da coleta forward (F01), reconstruir por anúncios da Binance e registrar em `snapshots/exchange_info/reconstructed/`, com flag `is_reconstructed: true`. O relatório de backtest declara qual fração do período usou filtros reconstruídos.

## 1.5 Paridade histórico ↔ live das métricas

`metrics` (D04) é agregado a 5m pela Binance. Ao vivo você lê `GET /fapi/v1/openInterest`, que é pontual. Os dois não são idênticos por construção.

**Teste obrigatório:** por 30 dias, coletar F05 ao vivo em paralelo e comparar contra D04 quando o dump do dia sair. Registrar o desvio como `oi_parity_bps`. Se o desvio mediano passar de 10 bps, a feature de OI usa a série **derivada da mesma forma nos dois modos**, não a nativa.

---

# PARTE II — FEATURE ENGINE

## 2.0 Princípios

1. **Determinismo.** `(dados, config, versão) → features` produz sempre o mesmo resultado, bit a bit.
2. **Causalidade.** Nenhuma feature em `t0` usa informação posterior a `t0`. Toda janela é retrospectiva.
3. **Caminho único.** O mesmo código gera features em lote e em streaming. Não existem duas implementações.
4. **Normalização causal.** Todo z-score e percentil usa janela expansiva ou rolante **estritamente anterior** a `t0`. Nunca estatística global.
5. **Tier declarado.** Toda feature tem tier. Só T1 entra no vetor de treino da V1.

| tier | significado | quantidade |
|---|---|---|
| **T1** | vetor de treino do Alpha V1 | **a medir (§2.0.1)** |
| **T2** | calculada, versionada, disponível — fora do vetor V1; candidata a ablação e V1.1 | restante |
| **T3** | definida mas bloqueada por fonte ausente ou cobertura curta | 18 |

### 2.0.1 O tamanho de T1 é medido, não estipulado

A versão anterior fixava T1 em 12 features a partir de uma amostra efetiva calculada por fórmula fechada. A fórmula estava errada e a regra de conversão é heurística (§0.2 R4). O procedimento correto:

```
Sprint 6  →  labels construídos
          →  N_eff = Σ uniqueness   (medido, não estimado)
          →  faixa candidata = [N_eff/500 , N_eff/200]

Sprint 8  →  ablação DENTRO do CPCV:
             treina com k = 6, 9, 12, 16, 24 features (ordem de importância T2)
             mede Sharpe OOS e PBO por k
             escolhe o maior k cujo PBO ainda seja < 0,30
          →  |T1| := k escolhido
          →  as 5 variantes de k CONTAM para o N_effective do DSR (§11.6)
```

**A ablação é o árbitro, não a heurística.** A faixa de `N_eff/[200…500]` serve só para limitar quais valores de `k` vale a pena testar — evita gastar orçamento de trials em `k = 60` quando a amostra claramente não sustenta.

**Lista de partida ordenada** (as 10 do §2.13 permanecem como as primeiras candidatas, por cobertura conceitual ortogonal — mas a ordem é revalidada por importância por permutação dentro de cada fold, nunca fixada a priori sobre o dataset inteiro).

**Critério de parada:** se o Sharpe OOS não crescer monotonicamente até `k = 6`, o problema não é número de features — é ausência de sinal. Nesse caso, voltar ao Gate 0 antes de adicionar features.

## 2.1 Convenção de nomes

```
{grupo}{nn}_{nome}_{parametro}_{tf}
exemplo: C03_atr_pct_20_30m
```

## 2.2 GRUPO A — Preço e retorno

| ID | nome | fórmula | fonte | lookback | TF | tier |
|---|---|---|---|---|---|---|
| A01 | `log_return_1` | `ln(C_t / C_{t−1})` | D03 | 1 | 30m | T2 |
| A02 | `log_return_2` | `ln(C_t / C_{t−2})` | D03 | 2 | 30m | T2 |
| A03 | `log_return_4` | `ln(C_t / C_{t−4})` | D03 | 4 | 30m | T2 |
| A04 | `log_return_12` | `ln(C_t / C_{t−12})` | D03 | 12 | 30m | T2 |
| **A05** | **`ret_vol_norm_4`** | `ln(C_t/C_{t−4}) / (ATR_20 × 2)` | D03 | 4+20 | 30m | **T1** |
| A06 | `ret_vol_norm_12` | `ln(C_t/C_{t−12}) / (ATR_20 × √3 × 2)` | D03 | 12+20 | 30m | T2 |
| A07 | `body_ratio` | `(C−O) / (H−L)`; 0 se `H=L` | D03 | 1 | 30m | T2 |
| A08 | `upper_wick_ratio` | `(H − max(O,C)) / (H−L)` | D03 | 1 | 30m | T2 |
| A09 | `lower_wick_ratio` | `(min(O,C) − L) / (H−L)` | D03 | 1 | 30m | T2 |
| A10 | `close_location` | `(C − L) / (H − L)` | D03 | 1 | 30m | T2 |
| A11 | `true_range_pct` | `max(H−L, |H−C_{t−1}|, |L−C_{t−1}|) / C_{t−1}` | D03 | 2 | 30m | T2 |
| A12 | `gap_pct` | `(O_t − C_{t−1}) / C_{t−1}` | D03 | 2 | 30m | T2 |
| **A13** | **`dist_ema48_atr`** | `(C_t − EMA_48) / ATR_20` | D03 | 48 | 30m | **T1** |
| A14 | `dist_ema12_atr` | `(C_t − EMA_12) / ATR_20` | D03 | 12 | 30m | T2 |
| A15 | `dist_vwap_d_atr` | `(C_t − VWAP_dia) / ATR_20` | D03 | intradiário | 30m | T2 |
| A16 | `ctx_dist_ema_2h` | `(C_t − EMA_48^{2h}) / ATR_20^{2h}` | D03 | 48 | 2h | T2 |
| A17 | `ctx_dist_ema_1d` | `(C_t − EMA_20^{1d}) / ATR_14^{1d}` | D03 | 20 | 1d | T2 |

## 2.3 GRUPO B — Momentum e reversão

| ID | nome | fórmula | fonte | lookback | TF | tier |
|---|---|---|---|---|---|---|
| **B01** | **`rsi_14`** | RSI de Wilder, escalado para [−1, 1] via `(RSI−50)/50` | D03 | 14 | 30m | **T1** |
| B02 | `rsi_48` | idem | D03 | 48 | 30m | T2 |
| B03 | `roc_12` | `(C_t − C_{t−12}) / C_{t−12}` | D03 | 12 | 30m | T2 |
| B04 | `macd_hist_norm` | `(MACD_{12,26} − sinal_9) / ATR_20` | D03 | 26+9 | 30m | T2 |
| B05 | `ema_slope_24` | `(EMA_24_t − EMA_24_{t−6}) / ATR_20` | D03 | 24+6 | 30m | T2 |
| B06 | `momentum_accel` | `ret_4 − ret_4[t−4]` normalizado por ATR | D03 | 8+20 | 30m | T2 |
| **B07** | **`efficiency_ratio_48`** | `|C_t − C_{t−48}| / Σ|C_i − C_{i−1}|` | D03 | 48 | 30m | **T1** |
| B08 | `efficiency_ratio_16` | idem, janela 16 | D03 | 16 | 30m | T2 |
| B09 | `zscore_close_48` | `(C_t − μ_48) / σ_48` | D03 | 48 | 30m | T2 |
| B10 | `stoch_k_14` | `(C − min L_14) / (max H_14 − min L_14)` | D03 | 14 | 30m | T2 |
| B11 | `bb_position_20` | `(C − MA_20) / (2 × σ_20)` | D03 | 20 | 30m | T2 |
| B12 | `ctx_rsi_2h` | RSI 14 no contexto de 2h | D03 | 14 | 2h | T2 |

## 2.4 GRUPO C — Volatilidade

| ID | nome | fórmula | fonte | lookback | TF | tier |
|---|---|---|---|---|---|---|
| C01 | `atr_20` | ATR de Wilder, absoluto | D03 | 20 | 30m | T2 |
| C02 | `atr_20_pct` | `ATR_20 / C_t` | D03 | 20 | 30m | T2 |
| C03 | `realized_vol_48` | `σ(log_return) × √48` | D03 | 48 | 30m | T2 |
| C04 | `parkinson_vol_48` | `√( Σ ln(H/L)² / (4 ln2 × n) )` | D03 | 48 | 30m | T2 |
| C05 | `garman_klass_48` | estimador GK com OHLC | D03 | 48 | 30m | T2 |
| **C06** | **`vol_ratio_12_96`** | `realized_vol_12 / realized_vol_96` | D03 | 96 | 30m | **T1** |
| **C07** | **`vol_pctile_expanding`** | posto de `realized_vol_48` na distribuição **expansiva** até `t−1` | D03 | expansiva | 30m | **T1** |
| C08 | `vol_pctile_rolling_1y` | idem, janela rolante de 1 ano | D03 | 17520 | 30m | T2 |
| C09 | `range_pctile_expanding` | posto de `true_range_pct` | D03 | expansiva | 30m | T2 |
| C10 | `vol_expansion_flag` | `1` se `vol_ratio_12_96 > q_0.80` expansivo | D03 | expansiva | 30m | T2 |
| C11 | `vol_compression_flag` | `1` se `vol_ratio_12_96 < q_0.20` expansivo | D03 | expansiva | 30m | T2 |
| C12 | `vol_of_vol_48` | `σ(realized_vol_12)` sobre 48 barras | D03 | 60 | 30m | T2 |
| C13 | `bvol_index` | índice BVOL da Binance, nível | D05 | 1 | 1d | T2 |
| C14 | `bvol_z_90d` | z-score expansivo do BVOL | D05 | 90d | 1d | T2 |
| C15 | `iv_rv_spread` | `bvol_index − realized_vol_anualizada` | D05+D03 | 48 | 1d | T2 |
| C16 | `dvol_deribit` | DVOL da Deribit | E06 | 1 | 1h | **T3** |
| C17 | `skew_25d` | skew 25 delta risk reversal | E06 | 1 | 1h | **T3** |

## 2.5 GRUPO D — Volume e fluxo de agressor

| ID | nome | fórmula | fonte | lookback | TF | tier |
|---|---|---|---|---|---|---|
| D01f | `volume_z_96` | `(V_t − μ_96) / σ_96` | D03 | 96 | 30m | T2 |
| D02f | `rel_volume_48` | `V_t / mediana(V)_48` | D03 | 48 | 30m | T2 |
| **D03f** | **`volume_z_expanding`** | z-score de `log(1+V_t)` em janela expansiva | D03 | expansiva | 30m | **T1** |
| D04f | `volume_accel` | `rel_volume_4 − rel_volume_4[t−4]` | D03 | 8 | 30m | T2 |
| D05f | `taker_buy_ratio` | `taker_buy_volume / volume` | D03 | 1 | 30m | T2 |
| **D06f** | **`taker_imbalance_z_48`** | z-score de `(2 × taker_buy_ratio − 1)` sobre 48 | D03 | 48 | 30m | **T1** |
| D07f | `taker_imbalance_1m_agg` | média de `2×tbr−1` das 30 barras de 1m dentro da barra de 30m | D03 | 30 | 1m→30m | T2 |
| D08f | `trade_count_z_48` | z-score de `number_of_trades` | D03 | 48 | 30m | T2 |
| D09f | `avg_trade_size_z` | z-score de `volume / number_of_trades` | D03 | 48 | 30m | T2 |
| D10f | `vol_price_divergence` | correlação rolante 48 de `|ret|` × `volume_z` | D03 | 48 | 30m | T2 |
| D11f | `large_trade_ratio` | fração do volume em `aggTrades` acima do percentil 99 de tamanho | D01 | 48 | 30m | T2 |
| D12f | `agg_order_flow_imb` | `(Σ vol_agressor_compra − Σ vol_agressor_venda) / Σ vol` | D01 | 1 | 30m | T2 |
| D13f | `trade_run_length` | comprimento médio de sequências do mesmo agressor | D01 | 1 | 30m | T2 |

## 2.6 GRUPO E — Futuros: funding, open interest, basis

| ID | nome | fórmula | fonte | lookback | TF | tier |
|---|---|---|---|---|---|---|
| E01f | `funding_last` | último funding liquidado | D07 | 1 | 8h→30m | T2 |
| **E02f** | **`funding_z_expanding`** | z-score expansivo de `funding_last` | D07 | expansiva | 30m | **T1** |
| E03f | `funding_cum_3d` | soma dos fundings das últimas 72h | D07 | 9 eventos | 30m | T2 |
| E04f | `funding_next_est` | `clamp(premium_index_MA + interest, ±0,05%)` — **estimativa antes do settlement** | **D11** | 480×1m | 30m | **T3→T1 após D11** |
| E05f | `time_to_funding_h` | horas até o próximo settlement | derivado | — | 30m | T2 |
| E06f | `premium_index` | nível do premium index | **D11** | 1 | 30m | T3 |
| E07f | `premium_index_z` | z-score expansivo | **D11** | expansiva | 30m | T3 |
| E08f | `oi_notional` | `sum_open_interest_value` | D04 | 1 | 5m→30m | T2 |
| E09f | `oi_contracts` | `sum_open_interest` | D04 | 1 | 5m→30m | T2 |
| **E10f** | **`oi_change_z_48`** | z-score de `Δln(oi_contracts)` sobre 48 | D04 | 48 | 30m | **T1** |
| E11f | `oi_change_1d` | `Δln(oi)` sobre 48 barras | D04 | 48 | 30m | T2 |
| E12f | `price_oi_divergence` | `sign(ret_12) × sign(oi_change_12)`, ∈ {−1,0,1} | D04+D03 | 12 | 30m | T2 |
| E13f | `oi_pctile_expanding` | posto expansivo de `oi_notional` | D04 | expansiva | 30m | T2 |
| E14f | `toptrader_ls_ratio` | `sum_toptrader_long_short_ratio` | D04 | 1 | 30m | T2 |
| E15f | `toptrader_ls_z` | z-score expansivo | D04 | expansiva | 30m | T2 |
| E16f | `global_ls_ratio` | `count_long_short_ratio` | D04 | 1 | 30m | T2 |
| E17f | `retail_vs_top_spread` | `global_ls_z − toptrader_ls_z` — proxy de posicionamento contrário | D04 | expansiva | 30m | T2 |
| E18f | `taker_ls_vol_ratio` | `sum_taker_long_short_vol_ratio` | D04 | 1 | 30m | T2 |
| **E19f** | **`basis_perp_index_bps`** | `(mark − index) / index × 10000` | **D10+D12** | 1 | 30m | **T3→T1** |
| E20f | `basis_z_expanding` | z-score expansivo do basis | D10+D12 | expansiva | 30m | T3 |
| E21f | `mark_last_divergence_bps` | `(mark − close) / close × 10000` | **D10** | 1 | 30m | T3 |
| E22f | `spot_perp_basis_bps` | `(perp_close − spot_close) / spot × 10000` | D13 | 1 | 30m | T3 |
| E23f | `quarterly_annualized_basis` | basis anualizado do trimestral vs perp | D06 | 1 | 30m | T2 |
| E24f | `funding_dispersion_venues` | desvio-padrão do funding entre Binance/Bybit/OKX/HL | E05 | 1 | 1h | T3 |
| E25f | `liq_notional_z` | z-score do nocional liquidado | F03 | 48 | 30m | T3 |
| **E27f** | **`cost_atr_ratio`** | `custo_round_trip_bps / (atr_20_pct × 10000)` | derivado | 20 | 15m | **T1** |
| E26f | `liq_side_imbalance` | `(liq_long − liq_short) / (liq_long + liq_short)` | F03 | 48 | 30m | T3 |

## 2.7 GRUPO F — Microestrutura

| ID | nome | fórmula | fonte | lookback | TF | tier |
|---|---|---|---|---|---|---|
| F01f | `spread_bps` | `(ask − bid) / mid × 10000`, média na barra | D08 | 1 | 30m | T2 |
| F02f | `spread_pctile_expanding` | posto expansivo do `spread_bps` | D08 | expansiva | 30m | T2 *(saiu de T1 na v3.3, §2.7.1)* |
| F03f | `spread_vol_ratio` | `spread_bps / (atr_20_pct × 10000)` — custo relativo à volatilidade | D08+D03 | 20 | 30m | T2 |
| F04f | `book_imbalance_l1` | `(bid_qty − ask_qty) / (bid_qty + ask_qty)` no topo | D08 | 1 | 30m | T2 *(saiu de T1 na v3.3, §2.7.1)* |
| F05f | `book_imbalance_l1_z` | z-score expansivo | D08 | expansiva | 30m | T2 |
| F06f | `book_imbalance_l5` | mesma razão somando 5 níveis | D02 | 1 | 30m | T2 |
| F07f | `book_slope_bid` | inclinação de profundidade acumulada no bid | D02 | 1 | 30m | T2 |
| F08f | `book_slope_ask` | idem no ask | D02 | 1 | 30m | T2 |
| F09f | `depth_at_20bps` | nocional disponível dentro de 20 bps do mid | D02 | 1 | 30m | T2 |
| F10f | `liquidity_cost_4units` | slippage estimado para executar 4 unidades a mercado | D02 | 1 | 30m | T2 |
| F11f | `quote_update_rate` | atualizações de `bookTicker` por minuto | D09 | 1 | 30m | T2 |
| F12f | `microprice_deviation` | `(microprice − mid) / mid × 10000` | D08 | 1 | 30m | T2 |
| F13f | `realized_spread_1m` | markout de 1 minuto após execuções | D01+D08 | 1 | 30m | T2 |
| F14f | `book_ticker_staleness_ms` | tempo desde a última atualização de cotação | D09 | 1 | 30m | T2 |

### 2.7.1 Quebra de definição em 2025-11-20 — Grupo F

Todas as features do Grupo F são calculadas de `bookTicker`/`bookDepth`, que excluem ordens RPI. Antes de 2025-11-20 isso era irrelevante (RPI não existia) e "book visível" = "book completo". Depois, não é mais.

Agravante: níveis de preço cruzados são ocultos, então RPI pode estar em preço melhor que o topo visível. Consequência direta: **o spread visível superestima o spread real no período pós-quebra.** `F02f_spread_pctile` está deslocada; `F04f_book_imbalance_l1` é razão sobre book incompleto.

Isto NÃO é mudança de regime de mercado. É mudança de definição de feature no meio da amostra — falha silenciosa por construção, e a razão de existir do check 23.

Tratamento obrigatório:

1. Adicionar coluna `rpi_regime` ∈ {PRE, POST} a todo dataset de features, fronteira em 2025-11-20T00:00:00Z.
2. Grupo F **removido de T1** até haver ≥ 6 meses de coleta forward de `rpiDepth` que permita definição consistente. T1 passa de 12 para 10 features, dentro do teto medido de N_eff (§0.2 R4).
3. `rpi_regime` entra como dimensão de ambiente na triagem de estabilidade (§5.4). Feature cuja definição mudou terá IC inconsistente entre ambientes e será penalizada por `consistência²` automaticamente — o mecanismo não precisa de exceção manual.
4. Amostra pós-quebra até 2026-08-01: 24.384 barras de 15m = **381 observações efetivas**. Insuficiente para treinar microestrutura isolada. Registrar o número, não contorná-lo.

**Alcance além de T1:** a contaminação não se limita ao vetor de treino do Alpha. Os gatilhos de stress S2 e S7 (§4.4) e o Grupo J do Meta (§2.11, V1.1) também derivam de `bookTicker`/`bookDepth` e herdam a mesma quebra de definição — carregam `rpi_regime` junto e são reavaliados quando Grupo F retornar a T1.

## 2.8 GRUPO G — Opções

| ID | nome | fórmula | fonte | tier |
|---|---|---|---|---|
| G01 | `put_call_oi_ratio` | OI de puts ÷ OI de calls | D14 | T3 |
| G02 | `put_call_volume_ratio` | volume de puts ÷ calls | D14 | T3 |
| G03 | `max_pain_dist_pct` | `(C − max_pain) / C` | D14 | T3 |
| G04 | `oi_concentration_strike` | Herfindahl do OI por strike | D14 | T3 |
| G05 | `days_to_major_expiry` | dias até o vencimento mensal/trimestral | D14 | T3 |
| G06 | `gamma_exposure_proxy` | Σ (OI × gamma) por strike | D14 | T3 |

## 2.9 GRUPO H — On-chain

| ID | nome | fonte | granularidade | tier |
|---|---|---|---|---|
| H01 | `exchange_netflow_z` | E01 | 1d | T2 |
| H02 | `exchange_balance_pct` | E01 | 1d | T2 |
| H03 | `active_addresses_z` | E01 | 1d | T2 |
| H04 | `tx_volume_usd_z` | E01 | 1d | T2 |
| H05 | `sopr` | E01 | 1d | T2 |
| H06 | `mvrv_z` | E01 | 1d | T2 |
| H07 | `nvt_ratio` | E01 | 1d | T2 |
| H08 | `hash_rate_z` | E01 | 1d | T2 |
| H09 | `miner_outflow_z` | E01 | 1d | T2 |
| H10 | `lth_supply_change` | E01 | 1d | T2 |
| H11 | `stablecoin_supply_change` | E01 | 1d | T2 |

**Aviso de granularidade:** on-chain é diário. Numa decisão a 30m, essas features são **constantes por 48 barras consecutivas**. Isso reduz a informação por observação e infla a correlação serial. São features de **contexto de regime**, não de entrada — e é por isso que nenhuma está em T1.

## 2.10 GRUPO I — Macro e fluxo institucional

| ID | nome | fonte | granularidade | tier | nota |
|---|---|---|---|---|---|
| I01 | `etf_netflow_usd_1d` | E02 | 1d | T3 | só desde 2024-01 |
| I02 | `etf_netflow_z_20d` | E02 | 1d | T3 | idem |
| I03 | `etf_flow_streak` | E02 | 1d | T3 | dias consecutivos do mesmo sinal |
| I04 | `dxy_ret_1d` | E04 | 1d | T3 | |
| I05 | `ust10y_change_bps` | E04 | 1d | T3 | |
| I06 | `real_yield_10y` | E04 | 1d | T3 | |
| I07 | `spx_ret_1d` | E04 | 1d | T3 | |
| I08 | `vix_level` | E04 | 1d | T3 | |
| I09 | `btc_spx_corr_30d` | E04+D03 | 1d | T3 | |
| I10 | `gold_ret_1d` | E04 | 1d | T3 | |

**Nota de estrutura de mercado:** o regime macro do BTC mudou depois dos ETFs à vista. Análise da Binance Research citada em abril/2026 registra que <cite index="142-1">a correlação do BTC com o índice de easing global de 41 bancos centrais inverteu de +0,21 antes da aprovação dos ETFs para −0,778 em 2026, e a hierarquia de sinal passou a ser: fluxo mensal de ETF primeiro, oferta de holders de longo prazo e reservas de exchange em segundo, regulação em terceiro e linguagem do Fed num distante quarto.</cite> Isso significa duas coisas: I01–I03 valem mais que I04–I10; e **treinar em 2020–2023 e esperar transferência para 2026 é otimista** — ver a política de janela de treino em §11.3.

## 2.11 GRUPO J — Execução (exclusivo do Meta, §6)

| ID | nome | fórmula | fonte | tier |
|---|---|---|---|---|
| J01 | `p_fill_est` | probabilidade estimada de preenchimento maker em `fill_timeout` | modelo de fila | T1-Meta |
| J02 | `dist_to_touch_bps` | distância do limite postado ao topo do book | D08 | T1-Meta |
| J03 | `queue_ahead_notional` | nocional à frente na fila no preço postado | D08/D02 | T1-Meta |
| J04 | `cost_est_bps` | custo esperado do caminho de execução previsto | derivado | T1-Meta |
| J05 | `adverse_selection_est_bps` | markout esperado condicional a preenchimento | D01+D08 | T1-Meta |

**Estas são a razão de existir do Meta.** São as únicas features que o Alpha **não vê por construção** — o que satisfaz a restrição de marginalidade (§6.4).

## 2.12 GRUPO K — Temporal e calendário

| ID | nome | fórmula | tier |
|---|---|---|---|
| K01 | `hour_sin` / `hour_cos` | codificação cíclica da hora UTC | T2 |
| K02 | `dow_sin` / `dow_cos` | codificação cíclica do dia da semana | T2 |
| K03 | `is_weekend` | sábado ou domingo UTC | T2 |
| K04 | `session_asia` / `_europe` / `_us` | sessão dominante | T2 |
| K05 | `hours_to_funding` | ver E05f | T2 |
| K06 | `is_event_window` | dentro de ±2h de FOMC/CPI/NFP | **T3 — gatilho de Risk, não feature** |
| K07 | `hours_to_major_expiry` | horas até o vencimento de opções | T3 |
| K08 | `days_since_halving` | determinístico | T2 |

## 2.13 O vetor T1 — as 10 features do Alpha V1

| # | ID | grupo | conceito coberto |
|---|---|---|---|
| 1 | `A05_ret_vol_norm_4` | preço | momentum curto normalizado por volatilidade |
| 2 | `A13_dist_ema48_atr` | preço | posição relativa à tendência |
| 3 | `B01_rsi_14` | momentum | exaustão / reversão |
| 4 | `E27f_cost_atr_ratio` | futuros | **degradação econômica do regime** (substitui `B07`) |
| 5 | `C06_vol_ratio_12_96` | volatilidade | expansão / compressão |
| 6 | `C07_vol_pctile_expanding` | volatilidade | regime de volatilidade |
| 7 | `D03f_volume_z_expanding` | volume | intensidade de participação |
| 8 | `D06f_taker_imbalance_z_48` | fluxo | pressão de agressor |
| 9 | `E02f_funding_z_expanding` | futuros | custo de carrego e posicionamento |
| 10 | `E10f_oi_change_z_48` | futuros | construção vs liquidação de posição |

**Removidas na v3.3:** as duas features de microestrutura (`F02f_spread_pctile_expanding`, `F04f_book_imbalance_l1`) saem por quebra de definição em 2025-11-20 (§2.7.1), não por desempenho. Retornam quando a coleta forward de `rpiDepth` (F06) permitir definição consistente. O tamanho final de T1 continua sendo decidido por ablação (§2.0.1), não por esta remoção.

**Por que `B07_efficiency_ratio_48` saiu de T1:** IC medido de **+0,042 em 2024 e −0,031 em 2026**, com sinal consistente em apenas 57% dos anos (§17.2). Inverte de sinal entre regimes. **Permanece como eixo de partição de regime** (§4.2) — descrever "quão tendencial está o mercado" não exige estabilidade de sinal; prever direção a partir disso, sim. `C06_vol_ratio_12_96` e `D03f_volume_z` estão sob a mesma suspeita (57%) e permanecem em T1 apenas até a primeira triagem de estabilidade in-fold (§5.4) decidir.

**Por que `E27f_cost_atr_ratio` entrou:** é a única variável que mudou estruturalmente entre 2021 e 2026 (custo/ATR de 11,0% para 19,4%, §17.1) e o blueprint não a tinha. Barreiras escalam com ATR e adaptam ao regime; custos são fixos em bps e não adaptam. Sem esta feature, o modelo teria que inferir indiretamente a degradação econômica que ela expressa diretamente.

Mais o **regime** (§4) como variável categórica, entrando como one-hot de 5 níveis — o que consome mais 4 graus de liberdade e é o motivo de T1 ficar em 10 e não em 14.

**Critério de ortogonalidade:** nenhum par em T1 pode ter `|correlação de Spearman| > 0,70` na janela de treino. Verificado no Sprint 4 e a cada rebuild de features. Par que violar → o de menor importância por permutação sai e o próximo T2 candidato entra.

**Promoção T2 → T1** só é permitida por ablação dentro do CPCV, e **cada promoção testada conta para o `N` do DSR** (§11.6).

## 2.14 Feature Registry

Toda feature, em qualquer tier, tem entrada obrigatória em `features/registry_v{n}.yaml`:

```yaml
- id: C07_vol_pctile_expanding
  tier: T1
  group: C
  formula: "rank(realized_vol_48[t]) sobre distribuição expansiva em [t0_dataset, t-1]"
  sources: [D03]
  lookback_bars: expanding
  min_warmup_bars: 2000
  tf: 30m
  dtype: float64
  range: [0.0, 1.0]
  nan_policy: "drop até warmup completo"
  causal_proof: "quantil calculado apenas sobre índices < t"
  parity_tested: true
  version: v1
  added: 2026-08-08
```

## 2.15 INVARIANTES do Feature Engine

```python
# 1. Causalidade: nenhuma feature enxerga além de t0
assert features.index.max() <= bars.loc[t0, "close_time"]

# 2. Sem normalização global
assert "global_mean" not in scaler_state      # scaler é expansivo ou por fold

# 3. Determinismo
assert hash(build(data, cfg, v1)) == hash(build(data, cfg, v1))

# 4. Paridade lote ↔ streaming
assert max(abs(batch_features[-500:] - stream_features[-500:])) < 1e-8

# 5. Warmup respeitado
assert features.iloc[:min_warmup].isna().all()

# 6. Ortogonalidade T1
assert spearman_corr(T1).abs().max(where=off_diagonal) <= 0.70

# 7. Cobertura
assert all(coverage_start[f] <= train_start for f in T1)
```

**A invariante 4 é a mais cara e a mais importante.** Sem ela, o modelo treina numa distribuição e opera em outra, e o sintoma no live parece decaimento de edge quando é bug de implementação.

---

# PARTE III — LABEL ENGINE

## 3.1 Âncoras temporais

Cada observação carrega quatro timestamps. O PRD V2 só nomeava um.

| símbolo | definição |
|---|---|
| `t0` | fechamento da barra de 30m. Momento em que as features congelam e a decisão é tomada |
| `t_post` | `t0 + latência_decisão`. Momento em que a ordem limite é postada |
| `t_entry` | preenchimento efetivo da entrada. **Null se não preenchida** |
| `t1` | toque de barreira ou time stop. **A coluna mais importante do dataset** |
| `t_exit` | preenchimento efetivo da saída |

Sob execução maker, `t_entry` **não é determinístico**. Isso cria um quarto desfecho que o triple barrier clássico não tem.

## 3.2 Os quatro desfechos

| label | `barrier_hit` | significado |
|---|---|---|
| `+1` | `TP` | barreira superior tocada primeiro |
| `0` | `TIME` | nenhuma barreira tocada dentro de `time_stop` |
| `−1` | `SL` | barreira inferior tocada primeiro |
| `−2` | `NOFILL` | ordem postada, nunca preenchida, cancelada no timeout |

`−2` não é contabilidade. É informação de primeira classe: sob maker, parte do trabalho do sistema é decidir se vale postar, e "eu seria preenchido?" é parte da pergunta.

## 3.3 INPUT

```yaml
bars_30m:        OHLCV no TF de decisão
mark_1m:         série de mark price em 1m          # D10 — obrigatória
funding_events:  timestamps e taxas reais
atr_20:          volatilidade causal em t0
filters_asof:    step_size, min_notional válidos na data da barra
fill_model:      p_fill(t_post, limit_price) → (t_entry | NOFILL)
config:
  tp_atr_mult:      2.0         # ⚠️ herdado do V2, sem base — varrer (§16.10)
  sl_atr_mult:      1.5         # ⚠️ idem
  time_stop_bars:   32          # 8h a 15m — uma janela de funding
  execution_path:   maker_in__maker_tp__taker_sl
  fill_timeout_bars: 1
```

**Por que `time_stop = 16` e não 96:** 96 barras de 30m são 48 horas, o que reduziria a amostra efetiva para 903 observações e o teto de features para 2 a 5. Com 16 barras (8 horas), a concorrência é `1 + (2×16 − 1) = 32`, a amostra efetiva é 3.240 e o teto sobe para 7–16 features. E 8h coincide exatamente com uma janela de funding, o que torna `n_funding_events` quase sempre 1 ou 2 e simplifica a atribuição de custo de carrego.

## 3.4 PROCESSO

**Regra dura nº 1 — barreiras avaliadas sobre `mark_1m`, nunca sobre high/low da barra de 30m.**

Dois motivos, ambos decisivos:
1. A Binance dispara stop-loss e liquidação **pelo mark price**. Avaliar no last price simula um trade que não é o seu.
2. Numa barra de 30m que tocou TP **e** SL, o high/low não diz qual veio primeiro. A convenção escolhida silenciosamente enviesa o label. A 30m com ATR de 0,272% e barreiras a 0,544%/0,408%, isso acontece com frequência alta o bastante para inflar o backtest sozinho.

```python
for t0 in bars.index:
    entry_ref  = bars.loc[t0, "close"]
    limit_px   = round_to_tick(entry_ref, side, filters_asof(t0))
    t_entry, fill_px = fill_model(t_post, limit_px, timeout=fill_timeout_bars)

    if t_entry is None:
        emit(label=-2, barrier_hit="NOFILL", t1=t_post + timeout, ret=0.0)
        continue

    tp = fill_px * (1 + side * tp_atr_mult * atr_pct)
    sl = fill_px * (1 - side * sl_atr_mult * atr_pct)
    horizon_end = t0 + time_stop_bars * bar_duration

    path = mark_1m[t_entry : horizon_end]          # granularidade de 1 minuto
    hit  = first_touch(path, tp, sl, side)          # ordem cronológica real

    t1, barrier, exit_px = resolve(hit, horizon_end, path)
    ...
```

**Regra dura nº 2 — `config_hash` do label DEVE bater com o da execução.**
Se o label foi gerado com TP 2,5×ATR e o Risk Engine executa com 2,0×ATR, o modelo aprendeu sobre um trade que você não faz. Teste de CI que quebra o build, não item de checklist.

**Regra dura nº 3 — custo atribuído pelo caminho real, não por média.**

```python
c_entry = MAKER if t_entry is not None else 0
c_exit  = MAKER if barrier == "TP" else TAKER     # SL e TIME saem a mercado
funding = sum(rate * notional * side for rate in funding_in(t_entry, t1))
ret_net = ret_gross - c_entry - c_exit - funding/notional
```

## 3.5 OUTPUT — `labels/{version}/labels.parquet`

| coluna | tipo | descrição |
|---|---|---|
| `t0` | `datetime64[ns, UTC]` | PK — fechamento da barra de decisão |
| `t_post` | `datetime64[ns, UTC]` | postagem da ordem |
| `t_entry` | `datetime64[ns, UTC]` | preenchimento; null se NOFILL |
| `t1` | `datetime64[ns, UTC]` | **toque de barreira ou time stop — insumo de purge** |
| `t_exit` | `datetime64[ns, UTC]` | preenchimento da saída |
| `side` | `int8` | lado avaliado: −1 / 0 / +1 |
| `label` | `int8` | +1 / 0 / −1 / −2 |
| `barrier_hit` | `category` | TP · SL · TIME · NOFILL |
| `entry_price_limit` | `float64` | limite postado |
| `entry_price_fill` | `float64` | preenchimento efetivo |
| `tp_price` | `float64` | |
| `sl_price` | `float64` | |
| `exit_price` | `float64` | |
| `ret_gross` | `float64` | retorno bruto de `t_entry` a `t1` |
| `cost_entry_bps` | `float64` | |
| `cost_exit_bps` | `float64` | |
| `funding_bps` | `float64` | funding atravessado, sinalizado pelo lado |
| `adverse_selection_bps` | `float64` | markout pós-fill, ver §9.5 |
| `ret_net` | `float64` | **líquido de tudo — o número que o backtest tem que reproduzir** |
| `atr_at_t0` | `float64` | volatilidade que dimensionou as barreiras |
| `n_bars_held` | `int16` | |
| `n_funding_events` | `int8` | |
| `concurrency` | `int16` | quantos labels se sobrepõem a este |
| `uniqueness` | `float64` | `1 / concurrency` médio no intervalo |
| `sample_weight` | `float64` | `uniqueness × |ret_net|`, normalizado para média 1 |
| `filters_hash` | `str` | filtros de instrumento vigentes na data |
| `config_hash` | `str` | hash do bloco de barreiras |

## 3.6 Distribuição esperada e critério de sanidade

Com TP 2,0×ATR, SL 1,5×ATR e `time_stop` 16 barras, a distribuição esperada é aproximadamente:

| desfecho | faixa esperada | ação se fora |
|---|---|---|
| `TP` | 30–40% | fora da faixa → recalibrar multiplicadores |
| `SL` | 35–45% | |
| `TIME` | 20–30% | > 40% ⟹ barreiras largas demais para o horizonte |
| `NOFILL` | 10–25% | > 35% ⟹ política de postagem agressiva demais |

Estes números não são metas. São **detectores de configuração errada**: um `TIME` de 60% significa que o horizonte não alcança as barreiras e o label perde poder discriminante.

## 3.7 CONSUMIDORES

| consumidor | consome | restrição |
|---|---|---|
| Alpha (treino) | `label`, `sample_weight`, `t1` | **descarta `NOFILL`** — é ruído de execução, não sinal direcional |
| Meta (treino) | `label_meta` derivado, `t1`, `sample_weight` | **mantém `NOFILL`** — para o Meta é informação |
| Splitter CPCV | `t0`, `t1` | único uso legítimo de informação futura no pipeline |
| Backtest (reconciliação) | `ret_net`, `barrier_hit` | tolerância declarada; divergência = bug em um dos dois |
| DSR / bootstrap | sequência de `ret_net` | |
| Dashboard | distribuição de `barrier_hit` | fração de `NOFILL` é o KPI da execução maker |

**Ninguém mais lê `labels/`.** Feature Engine, Regime Engine e Decision Engine não têm acesso a este diretório — restrição de import verificada estaticamente.

## 3.8 INVARIANTES

```python
assert (labels.t1 > labels.t0).all()
assert (labels.t_entry.isna() == (labels.barrier_hit == "NOFILL")).all()
assert labels.config_hash.nunique() == 1
assert labels.config_hash.iloc[0] == execution_config_hash
assert abs(labels.sample_weight.mean() - 1.0) < 1e-6
assert (labels.n_bars_held <= time_stop_bars).all()
assert labels.uniqueness.between(0, 1).all()
```

---

# PARTE IV — REGIME ENGINE

## 4.1 Por que o HMM de 8 estados do V2 sai

O PRD V2 definia 8 estados (`TREND_BULL`, `TREND_BEAR`, `MEAN_REVERSION`, `HIGH_VOLATILITY`, `LOW_VOLATILITY`, `COMPRESSION`, `CHAOTIC`, `UNKNOWN`) sobre um HMM. Quatro problemas:

1. **Amostra.** 8 estados × matriz de transição 8×8 × emissões gaussianas multivariadas = ordem de 100 parâmetros, sobre 3.240 observações efetivas.
2. **Estados não ortogonais.** `TREND_BULL` e `HIGH_VOLATILITY` não são mutuamente exclusivos — são eixos diferentes forçados numa dimensão só.
3. **Label switching.** Retreinos sucessivos devolvem estados em ordem arbitrária. O `TREND_BULL` do `hmm_v1` pode virar outra coisa no `hmm_v2` sem que nada quebre visivelmente.
4. **Causalidade frágil.** Um HMM ajustado sobre a série inteira e depois "predito" barra a barra é vazamento — e é sutil porque o `.predict()` parece causal enquanto o `.fit()` não foi.

**Decisão V3:** regime determinístico por quantis expansivos como primário. HMM (via `dynamax`, não `hmmlearn`) fica para a V1.1, como camada de suavização sobre o classificador determinístico, nunca como substituto.

## 4.2 Os dois eixos

**Eixo 1 — Estrutura**, medido por `B07_efficiency_ratio_48`:

```
ER_48 = |C_t − C_{t−48}| / Σ_{i=t−47}^{t} |C_i − C_{i−1}|
```
ER próximo de 1 = movimento direcional eficiente. ER próximo de 0 = vaivém.

**Eixo 2 — Volatilidade**, medido por `C07_vol_pctile_expanding`.

Ambos os cortes usam **quantis expansivos** calculados apenas sobre índices `< t`. Nunca quantil global.

## 4.3 Os cinco regimes canônicos

| ID | nome | condição | interpretação | tradeável |
|---|---|---|---|---|
| `R0` | `WARMUP` | `t < min_warmup` (2.000 barras) | quantis ainda não confiáveis | **não** |
| `R1` | `RANGE_LOW_VOL` | `ER < q60(ER)` **e** `vol_pct < 0,70` | lateral calmo — território de reversão à média | sim |
| `R2` | `RANGE_HIGH_VOL` | `ER < q60(ER)` **e** `vol_pct ≥ 0,70` | vaivém violento — pior cenário para stop apertado | sim, com cautela |
| `R3` | `TREND_LOW_VOL` | `ER ≥ q60(ER)` **e** `vol_pct < 0,70` | tendência ordenada — território de rompimento | sim |
| `R4` | `TREND_HIGH_VOL` | `ER ≥ q60(ER)` **e** `vol_pct ≥ 0,70` | tendência com expansão — melhor payoff, pior slippage | sim |
| `R5` | `STRESS` | qualquer gatilho de §4.4 | mercado disfuncional | **não — bloqueia entrada** |

`R5` tem precedência sobre todos os outros.

**Direção é separada do regime.** O V2 embutia direção em `TREND_BULL` / `TREND_BEAR`. Isso duplica estados sem adicionar informação, porque a direção já está em `A13_dist_ema48_atr` e `A05_ret_vol_norm_4`, que estão em T1. O regime descreve o **tipo de mercado**; o Alpha decide o lado.

**Mapeamento dos 8 estados do V2:**

| estado V2 | destino V3 |
|---|---|
| `TREND_BULL` | `R3`/`R4` + sinal de `A13` |
| `TREND_BEAR` | `R3`/`R4` + sinal de `A13` |
| `MEAN_REVERSION` | `R1` |
| `HIGH_VOLATILITY` | `R2`/`R4` |
| `LOW_VOLATILITY` | `R1`/`R3` |
| `COMPRESSION` | `R1` + `C11_vol_compression_flag` como feature |
| `CHAOTIC` | `R5` |
| `UNKNOWN` | `R0` |

## 4.3.1 Terceiro eixo — regime econômico

Os dois eixos de §4.2 (estrutura e volatilidade) descrevem o **mercado**. Falta o eixo que descreve a **viabilidade econômica** do mercado para esta conta:

```yaml
regime_economico:                       # eixo ortogonal, quantis expansivos
  ECONOMICS_FAVORABLE:  cost_atr_ratio <  p33 expansivo
  ECONOMICS_NEUTRAL:    p33 <= cost_atr_ratio < p66
  ECONOMICS_HOSTILE:    cost_atr_ratio >= p66
```

Valores históricos anuais de `cost/ATR` (§17.1): 2021 = 11,0% · 2023 = 19,9% · 2026 = 19,4%. O eixo teria classificado 2021 como favorável e 2023/2026 como hostil — **e é economicamente motivado em vez de estatisticamente ajustado**.

**Uso duplo:** (a) terceira dimensão dos ambientes de treino do Alpha (§5.4, 6 células = tercil × regime estrutural); (b) gate operacional no Gate 0 contínuo (§16.11), bloqueando entrada acima de `cost_atr_max`.

## 4.4 Gatilhos de STRESS (R5)

Qualquer um dispara. Todos usam quantis expansivos, exceto os absolutos.

| # | gatilho | limiar | fonte |
|---|---|---|---|
| S1 | volatilidade extrema | `vol_pctile_expanding > 0,98` | C07 |
| S2 | spread extremo | `spread_pctile_expanding > 0,95` | F02f |
| S3 | funding extremo | `|funding_z| > 3,0` | E02f |
| S4 | basis rompido | `|basis_perp_index_bps| > 100` | E19f |
| S5 | dado velho | `bar_staleness > 90s` ou `book_staleness > 5s` | F14f |
| S6 | gap de barra | ausência de barra na grade | RF-003 |
| S7 | liquidez rasa | `depth_at_20bps < 4 × unit_notional` | F09f |
| S8 | janela de evento | `is_event_window == 1` (±2h de FOMC/CPI/NFP) | K06 |
| S9 | cascata de liquidação | `liq_notional_z > 4,0` | E25f |
| S10 | mudança de filtro | `filters_hash` mudou nas últimas 24h | F01 |

**S8 e S10 não são features — são bloqueios operacionais.** S10 existe porque uma mudança de `MIN_NOTIONAL` ou `LOT_SIZE` invalida o dimensionamento até que o Risk Engine recarregue e revalide.

## 4.5 Persistência e histerese

Regime que oscila a cada barra é ruído. Duas defesas:

1. **Confirmação:** mudança de regime só é efetivada após 2 barras consecutivas na nova condição.
2. **Histerese nos cortes:** entrada em `HIGH_VOL` exige `vol_pct > 0,70`; saída exige `vol_pct < 0,65`. Idem para `ER`: entrada em TREND com `q60`, saída com `q55`.

Exceção: `R5 STRESS` entra **imediatamente**, sem confirmação, e sai com 4 barras de confirmação. Assimetria deliberada — errar para o lado de não operar.

## 4.6 OUTPUT — `regimes/{version}/regimes.parquet`

| coluna | tipo | descrição |
|---|---|---|
| `t0` | `datetime64[ns, UTC]` | PK |
| `regime` | `category` | R0…R5 |
| `regime_raw` | `category` | antes de confirmação/histerese |
| `er_48` | `float64` | |
| `er_quantile` | `float64` | posto expansivo |
| `vol_pctile` | `float64` | |
| `bars_in_regime` | `int16` | persistência atual |
| `stress_triggers` | `list[str]` | quais gatilhos estão ativos |
| `tradeable` | `bool` | |
| `engine_version` | `str` | |

## 4.7 CONSUMIDORES

| consumidor | uso |
|---|---|
| Alpha | `regime` como one-hot de 5 níveis no vetor de entrada |
| Risk Engine | `tradeable` como veto duro; `R5` ⟹ `REJECTED` sem consultar modelo |
| Backtest | estratificação de métricas por regime — **obrigatória** |
| Dashboard | regime atual, persistência, gatilhos ativos |
| Validação | CPCV verifica cobertura de regime por fold (§11.4) |

## 4.8 INVARIANTES

```python
assert regimes.regime.isin(["R0","R1","R2","R3","R4","R5"]).all()
assert (regimes.tradeable == regimes.regime.isin(["R1","R2","R3","R4"])).all()
assert regimes.loc[regimes.regime == "R5", "tradeable"].eq(False).all()
# quantis são causais
assert quantile_source_indices.max() < t                 # nenhum índice >= t
# confirmação respeitada
assert (regimes.bars_in_regime >= 2) | (regimes.regime == "R5")
```

---

# PARTE V — ALPHA MODEL

## 5.0 O problema: concentração de features sob mudança de regime

O XGBoost otimiza perda **dentro da janela de treino**. Isso cria uma patologia específica que a medição de IC (§17) torna concreta:

| feature | IC 2022 | IC 2023 | IC 2024 | IC 7 anos | consistência |
|---|---|---|---|---|---|
| `rsi_14` | −0,041 | **−0,064** | −0,007 | −0,023 | 86% |
| `zscore_close_48` | −0,046 | −0,046 | −0,000 | −0,019 | 86% |
| `taker_imb_z_48` | −0,011 | −0,021 | −0,006 | −0,012 | **100%** |

Um modelo treinado em 2022–2023 vê `rsi_14` com IC três vezes acima da média histórica dela. O boosting guloso vai concentrar capacidade ali. Em 2024, esse IC cai sete vezes e **a feature dominante do modelo morre**.

Enquanto isso, `taker_imb_z_48` nunca é espetacular — oscila entre −0,006 e −0,021 — mas **nunca falha**. O XGBoost sistematicamente prefere a feature barulhenta e instável à quieta e estável, porque o objetivo é perda na janela, não estabilidade entre regimes.

**`colsample_bytree: 0.8` não resolve.** Amostragem aleatória de colunas significa que 80% das árvores ainda veem `rsi_14`, e essas árvores vão dividir nela. Amostrar ao acaso não cria diversidade conceitual — cria repetição com ruído.

## 5.1 Decisão: manter o XGBoost, trocar o andaime

**Não substituir o learner.** Duas evidências:

<cite index="37-1">Ensembles de árvores com gradient boosting como o XGBoost continuam superando outros modelos de aprendizado de máquina em dados tabulares.</cite> E o caminho alternativo mais óbvio decepciona: <cite index="24-1">variantes de IRM demonstraram incapacidade de superar consistentemente modelos ERM bem ajustados, com um trade-off entre acurácia dentro e fora da distribuição — os modelos treinados por IRM sacrificaram acurácia in-distribution para obter melhora OOD sem de fato capturar features invariantes.</cite>

**O problema mora no objetivo e na amostragem, não no learner.** Substituir XGBoost por rede neural, IRM ou modelo linear troca um conjunto de patologias por outro sem atacar a causa. A solução é um andaime de cinco camadas em volta dele.

## 5.2 Arquitetura: dois modelos binários, não um multiclasse

O V3.0 usava `multi:softprob` com 3 classes. Isso impede restrições monotônicas, que são a camada 1 e a mais barata de todas.

```
M_long  : P(TP antes de SL | side = +1)
M_short : P(TP antes de SL | side = −1)

side_hat = +1  se p_long  > tau e p_long  > p_short
         = −1  se p_short > tau e p_short > p_long
         =  0  caso contrário
```

Três ganhos além das restrições monotônicas:

1. **Assimetria long/short vira explícita.** O carry estrutural (§16.6) afeta shorts e longs de forma diferente; um modelo único de 3 classes mistura isso na softmax.
2. **O label do Meta fica trivial** — já é binário e já é "o lado escolhido deu certo".
3. **Calibração isotônica funciona direto** em saída escalar, sem a gambiarra de calibrar softmax multiclasse.

## 5.3 Camada 1 — Restrições monotônicas por sinal medido

`monotone_constraints` do XGBoost força a dependência parcial a ser monótona na feature. Isso **impede fisicamente** que o modelo aprenda uma relação de sinal invertido por ruído local.

```python
monotone_constraints = {
    "A05_ret_vol_norm_4":      -1,   # reversão: IC negativo em 7/7 anos
    "D06f_taker_imbalance_z":  -1,   # contrário: IC negativo em 7/7 anos
    "B01_rsi_14":              -1,   # IC negativo em 6/7
    "E27f_cost_atr_ratio":     -1,   # custo alto piora tudo — economicamente forçado
    # sem restrição (sinal instável ou desconhecido):
    "A13_dist_ema48_atr":       0,
    "C06_vol_ratio_12_96":      0,
    "C07_vol_pctile_expanding": 0,
    "E02f_funding_z":           0,
    "E10f_oi_change_z":         0,
}
```

**v3.3:** `F02f_spread_pctile` e `F04f_book_imbalance_l1` saíram desta lista porque saíram de T1 (§2.7.1, §2.13) — Grupo F tem definição quebrada desde 2025-11-20 e não é insumo do Alpha até a coleta forward de `rpiDepth` sustentar redefinição. Se e quando retornarem a T1, `spread_pctile` recupera a restrição `-1` por argumento econômico (linha abaixo).

**Regra de atribuição — e aqui mora a armadilha:** a restrição só é atribuída se o sinal do IC for consistente em **≥ 6 de 7 ambientes calculados DENTRO DA JANELA DE TREINO**.

> ⚠️ **A tabela de IC do §17 cobre 2020–2026 e NÃO pode ser usada para atribuir restrições.** Usá-la para configurar um modelo treinado em 2020–2022 é vazamento de horizonte — a restrição carregaria informação de 2026. A triagem roda in-fold, sempre.

`cost_atr_ratio` recebe `−1` por **argumento econômico**, não estatístico: custo alto não pode melhorar o resultado esperado de um trade; isso é identidade contábil, não padrão aprendido. Restrições assim são as mais valiosas porque não gastam grau de liberdade. `spread_pctile` era a segunda exceção do mesmo tipo até a v3.2; saiu da lista na v3.3 porque `F02f_spread_pctile` saiu de T1 (§2.7.1) — quando Grupo F retornar, a restrição `−1` por argumento econômico volta junto, sem precisar de nova triagem estatística.

## 5.4 Camada 2 — Triagem de estabilidade entre ambientes (in-fold)

Ambientes = **tercil de `cost_atr_ratio` × regime estrutural**, seis células. Não usar "ano": ano não é partição econômica e confunde ciclo de preço com estado de mercado.

**v3.3 — `rpi_regime` como dimensão adicional de ambiente.** Desde a quebra de definição de 2025-11-20 (§2.7.1), toda feature candidata a T1 é também avaliada com `rpi_regime` ∈ {PRE, POST} cruzando as seis células acima. Uma feature cuja definição mudou no meio da amostra terá IC inconsistente entre PRE e POST e é penalizada por `consistência²` como qualquer outra inconsistência de ambiente — sem exceção manual.

```python
def stability_screen(X_train, y_train, envs_train):
    for f in features:
        ic = {e: spearman(X_train[f][envs_train==e], y_train[envs_train==e])
              for e in envs}
        sinal_dominante = sign(mean(ic.values()))
        consistencia    = mean([sign(v) == sinal_dominante for v in ic.values()])
        forca           = mean([abs(v) for v in ic.values()])
        estabilidade[f] = forca * consistencia**2      # penaliza inconsistência
    return [f for f in features if estabilidade[f] >= limiar]
```

O expoente 2 na consistência é deliberado: uma feature com IC forte e 60% de consistência (`efficiency_ratio_48`) perde para uma com IC modesto e 100% (`taker_imb_z_48`). É a inversão exata da preferência natural do boosting.

**`limiar` é constante classe A** — varrer, não escolher (§18).

## 5.5 Camada 3 — Bagging estruturado por grupo conceitual

Substitui `colsample_bytree` aleatório. Em vez de sortear 80% das colunas, treinar **K modelos, cada um vendo no máximo uma feature por grupo conceitual**:

```yaml
grupos_conceituais:
  preco:            [A05, A13]
  momentum:         [B01, B07]
  volatilidade:     [C06, C07]
  volume_fluxo:     [D03f, D06f]
  futuros:          [E02f, E10f, E27f]
  # microestrutura: [F02f, F04f]   # suspenso na v3.3 — Grupo F fora de T1, §2.7.1

bagging:
  n_modelos: 12
  regra: exatamente 1 feature de cada grupo por modelo
  agregacao: media das probabilidades calibradas
  diversidade_minima: nenhum par de modelos compartilha > 3 features
```

Isso força **diversidade conceitual por construção**. Se `rsi_14` for a feature dominante da janela, ela aparece em no máximo metade dos modelos — os outros são obrigados a encontrar sinal em `B07` ou em nada. O ensemble não pode colapsar num único preditor.

## 5.6 Camada 4 — DoubleEnsemble

<cite index="41-1">DoubleEnsemble é um framework de ensemble que usa reponderação de amostras baseada em trajetória de aprendizado e seleção de features baseada em embaralhamento, identificando amostras-chave pela dinâmica de treino e features-chave pelo impacto de ablação via shuffling, aplicável a uma gama de modelos-base e capaz de extrair padrões complexos mitigando sobreajuste e instabilidade na previsão de mercados financeiros.</cite> <cite index="39-1">Foi desenhado para resolver simultaneamente o problema de baixa razão sinal-ruído e o de número crescente de features</cite> — exatamente as duas condições deste projeto.

O mecanismo de seleção é o oposto de importância por ganho: <cite index="45-1">uma feature é considerada importante quando sua eliminação via embaralhamento aumenta significativamente as perdas nas amostras; para robustez contra g-values extremos, as features são divididas em bins segundo o g-value e amostradas de bins diferentes com taxas distintas.</cite>

E a reponderação: <cite index="44-1">a reponderação baseada em trajetória de aprendizado atribui pesos diferentes a amostras com dificuldades diferentes, sendo particularmente adequada a dados de mercado ruidosos e irregulares.</cite>

```yaml
double_ensemble:
  base_model: xgboost                    # camadas 1-3 ativas no base
  n_iteracoes: 6
  sample_reweight:
    metodo: learning_trajectory
    bins: 10
  feature_select:
    metodo: shuffling
    bins: 5
    taxas_por_bin: [0.9, 0.7, 0.5, 0.3, 0.1]
  peso_final: sample_weight(label) x w_trajetoria x w_similaridade(§11.3.1)
```

Implementação de referência disponível no `microsoft/qlib`, `examples/benchmarks/DoubleEnsemble`.

## 5.7 Camada 5 — Otimização robusta por ambiente (Group DRO)

Minimizar a perda do **pior ambiente**, não a média. É o que impede "funciona em 5 dos 6 regimes e destrói a conta no sexto".

A formulação teórica é V-REx, e a escolha é deliberada: <cite index="22-1">V-REx substitui o penalizador de gradiente do IRM por minimização de variância sobre os riscos dos ambientes, o que é mais estável na prática; otimização distribucionalmente robusta oferece uma perspectiva relacionada ao otimizar desempenho de pior caso sobre conjuntos de incerteza.</cite>

O XGBoost não aceita penalidade customizada de variância entre grupos, mas o efeito é obtido por **reponderação iterativa**, que ele aceita:

```python
w_env = {e: 1/6 for e in envs}                  # 6 ambientes
for it in range(n_dro_iter):                     # 5
    fit(model, X, y, sample_weight = w_amostra * w_env[env(i)])
    L = {e: loss(model, X[env==e], y[env==e]) for e in envs}
    w_env = softmax(log(w_env) + eta * L)        # sobe peso do pior ambiente
    w_env = normalize(clip(w_env, 0.05, 0.40))   # nenhum ambiente domina
```

O `clip` importa: sem ele, um ambiente com poucas amostras e perda alta captura todo o peso e o DRO vira sobreajuste ao pior caso.

## 5.8 Diagnóstico de concentração — novo gate

Sem métrica, nada disso é verificável.

```python
gain = model.get_score(importance_type="total_gain")
share = normalize(gain)
HHI = sum(s**2 for s in share.values())          # Herfindahl
```

| métrica | limiar | interpretação |
|---|---|---|
| HHI de importância | **< 0,25** | com 10 features, HHI uniforme = 0,10; 0,25 ≈ 4 features efetivas |
| maior share individual | **< 0,30** | nenhuma feature manda sozinha |
| features com share > 1% | **≥ 6** | o modelo usa o espaço que recebeu |
| deriva de HHI entre janelas WF | **< 0,10** | o modelo não muda de "personalidade" a cada retreino |

**Gate 3 recebe estes quatro critérios.** Um modelo com HHI de 0,45 pode ter Sharpe excelente na janela e é rejeitado — porque a próxima mudança de regime o mata, e o walk-forward não vai ter janelas suficientes para provar isso a tempo.

## 5.9 Onde cada peça treina e aplica — cronograma completo

**Este é o quadro que responde "em quais períodos ele vai treinar e o meta vai aplicar".**

```
Série completa:  2020-01-01 .. 2026-07-31   (230.784 barras de 15m)

WALK-FORWARD ANCORADO
  janela 1:  treino 2020-01..2022-12  →  OOS 2023-Q1
  janela 2:  treino 2020-01..2023-03  →  OOS 2023-Q2
  ...
  janela 14: treino 2020-01..2026-03  →  OOS 2026-Q2/Q3
```

Dentro de **cada** janela de treino, na ordem:

| # | passo | escopo | produz |
|---|---|---|---|
| 1 | rotular ambientes | só treino | `env ∈ {1..6}` = tercil custo/ATR × regime |
| 2 | triagem de estabilidade (§5.4) | só treino | subconjunto de features + sinais |
| 3 | atribuir restrições monotônicas (§5.3) | só treino | `monotone_constraints` |
| 4 | pesos: unicidade × retorno × similaridade | só treino | `sample_weight` |
| 5 | CPCV interno, 6 grupos, purge por `t1` | só treino | folds |
| 6 | treinar 12 modelos com bagging por grupo (§5.5) | por fold | ensemble |
| 7 | DoubleEnsemble, 6 iterações (§5.6) | por fold | pesos e features refinados |
| 8 | Group DRO, 5 iterações (§5.7) | por fold | pesos de ambiente |
| 9 | calibração isotônica | sub-split interno do fold | `calibrator` |
| 10 | **predições OOF** do Alpha | test de cada fold | `is_oof = True` |
| 11 | **treinar Meta** apenas nas linhas OOF onde `side_hat ≠ 0` | só treino | `M_meta` |
| 12 | congelar tudo | — | artefato versionado |

Depois, **aplicação no trimestre OOS**:

| componente | entrada | aplica em |
|---|---|---|
| Feature Engine | barras até `t0` | toda barra do OOS |
| Regime Engine | quantis expansivos até `t0` | toda barra |
| Gate 0 contínuo | preço, ATR, custo | toda barra |
| **Alpha** (ensemble de 12) | features T1 + regime | toda barra tradeável |
| **Meta** | saída do Alpha + Grupo J | **só onde `side_hat ≠ 0`** |
| Decision → Risk → Execution | — | só onde Meta aprova |

**Os três pontos que a pergunta expôs, respondidos:**

1. **O Alpha nunca vê o OOS.** Cada trimestre é predito por um modelo cuja janela de treino termina antes dele. As 14 janelas produzem 14 modelos distintos.
2. **A triagem de estabilidade é in-fold.** A tabela de IC de 7 anos do §17 é diagnóstico para o *desenho*, nunca insumo de *configuração* — usá-la seria vazamento de horizonte.
3. **O Meta só existe onde o Alpha disparou**, treinado exclusivamente em predições OOF, e a taxa de sinal de 1,89% (§0.2 R3) define o tamanho desse subconjunto: ~3.900 sinais em 206 mil barras, ~1.600 observações efetivas. É por isso que ele permanece em V1.1 (§6).

## 5.10 Hiperparâmetros do modelo-base

```yaml
xgboost_base:
  objective: binary:logistic         # dois modelos, não multi:softprob
  max_depth: 3                       # classe B — varrer
  n_estimators: 300                  # early stopping no fold
  learning_rate: 0.03
  subsample: 0.8
  colsample_bytree: 1.0              # DESATIVADO — camada 3 substitui
  min_child_weight: 30
  reg_lambda: 5.0
  monotone_constraints: <camada 1, in-fold>
  scale_pos_weight: <do balanço de classes do fold>
```

`colsample_bytree` volta para 1,0 porque a amostragem aleatória de colunas **conflita** com o bagging estruturado: sortear colunas dentro de um modelo que já recebeu exatamente uma feature por grupo destrói a cobertura conceitual que a camada 3 constrói.

## 5.11 Ordem de implementação e ablação

Nenhuma camada entra por fé. Cada uma é uma variante que **incrementa `N_lifetime`** e precisa provar ganho no walk-forward:

| ordem | camada | custo | critério de permanência |
|---|---|---|---|
| 1 | restrições monotônicas | trivial | Sharpe WF ≥ baseline em ≥ 9 de 14 janelas |
| 2 | triagem de estabilidade | baixo | idem + HHI cai |
| 3 | bagging por grupo | médio | idem + deriva de HHI cai |
| 4 | Group DRO | médio | pior-ambiente melhora sem cair a média > 15% |
| 5 | DoubleEnsemble | alto | idem, e só se 1–4 já passaram |

**Se a camada 1 sozinha resolver, pare na camada 1.** Cinco camadas custam cinco entradas no `N_lifetime` e cinco fontes de bug. A ordem é por razão ganho/custo, e o critério de parada é explícito: a primeira camada que não melhorar em ≥ 9 de 14 janelas encerra a sequência.

## 5.12 OUTPUT — `predictions/alpha/{model_id}/predictions.parquet`

| coluna | tipo | descrição |
|---|---|---|
| `t0` | `datetime64[ns, UTC]` | PK |
| `p_long` | `float64` | saída calibrada de `M_long` |
| `p_short` | `float64` | saída calibrada de `M_short` |
| `score_long_raw` `score_short_raw` | `float64` | antes da calibração |
| `side_hat` | `int8` | −1 / 0 / +1 |
| `confidence` | `float64` | `max(p_long, p_short)` |
| `confidence_rank` | `float64` | percentil (0,1] de `score_{side}_raw` DENTRO do `fold_id` que gerou a linha |
| `ensemble_std` | `float64` | **desvio entre os 12 modelos — proxy de incerteza epistêmica** |
| `n_models_agree` | `int8` | quantos dos 12 concordam com `side_hat` |
| `model_id` `calibrator_id` `feature_version` | `str` | |
| `features_selecionadas` | `list[str]` | saída da triagem in-fold daquela janela |
| `hhi_importancia` | `float64` | diagnóstico da janela |
| `wf_window_id` | `int16` | qual das 14 janelas gerou |
| `fold_id` | `int16` | null em produção |
| **`is_oof`** | `bool` | **o discriminador que impede o vazamento Alpha→Meta** |

`ensemble_std` e `n_models_agree` são novos e valiosos: com 12 modelos de features disjuntas, **discordância alta é sinal de que o edge daquela barra vem de um único conceito** — exatamente o caso que não sobrevive a mudança de regime. São candidatas naturais a feature do Meta e a filtro do Decision Engine.

**`confidence_rank` (2026-08-09, Faixa 1.5 Bloco 4) — segunda definição de confiança, adicionada sem remover `confidence`.** Mecanismo verificado empiricamente: o calibrador isotônico é ajustado POR FOLD (§5.9 passo 9); empilhar as predições OOF dos 15 folds preserva a ordem *dentro* de cada fold (cada mapa é individualmente monotônico), mas **não** preserva uma ordem global — o mesmo valor de `confidence` calibrado em fold A e em fold B pode corresponder a percentis muito diferentes da distribuição de score cru daquele fold. `confidence_rank = rank(score_{side}_raw) / count(score_{side}_raw)` calculado com `.over(fold_id)` (percentil, não probabilidade) resolve isso sem recalibrar sobre OOF empilhado — recalibrar vazaria os 15 folds entre si na própria probabilidade que o Meta consumiria na V1.1 (vazamento estrutural, mesma classe de B07). `confidence_rank` é ORDEM pura: não substitui `confidence` onde a magnitude calibrada é necessária (ex. `P(TP)` para dimensionamento), e qual campo o Decision Engine consome continua sendo decisão do Manager — este item só adiciona a opção, não escolhe entre elas. Ver `experiments/faixa1_5_prerequisites.json::confidence_variants` para os três perfis (cru/calibrado/rank) lado a lado.

## 5.13 INVARIANTES

```python
assert set(monotone_constraints) <= set(features_in_training_window)
assert stability_screen_data.index.max() <= train_end   # sem vazamento de horizonte
assert hhi_importancia < 0.25
assert max(feature_share.values()) < 0.30
assert alpha_preds.loc[alpha_preds.fold_id.notna(), "is_oof"].all()
assert not X_alpha.columns.str.startswith("J")          # features de execução são do Meta
assert len(set(m.features) for m in ensemble) == 12     # 12 conjuntos distintos
```

# PARTE VI — META MODEL

## 6.1 Decisão: o Meta sai do MVP

O Meta entra na **V1.1**, não na V1. A justificativa é aritmética.

## 6.2 O label do Meta é diferente do label do Alpha

O PRD V2 dizia que o Meta produz `trade_probability` mas **nunca definia sobre qual label ele treina**. Meta-labeling próprio é:

- Label do **Alpha**: `side ∈ {−1, 0, +1}` — *qual lado?*
- Label do **Meta**: binário — *o lado que o Alpha escolheu deu certo?*

```python
label_meta[t] = 1   se side_hat[t] != 0 e barrier_hit == "TP"
              = 0   se side_hat[t] != 0 e barrier_hit in {"SL", "TIME", "NOFILL"}
              = ⊥   se side_hat[t] == 0        → linha NÃO entra no dataset
```

## 6.3 A conta de amostra

O Meta só treina onde o Alpha disparou. Com taxa de sinal de 2,92% (§5.6) e horizonte de 16 barras:

```
barras (5,9 anos de 30m)          103.700
× taxa de sinal 2,92%          →     3.028 sinais
concorrência = 1 + s(2h−1) = 1 + 0,0292×31 = 1,905
obs efetivas do Meta           →     1.590
teto de features               →     3 a 8
```

Comparado ao Alpha (3.240 efetivas, teto 7–16), o Meta tem **metade da amostra**. E a Seção 14 do V2 listava **11 features** de entrada para um LightGBM.

**Um LightGBM com 11 features sobre 1.590 observações efetivas não é um modelo — é um gerador de ruído com boa métrica in-sample.**

## 6.4 Restrição de marginalidade

Se o Meta ficar, precisa obedecer uma regra que o V2 não menciona:

> O conjunto de features do Meta **não pode** estar contido em `features(Alpha) ∪ {saída do Alpha}`.

Se estiver, o Meta não pode adicionar informação — só recorta o mesmo espaço, e todo ganho aparente é overfitting.

**As features de execução (Grupo J, §2.11) são exatamente essa margem.** O Alpha não vê `p_fill_est`, `queue_ahead_notional` nem `adverse_selection_est_bps` por construção. Sob execução maker, o trabalho do Meta vira em boa parte:

> *"Vale postar este sinal, dado que talvez eu não seja preenchido — e que se eu for, provavelmente foi porque o mercado veio contra?"*

Essa é uma pergunta que o Alpha estruturalmente não pode responder. É a única justificativa honesta para o Meta existir neste sistema.

## 6.5 INPUT (quando entrar, V1.1)

Máximo de **6 features**, das quais **pelo menos 3 do Grupo J**:

| # | feature | origem | marginal? |
|---|---|---|---|
| 1 | `alpha_confidence` | Alpha OOF | não |
| 2 | `J01_p_fill_est` | modelo de fila | **sim** |
| 3 | `J04_cost_est_bps` | derivado | **sim** |
| 4 | `J05_adverse_selection_est_bps` | markout | **sim** |
| 5 | `F03f_spread_vol_ratio` | microestrutura | sim (Alpha vê F02f, não F03f) |
| 6 | `E05f_time_to_funding_h` | derivado | sim |

**Modelo:** regressão logística com penalidade L2, não LightGBM. Sobe para gradient boosting apenas quando as observações efetivas passarem de 3.000 — o que exige 2+ anos adicionais de dados ou taxa de sinal maior.

## 6.6 OUTPUT — `predictions/meta/{model_id}/predictions.parquet`

| coluna | tipo |
|---|---|
| `t0` | `datetime64[ns, UTC]` |
| `p_take` | `float64` |
| `decision` | `category` — APPROVE / REJECT |
| `threshold_used` | `float64` |
| `model_id` | `str` |
| `is_oof` | `bool` |

**Threshold:** fixado a priori pelo mesmo critério de orçamento de fees do §5.6, ou escolhido dentro do fold. Nunca por métrica OOS.

## 6.7 CONSUMIDORES

Decision Engine (APPROVE/REJECT) · Audit · Dashboard.

**O Risk Engine não usa `p_take` para dimensionar.** A nota do V2 §17 deixava a porta aberta para Kelly fracionado "se o Meta for genuinamente calibrado". Com 1.590 observações efetivas ele não será — e a calibração medida vai *parecer* boa exatamente porque a amostra é pequena. **Essa porta está fechada na V3.** Sizing fixo, ponto final.

## 6.8 Critério de entrada do Meta na V1.1

O Meta só é promovido quando **todos** forem satisfeitos:

```
1. obs_efetivas_meta ≥ 3.000
2. modelo de fila (J01–J05) calibrado e validado contra fills reais
3. ganho de precisão no CPCV > 5 pp, estável em ≥ 4 dos folds
4. DSR do sistema com Meta > DSR sem Meta, com o N corrigido pelas variantes de Meta testadas
5. Brier score do Meta < 0,22
```

Falhar qualquer um ⟹ o Meta continua fora. A ausência do Meta não é um débito técnico; é uma decisão de dimensionamento.

---

# PARTE VII — DECISION ENGINE

## 7.1 Responsabilidade

Transformar saídas de modelo em **intenção de trade**. Não decide tamanho, não valida risco, não executa.

## 7.2 Estados

```
NO_SIGNAL          nenhuma condição de entrada
LONG_CANDIDATE     Alpha indicou long, aguardando validação
SHORT_CANDIDATE    Alpha indicou short, aguardando validação
LONG_APPROVED      passou Decision + Risk
SHORT_APPROVED     passou Decision + Risk
REJECTED_DECISION  reprovado no Decision
REJECTED_RISK      reprovado no Risk (motivo enumerado, §8.5)
```

## 7.3 PROCESSO — cadeia de portões, ordem fixa

```
01. regime.tradeable == False            → NO_SIGNAL      (R0 ou R5)
02. alpha.side_hat == 0                  → NO_SIGNAL
03. alpha.confidence < τ_alpha           → NO_SIGNAL
04. posição atual != FLAT                → NO_SIGNAL      (uma posição por vez, V1)
05. cooldown ativo desde último exit     → NO_SIGNAL
06. [V1.1] meta.decision == REJECT       → REJECTED_DECISION
07. senão                                → {LONG|SHORT}_CANDIDATE → Risk Engine
```

**Cooldown (item 05):** mínimo de 4 barras (2h) entre a saída de um trade e a entrada do próximo. Existe por dois motivos: evita que o sistema reentre imediatamente no mesmo movimento que acabou de estopá-lo, e é o mecanismo mais simples de conter a taxa de trades dentro do orçamento de fees.

## 7.4 OUTPUT

```json
{
  "t0": "2026-08-08T14:30:00Z",
  "state": "LONG_CANDIDATE",
  "side": 1,
  "alpha_confidence": 0.34,
  "regime": "R3",
  "gates_passed": ["regime", "side", "confidence", "flat", "cooldown"],
  "gates_failed": [],
  "meta_p_take": null,
  "decision_version": "v1"
}
```

## 7.5 CONSUMIDORES
Risk Engine (único destino de `*_CANDIDATE`) · Audit · Dashboard.

---

# PARTE VIII — RISK ENGINE E POSITION SIZING

## 8.1 Autoridade

O Risk Engine é a **última autoridade antes da execução**. Pode transformar `APPROVED` em `REJECTED` sem consultar modelo nenhum. Nenhum componente pode contorná-lo.

## 8.2 Sizing — o cálculo completo

```python
# 1. orçamento de risco em dólares
equity          = reconciled_equity_usd            # do Reconciliation, nunca cache local
risk_usd        = equity * 0.005                   # §0.2 R1

# 2. distância de stop
atr_pct         = features.atr_20_pct
stop_pct        = 1.5 * atr_pct

# 3. nocional exigido
notional_req    = risk_usd / stop_pct

# 4. quantização pelo filtro VIGENTE NA DATA
filters         = load_filters_asof(t0)
qty_raw         = notional_req / mark_price
qty             = floor_to_step(qty_raw, filters.step_size)
notional_real   = qty * mark_price

# 5. verificações duras
risk_real       = notional_real * stop_pct
quant_error     = abs(notional_real - notional_req) / notional_req
leverage_eff    = notional_real / equity
```

## 8.3 Os 18 controles, em ordem de avaliação

| # | controle | limiar | motivo de rejeição |
|---|---|---|---|
| 1 | regime tradeável | `regime ∈ {R1..R4}` | `REGIME_BLOCKED` |
| 2 | estado do sistema | `state == RUNNING` | `STATE_NOT_RUNNING` |
| 3 | kill switch | `killed == False` | `KILL_SWITCH_ACTIVE` |
| 4 | reconciliação fresca | idade < 60s | `STALE_RECONCILIATION` |
| 5 | frescor de dados | barra < 90s, book < 5s | `DATA_STALE` |
| 6 | **quantidade mínima** | `qty ≥ filters.min_qty` | `BELOW_MIN_QTY` |
| 7 | **nocional mínimo** | `notional_real ≥ filters.min_notional` | `BELOW_MIN_NOTIONAL` |
| 8 | **granularidade** | `notional_real ≥ 3 × unit_notional` | `INSUFFICIENT_GRANULARITY` |
| 9a | **erro de quantização** | `quant_error ≤ 0,25` | `QUANTIZATION_LIMIT` |
| 9b | **resolução de sizing** | `N_req / unit ≥ 2,0` | `INSUFFICIENT_RESOLUTION` |
| 10 | **risco real** | `risk_real / equity ≤ 0,006` | `RISK_OVERSHOOT` |
| 11 | nocional máximo | `leverage_eff ≤ 3,0` | `MAX_NOTIONAL` |
| 12 | margem disponível | `IM_req ≤ 0,60 × equity` | `INSUFFICIENT_MARGIN` |
| 13 | **orçamento de fees** | fees do mês corrente ≤ 3% do equity | `FEE_BUDGET_EXHAUSTED` |
| 14 | perda diária | perda do dia ≤ 2% do equity | `DAILY_LOSS_LIMIT` |
| 15 | drawdown | DD do pico ≤ 10% | `MAX_DRAWDOWN` |
| 16 | perdas consecutivas | ≤ 5 | `CONSECUTIVE_LOSSES` |
| 17 | spread e liquidez | `spread_bps ≤ 3,0` e `depth_20bps ≥ 4 × unit` | `LIQUIDITY_INSUFFICIENT` |
| 18 | janela de evento | `is_event_window == 0` | `EVENT_WINDOW` |

**Nota v3.3 — controle 17 herda a quebra de 2025-11-20.** `spread_bps` (F01f) e `depth_20bps` (F09f) vêm de `bookTicker`/`bookDepth`, a mesma fonte contaminada do §2.7.1. Como o spread visível **superestima** o real pós-quebra, o efeito é um controle mais conservador que o necessário — bloqueia entradas por `LIQUIDITY_INSUFFICIENT` com mais frequência do que a liquidez real justificaria, não menos. Direção de erro segura, mas o limiar `3,0` deve ser revisto junto com o retorno do Grupo F a T1.

**Por que 9a e 9b são controles separados.** A v3.0 tinha só o erro de quantização, e isso deixa passar um caso ruim: a 2h, `N_req/unit = 1,14`, que arredonda para 1 unidade com erro de apenas 12,6% — **passa no controle por sorte de onde `N_req` calhou**. Mas com 1 unidade o nocional é fixo em US$ 64,94 independente do ATR, e o risco por trade deixa de ser parâmetro e vira consequência da volatilidade. Medido:

| TF | unid mediana | risco p10 | risco p50 | risco p90 | p90/p10 | barras > 0,60% |
|---|---|---|---|---|---|---|
| **15m** | 3,32 | 0,429% | 0,501% | 0,572% | **1,33x** | 5,8% |
| 30m | 2,30 | 0,416% | 0,506% | 0,615% | 1,48x | 11,7% |
| 1h | 1,61 | 0,392% | 0,537% | 0,766% | 1,95x | 29,1% |
| 2h | 1,14 | 0,372% | 0,517% | 1,134% | **3,05x** | 38,1% |
| 4h | 0,80 | 0,460% | 0,627% | 1,685% | **3,66x** | 56,5% |

**Controles 6 a 10 são o núcleo desta versão do PRD.** São a tradução operacional das restrições R1/R2 do §0.2. O V2 não tinha nenhum deles.

**Controle 9 explicado.** Quando o lote mínimo força um nocional muito maior que o exigido, o trade que seria executado tem risco materialmente diferente do pretendido:

| stop | N exigido | unidades | N real | risco real | erro |
|---|---|---|---|---|---|
| 0,30% | $328,1 | 5 | $324,7 | 0,495% | −1,0% ✓ |
| 0,41% | $241,2 | 4 | $259,8 | 0,538% | +7,7% ✓ |
| 0,50% | $196,8 | 3 | $194,8 | 0,495% | −1,0% ✓ |
| 0,80% | $123,0 | 2 | $129,9 | 0,528% | +5,6% ✓ |
| 1,50% | $65,6 | 1 | $64,9 | 0,495% | −1,0% ✓ |
| 2,00% | $49,2 | 1 | $64,9 | 0,660% | **+31,9% ✗** |

Um trade que só pode ser executado com 132% do risco pretendido **não é o mesmo trade**. É rejeitado, e a rejeição é registrada — **a frequência de `QUANTIZATION_LIMIT` é o indicador mais honesto de que a conta está pequena demais para a configuração**.

**Controle 13 explicado.** O orçamento de fees é um contador vivo, não uma aspiração:

```python
fees_mtd = sum(fills.fee for fills in current_month)
budget   = 0.03 * equity            # US$ 5,91
if fees_mtd + estimated_cost > budget:
    reject("FEE_BUDGET_EXHAUSTED")
```
Com custo assimétrico de US$ 0,143 por trade, isso permite ~41 trades no mês. Ao esgotar, o sistema para de abrir posições até a virada do mês — mas **continua gerenciando as abertas**.

## 8.4 Sizing é fixo — a porta do Kelly está fechada

```yaml
sizing:
  method: fixed_fractional_risk
  risk_per_trade: 0.005
  kelly: DISABLED
  kelly_reason: >
    Kelly fracionado exige p e b calibrados. Com 1.590 observações efetivas
    do Meta, a calibração medida vai parecer boa exatamente porque a amostra
    é pequena. Reabrir só se obs_efetivas > 5.000 e Brier < 0.20 sustentado
    em 6 meses de paper.
  dynamic_sizing: DISABLED
```

## 8.5 OUTPUT

```json
{
  "t0": "2026-08-08T14:30:00Z",
  "decision": "APPROVED",
  "side": 1,
  "qty": 0.004,
  "notional_usd": 259.76,
  "entry_ref": 64940.00,
  "stop_price": 64675.02,
  "tp_price": 65293.31,
  "stop_pct": 0.408,
  "risk_usd": 1.060,
  "risk_pct_equity": 0.538,
  "quantization_error": 0.077,
  "leverage_effective": 1.32,
  "im_required_usd": 25.98,
  "fees_mtd_pct": 1.84,
  "estimated_cost_usd": 0.143,
  "controls_passed": 18,
  "controls_failed": [],
  "filters_hash": "a81f92",
  "risk_version": "v1"
}
```

## 8.6 Configuração de alavancagem na exchange

**A alavancagem configurada não é controle de risco.** Testada de 3x a 20x, a janela de stop viável não se move — a restrição ativa é sempre lote e custo, nunca alavancagem.

O que ela muda é margem travada:

| alavancagem | IM para nocional $259,8 | % do equity travado |
|---|---|---|
| 3x | $86,60 | 44% |
| 10x | $25,98 | **13%** |
| 20x | $12,99 | 7% |

```yaml
exchange:
  margin_mode: CROSSED
  leverage: 10                  # libera buffer de margem
  max_notional_multiple: 3.0    # ← o controle real, no Risk Engine
```

Em cross margin, a alavancagem configurada não aproxima a liquidação — esta depende do saldo total contra a margem de manutenção. Com nocional de $259,8 e MMR de tier 1 (0,40%), a margem de manutenção é US$ 1,04 e a liquidação exige movimento adverso de ~74%. O stop está em 0,408%. **Liquidação está 180 vezes mais longe que o stop** — não é risco relevante neste desenho.

## 8.7 INVARIANTES

```python
assert qty % filters.step_size == 0
assert qty * price >= filters.min_notional
assert risk_real / equity <= 0.006
assert quant_error <= 0.25
assert notional_real / equity <= 3.0
assert equity_source == "reconciliation"        # nunca cache local
assert filters == load_filters_asof(t0)         # nunca filtros de hoje no passado
```

---

# PARTE IX — EXECUTION ENGINE

## 9.1 Política de execução

```yaml
execution:
  entry:
    type: LIMIT
    time_in_force: GTX            # post-only: cancela se cruzaria
    price: best_bid (long) | best_ask (short)
    timeout_bars: 1               # 30 minutos
    on_timeout: CANCEL            # o sinal expira; NUNCA vira market
    repost: false                 # sem perseguir preço na V1
    entry_mode:
      default: LIMIT_GTX               # post-only comum
      alternativa: LIMIT_GTX_RPI       # post-only RPI
      decisao: por experimento A/B (§9.5.1), NÃO por premissa
  take_profit:
    type: LIMIT
    time_in_force: GTC
    reduce_only: true
  stop_loss:
    type: STOP_MARKET
    working_type: MARK_PRICE      # alinhado com o Label Engine
    reduce_only: true
    close_position: false
  time_stop:
    bars: 32                    # 8h a 15m — ver time_stop_bars em constants.yaml
    action: MARKET reduce_only
```

**`on_timeout: CANCEL` é uma decisão de desenho, não uma otimização.** Se o limite não encheu em 30 minutos, o sinal envelheceu; converter para mercado destrói a economia toda de §0.3 e transforma o caminho assimétrico (0,055%) em taker/taker (0,10%), que reprova o Gate 0.

**`working_type: MARK_PRICE` no stop** é obrigatório para alinhar com o Label Engine (§3.4). Se o label avalia barreira em mark e a execução dispara em last, o modelo aprendeu sobre um trade diferente do que é executado.

**Corrigido (auditoria de engenharia, 2026-08-09):** `time_stop.bars` estava em 16 — sobra da era em que o TF de decisão era 30m (16×30m=8h). O valor canônico atual, usado por `constants.yaml::time_stop_bars` e por todo o resto do PRD (linhas 822, 2911, 3146), é 32 barras de 15m para a mesma janela de 8h/1 funding. O código nunca leu este bloco YAML (lê `constants.yaml` diretamente), então não houve impacto em labels/modelo — o risco era só para uma futura implementação de `src/execution/` que copiasse este trecho literalmente.

## 9.2 Máquina de estados da ordem

```
CREATED → SUBMITTED → ACKNOWLEDGED ─┬→ PARTIALLY_FILLED → FILLED
                                     ├→ FILLED
                                     ├→ CANCELED        (timeout)
                                     ├→ EXPIRED_GTX     (teria cruzado)
                                     └→ REJECTED
qualquer estado ─→ UNKNOWN  (timeout de rede / resposta ambígua)
```

`UNKNOWN` é terminal até resolução por reconciliação. **Nenhuma ordem nova é enviada enquanto existir ordem em `UNKNOWN`.**

## 9.3 Preenchimento parcial

Com 4 unidades de 0,001 BTC, o preenchimento parcial é real e frequente sob maker.

| situação | ação |
|---|---|
| preenchido ≥ 3 unidades no timeout | aceita a posição, cancela o resto, **redimensiona TP/SL para a qty efetiva** |
| preenchido 1–2 unidades no timeout | viola o controle 8 (granularidade) — **fecha a mercado imediatamente** e registra `PARTIAL_BELOW_MIN` |
| preenchido 0 | cancela, registra `NOFILL`, o sinal expira |

O segundo caso é contraintuitivo mas correto: uma posição de 1 unidade tem risco de 0,13% do equity e paga o mesmo custo fixo de round-trip — a razão custo/risco fica 4x pior que o desenho. Sair é mais barato que carregar.

## 9.4 Rate Limit / Weight Budget Manager

```yaml
rate_limits:
  ip_weight:
    header: X-MBX-USED-WEIGHT-1M
    strategy: token_bucket
    reserve_pct: 30              # reserva para execução
  order_count_10s:
    header: X-MBX-ORDER-COUNT-10S
  order_count_1m:
    header: X-MBX-ORDER-COUNT-1M
  priority:
    P0: [cancel_order, reconcile, close_position]
    P1: [create_order, query_order]
    P2: [account_info, position_risk]
    P3: [backfill, research]
```

Regras:
1. Ler os headers de **cada** resposta e ajustar o orçamento em tempo real. Nunca confiar apenas em contagem própria.
2. Peso de IP e contagem de ordens são orçamentos **independentes** — a Binance pune os dois separadamente.
3. Chamadas de execução têm prioridade absoluta sobre backfill quando o orçamento aperta.
4. Orçamento restante é **métrica de observabilidade**, não exceção descoberta em produção.

**Atenção de API (verificada no changelog):** desde 2026-01-15, endpoints assinados exigem **percent-encode do payload antes de calcular a assinatura**. Fora dessa ordem, `-1022 INVALID_SIGNATURE`. URLs legadas de WebSocket foram descomissionadas em 2026-04-23.

## 9.5 Modelo de preenchimento e seleção adversa

O desconto maker não é de graça. Albers, Cucuringu, Howison e Shestopaloff rodaram um experimento de trading ao vivo **no perpétuo de Bitcoin da Binance** e documentaram <cite index="134-1">uma correlação negativa entre probabilidade de preenchimento e retorno pós-fill: as ordens que enchem são as que você preferiria não ter enchido, o que torna estratégias maker comumente citadas altamente não-lucrativas e empurra o maker viável para uma postura contrária ao desbalanço do livro.</cite>

Mecanicamente: <cite index="137-1">se a ordem está no fim da fila no momento da execução, a própria ordem taker que a preencheu move o mid contra o preço limite — quanto menor a quantidade à frente na fila, maior a seleção adversa.</cite>

**Simulador de fila — o artefato de maior retorno do projeto.** Você já tem os dois datasets necessários: `bookTicker` no nível de tick (topo do livro a cada mudança) e `aggTrades` (cada execução com lado do agressor). Com os dois, dá para reconstruir posição de fila e simular preenchimento honestamente, em vez de assumir "limite tocado = preenchido" — que é a mentira que faz backtest de maker parecer maravilhoso. **Isso vale integralmente até 2025-11-19.** A partir de 2025-11-20 o par `bookTicker`+`aggTrades` já não descreve o livro inteiro — ver a divisão pré/pós abaixo.

```yaml
fill_model:
  type: queue_position
  sources_pre_2025_11_20:  [bookTicker_tick, aggTrades]
  sources_post_2025_11_20: [rpiDepth_stream, bookTicker_tick, aggTrades]
  aviso: >
    Não há dump histórico de rpiDepth. Fills pós-2025-11-20 NÃO são simuláveis a
    partir dos dumps públicos — o book visível é incompleto. O modelo de fill é,
    a partir dessa data, premissa validada apenas para a frente, contra fills
    reais de Testnet e Paper. Registrar isso no relatório de backtest, não
    silenciar.
  logic:
    - registra queue_ahead ao postar
    - decrementa por volume taker executado no nível
    - decrementa por cancelamentos estimados (taxa calibrada)
    - preenche quando queue_ahead <= 0
    - registra markout de 1m, 5m e 30m pós-fill
  outputs: [p_fill, t_entry, adverse_selection_bps]
  calibration:
    method: comparar contra fills reais de Testnet e Paper
    metric: erro absoluto mediano de p_fill
    threshold: 0.10
```

**Assimetria RPI que precisa ser modelada.** Ordens RPI casam apenas com takers não-algorítmicos. Nosso stop-loss é `STOP_MARKET` enviado por API — ordem taker algorítmica — logo **não pode consumir liquidez RPI**. Podemos adicionar liquidez ao pool RPI mas não retirá-la. Consequência: o slippage de saída deve ser estimado sobre profundidade **visível apenas**, mesmo quando a entrada foi postada como RPI. Modelar como dois pools distintos, não um.

Até o simulador estar calibrado, o backtest usa um valor conservador declarado:

```yaml
adverse_selection_bps: 1.5     # penalidade fixa; substituir por modelo calibrado
```

### 9.5.1 Experimento A/B — RPI vs post-only comum

RPI drena o fluxo taker não-algorítmico, que é o fluxo desinformado. O que sobra para bater numa ordem post-only comum é desproporcionalmente algorítmico e informado. Hipótese: postar RPI reduz seleção adversa às custas de fill rate.

Somos varejo de escala mínima — exatamente o participante que o mecanismo pretende beneficiar, e há estrutura de taxas dedicada a verificar.

Protocolo (Sprint 16, dentro do Paper):
- alternar `LIMIT_GTX` e `LIMIT_GTX_RPI` por sinal, aleatorizado
- medir por braço: fill rate, time-to-fill p50/p95, markout 1m/5m/30m, fee efetiva
- mínimo 60 fills por braço antes de decidir
- critério: adotar RPI se `markout_RPI < markout_comum − 1,0 bp` **e** `fill_rate_RPI ≥ 0,80 × fill_rate_comum`
- **conta como 1 trial no `N_lifetime`**

**Proveniência dos limiares do protocolo:** `60 fills/braço`, a vantagem mínima de `1,0 bp` de markout e o piso relativo de `0,80×` de fill rate são **classe B — hiperparâmetros do desenho experimental, provenance ASSUMED** (convenção razoável para poder estatístico mínimo num A/B de duas amostras; não é medição). Não entram no `N_lifetime` como busca — é desenho de protocolo, não otimização —, mas a decisão resultante (adotar RPI ou não) conta como 1 trial, conforme acima.

Verificação P0 do Sprint 2: confirmar via `exchangeInfo` / anúncio se BTCUSDT está entre os símbolos habilitados para RPI e qual a estrutura de taxas. Se não estiver, §9.5.1 fica suspensa e §2.7.1 permanece.

## 9.6 Métricas de execução

```
signal → order latency          order → ACK latency
ACK → fill latency              fill rate (preenchidas / postadas)
partial fill rate               time to fill (p50/p95)
adverse selection (markout 1m/5m/30m)
expected price vs actual        slippage realizado
rejection rate                  cancel rate
GTX expiry rate                 fee paid (maker vs taker split)
```

**`fill rate` e `adverse selection` são as duas métricas que decidem se o desenho maker se sustenta.** Se o fill rate ficar abaixo de 60%, a economia de §0.3 evapora e o sistema precisa voltar para o Gate 0. Para a seleção adversa, o limiar não é mais um número solto — é uma sensibilidade medida (abaixo).

**Sensibilidade medida (15m, TP 2,0×ATR, SL 1,5×ATR, ATR mediano 0,305%):**

| seleção adversa | BE win rate | veredito |
|---|---|---|
| 0 bps | 48,06% | ok |
| 2 bps | 49,89% | ok |
| 4 bps | 51,71% | ok |
| 5 bps | 52,62% | limite |
| 8 bps | 55,35% | rompe Gate 0 |

*(P1 — DERIVADO: aritmética direta sobre `tp_atr_mult`, `sl_atr_mult` — ambos classe A, P5-herdado, §18.5.1 — e o ATR mediano medido a 15m, 0,305% — P2, §18.3. Não é escolha nova; a tabela recalcula o breakeven win rate de §0.3 em função de um único parâmetro livre, a seleção adversa em bps.)*

Cada 1 bp custa **0,91 pp** de win rate exigido (DERIVADO da tabela acima). Margem confortável até **4,3 bps**; o teto do Gate 0 (BE ≤ 55%) rompe em **7,6 bps** (ambos DERIVADOS por interpolação linear da mesma tabela). O placeholder de 1,5 bps (§9.5) tem folga de ~3x antes do limite e ~5x antes da quebra.

**Risco RPI, registrado e aceito:** o RPI pode elevar a seleção adversa do post-only comum em magnitude desconhecida (P4 — nenhuma medição existe ainda; será P2 assim que o Paper produzir fills, §9.5.1). A decisão do Manager é prosseguir, porque (a) a variável é medida dos próprios fills no Paper, sem depender de dado histórico; (b) a folga até a quebra é de ~5x; (c) §9.5.1 oferece mitigação direta. Reavaliar no Gate 8 com o número medido.

## 9.7 INVARIANTES

```python
assert order.time_in_force == "GTX"                    # entrada sempre post-only
assert stop_order.working_type == "MARK_PRICE"
assert stop_order.reduce_only and tp_order.reduce_only
assert not any(o.state == "UNKNOWN" for o in open_orders)   # antes de nova ordem
assert client_order_id.is_unique_and_deterministic()        # idempotência
```

---

# PARTE X — RECONCILIAÇÃO, KILL SWITCH E ESTADOS

## 10.1 Reconciliação — RF-014

**Frequência:** a cada 30s em `RUNNING`, e obrigatoriamente antes de qualquer nova ordem.

| campo | local | exchange | tolerância |
|---|---|---|---|
| posição (lado) | `position.side` | `positionAmt` sinal | exata |
| quantidade | `position.qty` | `abs(positionAmt)` | exata |
| preço de entrada | `position.entry` | `entryPrice` | 1e-6 relativo |
| ordens abertas | conjunto de IDs | `openOrders` | exata |
| saldo | `equity` | `totalWalletBalance + unrealizedPnl` | 0,01 USDT |
| PnL não realizado | calculado | `unRealizedProfit` | 0,05 USDT |
| alavancagem | config | `leverage` | exata |
| modo de margem | config | `marginType` | exata |

**Divergência crítica** (posição, quantidade, ordens abertas ou modo de margem) ⟹ `TRADING_HALT` imediato. Nada de tentar corrigir automaticamente.

**A verdade é sempre da exchange.** O estado local é cache, nunca fonte.

## 10.2 Kill Switch — RF-015

| # | gatilho | limiar |
|---|---|---|
| 1 | perda diária | > 2% do equity |
| 2 | drawdown máximo | > 10% do pico |
| 3 | perdas consecutivas | > 5 |
| 4 | desconexão da exchange | > 120s sem WebSocket nem REST |
| 5 | divergência de posição | qualquer divergência crítica |
| 6 | ordem inesperada | ordem na exchange sem `client_order_id` conhecido |
| 7 | tempestade de erros de API | > 10 erros em 60s |
| 8 | corrupção de dados | Quality Gate falha em dado live |
| 9 | modelo indisponível | falha de carga ou inferência |
| 10 | falha do Risk Engine | exceção não tratada |
| 11 | estado de execução `UNKNOWN` | não resolvido em 120s |
| 12 | mudança de filtro | `filters_hash` mudou e não foi revalidado |
| 13 | equity abaixo do piso operacional | < US$ 150 (≈ 2,3 unidades) |

**Gatilho 13 é específico deste capital.** Abaixo de ~US$ 150, o controle 8 (granularidade) reprova essencialmente todo trade. O sistema para de operar antes de ficar preso numa configuração em que só consegue executar trades com risco fora do orçamento.

**Após `KILLED`:** sem retorno automático. Requer intervenção humana explícita, com registro de quem, quando e por quê. O procedimento de recuperação é: diagnosticar → reconciliar manualmente → resetar contadores → `PAUSED` → observação de 1h → `RUNNING`.

## 10.3 Estados do sistema

```
BOOT → INITIALIZING → SYNCING → READY → RUNNING ⇄ PAUSED
                                            ↓
                                          ERROR → HALTED → KILLED
```

Trading permitido **apenas** em `RUNNING`.

## 10.4 Estados da posição

```
FLAT
 ├─ LONG_PENDING  → LONG  → EXIT_PENDING → FLAT
 │       └─ (timeout/GTX expiry) → FLAT
 └─ SHORT_PENDING → SHORT → EXIT_PENDING → FLAT
         └─ (timeout/GTX expiry) → FLAT
```

Transições inválidas levantam exceção e disparam `TRADING_HALT`. A transição `*_PENDING → FLAT` por timeout é o caminho do `NOFILL`, e precisa ser tão explícita quanto as outras.

## 10.5 Disaster Recovery

```
BOOT
 → LOAD CONFIG            (valida hash contra o commit)
 → CONNECT EXCHANGE
 → FETCH SERVER TIME      (verifica drift do relógio, aborta se > 500ms)
 → LOAD FILTERS           (exchangeInfo + leverageBracket; compara hash)
 → LOAD MODEL             (verifica model_id e feature_version)
 → FETCH ACCOUNT STATE
 → FETCH OPEN ORDERS
 → FETCH POSITION
 → RECONCILE              (divergência → HALTED, não RUNNING)
 → REBUILD FEATURE STATE  (recarrega janelas de warmup do Data Lake)
 → VERIFY FEATURE PARITY  (últimas 500 barras, tolerância 1e-8)
 → READY
```

**Nunca assumir que o estado anterior continua correto porque o processo reiniciou.** E o passo de paridade de features no boot é o que impede o cenário mais silencioso de todos: reiniciar com estado de janela rolante diferente e operar com features sutilmente distintas das do treino.

## 10.6 Auditoria

Cada decisão gera um evento imutável, append-only, com tudo necessário para reconstruir o raciocínio:

```json
{
  "event_id": "uuid",
  "timestamp": "2026-08-08T14:30:00.123Z",
  "t0": "2026-08-08T14:30:00Z",
  "symbol": "BTCUSDT",
  "timeframe": "30m",
  "features": {"A05_ret_vol_norm_4": 0.42, "...": "..."},
  "feature_version": "v1",
  "regime": {"regime": "R3", "er_48": 0.71, "vol_pctile": 0.44, "bars_in_regime": 7},
  "regime_version": "v1",
  "alpha": {"p_long": 0.41, "p_short": 0.19, "p_neutral": 0.40,
            "side_hat": 1, "confidence": 0.01, "model_id": "alpha_xgb_v1.0"},
  "meta": null,
  "decision": {"state": "LONG_CANDIDATE", "gates_passed": ["..."]},
  "risk": {"decision": "APPROVED", "qty": 0.004, "notional_usd": 259.76,
           "risk_pct_equity": 0.538, "quantization_error": 0.077,
           "controls_failed": []},
  "order": {"client_order_id": "...", "type": "LIMIT", "tif": "GTX",
            "price": 64939.90, "qty": 0.004},
  "fill": {"t_entry": "...", "price": 64939.90, "fee": 0.0520, "is_maker": true},
  "exit": {"t_exit": "...", "barrier": "TP", "price": 65293.31, "fee": 0.0522},
  "funding": [{"ts": "...", "rate": 0.00008, "amount": -0.0208}],
  "pnl": {"gross": 1.4136, "fees": -0.1042, "funding": -0.0208, "net": 1.2886},
  "git_commit": "a81f92",
  "config_hash": "3d9e11",
  "filters_hash": "b72c04"
}
```

**Requisito de reprodutibilidade:** qualquer trade deve ser reconstruível a partir de `market data + features + regime + alpha + meta + risk + order + fill + fees + funding + position state`. Se um campo falta, o evento é inválido.

---

# PARTE XI — BACKTEST E VALIDAÇÃO

## 11.1 Backtest Engine

**Decisão de stack:** avaliar **NautilusTrader** antes de escrever motor próprio. Núcleo Rust, event-driven com resolução de nanossegundos, modelos configuráveis de fill/fee/latência, adapter Binance Futures, e **o mesmo código roda em backtest e live** — o que elimina de saída a classe inteira de bugs de divergência entre pesquisa e produção. Motor próprio é o componente caseiro de maior risco do projeto.

Se o motor próprio for mantido, ele precisa simular, sem exceção:

| item | tratamento |
|---|---|
| barreiras | avaliadas em `mark_1m`, ordem cronológica real |
| entrada | limite post-only com modelo de fila (§9.5) |
| não-preenchimento | desfecho `NOFILL`, sinal expira |
| preenchimento parcial | conforme §9.3 |
| TP | limite maker |
| SL | stop-market sobre mark price, taker |
| fees | maker/taker pelo caminho real, com desconto BNB se ativo |
| funding | evento discreto pontual nos timestamps reais, **não pro-rata** |
| seleção adversa | `adverse_selection_bps`, calibrado ou conservador |
| latência | distribuição medida, não constante |
| filtros | `load_filters_asof(t)`, nunca os de hoje |
| sizing | quantização real, incluindo rejeições por `QUANTIZATION_LIMIT` |
| orçamento de fees | contador vivo, rejeita ao esgotar |

## 11.2 Reconciliação backtest ↔ label

O backtest tem que **reproduzir `labels.ret_net`** dentro de tolerância declarada.

```python
assert abs(backtest.ret_net - labels.ret_net).max() < 1e-6
```

Divergência significa que um dos dois está errado. Este é o teste de integração de maior valor do projeto inteiro — vale mais que qualquer teste unitário isolado, porque cobre simultaneamente barreiras, custos, funding e quantização.

## 11.3 Janela de treino e política de dados

```yaml
dataset:
  start: 2020-09-01        # limitado por D04 metrics
  end:   2026-08-01
  bars_30m: ~103.700
  effective_obs: ~3.240
```

**Aviso de não-estacionariedade.** A estrutura do mercado mudou depois dos ETFs à vista (§2.10). Treinar em 2020–2023 e esperar transferência para 2026 é otimista. Duas defesas obrigatórias:

1. O CPCV **sempre** inclui pelo menos um fold de teste inteiramente em 2025–2026.
2. Relatar métricas de dois cortes: dataset completo e apenas 2024-01 em diante. Divergência grande entre os dois é evidência de decaimento estrutural, e o corte recente manda.

## 11.3.1 Ponderação por similaridade de estado

A resposta reflexiva à não-estacionariedade é treinar só em dados recentes. **Nestes dados, é o erro** — ver §17.3 para a evidência completa.

Em resumo: a literatura de concept drift mostra que <cite index="156-1">janelas deslizantes e pesos decaindo funcionam para drift suave e unidirecional, mas não exploram regimes recorrentes — uma vez que o conceito antigo é esquecido, ele precisa ser reaprendido quando retorna.</cite> E o BTC tem regimes **recorrentes**: 2023 e 2026 são quase gêmeos em ATR (0,277% vs 0,284%) e custo/ATR (19,9% vs 19,4%), e **2023 é o ano de maior sinal de toda a série** (§17.2). Treinar nos últimos 2 anos descartaria simultaneamente o ambiente mais parecido com hoje e o de melhor sinal.

**A alternativa: pesar por proximidade de estado, não por recência.**

```python
estado(t) = [ vol_pctile(t), cost_atr_ratio(t), regime_estrutural(t), funding_z(t) ]
w_sim(t)  = exp( −||estado(t) − estado(train_end)||² / (2σ²) )
w_final(t)= uniqueness(t) × |ret_net(t)| × w_sim(t)
```

Treinando hoje (custo/ATR 19,4%), **2023 (19,9%) recebe peso alto e 2021 (11,0%) recebe peso baixo — automaticamente**, sem ninguém decidir "cortar dados antigos".

`σ` é hiperparâmetro classe B; entra no `N_lifetime`. **Baseline obrigatório:** comparar contra peso uniforme e contra decaimento temporal puro (AFML cap. 4, parâmetro `c`). Se a similaridade não superar as duas em ≥ 10 de 14 janelas do walk-forward (§11.4.1, G-WF-5), ela sai.

## 11.4 CPCV — validação primária

Walk-forward **não** é o método primário. A literatura é clara: <cite index="93-1">CPCV apresenta menor Probabilidade de Backtest Overfitting e melhor estatística de Deflated Sharpe Ratio, enquanto o walk-forward mostra fragilidade na prevenção de falsas descobertas, com maior variabilidade temporal e estacionariedade mais fraca.</cite> <cite index="92-1">Trabalho comparativo de 2024 confirma a superioridade do CPCV em mitigar risco de sobreajuste, ainda que o walk-forward permaneça o padrão da indústria para simulação realista de trading.</cite>

```yaml
cpcv:
  n_groups: 6                # ~1 ano por grupo
  n_test_groups: 2
  n_splits: 15               # C(6,2)
  n_backtest_paths: 5
  purge:
    method: by_t1            # remove treino cujo [t0,t1] cruza o teste
    min_bars: 16             # = time_stop
  embargo:
    bars: 175                # ~1% do fold, ≈ 88h
  sample_weights: from labels.sample_weight
```

**Walk-forward permanece** como checagem de realismo sequencial: 1 caminho, treino expansivo, retreino trimestral. Se CPCV e walk-forward discordam materialmente, a discordância é o resultado — investigue antes de escolher o número que preferir.


## 11.4.1 Walk-Forward — especificação

A v3.0 tinha uma frase sem implementação. Agora tem função definida: **é o único instrumento que mede a taxa de decaimento do modelo**, e portanto o único que valida a cadência de retreino do §16.4 em vez de assumi-la.

### O que mede que o CPCV não pode

O CPCV é combinatório — gera splits em que o treino vem *depois* do teste. Correto e deliberado para medir sobreajuste; inútil para simular operação, onde só existe passado.

| pergunta | CPCV | walk-forward |
|---|---|---|
| o modelo sobreajusta? | **sim** | fraco |
| quanto decai entre retreinos? | não | **sim** |
| a cadência trimestral está certa? | não | **sim** |
| drawdown na ordem cronológica real | não | **sim** |
| peso por recência ou similaridade ajuda? | não | **sim** |
| qual camada do §5.11 vale manter? | não | **sim** |

### Configuração

```yaml
walk_forward:
  tipo: ancorado                     # expansivo; deslizante é variante testada
  treino_inicial: 3 anos             # 2020-01 .. 2022-12
  passo: 1 trimestre
  janelas_oos: 14                    # 2023-Q1 .. 2026-Q3
  retreino:
    hiperparametros: CONGELADOS do CPCV
    features: triagem de estabilidade RE-EXECUTADA in-fold a cada janela
    calibrador: reajustado a cada janela
  purge_embargo: idêntico ao CPCV (purge por t1, embargo 175 barras)
  variantes_de_peso:                 # cada uma incrementa N_lifetime
    - uniforme
    - decaimento_temporal(c=0.5)
    - decaimento_temporal(c=0.0)
    - similaridade(sigma=1.0)        # §11.3.1
```

### Saídas — séries, não médias

| saída | definição | por que importa |
|---|---|---|
| `sharpe_por_janela` | Sharpe OOS de cada trimestre | a média esconde tudo |
| `ic_por_janela` | IC realizado por janela | comparável direto com §17.2 |
| `decaimento_intra_janela` | Sharpe por semana desde o retreino (1..13) | mede envelhecimento |
| `meia_vida` | semanas até o Sharpe cair a 50% da primeira semana | **define a cadência** |
| `drawdown_cronologico` | DD na ordem real | o do CPCV é ficção |
| `pior_sequencia` | maior sequência de janelas negativas | calibra o kill switch |
| `ganho_por_esquema_de_peso` | Sharpe de cada variante | decide uniforme vs decaimento vs similaridade |
| `deriva_hhi` | variação do HHI de importância entre janelas | **detecta troca de personalidade do modelo** |
| `ganho_por_camada` | Sharpe com camadas 1..5 do §5.11 | decide onde parar |

### Gates — os números que faltavam

A frase original dizia *"se CPCV e walk-forward discordam materialmente, a discordância é o resultado"*, sem definir "materialmente":

```
G-WF-1  sharpe_walkforward >= 0,60 × sharpe_mediano_CPCV
        abaixo disso, o CPCV mede algo que não sobrevive à ordem cronológica

G-WF-2  meia_vida > 1,5 × cadência_de_retreino
        com cadência trimestral: meia-vida > 20 semanas
        FALHA → encurtar a cadência, não ignorar o resultado

G-WF-3  sharpe > 0 em >= 9 das 14 janelas OOS

G-WF-4  pior_sequencia <= 3 janelas negativas consecutivas

G-WF-5  esquema de peso vencedor supera 'uniforme' em >= 10 das 14 janelas
        senão: usar uniforme — mais simples e um trial a menos

G-WF-6  deriva_hhi < 0,10 entre janelas consecutivas
        senão: o modelo troca de feature dominante a cada retreino (§5.8)
```

**G-WF-2 fecha o laço com §16.4:** a cadência trimestral era assumida; agora é derivada da meia-vida medida.

### Integração

| item | valor |
|---|---|
| módulo | `src/validation/walk_forward.py` |
| comando | `python -m quant.validation.walkforward` |
| sprint | 11, junto com DSR |
| gate | Gate 4 — CPCV **e** walk-forward, ambos obrigatórios |
| DoD | critério 17b |

## 11.5 Detecção de vazamento — RF-018

| # | teste | método | falha ⟹ |
|---|---|---|---|
| 1 | close futuro | shuffle do alvo; AUC deve cair para ~0,5 | invalida |
| 2 | high/low futuro | inspeção de índices por feature | invalida |
| 3 | volume futuro | idem | invalida |
| 4 | funding futuro | `funding_next_est` só usa premium até `t0` | invalida |
| 5 | regime futuro | quantis do Regime Engine só sobre `< t` | invalida |
| 6 | contaminação de label | `t1` de treino nunca cruza janela de teste | invalida |
| 7 | labels sobrepostos | `sample_weight` aplicado em todo fit | invalida |
| 8 | normalização global | scaler é expansivo ou ajustado por fold | invalida |
| 9 | look-ahead em resample | agregação 1m→30m fecha em `close_time` | invalida |
| 10 | **encadeamento de modelo** | **`assert df_meta.is_oof.all()`** | invalida |
| 11 | **calibração vazada** | calibrador ajustado em sub-split interno | invalida |
| 12 | seleção de feature vazada | seleção **dentro** de cada fold de treino | invalida |
| 13 | filtros anacrônicos | `load_filters_asof` em todo o caminho | invalida |
| 14 | paridade lote/streaming | diferença < 1e-8 nas últimas 500 barras | invalida |

**Testes 10 a 14 não existiam no V2.** O 10 é o vazamento estrutural mais comum do desenho Alpha→Meta.

**Nota (auditoria de engenharia, 2026-08-09) — scan estatístico complementar, NÃO um 15º teste desta tabela.** `src/validation/leakage.py::scan_feature_target_correlation` (inspirado em `assert_no_leakage` do projeto irmão Laplace_Quant_V16) mede Spearman de cada feature T1 contra `ret_net`, com threshold Bonferroni-corrigido pelo número de features — pega erro de IMPLEMENTAÇÃO (off-by-one num `.shift()`, janela errada) que os 14 testes acima, focados em prova estrutural/causal_proof, não cobrem sozinhos. Deliberadamente NÃO é um gate PASS/FAIL binário: medido nesta auditoria que o Label Engine escala TP/SL por ATR (§3.4), então features derivadas de volatilidade correlacionam ESTRUTURALMENTE com `ret_net` mesmo sendo 100% causais (`E27f_cost_atr_ratio` mediu `rho=+0,142`, maior que o threshold Bonferroni ingênuo) — copiar o gate do projeto irmão sem essa verificação teria produzido falso positivo em 4 das 10 T1. Por isso o scan reporta `elevated` (informativo) separado de `hard_fail` (bloqueante, threshold calibrado no maior `rho` causal já medido — `constants.yaml::feature_leakage_hard_fail_threshold`). Proveniência completa em `constants.yaml::feature_leakage_bonferroni_factor`/`feature_leakage_hard_fail_threshold`.

## 11.6 Correção por múltiplos testes — DSR

O CPCV valida a estratégia **escolhida**, mas não corrige o fato de que ela foi escolhida entre N variantes testadas.

```yaml
trial_budget:                # declarado ANTES da busca, não estimado depois
  feature_sets: 4
  hyperparameter_trials: 40
  barrier_configs: 3
  threshold_variants: 1      # fixado a priori pelo orçamento de fees
  regime_configs: 2
  N_effective: 4 * 40 * 3 * 1 * 2 = 960
```

**Requisito operacional:** `experiments/` registra **todas** as variantes, não só a vencedora — configuração, métricas, timestamp, hash. Sem esse log o `N` não é reconstruível e o DSR não pode ser calculado. **Isso é V1, Sprint 6** — o V2 colocava experiment tracking na V1.1, o que tornava o Gate 6 incalculável por construção.

Métricas:
- **PSR** — probabilidade de o Sharpe observado ser de fato positivo, dado tamanho de amostra, assimetria e curtose reais
- **DSR** — PSR ajustado por `N_effective`
- **PBO** — probabilidade de sobreajuste de backtest, via CSCV

## 11.7 Monte Carlo — block bootstrap

Reamostragem i.i.d. de trades destrói autocorrelação e agrupamento de regime, produzindo distribuição de drawdown otimista.

```yaml
monte_carlo:
  method: stationary_bootstrap
  mean_block_length: 20      # trades
  n_simulations: 10000
  outputs:
    - distribuição de drawdown máximo
    - pior sequência de perdas
    - probabilidade de ruína (equity < US$ 150, o piso do kill switch 13)
    - IC 95% do retorno anual
    - IC 95% do Sharpe
```

## 11.8 Stress Engine

| # | cenário | variação |
|---|---|---|
| 1 | slippage | 1x · 1,5x · 2x · 3x |
| 2 | fees | tabela atual · +50% · sem desconto BNB |
| 3 | **fill rate** | 100% · 80% · 60% · 40% do modelo |
| 4 | **seleção adversa** | 0 · 1,5 · 3 · 5 bps |
| 5 | funding | histórico · percentil 95 sustentado |
| 6 | latência | medida · 2x · 5x |
| 7 | barras faltantes | 0,1% · 1% · 5% aleatórias |
| 8 | desconexão de WS | 1min · 10min · 1h |
| 9 | REST indisponível | 5min |
| 10 | ordem rejeitada | 1% · 5% das ordens |
| 11 | preenchimento parcial | 10% · 30% dos fills |
| 12 | gap de preço | 2% · 5% · 10% |
| 13 | volatilidade extrema | 2x ATR sustentado por 1 semana |
| 14 | flash crash | −15% em 5 minutos |
| 15 | **`MIN_NOTIONAL` dobra** | volta a 100 USDT |
| 16 | **`LOT_SIZE` dobra** | 0,002 BTC |
| 17 | BTC a US$ 130k | unidade mínima vira US$ 130 |
| 18 | BTC a US$ 30k | unidade mínima vira US$ 30 |

**Cenários 15 a 18 são específicos deste capital e não existiam no V2.** Se a Binance reverter o `MIN_NOTIONAL` ou o BTC dobrar de preço, a unidade mínima passa a ser uma fração maior do equity e a granularidade morre. O sistema precisa saber com antecedência a partir de qual preço de BTC a configuração deixa de ser viável.

## 11.9 Métricas

**Estratégia:** Net PnL · Gross PnL · win rate · profit factor · expectancy · ganho e perda médios · drawdown máximo e duração · Sharpe · Sortino · Calmar · recovery factor · contagem de trades · tempo médio de posição · turnover · fees · funding · slippage · **DSR** · **PSR** · **PBO**.

**Execução:** fill rate · time to fill (p50/p95) · taxa de preenchimento parcial · seleção adversa (markout 1m/5m/30m) · split maker/taker · taxa de rejeição · taxa de expiração GTX · **fração de `NOFILL`** · **fração de `QUANTIZATION_LIMIT`**.

**Estratificação obrigatória:** todas as métricas por regime (R1…R4), por ano e por faixa de volatilidade.

---

# PARTE XII — QUALITY GATES

Um modelo não avança por apresentar lucro no backtest.

## Gate 0 — Viabilidade Econômica

**Roda em segundos, antes de qualquer treino.** É o gate mais barato e o único que teria pego o MVP de 5m do V2 antes de escrever uma linha de Feature Engine.

```
custo_round_trip / distância_média_stop     ≤ 0,20
nocional_exigido / lot_mínimo               ≥ 3,0
breakeven_win_rate                          ≤ 0,55
fees_projetadas_mensais / equity            ≤ 0,03
erro_de_quantização_mediano                 ≤ 0,25
fração_NOFILL_projetada                     ≤ 0,35
distância_até_liquidação / stop             ≥ 20
```

Falhou ⟹ **não treina**. Muda TF, muda barreiras, muda execução, ou aporta capital.

## Gate 1 — Data Quality
`quality_score ≥ 0,995` · zero duplicatas · gaps classificados e listados · cobertura ≥ período de treino para toda feature T1 · desvio entre fontes < 1e-8.

## Gate 2 — Leakage
Os 14 testes do §11.5, todos `PASS`. Um único `FAIL` invalida o modelo.

## Gate 3 — Out-of-Sample e Baselines
Sharpe OOS > 0 · `ret_net` positivo · monotonicidade dos decis de `confidence` · nenhum regime com PnL catastrófico isolado.

**Baselines (§16.1), todos obrigatórios:** Sharpe do Alpha **acima do percentil 95 de B1** (entrada aleatória, 1.000 sementes, mesmas barreiras e custos) · acima de **B3** (só regime) · **`directional_sharpe > 0`** isoladamente, com `carry_share < 0,30` (§16.6) · B4 (features embaralhadas) deve colapsar AUC para ~0,5.

**Diagnóstico de concentração (§5.8):** os quatro critérios de HHI.

## Gate 4 — CPCV + Walk-Forward + Robustez por Regime

**CPCV:** Sharpe positivo em ≥ 4 dos 5 caminhos · desvio-padrão entre caminhos < 50% da média · **PBO < 0,30** · ao menos um fold de teste em 2025–2026.

**Walk-Forward:** G-WF-1 a G-WF-6 (§11.4.1), todos.

**Robustez por regime — novo, e o mais exigente:**
```
Sharpe > 0 em CADA regime estrutural R1..R4 individualmente     (não na média)
Sharpe > 0 em CADA faixa de regime econômico (§4.3.1)
Sharpe > 0 em CADA ano do OOS, ou explicação registrada do porquê não
```
Se o modelo só funciona em `ECONOMICS_FAVORABLE`, isso não é falha — é **especificação**: o motor ganha um gate de regime econômico e opera menos. Falha é descobrir isso ao vivo.

**Concentração (§5.8):** HHI < 0,25 · maior share < 0,30 · ≥ 6 features com share > 1% · deriva de HHI < 0,10.

## Gate 5 — Cost Stress
Sobrevive a 2x slippage · a fees +50% · a fill rate de 60% · a seleção adversa de 5,0 bps (limite medido, §9.6). "Sobrevive" = Sharpe permanece > 0 e drawdown < 15%.

## Gate 6 — Monte Carlo + DSR
**DSR > 0,95** com `N_effective` do orçamento declarado · probabilidade de ruína < 5% · drawdown do percentil 95 < 20%.

## Gate 7 — Testnet
Valida **mecânica**, não sinal: autenticação com o novo esquema de assinatura · todos os tipos de ordem · GTX rejeitando corretamente ao cruzar · arredondamento de tick e lote · tratamento de `PARTIALLY_FILLED` · reconciliação · recuperação de desconexão · rate limit sob carga · reinício com posição aberta. **Mínimo de 200 ordens e 2 semanas.**

## Gate 8 — Paper Trading
Valida **sinal**: dado real, features ao vivo, modelo ao vivo, risco ao vivo, execução simulada com o modelo de fila.
Mínimo **60 dias** e **60 trades**. Critérios:
- divergência de Sharpe vs backtest < 40%
- fill rate dentro de ±15 pp do previsto
- seleção adversa dentro de ±2 bps do previsto
- fees mensais ≤ 3% do equity
- **paridade de features batch↔streaming < 1e-8 em 100% das barras**
- seleção adversa medida ≤ 5,0 bps (limite; ≤ 4,3 bps é a faixa confortável) — §9.6
- experimento §9.5.1 (RPI vs post-only) concluído com decisão registrada

## Gate 9 — Operational Test
Reinício com posição aberta · desconexão de 1h e recuperação · kill switch disparado e recuperação manual · reconciliação após divergência forçada · dashboard refletindo estado real · todos os eventos de auditoria completos e reconstruíveis.

## Gate 10 — Go-Live
Revisão humana explícita, com registro assinado, de: todos os gates anteriores · risco regulatório do venue (§13.3) · capital comprometido · procedimento de parada. **Início com 50% do sizing por 30 dias.**

```
Gate 0 → 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → LIVE
```

---

# PARTE XIII — OPERAÇÃO

## 13.1 Observabilidade

**Níveis:** `INFO` · `WARNING` · `ERROR` · `CRITICAL`. Logging estruturado (`structlog` + JSON), nunca `print`.

**Monitorado continuamente:** conexão WebSocket · conexão REST · orçamento de rate limit restante · frescor de dados · frescor de features · idade da reconciliação · estado do modelo · estado do risco · estado da execução · estado da posição · fees acumuladas no mês · drawdown corrente · CPU/RAM/disco · drift do relógio.

**Alertas críticos:** `DATA_STALE` · `API_DISCONNECTED` · `POSITION_MISMATCH` · `ORDER_REJECTED` · `ORDER_UNKNOWN` · `RISK_LIMIT` · `KILL_SWITCH` · `MODEL_FAILURE` · `FEE_BUDGET_80PCT` · `FILTERS_CHANGED` · `PARITY_BREACH` · `CLOCK_DRIFT`.

## 13.2 Dashboard

**Página 1 — Live:** estado do sistema · posição · entrada · mark price · PnL não realizado e realizado · equity · drawdown · alavancagem efetiva · regime atual com persistência e gatilhos · saída do Alpha · risco · **fees do mês vs orçamento** · **unidades vs mínimo**.

**Página 2 — Execução:** ordens · fills · **fill rate** · time to fill · **seleção adversa (markout)** · slippage · split maker/taker · fees · rejeições · expirações GTX · **fração NOFILL**.

**Página 3 — Estratégia:** curva de equity · drawdown · PnL por regime · distribuição de trades · win/loss · expectancy · **contagem de trades vs orçamento** · distribuição de `barrier_hit`.

**Página 4 — Modelo:** distribuição de predições · **curva de calibração** · Brier · frequência de sinal · SHAP · importância por permutação · versão do modelo · **PSI por feature**.

**Página 5 — Saúde:** CPU · RAM · disco · WebSocket · REST · **orçamento de rate limit** · frescor de dados · uptime · drift do relógio · **hash dos filtros**.

**Página 6 — Risco:** contagem de rejeições por motivo (os 18 do §8.3) · **frequência de `QUANTIZATION_LIMIT`** · perdas consecutivas · perda diária · histórico do kill switch.

## 13.3 Risco de venue — acompanhamento obrigatório

Não é aconselhamento jurídico; é risco de dependência única sobre a exchange de que o sistema inteiro depende, com prazo dentro do cronograma do projeto.

- A CVM, no Ato Declaratório 17.961/2020, proíbe a Binance de captar clientes no Brasil para contratos futuros de cripto.
- Em julho de 2026, <cite index="51-1">a CVM afirmou que as regras já editadas sobre listagem, negociação e registro de contratos derivativos em mercados organizados no Brasil se aplicam integralmente a derivativos cujo ativo subjacente seja ativo virtual, alcançando plataformas estrangeiras que oferecem derivativos a investidores brasileiros.</cite>
- <cite index="45-1">As Resoluções BCB 519, 520 e 521 criaram as SPSAVs e deram às empresas estrangeiras 270 dias a partir de fevereiro de 2026 para transferir clientes e operações a uma instituição brasileira autorizada pelo BC ou abrir subsidiária local; quem não se adequar no prazo não poderá continuar atendendo investidores brasileiros.</cite> O prazo cai por volta de outubro/novembro de 2026.
- Desde julho de 2026 a Binance reporta operações de brasileiros à Receita, conforme a IN RFB 2.291/2025.

**Ações de projeto:**
1. Verificar empiricamente, antes do Sprint 2, o que a conta acessa hoje — isso é fato, não dedução a partir das normas.
2. Tratar o `ExchangeAdapter` como abstração que **precisa** de uma segunda implementação testada. O V2 já pedia o encapsulamento; falta exigir que a abstração seja provada.
3. O Audit Engine emite os registros necessários para apuração fiscal — o fato gerador existe independentemente de o sistema facilitar a apuração.
4. Reavaliar em cada ESA de stage.

---

# PARTE XIV — STACK E ROADMAP

## 14.1 Stack

| camada | escolha | nota |
|---|---|---|
| Python | 3.12+ | |
| ambiente | **uv** + lockfile | não pip/venv/conda |
| dataframe | **Polars** (lazy, Arrow) | Pandas só em interop de borda |
| analítico | **DuckDB** sobre Parquet | |
| armazenamento | Parquet + zstd | escrita atômica |
| ML | XGBoost · scikit-learn (calibração) | LightGBM só se o Meta entrar |
| busca | Optuna, **com orçamento declarado** | |
| regime | determinístico por quantis; `dynamax` na V1.1 | **não `hmmlearn`** |
| backtest | **NautilusTrader** (avaliar) | evita motor próprio |
| exchange | `binance-futures-connector` oficial, atrás de interface própria | não escrever adapter do zero |
| validação | CPCV próprio sobre `t1` | |
| tracking | MLflow local ou SQLite | **Sprint 6, não V1.1** |
| drift | PSI + KS; Evidently opcional | |
| config | Pydantic + YAML + `.env` | |
| logging | structlog + orjson | |
| dashboard | Streamlit + Plotly | |
| testes | pytest + hypothesis | |
| qualidade | ruff + mypy strict | |

## 14.2 Estrutura de software

```
btcusdt_quant/
├── config/       system · market · strategy · risk · execution · features · regime
├── data/         (ver §1.2)
├── models/
├── src/
│   ├── exchange/     adapter · rest · ws · rate_limit · filters
│   ├── data/         download · validate · resample · lake
│   ├── features/     engine · registry · groups/ · parity
│   ├── regime/       classifier · stress
│   ├── labels/       triple_barrier · fill_model · weights
│   ├── models/       alpha · meta · calibration · registry
│   ├── validation/   cpcv · purge · leakage · dsr · bootstrap
│   ├── backtest/     engine · simulator · costs · metrics
│   ├── risk/         engine · sizing · limits · kill_switch
│   ├── execution/    engine · orders · reconciliation · state
│   ├── live/         runner · paper · testnet
│   └── monitoring/   observability · alerts · dashboard
├── tests/        unit · integration · parity · failure
├── experiments/
├── audit/
└── scripts/
```

**Hierarquia de import (verificada estaticamente):**
```
exchange → data → features → labels → regime → models → validation
                                                    ↓
                          backtest ← risk ← execution ← live
```
`features/` **não pode** importar `labels/`. `models/` **não pode** importar `execution/`. Violação quebra o build.

## 14.3 Roadmap

| sprint | entrega | gate |
|---|---|---|
| **0** | **Gate 0** — planilha de viabilidade econômica com os números do §0.3 | **Gate 0** |
| 1 | repo · uv · config Pydantic · structlog · estrutura · CI · ruff/mypy | — |
| 2 | ExchangeAdapter · REST · WS · rate limit · **snapshots F01/F02/F04 iniciam hoje** · **coleta forward de `rpiDepth` inicia hoje (F06)** · **verificação empírica de acesso** | — |
| 3 | downloader dos 15 dumps · **D10 e D11 são P0** · validator · Parquet · DuckDB · resample | **Gate 1** |
| 4 | Feature Engine · 10 T1 · registry · **teste de paridade lote↔streaming** · ortogonalidade | — |
| 5 | Regime Engine · quantis expansivos · histerese · 10 gatilhos de stress | — |
| 6 | Label Engine · barreiras em mark 1m · `NOFILL` · pesos por unicidade · **experiment tracking** | — |
| 7 | CPCV · purge por `t1` · embargo · **os 14 testes de leakage** | **Gate 2** |
| 8 | Alpha · **camadas 1→5 do §5.11 em ordem, com ablação** · calibração no fold · **OOF com `is_oof`** · baselines B1–B5 | **Gate 3, 4** |
| 9 | **Simulador de fila** com bookTicker + aggTrades (+ `rpiDepth` pós-2025-11-20, §9.5) · calibração de seleção adversa | — |
| 10 | Backtest completo · custos · funding · filtros por data · **reconciliação vs `ret_net`** | **Gate 5** |
| 11 | DSR · PSR · PBO · Lo(2002) · block bootstrap · **walk-forward 14 janelas** · **19 cenários de stress** | **Gate 6** |
| 12 | Risk Engine · 18 controles · sizing quantizado · kill switch com 13 gatilhos | — |
| 13 | Execution Engine · GTX · stop em mark · parciais · máquina de estados | — |
| 14 | Reconciliação · disaster recovery · auditoria · dashboard 6 páginas | — |
| 15 | **Testnet** — 200 ordens, 2 semanas | **Gate 7** |
| 16 | **Paper** — 60 dias, 60 trades · **experimento A/B RPI vs post-only (§9.5.1), mín. 60 fills por braço** | **Gate 8** |
| 17 | Testes de falha · runbook operacional · revisão | **Gate 9, 10** |
| 18 | **Live a 50% do sizing por 30 dias** | — |

**Fora da V1, explicitamente:** Meta Model (§6.8 define o critério de entrada) · HMM · sizing dinâmico · Kelly · order book profundo · múltiplos pares · ETF flow como feature de treino.

---

# PARTE XV — DEFINITION OF DONE

## 15.1 Comandos

```bash
python -m quant.feasibility            # → Gate 0: PASS/FAIL com os números
python -m quant.data.download          # → 15 fontes, checksums verificados
python -m quant.data.validate          # → quality_report.json, gate PASS
python -m quant.features.build         # → features versionadas + paridade OK
python -m quant.regime.build           # → regimes versionados
python -m quant.labels.build           # → labels com t1, pesos, NOFILL
python -m quant.validation.leakage     # → 14 testes PASS
python -m quant.models.train           # → alpha registrado + predições OOF
python -m quant.backtest.run           # → relatório + reconciliação vs ret_net
python -m quant.validation.dsr         # → DSR, PSR, PBO com N declarado
python -m quant.stress.run             # → 18 cenários
python -m quant.testnet.run            # → mecânica validada
python -m quant.paper.run              # → paper ao vivo
python -m quant.live.run               # → motor live
python -m quant.monitor                # → estado operacional
```

## 15.2 Critérios de conclusão da V1

**Dados**
1. As 15 fontes coletadas, com checksum, incluindo D10 e D11
2. Snapshots de filtros iniciados e o backtest resolvendo por data
3. Quality Gate `PASS`, gaps listados nominalmente
4. Paridade histórico↔live das métricas medida e documentada

**Features**
5. 10 features T1 com registro completo e prova de causalidade
6. Paridade lote↔streaming < 1e-8 verificada
7. Ortogonalidade T1 ≤ 0,70 verificada
8. Determinismo bit a bit verificado

**Labels e regimes**
9. Barreiras avaliadas em mark 1m, primeiro toque cronológico correto
10. `NOFILL` emitido, pesos por unicidade aplicados
11. `config_hash` do label idêntico ao da execução
12. 5 regimes causais com histerese e 10 gatilhos de stress

**Modelo e validação**
13. Alpha treinado com pesos, calibrado dentro do fold
14. Predições OOF com `is_oof`, e o assert do Meta em vigor
15. Os 14 testes de leakage passando
16. CPCV com 5 caminhos, PBO < 0,30
17. DSR > 0,95 com `N` do orçamento declarado
18. Todas as variantes registradas em `experiments/`

**Execução e risco**
19. Simulador de fila calibrado contra fills reais
20. Backtest reproduzindo `labels.ret_net` dentro de 1e-6
21. 18 controles de risco implementados e testados individualmente
22. Sizing quantizado com rejeição por `QUANTIZATION_LIMIT`
23. Orçamento de fees como contador vivo
24. Execução GTX com timeout e cancelamento — nunca conversão para mercado
25. Stop em mark price, alinhado com o label

**Operação**
26. Reconciliação a cada 30s, exchange como verdade
27. Kill switch com 13 gatilhos, sem retorno automático
28. Reinício sem perder controle da posição, com paridade verificada no boot
29. Dashboard de 6 páginas refletindo estado real
30. Todo trade reconstruível a partir do log de auditoria
31. Live habilitável e desabilitável por configuração
32. Os 18 cenários de stress executados e documentados

## 15.3 O que a V1 é, e o que não é

O objetivo da V1 **não** é provar que BTCUSDT pode ser previsto. É construir a infraestrutura em que uma hipótese quantitativa possa ser **formulada → testada → invalidada ou aprovada → simulada → monitorada → executada → auditada → melhorada**.

Com US$ 196,85 de capital, isso deixa de ser filosofia e passa a ser a única leitura honesta do projeto. Os números do §0.2 mostram que esta conta opera na fronteira do que o instrumento permite: 4 unidades de granularidade, 1,4 trade por dia de orçamento, 10 features de teto, e um breakeven de 48,7% que só existe porque a execução é maker.

O capital confortável para este mesmo desenho — 10+ unidades e custo abaixo de 10% da distância de stop — sai entre **R$ 3.300 e R$ 13.200**, conforme a configuração. R$ 1.000 está de 3 a 13 vezes abaixo disso.

Isso não impede o projeto. Determina o que ele é: **um sistema de validação de infraestrutura que opera capital real em escala mínima**, não um veículo de composição de capital. Todo parâmetro deste blueprint decorre dessa leitura, e o Gate 0 existe para impedir que ela seja esquecida.

---

---

# PARTE XVI — ADIÇÕES v3.1

Nove lacunas identificadas na revisão do blueprint. Ordenadas por consequência.

## 16.1 Baselines nulos — RF-024 (NOVO)

O blueprint v3.0 não tinha controle. Sem baseline, um Sharpe positivo não distingue alpha de geometria de barreira: com `TP = 2,0×ATR` e `SL = 1,5×ATR` sobre um passeio aleatório, o win rate esperado já é `1,5/3,5 = 42,9%` **por construção**.

**Quatro baselines obrigatórios**, rodando no mesmo motor, com barreiras, custos, sizing, quantização e orçamento de fees **idênticos**:

| # | baseline | o que isola | critério |
|---|---|---|---|
| B1 | **entrada aleatória** — lado sorteado, mesma taxa de sinal | geometria das barreiras + custos | Alpha deve superar com significância |
| B2 | **buy-and-hold** BTCUSDT, sem alavancagem | prêmio direcional do ativo | contexto, não meta |
| B3 | **só regime** — entra long em R3/R4 com `A13 > 0`, sem Alpha | valor incremental do modelo | se o Alpha não supera, o modelo é decorativo |
| B4 | **Alpha com features embaralhadas** (permutação por coluna, mantendo marginais) | valor da estrutura das features | AUC deve cair para ~0,5 |

**B1 roda 1.000 sementes**, produzindo a distribuição nula do Sharpe. O Sharpe do Alpha é reportado como **percentil dentro dessa distribuição**, não como número absoluto. Isso é mais informativo que qualquer teste paramétrico, porque incorpora automaticamente custos, quantização e o orçamento de fees.

**Gate 3 revisado:** Sharpe do Alpha acima do percentil 95 de B1 **e** acima de B3. Falhar qualquer um invalida.

## 16.2 Janela desprotegida entre fill e stop — RF-025 (NOVO)

Não é possível postar ordem `reduce_only` antes de haver posição. A sequência real é:

```
t_post    posta entrada LIMIT GTX
t_entry   evento de fill chega pelo User Data Stream
t_sl      stop-market reduce_only aceito pela exchange
          ↑ entre t_entry e t_sl a posição está NUA
```

Com stop de 0,458% e latência Brasil→Binance, essa janela é risco material e não estava tratada.

```yaml
naked_window:
  trigger: ORDER_TRADE_UPDATE (User Data Stream) com status FILLED|PARTIALLY_FILLED
  action: enviar STOP_MARKET reduce_only IMEDIATAMENTE, antes de qualquer outra coisa
  ordem_de_prioridade: [stop_loss, take_profit, logging, dashboard]
  timeout_hard_ms: 2000
  on_timeout: MARKET reduce_only (fecha a posição) + alerta NAKED_WINDOW_TIMEOUT
  metrica: naked_window_ms (p50/p95/p99) — métrica de execução de primeira classe
```

**A ordem importa.** O stop vai antes do TP, e ambos antes de logging. Se o processo morrer entre fill e stop, o boot (§10.5) detecta posição sem stop associado e fecha a mercado.

**Cenário de stress 19 (novo):** processo morto exatamente entre `t_entry` e `t_sl`, com movimento adverso de 2% antes do restart.

## 16.3 User Data Stream — keepalive do listenKey — RF-026 (NOVO)

O `listenKey` expira em **60 minutos** sem renovação. Sem ele, os eventos de fill param de chegar e o estado local diverge silenciosamente até a próxima reconciliação — depois do prejuízo.

```yaml
user_data_stream:
  create:    POST /fapi/v1/listenKey
  keepalive: PUT  /fapi/v1/listenKey   a cada 1800s (metade da validade)
  on_keepalive_failure:
    retry: 3x com backoff 1s/2s/4s
    then:  recriar listenKey + reconciliação completa forçada
  watchdog:
    sem_evento_em: 300s  → ping sintético (consulta de posição)
    sem_resposta:  60s   → TRADING_HALT
  metrica: listenkey_age_s, ws_user_last_event_age_s
```

**Kill switch, gatilho 14 (novo):** `listenKey` inválido e não recriado em 120s.

## 16.4 Política de retreino — RF-027 (NOVO)

Ausente na v3.0. E o ponto que quase sempre escapa: **cada retreino é um novo trial que infla o `N` do DSR ao longo da vida do projeto**, não apenas dentro de uma busca.

```yaml
retraining:
  cadencia: trimestral, em data fixa declarada a priori
  gatilhos_extraordinarios:
    - PSI > 0.25 em >= 3 features T1 por 10 dias consecutivos
    - Brier score live > Brier backtest x 1.5 por 30 dias
    - drawdown live > percentil 95 do Monte Carlo
  proibido:
    - retreinar depois de uma sequencia de perdas
    - retreinar para "consertar" um mes ruim
  protocolo:
    - janela expansiva (nunca deslizante — descarta regime raro)
    - hiperparametros CONGELADOS do treino original
    - se hiperparametros mudarem, e um MODELO NOVO, nao um retreino
```

**Champion–challenger:**

```
challenger treinado → shadow mode 30 dias (prediz, não executa)
  → compara: Sharpe, Brier, taxa de sinal, concordância com champion
  → promove só se supera em >= 3 de 4 métricas E DSR do sistema não cai
  → champion vira fallback; rollback em 1 comando, testado trimestralmente
```

**Ledger de trials vitalício** (§16.9): cada retreino, cada challenger e cada mudança de hiperparâmetro incrementa `N_lifetime`. O DSR reportado usa `N_lifetime`, não o `N` de uma busca isolada.

## 16.5 Sharpe com autocorrelação — RF-028 (NOVO)

Retornos de trades sobrepostos e agrupados por regime têm autocorrelação positiva, que **infla o Sharpe**. O DSR corrige assimetria e curtose; **não corrige autocorrelação**.

```yaml
sharpe_correction:
  metodo: Lo (2002) — fator de escala para Sharpe sob retornos autocorrelacionados
  formula: SR_corrigido = SR_ingenuo x  q / sqrt( q + 2 x sum_{k=1..q-1} (q-k) rho_k )
  q: horizonte de agregacao (barras por periodo de reporte)
  rho_k: autocorrelacao amostral dos retornos de trade
  erro_padrao: Newey-West com lag = ceil(1.5 x h)
  reporte: SR_ingenuo E SR_corrigido, sempre lado a lado
  entrada_do_DSR: SR_corrigido
```

**Diagnóstico:** se `SR_corrigido / SR_ingênuo < 0,70`, a estratégia depende de agrupamento temporal e o intervalo de confiança do Monte Carlo está subestimado.

## 16.6 Decomposição de PnL: carry vs alpha — RF-029 (NOVO)

Se o funding for persistentemente positivo (longs pagam shorts), posições vendidas ganham **carregamento estrutural**. O modelo aprende "short é bom" e isso é chamado de alpha quando é carry trade — um fator que não requer modelo nenhum e que pode inverter.

```
PnL_total = PnL_direcional + PnL_carry + PnL_execucao

PnL_direcional = qty x (P_exit - P_entry) x side        # movimento puro
PnL_carry      = - sum(funding_rate x notional x side)   # carregamento
PnL_execucao   = (P_fill - P_ref) x qty - fees           # slippage + seleção adversa + fees
```

**Reportado por trade e agregado, sempre separado.** Métricas derivadas:

| métrica | interpretação |
|---|---|
| `carry_share` = PnL_carry / PnL_total | se > 0,30, a estratégia é majoritariamente carry |
| `directional_sharpe` | Sharpe só do componente direcional |
| `side_carry_asymmetry` | PnL_carry médio de long vs short |

**Gate 3 revisado:** `directional_sharpe > 0` isoladamente. Uma estratégia cujo Sharpe total é positivo mas cujo Sharpe direcional é negativo é um carry trade com um classificador caro em cima.

**Baseline B5 (novo):** short permanente com o mesmo sizing, isolando o carry puro.

## 16.7 Segurança e credenciais — RF-030 (NOVO)

Ausente por completo na v3.0.

```yaml
api_keys:
  permissoes:
    enable_futures:  true
    enable_reading:  true
    enable_spot:     false
    enable_withdraw: false      # NUNCA
    enable_internal_transfer: false
    enable_margin:   false
  ip_whitelist: obrigatorio, IP fixo da maquina de execucao
  rotacao: 90 dias, com procedimento testado
  chaves_separadas:
    live:    permissoes de trade, IP restrito
    research: somente leitura, sem IP restrito
    testnet: chaves distintas, base_url distinta

segredos:
  storage: variaveis de ambiente carregadas de arquivo fora do repo
  proibido: chave em codigo, em config versionada, em log, em mensagem de erro
  ci: scan de segredo em pre-commit; build falha se detectar padrao de chave
  logs: mascaramento de api_key e signature em TODA saida estruturada

incidente_de_vazamento:
  1. revogar chave na Binance (imediato)
  2. KILL_SWITCH manual
  3. verificar ordens e posicoes nao reconhecidas
  4. gerar chave nova com novo IP whitelist
  5. registrar no audit log
```

**Kill switch, gatilho 15 (novo):** ordem ou posição detectada na exchange sem `client_order_id` conhecido — já existia como gatilho 6, agora com procedimento de resposta explícito, porque o cenário mais provável é chave comprometida.

## 16.8 Preenchimento parcial na saída — RF-031 (NOVO)

A v3.0 tratou fill parcial só na entrada. Se o TP limite enche parcialmente, sobra posição residual sem proteção coerente.

| situação | ação |
|---|---|
| TP enche parcialmente, resíduo ≥ 1 unidade | **reduzir o stop para a qty residual** (cancelar e repostar), manter TP no resíduo |
| TP enche parcialmente, resíduo < 1 unidade | impossível pelo `LOT_SIZE` — não ocorre; se ocorrer, `TRADING_HALT` |
| SL stop-market enche parcialmente | raro em market; se ocorrer, **fechar resíduo a mercado imediatamente** |
| time stop enche parcialmente | fechar resíduo a mercado, sem espera |

**Invariante:** após qualquer evento de fill, `qty_stop == qty_tp == qty_position`. Divergência ⟹ `TRADING_HALT`.

```python
on_fill_event(e):
    place_or_amend_stop(qty=position.qty)     # SEMPRE primeiro
    place_or_amend_tp(qty=position.qty)
    assert stop.qty == tp.qty == position.qty
```

## 16.9 Encerramento do projeto e pré-registro — RF-032 (NOVO)

Existia kill switch de sessão; não existia kill switch de projeto. Sem critério pré-comprometido, a decisão de parar é tomada com apego ao sistema construído.

**Pré-registro — escrito e datado ANTES do Sprint 8, antes de qualquer resultado OOS:**

```yaml
pre_registro:
  hipotese: declarada em uma frase falseavel
  features_T1: lista congelada
  barreiras: tp_mult, sl_mult, time_stop congelados
  metrica_primaria: DSR sobre Sharpe corrigido por autocorrelacao
  limiar_de_sucesso: numero, escrito antes
  baselines: B1..B5 com criterios
  N_lifetime_inicial: contador zerado e versionado
```

Qualquer alteração posterior ao pré-registro é **emenda registrada**, com data e justificativa, e incrementa `N_lifetime`.

**Critérios de encerramento — cada um dispara revisão formal obrigatória:**

| # | condição | ação |
|---|---|---|
| 1 | DSR < 0,50 após 6 meses de live | encerrar ou voltar ao Gate 0 |
| 2 | Sharpe live < percentil 50 do baseline B1 por 3 meses | encerrar |
| 3 | equity < US$ 150 (piso do kill switch 13) | encerrar |
| 4 | `carry_share` > 0,50 sustentado | reclassificar: não é o projeto proposto |
| 5 | `N_lifetime` > 5.000 sem DSR > 0,95 | encerrar — o espaço foi exaurido |
| 6 | preço do BTC acima do teto de granularidade por 30 dias | suspender até aporte ou mudança de TF |
| 7 | venue indisponível (§13.3) | suspender |

**Anti-HARKing:** o relatório final compara o resultado contra o pré-registro literal. Hipótese reformulada depois de ver os dados é registrada como reformulação, não como confirmação.

## 16.10 Registro de proveniência de constantes — RF-033 (NOVO)

**Esta é a seção mais importante da v3.1.** Auditoria interna revelou que a maioria dos números deste blueprint é invenção sem base. O documento inteiro passa a exigir proveniência declarada para cada constante.

```yaml
# config/constants.yaml — TODA constante do sistema tem esta estrutura
cost_stop_ratio_max:
  value: 0.20
  provenance: ASSUMED          # MEASURED | DERIVED | LITERATURE | ASSUMED
  source: "sem base; escolhido por conveniencia"
  class: A                     # A|B|C|D — ver §16.10.1
  sweep_required: true
  sweep_range: [0.10, 0.40]
  review_by: sprint_10
```

### 16.10.1 Classificação por consequência do erro

| classe | definição | tratamento obrigatório |
|---|---|---|
| **A** | erro invalida o desenho | varredura de sensibilidade antes do Gate 3; `ASSUMED` proibido em produção |
| **B** | entra no espaço de busca | otimizável, **mas cada uma incrementa `N_lifetime`** |
| **C** | guardrail operacional | definido por **quantil da distribuição medida**, nunca por número redondo |
| **D** | cosmético | livre |

### 16.10.2 Regras de prevenção

1. **Nenhum literal numérico no código.** Toda constante vem de `constants.yaml`. Lint falha se encontrar número mágico fora de teste.
2. **CI bloqueia classe A com `provenance: ASSUMED`** em qualquer build marcado para live.
3. **Guardrails classe C são quantis, não números.** Em vez de `spread_max_bps: 3.0`, usar `spread_max: p95(spread_observado, janela=90d)`. Auto-adaptativo e auditável.
4. **Varredura de sensibilidade obrigatória** para toda classe A: `±50%` em grade, reportando a superfície de Sharpe. Se o resultado for fio de navalha, **o número está fazendo o trabalho que deveria ser do modelo** — e isso é um achado, não um detalhe.
5. **Ledger de trials vitalício.** `N_lifetime` é arquivo versionado no repo, incrementado por toda constante classe B otimizada, todo retreino e todo challenger. O DSR usa `N_lifetime`.
6. **Distribuições esperadas vêm de simulação, não de opinião.** Faixas como "TP entre 30 e 40%" só entram no documento depois de calculadas sobre os labels reais.

### 16.10.3 Gate 0 revisado

Passa a exigir, além dos critérios econômicos:

```
toda constante classe A tem provenance != ASSUMED
varredura de sensibilidade executada para todas as classe A
N_lifetime declarado e versionado
pre-registro assinado e datado
```

## 16.11 Gate 0 contínuo — RF-034 (NOVO)

O preço do BTC é variável aleatória. A viabilidade do desenho depende dele. Logo o Gate 0 não pode ser evento único.

```yaml
gate0_continuo:
  frequencia: a cada barra de decisao
  recalcula:
    unit_notional     = step_size x mark_price
    N_req             = risk_usd / stop_pct
    units             = N_req / unit_notional
    quantization_error
    breakeven_win_rate
    fee_budget_remaining
  bloqueia_entrada_se:
    quantization_error > quantization_tolerance
    breakeven_win_rate > breakeven_max
    fee_budget_remaining <= 0
  alerta:
    price_headroom_pct < 20    # distancia ate o teto de preco
  metrica_de_dashboard: btc_price_ceiling, price_headroom_pct
```

**Teto de preço atual (15m, stop 0,458%):** US$ 107.568. Preço hoje: US$ 64.940. Folga: 66%.

Quando a folga cair abaixo de 20%, o sistema alerta; abaixo de 0%, para de abrir posições e exige decisão: aportar capital, mudar de TF, ou suspender.

---

# PARTE XVII — ESTUDO DE NÃO-ESTACIONARIEDADE

**Base empírica:** 230.784 barras de 15m, 2020-01-01 a 2026-07-31, série completa da `data.binance.vision`.
**Pergunta:** o BTC de 2026 é diferente o bastante para que um motor treinado no passado não lucre hoje?
**Consome:** §0.4 (ATR medido) · §2.13 (T1) · §4.3.1 (regime econômico) · §5.0 (concentração) · §11.3.1 (similaridade) · §11.4.1 (walk-forward).

## 17.1 — O que mudou — medido, não presumido

### 17.1.1 Volatilidade é cíclica, não decadente

| ano | ATR(20) 15m mediano | custo/ATR | breakeven WR (maker) | efficiency ratio | AC(1) | VR(4) |
|---|---|---|---|---|---|---|
| 2020 | 0,372% | 14,8% | 47,1% | 0,112 | −0,023 | 0,94 |
| 2021 | **0,499%** | **11,0%** | **46,1%** | 0,120 | +0,005 | 1,05 |
| 2022 | 0,441% | 12,5% | 46,5% | 0,113 | +0,008 | 1,05 |
| 2023 | **0,277%** | **19,9%** | **48,6%** | 0,109 | −0,030 | 0,95 |
| 2024 | 0,361% | 15,2% | 47,3% | 0,113 | −0,004 | 1,01 |
| 2025 | 0,297% | 18,5% | 48,2% | 0,122 | −0,006 | 0,95 |
| **2026** | **0,284%** | **19,4%** | **48,4%** | 0,123 | −0,021 | 0,97 |

Três leituras que contrariam a intuição:

1. **A volatilidade não caiu monotonicamente.** Vai de 0,277% (2023) a 0,499% (2021) — amplitude de 1,8x, oscilando. **2026 (0,284%) é praticamente idêntico a 2023 (0,277%).**
2. **2023 foi pior que 2026 em custo relativo** — 19,9% contra 19,4%. O ambiente atual não é inédito; é a repetição de um estado já visto.
3. **A estrutura de previsibilidade incondicional não mudou.** Autocorrelação de primeira ordem oscila em torno de zero em todos os anos; a razão de variância fica entre 0,94 e 1,05 (1,0 = passeio aleatório). Não há tendência secular rumo a "mais eficiente".

*(Minha medição anterior de 8 meses sugeriu colapso monotônico de volatilidade. Estava errada — era artefato da amostra por conveniência. É o terceiro erro dessa mesma família nesta conversa, e reforça a regra do §16.10.)*

### 17.1.2 O que de fato mudou

**Custo relativo à volatilidade: de 11,0% para 19,4%.** Fator 1,8x.

Este é o mecanismo real pelo qual "o motor que lucrou antes não lucra agora", e ele é sutil:

```
barreiras são escaladas por ATR      →  adaptam ao regime automaticamente
custos são fixos em bps              →  NÃO adaptam

2021:  TP = 2,0 × 0,499% = 0,998%  |  custo 0,055% = 5,5% do TP
2026:  TP = 2,0 × 0,284% = 0,568%  |  custo 0,055% = 9,7% do TP
```

O mesmo `tp_atr_mult: 2.0` produz geometrias econômicas diferentes conforme o regime. **O motor não "deixa de funcionar" — ele silenciosamente exige mais edge para o mesmo resultado.** O breakeven sobe de 46,1% para 48,4%.

O contexto qualitativo confirma a direção: relatórios de 2026 descrevem <cite index="14-1">faixas de volatilidade comprimidas pontuadas por movimentos bruscos e narrativos, com o mercado menos eufórico que em ciclos anteriores e estruturalmente mais complexo</cite>, e <cite index="12-1">correções recentes com menos expansão de volume de varejo e menos picos de liquidação em relação a 2021-2022, indicando mecânica de fluxo institucional em vez de estresse conduzido por exchange</cite>. <cite index="17-1">Fluxo institucional é alocação persistente e programática, criando um bid estrutural em drawdowns que comprime volatilidade ao longo do tempo.</cite>

---

## 17.2 — O teste decisivo: o sinal decaiu?

Information Coefficient (Spearman) entre cada feature e o retorno futuro de 32 barras (8h, igual ao `time_stop`), normalizado por volatilidade para ser comparável entre anos.

| feature | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 | consistência de sinal |
|---|---|---|---|---|---|---|---|---|
| `ret_vol_norm_4` | −0,024 | −0,001 | −0,030 | −0,045 | −0,016 | −0,001 | −0,014 | **100%** |
| `taker_imb_z_48` | −0,017 | −0,006 | −0,011 | −0,021 | −0,006 | −0,011 | −0,012 | **100%** |
| `rsi_14` | −0,034 | +0,004 | −0,041 | −0,064 | −0,007 | −0,004 | −0,009 | 86% |
| `zscore_close_48` | −0,015 | −0,007 | −0,046 | −0,046 | −0,000 | −0,017 | +0,000 | 86% |
| `dist_ema48_atr` | −0,009 | −0,009 | −0,033 | −0,050 | +0,000 | −0,024 | **+0,017** | 71% |
| `efficiency_ratio_48` | +0,004 | −0,010 | +0,018 | −0,018 | **+0,042** | −0,013 | **−0,031** | **57%** |
| `vol_ratio_12_96` | +0,029 | −0,016 | −0,001 | +0,002 | −0,002 | +0,031 | +0,003 | **57%** |
| `volume_z_96` | +0,025 | −0,016 | −0,003 | +0,001 | −0,011 | +0,014 | +0,019 | **57%** |

**Força média do sinal por ano** (média de `|IC|` entre features):

```
2020  0,0196
2021  0,0087   ← o PIOR ano
2022  0,0228
2023  0,0308   ← o MELHOR ano
2024  0,0105   ← segundo pior
2025  0,0142
2026  0,0133   ← meio da tabela
```

### 17.2.1 As três conclusões

**(1) O sinal não decai — ele oscila, com amplitude de 3,5x.** E 2026 (0,0133) é **melhor** que 2021 (0,0087) e 2024 (0,0105). A premissa "o motor que lucrou ano passado pode não lucrar em 2026" é verdadeira como preocupação, mas a direção implícita — que 2026 é pior — não se sustenta nos dados.

**(2) Duas features sobreviveram a tudo.** `ret_vol_norm_4` (reversão de curto prazo) e `taker_imb_z_48` (fluxo de agressor contrário) têm sinal negativo em **100% dos sete anos**, atravessando o ciclo de varejo de 2021, o bear de 2022, a chegada dos ETFs em 2024 e o regime institucional de 2026. Isso é a coisa mais valiosa neste documento.

**(3) Quatro features são cara-ou-coroa.** `efficiency_ratio_48` é o caso grave: 57% de consistência, com IC de **+0,042 em 2024 e −0,031 em 2026** — inverte de sinal. E eu a coloquei em T1 **e** a usei como eixo de definição de regime.

**Correção:** ER sai do vetor T1 como feature direcional. **Permanece como eixo de partição de regime** — descrever "quão tendencial está o mercado" não exige estabilidade de sinal; prever direção a partir disso, sim. `vol_ratio_12_96` e `volume_z_96` recebem o mesmo tratamento: rebaixadas a T2 até que a ablação prove o contrário.

### 17.2.2 O número desconfortável

`|IC|` entre 0,012 e 0,023 é **fino**. Para referência de campo, IC de 0,03–0,05 é considerado bom em equities.

Não faço a conversão direta para "isso cobre o custo" — as barreiras são assimétricas e o IC marginal de uma feature isolada subestima o que um modelo com interações e condicionamento por regime extrai. Mas a margem não é obviamente confortável, e **é exatamente essa a pergunta que os baselines B1 e B3 (§16.1) existem para responder**. Se o Alpha não superar entrada aleatória com significância, a resposta é que não havia edge — não que o modelo precisa de mais features.

---

## 17.3 — Como o motor aprende o estado atual

### 17.3.1 O que NÃO fazer: treinar só em dados recentes

Este é o reflexo natural e, nestes dados, é o erro.

A literatura de concept drift é explícita: <cite index="9-1">esquemas de adaptação passiva restringem os dados de treino a um horizonte recente via janelas deslizantes, pesos decaindo ou ensembles dinâmicos; funcionam bem para drift suave e unidirecional, mas não exploram regimes recorrentes — uma vez que o conceito antigo é esquecido, ele precisa ser reaprendido quando retorna.</cite>

**O BTC tem regimes recorrentes, não drift unidirecional.** A prova está na tabela §1.1: 2023 e 2026 são quase gêmeos — ATR 0,277% vs 0,284%, custo/ATR 19,9% vs 19,4%. E 2023 é **o ano de maior sinal de toda a série**.

Treinar só nos últimos 2 anos descartaria 2023 — simultaneamente o ambiente mais parecido com hoje e o de melhor sinal. É autolesão.

O mesmo vale para peso por decaimento temporal (AFML cap. 4, parâmetro `c`): decaimento agressivo tem o mesmo efeito de forma mais suave. **`c` não deve ser escolhido a priori — deve ser varrido pelo walk-forward** (§4), que é o único método capaz de medir se recência ajuda ou atrapalha.

### 17.3.2 O que fazer — cinco camadas

### Camada 1 — Estacionariedade do espaço de features (já 80% feita)

Se as features são quantis expansivos e z-scores em vez de níveis brutos, "percentil de volatilidade 0,8 em 2021" e "percentil 0,8 em 2026" significam a mesma coisa para o modelo. O regime muda; a representação não.

T1 já é majoritariamente assim: `vol_pctile_expanding`, `volume_z_expanding`, `funding_z_expanding`, `spread_pctile_expanding`, `oi_change_z`, `taker_imbalance_z`, e as demais são razões ou limitadas (RSI, ER, book imbalance).

**Isso não foi sorte de desenho — é a razão pela qual duas features mantiveram sinal por 7 anos.**

### Camada 2 — `cost/ATR` como cidadão de primeira classe (LACUNA)

É a variável que efetivamente mudou (11,0% → 19,4%) e ela **não é feature nem eixo de regime** no blueprint. Precisa ser as duas coisas:

```yaml
# nova feature T1 — substitui efficiency_ratio_48
E27f_cost_atr_ratio:
  formula: "custo_round_trip_bps / (atr_20_pct × 10000)"
  tier: T1
  racional: >
    Barreiras escalam com ATR e adaptam ao regime; custos são fixos em bps
    e não adaptam. Esta razão captura diretamente a degradação econômica
    que o modelo, de outro modo, teria que inferir indiretamente.

# novo eixo de regime — terceira dimensão
regime_cost:
  ECONOMICS_FAVORABLE:  cost_atr_ratio < p33 expansivo
  ECONOMICS_NEUTRAL:    p33 <= ratio < p66
  ECONOMICS_HOSTILE:    ratio >= p66

# novo gate operacional
gate0_continuo:
  bloqueia_entrada_se: cost_atr_ratio > cost_atr_max   # classe A, varrer
```

A tabela §1.1 mostra que este gate teria bloqueado grande parte de 2023 e 2026 e liberado 2021 — que é exatamente o comportamento desejado, **e é economicamente motivado em vez de estatisticamente ajustado**.

### Camada 3 — Ponderação por similaridade, não por recência (LACUNA)

Em vez de "treine nos últimos N meses", **pese cada observação histórica pela proximidade do estado de mercado dela ao estado de hoje**. Isso explora regimes recorrentes em vez de esquecê-los.

```python
estado(t) = [ vol_pctile(t), cost_atr_ratio(t), regime_estrutural(t), funding_z(t) ]

w_similaridade(t) = exp( −||estado(t) − estado(t_treino_fim)||² / (2σ²) )
w_final(t)        = uniqueness(t) × |ret_net(t)| × w_similaridade(t)
```

Com isso, treinando hoje (custo/ATR 19,4%), **2023 (19,9%) recebe peso alto e 2021 (11,0%) recebe peso baixo** — automaticamente, sem que ninguém precise decidir "cortar dados antigos".

É a implementação prática de recuperação por contexto macro. `σ` é hiperparâmetro classe B — entra no `N_lifetime`.

**Baseline obrigatório:** comparar contra peso uniforme e contra decaimento temporal puro. Se a similaridade não superar as duas, ela sai.

### Camada 4 — Validação condicional a regime, não modelo por regime

Com ~1.800 a 3.000 observações efetivas, **não** se ajustam cinco modelos separados. Mas é obrigatório **validar em cada regime separadamente**.

```
Gate 4 revisado:
  Sharpe > 0 em cada regime R1..R4 individualmente          (não na média)
  Sharpe > 0 em cada faixa de cost_atr_ratio (baixa/média/alta)
  Sharpe > 0 em cada ano, ou explicação registrada do porquê não
```

Se o modelo só funciona em `ECONOMICS_FAVORABLE`, isso não é falha — é **especificação**: o motor passa a ter um gate de regime econômico e opera menos.

### Camada 5 — Walk-forward como instrumento de medição (§4)

---

## 17.5 — Resumo executivo

**O que mudou de fato:** o custo relativo à volatilidade quase dobrou (11,0% → 19,4%), elevando o breakeven de 46,1% para 48,4%. Volatilidade oscilou mas não decaiu. A estrutura incondicional de previsibilidade não mudou.

**O que não mudou:** reversão de curto prazo e fluxo de agressor contrário mantiveram sinal em 100% dos sete anos, atravessando o ciclo de varejo, o bear, a chegada dos ETFs e o regime institucional.

**A premissa do Manager está certa em espírito e errada em direção:** 2026 não é o pior ano da série. 2021 e 2024 foram piores. O risco real não é "2026 é ruim" — é que **a força do sinal varia 3,5x entre anos de forma imprevisível**, e um motor validado num ano forte vai decepcionar num ano fraco.

**A resposta não é treinar em dados recentes.** É estacionarizar as features (feito), tratar `cost/ATR` como feature e como regime (lacuna), pesar por **similaridade de estado** em vez de recência (lacuna), validar por regime em vez de na média (lacuna) e **medir a taxa de decaimento com walk-forward** em vez de assumir cadência de retreino (lacuna, agora especificada).

**O que ainda pode matar o projeto:** IC entre 0,012 e 0,023 é fino. Se ele não cobre o custo, nenhuma dessas camadas resolve — e os baselines B1 e B3 vão dizer isso antes do live, que é exatamente para o que servem.

---

# PARTE XVIII — REGISTRO DE PROVENIÊNCIA DE CONSTANTES

**Auditoria interna do próprio blueprint.** Das 187 constantes numéricas, ~130 (70%) não têm base verificada. Esta parte classifica todas e define os seis mecanismos de prevenção. Implementa §16.10.

## 18.1 — Escala de proveniência

| nível | definição | quantas |
|---|---|---|
| **P0 — VERIFICADO** | consultado em fonte externa nesta conversa (API, dump, doc oficial, paper) | 14 |
| **P1 — DERIVADO** | aritmética sobre P0; correto se P0 estiver correto | 21 |
| **P2 — MEDIDO (parcial)** | medi de dados reais, mas com amostra por conveniência | 8 |
| **P3 — LITERATURA** | heurística com origem rastreável, sem derivação | 9 |
| **P4 — INVENTADO** | escolhi por parecer razoável. Sem base. | **~130** |
| **P5 — HERDADO** | veio do PRD V2, nunca questionado por mim nem por ele | 5 |

---

## 18.2 — O que É confiável (P0)

Estes eu conferi diretamente:

| constante | valor | como verifiquei |
|---|---|---|
| `step_size` BTCUSDT | 0,001 BTC | dump + `exchangeInfo` |
| `min_notional` | 50 USDT | anúncio Binance, mudou de 100 em 2026-04-14 |
| maker / taker | 0,02% / 0,05% | tabela de fees Binance |
| desconto BNB | −10% | idem |
| início de `metrics` | 2020-09-01 | listei o bucket S3 |
| granularidade de `metrics` | 5 min, 289 linhas/dia | baixei e li o arquivo |
| colunas de `metrics` | 8, nomeadas | idem |
| existência de `markPriceKlines` / `premiumIndexKlines` | confirmada | baixei e li |
| catálogo `futures/um/daily` | 9 diretórios | listagem S3 |
| mudança de assinatura REST | 2026-01-15 | changelog Binance |
| descomissionamento de WS legado | 2026-04-23 | idem |
| BTC | ~US$ 64.940 | busca |
| USD/BRL | 5,08 | busca |
| MMR tier 1 | 0,40% | conhecimento padrão — **não consegui verificar**, endpoint bloqueado do container |

⚠️ O MMR é o único P0 que não consegui confirmar. Verificar antes de usar.

---

## 18.3 — O que medi, mas mal (P2)

| constante | valor | problema |
|---|---|---|
| ATR(20) mediano 5m / 15m / 30m / 1h | 0,163 / 0,305 / 0,440 / 0,626 % | **8 meses de 71 disponíveis**, escolhidos por conveniência (junho de cada ano + 2 meses de 2026) |
| percentis p25/p75 do ATR | vários | mesma amostra |
| fração de barras na janela (60,9% a 15m) | idem | mesma amostra |
| teto de preço do BTC por TF | US$ 107.568 a 15m | derivado da mediana de ATR acima |

**O viés é conhecido e direcional:** junho é sistematicamente um mês, não o ano. E incluí dois meses de 2026 e nenhum de 2020. A distribuição real de ATR pode estar deslocada em qualquer direção.

**Isso importa muito** porque a escolha de 15m depende dela. Se o ATR mediano verdadeiro a 15m for 0,45% em vez de 0,305%, o stop vira 0,675%, ainda dentro da janela — mas as unidades caem de 3,32 para 2,25 e o teto de preço do BTC despenca para US$ 73 mil, 12% acima do preço de hoje.

**Refazer sobre a série completa é tarefa do Sprint 3, não opcional.**

---

## 18.4 — Heurísticas de literatura (P3)

Rastreáveis, mas sem derivação. Todas são priores, não resultados:

| constante | valor | origem | força |
|---|---|---|---|
| obs por parâmetro | 200–500 | *events per variable* (~10 EPV, bioestatística) inflado por praticantes | fraca |
| PBO máximo | 0,30 | AFML, convenção | média |
| embargo | 1% do fold | sugestão de López de Prado | média |
| purge por `t1` | — | AFML cap. 7 | **forte** |
| unicidade média | fórmula | AFML cap. 4 | **forte** |
| CPCV > walk-forward | — | Arian et al. 2024 | forte |
| seleção adversa maker | existe | Albers et al., experimento no perp BTC da Binance | **forte** (existência), nula (magnitude) |
| correção de Lo | fórmula | Lo (2002) | forte |
| block bootstrap | método | Politis & Romano | forte |

Note que os métodos são fortes; os **limiares** (0,30; 1%; 200–500) são convenções.

---

## 18.5 — O que inventei — e o que acontece se estiver errado

### 18.5.1 CLASSE A — invalidam o desenho (11 constantes)

Se estas estiverem erradas, o motor está errado e nenhum teste do blueprint detecta.

| constante | valor | de onde veio | se errar |
|---|---|---|---|
| **`tp_atr_mult`** | 2,0 | **herdado do V2, nunca questionado** | define toda a geometria de payoff. O breakeven WR de 48,1% é função direta dele |
| **`sl_atr_mult`** | 1,5 | **herdado do V2** | idem |
| **`cost_stop_ratio_max`** | 0,20 | inventei | define o piso da janela de stop. A 0,30 o piso cai para 0,183% e 5m volta a ser viável |
| **`quantization_tolerance`** | 0,25 | semi-derivado (0,5 unidade de arredondamento) | define o teto da janela. Foi o que consertou meu erro do "≥3 unidades" |
| **`fee_budget_monthly`** | 0,03 | inventei | determina taxa de sinal, threshold do Alpha e contagem de trades. Cascateia por tudo |
| **`risk_per_trade`** | 0,005 | derivado de R1+R2 — mas R1 e R2 usam constantes inventadas | circular |
| **`time_stop_bars`** | 32 (8h) | justifiquei por "uma janela de funding" — isso é estética pós-hoc | define amostra efetiva e teto de features |
| **`atr_window`** | 20 | convenção de mercado, sem teste | define a própria medida de volatilidade |
| **taxa de sinal alvo** | 1,89% | derivada do orçamento de fees inventado | é o threshold do Alpha |
| **corte de regime `ER`** | q60 | inventei | define a partição de regime inteira |
| **corte de regime `vol`** | 0,70 | inventei | idem |

**Os dois primeiros são os mais graves.** `TP 2,0 / SL 1,5` atravessou V2 → auditoria → V3 → V3.1 sem ninguém — eu inclusive — perguntar de onde veio. E é a constante que mais determina o resultado: com passeio aleatório puro, essa razão já fixa o win rate em 42,9%.

### 18.5.2 CLASSE B — hiperparâmetros (22 constantes)

Legítimo otimizá-las. Ilegítimo otimizar sem contar:

`max_depth: 3` · `n_estimators: 300` · `learning_rate: 0,03` · `subsample: 0,8` · `colsample_bytree: 0,8` · `min_child_weight: 30` · `reg_lambda: 5,0` · janelas de EMA (12, 24, 48) · RSI (14, 48) · ER (16, 48) · vol_ratio (12/96) · janelas de z-score (48, 96) · `n_groups: 6` · `n_test_groups: 2` · limiar de ortogonalidade `0,70` · `min_warmup_bars: 2000` · `cooldown: 4 barras` · `fill_timeout_bars: 1` · `mean_block_length: 20`

Todos inventados. `min_child_weight: 30` em particular — escolhi porque "amostra pequena pede piso alto", que é raciocínio correto e número arbitrário.

**As janelas de lookback das 106 features são todas inventadas.** EMA48, ATR20, RSI14, z-score de 48 — nenhuma testada. Isso é um espaço de busca enorme escondido dentro do que parece ser "definição de feature".

### 18.5.3 CLASSE C — guardrails operacionais (~50 constantes)

Aqui o problema não é o valor, é a **forma**. Todos são números redondos onde deveriam ser quantis da distribuição observada:

| constante | valor inventado | o que deveria ser |
|---|---|---|
| `spread_max_bps` | 3,0 | `p95(spread, 90d)` |
| `depth_min` | 4 unidades | `p10(depth_20bps, 90d)` |
| staleness de barra / book | 90s / 5s | `p99(intervalo entre updates)` |
| `vol_pctile` stress | 0,98 | ok (já é quantil) |
| `funding_z` stress | 3,0 | `p99(|funding_z|)` |
| basis stress | 100 bps | `p99(|basis|)` |
| `liq_z` stress | 4,0 | `p99(liq_z)` |
| desconexão | 120s | medir distribuição de reconexão |
| tempestade de erros | 10 em 60s | medir taxa base |
| drift de relógio | 500ms | derivar de `recvWindow` (5000ms padrão) |
| reconciliação | 30s | ok, é escolha de custo |
| tolerâncias de reconciliação | 0,01 / 0,05 USDT | derivar de tick size |
| perda diária | 2% | herdado do V2 |
| max drawdown | 10% | herdado do V2 |
| perdas consecutivas | 5 | inventado |
| `IM ≤ 60% equity` | 0,60 | inventado |
| `max_leverage` / `max_notional_multiple` | 3,0 | herdado do V2 |
| piso de equity | US$ 150 | inventado (≈2,3 unidades — semi-derivado) |
| `naked_window` timeout | 2000ms | inventado |
| keepalive | 1800s | **derivado** (metade dos 60min da Binance) — este está certo |

### 18.5.4 CLASSE C-crítica — distribuições que fabriquei (§3.6)

O pior caso do documento. Escrevi como se fossem expectativas fundamentadas:

```
TP     30–40%      ← inventado
SL     35–45%      ← inventado
TIME   20–30%      ← inventado
NOFILL 10–25%      ← inventado
```

E chamei de "detectores de configuração errada". São quatro faixas que saíram da minha cabeça e que, se usadas como especificado, vão fazer você recalibrar barreiras corretas para bater números fictícios.

**Mesma categoria:** `adverse_selection_bps: 1,5` (rotulei como placeholder conservador, mas não há nada de conservador em um número sem base — continua P4 até o Paper medir, §9.5.1) · erro de `p_fill` ≤ 0,10 · fill rate mínimo 60%.

**Corrigido na v3.3:** o antigo "seleção adversa máxima 3 bps" era P4 — número redondo sem derivação. Foi substituído por uma tabela de sensibilidade (§9.6): o limiar agora é **P1 — DERIVADO** (aritmética sobre `tp_atr_mult`, `sl_atr_mult` e o ATR mediano medido, §18.3), com limite em 5,0 bps e ruptura do Gate 0 em 7,6 bps. Isso não cobre o risco RPI em si — a magnitude do impacto do RPI sobre a seleção adversa continua P4 até medida no Paper (§9.5.1).

### 18.5.5 CLASSE C-crítica — limiares de Gate (~25 constantes)

Todos os critérios de aprovação são inventados:

`quality_score ≥ 0,995` · `DSR > 0,95` · `Sharpe positivo em 4 de 5 caminhos` · `desvio entre caminhos < 50% da média` · `breakeven_win_rate ≤ 0,55` · `Testnet: 200 ordens, 2 semanas` · `Paper: 60 dias, 60 trades` · `divergência de Sharpe < 40%` · `fill rate ±15 pp` · `seleção adversa ±2 bps` · `Brier < 0,25` · Meta: `3.000 obs, +5 pp, 4 folds, Brier 0,22` · Kelly: `5.000 obs, Brier 0,20, 6 meses` · encerramento: `DSR < 0,50 em 6 meses`, `N_lifetime > 5.000`

**`N_effective = 960`** (4 × 40 × 3 × 1 × 2) merece menção separada: cada fator é inventado, e o produto entra diretamente no cálculo do DSR — a métrica que decide se o sistema vai ao ar.

---

## 18.6 — Como prevenir — seis mecanismos

O erro que cometi duas vezes nesta conversa (ATR presumido; "≥3 unidades") tem uma assinatura comum: **um número plausível, escrito com confiança, propagando-se por dezenas de conclusões sem nunca ser marcado como suposição.** Os mecanismos abaixo atacam a assinatura, não os números individuais.

## M1 — Proveniência obrigatória, verificada em CI

Toda constante em `constants.yaml`, com `provenance`, `class` e `source`. Nenhum literal numérico no código — lint falha em número mágico fora de teste.

**CI bloqueia build de produção se qualquer constante classe A tiver `provenance: ASSUMED`.** Isso torna impossível chegar ao live com `tp_atr_mult` não justificado.

## M2 — Varredura de sensibilidade antes do Gate 3

Para cada uma das 11 constantes classe A: grade de ±50%, reportando a superfície de Sharpe.

**O critério de aprovação não é "o Sharpe é bom no valor escolhido". É "o Sharpe é robusto na vizinhança".** Se o resultado for um pico estreito, o número está fazendo o trabalho que deveria ser do modelo — e isso é o achado, não um detalhe de tuning.

Prioridade da varredura: `tp_atr_mult` × `sl_atr_mult` conjuntamente (grade 2D), depois `cost_stop_ratio_max`, `fee_budget_monthly`, `time_stop_bars`.

## M3 — Guardrails como quantis, não como números

Substituir toda constante classe C por função da distribuição observada:

```python
# ERRADO — número redondo que envelhece mal
spread_max_bps = 3.0

# CERTO — quantil recalculado, auditável, auto-adaptativo
spread_max = rolling_quantile(spread_bps, window="90d", q=0.95)
```

Isso resolve ~50 constantes de uma vez e as torna robustas a mudança de regime de liquidez.

## M4 — Distribuições esperadas vêm de simulação

Nenhuma faixa esperada entra no documento antes de ser calculada. O §3.6 vira:

```
Sprint 6 → construir labels
         → medir distribuição real de barrier_hit
         → escrever a faixa observada ± 2 desvios como banda de controle
         → SÓ ENTÃO usar como detector
```

Até lá, o campo fica literalmente `TBD — medir no Sprint 6`, não uma faixa inventada.

## M5 — Ledger de trials vitalício

`N_lifetime` é arquivo versionado. Incrementa em: cada constante classe B otimizada, cada retreino, cada challenger, cada emenda ao pré-registro.

Isso resolve o problema que o `N = 960` esconde: o DSR reportado hoje considera uma busca; o `N` verdadeiro é tudo que já foi tentado desde o V2 — incluindo as três mudanças de timeframe (5m → 1h → 30m → 15m) desta conversa, cada uma um trial.

## M6 — Pré-registro dos valores classe A

Congelar os 11 valores classe A, com justificativa e resultado da varredura, **antes** de ver qualquer resultado OOS. Mudança posterior é emenda datada que incrementa `N_lifetime`.

Isso impede a falha mais cara: ajustar `tp_atr_mult` até o backtest ficar bonito e depois reportar o Sharpe como se a barreira tivesse sido escolhida a priori.

---

## 18.7 — Ordem de ataque

| # | ação | sprint | por quê |
|---|---|---|---|
| 1 | **Refazer a medição de ATR sobre a série completa** | 3 | a escolha de 15m depende de 8 meses de amostra |
| 2 | **Varredura 2D de `tp_atr_mult` × `sl_atr_mult`** | 6 | herdados sem questionamento, definem o payoff |
| 3 | Medir `N_eff` real via unicidade | 6 | substitui a fórmula errada |
| 4 | Medir a distribuição de `barrier_hit` | 6 | substitui as faixas fabricadas do §3.6 |
| 5 | Converter guardrails classe C em quantis | 12 | ~50 constantes de uma vez |
| 6 | Calibrar `adverse_selection_bps` contra fills reais | 9 | hoje é 1,5 sem base |
| 7 | Varrer `cost_stop_ratio_max` e `fee_budget_monthly` | 10 | determinam a janela e a taxa de sinal |
| 8 | Verificar MMR tier 1 | 2 | único P0 não confirmado |
| 9 | Iniciar `N_lifetime` com o histórico desta conversa | 1 | já há trials gastos |

### 18.7.1 — Nota de implementação para o item 2 (auditoria de engenharia, 2026-08-09)

Auditoria comparativa contra um projeto irmão (Laplace_Quant_V16, forex
multi-par) trouxe dois pontos concretos para quando a varredura 2D de
`tp_atr_mult` × `sl_atr_mult` do item 2 for implementada. Registrados aqui
— não implementados agora — para não se perderem até o Sprint 6.

**(a) Rodar a varredura SEPARADAMENTE por lado, não assumir simetria.**
`LabelConfig` hoje usa um `tp_atr_mult`/`sl_atr_mult`/`time_stop_bars`
único para os dois lados (`side * sl_atr_mult`, mesmo multiplicador, sinal
invertido — §3.3/§3.4). Essa simetria nunca foi medida, só herdada
(`tp_atr_mult`/`sl_atr_mult` são §18.5.1, "herdado do V2, nunca
questionado"). O projeto irmão roda grid search independente por direção
(`triple_barrier_v14.py::_grid_pass(..., pass_dir=+1|-1)`, inclusive com
grade de `time_stop` diferente por lado) — e há motivo agora, não só
teórico, pra desconfiar da simetria aqui: uma investigação anterior a
esta nota (Faixa 1, `experiments/faixa1_calibration_diagnostic.json`)
mediu, de forma independente, que long e short se comportam de modo
estruturalmente diferente em quase toda dimensão observada (sinal de
`E02f_funding_z` por regime, ordenação do score cru por decil, taxa de
NOFILL por decil). Escopo do Sprint 6: rodar o grid 2D uma vez por lado
(`tp_atr_mult_long`/`sl_atr_mult_long` × `tp_atr_mult_short`/
`sl_atr_mult_short`), comparar contra a variante simétrica atual pelo
mesmo critério de permanência já usado em outras camadas (§5.11), e só
manter a versão assimétrica se ela realmente vencer — não assumir a
priori que assimetria é melhor.

**(b) Técnica de implementação — busca vetorizada via `sliding_window_view`.**
`src/analysis/cost_surface.py` varre o grid rotulando a série inteira uma
vez por célula (`build_labels_both_sides`, ~50-60s medido por combinação,
§ nota do próprio módulo) — factível pro grid 3×3 já rodado, mais caro
pra um grid 2D maior com `time_stop` variável. O projeto irmão implementa
a detecção de toque de barreira via `numpy.lib.stride_tricks.
sliding_window_view` sobre `high`/`low` (`triple_barrier_v14.py::
compute_labels_vectorized`), testando TODAS as combinações de TP/SL sem
loop Python por barra. Não é código diretamente portável (a versão daqui
precisa de `mark_1m`, fill simulado, funding e quantização — mais rica
que a do projeto irmão, que não tem nenhum desses), mas a TÉCNICA de
vetorização é diretamente aplicável na hora de escrever a varredura real:
usar `sliding_window_view` sobre `mark_1m` em vez de rotular a série
inteira uma vez por célula do grid.

---

## 18.8 — A conclusão desconfortável

O blueprint tem 2.478 linhas e parece rigoroso. A estrutura é sólida — os contratos, as invariantes, a separação de responsabilidades, os testes de vazamento, a ordem dos gates. **Isso vale, e não muda.**

Mas os *números* dentro da estrutura são majoritariamente meus, e a confiança com que foram escritos não corresponde ao que os sustenta. Um documento que diz `time_stop_bars: 32` com a mesma tipografia com que diz `step_size: 0.001` está mentindo por omissão, porque o segundo eu conferi e o primeiro eu escolhi.

O mecanismo M1 existe exatamente para tornar essa diferença visível na página. Depois dele, o blueprint não fica mais correto — fica **honesto sobre onde ainda não é**.

---

# PARTE XIX — MAPA DE RASTREABILIDADE

Cada requisito debatido, com destino e evidência.

| # | requisito | seção | origem da decisão | evidência |
|---|---|---|---|---|
| 1 | USDⓈ-M only, BTCUSDT | §0.1 | restrição do Manager | migração CM-UM em curso |
| 2 | Capital R$ 1.000 = US$ 196,85 | §0.1 | restrição do Manager | USD/BRL 5,08 |
| 3 | Erro de quantização como restrição real | §0.2 R1, §8.3 c9a | correção — "≥3 unidades" não tinha base | 0,5 unid ÷ tolerância |
| 4 | Resolução de sizing ≥ 2 unidades | §8.3 c9b | 2h passava por sorte de arredondamento | dispersão p90/p10 3,05x |
| 5 | Execução maker assimétrica | §0.3, §9.1 | breakeven 53,4% → 48,1% | fees Binance |
| 6 | Alavancagem não é controle de risco | §8.6 | janela idêntica de 3x a 20x | liquidação a 74% vs stop 0,458% |
| 7 | TF de decisão 15m | §0.4 | ATR medido, não presumido | 79 arquivos, 4 TFs |
| 8 | 1h/2h/4h eliminados; 5m condicional | §0.5 | Gate 0 aritmético | tabela de capital mínimo |
| 9 | 30m como robustez, não competidor | §0.5 | evita seleção por ruído | N_lifetime fator 1 |
| 10 | Teto de preço do BTC | §0.4, §16.11 | preço é variável aleatória | US$ 107.568 a 15m |
| 11 | 15 dumps + 5 forward + 6 externas | §1.1 | anexo do Manager + catálogo S3 | D10/D11 P0 |
| 12 | OI resolvido por dump (não API) | §1.1 D04 | retratação do F8 | metrics desde 2020-09-01 |
| 13 | Filtros versionados por data | §1.4 | MIN_NOTIONAL mudou em 2026-04-14 | anúncio Binance |
| 14 | 106 features enumeradas | §2.2–2.12 | pedido de blueprint | — |
| 15 | T1 medido, não estipulado | §2.0.1, §0.2 R4 | fórmula de concorrência estava errada | LdP cap.4 vs 2h−1 |
| 16 | `E27f_cost_atr_ratio` em T1 | §2.6, §2.13 | única variável que mudou de fato | 11,0% → 19,4% |
| 17 | `B07` sai de T1, fica como regime | §2.13, §4.2 | IC inverte de sinal | +0,042 (2024) / −0,031 (2026) |
| 18 | Barreiras em mark price 1m | §3.4 | Binance dispara stop por mark | — |
| 19 | Desfecho `NOFILL` | §3.2 | maker não garante preenchimento | — |
| 20 | `t1` e `config_hash` obrigatórios | §3.5 | purge e paridade label↔execução | AFML cap.7 |
| 21 | 5 regimes determinísticos | §4.3 | 8 estados HMM não cabem na amostra | label switching |
| 22 | Terceiro eixo: regime econômico | §4.3.1 | custo/ATR não era eixo nem feature | §17.1 |
| 23 | **Dois modelos binários** | §5.2 | multiclasse impede monotone_constraints | — |
| 24 | **Camada 1: restrições monotônicas** | §5.3 | impede sinal invertido por ruído | IC 7/7 anos |
| 25 | **Camada 2: triagem in-fold** | §5.4 | consistência² inverte a preferência do boosting | §17.2 |
| 26 | **Camada 3: bagging por grupo** | §5.5 | colsample aleatório não cria diversidade | — |
| 27 | **Camada 4: DoubleEnsemble** | §5.6 | desenhado para baixo SNR + muitas features | Zhang et al. 2020 |
| 28 | **Camada 5: Group DRO** | §5.7 | pior ambiente, não média | V-REx |
| 29 | **Gate de concentração (HHI)** | §5.8, Gate 3/4 | sem métrica nada é verificável | HHI < 0,25 |
| 30 | Cronograma treino/aplicação | §5.9 | resposta direta à pergunta do Manager | 14 janelas |
| 31 | Ablação camada a camada com parada | §5.11 | 5 camadas = 5 entradas no N_lifetime | — |
| 32 | `ensemble_std`, `n_models_agree` | §5.12 | discordância = edge de conceito único | — |
| 33 | Meta: OOF obrigatório (`is_oof`) | §5.12, §6 | vazamento estrutural Alpha→Meta | — |
| 34 | Meta rebaixado a V1.1 | §6.8 | ~1.600 obs efetivas vs 11 features | — |
| 35 | Restrição de marginalidade do Meta | §6.4 | Grupo J é a única margem real | — |
| 36 | Baselines nulos B1–B5 | §16.1, Gate 3 | TP2,0/SL1,5 já dá 42,9% por construção | — |
| 37 | Janela nua fill → stop | §16.2 | reduce_only exige posição | — |
| 38 | `listenKey` keepalive | §16.3 | expira em 60 min | doc Binance |
| 39 | Retreino + champion-challenger | §16.4 | ausente; cada retreino infla N | — |
| 40 | Sharpe corrigido por autocorrelação | §16.5 | DSR não corrige AC | Lo (2002) |
| 41 | Decomposição carry vs alpha | §16.6, Gate 3 | carry vira "alpha" por engano | — |
| 42 | Segurança de chaves | §16.7 | ausente por completo | — |
| 43 | Fill parcial na saída | §16.8 | só a entrada estava coberta | — |
| 44 | Pré-registro e encerramento | §16.9 | anti-HARKing | — |
| 45 | Proveniência de constantes | §16.10, PARTE XVIII | 70% sem base | — |
| 46 | Gate 0 contínuo | §16.11 | preço do BTC é aleatório | — |
| 47 | Ponderação por similaridade | §11.3.1 | recência descartaria 2023 | regimes recorrentes |
| 48 | Walk-forward completo | §11.4.1 | era uma frase sem implementação | G-WF-1..6 |
| 49 | Robustez por regime no Gate 4 | Gate 4 | "funciona na média" esconde falha | — |
| 50 | Estudo de não-estacionariedade | PARTE XVII | pergunta do Manager | 230.784 barras |
| 51 | Ordens RPI desde 2025-11-20 | §1.1 F06, §2.7.1 | fato de venue verificado | docs Binance |
| 52 | Check 23 — quebra semântica de fonte | §1.3 | schema passa, significado muda | — |
| 53 | Grupo F fora de T1 até coleta forward | §2.7.1, §2.13 | definição quebrada, não desempenho | 381 obs pós-quebra |
| 54 | Experimento A/B RPI | §9.5.1, Gate 8 | somos o varejo-alvo do mecanismo | — |

## Fora de escopo por decisão do Manager

| item | razão |
|---|---|
| Custo total de propriedade (VPS, energia, câmbio BRL↔USDT) | controle de alocação do Manager, não variável do motor |

## Erros corrigidos ao longo da elaboração

| # | erro | onde estava | correção |
|---|---|---|---|
| 1 | OI limitado a 30 dias | auditoria F8 | dump `metrics` tem desde 2020-09-01 |
| 2 | Concorrência `1+s(2h−1)` como "a fórmula" | v3.0 §0.2 R4 | é o pior caso; LdP usa `s·h` — virou medição |
| 3 | ATR presumido de vol 40% | v3.0 §0.1 | medido: percentil 13 da distribuição real |
| 4 | Amostra de 8 meses sugerindo colapso de vol | análise de TF | série completa mostra ciclo, não declínio |
| 5 | "≥ 3 unidades" como restrição | v3.0 §0.2 R1 | sem base; real é erro de quantização + resolução |
| 6 | TF 30m como ótimo | v3.0 §0.4 | ATR medido move para 15m |
| 7 | Walk-forward "especificado" | v3.0 §11.4 | era uma frase; agora §11.4.1 com 6 gates |
| 8 | Distribuições de `barrier_hit` | §3.6 | fabricadas — viram TBD medido no Sprint 6 |
| 9 | Simulador de fila especificado sobre `bookTicker` | §9.5 v3.0–v3.2 | fonte exclui RPI desde 2025-11-20; trocar para `rpiDepth` forward |

**Erros 2, 3 e 4 são a mesma família:** número plausível, escrito com confiança, propagado sem marca de suposição. É a razão de existir da PARTE XVIII.

---
## Registro de mudanças V2 → V3

| # | mudança | origem |
|---|---|---|
| 1 | COIN-M → **USDⓈ-M** `BTCUSDT` / `fapi` | decisão do usuário; confirmada pela migração CM-UM em curso |
| 2 | Capital fixado em R$ 1.000 = US$ 196,85 | restrição do usuário |
| 3 | TF de decisão 5m → **30m** | maker moveu o ótimo; taker apontava 1h |
| 4 | Execução taker → **maker post-only, SL taker** | reduz breakeven de 53,4% para 48,7% |
| 5 | `risk_per_trade` 0,25–0,50% → **0,50% fixo** | janela vazia a 0,25% |
| 6 | `max_leverage: 3` → `max_notional_multiple: 3.0` + `exchange_leverage: 10` | alavancagem não é controle de risco |
| 7 | **Gate 0** de viabilidade econômica | ausente no V2 |
| 8 | Controles de risco 6–10 (lote, granularidade, quantização) | ausentes no V2 |
| 9 | Orçamento de fees como contador vivo | ausente no V2 |
| 10 | `time_stop` 96 → **16 barras** | amostra efetiva 903 → 3.240 |
| 11 | Barreiras em **mark price 1m** | V2 não especificava a série |
| 12 | Desfecho **`NOFILL`** | inexistente no V2 |
| 13 | `t1` e `config_hash` como colunas obrigatórias | V2 não tinha schema |
| 14 | Features: ~50 sem tier → **106 catalogadas, 12 em T1** | teto por amostra efetiva |
| 15 | Regimes: 8 estados HMM → **5 determinísticos** + HMM na V1.1 | amostra, ortogonalidade, label switching |
| 16 | **`is_oof`** e OOF obrigatório para o Meta | vazamento estrutural no V2 |
| 17 | **Meta rebaixado para V1.1** com critério de entrada | 1.590 obs efetivas vs 11 features |
| 18 | Walk-forward → **CPCV** primário | PBO e DSR superiores |
| 19 | Experiment tracking V1.1 → **Sprint 6** | DSR era incalculável no V2 |
| 20 | Monte Carlo i.i.d. → **block bootstrap** | preserva autocorrelação |
| 21 | Leakage: 9 → **14 testes** | encadeamento, calibração, filtros, paridade |
| 22 | Stress: 11 → **18 cenários** | fill rate, seleção adversa, mudança de filtros |
| 23 | Gates: 9 → **11** (Gate 0 e Gate 10) | |
| 24 | Fontes: implícitas → **15 dumps + 5 forward + 6 externas** | D10 e D11 são P0 |
| 25 | Filtros de instrumento **versionados por data** | `MIN_NOTIONAL` mudou em 2026-04-14 |
| 26 | Simulador de fila com bookTicker + aggTrades | seleção adversa era ignorada |
| 27 | `hmmlearn` → determinístico / `dynamax` | stack vintage |
| 28 | Motor de backtest próprio → **avaliar NautilusTrader** | maior risco caseiro do projeto |
| 29 | Pandas core → **Polars core** | |
| 30 | Kill switch: 10 → **13 gatilhos** | inclui piso de equity de US$ 150 |

---
## Registro de mudanças v3.2 → v3.3

**Gatilho:** fato de venue verificado em 2026-08-08 — desde 2025-11-20 a Binance Futures opera ordens RPI (Retail Price Improvement), post-only, invisíveis a `bookTicker`/`GET /fapi/v1/depth`, sem dump histórico. Decisão do Manager: prosseguir, risco aceito e mitigado, não bloqueante.

| # | mudança | origem |
|---|---|---|
| 1 | Nova fonte forward **F06 `rpiDepth`** (REST + WS `Diff-Book-Depth-RPI`), P0 desde Sprint 2 | §1.1 — sem RPI, o simulador de fila subestima `queue_ahead` |
| 2 | Data Quality Engine: **check 23 — quebra semântica de fonte**, `config/venue_changelog.yaml` | §1.3 — schema pode passar e o significado ainda assim mudar |
| 3 | Nova subseção **§2.7.1** — quebra de definição do Grupo F em 2025-11-20 | §2.7.1 — book visível deixou de ser book completo |
| 4 | **T1: 12 → 10 features.** `F02f_spread_pctile_expanding` e `F04f_book_imbalance_l1` saem por quebra de definição, não por desempenho | §2.13 — retornam com ≥ 6 meses de coleta forward de `rpiDepth` |
| 5 | `monotone_constraints`, bagging por grupo conceitual (Camada 3) e HHI de concentração atualizados para 10 features | §5.3, §5.5, §5.8 — consequência direta da mudança 4 |
| 6 | `rpi_regime` ∈ {PRE, POST} como dimensão de ambiente na triagem de estabilidade | §5.4 — penaliza automaticamente feature cuja definição mudou no meio da amostra |
| 7 | Simulador de fila: fontes divididas em `sources_pre_2025_11_20` / `sources_post_2025_11_20`, aviso explícito de não-simulabilidade histórica | §9.5 — não há dump de `rpiDepth`; fills pós-quebra só são calibráveis para a frente |
| 8 | Assimetria RPI modelada como dois pools de liquidez (stop-loss taker não consome RPI) | §9.5 |
| 9 | Novo modo de execução `LIMIT_GTX_RPI` e **experimento A/B §9.5.1** (RPI vs post-only comum, Sprint 16, ≥60 fills/braço, conta como 1 trial no `N_lifetime`) | §9.1, §9.5.1 |
| 10 | §9.6 recalibrado: tabela de sensibilidade da seleção adversa (0,91 pp por bp; margem confortável até 4,3 bps; Gate 0 rompe em 7,6 bps), substitui o limiar solto de "3 bps" | §9.6 — números DERIVED, não ASSUMED (§18) |
| 11 | Gate 5 (Cost Stress) e Gate 8 (Paper) atualizados com o novo limiar de 5,0 bps e com a exigência de decisão registrada do experimento §9.5.1 | PARTE XII |
| 12 | PARTE XIX: requisitos 51–54 e erro corrigido #9 (simulador de fila especificado sobre `bookTicker`, que exclui RPI) | PARTE XIX |

**Não é regressão de escopo.** A V1 não perde capacidade: perde duas features de microestrutura que já não significavam o que diziam significar, e ganha um mecanismo (check 23 + `rpi_regime`) que detecta a próxima quebra silenciosa deste tipo sem depender de alguém lembrar de procurar por ela.