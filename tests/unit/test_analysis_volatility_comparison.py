"""Testes de `src/analysis/volatility_comparison.py` -- M1 (PRD_V4_1.md
§3.2), orquestração real dos 4 candidatos implementados sobre bars.
`compare_estimators_for_combination` é o núcleo puro (bars sintéticas, sem
IO); `run_volatility_comparison_for_symbol_tf` é o único ponto que toca
disco real (`integration`, pula se o backfill local não existir)."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import polars as pl
import pytest

from src.analysis import volatility_comparison as vc
from src.data._paths import CAPACITY_DIR


def _daily_open_time_ms(start: str, n_days: int) -> np.ndarray:
    start_dt = datetime.fromisoformat(start).replace(tzinfo=UTC)
    start_ms = int(start_dt.timestamp() * 1000)
    day_ms = 86_400_000
    return np.array([start_ms + i * day_ms for i in range(n_days)], dtype=np.int64)


def _synthetic_bars_df(n_days: int, *, start: str = "2019-01-01", seed: int = 11) -> pl.DataFrame:
    """Barras diárias sintéticas -- granularidade "diária" só serve pra dar
    ao walk-forward (que corta por trimestre CIVIL, não por contagem de
    barras) folds suficientes num teste rápido; `timeframe_minutes` passado
    a `compare_estimators_for_combination` é nominal, não precisa bater com
    o espaçamento real das barras sintéticas -- `estimate()` só valida
    `horizon_minutes == bars.timeframe_minutes`, nunca o espaçamento real
    de `open_time`."""
    rng = np.random.default_rng(seed)
    close = 100.0 + np.cumsum(rng.normal(0, 0.5, n_days))
    high = close + rng.uniform(0, 1, n_days)
    low = close - rng.uniform(0, 1, n_days)
    open_ = close + rng.normal(0, 0.1, n_days)
    return pl.DataFrame(
        {
            "open_time": _daily_open_time_ms(start, n_days),
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
        }
    )


# ============================================================================
# compare_estimators_for_combination -- núcleo puro
# ============================================================================


def test_compare_estimators_dado_insuficiente_retorna_none() -> None:
    bars_df = _synthetic_bars_df(200)  # ~6.5 meses, menos que os 2 anos de treino inicial
    result = vc.compare_estimators_for_combination(
        "BTCUSDT",
        "15m",
        bars_df,
        timeframe_minutes=15,
        candidate_window=20,
        initial_train_years=2,
    )
    assert result is None


def test_compare_estimators_estrutura_do_resultado() -> None:
    bars_df = _synthetic_bars_df(1460)  # ~4 anos -- treino 2 anos + folds de teste
    result = vc.compare_estimators_for_combination(
        "BTCUSDT",
        "15m",
        bars_df,
        timeframe_minutes=15,
        candidate_window=20,
        initial_train_years=2,
    )
    assert result is not None
    assert result.symbol == "BTCUSDT"
    assert result.tf == "15m"
    assert result.n_bars == 1460
    assert result.n_folds > 0
    assert result.baseline.estimator_id == "atr_wilder_w20"
    assert result.baseline.n_oos_obs > 0

    candidate_ids = {c.metrics.estimator_id for c in result.candidates}
    assert candidate_ids == {
        "parkinson_w20",
        "garman_klass_w20",
        "realized_vol_w20",
        "har_rv_d96",
        "egarch_1_1",
    }
    for c in result.candidates:
        assert 0.0 <= c.fold_win_rate <= 1.0 or np.isnan(c.fold_win_rate)
        assert isinstance(c.beats_baseline_qlike, bool)
    assert isinstance(result.any_candidate_beats_baseline, bool)


def test_compare_estimators_har_rv_produz_forecast_nao_trivial_com_dado_suficiente() -> None:
    # 1460 barras "diárias" não bastam pra janela mensal do HAR-RV fechar
    # em tf=15m (bars_per_day=96, mês=2880) -- esse teste usa mais barras
    # especificamente pra confirmar que a integração produz observações
    # reais, não só "não quebra". Correção matemática do HAR-RV em si já
    # é coberta em tests/unit/test_features_volatility_models.py.
    bars_df = _synthetic_bars_df(4000, seed=13)
    result = vc.compare_estimators_for_combination(
        "BTCUSDT",
        "15m",
        bars_df,
        timeframe_minutes=15,
        candidate_window=20,
        initial_train_years=2,
    )
    assert result is not None
    har_rv = next(c for c in result.candidates if c.metrics.estimator_id == "har_rv_d96")
    assert har_rv.metrics.n_oos_obs > 0


def test_compare_estimators_egarch_produz_forecast_nao_trivial() -> None:
    # EGARCH não precisa de janela grande pra fechar (diferente do HAR-RV
    # mensal) -- 1460 barras já bastam pra confirmar que a integração
    # funciona de ponta a ponta. Correção matemática do EGARCH em si já é
    # coberta em tests/unit/test_features_volatility_models.py.
    bars_df = _synthetic_bars_df(1460)
    result = vc.compare_estimators_for_combination(
        "BTCUSDT",
        "15m",
        bars_df,
        timeframe_minutes=15,
        candidate_window=20,
        initial_train_years=2,
    )
    assert result is not None
    egarch = next(c for c in result.candidates if c.metrics.estimator_id == "egarch_1_1")
    assert egarch.metrics.n_oos_obs > 0


def test_compare_estimators_forecast_var_e_o_quadrado_do_estimate() -> None:
    # Sanity check da convenção declarada na docstring do módulo: o
    # forecast em escala de variância é sempre >= 0 (estimate() ao
    # quadrado), nunca negativo -- QLIKE levantaria silenciosamente NaN
    # sobre forecast negativo do contrário.
    bars_df = _synthetic_bars_df(1460)
    from src.features.volatility import Bars

    bars = Bars(frame=bars_df, timeframe_minutes=15)
    forecast_var = vc._forecast_var(vc._baseline_estimator(), bars)
    valid = forecast_var[~np.isnan(forecast_var)]
    assert np.all(valid >= 0.0)


# ============================================================================
# stopping_criterion_1_from_results -- §6.5 critério de parada #1
# ============================================================================


def _fake_combination_result(*, any_beats: bool) -> vc.CombinationResult:
    metrics = vc.EstimatorMetrics(
        estimator_id="atr_wilder_w20",
        qlike_mean=0.1,
        mse_mean=0.01,
        bias=0.0,
        mz_intercept=0.0,
        mz_slope=1.0,
        mz_r_squared=0.5,
        mz_n=100,
        n_oos_obs=100,
        n_inf_qlike=0,
    )
    return vc.CombinationResult(
        symbol="BTCUSDT",
        tf="15m",
        n_bars=1000,
        n_folds=5,
        baseline=metrics,
        candidates=(),
        any_candidate_beats_baseline=any_beats,
    )


def test_stopping_criterion_1_vazio_da_false() -> None:
    assert vc.stopping_criterion_1_from_results([]) is False


def test_stopping_criterion_1_dispara_quando_nenhum_candidato_vence_em_lugar_nenhum() -> None:
    results = [_fake_combination_result(any_beats=False), _fake_combination_result(any_beats=False)]
    assert vc.stopping_criterion_1_from_results(results) is True


def test_stopping_criterion_1_nao_dispara_se_ao_menos_uma_combinacao_venceu() -> None:
    results = [_fake_combination_result(any_beats=False), _fake_combination_result(any_beats=True)]
    assert vc.stopping_criterion_1_from_results(results) is False


# ============================================================================
# run_volatility_comparison_for_symbol_tf -- IO real (integration)
# ============================================================================


def _skip_if_no_backfill() -> None:
    if not (CAPACITY_DIR / "klines_1m" / "BTCUSDT" / "2020-01-01.parquet").exists():
        pytest.skip("backfill local de klines_1m/BTCUSDT ausente -- rode o download primeiro")


@pytest.mark.integration
@pytest.mark.slow
def test_run_volatility_comparison_for_symbol_tf_btcusdt_15m_sobre_dado_real() -> None:
    _skip_if_no_backfill()
    result = vc.run_volatility_comparison_for_symbol_tf(
        "BTCUSDT", "15m", start="2020-01-01", end="2022-06-30", initial_train_years=2
    )
    assert result is not None
    assert result.n_folds >= 1
    assert not np.isnan(result.baseline.qlike_mean)
    for c in result.candidates:
        assert not np.isnan(c.metrics.qlike_mean) or c.metrics.n_oos_obs == 0
