"""Testes de `src.models.hyperparams_optuna` -- busca real de
hiperparâmetro via Optuna (`AG-371`, 2026-08-29), primeira vez que
`optuna` é exercitado de verdade neste repo (dependência declarada desde
sempre, nunca importada até este módulo).

Escopo: `build_search_space`/`compute_search_config_hash` (funções puras,
sem Optuna nem I/O), `_objective` (via `optuna.Study` real com `alpha.
run_all_folds`/`backtest_lite.backtest_by_path` monkeypatchados -- nenhum
treino de verdade), e `write_search_artifact` (round-trip real em disco
via `tmp_path`, mesmo padrão de `src.io.artifact` já usado no repo)."""

from __future__ import annotations

from typing import Any

import optuna
import polars as pl
import pytest

from src.io import artifact as io_artifact
from src.models import alpha, backtest_lite
from src.models import dataset as ds
from src.models import hyperparams_optuna as mod
from src.models._constants import load_constant_entry as _real_load_constant_entry

optuna.logging.set_verbosity(optuna.logging.WARNING)


# --- build_search_space --------------------------------------------------


def test_max_depth_e_seletores_de_modo_nunca_elegiveis() -> None:
    """Estrutural, não depende de mock: estes campos NUNCA entram na
    busca, mesmo que a constante correspondente algum dia ganhe
    `sweep_range` por engano -- `max_depth` é redundante com `num_leaves`
    sob crescimento leaf-wise; os outros 3 são seletor de modo de código
    já promovido a default de produção (decisão do Manager, 2026-08-27)."""
    assert "max_depth" not in mod._FIELD_KIND
    assert "regularization_basis" not in mod._FIELD_KIND
    assert "early_stopping_mode" not in mod._FIELD_KIND
    assert "ic_magnitude_floor_k" not in mod._FIELD_KIND


def test_build_search_space_inclui_so_class_b_com_sweep_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    table: dict[str, dict[str, Any]] = {
        "alpha_lgbm_num_leaves": {"class": "B", "sweep_range": [4, 64]},
        "alpha_lgbm_subsample": {"class": "C", "sweep_range": [0.5, 1.0]},  # classe errada
        "alpha_lgbm_lambda_l2": {"class": "B"},  # sem sweep_range
    }

    def fake_entry(name: str) -> dict[str, Any]:
        if name not in table:
            raise KeyError(name)
        return table[name]

    monkeypatch.setattr(mod, "load_constant_entry", fake_entry)

    space = mod.build_search_space()

    assert set(space) == {"num_leaves"}
    assert space["num_leaves"].kind == "int"
    assert space["num_leaves"].low == 4.0
    assert space["num_leaves"].high == 64.0


def test_build_search_space_log_scale_acima_do_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    table: dict[str, dict[str, Any]] = {
        "alpha_lgbm_min_sum_hessian_in_leaf": {"class": "B", "sweep_range": [0.001, 5.0]},
        "alpha_lgbm_num_leaves": {"class": "B", "sweep_range": [4, 8]},
    }

    def fake_entry(name: str) -> dict[str, Any]:
        if name not in table:
            raise KeyError(name)
        return table[name]

    monkeypatch.setattr(mod, "load_constant_entry", fake_entry)

    space = mod.build_search_space()

    assert space["min_sum_hessian_in_leaf"].log is True  # razão ~5000x
    assert space["num_leaves"].log is False  # razão 2x


# --- compute_search_config_hash ------------------------------------------


def test_compute_search_config_hash_independente_de_ordem_feature_ids() -> None:
    h1 = mod.compute_search_config_hash(
        ("A01", "A02", "A03"), variant="camada1", n_trials=30, sampler_name="tpe", sampler_seed=1
    )
    h2 = mod.compute_search_config_hash(
        ("A03", "A01", "A02"), variant="camada1", n_trials=30, sampler_name="tpe", sampler_seed=1
    )
    assert h1 == h2


def test_compute_search_config_hash_muda_com_variant() -> None:
    h1 = mod.compute_search_config_hash(
        ("A01",), variant="camada1", n_trials=30, sampler_name="tpe", sampler_seed=1
    )
    h2 = mod.compute_search_config_hash(
        ("A01",), variant="camada0", n_trials=30, sampler_name="tpe", sampler_seed=1
    )
    assert h1 != h2


def test_compute_search_config_hash_muda_com_n_trials_e_seed() -> None:
    base = mod.compute_search_config_hash(
        ("A01",), variant="camada1", n_trials=30, sampler_name="tpe", sampler_seed=1
    )
    outro_n_trials = mod.compute_search_config_hash(
        ("A01",), variant="camada1", n_trials=50, sampler_name="tpe", sampler_seed=1
    )
    outro_seed = mod.compute_search_config_hash(
        ("A01",), variant="camada1", n_trials=30, sampler_name="tpe", sampler_seed=2
    )
    assert base != outro_n_trials
    assert base != outro_seed


def test_compute_search_config_hash_muda_se_sweep_range_mudar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Staleness fechada pelo MESMO mecanismo que já protege `feature_ids`
    -- editar um `sweep_range` em `constants.yaml` sem bumpar
    `_SEARCH_SPACE_VERSION` ainda muda o hash sozinho, porque o range entra
    no payload por VALOR."""
    before = mod.compute_search_config_hash(
        ("A01",), variant="camada1", n_trials=30, sampler_name="tpe", sampler_seed=1
    )

    def patched(name: str) -> dict[str, Any]:
        entry = dict(_real_load_constant_entry(name))
        if name == "alpha_lgbm_num_leaves":
            entry["sweep_range"] = [4, 999]
        return entry

    monkeypatch.setattr(mod, "load_constant_entry", patched)

    after = mod.compute_search_config_hash(
        ("A01",), variant="camada1", n_trials=30, sampler_name="tpe", sampler_seed=1
    )
    assert before != after


# --- _objective ------------------------------------------------------------

_FAKE_MF = ds.ModelingFrame(data=pl.DataFrame(), t1_feature_ids=(), regime_labels_present=())
_FAKE_PATH_RESULT = backtest_lite.PathBacktestResult(
    path_id=0,
    n_signals=10,
    n_filled_trades=8,
    fill_rate=0.8,
    sharpe_naive=1.0,
    mean_trade_ret=0.01,
    std_trade_ret=0.02,
    trades_per_year=100.0,
)
_SMALL_SEARCH_SPACE = {"num_leaves": mod._SearchDim(kind="int", low=4.0, high=8.0, log=False)}


def _run_objective_once(
    monkeypatch: pytest.MonkeyPatch, *, seed: int = 7
) -> tuple[dict[str, Any], optuna.Study]:
    captured: dict[str, Any] = {}

    def fake_run_all_folds(df: pl.DataFrame, splits: tuple[Any, ...], **kwargs: Any) -> list[Any]:
        captured.update(kwargs)
        return []

    def fake_backtest_by_path(folds: list[Any], df: pl.DataFrame) -> dict[int, Any]:
        return {0: _FAKE_PATH_RESULT}

    monkeypatch.setattr(alpha, "run_all_folds", fake_run_all_folds)
    monkeypatch.setattr(backtest_lite, "backtest_by_path", fake_backtest_by_path)

    study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=1))
    base_hyper = alpha.LGBMHyperparams.from_constants()

    def objective(trial: optuna.Trial) -> float:
        return mod._objective(
            trial,
            mf=_FAKE_MF,
            splits=(),
            symbol="BTCUSDT",
            resolution_id="R1",
            variant=alpha.VARIANT_CAMADA1,
            feature_ids_effective=("A01",),
            base_hyper=base_hyper,
            seed=seed,
            device_type="cpu",
            search_space=_SMALL_SEARCH_SPACE,
            monotone_screen_cache={},
        )

    study.optimize(objective, n_trials=1)
    return captured, study


def test_objective_passa_politicas_de_producao_explicitas(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regressão direta contra herdar os bare defaults LEGADOS de
    `alpha.run_all_folds` (pré-`AG-272`) -- a busca precisa otimizar sob o
    MESMO regime que a produção de fato usa."""
    captured, _study = _run_objective_once(monkeypatch)

    assert captured["tau_policy"] == alpha.TAU_POLICY_LEGACY_PER_SIDE
    assert captured["calib_split_mode"] == alpha.CALIB_SPLIT_TEMPORAL_PURGED
    assert captured["class_balance_basis"] == alpha.CLASS_BALANCE_WEIGHT
    assert captured["calib_weight_basis"] == alpha.CALIB_WEIGHT_UNIQUENESS
    assert captured["enforce_r2"] is True
    assert captured["variant"] == alpha.VARIANT_CAMADA1
    assert captured["device_type"] == "cpu"
    # AG-380 -- o cache pré-computado (aqui, `{}` de propósito) chega
    # intacto em `run_all_folds`, nunca recalculado dentro de `_objective`.
    assert captured["monotone_screen_override_by_split_side"] == {}


def test_objective_usa_pooled_sharpe_como_metrica(monkeypatch: pytest.MonkeyPatch) -> None:
    _captured, study = _run_objective_once(monkeypatch)
    assert study.best_value == pytest.approx(_FAKE_PATH_RESULT.sharpe_naive)


def test_seed_fixo_em_todos_os_trials(monkeypatch: pytest.MonkeyPatch) -> None:
    """`seed` nunca sorteado por trial -- ruído de seed já medido neste
    projeto (`audit/n_lifetime.yaml` id=20, `std~=0,31`); sortear
    contaminaria a superfície de resposta que o TPE aprende."""
    seeds: list[int] = []

    def fake_run_all_folds(df: pl.DataFrame, splits: tuple[Any, ...], **kwargs: Any) -> list[Any]:
        seeds.append(kwargs["seed"])
        return []

    def fake_backtest_by_path(folds: list[Any], df: pl.DataFrame) -> dict[int, Any]:
        return {0: _FAKE_PATH_RESULT}

    monkeypatch.setattr(alpha, "run_all_folds", fake_run_all_folds)
    monkeypatch.setattr(backtest_lite, "backtest_by_path", fake_backtest_by_path)

    study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=1))
    base_hyper = alpha.LGBMHyperparams.from_constants()

    def objective(trial: optuna.Trial) -> float:
        return mod._objective(
            trial,
            mf=_FAKE_MF,
            splits=(),
            symbol="BTCUSDT",
            resolution_id="R1",
            variant=alpha.VARIANT_CAMADA1,
            feature_ids_effective=("A01",),
            base_hyper=base_hyper,
            seed=7,
            device_type="cpu",
            search_space=_SMALL_SEARCH_SPACE,
            monotone_screen_cache={},
        )

    study.optimize(objective, n_trials=3)

    assert seeds == [7, 7, 7]


# --- write_search_artifact -------------------------------------------------


def _make_result(**overrides: Any) -> mod.OptunaSearchResult:
    base: dict[str, Any] = {
        "symbol": "BTCUSDT",
        "resolution_id": "R1",
        "variant": alpha.VARIANT_CAMADA1,
        "best_hyper": alpha.LGBMHyperparams.from_constants(),
        "best_value": 1.5,
        "n_trials_run": 3,
        "sampler_name": "tpe",
        "sampler_seed": 1,
        "device_type": "cpu",
        "study_name": "alpha_hyperparams_BTCUSDT_R1_camada1_deadbeef",
        "dsr": None,
        "dsr_n_trials": None,
    }
    base.update(overrides)
    return mod.OptunaSearchResult(**base)


def test_write_search_artifact_round_trip(tmp_path: Any) -> None:
    result = _make_result()
    manifest = mod.write_search_artifact(
        result, feature_ids_effective=("A01", "A02"), root=tmp_path
    )

    df, _read_manifest = io_artifact.read_artifact(
        root=tmp_path,
        stage=mod.OPTUNA_HYPERPARAMS_STAGE,
        config_hash=manifest.config_hash,
        symbol="BTCUSDT",
        resolution="R1",
    )
    row = df.row(0, named=True)
    assert row["num_leaves"] == result.best_hyper.num_leaves
    assert row["best_value"] == pytest.approx(1.5)
    assert row["variant"] == alpha.VARIANT_CAMADA1


def test_write_search_artifact_colide_sem_scratch(tmp_path: Any) -> None:
    result = _make_result()
    mod.write_search_artifact(result, feature_ids_effective=("A01",), root=tmp_path)

    with pytest.raises(io_artifact.ArtifactExistsError):
        mod.write_search_artifact(result, feature_ids_effective=("A01",), root=tmp_path)


def test_write_search_artifact_scratch_permite_sobrescrita(tmp_path: Any) -> None:
    result = _make_result()
    mod.write_search_artifact(result, feature_ids_effective=("A01",), root=tmp_path, scratch=True)
    # não levanta na 2a escrita
    mod.write_search_artifact(result, feature_ids_effective=("A01",), root=tmp_path, scratch=True)
