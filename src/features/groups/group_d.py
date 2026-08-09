"""GRUPO D — Volume e fluxo de agressor (§2.5). Escopo T1 do Sprint 4:
D03f, D06f. Fonte: `taker_buy_volume`/`volume` já vêm de `klines_1m`
agregado para 15m por `src.data.resample.resample_klines` (schema
confirmado em `src/data/schemas.py` e `_OHLCV_COLUMN_ORDER` de
`resample.py` — soma, não média, é a agregação causal correta para volume).
"""

from __future__ import annotations

import numpy as np

from .. import support
from ..support import FloatArray


def d03f_volume_z_expanding(volume: FloatArray) -> FloatArray:
    """Z-score expansivo estrito de `log(1+V_t)` — §2.5 D03f."""
    log_volume = np.log1p(volume)
    return support.expanding_zscore_strict(log_volume)


def d06f_taker_imbalance_z_48(
    taker_buy_volume: FloatArray, volume: FloatArray, window: int
) -> FloatArray:
    """Z-score ROLANTE (janela fixa `window`, não expansiva) de
    `2×taker_buy_ratio − 1` — §2.5 D06f."""
    with np.errstate(divide="ignore", invalid="ignore"):
        taker_buy_ratio = taker_buy_volume / volume
    imbalance = 2 * taker_buy_ratio - 1
    return support.rolling_zscore(imbalance, window)
