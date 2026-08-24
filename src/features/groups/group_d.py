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


# ============================================================================
# Lote B da liberação de features (H5, 2026-08-24) — D07f, D10f.
# D07f precisa de fonte nova (klines_1m, além de klines_1m já-resampled-
# pra-15m que o resto do Feature Engine usa) -- núcleo puro aqui, ponto
# de entrada com IO em `_sources.py::load_taker_imbalance_1m_agg_aligned`.
# D10f precisa de primitiva nova (correlação rolante, support.py).
# ============================================================================


def d07f_taker_imbalance_1m_agg(
    taker_buy_volume_1m: FloatArray,
    volume_1m: FloatArray,
    bucket_id_1m: FloatArray,
    bucket_id_15m: FloatArray,
) -> FloatArray:
    """Média de `2×taker_buy_ratio-1` das barras de 1m dentro de cada
    barra de 15m — §2.5 D07f. PRD original (a 30m) cita "30 barras de
    1m"; sob 15m real, são as barras de 1m cujo `bucket_id` (janela de
    relógio fixa, `open_time // step_ms("15m")`, calculado pelo
    chamador) bate com o `bucket_id` da barra de 15m alvo — contagem
    natural = 15, não hardcoded (mesma disciplina de não recalibrar
    contagens de barra herdadas do PRD a menos que a própria janela
    dependa disso, aqui não depende).

    Núcleo puro (Idioma A) — recebe `bucket_id_1m`/`bucket_id_15m` já
    resolvidos pelo chamador (mesmo padrão de `funding_last_aligned`/
    `oi_contracts_aligned`: esta função não sabe de timestamp bruto nem
    de IO, só de arrays já alinhados/rotulados). `taker_buy_volume_1m`/
    `volume_1m` continuam em ORDEM CRONOLÓGICA de 1m — o agrupamento por
    `bucket_id_1m` é causal por construção (cada bucket de 15m só agrega
    as barras de 1m que ele mesmo contém, nunca uma barra de outro
    bucket)."""
    with np.errstate(divide="ignore", invalid="ignore"):
        imbalance_1m: FloatArray = 2.0 * (taker_buy_volume_1m / volume_1m) - 1.0
    df = pl.DataFrame({"bucket_id": bucket_id_1m, "imbalance": imbalance_1m})
    agg = df.group_by("bucket_id", maintain_order=True).agg(pl.col("imbalance").mean())
    lookup = dict(
        zip(agg["bucket_id"].to_list(), agg["imbalance"].to_list(), strict=True)
    )
    out = np.array([lookup.get(int(b), np.nan) for b in bucket_id_15m], dtype=np.float64)
    return out


def d10f_vol_price_divergence(
    log_return_1: FloatArray, volume: FloatArray, window: int
) -> FloatArray:
    """Correlação rolante (janela `window`) de `|ret|` × `volume_z` —
    §2.5 D10f. `volume_z` computado INTERNAMENTE
    (`support.rolling_zscore(volume, window)`, mesmo `window` da
    correlação) — o PRD não referencia nenhuma feature `D0Xf` existente
    com janela=48 pra volume_z (`D01f_volume_z_96` é janela 96,
    `D03f_volume_z_expanding` é expansiva), então calcular um `volume_z`
    dedicado aqui evita a ambiguidade de qual reaproveitar sob um
    `window` que não bate com nenhuma das duas."""
    abs_ret = np.abs(log_return_1)
    volume_z = support.rolling_zscore(volume, window)
    return support.rolling_correlation(abs_ret, volume_z, window)
