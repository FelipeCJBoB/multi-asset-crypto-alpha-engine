"""AG-371 Passo 3 (item 1) — testes de `src.validation.hyperparam_search`.

`run_one_trial` stuba `alpha.run_all_folds`/`backtest_lite.backtest_by_path`
(não repete cobertura de treino real, já coberta em `test_models_alpha.py`/
`tests/golden/`) — cobre só a AGREGAÇÃO (pooled_sharpe, exclusão de NaN,
campos *_by_path) e o THREADING de kwargs até `run_all_folds`, que é o
código novo deste módulo. `append_trial_result_jsonl`/`read_trial_results_
jsonl` cobrem round-trip real em disco (`tmp_path`), sem mock."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.models import alpha, backtest_lite
from src.validation import hyperparam_search as hs
from src.validation import noise_floor_diagnostics


def _fake_path_result(path_id: int, sharpe: float) -> backtest_lite.PathBacktestResult:
    return backtest_lite.PathBacktestResult(
        path_id=path_id,
        n_signals=10 + path_id,
        n_filled_trades=9 + path_id,
        fill_rate=0.9,
        sharpe_naive=sharpe,
        mean_trade_ret=0.001,
        std_trade_ret=0.01,
        trades_per_year=100.0 + path_id,
    )


def _patch_training(
    monkeypatch: pytest.MonkeyPatch, sharpes: dict[int, float]
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def _fake_run_all_folds(df: Any, splits: Any, **kwargs: Any) -> list[Any]:
        calls.append(kwargs)
        return ["fake_fold_result"]

    def _fake_backtest_by_path(
        fold_results: Any, df_all: Any
    ) -> dict[int, backtest_lite.PathBacktestResult]:
        return {pid: _fake_path_result(pid, s) for pid, s in sharpes.items()}

    monkeypatch.setattr(hs.alpha, "run_all_folds", _fake_run_all_folds)
    monkeypatch.setattr(hs.backtest_lite, "backtest_by_path", _fake_backtest_by_path)
    return calls


def _hyper() -> alpha.LGBMHyperparams:
    return alpha.LGBMHyperparams.from_constants()


def test_run_one_trial_agrega_pooled_sharpe_excluindo_nan(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_training(monkeypatch, {0: -1.0, 1: 2.0, 2: float("nan"), 3: 0.0, 4: 3.0})

    result = hs.run_one_trial(
        mf=SimpleNamespace(data="fake_df"),
        splits=(),
        symbol="BTCUSDT",
        resolution_id="R1",
        variant=alpha.VARIANT_CAMADA1,
        hyper=_hyper(),
        feature_ids=("A01_log_return_1",),
        seed=42,
        trial_id="screen_0",
    )

    # media de -1.0, 2.0, 0.0, 3.0 (NaN excluido) = 1.0
    assert result.pooled_sharpe == pytest.approx(1.0)
    # NaN preservado no dict por-path, nao descartado
    assert result.sharpe_by_path["2"] != result.sharpe_by_path["2"]
    assert result.n_paths == 5
    assert result.symbol == "BTCUSDT"
    assert result.resolution_id == "R1"
    assert result.variant == alpha.VARIANT_CAMADA1
    assert result.seed == 42
    assert result.trial_id == "screen_0"


def test_run_one_trial_captura_campos_por_path(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_training(monkeypatch, {0: -0.5, 1: 0.5})

    result = hs.run_one_trial(
        mf=SimpleNamespace(data="fake_df"), splits=(), symbol="ETHUSDT", resolution_id="R2",
        variant=alpha.VARIANT_CAMADA0, hyper=_hyper(),
        feature_ids=("A01_log_return_1",), seed=7, trial_id="screen_1",
    )

    assert result.n_signals_by_path == {"0": 10, "1": 11}
    assert result.n_filled_by_path == {"0": 9, "1": 10}
    assert result.fill_rate_by_path == {"0": 0.9, "1": 0.9}
    assert result.trades_per_year_by_path == {"0": 100.0, "1": 101.0}


def test_run_one_trial_so_grava_os_9_campos_de_hiper(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_training(monkeypatch, {0: 0.0})
    result = hs.run_one_trial(
        mf=SimpleNamespace(data="fake_df"), splits=(), symbol="SOLUSDT", resolution_id="R1",
        variant=alpha.VARIANT_CAMADA1, hyper=_hyper(),
        feature_ids=("A01_log_return_1",), seed=1, trial_id="t0",
    )
    assert set(result.hyper.keys()) == set(hs._HYPER_FIELDS)
    assert result.hyper["max_depth"] == _hyper().max_depth


def test_run_one_trial_repassa_kwargs_corretos_para_run_all_folds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_training(monkeypatch, {0: 1.0})
    hyper = _hyper()
    feature_ids = ("A01_log_return_1", "B01_rsi_14")

    hs.run_one_trial(
        mf=SimpleNamespace(data="fake_df"), splits=(), symbol="XRPUSDT", resolution_id="R3",
        variant=alpha.VARIANT_CAMADA0, hyper=hyper, feature_ids=feature_ids,
        seed=99, trial_id="t1", device_type="cpu", model_id="custom_model_id",
    )

    assert len(calls) == 1
    kw = calls[0]
    assert kw["variant"] == alpha.VARIANT_CAMADA0
    assert kw["model_id"] == "custom_model_id"
    assert kw["symbol"] == "XRPUSDT"
    assert kw["resolution_id"] == "R3"
    assert kw["hyper"] is hyper
    assert kw["seed"] == 99
    assert kw["feature_ids"] == feature_ids
    assert kw["device_type"] == "cpu"
    # AG-371 (MDA diagnostic, mesma sessao) -- early_stopping_mode='three_way'
    # exige temporal_purged; default aqui precisa continuar assim.
    assert kw["calib_split_mode"] == alpha.CALIB_SPLIT_TEMPORAL_PURGED


def test_build_mf_and_splits_reexporta_o_privado_de_noise_floor_diagnostics() -> None:
    assert hs.build_mf_and_splits is noise_floor_diagnostics._build_mf_and_splits


def test_append_and_read_trial_results_jsonl_roundtrip(tmp_path: Path) -> None:
    log_path = tmp_path / "campaign" / "trials.jsonl"
    r1 = hs.TrialResult(
        symbol="BTCUSDT", resolution_id="R1", variant=alpha.VARIANT_CAMADA1, seed=1,
        trial_id="t0", hyper={"max_depth": 2.0}, pooled_sharpe=-0.5,
        sharpe_by_path={"0": -0.5}, n_signals_by_path={"0": 10},
        n_filled_by_path={"0": 9}, fill_rate_by_path={"0": 0.9},
        trades_per_year_by_path={"0": 100.0}, n_paths=1, elapsed_seconds=32.6,
    )
    r2 = hs.TrialResult(
        symbol="BTCUSDT", resolution_id="R1", variant=alpha.VARIANT_CAMADA1, seed=2,
        trial_id="t1", hyper={"max_depth": 3.0}, pooled_sharpe=0.2,
        sharpe_by_path={"0": 0.2}, n_signals_by_path={"0": 12},
        n_filled_by_path={"0": 11}, fill_rate_by_path={"0": 0.92},
        trades_per_year_by_path={"0": 105.0}, n_paths=1, elapsed_seconds=30.1,
    )

    hs.append_trial_result_jsonl(r1, log_path)
    hs.append_trial_result_jsonl(r2, log_path)

    rows = hs.read_trial_results_jsonl(log_path)
    assert len(rows) == 2
    assert rows[0]["trial_id"] == "t0"
    assert rows[0]["pooled_sharpe"] == pytest.approx(-0.5)
    assert rows[1]["trial_id"] == "t1"
    assert rows[1]["hyper"]["max_depth"] == 3.0


def test_read_trial_results_jsonl_arquivo_inexistente_retorna_vazio(tmp_path: Path) -> None:
    assert hs.read_trial_results_jsonl(tmp_path / "nao_existe.jsonl") == []
