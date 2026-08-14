"""Testes de `src/analysis/m3_timeframe_choice.py` -- PRD_V4_1.md §3.2 M3.

A matemática de R1 (`_r1_vectorized`/`_r1_pass`) e das fórmulas de
`feasibility.py` (`breakeven_win_rate`/`trades_per_year_budget`) já é
testada em `test_analysis_volatility_operational_effect.py`/
`test_analysis_feasibility.py` -- este módulo só ORQUESTRA essas peças já
testadas por TF, então o que vale testar aqui é a orquestração em si:
(1) a duplicação local de `_TF_TO_MINUTES` não diverge da fonte canônica
de `src.data.resample`; (2) `compute_timeframe_choice_for_symbol` roda de
ponta a ponta sobre dado real (integration/slow, skip se backfill local
ausente) -- mesma convenção de `test_analysis_volatility_comparison.py`."""

from __future__ import annotations

import math

import pytest

from src.analysis.m3_timeframe_choice import _TF_TO_MINUTES, compute_timeframe_choice_for_symbol
from src.analysis.volatility_comparison import TIMEFRAMES
from src.data._paths import CAPACITY_DIR
from src.data.resample import _TIMEFRAME_MINUTES


def test_tf_to_minutes_bate_com_resample_canonico_para_todos_os_tfs_usados() -> None:
    for tf in TIMEFRAMES:
        assert _TF_TO_MINUTES[tf] == _TIMEFRAME_MINUTES[tf], tf


def _skip_if_no_backfill() -> None:
    if not (CAPACITY_DIR / "klines_1m" / "BTCUSDT" / "2020-01-01.parquet").exists():
        pytest.skip("backfill local de klines_1m/BTCUSDT ausente -- rode o download primeiro")


@pytest.mark.integration
@pytest.mark.slow
def test_compute_timeframe_choice_for_symbol_btcusdt_sobre_dado_real() -> None:
    _skip_if_no_backfill()
    results = compute_timeframe_choice_for_symbol("BTCUSDT")

    assert [r.tf for r in results] == list(TIMEFRAMES)
    for r in results:
        assert r.symbol == "BTCUSDT"
        assert r.n_bars > 0
        assert r.n_valid > 0
        assert r.atr_pct_median > 0
        assert not math.isnan(r.atr_pct_median)
        assert r.atr_pct_p25 <= r.atr_pct_median <= r.atr_pct_p75
        assert r.custo_atr_median > 0
        assert 0.0 <= r.r1_pass_fraction <= 1.0
        assert 0.0 <= r.r2_pass_fraction <= 1.0
        assert 0.0 <= r.janela_viavel_fraction <= 1.0
        assert not math.isnan(r.breakeven_win_rate)
        assert not math.isnan(r.trades_per_year_budget)
