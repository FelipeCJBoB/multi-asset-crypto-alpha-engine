"""Testes do núcleo puro de `src.analysis.regime_cutoff_sweep` (`AG-342`) --
`_linspace_grid`/`_summarize_regime_distribution` não tocam disco, então
cobertos aqui sem depender de `build_t1_features`/backfill real."""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from src.analysis import regime_cutoff_sweep as sweep
from src.regime.classifier import REGIME_LABELS


def test_linspace_grid_inclui_as_duas_pontas() -> None:
    grid = sweep._linspace_grid(0.45, 0.75, 5)
    assert grid[0] == pytest.approx(0.45)
    assert grid[-1] == pytest.approx(0.75)
    assert len(grid) == 5


def test_linspace_grid_n_impar_inclui_o_ponto_medio_exato() -> None:
    grid = sweep._linspace_grid(0.45, 0.75, 5)
    assert grid[2] == pytest.approx(0.60)


def test_linspace_grid_n_menor_que_2_levanta_erro() -> None:
    with pytest.raises(ValueError, match="n deve ser >= 2"):
        sweep._linspace_grid(0.0, 1.0, 1)


def _synthetic_regime_df(regimes: list[str], bars_in_regime: list[int]) -> pl.DataFrame:
    n = len(regimes)
    assert len(bars_in_regime) == n
    return pl.DataFrame(
        {
            "regime": pl.Series(regimes, dtype=pl.Enum(list(REGIME_LABELS))),
            "bars_in_regime": pl.Series(bars_in_regime, dtype=pl.Int32),
            "tradeable": [r in ("R1", "R2", "R3", "R4") for r in regimes],
        }
    )


def test_summarize_regime_distribution_fracoes_somam_1() -> None:
    df = _synthetic_regime_df(
        ["R0", "R0", "R1", "R1", "R1", "R4"],
        [1, 2, 2, 3, 4, 2],
    )
    cell = sweep._summarize_regime_distribution(
        df, symbol="BTCUSDT", er_cutoff_enter=0.60, er_cutoff_exit=0.55,
        vol_cutoff_enter=0.70, vol_cutoff_exit=0.65,
    )
    assert cell.n_bars == 6
    assert sum(cell.regime_fraction.values()) == pytest.approx(1.0)
    assert cell.regime_fraction["R0"] == pytest.approx(2 / 6)
    assert cell.regime_fraction["R1"] == pytest.approx(3 / 6)
    assert cell.regime_fraction["R4"] == pytest.approx(1 / 6)


def test_summarize_regime_distribution_tradeable_exclui_r0_e_r5() -> None:
    df = _synthetic_regime_df(["R0", "R1", "R5"], [1, 2, 1])
    cell = sweep._summarize_regime_distribution(
        df, symbol="BTCUSDT", er_cutoff_enter=0.60, er_cutoff_exit=0.55,
        vol_cutoff_enter=0.70, vol_cutoff_exit=0.65,
    )
    # 1 de 3 barras (R1) é tradeable
    assert cell.tradeable_fraction == pytest.approx(1 / 3)


def test_summarize_regime_distribution_bars_in_regime_ignora_r0() -> None:
    """R0 (warmup) não deveria dominar a distribuição de persistência --
    a função filtra R0 antes de calcular médias/percentis de
    `bars_in_regime`."""
    df = _synthetic_regime_df(
        ["R0", "R0", "R0", "R1", "R1"],
        [1, 1, 1, 10, 20],
    )
    cell = sweep._summarize_regime_distribution(
        df, symbol="BTCUSDT", er_cutoff_enter=0.60, er_cutoff_exit=0.55,
        vol_cutoff_enter=0.70, vol_cutoff_exit=0.65,
    )
    assert cell.bars_in_regime_median == pytest.approx(15.0)


def test_summarize_regime_distribution_conta_transicoes() -> None:
    df = _synthetic_regime_df(
        ["R1", "R1", "R2", "R2", "R1", "R1"],
        [2, 2, 2, 2, 2, 2],
    )
    cell = sweep._summarize_regime_distribution(
        df, symbol="BTCUSDT", er_cutoff_enter=0.60, er_cutoff_exit=0.55,
        vol_cutoff_enter=0.70, vol_cutoff_exit=0.65,
    )
    # R1->R2 (t=2) e R2->R1 (t=4): 2 transições
    assert cell.n_transitions == 2
    assert cell.transitions_per_1000_bars == pytest.approx((2 / 6) * 1000.0)


def test_summarize_regime_distribution_frame_vazio_nao_quebra() -> None:
    df = _synthetic_regime_df([], [])
    cell = sweep._summarize_regime_distribution(
        df, symbol="BTCUSDT", er_cutoff_enter=0.60, er_cutoff_exit=0.55,
        vol_cutoff_enter=0.70, vol_cutoff_exit=0.65,
    )
    assert cell.n_bars == 0
    assert np.isnan(cell.tradeable_fraction)
    assert np.isnan(cell.bars_in_regime_median)
    assert np.isnan(cell.transitions_per_1000_bars)
