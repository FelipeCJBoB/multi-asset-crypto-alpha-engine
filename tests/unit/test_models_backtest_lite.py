"""Testes de `src/models/backtest_lite.py` — harness de avaliação mínimo
desta rodada (Sharpe ingênuo, não corrigido por autocorrelação/DSR, ver
docstring do módulo)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl
import pytest

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


class _FakeFoldResult:
    """Duck-type mínimo pro contrato que `realize_trades` de fato usa
    (`.predictions`/`.path_id`/`.variant`) -- construir um `FoldResult`
    real exigiria `SideModelResult` completo (booster, calibrador etc.),
    irrelevante pro que `camada_diff_series` testa (AG-252)."""

    def __init__(self, predictions: pl.DataFrame, path_id: int, variant: str = "camada1") -> None:
        self.predictions = predictions
        self.path_id = path_id
        self.variant = variant


def _mk_predictions(t0: list[datetime], side_hat: list[int], fold_id: int = 0) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "t0": pl.Series(t0).cast(pl.Datetime("ms")).dt.replace_time_zone("UTC"),
            "side_hat": pl.Series(side_hat, dtype=pl.Int8),
            "fold_id": pl.Series([fold_id] * len(t0), dtype=pl.Int16),
        }
    )


def _mk_labels(t0: list[datetime], side: list[int], ret_net: list[float]) -> pl.DataFrame:
    n = len(t0)
    return pl.DataFrame(
        {
            "t0": pl.Series(t0).cast(pl.Datetime("ms")).dt.replace_time_zone("UTC"),
            "side": pl.Series(side, dtype=pl.Int8),
            "barrier_hit": pl.Series(["TP"] * n),
            "ret_net": pl.Series(ret_net, dtype=pl.Float64),
            "sample_weight": pl.Series([1.0] * n),
            "ret_gross": pl.Series(ret_net, dtype=pl.Float64),
            "cost_entry_bps": pl.Series([0.0] * n),
            "cost_exit_bps": pl.Series([0.0] * n),
            "funding_bps": pl.Series([0.0] * n),
        }
    )


def test_camada_diff_series_zero_filling_e_has_signal_mask() -> None:
    """4 barras. `df_all` tem DUAS linhas por barra (side=1/side=-1, mesmo
    contrato de `alpha._unique_test_bars`) -- `bar_idx` cobre TODAS elas
    (como `path_bar_indices` real faria via `test_idx`), então o teste
    também cobre a deduplicação por `side==1` (achado AG-252).
    C1 sinaliza long em t0[0] (ret=0.01) e t0[2] (ret=0.02); C0 sinaliza
    short em t0[1] (ret=-0.005) e long em t0[2] (MESMO ret=0.02 -- diff=0
    ali, mas has_signal deve ser True pois as duas sinalizaram); nenhuma
    sinaliza em t0[3]."""
    t0 = [datetime(2024, 1, 1, h, tzinfo=UTC) for h in range(4)]

    labels = pl.concat(
        [
            _mk_labels([t0[0]], [1], [0.01]),
            _mk_labels([t0[0]], [-1], [-0.99]),  # não referenciado por nenhum side_hat
            _mk_labels([t0[1]], [1], [0.99]),  # não referenciado
            _mk_labels([t0[1]], [-1], [-0.005]),
            _mk_labels([t0[2]], [1], [0.02]),
            _mk_labels([t0[2]], [-1], [-0.99]),  # não referenciado
            _mk_labels([t0[3]], [1], [0.99]),  # não referenciado -- só existe pra t0[3] aparecer em `bars`
            _mk_labels([t0[3]], [-1], [-0.99]),  # não referenciado
        ]
    )
    bar_idx = np.arange(labels.height)  # cobre as 8 linhas (2 por barra), como test_idx real faria

    c1_preds = _mk_predictions([t0[0], t0[1], t0[2], t0[3]], [1, 0, 1, 0])
    c0_preds = _mk_predictions([t0[0], t0[1], t0[2], t0[3]], [0, -1, 1, 0])
    c1_folds = [_FakeFoldResult(c1_preds, path_id=0, variant="camada1")]
    c0_folds = [_FakeFoldResult(c0_preds, path_id=0, variant="camada0")]

    diff, has_signal = backtest_lite.camada_diff_series(c1_folds, c0_folds, labels, path_id=0, bar_idx=bar_idx)

    assert diff.shape == (4,)  # deduplicado -- 4 barras, não 8 linhas
    assert has_signal.tolist() == [True, True, True, False]
    assert diff[0] == pytest.approx(0.01)  # só C1 sinalizou
    assert diff[1] == pytest.approx(0.005)  # só C0 sinalizou (short ret -0.005 -> diff = 0 - (-0.005))
    assert diff[2] == pytest.approx(0.0)  # as duas sinalizaram, MESMO ret_net -> diff=0, mas has_signal=True
    assert diff[3] == pytest.approx(0.0)  # nenhuma sinalizou


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


# ============================================================================
# percentile_rank -- ADR-005 §13.13, item 5 de §13.17
# ============================================================================


def test_percentile_rank_headline_supera_todos_os_nulos() -> None:
    nulls = np.array([0.1, 0.2, 0.15, -0.3])  # noqa: magic-number
    assert backtest_lite.percentile_rank(1.0, nulls) == pytest.approx(1.0)


def test_percentile_rank_headline_nao_supera_nenhum() -> None:
    nulls = np.array([0.1, 0.2, 0.15, 0.3])  # noqa: magic-number
    assert backtest_lite.percentile_rank(-1.0, nulls) == pytest.approx(0.0)


def test_percentile_rank_headline_no_meio_da_distribuicao() -> None:
    nulls = np.array([0.0, 1.0, 2.0, 3.0])  # noqa: magic-number -- 1.5 supera 0.0 e 1.0 -> 2/4
    assert backtest_lite.percentile_rank(1.5, nulls) == pytest.approx(0.5)


def test_percentile_rank_empate_conta_a_favor_do_nulo() -> None:
    """`<=`, não `<` -- leitura conservadora: um nulo empatado com o
    headline conta como "o nulo bateu", não infla o percentual do real."""
    nulls = np.array([1.0, 1.0, 0.5])  # noqa: magic-number
    assert backtest_lite.percentile_rank(1.0, nulls) == pytest.approx(1.0)


def test_percentile_rank_descarta_nan_da_distribuicao_nula() -> None:
    nulls = np.array([0.1, float("nan"), 0.3, float("nan")])  # noqa: magic-number
    # só 0.1 e 0.3 contam -- headline=0.2 supera só 0.1 -> 1/2
    assert backtest_lite.percentile_rank(0.2, nulls) == pytest.approx(0.5)  # noqa: magic-number


def test_percentile_rank_todos_os_nulos_sao_nan_devolve_nan() -> None:
    nulls = np.array([float("nan"), float("nan")])
    assert np.isnan(backtest_lite.percentile_rank(0.5, nulls))  # noqa: magic-number


def test_percentile_rank_headline_nan_devolve_nan() -> None:
    nulls = np.array([0.1, 0.2, 0.3])  # noqa: magic-number
    assert np.isnan(backtest_lite.percentile_rank(float("nan"), nulls))
