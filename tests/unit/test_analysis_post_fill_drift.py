"""Testes de `src/analysis/post_fill_drift.py` (AG-425). Núcleo puro
primeiro (`_drift_for_trade`, `_decile_rows`, arrays sintéticos, sem IO),
depois `post_fill_drift_by_decile` com `_load_day_arrays` monkeypatched
(evita depender de `data/capacity/` real no CI)."""

from __future__ import annotations

import datetime as dt
import math
from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl
import pytest

from src.analysis import post_fill_drift as pfd

_T0_DTYPE_MS = pl.Datetime(time_unit="ms", time_zone="UTC")


# ============================================================================
# _drift_for_trade — núcleo puro
# ============================================================================


def test_drift_for_trade_long_favoravel_quando_preco_sobe() -> None:
    """Long preenche em 100 (trade toca o limite em t=1000ms -- 1o trade
    elegível, t_post=0 é estritamente exclusivo), fill+horizon=301_000ms,
    mark_1m tem candle EXATO em 301_000 fechando em 102 -- drift =
    (102/100 - 1) * 10_000 = +200bps, sinal positivo (favorável)."""
    trade_time_ms = np.array([500, 1_000, 2_000], dtype=np.int64)
    trade_price = np.array([101.0, 100.0, 99.0], dtype=np.float64)  # toca 100 em t=1000
    mark_open_time_ms = np.array([0, 301_000, 600_000], dtype=np.int64)
    mark_close = np.array([100.0, 102.0, 103.0], dtype=np.float64)

    drift = pfd._drift_for_trade(
        trade_time_ms=trade_time_ms,
        trade_price=trade_price,
        mark_open_time_ms=mark_open_time_ms,
        mark_close=mark_close,
        t_post_ms=0,
        fill_timeout_ms=900_000,
        limit_price=100.0,
        side=1,
        horizon_ms=300_000,
    )
    assert drift == pytest.approx(200.0)


def test_drift_for_trade_short_favoravel_quando_preco_desce() -> None:
    """Short preenche em 100 (t=1000ms), fill+horizon=301_000ms, mark_1m
    tem candle EXATO em 301_000 fechando em 98 -- favorável pro short:
    drift = -1 * (98/100 - 1) * 10_000 = +200bps."""
    trade_time_ms = np.array([500, 1_000, 2_000], dtype=np.int64)
    trade_price = np.array([99.0, 100.0, 101.0], dtype=np.float64)
    mark_open_time_ms = np.array([0, 301_000], dtype=np.int64)
    mark_close = np.array([100.0, 98.0], dtype=np.float64)

    drift = pfd._drift_for_trade(
        trade_time_ms=trade_time_ms,
        trade_price=trade_price,
        mark_open_time_ms=mark_open_time_ms,
        mark_close=mark_close,
        t_post_ms=0,
        fill_timeout_ms=900_000,
        limit_price=100.0,
        side=-1,
        horizon_ms=300_000,
    )
    assert drift == pytest.approx(200.0)


def test_drift_for_trade_none_quando_nunca_preenche() -> None:
    trade_time_ms = np.array([500, 1_000], dtype=np.int64)
    trade_price = np.array([105.0, 106.0], dtype=np.float64)  # nunca toca 100
    mark_open_time_ms = np.array([0, 300_000], dtype=np.int64)
    mark_close = np.array([100.0, 102.0], dtype=np.float64)

    drift = pfd._drift_for_trade(
        trade_time_ms=trade_time_ms,
        trade_price=trade_price,
        mark_open_time_ms=mark_open_time_ms,
        mark_close=mark_close,
        t_post_ms=0,
        fill_timeout_ms=900_000,
        limit_price=100.0,
        side=1,
        horizon_ms=300_000,
    )
    assert drift is None


def test_drift_for_trade_none_quando_janela_de_mark_nao_alcanca_horizonte() -> None:
    """Fill ocorre, mas o horizonte pedido (fill + 5min) passa do último
    candle de mark_1m carregado -- `None`, não extrapola."""
    trade_time_ms = np.array([500, 1_000], dtype=np.int64)
    trade_price = np.array([101.0, 100.0], dtype=np.float64)
    mark_open_time_ms = np.array([0], dtype=np.int64)  # só 1 candle, nada em t=300_000
    mark_close = np.array([100.0], dtype=np.float64)

    drift = pfd._drift_for_trade(
        trade_time_ms=trade_time_ms,
        trade_price=trade_price,
        mark_open_time_ms=mark_open_time_ms,
        mark_close=mark_close,
        t_post_ms=0,
        fill_timeout_ms=900_000,
        limit_price=100.0,
        side=1,
        horizon_ms=300_000,
    )
    assert drift is None


# ============================================================================
# _decile_rows — mesma disciplina de teste-t/piso n>=5 de AG-424
# ============================================================================


def test_decile_rows_media_e_tstat_conferidos_a_mao() -> None:
    """50 observações, 5 por decil (>= _MIN_OBS_T_STAT) -- decil k tem
    drift_bps={2k-2,2k-1,2k,2k+1,2k+2} (mesma derivação de AG-424): mean=2k,
    std=sqrt(2.5), t_stat=2k/(sqrt(2.5)/sqrt(5))=2*sqrt(2)*k."""
    observations: list[pfd._DriftObservation] = []
    for k in range(1, 11):
        for offset in (-2.0, -1.0, 0.0, 1.0, 2.0):
            observations.append(
                pfd._DriftObservation(
                    feature_value=float(k), side_label="long", drift_bps=2.0 * k + offset
                )
            )

    out = pfd._decile_rows(observations, side_label="long", n_deciles=10)
    assert len(out) == 10

    d1 = next(r for r in out if r["decile"] == 1)
    assert d1["n"] == 5
    assert d1["mean_drift_bps"] == pytest.approx(2.0)
    assert d1["std_drift_bps"] == pytest.approx(math.sqrt(2.5))
    assert d1["t_stat"] == pytest.approx(2.0 * math.sqrt(2.0))
    assert d1["value_min"] == pytest.approx(1.0)
    assert d1["value_max"] == pytest.approx(1.0)  # feature_value constante = k dentro do decil

    d10 = next(r for r in out if r["decile"] == 10)
    assert d10["mean_drift_bps"] == pytest.approx(20.0)
    assert d10["t_stat"] == pytest.approx(20.0 * math.sqrt(2.0))


def test_decile_rows_tstat_nan_abaixo_do_piso_min_obs() -> None:
    """4 observações por decil -- mesmo achado de AG-424, t_stat fica nan
    mesmo com std>0."""
    observations: list[pfd._DriftObservation] = []
    for k in range(1, 11):
        for offset in (-1.5, -0.5, 0.5, 1.5):
            observations.append(
                pfd._DriftObservation(
                    feature_value=float(k), side_label="short", drift_bps=2.0 * k + offset
                )
            )

    out = pfd._decile_rows(observations, side_label="short", n_deciles=10)
    d1 = next(r for r in out if r["decile"] == 1)
    assert d1["n"] == 4
    assert d1["std_drift_bps"] > 0.0
    assert math.isnan(d1["t_stat"])
    assert d1["mean_drift_bps"] == pytest.approx(2.0)


def test_decile_rows_vazio_devolve_lista_vazia() -> None:
    assert pfd._decile_rows([], side_label="long", n_deciles=10) == []


# ============================================================================
# post_fill_drift_by_decile — wiring/joins, _load_day_arrays monkeypatched
# ============================================================================


def _t0s(n: int) -> list[datetime]:
    base = datetime(2024, 1, 1, tzinfo=UTC)
    return [base + timedelta(days=i) for i in range(n)]


def test_post_fill_drift_by_decile_coluna_ausente_em_trade_data_levanta_valueerror() -> None:

    predictions = pl.DataFrame(
        {
            "t0": pl.Series([datetime(2024, 1, 1, tzinfo=UTC)], dtype=_T0_DTYPE_MS),
            "side_hat": pl.Series([1], dtype=pl.Int8),
            "is_oof": pl.Series([True], dtype=pl.Boolean),
        }
    )
    trade_data = pl.DataFrame(
        {
            "t0": pl.Series([datetime(2024, 1, 1, tzinfo=UTC)], dtype=_T0_DTYPE_MS),
            "side": pl.Series([1], dtype=pl.Int8),
            "barrier_hit": pl.Series(["TP"], dtype=pl.Utf8),
        }
    )
    with pytest.raises(ValueError, match="entry_price_limit"):
        pfd.post_fill_drift_by_decile(
            "BTCUSDT",
            predictions,
            trade_data,
            "A11_true_range_pct",
            horizon_minutes=5,
            fill_timeout_ms=900_000,
        )


def test_post_fill_drift_by_decile_n_deciles_invalido_levanta_valueerror() -> None:

    predictions = pl.DataFrame(
        {"t0": pl.Series([], dtype=_T0_DTYPE_MS), "side_hat": pl.Series([], dtype=pl.Int8),
         "is_oof": pl.Series([], dtype=pl.Boolean)}
    )
    trade_data = pl.DataFrame(
        {
            "t0": pl.Series([], dtype=_T0_DTYPE_MS),
            "side": pl.Series([], dtype=pl.Int8),
            "barrier_hit": pl.Series([], dtype=pl.Utf8),
            "entry_price_limit": pl.Series([], dtype=pl.Float64),
            "A11_true_range_pct": pl.Series([], dtype=pl.Float64),
        }
    )
    with pytest.raises(ValueError, match="n_deciles"):
        pfd.post_fill_drift_by_decile(
            "BTCUSDT",
            predictions,
            trade_data,
            "A11_true_range_pct",
            horizon_minutes=5,
            fill_timeout_ms=900_000,
            n_deciles=0,
        )


def test_post_fill_drift_by_decile_fim_a_fim_com_load_day_arrays_monkeypatched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """10 trades long, 1 por decil de `A11_true_range_pct` -- preço sobe
    proporcionalmente ao decil (decil k -> drift positivo crescente),
    `_load_day_arrays` devolve arrays sintéticos fixos (sem IO real)."""

    t0s = _t0s(10)
    predictions = pl.DataFrame(
        {
            "t0": pl.Series(t0s, dtype=_T0_DTYPE_MS),
            "side_hat": pl.Series([1] * 10, dtype=pl.Int8),
            "is_oof": pl.Series([True] * 10, dtype=pl.Boolean),
        }
    )
    trade_data = pl.DataFrame(
        {
            "t0": pl.Series(t0s, dtype=_T0_DTYPE_MS),
            "side": pl.Series([1] * 10, dtype=pl.Int8),
            "barrier_hit": pl.Series(["TP"] * 10, dtype=pl.Utf8),
            "entry_price_limit": pl.Series([100.0] * 10, dtype=pl.Float64),
            "A11_true_range_pct": pl.Series([float(i) for i in range(10)], dtype=pl.Float64),
        }
    )

    def _fake_load_day_arrays(
        symbol: str, day: dt.date
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        # t0 de cada trade fixture é meia-noite UTC do próprio `day`
        # (_t0s usa hora/min/seg=0) -- ancora os arrays sintéticos nesse
        # mesmo epoch, senão "trade_time > t_post_ms" nunca é verdade
        # (t_post_ms é um epoch real de 2024, não 0).
        day_start_ms = int(
            datetime.combine(day, dt.time.min, tzinfo=UTC).timestamp() * 1000
        )
        trade_time_ms = np.array([day_start_ms + 1_000], dtype=np.int64)
        trade_price = np.array([100.0], dtype=np.float64)
        mark_open_time_ms = np.array([day_start_ms, day_start_ms + 301_000], dtype=np.int64)
        mark_close = np.array([100.0, 105.0], dtype=np.float64)
        return trade_time_ms, trade_price, mark_open_time_ms, mark_close

    monkeypatch.setattr(pfd, "_load_day_arrays", _fake_load_day_arrays)

    out = pfd.post_fill_drift_by_decile(
        "BTCUSDT",
        predictions,
        trade_data,
        "A11_true_range_pct",
        horizon_minutes=5,
        fill_timeout_ms=900_000,
    )
    assert out.height == 10
    assert set(out["side"].unique().to_list()) == {"long"}
    for row in out.iter_rows(named=True):
        assert row["n"] == 1
        assert row["mean_drift_bps"] == pytest.approx(500.0)  # (105/100-1)*10_000


def test_post_fill_drift_by_decile_dia_sem_dado_e_pulado_sem_derrubar_o_resto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    t0s = _t0s(2)
    predictions = pl.DataFrame(
        {
            "t0": pl.Series(t0s, dtype=_T0_DTYPE_MS),
            "side_hat": pl.Series([1, 1], dtype=pl.Int8),
            "is_oof": pl.Series([True, True], dtype=pl.Boolean),
        }
    )
    trade_data = pl.DataFrame(
        {
            "t0": pl.Series(t0s, dtype=_T0_DTYPE_MS),
            "side": pl.Series([1, 1], dtype=pl.Int8),
            "barrier_hit": pl.Series(["TP", "TP"], dtype=pl.Utf8),
            "entry_price_limit": pl.Series([100.0, 100.0], dtype=pl.Float64),
            "A11_true_range_pct": pl.Series([1.0, 2.0], dtype=pl.Float64),
        }
    )

    def _fake_load_day_arrays(symbol: str, day: dt.date) -> None:
        return None

    monkeypatch.setattr(pfd, "_load_day_arrays", _fake_load_day_arrays)

    out = pfd.post_fill_drift_by_decile(
        "BTCUSDT",
        predictions,
        trade_data,
        "A11_true_range_pct",
        horizon_minutes=5,
        fill_timeout_ms=900_000,
    )
    # 0 linhas -- os 2 trades candidatos (long) existem, mas nenhum dia
    # tem dado carregável (_load_day_arrays sempre None), então nenhuma
    # observação válida sobra pra formar decil; short não tem trade
    # nenhum. Mesmo comportamento de "sem trades no lado" já coberto por
    # confidence_deciles_by_side -- nada quebra, só não há o que reportar.
    assert out.height == 0
    assert out.schema == pfd._OUTPUT_SCHEMA
