"""Testes de `src/models/backtest_lite.py` — harness de avaliação mínimo
desta rodada (Sharpe ingênuo, não corrigido por autocorrelação/DSR, ver
docstring do módulo)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl

from src.models import backtest_lite

_DAY_S = 86_400.0  # noqa: magic-number — segundos por dia, calendário


def test_sharpe_naive_retorno_constante_positivo_da_sharpe_positivo() -> None:
    rets = np.full(50, 0.01)  # noqa: magic-number
    # variância zero -> std=0 -> nan (Sharpe indefinido sem dispersão)
    sharpe, tpy = backtest_lite.sharpe_naive(rets, span_seconds=365 * _DAY_S)
    assert np.isnan(sharpe)
    assert tpy > 0.0


def test_sharpe_naive_retornos_com_dispersao() -> None:
    rng = np.random.default_rng(0)
    rets = rng.normal(loc=0.001, scale=0.01, size=200)  # noqa: magic-number
    sharpe, tpy = backtest_lite.sharpe_naive(rets, span_seconds=365 * _DAY_S)
    assert np.isfinite(sharpe)
    assert sharpe > 0.0  # média positiva, desvio positivo -> Sharpe positivo
    assert tpy > 0.0


def test_sharpe_naive_poucos_trades_retorna_nan() -> None:
    sharpe, tpy = backtest_lite.sharpe_naive(np.array([0.01]), span_seconds=1000.0)
    assert np.isnan(sharpe)
    assert np.isnan(tpy)


def test_sharpe_naive_span_zero_retorna_nan() -> None:
    sharpe, tpy = backtest_lite.sharpe_naive(np.array([0.01, 0.02, -0.01]), span_seconds=0.0)
    assert np.isnan(sharpe)
    assert np.isnan(tpy)


def test_span_seconds_calcula_intervalo_correto() -> None:
    t0 = pl.Series(
        [datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 11, tzinfo=UTC)]
    ).cast(pl.Datetime("ms")).dt.replace_time_zone("UTC")
    span = backtest_lite.span_seconds(t0)
    assert abs(span - 10 * _DAY_S) < 1.0  # noqa: magic-number


def test_span_seconds_menos_de_2_pontos_retorna_zero() -> None:
    t0 = pl.Series([datetime(2024, 1, 1, tzinfo=UTC)]).cast(pl.Datetime("ms")).dt.replace_time_zone(
        "UTC"
    )
    assert backtest_lite.span_seconds(t0) == 0.0


def test_permanence_count_conta_paths_onde_camada1_supera_camada0() -> None:
    def _mk(path_id: int, sharpe: float) -> backtest_lite.PathBacktestResult:
        return backtest_lite.PathBacktestResult(
            path_id=path_id,
            n_signals=10,
            n_filled_trades=10,
            fill_rate=1.0,
            sharpe_naive=sharpe,
            mean_trade_ret=0.0,
            std_trade_ret=0.01,
            trades_per_year=100.0,
        )

    c1 = {0: _mk(0, 0.5), 1: _mk(1, -0.2), 2: _mk(2, 1.0)}
    c0 = {0: _mk(0, 0.1), 1: _mk(1, 0.3), 2: _mk(2, -1.0)}
    n_better, n_total = backtest_lite.permanence_count(c1, c0)
    assert n_total == 3
    assert n_better == 2  # paths 0 e 2 melhoram; path 1 piora


def test_permanence_count_nan_nunca_conta_como_melhora() -> None:
    def _mk(sharpe: float) -> backtest_lite.PathBacktestResult:
        return backtest_lite.PathBacktestResult(
            path_id=0,
            n_signals=0,
            n_filled_trades=0,
            fill_rate=float("nan"),
            sharpe_naive=sharpe,
            mean_trade_ret=float("nan"),
            std_trade_ret=float("nan"),
            trades_per_year=float("nan"),
        )

    c1 = {0: _mk(float("nan"))}
    c0 = {0: _mk(0.1)}
    n_better, n_total = backtest_lite.permanence_count(c1, c0)
    assert n_total == 1
    assert n_better == 0
