"""GRUPO C — Volatilidade (§2.4). Escopo do Sprint 4:

* C01 `atr_20` / C02 `atr_20_pct` — não são T1 isoladas, mas são insumo de
  A05, A13, C06, C07, E27f (task explícita: "não é feature T1 sozinha mas
  é insumo de várias"). Registradas como T2 por completude de catálogo
  (§2.14 exige entrada para "toda feature, em qualquer tier").
* C06 `vol_ratio_12_96` (T1) e C07 `vol_pctile_expanding` (T1).
"""

from __future__ import annotations

import numpy as np

from .. import support
from ..support import FloatArray


def c01_atr_20(high: FloatArray, low: FloatArray, close: FloatArray, window: int) -> FloatArray:
    """ATR de Wilder, absoluto — §2.4 C01."""
    return support.atr_wilder(high, low, close, window)


def c02_atr_20_pct(atr_20_abs: FloatArray, close: FloatArray) -> FloatArray:
    """`ATR_20 / C_t` — §2.4 C02."""
    with np.errstate(divide="ignore", invalid="ignore"):
        out: FloatArray = atr_20_abs / close
    return out


def c06_vol_ratio_12_96(
    log_return_1: FloatArray, short_window: int, long_window: int
) -> FloatArray:
    """`realized_vol_12 / realized_vol_96` — §2.4 C06."""
    rv_short = support.realized_vol(log_return_1, short_window)
    rv_long = support.realized_vol(log_return_1, long_window)
    with np.errstate(divide="ignore", invalid="ignore"):
        out: FloatArray = rv_short / rv_long
    return out


def c07_vol_pctile_expanding(log_return_1: FloatArray, window: int) -> FloatArray:
    """Posto de `realized_vol_48` na distribuição EXPANSIVA estrita até
    `t-1` — §2.4 C07. Janela rolante fixa (`window`) só para calcular a
    volatilidade realizada em si; o posto dela é que é expansivo estrito
    (B02)."""
    rv = support.realized_vol(log_return_1, window)
    return support.expanding_percentile_rank_strict(rv)
