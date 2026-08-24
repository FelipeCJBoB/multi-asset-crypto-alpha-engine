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

from .. import support
from ..support import FloatArray


def a05_ret_vol_norm_4(close: FloatArray, atr_20_pct: FloatArray, lookback_bars: int) -> FloatArray:
    """`ln(C_t/C_{t-lookback_bars}) / (atr_20_pct × 2)` — §2.2 A05."""
    n = close.shape[0]
    log_ret = np.full(n, np.nan, dtype=np.float64)
    if n > lookback_bars:
        with np.errstate(divide="ignore", invalid="ignore"):
            log_ret[lookback_bars:] = np.log(close[lookback_bars:] / close[:-lookback_bars])
    # 2.0 = feature_a05_vol_norm_divisor em config/constants.yaml (AG-027,
    # 2026-08-15) -- valor ASSUMED, propósito não documentado em lugar
    # nenhum encontrado; não lido dinamicamente ainda (ver ressalva de
    # escopo na entrada do yaml).
    with np.errstate(divide="ignore", invalid="ignore"):
        out: FloatArray = log_ret / (atr_20_pct * 2.0)  # noqa: magic-number -- ver comentário acima
    return out


def a13_dist_ema48_atr(close: FloatArray, ema_48: FloatArray, atr_20_abs: FloatArray) -> FloatArray:
    """`(C_t − EMA_48) / ATR_20` (absoluto) — §2.2 A13."""
    with np.errstate(divide="ignore", invalid="ignore"):
        out: FloatArray = (close - ema_48) / atr_20_abs
    return out


# ============================================================================
# Lote A da liberação de features (H5, 2026-08-24) — A01-A04, A06-A12, A14.
# Todas T2 (nenhuma promovida a T1 por esta implementação, §0.2 R4/§2.13).
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


def a12_gap_pct(open_: FloatArray, close: FloatArray) -> FloatArray:
    """`(O_t - C_{t-1}) / C_{t-1}` — §2.2 A12."""
    n = close.shape[0]
    prev_close = np.full(n, np.nan, dtype=np.float64)
    if n > 1:
        prev_close[1:] = close[:-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        out: FloatArray = (open_ - prev_close) / prev_close
    return out


def a14_dist_ema12_atr(close: FloatArray, ema_12: FloatArray, atr_20_abs: FloatArray) -> FloatArray:
    """`(C_t - EMA_12) / ATR_20` (absoluto) — §2.2 A14. Mesma resolução
    dimensional de A13 (numerador em unidade de preço → denominador ATR
    absoluto, não `atr_20_pct`)."""
    with np.errstate(divide="ignore", invalid="ignore"):
        out: FloatArray = (close - ema_12) / atr_20_abs
    return out
