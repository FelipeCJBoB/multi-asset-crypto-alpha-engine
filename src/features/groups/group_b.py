"""GRUPO B — Momentum e reversão (§2.3). Escopo do Sprint 4: B01 (T1) e
B07 (T2, mas implementado agora — insumo do Regime Engine, §4.2, Sprint 5)."""

from __future__ import annotations

import numpy as np
import polars as pl

from .. import support
from ..support import FloatArray


def b01_rsi_14(close: FloatArray, window: int) -> FloatArray:
    """RSI de Wilder escalado para `[-1, 1]` via `(RSI-50)/50` — §2.3 B01."""
    rsi = support.rsi_wilder(close, window)
    out: FloatArray = (rsi - 50.0) / 50.0  # reescala fixa [0,100] do RSI [noqa: magic-number]
    return out


def b07_efficiency_ratio_48(close: FloatArray, window: int) -> FloatArray:
    """`|C_t − C_{t−48}| / Σ|C_i − C_{i−1}|` — §2.3 B07. T2 no vetor de
    treino do Alpha V1, mas eixo de partição do Regime Engine (§4.2) — por
    isso implementado no Sprint 4 junto com T1, não adiado para quando B07
    for promovido por ablação (§2.0.1)."""
    return support.efficiency_ratio(close, window)


# ============================================================================
# Lote A da liberação de features (H5, 2026-08-24) — B02-B06, B08, B09, B11.
# Todas T2 (nenhuma promovida a T1 por esta implementação, §0.2 R4/§2.13).
# ============================================================================


def b02_rsi_48(close: FloatArray, window: int) -> FloatArray:
    """RSI de Wilder, escalado para `[-1, 1]` — §2.3 B02 (mesma fórmula
    de B01, janela diferente)."""
    return b01_rsi_14(close, window)


def b03_roc_12(close: FloatArray, lookback_bars: int) -> FloatArray:
    """`(C_t - C_{t-lookback_bars}) / C_{t-lookback_bars}` — §2.3 B03."""
    n = close.shape[0]
    out = np.full(n, np.nan, dtype=np.float64)
    if n > lookback_bars:
        with np.errstate(divide="ignore", invalid="ignore"):
            out[lookback_bars:] = (close[lookback_bars:] - close[:-lookback_bars]) / close[
                :-lookback_bars
            ]
    return out


def _ema_skip_leading_nan(values: FloatArray, span: int) -> FloatArray:
    """`support.ema` (via `polars.ewm_mean`) nunca foi exercitada neste
    repo com uma entrada que já carrega NaN líder (todo caller existente
    passa `close`, preço bruto, sem NaN) — a semântica NaN-vs-null do
    `ewm_mean` do polars pra esse caso não está verificada aqui, e uma
    suposição errada poderia propagar NaN pra sempre (contaminação
    silenciosa do resto da série). Em vez de confiar nisso, aplica
    `support.ema` só na cauda válida (mesma técnica de `support.
    wilder_smooth`/`_first_valid_index`: acha o primeiro índice não-NaN,
    computa só a partir dali) e cola o prefixo NaN de volta —
    determinístico por construção, independente da semântica interna do
    polars."""
    n = values.shape[0]
    out = np.full(n, np.nan, dtype=np.float64)
    first_valid = 0
    while first_valid < n and np.isnan(values[first_valid]):
        first_valid += 1
    if first_valid >= n:
        return out
    out[first_valid:] = support.ema(values[first_valid:], span)
    return out


def b04_macd_hist_norm(
    close: FloatArray,
    atr_20_abs: FloatArray,
    fast_window: int,
    slow_window: int,
    signal_window: int,
) -> FloatArray:
    """`(MACD_{fast,slow} - sinal_signal) / ATR_20` (absoluto) — §2.3 B04.
    `MACD = EMA_fast - EMA_slow` (Gerald Appel, anos 1970 — validado via
    pesquisa web: EMA12/EMA26, sinal=EMA9 do MACD, convenção pública
    universal). Numerador é diferença de duas EMAs de preço (unidade de
    preço) → denominador ATR absoluto, mesma leitura dimensional de
    A13/A14. Sinal = EMA9 de `macd`, que já carrega o warmup NaN de
    `ema_slow` — via `_ema_skip_leading_nan` (não `support.ema` direto
    sobre a série com NaN líder, ver docstring dela)."""
    ema_fast = support.ema(close, fast_window)
    ema_slow = support.ema(close, slow_window)
    macd = ema_fast - ema_slow
    signal = _ema_skip_leading_nan(macd, signal_window)
    hist = macd - signal
    with np.errstate(divide="ignore", invalid="ignore"):
        out: FloatArray = hist / atr_20_abs
    return out


def b05_ema_slope_24(
    close: FloatArray, atr_20_abs: FloatArray, ema_window: int, slope_lag_bars: int
) -> FloatArray:
    """`(EMA_{ema_window,t} - EMA_{ema_window,t-slope_lag_bars}) / ATR_20`
    (absoluto) — §2.3 B05. Numerador é diferença de EMA de preço (unidade
    de preço) → denominador ATR absoluto, mesma leitura dimensional de
    A13/A14/B04."""
    ema_v = support.ema(close, ema_window)
    n = ema_v.shape[0]
    slope = np.full(n, np.nan, dtype=np.float64)
    if n > slope_lag_bars:
        slope[slope_lag_bars:] = ema_v[slope_lag_bars:] - ema_v[:-slope_lag_bars]
    with np.errstate(divide="ignore", invalid="ignore"):
        out: FloatArray = slope / atr_20_abs
    return out


def b06_momentum_accel(close: FloatArray, atr_20_pct: FloatArray, lookback_bars: int) -> FloatArray:
    """`ret_{lookback_bars,t} - ret_{lookback_bars,t-lookback_bars}`,
    normalizado por `atr_20_pct` — §2.3 B06. `ret_lookback_bars` é o
    log-retorno de `lookback_bars` (mesmo núcleo de A01-A04, inline aqui
    para não depender de símbolo privado de outro módulo); o lag do
    deslocamento é o PRÓPRIO `lookback_bars` (comparar o retorno de N
    barras agora contra o retorno de N barras N barras atrás, sem
    sobreposição) — não é um segundo parâmetro independente (PRD tabula
    lookback "8+20" = 4+4 barras de retorno + a janela de ATR, não dois
    lookbacks de retorno distintos). Numerador adimensional (diferença de
    log-retornos) → denominador `atr_20_pct`, mesma leitura de A05/A06."""
    n = close.shape[0]
    ret = np.full(n, np.nan, dtype=np.float64)
    if n > lookback_bars:
        with np.errstate(divide="ignore", invalid="ignore"):
            ret[lookback_bars:] = np.log(close[lookback_bars:] / close[:-lookback_bars])
    accel = np.full(n, np.nan, dtype=np.float64)
    if n > lookback_bars:
        accel[lookback_bars:] = ret[lookback_bars:] - ret[:-lookback_bars]
    with np.errstate(divide="ignore", invalid="ignore"):
        out: FloatArray = accel / atr_20_pct
    return out


def b08_efficiency_ratio_16(close: FloatArray, window: int) -> FloatArray:
    """`|C_t − C_{t−window}| / Σ|C_i − C_{i−1}|` — §2.3 B08 (mesma
    fórmula de B07, janela diferente)."""
    return support.efficiency_ratio(close, window)


def b09_zscore_close_48(close: FloatArray, window: int) -> FloatArray:
    """`(C_t - μ_window) / σ_window` — §2.3 B09."""
    return support.rolling_zscore(close, window)


def b11_bb_position_20(close: FloatArray, window: int, std_multiplier: float) -> FloatArray:
    """`(C - MA_window) / (std_multiplier × σ_window)` — §2.3 B11
    (posição estilo Bollinger %B). `std_multiplier=2.0` é a convenção
    padrão de Bollinger Bands (validado via pesquisa web: John Bollinger,
    2 desvios-padrão). `rolling_zscore(close, window)` já calcula
    `(C-MA)/σ` — esta função só reescala pelo `std_multiplier`, não
    duplica o cálculo de z-score."""
    z = support.rolling_zscore(close, window)
    out: FloatArray = z / std_multiplier
    return out


# ============================================================================
# Lote B da liberação de features (H5, 2026-08-24) — B10, única do grupo B
# nesta leva (precisa de primitiva nova: mínimo/máximo rolante).
# ============================================================================


def b10_stoch_k_14(high: FloatArray, low: FloatArray, close: FloatArray, window: int) -> FloatArray:
    """`(C - min(L)_window) / (max(H)_window - min(L)_window) × 100` —
    §2.3 B10 (Stochastic %K padrão, George Lane, validado via pesquisa
    web). Janela rolante fixa (a barra `t` entra na própria janela —
    `min(L)`/`max(H)` incluem `L_t`/`H_t`, B02 não se aplica).
    `min`/`max` rolantes via `polars.rolling_min`/`rolling_max`
    diretamente — mesmo padrão de uso direto de primitiva polars já
    presente no módulo (`rolling_median` em D02f/D04f), não precisa de
    wrapper novo em `support.py`. `range_=0` (preço flat na janela
    inteira, caso degenerado raro) produz `NaN` via `errstate` — o PRD
    não declara uma convenção pra esse caso (diferente de A07-A10, que
    declaram "0 se H=L" explicitamente), então nenhuma é inventada
    aqui."""
    lowest_low = pl.Series(low).rolling_min(window_size=window, min_samples=window).to_numpy()
    highest_high = pl.Series(high).rolling_max(window_size=window, min_samples=window).to_numpy()
    pct_scale = 100.0  # noqa: magic-number -- escala percentual padrão do Stochastic %K, definicional (mesma classe do 50.0/100.0 de rsi_wilder), não hiperparâmetro
    with np.errstate(divide="ignore", invalid="ignore"):
        out: FloatArray = (close - lowest_low) / (highest_high - lowest_low) * pct_scale
    return out
