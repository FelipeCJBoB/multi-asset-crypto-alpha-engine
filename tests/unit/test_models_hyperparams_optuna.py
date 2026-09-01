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
    win_rate=0.5,
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


# --- confirm_top_k_multi_seed / confirm_combo_paired (2026-08-30) ---------
#
# Isola a LÓGICA (top-k, mediana, viés de seleção, gate pareado) de treino
# real -- `build_search_frame`/`_precompute_monotone_screens`/`alpha.
# run_all_folds`/`backtest_lite.backtest_by_path` monkeypatchados, mesmo
# padrão de `_run_objective_once` acima. `run_all_folds` (falso) devolve um
# marcador codificando (seed, num_leaves) -- `backtest_by_path` (falso) lê
# esse marcador e devolve Sharpe por caminho DETERMINÍSTICO, função de
# ambos, pra poder prever exatamente qual candidato/seed deveria vencer.


def _fake_path_result(path_id: int, sharpe: float) -> Any:
    return backtest_lite.PathBacktestResult(
        path_id=path_id,
        n_signals=10,
        n_filled_trades=8,
        fill_rate=0.8,
        sharpe_naive=sharpe,
        mean_trade_ret=0.01,
        std_trade_ret=0.02,
        trades_per_year=100.0,
        win_rate=0.5,
    )


def _patch_confirmation_plumbing(monkeypatch: pytest.MonkeyPatch) -> None:
    """`sharpe(seed, num_leaves) = num_leaves + seed/100` -- crescente nos
    dois eixos, então o candidato de MAIOR `num_leaves` sempre vence por
    mediana (sem empate), e dá pra prever o valor exato esperado."""
    monkeypatch.setattr(
        mod,
        "build_search_frame",
        lambda *a, **k: (_FAKE_MF, (), ("A01",)),
    )
    monkeypatch.setattr(mod, "_precompute_monotone_screens", lambda *a, **k: {})

    def fake_run_all_folds(df: pl.DataFrame, splits: tuple[Any, ...], **kwargs: Any) -> Any:
        return {"seed": kwargs["seed"], "num_leaves": kwargs["hyper"].num_leaves}

    def fake_backtest_by_path(folds: Any, df: pl.DataFrame) -> dict[int, Any]:
        base = folds["num_leaves"] + folds["seed"] / 100.0
        return {0: _fake_path_result(0, base), 1: _fake_path_result(1, base + 0.5)}

    monkeypatch.setattr(alpha, "run_all_folds", fake_run_all_folds)
    monkeypatch.setattr(backtest_lite, "backtest_by_path", fake_backtest_by_path)


def _seed_study(
    tmp_path: Any, *, symbol: str, resolution_id: str, variant: str, trials_num_leaves: list[int]
) -> None:
    """Cria um study REAL com trials COMPLETE conhecidos -- mesmo `study_
    name`/`db_path` que `run_search_for_combo` grava, pra `_load_existing_
    study` (dentro de `confirm_top_k_multi_seed`) achar de verdade."""
    config_hash = mod.compute_search_config_hash(
        ("A01",), variant=variant, n_trials=30, sampler_name="tpe", sampler_seed=42
    )
    study_name = f"alpha_hyperparams_{symbol}_{resolution_id}_{variant}_cpu_{config_hash[:8]}"
    db_path = tmp_path / f"{symbol}_{resolution_id}_{variant}_cpu.db"
    study = optuna.create_study(
        study_name=study_name, storage=f"sqlite:///{db_path.resolve()}", direction="maximize"
    )
    for num_leaves in trials_num_leaves:
        study.add_trial(
            optuna.trial.create_trial(
                params={"num_leaves": num_leaves},
                distributions={"num_leaves": optuna.distributions.IntDistribution(4, 64)},
                value=float(num_leaves),  # screening_value (1 seed) -- valor arbitrário aqui
                state=optuna.trial.TrialState.COMPLETE,
            )
        )


def test_confirm_top_k_multi_seed_escolhe_por_mediana_nao_por_screening(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Screening (1 seed) reportou `num_leaves=50` como "melhor" (maior
    `value` no study) -- mas a função `sharpe(seed, num_leaves)` usada nos
    mocks favorece linearmente `num_leaves` maior em QUALQUER seed, então
    o candidato de maior `num_leaves` dentre os top-k também vence por
    mediana aqui (caso simples, sem inversão) -- o teste seguinte cobre a
    inversão de fato."""
    _patch_confirmation_plumbing(monkeypatch)
    _seed_study(
        tmp_path,
        symbol="BTCUSDT",
        resolution_id="R1",
        variant=alpha.VARIANT_CAMADA1,
        trials_num_leaves=[10, 30, 50, 20, 5],
    )

    result = mod.confirm_top_k_multi_seed(
        symbol="BTCUSDT",
        resolution_id="R1",
        variant=alpha.VARIANT_CAMADA1,
        top_k=3,
        confirmation_seeds=(1, 2, 3),
        n_trials=30,
        sampler_seed=42,
        storage_dir=tmp_path,
    )

    assert len(result.candidates) == 3  # noqa: magic-number -- top_k=3
    assert result.winner.hyper.num_leaves == 50  # noqa: magic-number -- maior num_leaves, top-3
    # pooled(seed) = 50 + seed/100 + 0.25 (média de 2 paths, offsets 0/0.5) ->
    # seeds (1,2,3): [50.26, 50.27, 50.28] -> mediana = 50.27
    assert result.winner.median_pooled_sharpe == pytest.approx(50.27)  # noqa: magic-number


def test_confirm_top_k_multi_seed_vies_de_selecao_calculado(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`selection_bias_estimate` = `screening_value` (1 seed, o `value`
    gravado no study) menos `median_pooled_sharpe` (N seeds, recalculado
    aqui) -- os dois vêm de fontes DIFERENTES de propósito (um é histórico,
    o outro é medido de novo), então o teste prova que a subtração usa os
    valores certos, não que eles coincidem."""
    _patch_confirmation_plumbing(monkeypatch)
    _seed_study(
        tmp_path,
        symbol="ETHUSDT",
        resolution_id="R3",
        variant=alpha.VARIANT_CAMADA0,
        trials_num_leaves=[8, 16],
    )

    result = mod.confirm_top_k_multi_seed(
        symbol="ETHUSDT",
        resolution_id="R3",
        variant=alpha.VARIANT_CAMADA0,
        top_k=2,
        confirmation_seeds=(1,),
        n_trials=30,
        sampler_seed=42,
        storage_dir=tmp_path,
    )
    winner = result.winner
    assert winner.hyper.num_leaves == 16  # noqa: magic-number
    assert winner.screening_value == pytest.approx(16.0)  # noqa: magic-number -- value gravado no study
    assert winner.selection_bias_estimate == pytest.approx(
        winner.screening_value - winner.median_pooled_sharpe
    )


def test_confirm_top_k_multi_seed_falha_alto_sem_trial_complete(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_confirmation_plumbing(monkeypatch)
    config_hash = mod.compute_search_config_hash(
        ("A01",), variant=alpha.VARIANT_CAMADA1, n_trials=30, sampler_name="tpe", sampler_seed=42
    )
    study_name = f"alpha_hyperparams_XRPUSDT_R1_camada1_cpu_{config_hash[:8]}"
    db_path = tmp_path / "XRPUSDT_R1_camada1_cpu.db"
    optuna.create_study(
        study_name=study_name, storage=f"sqlite:///{db_path.resolve()}", direction="maximize"
    )  # study existe, mas 0 trials

    with pytest.raises(ValueError, match="não tem nenhum trial COMPLETE"):
        mod.confirm_top_k_multi_seed(
            symbol="XRPUSDT",
            resolution_id="R1",
            variant=alpha.VARIANT_CAMADA1,
            top_k=3,
            confirmation_seeds=(1,),
            n_trials=30,
            sampler_seed=42,
            storage_dir=tmp_path,
        )


def test_confirm_top_k_multi_seed_falha_alto_sem_study_no_disco(tmp_path: Any) -> None:
    with pytest.raises(FileNotFoundError, match="não existe"):
        mod.confirm_top_k_multi_seed(
            symbol="BNBUSDT",
            resolution_id="R2",
            variant=alpha.VARIANT_CAMADA1,
            top_k=3,
            confirmation_seeds=(1,),
            n_trials=30,
            sampler_seed=42,
            storage_dir=tmp_path,
        )


def test_confirm_combo_paired_gate_pass_quando_c1_supera_c0_nos_2_paths(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`sharpe(seed, num_leaves)` cresce em `num_leaves` -- dando à Camada1
    um `num_leaves` MAIOR que o teto da Camada0, C1 supera C0 nos 2
    caminhos, em toda seed -- `n_better=2` sempre, mediana=2. Não é o gate
    de produção (`min_paths=4/5`, aqui só 2 caminhos simulados) -- prova só
    o MECANISMO de contagem/mediana pareada, não o limiar real."""
    _patch_confirmation_plumbing(monkeypatch)
    _seed_study(
        tmp_path,
        symbol="SOLUSDT",
        resolution_id="R2",
        variant=alpha.VARIANT_CAMADA1,
        trials_num_leaves=[40, 50],
    )
    _seed_study(
        tmp_path,
        symbol="SOLUSDT",
        resolution_id="R2",
        variant=alpha.VARIANT_CAMADA0,
        trials_num_leaves=[10, 20],
    )

    result = mod.confirm_combo_paired(
        symbol="SOLUSDT",
        resolution_id="R2",
        top_k=1,
        confirmation_seeds=(1, 2),
        n_trials=30,
        sampler_seed=42,
        storage_dir=tmp_path,
    )

    assert result.camada1.winner.hyper.num_leaves == 50  # noqa: magic-number
    assert result.camada0.winner.hyper.num_leaves == 20  # noqa: magic-number
    assert result.n_better_by_seed == {1: 2, 2: 2}  # noqa: magic-number -- 2 paths, C1 > C0 nos 2
    assert result.median_n_better == pytest.approx(2.0)  # noqa: magic-number
    assert result.permanence_min_paths == 4  # noqa: magic-number -- alpha_layer1_permanence_min_paths real
    assert result.permanence_pass is False  # median_n_better(2) < permanence_min_paths(4)

    # Gate de edge bruto (AG-383-ADDENDUM) -- _fake_path_result fixa
    # mean_trade_ret=0.01 (positivo, > edge_min_bps=0.0) e n_filled_trades=8
    # por path; pooled entre os 2 paths falsos = 8+8=16 < edge_min_trades=30
    # real -- falha por COBERTURA, não por sinal, prova que os dois testes
    # do gate de edge são independentes.
    assert result.edge_min_bps == pytest.approx(0.0)
    assert result.edge_min_trades == 30  # noqa: magic-number -- alpha_layer1_permanence_min_trades real
    assert result.winner_median_pooled_edge_bps == pytest.approx(100.0)  # noqa: magic-number -- 0,01 fração * _BPS_PER_UNIT
    assert result.winner_median_trade_count == pytest.approx(16.0)  # noqa: magic-number -- 8+8, 2 paths
    assert result.edge_gate_pass is False  # cobertura (16) < piso (30)
    assert result.dual_gate_pass is False  # nem permanence nem edge passam aqui


def test_confirm_combo_paired_edge_gate_passa_com_edge_positivo_e_cobertura_suficiente(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Variante local de `_patch_confirmation_plumbing` com cobertura real
    (`n_filled_trades=20`/path x 2 paths = 40 >= piso de 30) e edge positivo
    -- prova que `edge_gate_pass` PODE ser True quando sinal e cobertura
    andam juntos, isolado de `permanence_pass` (que continua False aqui, só
    2 paths simulados nunca atingem o piso de 4/5 -- não é o alvo deste
    teste, mesma ressalva já documentada no teste irmão acima)."""

    def fake_path_result_cobertura_boa(path_id: int, sharpe: float) -> Any:
        return backtest_lite.PathBacktestResult(
            path_id=path_id,
            n_signals=25,
            n_filled_trades=20,
            fill_rate=0.8,
            sharpe_naive=sharpe,
            mean_trade_ret=0.02,
            std_trade_ret=0.02,
            trades_per_year=100.0,
            win_rate=0.5,
        )

    monkeypatch.setattr(
        mod, "build_search_frame", lambda *a, **k: (_FAKE_MF, (), ("A01",))
    )
    monkeypatch.setattr(mod, "_precompute_monotone_screens", lambda *a, **k: {})

    def fake_run_all_folds(df: pl.DataFrame, splits: tuple[Any, ...], **kwargs: Any) -> Any:
        return {"seed": kwargs["seed"], "num_leaves": kwargs["hyper"].num_leaves}

    def fake_backtest_by_path(folds: Any, df: pl.DataFrame) -> dict[int, Any]:
        base = folds["num_leaves"] + folds["seed"] / 100.0
        return {
            0: fake_path_result_cobertura_boa(0, base),
            1: fake_path_result_cobertura_boa(1, base + 0.5),
        }

    monkeypatch.setattr(alpha, "run_all_folds", fake_run_all_folds)
    monkeypatch.setattr(backtest_lite, "backtest_by_path", fake_backtest_by_path)
    _seed_study(
        tmp_path,
        symbol="SOLUSDT",
        resolution_id="R2",
        variant=alpha.VARIANT_CAMADA1,
        trials_num_leaves=[40, 50],
    )
    _seed_study(
        tmp_path,
        symbol="SOLUSDT",
        resolution_id="R2",
        variant=alpha.VARIANT_CAMADA0,
        trials_num_leaves=[10, 20],
    )

    result = mod.confirm_combo_paired(
        symbol="SOLUSDT",
        resolution_id="R2",
        top_k=1,
        confirmation_seeds=(1, 2),
        n_trials=30,
        sampler_seed=42,
        storage_dir=tmp_path,
    )

    assert result.winner_median_pooled_edge_bps == pytest.approx(200.0)  # noqa: magic-number -- 0,02 fração * _BPS_PER_UNIT
    assert result.winner_median_trade_count == pytest.approx(40.0)  # noqa: magic-number -- 20+20
    assert result.edge_gate_pass is True
    assert result.dual_gate_pass is False  # permanence_pass segue False (só 2 paths simulados)


def test_confirm_combo_paired_edge_gate_falha_por_sinal_mesmo_com_cobertura_boa(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mesma cobertura suficiente do teste irmão, mas `mean_trade_ret`
    negativo -- prova que o piso de sinal (`edge_min_bps=0,0`) reprova
    independentemente da cobertura, o outro eixo do gate duplo."""

    def fake_path_result_edge_negativo(path_id: int, sharpe: float) -> Any:
        return backtest_lite.PathBacktestResult(
            path_id=path_id,
            n_signals=25,
            n_filled_trades=20,
            fill_rate=0.8,
            sharpe_naive=sharpe,
            mean_trade_ret=-0.03,
            std_trade_ret=0.02,
            trades_per_year=100.0,
            win_rate=0.5,
        )

    monkeypatch.setattr(
        mod, "build_search_frame", lambda *a, **k: (_FAKE_MF, (), ("A01",))
    )
    monkeypatch.setattr(mod, "_precompute_monotone_screens", lambda *a, **k: {})

    def fake_run_all_folds(df: pl.DataFrame, splits: tuple[Any, ...], **kwargs: Any) -> Any:
        return {"seed": kwargs["seed"], "num_leaves": kwargs["hyper"].num_leaves}

    def fake_backtest_by_path(folds: Any, df: pl.DataFrame) -> dict[int, Any]:
        base = folds["num_leaves"] + folds["seed"] / 100.0
        return {
            0: fake_path_result_edge_negativo(0, base),
            1: fake_path_result_edge_negativo(1, base + 0.5),
        }

    monkeypatch.setattr(alpha, "run_all_folds", fake_run_all_folds)
    monkeypatch.setattr(backtest_lite, "backtest_by_path", fake_backtest_by_path)
    _seed_study(
        tmp_path,
        symbol="SOLUSDT",
        resolution_id="R2",
        variant=alpha.VARIANT_CAMADA1,
        trials_num_leaves=[40, 50],
    )
    _seed_study(
        tmp_path,
        symbol="SOLUSDT",
        resolution_id="R2",
        variant=alpha.VARIANT_CAMADA0,
        trials_num_leaves=[10, 20],
    )

    result = mod.confirm_combo_paired(
        symbol="SOLUSDT",
        resolution_id="R2",
        top_k=1,
        confirmation_seeds=(1, 2),
        n_trials=30,
        sampler_seed=42,
        storage_dir=tmp_path,
    )

    assert result.winner_median_pooled_edge_bps == pytest.approx(-300.0)  # noqa: magic-number -- -0,03 fração * _BPS_PER_UNIT
    assert result.winner_median_trade_count == pytest.approx(40.0)  # noqa: magic-number -- cobertura OK
    assert result.edge_gate_pass is False  # sinal negativo, apesar da cobertura suficiente
    assert result.dual_gate_pass is False


# ============================================================================
# ADR-008 Fase 2 (item 12/consultor) -- export_trial_trajectory
# ============================================================================


def _study_with_trials(n_trials: int) -> optuna.Study:
    """Study Optuna REAL, em memória (sem SQLite), com `n_trials`
    completos -- objetivo trivial, não treina nada, só exercita a
    mecânica real de `trials_dataframe()`."""
    study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=1))
    study.optimize(lambda trial: trial.suggest_float("x", 0.0, 1.0), n_trials=n_trials)
    return study


def test_export_trial_trajectory_grava_todos_os_trials_nao_so_o_vencedor(tmp_path: Any) -> None:
    study = _study_with_trials(5)

    out_path = mod.export_trial_trajectory(
        study, symbol="BTCUSDT", resolution_id="R2", variant="camada1", root=tmp_path
    )

    assert out_path.exists()
    assert out_path.name == "alpha_optuna_trials_BTCUSDT_R2_camada1.parquet"
    df = pl.read_parquet(out_path)
    assert df.height == 5  # todos os 5 trials, não só o best_trial
    assert "value" in df.columns
    assert "params_x" in df.columns
    assert "number" in df.columns


def test_export_trial_trajectory_e_atomico_tmp_nao_sobra(tmp_path: Any) -> None:
    study = _study_with_trials(2)
    mod.export_trial_trajectory(
        study, symbol="SOLUSDT", resolution_id="R3", variant="camada0", root=tmp_path
    )
    assert not (tmp_path / "alpha_optuna_trials_SOLUSDT_R3_camada0.parquet.tmp").exists()


def test_export_trial_trajectory_cria_diretorio_se_ausente(tmp_path: Any) -> None:
    study = _study_with_trials(1)
    root = tmp_path / "nested" / "dir"
    assert not root.exists()

    out_path = mod.export_trial_trajectory(
        study, symbol="XRPUSDT", resolution_id="R2", variant="camada1", root=root
    )

    assert out_path.exists()


# ============================================================================
# _derived_sampler_seed -- AG-399/AG-405 (auditoria adversarial externa,
# achado N2: sampler_seed compartilhado entre studies produzia trials de
# startup identicos entre combos)
# ============================================================================


def test_derived_sampler_seed_e_deterministico() -> None:
    a = mod._derived_sampler_seed(42, "BTCUSDT", "R2", "camada1")
    b = mod._derived_sampler_seed(42, "BTCUSDT", "R2", "camada1")
    assert a == b


def test_derived_sampler_seed_varia_por_symbol_resolution_variant() -> None:
    base = mod._derived_sampler_seed(42, "BTCUSDT", "R2", "camada1")
    outros = {
        mod._derived_sampler_seed(42, "XRPUSDT", "R2", "camada1"),
        mod._derived_sampler_seed(42, "BTCUSDT", "R3", "camada1"),
        mod._derived_sampler_seed(42, "BTCUSDT", "R2", "camada0"),
    }
    # nenhuma das 3 variacoes (symbol/resolution/variant) reproduz o
    # mesmo seed base -- a coincidencia que N2 mediu (learning_rate
    # identico entre BTCUSDT/R2 C1 e XRPUSDT/R3 C0) fica estruturalmente
    # impossivel: cada (symbol, resolution_id, variant) tem seed proprio.
    assert base not in outros


def test_derived_sampler_seed_dentro_do_range_valido_do_tpesampler() -> None:
    seed = mod._derived_sampler_seed(42, "SOLUSDT", "R3", "camada0")
    assert 0 <= seed < 2_147_483_647


# ============================================================================
# run_search_for_combo -- guard de t0_end sem storage_dir (item 12 do
# roadmap "Caso 0/20" / AG-411: t0_end nao entra no hash de identidade
# content-addressed, entao exige storage_dir explicito pra nao arriscar
# colidir/retomar o study de producao)
# ============================================================================


def test_run_search_for_combo_t0_end_sem_storage_dir_levanta_valueerror() -> None:
    """O guard precisa disparar ANTES de qualquer trabalho caro (build_
    search_frame/Optuna) -- este teste não deve custar mais que um
    ValueError imediato."""
    with pytest.raises(ValueError, match="storage_dir"):
        mod.run_search_for_combo(
            symbol="BTCUSDT",
            resolution_id="R2",
            variant=alpha.VARIANT_CAMADA1,
            t0_end="2022-01-01",
        )


def test_run_search_for_combo_variant_desconhecido_levanta_antes_do_guard_t0_end() -> None:
    """`variant` inválido é checado primeiro -- ordem de validação não
    esconde um erro atrás do outro."""
    with pytest.raises(ValueError, match="variant"):
        mod.run_search_for_combo(
            symbol="BTCUSDT", resolution_id="R2", variant="camada_invalida", t0_end="2022-01-01"
        )
