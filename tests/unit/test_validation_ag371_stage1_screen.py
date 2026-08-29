"""AG-371 Passo 3 (item 2) — testes de `src.validation.ag371_stage1_screen`.

Stuba a fronteira real (`hyperparam_search.run_one_trial`/`build_mf_and_
splits`) — não repete cobertura de treino, já coberta em `test_models_
alpha.py`/`test_validation_hyperparam_search.py`. Cobre a ESTRUTURA do
desenho (tamanho do grid, ordem, retomada por célula-camada, seleção do
melhor ponto ignorando NaN), que é o código novo deste módulo."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.models import alpha
from src.validation import ag371_stage1_screen as s1
from src.validation import hyperparam_search as hs


def _fake_trial_result(
    trial_id: str, pooled_sharpe: float, hyper: dict[str, float]
) -> hs.TrialResult:
    return hs.TrialResult(
        symbol="BTCUSDT", resolution_id="R1", variant=alpha.VARIANT_CAMADA1, seed=42,
        trial_id=trial_id, hyper=hyper, pooled_sharpe=pooled_sharpe,
        sharpe_by_path={"0": pooled_sharpe}, n_signals_by_path={"0": 10},
        n_filled_by_path={"0": 9}, fill_rate_by_path={"0": 0.9},
        trades_per_year_by_path={"0": 100.0}, n_paths=1, elapsed_seconds=1.0,
    )


def _patch_infra(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(s1, "_STAGE1_DIR", tmp_path)
    monkeypatch.setattr(
        s1.hs, "build_mf_and_splits", lambda *a, **k: (SimpleNamespace(data="df"), ())
    )
    monkeypatch.setattr(s1, "load_constant", lambda *_a, **_k: 42)

    def _fake_run_one_trial(mf: Any, splits: Any, **kwargs: Any) -> hs.TrialResult:
        calls.append(kwargs)
        hyper_dict = {f: getattr(kwargs["hyper"], f) for f in hs._HYPER_FIELDS}
        # Sharpe determinístico e distinto por trial, pra testar seleção do melhor.
        pooled = float(len(calls))
        return _fake_trial_result(kwargs["trial_id"], pooled, hyper_dict)

    monkeypatch.setattr(s1.hs, "run_one_trial", _fake_run_one_trial)

    def _fake_append(result: hs.TrialResult, path: Path) -> None:
        pass  # persistencia real testada em test_validation_hyperparam_search.py

    monkeypatch.setattr(s1.hs, "append_trial_result_jsonl", _fake_append)
    return calls


def test_trial_log_path_nomeia_por_celula_e_camada() -> None:
    path = s1.trial_log_path("BTCUSDT", "R1", alpha.VARIANT_CAMADA1)
    assert path.name == f"BTCUSDT_R1_{alpha.VARIANT_CAMADA1}.jsonl"


def test_grid_tem_29_trials_12_estrutural_17_coordenada(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(s1.hs, "read_trial_results_jsonl", lambda _p: [])
    calls = _patch_infra(monkeypatch, tmp_path)

    trials = s1.run_stage1_screen_one_cell_layer("BTCUSDT", "R1", alpha.VARIANT_CAMADA1)

    assert len(trials) == 29
    assert len(calls) == 29
    n_structural = sum(1 for c in calls if c["trial_id"].startswith("struct_"))
    n_coord = sum(1 for c in calls if c["trial_id"].startswith("coord_"))
    assert n_structural == 12
    assert n_coord == 17


def test_coordenada_descendente_ancora_no_melhor_ponto_do_grid_estrutural(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(s1.hs, "read_trial_results_jsonl", lambda _p: [])
    calls = _patch_infra(monkeypatch, tmp_path)

    s1.run_stage1_screen_one_cell_layer("BTCUSDT", "R1", alpha.VARIANT_CAMADA1)

    # fake_run_one_trial da pooled_sharpe crescente (1,2,3,...) -- o ultimo
    # trial estrutural (12o) e o "melhor" do grid -- ancora precisa refletir
    # os hiperparametros estruturais DAQUELE trial nos 17 trials seguintes.
    structural_calls = [c for c in calls if c["trial_id"].startswith("struct_")]
    coord_calls = [c for c in calls if c["trial_id"].startswith("coord_")]
    winner_hyper = structural_calls[-1]["hyper"]
    for c in coord_calls:
        assert c["hyper"].max_depth == winner_hyper.max_depth
        assert c["hyper"].num_leaves == winner_hyper.num_leaves
        assert c["hyper"].min_child_samples == winner_hyper.min_child_samples


def test_variant_e_feature_ids_repassados_corretamente(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(s1.hs, "read_trial_results_jsonl", lambda _p: [])
    calls = _patch_infra(monkeypatch, tmp_path)

    s1.run_stage1_screen_one_cell_layer("ETHUSDT", "R2", alpha.VARIANT_CAMADA0)

    assert all(c["variant"] == alpha.VARIANT_CAMADA0 for c in calls)
    assert all(c["symbol"] == "ETHUSDT" for c in calls)
    assert all(c["resolution_id"] == "R2" for c in calls)
    from src.features import build as features_build

    assert all(c["feature_ids"] == features_build.T1_FEATURE_IDS for c in calls)


def test_celula_camada_ja_feita_pula_e_nao_chama_run_one_trial(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_row = _fake_trial_result("struct_0_0", 1.0, dict.fromkeys(hs._HYPER_FIELDS, 0.0))
    from dataclasses import asdict

    monkeypatch.setattr(s1.hs, "read_trial_results_jsonl", lambda _p: [asdict(fake_row)])
    calls = _patch_infra(monkeypatch, tmp_path)

    trials = s1.run_stage1_screen_one_cell_layer("BTCUSDT", "R1", alpha.VARIANT_CAMADA1)

    assert len(calls) == 0
    assert len(trials) == 1
    assert trials[0].trial_id == "struct_0_0"


def test_best_finite_ignora_nan() -> None:
    good = _fake_trial_result("a", 0.5, {})
    nan_trial = _fake_trial_result("b", float("nan"), {})
    best = _fake_trial_result("c", 2.5, {})
    result = s1._best_finite([good, nan_trial, best])
    assert result.trial_id == "c"


def test_best_finite_todos_nan_nao_crasha() -> None:
    all_nan = [_fake_trial_result(f"t{i}", float("nan"), {}) for i in range(3)]
    result = s1._best_finite(all_nan)
    assert result.trial_id in {"t0", "t1", "t2"}
