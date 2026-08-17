"""Testes de `src/analysis/volatility_comparison.py` -- extensão PÓS-M1
(Garman-Klass baseline, Parkinson/Rogers-Satchell/Yang-Zhang candidatos;
ver docstring do módulo para o porquê do M1 original de PRD_V4_1.md §3.2
não ser mais o que este harness roda). `compare_estimators_for_combination`
é o núcleo puro (bars sintéticas, sem IO); `run_volatility_comparison_for_
symbol_tf` é o único ponto que toca disco real (`integration`, pula se o
backfill local não existir)."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import polars as pl
import pytest

from src.analysis import volatility_comparison as vc
from src.data._paths import CAPACITY_DIR
from src.validation import volatility_walkforward as vwf


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
    de `open_time`.

    `close_time = open_time + 1 dia - 1ms` -- estritamente ascendente e
    nunca colide entre barras (`_causal_window_mean`/`_acd_durations`
    exigem isso), necessário desde que `compare_estimators_for_combination_
    dollar_bar` passou a religar HAR-RV/EGARCH-acoplado (AG-036,
    2026-08-17), que consomem `close_time` real."""
    rng = np.random.default_rng(seed)
    close = 100.0 + np.cumsum(rng.normal(0, 0.5, n_days))
    high = close + rng.uniform(0, 1, n_days)
    low = close - rng.uniform(0, 1, n_days)
    open_ = close + rng.normal(0, 0.1, n_days)
    open_time = _daily_open_time_ms(start, n_days)
    day_ms = 86_400_000
    return pl.DataFrame(
        {
            "open_time": open_time,
            "close_time": open_time + day_ms - 1,
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
    assert result.baseline.estimator_id == "garman_klass_w20"
    assert result.baseline.n_oos_obs > 0

    candidate_ids = {c.metrics.estimator_id for c in result.candidates}
    assert candidate_ids == {
        "parkinson_w20",
        "rogers_satchell_w20",
        "yang_zhang_w20",
    }
    for c in result.candidates:
        assert 0.0 <= c.fold_win_rate <= 1.0 or np.isnan(c.fold_win_rate)
        assert isinstance(c.beats_baseline_qlike, bool)
        # Todos os 4 candidatos/baseline atuais são fórmula fechada (sem
        # fit por fold) -- diferente do HAR-RV/EGARCH que existiam aqui
        # antes, nenhum motivo estrutural pra faltar observação OOS com
        # 1460 barras/2 anos de treino inicial.
        assert c.metrics.n_oos_obs > 0
    assert isinstance(result.any_candidate_beats_baseline, bool)


def test_compare_estimators_forecast_var_e_o_quadrado_do_estimate() -> None:
    # Sanity check da convenção declarada na docstring do módulo: o
    # forecast em escala de variância é sempre >= 0 (estimate() ao
    # quadrado), nunca negativo -- QLIKE levantaria silenciosamente NaN
    # sobre forecast negativo do contrário.
    bars_df = _synthetic_bars_df(1460)
    from src.features.volatility import Bars

    bars = Bars(frame=bars_df, timeframe_minutes=15)
    forecast_var = vc._forecast_var(
        vc._baseline_estimator(window=20), bars, horizon_minutes=15
    )
    valid = forecast_var[~np.isnan(forecast_var)]
    assert np.all(valid >= 0.0)


# ============================================================================
# compare_estimators_for_combination_dollar_bar -- núcleo puro, grade
# dollar-bar (AG-036). Mesmas fixtures sintéticas de open_time/close diário
# -- Bars(resolution_id=...) não exige close_time (só os 5 estimadores de
# fórmula fechada consomem high/low/close/open de bars.frame diretamente).
# ============================================================================


def test_compare_estimators_dollar_bar_dado_insuficiente_retorna_none() -> None:
    bars_df = _synthetic_bars_df(200)
    result = vc.compare_estimators_for_combination_dollar_bar(
        "BTCUSDT",
        "R1",
        bars_df,
        candidate_window=20,
        initial_train_years=2,
    )
    assert result is None


def test_compare_estimators_dollar_bar_estrutura_do_resultado_sem_yang_zhang() -> None:
    bars_df = _synthetic_bars_df(1460)
    result = vc.compare_estimators_for_combination_dollar_bar(
        "BTCUSDT",
        "R1",
        bars_df,
        candidate_window=20,
        initial_train_years=2,
    )
    assert result is not None
    assert result.symbol == "BTCUSDT"
    assert result.tf == "R1"  # resolution_id, não relógio -- mesma ontologia AG-042
    assert result.n_bars == 1460
    assert result.n_folds > 0
    assert result.baseline.estimator_id == "garman_klass_w20"
    assert result.baseline.n_oos_obs > 0

    candidate_ids = {c.metrics.estimator_id for c in result.candidates}
    # YangZhang FORA -- ainda bloqueado sob dollar bar (AG-043, componente
    # overnight). Os outros 4 sobreviventes de fórmula fechada + HAR-RV +
    # EGARCH-acoplado (fold-aware, religados AG-036 2026-08-17) -- 6 no total.
    assert candidate_ids == {
        "realized_vol_w20",
        "atr_wilder_w20",
        "parkinson_w20",
        "rogers_satchell_w20",
        "har_rv",
        "egarch_coupled",
    }
    for c in result.candidates:
        assert 0.0 <= c.fold_win_rate <= 1.0 or np.isnan(c.fold_win_rate)
        assert isinstance(c.beats_baseline_qlike, bool)
        assert c.metrics.n_oos_obs > 0
    assert isinstance(result.any_candidate_beats_baseline, bool)


def test_candidate_estimators_dollar_bar_nao_inclui_yang_zhang() -> None:
    ids = {e.estimator_id for e in vc._candidate_estimators_dollar_bar(window=20)}
    assert "yang_zhang_w20" not in ids
    assert ids == {"realized_vol_w20", "atr_wilder_w20", "parkinson_w20", "rogers_satchell_w20"}


# ============================================================================
# _har_rv_forecast_var_dollar_bar / _egarch_coupled_forecast_var_dollar_bar
# -- glue code fold-aware religado ao harness dollar-bar (AG-036,
# 2026-08-17). fit_har_rv/fit_egarch_coupled/fit_acd/predict_acd já têm
# cobertura própria de causalidade em test_features_volatility_models.py/
# test_features_acd.py -- o que estes testes cobrem é a FIAÇÃO desta
# camada (train_end_idx certo por fold, sem re-testar a matemática interna).
# ============================================================================


def _splits_for(
    bars_df: pl.DataFrame, *, initial_train_years: int = 2
) -> tuple[vwf.WalkForwardSplit, ...]:
    open_time_ms = bars_df["open_time"].cast(pl.Int64).to_numpy()
    return vwf.generate_anchored_walk_forward_splits(
        open_time_ms, initial_train_years=initial_train_years
    )


_TEST_SYMBOL = "BTCUSDT"
_TEST_RESOLUTION_ID = "R1"


def test_har_rv_forecast_var_dollar_bar_forma_e_nan_fora_dos_folds() -> None:
    bars_df = _synthetic_bars_df(1460)
    splits = _splits_for(bars_df)
    close = bars_df["close"].cast(pl.Float64).to_numpy()
    close_time = bars_df["close_time"].cast(pl.Int64).to_numpy()
    realized_var = vwf.next_bar_realized_variance(close)

    out = vc._har_rv_forecast_var_dollar_bar(
        realized_var, close_time, splits, symbol=_TEST_SYMBOL, resolution_id=_TEST_RESOLUTION_ID
    )

    assert out.shape == (1460,)
    # antes do 1º fold de teste, nunca preenchido (fora da união dos folds)
    assert np.all(np.isnan(out[: splits[0].test_start_idx]))
    # dentro da região de teste coberta pelos folds, ao menos alguns
    # valores finitos (treino inicial de 2 anos >> _MIN_TRAIN_OBS=10)
    oos_start, oos_end = splits[0].test_start_idx, splits[-1].test_end_idx
    assert np.any(np.isfinite(out[oos_start:oos_end]))


def test_egarch_coupled_forecast_var_dollar_bar_forma_e_nan_fora_dos_folds() -> None:
    bars_df = _synthetic_bars_df(1460)
    splits = _splits_for(bars_df)
    close = bars_df["close"].cast(pl.Float64).to_numpy()
    close_time = bars_df["close_time"].cast(pl.Int64).to_numpy()

    out = vc._egarch_coupled_forecast_var_dollar_bar(
        close, close_time, splits, symbol=_TEST_SYMBOL, resolution_id=_TEST_RESOLUTION_ID
    )

    assert out.shape == (1460,)
    assert np.all(np.isnan(out[: splits[0].test_start_idx]))
    oos_start, oos_end = splits[0].test_start_idx, splits[-1].test_end_idx
    assert np.any(np.isfinite(out[oos_start:oos_end]))
    # forecast de variância nunca é negativo -- mesma disciplina de
    # predict_egarch_coupled (NaN explícito em vez de valor <=0)
    finite = out[np.isfinite(out)]
    assert np.all(finite > 0.0)


def test_har_rv_forecast_var_dollar_bar_fold_usa_so_o_proprio_treino() -> None:
    """Regressão de fiação: perturbar `realized_var` bem DEPOIS da região
    de teste do 1º fold não pode mudar o forecast do 1º fold -- se o glue
    code passasse o `train_end_idx` errado (ex. sempre o do último fold),
    isso vazaria e o teste pegaria."""
    bars_df = _synthetic_bars_df(1460)
    splits = _splits_for(bars_df)
    close = bars_df["close"].cast(pl.Float64).to_numpy()
    close_time = bars_df["close_time"].cast(pl.Int64).to_numpy()
    realized_var = vwf.next_bar_realized_variance(close)

    baseline = vc._har_rv_forecast_var_dollar_bar(
        realized_var, close_time, splits, symbol=_TEST_SYMBOL, resolution_id=_TEST_RESOLUTION_ID
    )

    perturbed = realized_var.copy()
    far_future_start = splits[-1].test_start_idx
    perturbed[far_future_start:] *= 3.0

    perturbed_out = vc._har_rv_forecast_var_dollar_bar(
        perturbed, close_time, splits, symbol=_TEST_SYMBOL, resolution_id=_TEST_RESOLUTION_ID
    )

    first_fold = splits[0]
    np.testing.assert_array_equal(
        baseline[first_fold.test_start_idx : first_fold.test_end_idx],
        perturbed_out[first_fold.test_start_idx : first_fold.test_end_idx],
    )


def test_egarch_coupled_forecast_var_dollar_bar_fold_usa_so_o_proprio_treino() -> None:
    bars_df = _synthetic_bars_df(1460)
    splits = _splits_for(bars_df)
    close = bars_df["close"].cast(pl.Float64).to_numpy()
    close_time = bars_df["close_time"].cast(pl.Int64).to_numpy()

    baseline = vc._egarch_coupled_forecast_var_dollar_bar(
        close, close_time, splits, symbol=_TEST_SYMBOL, resolution_id=_TEST_RESOLUTION_ID
    )

    perturbed_close = close.copy()
    far_future_start = splits[-1].test_start_idx
    perturbed_close[far_future_start:] *= 1.5

    perturbed_out = vc._egarch_coupled_forecast_var_dollar_bar(
        perturbed_close,
        close_time,
        splits,
        symbol=_TEST_SYMBOL,
        resolution_id=_TEST_RESOLUTION_ID,
    )

    first_fold = splits[0]
    np.testing.assert_array_equal(
        baseline[first_fold.test_start_idx : first_fold.test_end_idx],
        perturbed_out[first_fold.test_start_idx : first_fold.test_end_idx],
    )


def test_har_rv_forecast_var_dollar_bar_fold_adjacente_nao_vaza() -> None:
    """Achado LOW de revisão independente (`project_assurance`, AG-068):
    os testes acima só provam ausência de vazamento 1º-vs-último fold --
    um bug tipo "fold i usa splits[i+1].train_end_idx por engano" (leak
    de exatamente 1 fold à frente) não seria pego por eles, porque a
    perturbação nunca alcançaria o treino do 2º fold. Este teste perturba
    a partir do INÍCIO DA REGIÃO DE TESTE DO 2º fold (splits[1]) -- ainda
    fora do treino do 1º fold -- e confirma que o forecast do 1º fold
    continua intocado."""
    bars_df = _synthetic_bars_df(1460)
    splits = _splits_for(bars_df)
    assert len(splits) >= 2, "fixture precisa de >=2 folds pra este teste fazer sentido"
    close = bars_df["close"].cast(pl.Float64).to_numpy()
    close_time = bars_df["close_time"].cast(pl.Int64).to_numpy()
    realized_var = vwf.next_bar_realized_variance(close)

    baseline = vc._har_rv_forecast_var_dollar_bar(
        realized_var, close_time, splits, symbol=_TEST_SYMBOL, resolution_id=_TEST_RESOLUTION_ID
    )

    perturbed = realized_var.copy()
    second_fold_test_start = splits[1].test_start_idx
    perturbed[second_fold_test_start:] *= 3.0

    perturbed_out = vc._har_rv_forecast_var_dollar_bar(
        perturbed, close_time, splits, symbol=_TEST_SYMBOL, resolution_id=_TEST_RESOLUTION_ID
    )

    first_fold = splits[0]
    np.testing.assert_array_equal(
        baseline[first_fold.test_start_idx : first_fold.test_end_idx],
        perturbed_out[first_fold.test_start_idx : first_fold.test_end_idx],
    )


# ============================================================================
# stopping_criterion_1_from_results -- mesmo mecanismo do §6.5 critério de
# parada #1 do PRD, reaplicado aqui contra o baseline atual (GK), não o
# gate formal em si (já resolvido na rodada original de M1 contra
# ATRWilder -- ver docstring da função)
# ============================================================================


def _fake_combination_result(*, any_beats: bool) -> vc.CombinationResult:
    metrics = vc.EstimatorMetrics(
        estimator_id="garman_klass_w20",
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
