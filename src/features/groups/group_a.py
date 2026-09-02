"""GRUPO A — Preço e retorno (§2.2). Escopo T1 do Sprint 4: A05, A13.

Ambíguidade de notação do PRD resolvida por análise dimensional (reportada
no relatório do Sprint 4, não silenciada): a tabela §2.2 usa o mesmo rótulo
`ATR_20` nas fórmulas de A05 e A13, mas eles não podem ser a mesma
quantidade:

* **A05** `ln(C_t/C_{t−4}) / (ATR_20 × 2)` — o numerador (log-retorno) é
  adimensional, então o denominador precisa ser adimensional também: é
  `atr_20_pct` (fração do preço, §2.4 C02), não o ATR em dólares. Dividir
  por ATR em dólares (~centenas) produziria um número da ordem de 1e-5,
  incompatível de escala com o resto do vetor T1.
* **A13** `(C_t − EMA_48) / ATR_20` — o numerador está em unidade de preço
  (dólares), então o denominador precisa estar na mesma unidade: é o ATR
  absoluto (§2.4 C01), não `atr_20_pct`. Dividir por uma fração (~0,003)
  produziria um número da ordem de 1e5.

Confirmado numericamente contra a tabela §0.4 (ATR mediano 15m = 0,305%
≈ US$ 198 a US$ 65.000): A05 com `atr_20_pct` dá uma feature O(1); A13 com
ATR absoluto dá uma feature O(1) a O(10) ("distância em unidades de ATR").
As combinações trocadas dão ordens de grandeza absurdas — não é uma escolha
estética, é a única leitura que faz a feature ter escala utilizável.
"""

from __future__ import annotations

import numpy as np
import polars as pl

from .. import support
from ..support import FloatArray


def a05_ret_vol_norm_4(
    close: FloatArray, atr_20_pct: FloatArray, lookback_bars: int, vol_norm_divisor: float
) -> FloatArray:
    """`ln(C_t/C_{t-lookback_bars}) / (atr_20_pct × vol_norm_divisor)` — §2.2 A05.

    **Corrigido 2026-08-24** (achado da varredura de gaps, mesmo padrão do
    `round_trip_cost_bps_maker_prob`): `feature_a05_vol_norm_divisor`
    (`constants.yaml`, AG-027) já existia declarada e já era lida
    corretamente por `a06_ret_vol_norm_12` (`vol_norm_divisor=lote_a.
    a05_vol_norm_divisor`, `build.py`) — só A05 continuava com `2.0`
    hardcoded no corpo, isento do lint via `_ALLOWED_NUMERIC_LITERALS`.
    Valor da constante já era `2.0` (idêntico ao literal) -- correção é
    só de fiação, comportamento atual bit-exato preservado."""
    n = close.shape[0]
    log_ret = np.full(n, np.nan, dtype=np.float64)
    if n > lookback_bars:
        with np.errstate(divide="ignore", invalid="ignore"):
            log_ret[lookback_bars:] = np.log(close[lookback_bars:] / close[:-lookback_bars])
    with np.errstate(divide="ignore", invalid="ignore"):
        out: FloatArray = log_ret / (atr_20_pct * vol_norm_divisor)
    return out


def a13_dist_ema48_atr(close: FloatArray, ema_48: FloatArray, atr_20_abs: FloatArray) -> FloatArray:
    """`(C_t − EMA_48) / ATR_20` (absoluto) — §2.2 A13."""
    with np.errstate(divide="ignore", invalid="ignore"):
        out: FloatArray = (close - ema_48) / atr_20_abs
    return out


# ============================================================================
# Lote A da liberação de features (H5, 2026-08-24) — A01-A04, A06-A11, A14.
# Todas T2 (nenhuma promovida a T1 por esta implementação, §0.2 R4/§2.13).
#
# `A12_gap_pct` REMOVIDA 2026-08-27 (AG-316): media `(O_t - C_{t-1}) /
# C_{t-1}`, "gap de sessão" — mecanismo que não existe em mercado 24/7
# contíguo (não há fechamento/reabertura de sessão na Binance Futures).
# O que a fórmula mede de fato ("retorno de 1 tick" entre o open e o close
# anterior) já é coberto por A01 (log-retorno de 1 barra) — manter A12 sob
# outro nome seria uma feature redundante disfarçada de correção. Sem
# redefinição honesta que preserve a intenção original. Ver
# audit/architecture_gaps_log.yaml::AG-316.
# ============================================================================


def _log_return_n(close: FloatArray, lag_bars: int) -> FloatArray:
    """`ln(C_t / C_{t-lag_bars})` — núcleo comum de A01-A04 (§2.2). Cada
    uma das 4 tem seu próprio `lag_bars` provenanced em `constants.yaml`
    (`feature_a0{1,2,3,4}_log_return_lag`), mesmo quando o valor numérico
    coincide com outra (A03 = 4, mesmo valor de `feature_a05_ret_lookback_
    bars`) — constantes dedicadas por feature, não reaproveitadas entre
    ids diferentes (mesmo padrão já usado no repo pras 4 janelas de 48
    barras distintas: `feature_a13_ema_window`/`feature_d06f_taker_
    imbalance_window`/`feature_e10f_oi_change_window`/`feature_b07_
    efficiency_ratio_window`)."""
    n = close.shape[0]
    out = np.full(n, np.nan, dtype=np.float64)
    if n > lag_bars:
        with np.errstate(divide="ignore", invalid="ignore"):
            out[lag_bars:] = np.log(close[lag_bars:] / close[:-lag_bars])
    return out


def a01_log_return_1(close: FloatArray, lag_bars: int) -> FloatArray:
    """`ln(C_t / C_{t-1})` — §2.2 A01."""
    return _log_return_n(close, lag_bars)


def a02_log_return_2(close: FloatArray, lag_bars: int) -> FloatArray:
    """`ln(C_t / C_{t-2})` — §2.2 A02."""
    return _log_return_n(close, lag_bars)


def a03_log_return_4(close: FloatArray, lag_bars: int) -> FloatArray:
    """`ln(C_t / C_{t-4})` — §2.2 A03."""
    return _log_return_n(close, lag_bars)


def a04_log_return_12(close: FloatArray, lag_bars: int) -> FloatArray:
    """`ln(C_t / C_{t-12})` — §2.2 A04."""
    return _log_return_n(close, lag_bars)


def a06_ret_vol_norm_12(
    close: FloatArray,
    atr_20_pct: FloatArray,
    lookback_bars: int,
    *,
    variance_ref_lookback_bars: int,
    vol_norm_divisor: float,
) -> FloatArray:
    """`ln(C_t/C_{t-lookback_bars}) / (atr_20_pct × sqrt(lookback_bars /
    variance_ref_lookback_bars) × vol_norm_divisor)` — §2.2 A06.

    PRD cita literalmente "ATR_20 × √3 × 2" (`lookback_bars=12`). Mesma
    leitura dimensional de A05 (numerador log-retorno é adimensional →
    denominador é `atr_20_pct`, não ATR absoluto). O fator `√3` é
    `sqrt(12/4)` — a razão entre o lookback de A06 e o lookback de
    referência de A05 (`variance_ref_lookback_bars`), sob a premissa de
    retorno ~ passeio aleatório (variância escala linearmente com o
    horizonte). Generalizado aqui como razão CALCULADA em runtime a
    partir de dois lookbacks já provenanced (`feature_a06_ret_lookback_
    bars`, `feature_a05_ret_lookback_bars`) — não um `sqrt(3)` hardcoded
    sem explicação (mesmo problema que motivou o achado AG-027 sobre o
    divisor `2.0` de A05, agora documentado em vez de escondido).
    `vol_norm_divisor` reaproveita `feature_a05_vol_norm_divisor` (mesma
    convenção "×2" que A05 já usa)."""
    n = close.shape[0]
    log_ret = np.full(n, np.nan, dtype=np.float64)
    if n > lookback_bars:
        with np.errstate(divide="ignore", invalid="ignore"):
            log_ret[lookback_bars:] = np.log(close[lookback_bars:] / close[:-lookback_bars])
    variance_scale = np.sqrt(
        lookback_bars / variance_ref_lookback_bars
    )  # noqa: unguarded-ratio -- ambos os lookbacks vêm de constants.yaml (int > 0 por construção)
    with np.errstate(divide="ignore", invalid="ignore"):
        out: FloatArray = log_ret / (atr_20_pct * variance_scale * vol_norm_divisor)
    return out


def a07_body_ratio(
    open_: FloatArray, high: FloatArray, low: FloatArray, close: FloatArray
) -> FloatArray:
    """`(C-O)/(H-L)`, `0` se `H=L` — §2.2 A07 (convenção explícita do PRD
    para o caso degenerado)."""
    range_ = high - low
    with np.errstate(divide="ignore", invalid="ignore"):
        out: FloatArray = np.where(range_ == 0.0, 0.0, (close - open_) / range_)
    return out


def a08_upper_wick_ratio(
    open_: FloatArray, high: FloatArray, low: FloatArray, close: FloatArray
) -> FloatArray:
    """`(H - max(O,C))/(H-L)` — §2.2 A08. `H=L` → `0`, mesma convenção de
    A07 (PRD não declara o caso degenerado aqui explicitamente, mas
    `H=L` implica `O=H=L=C`, numerador também `0` — `0/0` resolvido pra
    `0` por consistência de tratamento entre as 4 razões OHLC do grupo,
    decisão explícita, não herança silenciosa)."""
    range_ = high - low
    with np.errstate(divide="ignore", invalid="ignore"):
        out: FloatArray = np.where(range_ == 0.0, 0.0, (high - np.maximum(open_, close)) / range_)
    return out


def a09_lower_wick_ratio(
    open_: FloatArray, high: FloatArray, low: FloatArray, close: FloatArray
) -> FloatArray:
    """`(min(O,C) - L)/(H-L)` — §2.2 A09. Mesma convenção `H=L → 0` de
    A08."""
    range_ = high - low
    with np.errstate(divide="ignore", invalid="ignore"):
        out: FloatArray = np.where(range_ == 0.0, 0.0, (np.minimum(open_, close) - low) / range_)
    return out


def a10_close_location(high: FloatArray, low: FloatArray, close: FloatArray) -> FloatArray:
    """`(C-L)/(H-L)` — §2.2 A10. Mesma convenção `H=L → 0` de A08/A09."""
    range_ = high - low
    with np.errstate(divide="ignore", invalid="ignore"):
        out: FloatArray = np.where(range_ == 0.0, 0.0, (close - low) / range_)
    return out


def a11_true_range_pct(high: FloatArray, low: FloatArray, close: FloatArray) -> FloatArray:
    """`TR_t / C_{t-1}` — §2.2 A11. `TR_t` via `support.true_range`
    (mesma primitiva de C01/ATR); `C_{t-1}` indefinido no primeiro
    índice (NaN)."""
    tr = support.true_range(high, low, close)
    n = close.shape[0]
    prev_close = np.full(n, np.nan, dtype=np.float64)
    if n > 1:
        prev_close[1:] = close[:-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        out: FloatArray = tr / prev_close
    return out


def a16_return_3(close: FloatArray, lag_bars: int) -> FloatArray:
    """`ln(C_t / C_{t-lag_bars})` — mesmo núcleo de A01-A04
    (`_log_return_n`). **[NOVO, 2026-08-28, `AG-372`/ADR-006]** Preenche o
    gap entre A02 (lag 2) e A03 (lag 4) na escala medida do horizonte de
    holding real do motor (`n_bars_held` mediana=1, p75=3, `feature_a16_
    return_lag_bars`) — não um lag arbitrário: é o lag onde o `h/H` de
    A01-A04 já cruzava de "muito curto" pra "possivelmente longo demais"
    sem nenhum candidato exatamente em cima do p75 medido."""
    return _log_return_n(close, lag_bars)


def a17_log_tr_per_overshoot_ratio(
    high: FloatArray,
    low: FloatArray,
    close: FloatArray,
    overshoot: FloatArray,
    threshold_quote: FloatArray,
) -> FloatArray:
    """`ln1p( (TR_t/C_{t-1}) / (overshoot_t/threshold_quote_t) )` —
    **[NOVO, 2026-08-28, `AG-372`/ADR-006; REDESENHADA no mesmo dia,
    `AG-373`]**. Substitui a versão original (`TR_t/overshoot_t` cru),
    que tinha um defeito dimensional real achado por auditoria
    independente: `TR_t` tem unidade de PREÇO (`$/coin`) e `overshoot_t`
    tem unidade de NOTIONAL em dólar (`quote_volume_t - threshold_
    quote_t`, `price*quantity` somado) — a razão crua não cancela,
    unidade residual `1/coin`, deriva sistemática com o nível de preço
    do próprio ativo ao longo do calendário (mesma classe de defeito que
    o cabeçalho deste módulo já trata como não-negociável pra A05 vs
    A13). Corrigido normalizando os DOIS lados contra sua própria escala
    de referência antes de dividir: `TR_t/C_{t-1}` (== `A11_true_range_
    pct`, retorno relativo, adimensional) sobre `overshoot_t/threshold_
    quote_t` (fração de quanto a barra passou do alvo, adimensional) —
    razão de duas quantidades adimensionais, unidade final = nenhuma.
    `ln1p` doma a cauda pesada à direita (overshoot pequeno relativo ao
    threshold é o caso ECONOMICAMENTE esperado, não raro — `AG-321`: a
    barra fecha quase exatamente no threshold — então o denominador da
    razão interna é tipicamente pequeno, produzindo valores grandes;
    mesmo tratamento que A18-A21/B16 já aplicam no lote, por
    consistência, não estética). Tese econômica preservada: deslocamento
    de preço por unidade de atividade monetária MARGINAL relativa ao
    threshold-alvo — overshoot pequeno com TR grande é o sinal de
    iliquidez/impacto alto. Deliberadamente NÃO chamada de "Amihud"/
    "Kyle lambda" — a analogia é conceitual, não replicação da métrica.

    `overshoot_t<=0` (guardado explicitamente — acontece de fato 1x por
    símbolo×resolução na última barra de cada stream, subdimensionada
    por construção, `AG-373`) ou `threshold_quote_t<=0` (nunca deveria
    acontecer, guardado mesmo assim) produzem `NaN`."""
    tr = support.true_range(high, low, close)
    n = close.shape[0]
    prev_close = np.full(n, np.nan, dtype=np.float64)
    if n > 1:
        prev_close[1:] = close[:-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        valid = (overshoot > 0.0) & (threshold_quote > 0.0)
        impact_ratio = np.where(valid, (tr * threshold_quote) / (prev_close * overshoot), np.nan)
        out: FloatArray = np.log1p(impact_ratio)
    return out


def a18_body_log(open_: FloatArray, close: FloatArray) -> FloatArray:
    """`ln(C_t / O_t)` — **[NOVO, 2026-08-28, `AG-372`/ADR-006, Lote D2]**
    deslocamento open→close DENTRO da própria barra, em log — diferente
    de A01 (`ln(C_t/C_{t-1})`, close-a-close ENTRE barras). Nenhuma
    feature do vetor media isso hoje. `O_t>0` sempre (preço real) — mesma
    classe de denominador "estruturalmente seguro" que A01-A04 já tratam
    sem guarda explícita (`close[:-lag_bars]`)."""
    with np.errstate(divide="ignore", invalid="ignore"):
        out: FloatArray = np.log(close / open_)
    return out


def a19_log_range(high: FloatArray, low: FloatArray) -> FloatArray:
    """`ln(H_t / L_t)` — **[NOVO, 2026-08-28, `AG-372`/ADR-006, Lote D2]**
    range CRU de 1 barra, não suavizado — diferente de `atr_20_pct`
    (média de Wilder, 20 barras). `H_t=L_t` (barra flat) dá `ln(1)=0`,
    sem divisão nem caso degenerado a tratar."""
    with np.errstate(divide="ignore", invalid="ignore"):
        out: FloatArray = np.log(high / low)
    return out


def a20_log_duration(open_time_ms: FloatArray, close_time_ms: FloatArray) -> FloatArray:
    """`ln(1 + duração_s)` — **[NOVO, 2026-08-28, `AG-372`/ADR-006, Lote
    D2]** exclusivo de dollar bar: quanto tempo o mercado precisou pra
    negociar aquele quantum de valor. Sob `time_15m` continua computável
    (não vira NaN) mas degenera pra quase-constante (~15min sempre) —
    baixa informação nesse grid, não um erro. `close_time_ms >=
    open_time_ms` sempre (fecho nunca antes da abertura) — `log1p` é
    seguro mesmo no caso-limite duração=0 (barra de 1 trade só)."""
    duration_ms = close_time_ms - open_time_ms
    duration_s = duration_ms / 1000.0  # noqa: magic-number -- ms->s, conversão de unidade, não hiperparâmetro
    out: FloatArray = np.log1p(duration_s)
    return out


def a21_log_dollar_velocity(quote_volume: FloatArray, duration_s: FloatArray) -> FloatArray:
    """`ln(1 + QV_t/duração_s)` — **[NOVO, 2026-08-28, `AG-372`/ADR-006,
    Lote D2]** intensidade de atividade monetária por segundo, eixo
    ORTOGONAL a A17 (A17 mede impacto de preço por overshoot; isto mede
    velocidade de atividade sem olhar pro preço). `duração_s<=0` (barra
    de 1 trade instantâneo — caso real, não hipotético) produz `NaN`,
    nunca `inf` (mesma disciplina de A17/B13, achado de
    `/audit_engineering`)."""
    with np.errstate(divide="ignore", invalid="ignore"):
        out: FloatArray = np.where(duration_s > 0.0, np.log1p(quote_volume / duration_s), np.nan)
    return out


def a14_dist_ema12_atr(close: FloatArray, ema_12: FloatArray, atr_20_abs: FloatArray) -> FloatArray:
    """`(C_t - EMA_12) / ATR_20` (absoluto) — §2.2 A14. Mesma resolução
    dimensional de A13 (numerador em unidade de preço → denominador ATR
    absoluto, não `atr_20_pct`)."""
    with np.errstate(divide="ignore", invalid="ignore"):
        out: FloatArray = (close - ema_12) / atr_20_abs
    return out


# ============================================================================
# Lote B da liberação de features (H5, 2026-08-24) — A15, única do grupo A
# nesta leva (precisa de primitiva nova: reset por fronteira de dia).
# ============================================================================


def a15_dist_vwap_d_atr(
    high: FloatArray,
    low: FloatArray,
    close: FloatArray,
    volume: FloatArray,
    close_time_ms: FloatArray,
    atr_20_abs: FloatArray,
) -> FloatArray:
    """`(C_t - VWAP_dia) / ATR_20` (absoluto) — §2.2 A15. `VWAP_dia =
    cumulative(preço_típico × volume) / cumulative(volume)` DESDE o
    início do dia UTC contendo a barra `t` — `preço_típico = (H+L+C)/3`,
    convenção pública padrão (validada via pesquisa web: Investing.com/
    StockCharts/QuantInsti — "the industry standard for VWAP uses...
    (High + Low + Close) / 3"). Cripto negocia 24/7, sem "abertura de
    sessão" tradicional (ações/futuros) — reset à meia-noite UTC é a
    adaptação natural pra um mercado contínuo, mesma convenção de
    fronteira de dia já usada em `group_k.py` (K03) deste repo.

    `polars.cum_sum().over("day_id")` reseta a soma acumulada a cada
    novo `day_id` (partição), preservando a ORDEM de aparição dentro de
    cada dia — como `close_time_ms` chega estritamente crescente
    (barras em ordem cronológica), isso reproduz exatamente "acumula
    desde o início do dia, nunca olha pra frente" (B02: a barra `t` só
    soma até si mesma dentro do próprio dia, nunca além). Mesma leitura
    dimensional de A13/A14 (numerador em unidade de preço → ATR
    absoluto, não `atr_20_pct`)."""
    typical_price = (high + low + close) / 3.0  # noqa: magic-number -- média de 3 (H+L+C), definicional da fórmula pública de VWAP, não hiperparâmetro
    day_id = close_time_ms.astype(np.int64) // 86_400_000  # noqa: magic-number -- ms/dia, conversão de unidade, não hiperparâmetro (mesma constante de group_k.py::_MS_PER_DAY)
    pv = typical_price * volume
    df = pl.DataFrame({"day_id": day_id, "pv": pv, "v": volume})
    cum_pv = df.select(pl.col("pv").cum_sum().over("day_id")).to_series().to_numpy()
    cum_v = df.select(pl.col("v").cum_sum().over("day_id")).to_series().to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        vwap = cum_pv / cum_v
        out: FloatArray = (close - vwap) / atr_20_abs
    return out
