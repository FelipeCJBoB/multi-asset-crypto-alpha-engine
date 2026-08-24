"""GRUPO D — Volume e fluxo de agressor (§2.5). Escopo T1 do Sprint 4:
D03f, D06f. Fonte: `taker_buy_volume`/`volume` já vêm de `klines_1m`
agregado para 15m por `src.data.resample.resample_klines` (schema
confirmado em `src/data/schemas.py` e `_OHLCV_COLUMN_ORDER` de
`resample.py` — soma, não média, é a agregação causal correta para volume).
"""

from __future__ import annotations

import numpy as np
import polars as pl

from .. import support
from ..support import FloatArray


def d03f_volume_z_expanding(
    volume: FloatArray, *, min_common_history_bars: int | None = None
) -> FloatArray:
    """Z-score expansivo estrito de `log(1+V_t)` — §2.5 D03f.

    `min_common_history_bars` (AG-030, T0.5): repassado direto a
    `support.expanding_zscore_strict` — cap no histórico comum entre os 5
    ativos (ver docstring da primitiva). `None` (default) preserva o
    comportamento expansivo desde a origem do ativo."""
    log_volume = np.log1p(volume)
    return support.expanding_zscore_strict(
        log_volume, min_common_history_bars=min_common_history_bars
    )


def d06f_taker_imbalance_z_48(
    taker_buy_volume: FloatArray, volume: FloatArray, window: int
) -> FloatArray:
    """Z-score ROLANTE (janela fixa `window`, não expansiva) de
    `2×taker_buy_ratio − 1` — §2.5 D06f."""
    with np.errstate(divide="ignore", invalid="ignore"):
        taker_buy_ratio = taker_buy_volume / volume
    imbalance = 2 * taker_buy_ratio - 1
    return support.rolling_zscore(imbalance, window)


# ============================================================================
# Lote A da liberação de features (H5, 2026-08-24) — D01f, D02f, D04f,
# D05f, D08f, D09f. Todas T2 (nenhuma promovida a T1 por esta
# implementação, §0.2 R4/§2.13). D08f/D09f consomem `trade_count`
# (`count`, klines Binance) — fonte já em `bars_15m`, sem novo `_sources.py`.
# ============================================================================


def d01f_volume_z_96(volume: FloatArray, window: int) -> FloatArray:
    """`(V_t - μ_window) / σ_window` — §2.5 D01f."""
    return support.rolling_zscore(volume, window)


def d02f_rel_volume_48(volume: FloatArray, window: int) -> FloatArray:
    """`V_t / mediana(V)_window` — §2.5 D02f. Mediana rolante via
    `polars.rolling_median` diretamente — mesmo padrão de uso direto de
    `polars.rolling_std`/`rolling_mean` já presente no módulo, não
    precisa de primitiva nova em `support.py`."""
    median = pl.Series(volume).rolling_median(window_size=window, min_samples=window).to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        out: FloatArray = volume / median
    return out


def d04f_volume_accel(volume: FloatArray, window: int) -> FloatArray:
    """`rel_volume_{window,t} - rel_volume_{window,t-window}` — §2.5
    D04f. `rel_volume_window = V_t / mediana(V)_window` (mesmo núcleo de
    D02f, janela menor); o lag do deslocamento é o PRÓPRIO `window` (PRD
    tabula lookback "8" = window+window, não dois parâmetros
    independentes — mesma construção de `group_b.b06_momentum_accel`)."""
    median = pl.Series(volume).rolling_median(window_size=window, min_samples=window).to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        rel_volume: FloatArray = volume / median
    n = rel_volume.shape[0]
    out = np.full(n, np.nan, dtype=np.float64)
    if n > window:
        out[window:] = rel_volume[window:] - rel_volume[:-window]
    return out


def d05f_taker_buy_ratio(taker_buy_volume: FloatArray, volume: FloatArray) -> FloatArray:
    """`taker_buy_volume / volume` — §2.5 D05f. Sem janela (razão ponto a
    ponto); insumo direto de D06f (`2×taker_buy_ratio-1`), aqui exposta
    isoladamente como feature própria."""
    with np.errstate(divide="ignore", invalid="ignore"):
        out: FloatArray = taker_buy_volume / volume
    return out


def d08f_trade_count_z_48(trade_count: FloatArray, window: int) -> FloatArray:
    """Z-score rolante de `number_of_trades` (`count`, klines Binance) —
    §2.5 D08f."""
    return support.rolling_zscore(trade_count, window)


def d09f_avg_trade_size_z(volume: FloatArray, trade_count: FloatArray, window: int) -> FloatArray:
    """Z-score rolante de `volume / number_of_trades` — §2.5 D09f."""
    with np.errstate(divide="ignore", invalid="ignore"):
        avg_trade_size: FloatArray = volume / trade_count
    return support.rolling_zscore(avg_trade_size, window)
