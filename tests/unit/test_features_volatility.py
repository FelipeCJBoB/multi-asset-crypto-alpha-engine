"""Testes de `src/features/volatility.py` -- `VolatilityEstimator`
(PRD_V4_1.md T0.1) e os candidatos de M1 (§3.2, Camada 1). Eixos: (1)
unit puro com barras sintéticas, comparando cada `*Estimator` contra a
primitiva `support.*` chamada direto (garante que o wrapper não introduz
nenhuma transformação além do que o docstring declara); (2) golden
bit-exato de `ATRWilderEstimator` contra `data/labels/BTCUSDT/15m/v1/
labels.parquet::atr_at_t0` (G-C0-1) -- recomputa ATR das mesmas `bars_15m`
(BTCUSDT, `close_time == t0`, `triple_barrier.py:573/576-577`) que o
Label Engine usou e compara com tolerância zero. `Parkinson`/`GarmanKlass`/
`RealizedVol` (3 dos 6 candidatos de M1) não têm golden -- não são
produção ainda, não existe artefato de referência pra comparar.

Caminho migrado do legado `labels/v1/labels.parquet` pro layout chaveado
(T0.3, PRD_V4_1.md §3.1) nesta mesma rodada -- via
`src.validation.cpcv.load_labels_v1()`, o loader canônico único."""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from src.data import lake
from src.features import support
from src.features.volatility import (
    ATRWilderEstimator,
    Bars,
    GarmanKlassEstimator,
    ParkinsonEstimator,
    RealizedVolEstimator,
)
from src.validation._paths import labels_symbol_tf_dir

_LABELS_PATH = labels_symbol_tf_dir("BTCUSDT", "v1") / "labels.parquet"


def _synthetic_bars(n: int = 40) -> pl.DataFrame:
    rng = np.random.default_rng(7)
    close = 100.0 + np.cumsum(rng.normal(0, 0.5, n))
    high = close + rng.uniform(0, 1, n)
    low = close - rng.uniform(0, 1, n)
    open_ = close + rng.normal(0, 0.1, n)
    return pl.DataFrame({"open": open_, "high": high, "low": low, "close": close})


def test_atr_wilder_estimator_bate_com_support_direto() -> None:
    frame = _synthetic_bars()
    window = 5
    bars = Bars(frame=frame, timeframe_minutes=15)
    estimator = ATRWilderEstimator(window=window)
    got = estimator.estimate(bars, horizon_minutes=15)

    high = frame["high"].to_numpy()
    low = frame["low"].to_numpy()
    close = frame["close"].to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        expected = support.atr_wilder(high, low, close, window) / close

    both_nan = np.isnan(got) & np.isnan(expected)
    assert np.array_equal(got[~both_nan], expected[~both_nan])
    assert np.array_equal(np.isnan(got), np.isnan(expected))


def test_atr_wilder_estimator_warmup_bars_e_estimator_id() -> None:
    estimator = ATRWilderEstimator(window=20)
    assert estimator.warmup_bars == 20
    assert estimator.estimator_id == "atr_wilder_w20"


def test_atr_wilder_estimator_horizonte_diferente_do_nativo_levanta() -> None:
    # I2 (PRD §2.7): conversão clock-based entre TFs é escopo do M1, não
    # implementada aqui -- deve levantar, não fabricar um número.
    bars = Bars(frame=_synthetic_bars(), timeframe_minutes=15)
    estimator = ATRWilderEstimator(window=5)
    with pytest.raises(NotImplementedError):
        estimator.estimate(bars, horizon_minutes=30)


def test_from_constants_le_atr_window_de_constants_yaml() -> None:
    from src.features._constants import load_constant

    estimator = ATRWilderEstimator.from_constants()
    assert estimator.window == int(load_constant("atr_window"))


# ============================================================================
# ParkinsonEstimator / GarmanKlassEstimator / RealizedVolEstimator
# (PRD_V4_1.md §3.2 M1 -- 3 dos 6 candidatos, wrappers finos sobre
# support.py; mesma disciplina de horizon_minutes/warmup_bars/
# estimator_id do ATRWilderEstimator)
# ============================================================================


def test_parkinson_estimator_bate_com_support_direto() -> None:
    frame = _synthetic_bars()
    window = 5
    bars = Bars(frame=frame, timeframe_minutes=15)
    got = ParkinsonEstimator(window=window).estimate(bars, horizon_minutes=15)
    expected = support.parkinson_vol(
        frame["high"].to_numpy(), frame["low"].to_numpy(), window
    )
    both_nan = np.isnan(got) & np.isnan(expected)
    assert np.array_equal(got[~both_nan], expected[~both_nan])
    assert np.array_equal(np.isnan(got), np.isnan(expected))


def test_parkinson_estimator_warmup_bars_e_estimator_id() -> None:
    estimator = ParkinsonEstimator(window=20)
    assert estimator.warmup_bars == 20
    assert estimator.estimator_id == "parkinson_w20"


def test_parkinson_estimator_horizonte_diferente_do_nativo_levanta() -> None:
    bars = Bars(frame=_synthetic_bars(), timeframe_minutes=15)
    with pytest.raises(NotImplementedError):
        ParkinsonEstimator(window=5).estimate(bars, horizon_minutes=30)


def test_garman_klass_estimator_bate_com_support_direto() -> None:
    frame = _synthetic_bars()
    window = 5
    bars = Bars(frame=frame, timeframe_minutes=15)
    got = GarmanKlassEstimator(window=window).estimate(bars, horizon_minutes=15)
    expected = support.garman_klass_vol(
        frame["high"].to_numpy(),
        frame["low"].to_numpy(),
        frame["open"].to_numpy(),
        frame["close"].to_numpy(),
        window,
    )
    both_nan = np.isnan(got) & np.isnan(expected)
    assert np.array_equal(got[~both_nan], expected[~both_nan])
    assert np.array_equal(np.isnan(got), np.isnan(expected))


def test_garman_klass_estimator_warmup_bars_e_estimator_id() -> None:
    estimator = GarmanKlassEstimator(window=20)
    assert estimator.warmup_bars == 20
    assert estimator.estimator_id == "garman_klass_w20"


def test_garman_klass_estimator_horizonte_diferente_do_nativo_levanta() -> None:
    bars = Bars(frame=_synthetic_bars(), timeframe_minutes=15)
    with pytest.raises(NotImplementedError):
        GarmanKlassEstimator(window=5).estimate(bars, horizon_minutes=30)


def test_realized_vol_estimator_bate_com_support_direto() -> None:
    frame = _synthetic_bars()
    window = 5
    bars = Bars(frame=frame, timeframe_minutes=15)
    got = RealizedVolEstimator(window=window).estimate(bars, horizon_minutes=15)

    close = frame["close"].to_numpy()
    n = close.shape[0]
    log_return = np.full(n, np.nan, dtype=np.float64)
    log_return[1:] = np.log(close[1:] / close[:-1])
    expected = support.realized_vol(log_return, window)

    both_nan = np.isnan(got) & np.isnan(expected)
    assert np.array_equal(got[~both_nan], expected[~both_nan])
    assert np.array_equal(np.isnan(got), np.isnan(expected))


def test_realized_vol_estimator_warmup_bars_e_estimator_id() -> None:
    estimator = RealizedVolEstimator(window=20)
    assert estimator.warmup_bars == 21  # +1: log_return[0] sempre NaN
    assert estimator.estimator_id == "realized_vol_w20"


def test_realized_vol_estimator_horizonte_diferente_do_nativo_levanta() -> None:
    bars = Bars(frame=_synthetic_bars(), timeframe_minutes=15)
    with pytest.raises(NotImplementedError):
        RealizedVolEstimator(window=5).estimate(bars, horizon_minutes=30)


def _skip_if_labels_missing() -> None:
    if not _LABELS_PATH.exists():
        pytest.skip(f"{_LABELS_PATH} ausente -- rode o Label Engine (Sprint 6) primeiro")


@pytest.mark.golden
@pytest.mark.integration
@pytest.mark.slow
def test_atr_wilder_estimator_bate_bit_exato_com_labels_v1() -> None:
    """G-C0-1 -- golden bit-exato contra o artefato persistido. Reconstrói
    a MESMA `bars_15m` (BTCUSDT) que o Label Engine usou e junta por `t0`
    (== `close_time`) em vez de confiar em alinhamento posicional entre
    dois DataFrames carregados de fontes diferentes.

    `t0` em `labels.parquet` já foi convertido pra `Datetime("ms")` UTC
    (`triple_barrier.py::_finalize_pre_weight_frame`, via `_ms_epoch_to_utc`)
    -- não é mais o Int64 ms epoch do schema pré-conversão. `close_time`
    de `bars_15m` (klines cru) ainda é Int64 ms epoch; convertido aqui do
    mesmo jeito pra bater tipo no join."""
    _skip_if_labels_missing()
    labels = pl.read_parquet(_LABELS_PATH, columns=["t0", "atr_at_t0"])
    start = labels["t0"].min().date()
    end = labels["t0"].max().date()

    bars_15m = lake.query_bars("BTCUSDT", "15m", start, end, source="klines_1m", cast_prices=True)
    estimator = ATRWilderEstimator.from_constants()
    bars = Bars(frame=bars_15m, timeframe_minutes=15)
    atr_pct = estimator.estimate(bars, horizon_minutes=15)

    t0_from_bars = (
        bars_15m["close_time"].cast(pl.Int64).cast(pl.Datetime("ms")).dt.replace_time_zone("UTC")
    )
    recomputed = pl.DataFrame({"t0": t0_from_bars, "atr_at_t0_recomputed": atr_pct})
    joined = labels.join(recomputed, on="t0", how="inner")
    assert joined.height > 0, "nenhum t0 de labels.parquet bateu com bars_15m reconstruído"

    left = joined["atr_at_t0"].to_numpy()
    right = joined["atr_at_t0_recomputed"].to_numpy()
    both_nan = np.isnan(left) & np.isnan(right)
    assert np.array_equal(left[~both_nan], right[~both_nan]), (
        "ATRWilderEstimator diverge bit-a-bit de atr_at_t0 persistido em labels/v1/labels.parquet"
    )
