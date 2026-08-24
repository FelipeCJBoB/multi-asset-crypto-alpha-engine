"""GRUPO C — Volatilidade (§2.4). Escopo do Sprint 4:

* C01 `atr_20` / C02 `atr_20_pct` — não são T1 isoladas, mas são insumo de
  A05, A13, C06, C07, E27f (task explícita: "não é feature T1 sozinha mas
  é insumo de várias"). Registradas como T2 por completude de catálogo
  (§2.14 exige entrada para "toda feature, em qualquer tier").
* C06 `vol_ratio_12_96` (T1) e C07 `vol_pctile_expanding` (T1).
"""

from __future__ import annotations

import numpy as np
import polars as pl

from .. import support
from ..support import FloatArray


def c01_atr_20(high: FloatArray, low: FloatArray, close: FloatArray, window: int) -> FloatArray:
    """ATR de Wilder, absoluto — §2.4 C01."""
    return support.atr_wilder(high, low, close, window)


def c01_atr_20_parkinson(
    high: FloatArray, low: FloatArray, close: FloatArray, window: int
) -> FloatArray:
    """C01 sob o estimador Parkinson (1980) — variante promovida a candidato
    canônico de volatilidade em 2026-08-17 (AG-036/065/074, `constants.yaml::
    canonical_volatility_estimator`). `support.parkinson_vol` retorna fração
    do preço (mesma escala de `atr_wilder(...)/close`); `* close` denormaliza
    pra unidade de preço absoluta — mesma unidade de `c01_atr_20`, operação
    confirmada dimensionalmente correta por revisão `project_assurance`
    (2026-08-17).

    A distribuição numérica de C01 (e, por consequência, de A05/A13/C02/
    E27f, que consomem `atr_20_abs`/`atr_20_pct` como insumo) MUDA de
    verdade em relação a `c01_atr_20` — ATR de Wilder é suavização
    recursiva de `true_range` (inclui gap de fechamento); Parkinson é média
    móvel simples de `ln(H/L)^2` sobre a janela (só range intrabar, sem
    gap). Não é um re-rótulo cosmético do mesmo número."""
    return support.parkinson_vol(high, low, window) * close


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


def c07_vol_pctile_expanding(
    log_return_1: FloatArray, window: int, *, min_common_history_bars: int | None = None
) -> FloatArray:
    """Posto de `realized_vol_48` na distribuição EXPANSIVA estrita até
    `t-1` — §2.4 C07. Janela rolante fixa (`window`) só para calcular a
    volatilidade realizada em si; o posto dela é que é expansivo estrito
    (B02).

    `min_common_history_bars` (AG-030, T0.5): repassado direto a
    `support.expanding_percentile_rank_strict` — cap no histórico comum
    entre os 5 ativos (ver docstring da primitiva). `None` (default)
    preserva o comportamento expansivo desde a origem do ativo."""
    rv = support.realized_vol(log_return_1, window)
    return support.expanding_percentile_rank_strict(
        rv, min_common_history_bars=min_common_history_bars
    )


# ============================================================================
# Lote A da liberação de features (H5, 2026-08-24) — C03-C05, C09-C12.
# Todas T2 (nenhuma promovida a T1 por esta implementação, §0.2 R4/§2.13).
# ============================================================================


def c03_realized_vol_48(log_return_1: FloatArray, window: int) -> FloatArray:
    """`σ(log_return) × √window` — §2.4 C03."""
    return support.realized_vol(log_return_1, window)


def c04_parkinson_vol_48(high: FloatArray, low: FloatArray, window: int) -> FloatArray:
    """Estimador de Parkinson (1980), fração do preço — §2.4 C04."""
    return support.parkinson_vol(high, low, window)


def c05_garman_klass_48(
    high: FloatArray, low: FloatArray, open_: FloatArray, close: FloatArray, window: int
) -> FloatArray:
    """Estimador de Garman-Klass (1980), fração do preço — §2.4 C05."""
    return support.garman_klass_vol(high, low, open_, close, window)


def c09_range_pctile_expanding(
    true_range_pct: FloatArray, *, min_common_history_bars: int | None = None
) -> FloatArray:
    """Posto expansivo estrito de `true_range_pct` (A11) — §2.4 C09.
    Mesma primitiva de C07 (`support.expanding_percentile_rank_strict`),
    sobre um sinal de entrada diferente."""
    return support.expanding_percentile_rank_strict(
        true_range_pct, min_common_history_bars=min_common_history_bars
    )


def c10_vol_expansion_flag(
    vol_ratio_12_96: FloatArray,
    threshold: float,
    *,
    min_common_history_bars: int | None = None,
) -> FloatArray:
    """`1.0` se `vol_ratio_12_96` está acima do quantil `threshold`
    EXPANSIVO (posto percentil estrito > threshold), senão `0.0` — §2.4
    C10. "Posto percentil > q" é equivalente por definição a "valor > q-
    ésimo percentil expansivo" — reaproveita `expanding_percentile_rank_
    strict` (mesma primitiva de C07/C09) em vez de uma nova função de
    quantil expansivo. NaN se o posto ainda não está definido (warmup)."""
    rank = support.expanding_percentile_rank_strict(
        vol_ratio_12_96, min_common_history_bars=min_common_history_bars
    )
    out: FloatArray = np.where(np.isnan(rank), np.nan, (rank > threshold).astype(np.float64))
    return out


def c11_vol_compression_flag(
    vol_ratio_12_96: FloatArray,
    threshold: float,
    *,
    min_common_history_bars: int | None = None,
) -> FloatArray:
    """`1.0` se `vol_ratio_12_96` está abaixo do quantil `threshold`
    EXPANSIVO, senão `0.0` — §2.4 C11. Mesma técnica de `c10_vol_
    expansion_flag`, comparação invertida."""
    rank = support.expanding_percentile_rank_strict(
        vol_ratio_12_96, min_common_history_bars=min_common_history_bars
    )
    out: FloatArray = np.where(np.isnan(rank), np.nan, (rank < threshold).astype(np.float64))
    return out


def c12_vol_of_vol_48(log_return_1: FloatArray, inner_window: int, outer_window: int) -> FloatArray:
    """`σ(realized_vol_{inner_window})` sobre `outer_window` barras —
    §2.4 C12. `realized_vol_12` (`inner_window`) via `support.
    realized_vol`; desvio-padrão rolante (`outer_window`, ddof=1, mesma
    convenção de `rolling_zscore`/`realized_vol`) calculado diretamente
    via `polars.rolling_std` — mesmo padrão já usado inline em
    `support.yang_zhang_vol`, não precisa de primitiva nova."""
    rv_inner = support.realized_vol(log_return_1, inner_window)
    out: FloatArray = (
        pl.Series(rv_inner)
        .rolling_std(window_size=outer_window, min_samples=outer_window, ddof=1)
        .to_numpy()
    )
    return out
