"""Testes de `src/analysis/cross_symbol_ess.py` — ESS transversal
(`AG-216`/`AG-255`). Núcleo puro (`_aggregate_daily`) testado sem IO;
`weighted_participation_ratio` já é testado em `test_models_hhi.py`
(reusado, não reescrito aqui)."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import polars as pl
import pytest

from src.analysis import cross_symbol_ess as css


def test_aggregate_daily_soma_ret_net_por_dia() -> None:
    t0 = [
        datetime(2024, 1, 1, 0, tzinfo=UTC),
        datetime(2024, 1, 1, 12, tzinfo=UTC),
        datetime(2024, 1, 2, 0, tzinfo=UTC),
    ]
    rows = pl.DataFrame(
        {
            "t0": pl.Series(t0).cast(pl.Datetime("ms")).dt.replace_time_zone("UTC"),
            "ret_net": pl.Series([0.01, 0.02, -0.005], dtype=pl.Float64),
        }
    )
    out = css._aggregate_daily(rows, symbol="BTCUSDT")
    assert out.columns == ["_day", "BTCUSDT"]
    assert out.sort("_day")["BTCUSDT"].to_list() == pytest.approx([0.03, -0.005])


def test_compute_cross_symbol_ess_2_simbolos_perfeitamente_correlacionados() -> None:
    """Sanidade end-to-end do núcleo estatístico (sem IO real): 2 séries
    IDÊNTICAS -- correlação = 1, N_eff deve cair pra 1 (toda a massa num
    único eixo), não 2."""
    rng = np.random.default_rng(1)
    corr = np.ones((2, 2))
    weights = np.array([0.5, 0.5])
    n_eff, hhi_eff, eigenvalues = css.weighted_participation_ratio(corr, weights)
    assert n_eff == pytest.approx(1.0)
    assert hhi_eff == pytest.approx(1.0)


def test_compute_cross_symbol_ess_simbolos_independentes_da_n_eff_igual_a_n() -> None:
    n = 5
    corr = np.eye(n)
    weights = np.full(n, 1.0 / n)
    n_eff, hhi_eff, _ = css.weighted_participation_ratio(corr, weights)
    assert n_eff == pytest.approx(float(n))
    assert hhi_eff == pytest.approx(1.0 / n)
