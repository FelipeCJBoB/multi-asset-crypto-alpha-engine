"""Testes de `src.models.walk_forward.run_walk_forward_for_combo` +
`min_test_bars_for_non_degenerate_fold`/`_aggregate_stats` — ADR-008
Fase 4. `alpha.run_fold` é MOCKADO (mesmo padrão de `test_models_
alpha_hyperparams_wiring.py`/`test_models_backtest_lite.py::
_FakeFoldResult`): construir um `SideModelResult` real por fold exigiria
booster/calibrador completos por retreino de verdade, caro e irrelevante
pro que este módulo testa (orquestração: geração de folds, marcação de
degenerado, agregação) — a geração REAL de splits
(`generate_anchored_walk_forward_splits`/`walk_forward_split_to_cpcv_
split`) e o backtest/score_quality REAIS continuam rodando sobre dado
sintético."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import polars as pl
import pytest

from src.models import alpha
from src.models import walk_forward as wf
from src.validation.cpcv import CPCVSplit

_T0_DTYPE = pl.Datetime(time_unit="ms", time_zone="UTC")
_BASE = datetime(2020, 1, 1, tzinfo=UTC)


# ============================================================================
# min_test_bars_for_non_degenerate_fold / _aggregate_stats -- núcleo puro
# ============================================================================


def test_min_test_bars_formula_derivada_do_target_signal_rate() -> None:
    assert wf.min_test_bars_for_non_degenerate_fold(0.02) == 500  # noqa: magic-number -- ceil(10/0.02)
    assert wf.min_test_bars_for_non_degenerate_fold(0.5) == 20  # noqa: magic-number -- ceil(10/0.5)


def test_aggregate_stats_conferido_a_mao() -> None:
    out = wf._aggregate_stats([1.0, 2.0, 3.0])  # noqa: magic-number
    assert out["mean"] == pytest.approx(2.0)  # noqa: magic-number
    assert out["median"] == pytest.approx(2.0)  # noqa: magic-number
    assert out["std"] == pytest.approx(1.0)  # noqa: magic-number
    assert out["min"] == pytest.approx(1.0)  # noqa: magic-number
    assert out["max"] == pytest.approx(3.0)  # noqa: magic-number


def test_aggregate_stats_nan_descartado_antes_de_agregar() -> None:
    com_nan = wf._aggregate_stats([1.0, float("nan"), 3.0])  # noqa: magic-number
    sem_nan = wf._aggregate_stats([1.0, 3.0])  # noqa: magic-number
    assert com_nan == sem_nan


def test_aggregate_stats_um_ponto_so_std_nan() -> None:
    out = wf._aggregate_stats([5.0])  # noqa: magic-number
    assert out["mean"] == pytest.approx(5.0)  # noqa: magic-number
    assert np.isnan(out["std"])


def test_aggregate_stats_vazio_tudo_nan() -> None:
    out = wf._aggregate_stats([])
    assert out["n"] == 0.0
    assert np.isnan(out["mean"])


# ============================================================================
# run_walk_forward_for_combo -- orquestração real, run_fold mockado
# ============================================================================


def _synthetic_mf_data(n_days: int = 1095, seed: int = 0) -> pl.DataFrame:  # noqa: magic-number -- 3 anos
    """3 anos de barras diárias, 2 linhas/barra (`side=1`/`side=-1`) --
    ORDEM por bloco de lado (side=1 inteiro, depois side=-1 inteiro),
    mesma não-monotonicidade real documentada em `walk_forward.py`.
    `t1 = t0 + 1h` (horizonte curto -- nunca cruza fronteira de
    trimestre, purge não entra no caminho deste teste, já coberto à
    parte em `test_models_walk_forward.py`)."""
    rng = np.random.default_rng(seed)
    dates = [_BASE + timedelta(days=i) for i in range(n_days)]
    t0 = pl.Series(dates, dtype=_T0_DTYPE)
    t1 = pl.Series([d + timedelta(hours=1) for d in dates], dtype=_T0_DTYPE)
    ret_net = rng.normal(loc=0.001, scale=0.01, size=n_days)  # noqa: magic-number
    zeros = pl.Series(np.zeros(n_days), dtype=pl.Float64)
    ones = pl.Series(np.ones(n_days), dtype=pl.Float64)
    blocks = []
    for side, ret in ((1, ret_net), (-1, -ret_net)):
        blocks.append(
            pl.DataFrame(
                {
                    "t0": t0,
                    "t1": t1,
                    "side": pl.Series([side] * n_days, dtype=pl.Int8),
                    "barrier_hit": pl.Series(["TP"] * n_days, dtype=pl.Utf8),
                    "ret_net": pl.Series(ret, dtype=pl.Float64),
                    "sample_weight": ones,
                    "ret_gross": pl.Series(ret, dtype=pl.Float64),
                    "cost_entry_bps": zeros,
                    "cost_exit_bps": zeros,
                    "funding_bps": zeros,
                }
            )
        )
    return pl.concat(blocks, how="vertical")


class _FakeFoldResult:
    """Duck-type mínimo pro contrato que `run_walk_forward_for_combo`/
    `backtest_lite.backtest_by_path` de fato usam (`.predictions`/
    `.path_id`/`.variant`/`.n_test_bars`) -- mesmo padrão de
    `_FakeFoldResult` em `test_models_backtest_lite.py`."""

    def __init__(
        self, predictions: pl.DataFrame, *, path_id: int, variant: str, n_test_bars: int
    ) -> None:
        self.predictions = predictions
        self.path_id = path_id
        self.variant = variant
        self.n_test_bars = n_test_bars


def _make_fake_run_fold(degenerate_fold_id: int | None = None):
    def _fake_run_fold(
        mf_data_arg: pl.DataFrame,
        split: CPCVSplit,
        *,
        variant: str,
        model_id: str,
        seed: int,
        symbol: str,
        resolution_id: str | None = None,
        **_kwargs: Any,
    ) -> _FakeFoldResult:
        test_bars = (
            mf_data_arg[split.test_idx]
            .filter(pl.col("side") == 1)
            .unique(subset=["t0"], keep="first")
            .sort("t0")
        )
        if degenerate_fold_id is not None and split.split_id == degenerate_fold_id:
            test_bars = test_bars.head(1)
        n = test_bars.height
        predictions = pl.DataFrame(
            {
                "t0": test_bars["t0"],
                "side_hat": pl.Series([1] * n, dtype=pl.Int8),
                "is_oof": pl.Series([True] * n, dtype=pl.Boolean),
                "fold_id": pl.Series([split.split_id] * n, dtype=pl.Int16),
                "confidence": pl.Series(np.linspace(0.5, 0.9, n) if n else [], dtype=pl.Float64),  # noqa: magic-number
            }
        )
        return _FakeFoldResult(predictions, path_id=split.path_id, variant=variant, n_test_bars=n)

    return _fake_run_fold


def _base_kwargs(target_signal_rate: float = 0.5) -> dict[str, Any]:  # noqa: magic-number
    return {
        "symbol": "BTCUSDT",
        "resolution_id": "R2",
        "variant": alpha.VARIANT_CAMADA1,
        "hyper": alpha.LGBMHyperparams.from_constants(),
        "seed": 1,
        "target_signal_rate": target_signal_rate,
        "initial_train_years": 2,  # noqa: magic-number -- 3 anos de dado, deixa 1 ano de teste
    }


def test_run_walk_forward_gera_1_fold_por_wf_split(monkeypatch: pytest.MonkeyPatch) -> None:
    mf_data = _synthetic_mf_data()
    monkeypatch.setattr(alpha, "run_fold", _make_fake_run_fold())

    result = wf.run_walk_forward_for_combo(mf_data, **_base_kwargs())

    unique_t0_ms = np.unique(mf_data["t0"].dt.epoch(time_unit="ms").to_numpy().astype(np.int64))
    from src.validation.volatility_walkforward import generate_anchored_walk_forward_splits

    expected_splits = generate_anchored_walk_forward_splits(unique_t0_ms, initial_train_years=2)
    assert result.n_folds_total == len(expected_splits)
    assert len(result.fold_results) == len(expected_splits)
    assert result.n_folds_total > 1  # noqa: magic-number -- teste sem sentido com 1 fold só


def test_run_walk_forward_marca_fold_degenerado_e_exclui_do_agregado(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mf_data = _synthetic_mf_data()
    monkeypatch.setattr(alpha, "run_fold", _make_fake_run_fold(degenerate_fold_id=0))

    # target_signal_rate alto -> min_test_bars baixo (20) -- fold 0 forçado
    # pra 1 barra de teste cai abaixo, os outros (~1 trimestre = ~90
    # barras) ficam acima.
    result = wf.run_walk_forward_for_combo(mf_data, **_base_kwargs(target_signal_rate=0.5))

    fold0 = next(fm for fm in result.fold_results if fm.fold_id == 0)
    assert fold0.degenerado is True
    assert fold0.n_test_bars == 1
    assert result.n_folds_degenerados == 1
    assert result.n_folds_usados == result.n_folds_total - 1
    # o fold degenerado continua PRESENTE no artefato (auditável), só não
    # entra no agregado -- nunca removido silenciosamente.
    assert len(result.fold_results) == result.n_folds_total


def test_run_walk_forward_zero_folds_levanta_valueerror(monkeypatch: pytest.MonkeyPatch) -> None:
    """Série curta demais pra `initial_train_years` -- 0 folds gerados,
    falha alta em vez de devolver um resultado vazio silencioso."""
    mf_data = _synthetic_mf_data(n_days=180)  # noqa: magic-number -- ~6 meses, < 2 anos
    monkeypatch.setattr(alpha, "run_fold", _make_fake_run_fold())

    with pytest.raises(ValueError, match="0 folds gerados"):
        wf.run_walk_forward_for_combo(mf_data, **_base_kwargs())


def test_run_walk_forward_schema_do_agregado_bate_com_adr_008(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mf_data = _synthetic_mf_data()
    monkeypatch.setattr(alpha, "run_fold", _make_fake_run_fold())

    result = wf.run_walk_forward_for_combo(mf_data, **_base_kwargs())

    assert set(result.aggregate.keys()) == {"mean", "median", "std", "min", "max"}
    for stat_dict in result.aggregate.values():
        assert set(stat_dict.keys()) == {"sharpe", "edge_bps", "win_rate"}
