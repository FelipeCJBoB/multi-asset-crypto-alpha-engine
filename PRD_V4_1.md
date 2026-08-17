# PRD V4.1 — REABERTURA ESTRUTURAL MULTI-ATIVO E MULTI-TIMEFRAME

**Versão:** 4.1 · **Data:** 2026-08-09
**Natureza:** emenda ao `PRD_V3_2_UNIFICADO.md`; substitui o V4.0
**Base factual verificada:** `exchangeInfo` (5 símbolos) · catálogo `data.binance.vision` por fonte × ativo · `code_discovery.json` (ddc0362) · `inventario_master.json` (160) · `n_lifetime.yaml` (45)

> **Emenda, não substituição.** O DSR depende de `N_lifetime`, que acumula desde o Sprint 8. Documento novo perde o rastro de 45 trials e torna o Gate 6 incalculável. O V3.2 permanece como fonte de contratos, invariantes e banned patterns.

---

# PARTE 0 — O QUE MUDA E POR QUÊ

## 0.1 A descoberta que reabre o projeto

O V3.2 inteiro foi construído sobre uma restrição que se revelou **propriedade do instrumento, não do mercado**:

```
BTCUSDT   stepSize 0,001 × US$ 73.570 = US$ 73,57 = 37,37% do equity
SOLUSDT   stepSize 0,01  × US$  86,35 = US$  0,86 =  0,44% do equity
XRPUSDT   stepSize 0,1   × US$   1,39 = US$  0,14 =  0,07% do equity
```

**O BTCUSDT tem a unidade mais cara entre os cinco ativos analisados.** A restrição R1 (quantização), que escolheu 15m, eliminou 30m/1h/2h/4h, derivou `risk_per_trade = 0,50%` e gerou os controles 9a/9b, **não vincula em nenhum stop testado no SOL, ETH ou XRP**.

| ativo | passos de sizing @ stop 1,5×ATR | erro de quantização |
|---|---|---|
| BTC | **3,1** | **16,2%** |
| BNB | 35,4 | 1,4% |
| ETH | 79,3 | 0,6% |
| SOL | 173,1 | 0,3% |
| XRP | **1.246,8** | **0,0%** |

## 0.2 E a economia acompanha

**Tabela original (ATR de Wilder, amostra de 4 meses, 2025-11 a 2026-07) — mantida por proveniência, NÃO usar para decisão:**

| ativo | ATR 15m | `custo_atr` | breakeven | trades/ano no orçamento |
|---|---|---|---|---|
| **SOL** | 0,439% | 0,131 | **46,5%** | **862** |
| ETH | 0,391% | 0,147 | 46,9% | 767 |
| XRP | 0,379% | 0,152 | 47,1% | 745 |
| BTC | 0,289% | 0,199 | **48,3%** | 568 |
| BNB | 0,288% | 0,200 | 48,4% | 565 |

**Remedida (2026-08-12) — Garman-Klass (vencedor de M1, §3.2), série completa por ativo, `decision_tf=15m`:**

| ativo | GK 15m (mediano) | `custo_atr` | breakeven | trades/ano |
|---|---|---|---|---|
| **SOL** | 0,406% | 0,135 | TBD — não remedido | TBD — não remedido |
| XRP | 0,312% | 0,176 | TBD — não remedido | TBD — não remedido |
| ETH | 0,289% | 0,190 | TBD — não remedido | TBD — não remedido |
| BTC | 0,241% | 0,228 | TBD — não remedido | TBD — não remedido |
| BNB | 0,235% | 0,234 | TBD — não remedido | TBD — não remedido |

`breakeven`/`trades/ano` **não foram remedidos** — não existe uma função canônica no repo que os produza (só `custo_atr` tem implementação localizada, `group_e.e27f_cost_atr_ratio`); os valores da tabela original foram calculados manualmente quando o PRD foi escrito, nunca viraram código. Derivar essa fórmula formalmente (DERIVED, validada contra o texto atual) é trabalho pendente, não fabricado aqui.

O custo é fixo em bps; a volatilidade não. Ativo mais volátil **dilui** o custo. Isso continua verdade, mas **a ordenação mudou**: XRP e ETH trocaram de posição (XRP tinha `custo_atr` pior que ETH na amostra de 4 meses; na série completa XRP é melhor). Só os extremos (SOL melhor, BTC/BNB piores) se confirmaram estáveis. Os valores absolutos de `custo_atr` pioraram entre 13% e 29% para BTC/ETH/XRP/BNB na série completa — a amostra de 4 meses capturou um regime de volatilidade mais alto que a média histórica.

✅ **Ressalva original resolvida (2026-08-12), com achado.** ATR medido sobre 4 meses foi substituído por Garman-Klass sobre a série completa de cada ativo (M1, §3.2) — `experiments/volatility_operational_effect_report.json`. A previsão "a ordenação entre ativos é provavelmente estável" **só acertou parcialmente**: verdadeira para os extremos (SOL/BTC), falsa para o par ETH/XRP. Nota de honestidade: esta remedição muda estimador (ATRWilder→GK) e janela (4 meses→completa) ao mesmo tempo — os dois efeitos não foram isolados formalmente (ver §3.2, painel 07/08 do artefato de M1 na sessão de 2026-08-12).

## 0.3 Os três fechamentos indevidos do V3

| estágio | argumento que o fechou | por que caiu |
|---|---|---|
| Regime (HMM) | "8 estados não cabem em 3.240 obs efetivas" | `N_eff` medido = **32.608** |
| Meta-Model | "~1.590 obs efetivas contra 11 features" | com `N_eff` correto, **~13.000** |
| Timeframe 30m/1h | eliminados por aritmética de lote | ATR de 8 meses; e a restrição é do BTC, não do mercado |

## 0.4 Escopo da V4.1

**Cinco ativos** — BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, XRPUSDT — como **medição aberta**, sem favorito declarado.
**Três timeframes** — M15, M30, H1 — obrigatórios ponta a ponta.
**Quinze combinações** de treino e validação. Execução em subconjunto que passe nos gates.

---

# PARTE I — A ÁLGEBRA DA COMPARAÇÃO

## 1.1 O problema

O custo é fixo em bps e a volatilidade varia 1,5x entre os ativos. **Comparar desempenho em bps mede o ativo, não o sinal.** Um resultado melhor no SOL pode ser sinal melhor ou custo menor, e as duas conclusões levam a decisões opostas.

## 1.2 A solução — tudo em unidades de ATR

```
edge_bruto_atr = frac_TP × tp_mult − frac_SL × sl_mult        adimensional, sem custo
custo_atr      = custo_round_trip_bps / (ATR_pct × 100)       o mesmo custo, na escala do ativo
edge_liq_atr   = edge_bruto_atr − custo_atr
captura        = edge_liq_atr / edge_bruto_atr                fração do sinal que sobrevive
```

`edge_bruto_atr` é **invariante ao ativo** — mede geometria de acerto, normalizada por volatilidade. `custo_atr` carrega toda a diferença econômica. `captura` é a ponte.

## 1.3 Por que isso importa — o mesmo sinal, cinco resultados

Um `edge_bruto_atr = 0,25` idêntico nos cinco:

| ativo | `custo_atr` | `edge_liq` | **captura** | bps/trade |
|---|---|---|---|---|
| SOL | 0,131 | +0,119 | **47,5%** | +5,21 |
| ETH | 0,147 | +0,103 | 41,1% | +4,02 |
| XRP | 0,152 | +0,098 | 39,2% | +3,72 |
| BTC | 0,199 | +0,051 | **20,3%** | +1,46 |
| BNB | 0,200 | +0,050 | 20,0% | +1,44 |

**O mesmo sinal rende 3,6x mais no SOL que no BTC.**

## 1.4 Regra de reporte — invariante do projeto

> **Nenhuma decisão sobre um número só.** Todo relatório emite `edge_bruto_atr`, `custo_atr`, `edge_liq_atr` e `captura`, por ativo, por TF, por lado e por regime. Comparação entre ativos usa `edge_bruto_atr` para sinal e `captura` para economia — **nunca `ret_net` isolado**.

✅ **Achado corrigido (2026-08-12) — a fórmula estava certa, a implementação estava ausente, e isso já mudou.** Correção honesta sobre um achado anterior meu, no mesmo dia: eu havia registrado aqui "o PRD não explica onde/como aplicar esta álgebra" — falso. §1.2 já dá a fórmula exata (`edge_bruto_atr = frac_TP×tp_mult − frac_SL×sl_mult`; `edge_liq_atr = edge_bruto_atr − custo_atr`; `captura = edge_liq_atr/edge_bruto_atr`), e §1.3 até valida numericamente. O que faltava era só código. `src/analysis/feasibility.py` (2026-08-12) implementa as quatro funções — `custo_atr`/`edge_bruto_atr`/`edge_liq_atr`/`captura` — testadas contra os números JÁ PUBLICADOS aqui no §1.3 (SOL: edge_liq=+0,119, captura=47,5% — bate). `edge_bruto_atr` precisa de `frac_TP`/`frac_SL` reais (`frac_tp_sl_from_labels`, lê `labels.parquet::barrier_hit`) — ainda falta rodar a agregação estratificada por (symbol, tf, lado, regime) sobre os dados reais das 15 combinações; as funções em si já existem e estão testadas.

## 1.5 Breakeven por ativo

`edge_bruto_atr` mínimo para EV zero é exatamente `custo_atr`:

```
SOL 0,131 · ETH 0,147 · XRP 0,152 · BTC 0,199 · BNB 0,200
```

Referência histórica: `long×R3` do V3 entregou `edge_bruto_atr = 0,226` — acima do breakeven do BTC (0,199) por margem de 13%, e acima do SOL (0,131) por 73%.

---

# PARTE II — RESTRIÇÕES DESCOBERTAS

Cinco falhas de dado e três inconsistências de desenho, todas verificadas.

## 2.1 F1 — `metrics` começa 15 meses depois nos quatro não-BTC

| ativo | BTC | ETH | SOL | BNB | XRP |
|---|---|---|---|---|---|
| início de `metrics` | **2020-09** | 2021-12 | 2021-12 | 2021-12 | 2021-12 |

Atinge `E10f_oi_change_z_48` e `E17f_retail_vs_top_spread` — **duas features de T1** — e todo o Grupo E derivado de OI.

**Decisão: janela comum 2021-12-01 → 2026-08-01.** Perde 15 meses do BTC. Validação transversal só significa algo se o período for o mesmo.

## 2.2 F2 — BVOL só existe para BTC e ETH

`C13_bvol_index`, `C14_bvol_z_90d` e `C15_iv_rv_spread` **não são computáveis** para SOL, BNB e XRP. Sem substituto gratuito.

**Decisão:** T3 com bloqueio por fonte declarado no registry. Nenhuma feature de T1 pode depender de fonte indisponível em qualquer um dos cinco.

## 2.3 F3 — `indexPriceKlines` do SOL atrasa 4 meses

Início 2021-01 contra 2020-09 do resto do SOL. Dentro da janela comum (2021-12) **o problema desaparece** — resolvido por F1.

## 2.4 F4 — `bookTicker` desde 2023-05 e RPI corrompe desde 2025-11

Janela útil de microestrutura: **2023-05 → 2025-11, ~30 meses** (teórico/upstream — texto original, mantido por proveniência). ⚠️ **Correção 2026-08-12 (verificado contra `data/raw/book_ticker/`, os 5 símbolos):** o que está de fato baixado localmente é **2023-05-16 → 2024-03-30, ~10,5 meses (320 dias), idêntico nos cinco** — não os ~30 meses acima. `CLAUDE.md` "Estado atual" já tinha o número certo ("D08/D09 bookTicker só existe 2023-05→2024-03 upstream"); este §2.4 nunca tinha sido conferido contra o disco. Não sei se a diferença é backfill incompleto (dá pra estender baixando mais) ou limite real do upstream — **TBD, verificar antes de assumir qualquer um dos dois**. Grupo F permanece fora do T1 (§2.7.1 do V3.2). Simulador de fila restrito à janela real (10,5 meses), não a teórica.

**Consequência não trivial:** no período 2021-12 → 2023-05 (17 meses do treino comum) o **spread por ativo é não observável**. Assumir custo igual entre ativos com dispersão de volume de 3.700x é premissa forte, e vai declarada.

## 2.5 F5 — `daily/klines` começa 2023-06, `monthly/klines` vai a 2020

Armadilha de implementação. O downloader precisa usar `monthly/` para histórico longo. **Teste obrigatório** que falhe se a partição errada for escolhida.

## 2.6 I1 — Volume varia 3.700x

| ativo | volume mediano USD/15m | vs BTC |
|---|---|---|
| XRP | 1.858.168 | 3.696x |
| SOL | 75.574 | 150x |
| ETH | 13.987 | 28x |
| BNB | 1.946 | 3,9x |
| BTC | 503 | 1,0x |

*(Números do `quote_volume` do dump; o valor do BTC parece baixo demais — **verificar a unidade da coluna antes de usar**. Registrado como suspeita, não como fato.)*

Nocional de US$ 150 é fração desprezível em todos — **liquidez não vincula**. O spread relativo vincula, e F4 impede medi-lo no início do treino.

## 2.7 I2 — `atr_window` e `time_stop` não têm conversão única entre TFs

```
        ATR(20) cobre    time_stop 32 barras
M15          5,0h                8,0h
M30         10,0h               16,0h
H1          20,0h               32,0h
```

Em **barras**, os três TFs medem coisas diferentes — a comparação vira artefato de agregação. Em **relógio** (ATR de 5h, stop de 8h), o H1 usaria ATR de 5 barras, ruidoso demais para ser o mesmo estimador.

**Não há solução única.** Decisão de desenho que precede a implementação, e acopla-se à Camada 1: o estimador de volatilidade precisa ser recalibrado por TF, com o **horizonte em relógio fixo** e a janela em barras derivada. Ver §3.2 M1.

## 2.8 I3 — Os cinco ativos são ~1,15 ativos

Correlação de log-retornos 15m:

```
        BTC     ETH     SOL     BNB     XRP
BTC   1.000   0.951   0.861   0.915   0.912
ETH   0.951   1.000   0.918   0.932   0.936
SOL   0.861   0.918   1.000   0.881   0.912
BNB   0.915   0.932   0.881   1.000   0.931
XRP   0.912   0.936   0.912   0.931   1.000
```

**Fatores efetivos: 1,15 de 5** (participation ratio dos autovalores).

**Consequência 1 — a justificativa do multi-ativo muda.** Não é replicação estatística; com ρ ≈ 0,91 um sinal que funciona no BTC funciona no ETH quase por construção. **É estresse econômico**: o mesmo sinal enfrentando lote de 37,37% do equity contra 0,07%, e `MIN_NOTIONAL` de 50 contra 5. Isso é real e é exatamente o gargalo do projeto.

**Consequência 2 — o `N_trial` não é 15.** Ver §6.2.

**Consequência 3 — a `N_eff` agregada é ~1,15×, não 5×.** O teto de features e o DSR usam isso.

## 2.9 I4 — Cinco posições correlacionadas não são cinco riscos

```
risco por trade:                        0,500%
2 posições simultâneas (ρ=0,91):  σ =   0,977%   (1,95x)
3 posições:                       σ =   1,454%   (2,91x)
5 posições:                       σ =   2,408%   (4,82x)
eficiência de diversificação:            46,4%
```

**Cinco long simultâneos são uma posição de 4,82x o risco declarado**, e 2,41% de risco efetivo quase esgota o `max_daily_loss` de 2% num único evento.

O Risk Engine hoje avalia cada posição isoladamente contra 0,50%. **Isso é falha de segurança, não de medição.** Ver §5.3.

## 2.10 I5 — A janela comum não é neutra

```
2021-11  pico do ciclo         US$  69.000
2021-12  INÍCIO DA JANELA      US$  47.000    ← logo após o topo
2022-11  fundo do bear         US$  16.000
2024-03  novo topo             US$  73.000
2025-07  pico                  US$ 115.000
2026-08  hoje                  US$  73.500
```

A janela **exclui a mania de 2020-2021** e começa numa queda. O viés de beta long que dominou a V3 — 94% em tendência de alta, lift 1,82x — deve enfraquecer.

**Consequência dura: os 28 verdes do inventário não são comparáveis com o que sair da janela nova.** O `long×R3`, que sobreviveu a todo o escrutínio da V3, pode não existir a partir de 2021-12.

**Obrigatório:** rodar o baseline atual na janela comum **antes** de qualquer coisa nova (§3.1 T0.5). Sem isso, todo resultado da V4.1 se confunde com efeito de janela.

---

# PARTE III — CAMADA 0 E CAMADA 1

## 3.0 Arquitetura

```
CAMADA 0 — refatoração habilitante + baseline na janela nova
CAMADA 1 — o que DEFINE uma observação
             volatilidade · barra · timeframe · regime · seleção de ativo
             → 5 de 6 medições contra alvo externo → poucos trials
             → PRD V4.2 escrito COM os resultados
CAMADA 2 — o que OPERA sobre a observação
             barreiras · meta-label · pesos · features · learner
CAMADA 3 — o que CONSOME a saída
             calibração · Meta-Model · walk-forward · validação completa
```

**Precedência causal:** se o estimador de volatilidade mudar, barreiras, sizing, `cost_atr_ratio` e o Grupo C mudam de definição simultaneamente. Nenhuma camada abre antes da anterior fechar com resultado registrado.

## 3.1 Camada 0 — Refatoração habilitante

**Sem isto nada é testável.** Zero trials.

### T0.1 — `VolatilityEstimator`

`fan_in` medido: **135 pontos**. `interface_existente: null`.

```python
class VolatilityEstimator(Protocol):
    def estimate(self, bars: Bars, *, horizon_minutes: int) -> FloatArray:
        """Volatilidade prevista para os próximos `horizon_minutes`.
        Horizonte em RELÓGIO, não em barras (I2).
        Causal: só informação disponível no fechamento de cada barra.
        Retorna fração do preço. NaN no warmup; nunca zero, nunca parcial."""
    @property
    def warmup_bars(self) -> int: ...
    @property
    def estimator_id(self) -> str: ...
```

Implementação inicial `ATRWilderEstimator` **bit-idêntica** — golden com tolerância zero contra `labels/v1/labels.parquet`.

**Impedimentos catalogados a resolver:**

| # | impedimento | arquivo:linha |
|---|---|---|
| I-a | `atr_wilder` chamado direto, `window` literal 20 | `research/research_t2.py:132` |
| I-b | `c01_atr_20(..., 20)` com literal em vez de `load_constant` | `src/analysis/faixa2_e2_research.py:116` |
| I-c | `barrier_sweep` lê `atr_at_t0` persistido, sem caminho de recomputo | `src/labels/barrier_sweep.py:123` |

**I-a e I-b são banned pattern ativo.** Sem corrigir, a varredura de `atr_window` diverge silenciosamente.

### T0.2 — `RegimeClassifier`

`fan_in` medido: **350 pontos**.

```python
class RegimeClassifier(Protocol):
    def classify(self, features: pl.DataFrame) -> pl.DataFrame:
        """Colunas: t0, regime, regime_raw, tradeable, classifier_id.
        Causal e online: barra t usa apenas índices < t."""
    @property
    def n_states(self) -> int: ...
    @property
    def classifier_id(self) -> str: ...
```

Implementação inicial `QuantileRegimeClassifier` bit-idêntica.

**Resolver no mesmo passo (I-d):** `classify_regimes` recalcula `er_quantile`/`econ_quantile` internamente mesmo quando `build_regimes` já passou `vol_pctile` pronto — assimetria sem ponto de injeção (`src/regime/classifier.py`).

### T0.3 — Chaveamento por (símbolo, TF)

Todo artefato passa a ser chaveado. Estrutura:

```
data/processed/{symbol}/{tf}/bars.parquet
data/features/{symbol}/{tf}/{feature_version}/
data/labels/{symbol}/{tf}/{label_version}/
predictions/alpha/{symbol}/{tf}/{model_id}/
```

`load_filters_asof(symbol, t)` — filtros são **por símbolo**, e mudam no tempo (`MIN_NOTIONAL` do BTC caiu 100→50 em 2026-04-14).

**Teste obrigatório (F5):** falha se o downloader usar `daily/klines/` para histórico anterior a 2023-06.

### T0.4 — Triagem das 54 divergências PRD↔código

Distribuição: BARRA 7 · VOLATILIDADE 4 · REGIME 6 · META-LABEL 6 · PESOS 1 · BARREIRAS 2 · FEATURES 4 · LEARNER 6 · CALIBRAÇÃO 3 · VALIDAÇÃO 11 · EXECUÇÃO 4.

**Regra: o código é a verdade**, salvo onde violar banned pattern (I-a, I-b) ou invariante declarada. Classificar cada uma em `corrigir-PRD`, `corrigir-código` ou `ambiguidade-de-vocabulário`.

### T0.5 — Baseline reprocessado na janela comum ⭐

**O item mais importante da Camada 0.** Rodar `alpha_c1_v1` sem alteração alguma sobre 2021-12 → 2026-08, BTCUSDT M15, e comparar contra os 28 verdes.

Emitir por célula lado×regime: `edge_bruto_atr`, `custo_atr`, `captura`, `directional_sharpe`, `n`.

**Sem isto, todo resultado da V4.1 é inconfundível de efeito de janela.** Zero trials — é a mesma configuração, outro período.

### T0.6 — `evidence_ledger.yaml`

Migrar as 160 entradas com campos novos: `estagio` · `symbol` · `tf` · `janela` · `tier` (0–3) · `mechanism` · `control` · `superseded_by` · `n_lifetime_cost`. Gerador de Mermaid a partir do ledger, nunca desenhado à mão.

⚠️ A classificação por estágio usada na análise preliminar **não existe no inventário** — foi produzida por regex sobre `feature_ou_filtro`. Os percentuais por estágio são indicativos, não medição. T0.6 corrige isso na fonte.

### Gate da Camada 0

```
G-C0-1  golden bit-exato para VolatilityEstimator e RegimeClassifier
G-C0-2  135 + 350 pontos de fan_in migrados
G-C0-3  I-a, I-b, I-c, I-d resolvidos
G-C0-4  artefatos chaveados por (symbol, tf); teste de partição monthly/daily passa
G-C0-5  54 divergências triadas
G-C0-6  baseline T0.5 emitido, com comparação explícita contra os 28 verdes
G-C0-7  evidence_ledger migrado com symbol, tf e janela
```

## 3.2 Camada 1 — Medições

### M1 — Volatilidade (0 trials)

**Candidatos:** `ATRWilder` (baseline) · `EGARCH(1,1)` · `HAR-RV` · `Parkinson` · `GarmanKlass` · `RealizedVol`.

**Alvo externo:** volatilidade realizada nos próximos `horizon_minutes`. Quantidade objetiva, não PnL.
**Métricas:** QLIKE (primária, robusta a outlier), MSE, viés, Mincer-Zarnowitz.
**Protocolo:** walk-forward ancorado, treino inicial 2 anos, passo trimestral. **Por ativo e por TF** — 15 combinações.

**Resolve I2 no mesmo passo:** cada estimador é calibrado com horizonte em **relógio fixo** e janela em barras derivada por TF. Emitir o QLIKE por TF para verificar se o mesmo horizonte de relógio é ótimo nos três.

**Emitir também:** efeito de cada estimador sobre `stop_pct` mediano, sobre `custo_atr` e sobre a fração de barras dentro da janela viável, **por ativo**.

**Refaz a medição de ATR de 4 meses sobre a série completa** (§0.2), corrigindo o erro que já cometemos duas vezes.

**Resultado (medido 2026-08-11/12, `experiments/volatility_comparison_report.json` commit `2410bc1`):** os 6 candidatos rodaram sobre as 15 combinações reais. Critério de encerramento §6.5-1 **não disparou**. Parkinson e Garman-Klass batem `ATRWilder` em QLIKE em 14/15 combinações (Garman-Klass vence a comparação direta Parkinson×GK em 9/14, Parkinson em 5/14); HAR-RV vence sozinho em ETHUSDT×H1 (1/15); EGARCH(1,1) e `RealizedVol` nunca vencem. **Decisão do Manager (2026-08-11): Garman-Klass é o vencedor de M1.**

> **Remedido sob dollar-bar em 2026-08-17** — Parkinson venceu 12/15 nessa medição separada (grade dollar-bar, não a grade de tempo acima). Ver `PLANO_MESTRE_PRINCE2.md` §11.4/§11.6 e `docs/refactor_parkinson_canonico.md` pro estado real: decisão tomada, ainda **não deployada** (`constants.yaml::canonical_volatility_estimator.value` continua `garman_klass_w20`).

**Extensão pós-M1, não prevista neste texto** (`experiments/volatility_rs_yz_vs_gk_report.json`, commit `2436b33`): testou Rogers-Satchell (1991, drift-independente) e Yang-Zhang (2000, soma componente overnight) contra o Garman-Klass. Resultado negativo — GK segue vencendo 10/15 combinações; Parkinson vence 4/15 (margens de −0,03% a −0,32%); Yang-Zhang vence 1/15; Rogers-Satchell não vence em nenhuma, e onde perde é com significância clara (Diebold-Mariano p<0,01 em 10/15). Nenhum candidato pós-M1 supera o vencedor. `ATRWilderEstimator`/`HAR-RV`/`EGARCH(1,1)`/`RealizedVol` foram amputados do harness de comparação (`src/analysis/volatility_comparison.py`) — o código de HAR-RV/EGARCH foi deletado (`src/features/volatility_models.py`, zero dependência de produção); `ATRWilderEstimator` (a classe) continua existindo em `src/features/volatility.py`, intocada, por depender dela um golden test contra `labels.parquet` de produção.

**Deliverables de `stop_pct`/`custo_atr`/janela viável e remedição de ATR sobre a série completa: FEITOS** (`experiments/volatility_operational_effect_report.json`, commit `a5e48be`, rodados só para os 4 candidatos vivos — GK/Parkinson/RS/YZ; os 4 amputados já perderam a métrica primária, recalcular seu efeito operacional não muda nenhuma decisão pendente e o resultado deles continua no git se precisar). Achado novo: R1 (quantização) só vincula de verdade em **BTCUSDT** (~9-10% das barras falham) — confirma numericamente pela primeira vez o que §0.1 já afirmava qualitativamente. Nos outros 4 ativos R1 falha em <0,02% das barras; o gargalo real em todo lugar é **R2** (custo/stop). Tabela §0.2 remedida com os números de GK.

**Não fechado ainda:** mapa de blast radius de ATR→GK em produção existe (`docs/refactor_gk_canonico.md`) mas a migração em si (Label Engine, Feature Engine, Regime Engine) **não foi executada** — GK é canônico só dentro do harness de comparação de M1, ainda não em produção. `breakeven`/`trades/ano` do §0.2 não foram remedidos (fórmula nunca virou código, ver §0.2).

### M2 — Barra (0 trials)

**Candidatos:** tempo (baseline) · dollar bars · volume bars · tick imbalance bars, calibradas para a mesma frequência média.

**Métricas:** Jarque-Bera · curtose · Ljung-Box em `r` e `r²` · ADF · **razão de amostra efetiva** (unicidade média com `time_stop` equivalente em relógio).

**Nota multi-ativo:** dollar bars normalizam por atividade. Com volume variando 3.700x (I1), elas podem tornar os cinco **mais** comparáveis que barras de tempo — hipótese testável, não assumida.

### M3 — Timeframe (0 trials)

Refazer o §0.5 do V3.2 com ATR da série completa e o estimador vencedor de M1, **por ativo**. Avaliar M15/M30/H1 contra R1 (quantização), R2 (custo), R3 (orçamento).

**Nota de honestidade:** 30m foi eliminado no V3.2 com `stop 0,659%` contra teto de `0,758%` — estava dentro. A eliminação foi por "menos unidades", não por inviabilidade. E o teto era do BTC.

**Resultado (medido 2026-08-14, `experiments/m3_timeframe_choice_report.json`, commit `daa1ab5`):** Garman-Klass (vencedor de M1), série completa por ativo, `atr_window=20` idêntico nos 3 TFs (I2 não resolvido, mesma ressalva herdada). `janela_viavel_fraction` (R1 **e** R2) por (ativo, TF):

| ativo | 15m | 30m | 1h |
|---|---|---|---|
| BTC | 58,2% | **65,5%** | 56,9% |
| BNB | 67,1% | 88,3% | 98,1% |
| ETH | 80,1% | 94,3% | 99,1% |
| XRP | 85,8% | 97,3% | 99,9% |
| SOL | 95,6% | 99,4% | **100,0%** |

**Achado central: BTC é o único ativo em que subir de TF não melhora monotonicamente a viabilidade — chega a piorar.** Nos outros 4 ativos, R1 (quantização) nunca vincula de verdade em nenhum TF (`r1_pass_fraction` entre 99,98% e 100% sempre) — `janela_viavel_fraction` sobe monotonicamente com o TF porque só R2 (custo) está em jogo, e custo dilui com TF maior. Em BTC, R1 **piora** com TF maior (`r1_pass_fraction`: 90,7%→78,1%→59,9% de 15m→30m→1h) — mecanismo: `notional_req = risk_usd/stop_pct`, e `stop_pct` cresce com TF, então o notional requerido por trade *encolhe*, ficando mais perto do lote mínimo caro do BTC (mesmo mecanismo de §0.1, agora medido nos 3 TFs, não só 15m). O resultado é `janela_viavel_fraction` não-monótona em BTC: melhor em 30m (65,5%) que em 15m (58,2%) OU 1h (56,9%) — o ponto-doce fica no meio, não na borda. Terceiro caller real, junto com M1/M6, a confirmar que o problema de quantização é estrutural do instrumento BTC, não do timeframe de decisão.

**Não fechado ainda:** este resultado é medição (R1/R2/R3 por TF), não decisão de qual TF adotar — isso é V41-5 (PRD V4.2), depois de M2/M4 fecharem também.

### M4 — Regime (≤6 trials)

**Única da Camada 1 que gasta orçamento** — não existe "regime verdadeiro" contra o qual comparar.

**Candidatos:** quantis expansivos (baseline) · HMM gaussiano (`dynamax`, 2/3/4 estados) · Jump Model · BOCPD.

**Métricas de utilidade, não de PnL:** separação de retorno condicional (ANOVA F, ω²) · persistência (duração mediana, taxa de troca) · estabilidade entre folds (Rand ajustado) · **ortogonalidade contra volatilidade**.

> A partição atual **é função de volatilidade**: `vol_state` deriva de `C07`, que é posto expansivo de `realized_vol(48)`. E `C07` é a feature mais robusta do projeto **com IC negativo simétrico nos dois lados** — o que aponta para custo de execução, não direção. A partição pode estar reforçando o defeito que contamina a confiança.

**Terceira via, testável (Q3):** com ρ ≈ 0,91, **o BTC é o fator de mercado**. Classificar regime no BTC e aplicar aos cinco tem três vantagens — rótulos com conteúdo idêntico, elimina 4/5 do custo, e testa se regime é propriedade do mercado ou do ativo. Falha se algum ativo tiver regime idiossincrático, e isso é medível pelo Rand ajustado entre a classificação própria e a derivada. **A medição decide.**

**Canonicalização obrigatória:** estados ordenados de forma determinística (média de retorno, desempate por variância) — banned pattern B21.

### M5 — Reconciliação de fill (0 trials)

Todos os 28 verdes usam fill de **97,1%**; o real medido é **42,2%** — medido só em BTCUSDT, janela 2023-05-16→2024-03-30 (~10,5 meses, `src/backtest/fill_reconciliation.py`, ver correção do §6.5 abaixo sobre o que esse número realmente representa).

Não há `bookTicker` fora de 2023-05 → 2024-03 (janela real, corrigida em §2.4 F4 — não 2025-11). A medição **quantifica a incerteza**, não a resolve:

- reprocessar as células verdes sob os dois gates, dentro da janela
- delta por célula, com IC
- **declaração de escopo versionada** anexa a todo relatório:

> *Todos os números derivam de fill otimista do Label Engine (97,1%). Na única janela verificável (2023-05→2024-03), o fill real é 42,2% e direção+carry ficaram negativos nos dois gates. A direção do viés fora dessa janela é DESCONHECIDA. No período 2021-12→2023-05 (17 meses do treino comum) o spread por ativo é não observável e o custo entre ativos é ASSUMIDO igual.*

**Pré-requisito real pra "escopo completo" (achado 2026-08-12, verificado contra o disco antes de escrever qualquer código — ver §6.5):** `fill_reconciliation.py` depende de `labels.parquet` + `predictions.parquet` + `orders.parquet` (via `fill_simulator`) — hoje os três só existem para BTCUSDT. Estender a 5 ativos não é generalizar um loop; é rodar Feature Engine + Label Engine + uma passada de Alpha/backtest + `fill_simulator` para os outros 4 ativos primeiro, dentro da janela real de 10,5 meses. Continua 0 trials (não é busca), mas é engenharia real, não script de meia hora.

### M6 — Hipótese do fator comum (0 trials)

**Nula (Q1):** `edge_bruto_atr` é o mesmo entre os cinco ativos, e as diferenças em `ret_net` vêm inteiramente de `custo_atr`.

**Falsificação:** se `edge_bruto_atr` variar significativamente com direção estável, existe componente idiossincrático além do fator comum — e multi-ativo é diversificação real. Se não variar, os cinco são um ativo com cinco estruturas de custo, e a seleção é puramente econômica.

**É teste de proposição, não busca.** Zero trials.

**Resultado (medido 2026-08-14, `experiments/m6_common_factor_hypothesis_report.json`, commit pendente):** teste de heterogeneidade de Cochran's Q/I² rodado sobre `edge_bruto_atr` pooled (sem estratificação por regime) nos 5 ativos, `decision_tf=15m`, cada lado testado separadamente. **H0 rejeitada nos dois lados, com folga:** long `I²=96,1%`, `p≈3,2×10⁻²¹`; short `I²=97,8%`, `p≈1,0×10⁻³⁸`. Por convenção de Higgins & Thompson (2002), `I²>75%` já é "alta heterogeneidade" — 96–98% é heterogeneidade quase total, praticamente nada da variação entre ativos é ruído amostral.

`edge_bruto_atr` por ativo (long / short): BTC −0,0375 / −0,0384 · ETH −0,0252 / −0,0109 · SOL −0,0514 / **+0,0066** · BNB −0,0435 / **+0,0059** · XRP −0,0793 / **+0,0296**. No lado long todos os 5 são negativos mas com amplitude >3× entre o melhor (ETH) e o pior (XRP — pior que BTC). No lado short o sinal **inverte**: BTC/ETH negativos, SOL/BNB/XRP positivos — evidência qualitativa direta da heterogeneidade, não só o p-value.

**Interpretação:** falsificação confirmada — existe componente idiossincrático real por ativo, além do fator comum. Multi-ativo é diversificação real, não "um ativo com cinco estruturas de custo". **Não** significa que algum ativo tem edge líquido positivo — `edge_liq_atr` (após `custo_atr`) segue negativo em todos os 10 pares ativo×lado pooled, inclusive onde `edge_bruto_atr` é positivo (custo ainda domina). Onde `edge_bruto_atr` é pequeno e positivo mas `edge_liq_atr` é negativo, `captura` degenera (ex. BNB short R1: `captura=-2280`) — artefato conhecido da razão perto de zero no denominador, não erro de cálculo; não usar `captura` como métrica de decisão nesses casos. **Consequência para M5:** o achado de T0.5 (permanência 5/5→1/5 na janela comum, só BTC) não pode mais ser presumido representativo dos outros 4 ativos — a heterogeneidade medida aqui é evidência a favor de rodar M5 em escopo completo, não a favor de encerrar.

### Gate da Camada 1

```
G-C1-1  M1, M2, M3, M5, M6 emitidos com 0 trials
G-C1-2  M4 emitido com <= 6 trials, canonicalização testada
G-C1-3  todo relatório emite edge_bruto_atr, custo_atr, edge_liq_atr e captura
G-C1-4  todas as métricas estratificadas por (symbol, tf, lado, regime)
G-C1-5  declaração de escopo de fill anexada
G-C1-6  N_trial ponderado por fatores efetivos, registrado no ledger
```

**Saída:** o PRD V4.2 é escrito **com** esses resultados.

---

# PARTE IV — CAMADAS 2 E 3

Escopo condicionado à Camada 1. Estrutura fixa, parâmetros a definir.

## 4.1 Barreiras — rederivadas, não varridas (≤4 trials)

Com o estimador vencedor, recalcular `tp_mult`/`sl_mult` a partir da **distribuição de MFE**, não por grid. MFE mediana medida no V3: **1,27–1,40 ATR** contra `tp = 2,0` — fora de alcance por construção.

**Assimetria por lado** entra aqui (§18.7.2 do V3.2, registrada e nunca executada).

**Restrição herdada:** o ótimo de barreira depende da população **selecionada**. A varredura da Faixa 2 foi incondicional — erro de desenho registrado. A rederivação roda sobre a população que o Alpha dispara.

**Multi-ativo:** `tp_mult` e `sl_mult` são compartilhados ou por ativo? Compartilhados custam 4 trials; por ativo custam 20. **Default: compartilhados**, com o desvio por ativo emitido como diagnóstico.

## 4.2 Meta-label, pesos, features (≤3 trials)

**Meta-label:** triple barrier permanece. `time_stop` vira **relógio** (I2), não barras.

> **Proveniência da decisão (achado `AG-079`/`AG-081`, 2026-08-17 — texto original só dizia "permanece", sem justificativa escrita):** triple-barrier (López de Prado, *Advances in Financial Machine Learning*, 2018, cap. 3) é mantido por dois motivos, não por inércia: (1) o rótulo espelha diretamente o mecanismo real de saída do trade (SL/TP/timeout), então trocar de esquema muda o que o modelo aprende a prever, não só a métrica de avaliação — reversão é cara (relabeling de todo `labels/` já gerado pros 5 símbolos); (2) nenhum PRD ou literatura citada no projeto propõe um esquema concorrente com evidência comparável. Decisão do Manager: não abrir estudo de comparação tipo-M1 — decisão fica fechada por proveniência de literatura, não por medição interna.

**Pesos:** unicidade permanece. Decaimento temporal e ponderação por similaridade (§11.3.1 do V3.2, especificado e nunca rodado) entram como 2 trials, com controle contra peso uniforme.

**Sobreposição transversal:** a unicidade é calculada por série. Com 15 combinações, o mesmo movimento aparece em quinze — a `N_eff` agregada é ~1,15× a de uma série, não 15×. A fórmula de peso precisa refletir isso.

**Features:** teto do `N_eff` **medido** sob a nova barra e barreira, nunca de fórmula. As 70 candidatas T2 do passe de pesquisa existem em `research/`. **1 trial** para o lote.

**Restrição nova (F2):** nenhuma feature de T1 pode depender de fonte indisponível em qualquer um dos cinco ativos. Isso elimina C13/C14/C15.

## 4.3 Learner — fora do orçamento

Provavelmente dispensável. O `code_discovery` mostra que o learner é o estágio **mais bem parametrizado** do repo (19 parâmetros, todos em `constants.yaml`), e é o estágio com **0% de verde** no inventário.

Só entra se a Camada 2 fechar com sinal estável e o tempo de treino virar gargalo da ablação. Exige **emenda declarada**, elevando o teto de `N_lifetime` para 62.

> **Nota (`AG-077`/`AG-079`, 2026-08-17):** `N_lifetime` foi descontinuado como orçamento vinculante — a cláusula acima ("eleva o teto pra 62") pressupõe o regime antigo. O GATILHO de reabertura (Camada 2 fechar com sinal estável + treino virar gargalo) continua válido; só o mecanismo de "emenda declarada elevando N_lifetime" precisa de reinterpretação sob o regime atual quando/se este gatilho disparar — decisão não antecipada aqui, ver `AG-077`.

## 4.4 Calibração

`confidence_rank` existe (§5.12) e **nunca foi avaliado**. Avaliar antes de qualquer alternativa. `ensemble_std` e `n_models_agree` estão especificados e ausentes.

**Achado a carregar:** a confiança **não ordena** dentro do conjunto disparado (ρ≈0) mas **funciona como porta** — vale +1,575 de Sharpe direcional contra aleatório de mesmo tamanho. São propriedades distintas. A Camada 3 investiga o que a porta captura.

## 4.5 Meta-Model (≤2 trials)

**Reaberto** — o argumento que o fechou caiu (§0.3).

É o único componente que consome o **Grupo J** (`p_fill_est`, `adverse_selection_est_bps`, `cost_est_bps`). Com fill real de 42,2%, deixa de ser refinamento e passa a atacar o custo dominante.

`is_oof` obrigatório com assert. Restrição de marginalidade: ≥1 feature que o Alpha não vê. Contrato de import-linter `alpha ↛ meta` sai de TODO (`pyproject.toml:159`) e vira contrato real.

## 4.6 Walk-forward (0 trials)

`src/validation/walk_forward.py` **não existe**. Gates G-WF-1..6 do §11.4.1.

**Correção obrigatória antes de rodar:** cada janela reporta **composição de regime** junto com o Sharpe. Com amplitude de `directional_sharpe` de 6,87 entre regimes no long, o Sharpe por janela oscila com o mix de regime, não com envelhecimento — e o G-WF-2 (meia-vida) mediria composição em vez de decaimento.

**Multi-ativo:** as janelas são **alinhadas em calendário** entre ativos e TFs. Folds por contagem de barras produzem períodos diferentes por TF e vazam entre séries.

## 4.7 PBO/CSCV e correção de Lo (0 trials)

Ambos especificados (§11.6, §16.5) e ausentes. Pré-requisitos do Gate 6.

---

# PARTE V — RISCO E EXECUÇÃO MULTI-ATIVO

## 5.1 O orçamento de fees é compartilhado

Uma conta, R$ 1.000. O orçamento de 3%/mês não se multiplica por ativo.

| ativo | custo/trade @ stop 1,5×ATR | trades/ano sozinho |
|---|---|---|
| SOL | US$ 0,0685 | 862 |
| ETH | US$ 0,0770 | 767 |
| XRP | US$ 0,0793 | 745 |
| BTC | US$ 0,1040 | 568 |
| BNB | US$ 0,1045 | 565 |

Com 15 combinações dividindo o orçamento: **~40 a 57 trades/ano por combinação**. Insuficiente para significância em qualquer uma.

> **Multi-ativo × multi-TF é requisito de consistência de treino e validação, não universo de execução.** A execução roda no subconjunto que passa nos gates e cabe no orçamento.

## 5.2 Filtros por símbolo

```yaml
BTCUSDT:  step 0.001   minNotional 50   pricePrecision 2   qtyPrecision 3
ETHUSDT:  step 0.001   minNotional 20   pricePrecision 2   qtyPrecision 3
SOLUSDT:  step 0.01    minNotional  5   pricePrecision 4   qtyPrecision 2
BNBUSDT:  step 0.01    minNotional  5   pricePrecision 3   qtyPrecision 2
XRPUSDT:  step 0.1     minNotional  5   pricePrecision 4   qtyPrecision 1
```

`MIN_NOTIONAL` é **por símbolo**, não global — erro que o V3.2 cometeu ao generalizar os 50 USDT do BTC. `load_filters_asof(symbol, t)` obrigatório, com snapshot diário versionado.

**Teto de preço por ativo** vira alerta operacional: o preço acima do qual a granularidade quebra. Para o BTC hoje já são 37,37% do equity numa unidade.

## 5.3 Controle novo — risco agregado por correlação ⭐

**Falha de segurança identificada em I4.** O Risk Engine avalia cada posição isoladamente contra `risk_per_trade = 0,50%`. Com ρ ≈ 0,91:

| posições simultâneas | σ agregado | múltiplo do unitário |
|---|---|---|
| 1 | 0,500% | 1,00x |
| **2** | **0,977%** | **1,95x** |
| 3 | 1,454% | 2,91x |
| 5 | **2,408%** | **4,82x** |

Cinco long simultâneos entregam 2,41% de risco efetivo — **acima do `max_daily_loss` de 2%** num único evento adverso.

**Novo controle 19 — `AGGREGATE_RISK_LIMIT`:**

```python
sigma_agg = sqrt( w.T @ Corr @ w )          # w = risco de cada posição aberta
if sigma_agg > aggregate_risk_max:
    reject("AGGREGATE_RISK_LIMIT")
```

`Corr` estimada em janela expansiva causal, por par de ativos, atualizada diariamente.
`aggregate_risk_max` = **1,00%** (classe A, ASSUMED, varredura obrigatória antes do Gate 3).

**Consequência imediata:** com ρ = 0,91 e limite de 1,00%, o **cap efetivo é 2 posições simultâneas**. Três já violam.

## 5.4 Sizing por ativo

`risk_per_trade` deixa de ser derivado do lote do BTC e volta a ser parâmetro. Mas o **erro de quantização** continua sendo controle por símbolo:

```
BTC @ stop 0,434%:    3,1 passos, erro 16,2%   → controle 9a/9b ATIVO
SOL @ stop 0,658%:  173,1 passos, erro  0,3%   → controle inerte
XRP @ stop 0,569%: 1246,8 passos, erro  0,0%   → controle inerte
```

O controle permanece no código, agora como guarda de borda em vez de restrição dominante.

---

# PARTE VI — GOVERNANÇA

## 6.1 Orçamento de trials

`N_lifetime` = **45**. Piso do DSR:

| N | SR_0 | delta vs 45 |
|---|---|---|
| **45 (hoje)** | **0,874** | — |
| 48 | 0,884 | +0,010 |
| 52 | 0,896 | +0,022 |
| 55 | 0,904 | +0,030 |
| 60 | 0,917 | +0,043 |

**Orçamento V4.1: 15 trials.**

| camada | item | trials |
|---|---|---|
| 1 | M4 regime (baseline + HMM×3 + Jump + BOCPD) | 6 |
| 2 | barreiras rederivadas + assimetria por lado | 4 |
| 2 | pesos (decaimento temporal + similaridade) | 2 |
| 2 | features (1 lote de promoção) | 1 |
| 3 | Meta-Model | 2 |
| — | learner: **0** — fora do orçamento, exige emenda | 0 |
| | **total** | **15** |

`N_lifetime` final = **60**, piso **0,917**. Custo total da V4.1: **+0,043 de Sharpe exigido**.

## 6.2 `N_trial` com redundância transversal ⭐

Uma hipótese rodada em 15 combinações **não é 15 trials nem 1**.

```
N_trial = fatores_efetivos(ativos) × fatores_efetivos(TFs)
```

`fatores_efetivos(ativos)` = **1,15** (medido, participation ratio de `Corr`).
`fatores_efetivos(TFs)` = **a medir** — mesma série reamostrada, esperado próximo de 1.

Estimativa provisória: `1,15 × ~1,5 ≈ 1,7 trials` por hipótese.

> **Condição dura:** isso só vale se o critério for **"vale nas 15"**. Se em qualquer momento a melhor combinação for escolhida, `N_trial = 15` e o piso do DSR salta para além do orçamento. A escolha de combinação de execução após ver resultado é **B20 literal**.

## 6.3 O que conta como trial

| conta | não conta |
|---|---|
| variante de modelo, feature set, barreira, calibrador, regime | leitura de código |
| escolha de mecanismo de seleção | medição contra alvo externo |
| **escolha entre células vistas** (B20) | recomputação sobre passe já contado |
| retreino sob config nova | correção de bug |
| **escolha de ativo ou TF de execução após ver resultado** | replicação obrigatória nas 15 |

## 6.4 Escala de evidência

| tier | exige | exemplo atual |
|---|---|---|
| 3 | mecanismo pré-registrado + controle + fora de amostra | **nenhum** |
| 2 | controle adequado, mecanismo não estabelecido | C07 composto · `long×R3` (lift 1,82) |
| 1 | verde sem controle | quase tudo antes da Faixa 1.7 |
| 0 | verde depois explicado por outra coisa | "congruência E02f" |

`superseded_by` obrigatório. E, na V4.1, `janela` obrigatório — os 28 verdes são da janela antiga (I5).

## 6.5 Critérios de encerramento — pré-registrados

| # | condição | ação |
|---|---|---|
| 1 | nenhum estimador bate `ATRWilder` em QLIKE em nenhum ativo | encerrar — o gargalo não é volatilidade — ✅ **medido 2026-08-11: NÃO disparou** (Parkinson/GK batem em 14/15, ver §3.2 M1) |
| 2 | nenhuma partição bate os quantis em separação **e** ortogonalidade contra vol | encerrar a linha de regime; C2 segue com quantis |
| 3 | T0.5 mostra que os verdes não sobrevivem à janela comum | reavaliar escopo antes de gastar trials — ⚠️ **disparou, 2026-08-10** (commit `5d8c8aa`, `audit/evidence_ledger.yaml::t05-permanence-camada1-vs-camada0-janela-comum`, status vermelho): permanência Camada1 vs Camada0 cai de 5/5 (janela cheia) para 1/5 (janela comum, mínimo exigido 4). **Não é ausência de sinal** — `directional_sharpe` pooled +2,51, positivo em 5/5 paths (`t05-directional-sharpe-positivo-cost-dominado`, status amarelo); `pnl_direcional` +12,45 vs `pnl_execução` -17,11. **Correção 2026-08-12 (pergunta direta do Manager expôs um elo fraco):** este `pnl_execução` foi calculado com o MESMO modelo de fill do Label Engine usado no resto do projeto (~97% simulado, ver `fill_rate` por path no próprio artefato) — **não** incorpora o fill real medido. O fill real (97,1%→42,2%) vem de um estudo à parte e mais estreito (`src/backtest/fill_reconciliation.py`, janela 2023-05→2024-03, ~10,5 meses, só BTCUSDT, 2.116 sinais — `docs/SPRINT_LOG.md` linha 366), nunca aplicado a este backtest de T0.5. E onde esse estudo pôde comparar, o resultado foi CONTRAINTUITIVO: trocar pro gate de fill real **reduziu** o Sharpe negativo (-9,25→-4,27), não piorou — "o gate otimista superestimava o dano de execução mais do que subestimava" (`docs/SPRINT_LOG.md`). Ou seja: **não sabemos ainda** se corrigir o fill no T0.5 pioraria ou melhoraria o -17,11 — é pergunta em aberto, não confirmação. **Decisão do Manager, 2026-08-12 — "vamos reavaliar escopo agora... confirmo":** não encerrar. M5 (fill) e M6 (fator comum) passam a ter prioridade sobre M4 (regime, ≤6 trials, único item pago da Camada 1) — M4 espera o resultado dos dois. Razão declarada: BTC já é conhecido como o ativo de pior `custo_atr` (0,228, só atrás do BNB) e menor `captura` (20,3% vs 47,5% do SOL, §1.3) — T0.5 testou só BTC, então "o sinal não sobrevive no BTC" pode ser achado específico do pior caso, não do projeto inteiro; M6 existe exatamente pra testar isso. **Correção de escopo 2026-08-12 (2ª rodada, "pode seguir" expôs que eu não tinha checado o disco antes de chamar M5/M6 de "rápidos"):** nem M5 nem M6 são triviais de estender pra 5 ativos — `labels.parquet` só existe pra BTCUSDT hoje (`data/labels/BTCUSDT/15m/v1`, únicos), `predictions`/`orders` do fill simulator idem. M6 precisa só de `labels.parquet` por ativo (mais leve); M5 precisa também de `predictions`+`orders` (mais pesado). O pré-requisito real e compartilhado dos dois é rodar Feature Engine + Label Engine pros outros 4 ativos — 0 trials continua verdade (não é busca/otimização), mas é engenharia de pipeline real, não os "próximos passos rápidos" que eu tinha descrito. Ver §3.2 M5 pro detalhe. |
| 4 | Camada 2 fecha com `edge_bruto_atr` abaixo de `custo_atr` no melhor ativo | encerrar |
| 5 | `N_lifetime` > 60 sem Camada 2 fechada | encerrar — orçamento exaurido |
| 6 | DSR final < 0,50 | encerrar |
| 7 | qualquer camada exige alterar critério pré-registrado para passar | encerrar aquela camada |

## 6.6 Proveniência

Doutrina do §16.10 integral: `constants.yaml` com `provenance` e `class`; CI bloqueando classe A `ASSUMED` em produção; guardrails classe C como quantis; varredura ±50% antes do Gate 3.

**Adições da V4.1:**
- todo estimador e classificador carrega `estimator_id`/`classifier_id` versionado
- **todo artefato derivado registra `symbol`, `tf`, `janela`, `estimator_id`, `classifier_id`**
- `Metric` ganha campos `symbol` e `tf` — sem isso, trocar de ativo reproduz a perda de rastro que causou os quatro erros de denominador do V3

---

# PARTE VII — DÍVIDA HERDADA

| # | item | onde | camada |
|---|---|---|---|
| D1 | I-a/I-b — literal `20` fora de `constants.yaml` | `research_t2.py:132`, `faixa2_e2_research.py:116` | C0 |
| D2 | I-c — `barrier_sweep` sem caminho de recomputo de ATR | `barrier_sweep.py:123` | C0 |
| D3 | I-d — assimetria de injeção em `classify_regimes` | `src/regime/classifier.py` | C0 |
| D4 | `regimes.parquet` desatualizado vs `labels.parquet` | `data/regimes/regime_v1/` | C0 |
| D5 | 54 divergências PRD↔código | — | C0 |
| D6 | `walk_forward.py` ausente | §11.4.1 | C3 |
| D7 | PBO/CSCV ausente | §11.6 | C3 |
| D8 | correção de Lo ausente | §16.5 | C3 |
| D9 | `ensemble_std`/`n_models_agree` ausentes | §5.12 | C2/C3 |
| D10 | contrato `alpha ↛ meta` é TODO | `pyproject.toml:159` | C3 |
| D11 | `fee_budget_monthly` classe A ASSUMED, nunca varrido | `constants.yaml` | C1 |
| D12 | `min_consistent_envs` 6/6 nunca varrido | `constants.yaml` | C2 |
| D13 | barreiras simétricas por lado, nunca medidas | §18.7.2 | C2 |
| D14 | unidade de `quote_volume` do dump não verificada | I1 | C0 |

---

# PARTE VIII — ROADMAP

| # | entrega | trials | gate |
|---|---|---|---|
| **V41-0** | T0.1–T0.4, T0.6 — interfaces, chaveamento, triagem, ledger | 0 | G-C0-1..5, 7 |
| **V41-1** | **T0.5 — baseline na janela comum** | 0 | **G-C0-6** |
| **V41-2** | M1 volatilidade ✅ (2026-08-12, GK vencedor) + M5 fill ⬜ | 0 | G-C1-1, 5 — parcial, falta M5 |
| **V41-3** | M2 barra + M3 timeframe + M6 fator comum | 0 | G-C1-1 |
| **V41-4** | M4 regime | ≤6 | G-C1-2 |
| **V41-5** | **PRD V4.2 escrito com os resultados** | 0 | — |
| V41-6 | barreiras rederivadas | ≤4 | G-C2-1 |
| V41-7 | pesos + features | ≤3 | G-C2-2 |
| V41-8 | controle 19 (risco agregado) + sizing por ativo | 0 | G-C2-3 |
| V41-9 | calibração + `confidence_rank` | 0 | — |
| V41-10 | Meta-Model + Grupo J | ≤2 | §6.8 do V3.2 |
| V41-11 | walk-forward + PBO + Lo | 0 | G-WF-1..6 |
| V41-12 | DSR final com `N_lifetime` = 60 | 0 | **Gate 6** |

**V41-0 a V41-5 são a decisão do projeto.** Se a Camada 1 não produzir vencedor em volatilidade nem em regime, os critérios 1 ou 2 disparam e o resto não roda.

**V41-1 tem precedência sobre tudo.** Se os verdes não sobreviverem à janela comum, o escopo muda antes de gastar um trial.

---

# PARTE IX — DEFINITION OF DONE

## 9.1 Por entrega

- [ ] Trials declarados **antes**, com hipótese mecanística escrita
- [ ] Nenhuma constante nova sem `provenance` e `class`
- [ ] `Metric.per_unit()` para toda conversão a bps — nunca divisão à mão
- [ ] Todo relatório emite `edge_bruto_atr`, `custo_atr`, `edge_liq_atr`, `captura`
- [ ] Toda métrica estratificada por `(symbol, tf, lado, regime)`
- [ ] Declaração de escopo de fill anexada
- [ ] Entrada no `evidence_ledger` com `estagio`, `symbol`, `tf`, `janela`, `tier`, `superseded_by`
- [ ] `N_trial` ponderado por fatores efetivos, registrado
- [ ] Suíte verde, 6/6 import-linter, 0 lint

## 9.2 Da V4.1 completa

1. `VolatilityEstimator` e `RegimeClassifier` com ≥2 implementações, golden bit-exato no baseline
2. 135 + 350 pontos de `fan_in` migrados
3. Todo artefato chaveado por `(symbol, tf)`; `load_filters_asof(symbol, t)` implementado
4. 54 divergências triadas
5. **Baseline na janela comum emitido, com comparação explícita contra os 28 verdes**
6. `evidence_ledger` com 160+ entradas, campos `estagio`/`symbol`/`tf`/`janela`
7. M1, M2, M3, M5, M6 emitidos com 0 trials, nos 5 ativos × 3 TFs
8. M4 emitido com ≤6 trials e canonicalização testada
9. **Controle 19 (risco agregado por correlação) implementado e testado**
10. PRD V4.2 escrito **com** os resultados da Camada 1
11. `walk_forward.py`, PBO/CSCV e correção de Lo implementados
12. `N_lifetime` ≤ 60, auditado item a item, com `N_trial` ponderado
13. DSR final reportado com `N_lifetime` real

## 9.3 O que a V4.1 é

A V3 provou que **uma** configuração, num ativo, num timeframe, numa janela, não entrega edge. A V4.1 existe para descobrir se **o espaço** não entrega — e a diferença entre as duas afirmações é o projeto inteiro.

Se a Camada 1 fechar sem vencedor em nenhum dos cinco ativos e nenhum dos três timeframes, a conclusão "não há edge extraível em cripto de grande cap com R$ 1.000" passa a ser sustentada. Hoje não é.

---

## Registro de mudanças V4.0 → V4.1

| # | mudança | origem |
|---|---|---|
| 1 | 5 ativos como medição aberta | decisão do Manager |
| 2 | 3 timeframes obrigatórios ponta a ponta | decisão do Manager |
| 3 | Álgebra em unidades de ATR como régua de comparação | custo fixo em bps vs volatilidade variável |
| 4 | Janela comum 2021-12 → 2026-08 | `metrics` dos 4 não-BTC começa 15 meses depois |
| 5 | C13/C14/C15 para T3 | BVOL só existe para BTC e ETH |
| 6 | Grupo F confirmado fora de T1 | `bookTicker` 2023-05 e RPI 2025-11, nos 5 |
| 7 | `atr_window`/`time_stop` em relógio, não em barras | horizontes divergem entre TFs |
| 8 | `N_trial` ponderado por fatores efetivos | 5 ativos = 1,15 fatores |
| 9 | **Controle 19 — risco agregado por correlação** | 5 posições = 4,82x o risco unitário |
| 10 | **T0.5 — baseline na janela comum, precedência máxima** | janela nova exclui a mania de 2020-2021 |
| 11 | Regime derivado do BTC como terceira via | ρ ≈ 0,91 torna o BTC o fator de mercado |
| 12 | `load_filters_asof(symbol, t)` | `MIN_NOTIONAL` é por símbolo, não global |
| 13 | Artefatos chaveados por `(symbol, tf)` | 15 combinações |
| 14 | Multi-ativo justificado como estresse econômico | replicação estatística refutada por I3 |
