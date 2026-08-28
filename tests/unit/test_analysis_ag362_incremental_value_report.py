"""Núcleo puro de `src.analysis.ag362_incremental_value_report` -- não
exercita `run_layer1_sprint_all_combinations` (treino real, já coberto
em `test_models_pipeline*.py`), só `summarize_combinations`/
`pick_better_hyperparam_config`."""

from __future__ import annotations

import math
from typing import Any

from src.analysis import ag362_incremental_value_report as mod


def _report(
    *, permanence_pass: bool, delta_sharpe_mean: float, n_better: int = 3
) -> dict[str, Any]:
    return {
        "layer1_vs_layer0": {
            "permanence_pass": permanence_pass,
            "n_paths_camada1_supera_camada0": n_better,
            "n_paths_total": 5,
            "delta_sharpe_mean": delta_sharpe_mean,
        },
        "economic_gate": None,
    }


def test_summarize_combinations_conta_permanence_pass_e_soma_delta_sharpe() -> None:
    reports = {
        ("BTCUSDT", "R1"): _report(permanence_pass=True, delta_sharpe_mean=0.10),
        ("BTCUSDT", "R2"): _report(permanence_pass=False, delta_sharpe_mean=-0.05),
        ("ETHUSDT", "R1"): _report(permanence_pass=True, delta_sharpe_mean=0.20),
    }

    summary = mod.summarize_combinations(reports)

    assert summary["n_combinations"] == 3
    assert summary["n_permanence_pass"] == 2
    assert summary["delta_sharpe_mean_sum"] == 0.10 - 0.05 + 0.20
    assert summary["delta_sharpe_mean_avg"] == (0.10 - 0.05 + 0.20) / 3
    assert set(summary["per_combo"]) == {"BTCUSDT_R1", "BTCUSDT_R2", "ETHUSDT_R1"}
    assert summary["per_combo"]["BTCUSDT_R1"]["permanence_pass"] is True


def test_summarize_combinations_delta_sharpe_nan_nao_contamina_o_agregado() -> None:
    """Regressão de `AG-367`: medido ao vivo em `stage=off` -- 5/15
    combinações tinham `delta_sharpe_mean=NaN` (Sharpe indefinido em
    algum caminho), e a soma ingênua propagava `NaN` pro agregado
    inteiro (`nan + x == nan`), que `orjson` depois serializa como
    `null` -- destruindo o critério de desempate silenciosamente."""
    reports = {
        ("BTCUSDT", "R1"): _report(
            permanence_pass=False, delta_sharpe_mean=math.nan, n_better=0
        ),
        ("ETHUSDT", "R1"): _report(permanence_pass=True, delta_sharpe_mean=0.30, n_better=4),
        ("SOLUSDT", "R1"): _report(permanence_pass=False, delta_sharpe_mean=0.10, n_better=2),
    }

    summary = mod.summarize_combinations(reports)

    assert summary["n_combinations"] == 3
    assert summary["n_delta_sharpe_non_finite"] == 1
    assert summary["delta_sharpe_mean_sum"] == 0.40
    assert summary["delta_sharpe_mean_avg"] == 0.20
    assert summary["per_combo"]["BTCUSDT_R1"]["delta_sharpe_mean"] is None


def test_summarize_combinations_vazio_nao_divide_por_zero() -> None:
    summary = mod.summarize_combinations({})

    assert summary["n_combinations"] == 0
    assert summary["n_permanence_pass"] == 0
    assert summary["delta_sharpe_mean_avg"] == 0.0


def test_pick_better_hyperparam_config_decide_por_n_permanence_pass() -> None:
    summary_off = {"n_permanence_pass": 5, "delta_sharpe_mean_sum": -1.0}
    summary_on = {"n_permanence_pass": 3, "delta_sharpe_mean_sum": 10.0}

    winner, reason = mod.pick_better_hyperparam_config(summary_off, summary_on)

    assert winner == "off"
    assert "n_permanence_pass" in reason


def test_pick_better_hyperparam_config_empate_desempata_por_delta_sharpe() -> None:
    summary_off = {"n_permanence_pass": 4, "delta_sharpe_mean_sum": 0.5}
    summary_on = {"n_permanence_pass": 4, "delta_sharpe_mean_sum": 1.5}

    winner, reason = mod.pick_better_hyperparam_config(summary_off, summary_on)

    assert winner == "on"
    assert "empate" in reason


def test_pick_better_hyperparam_config_empate_total_favorece_off() -> None:
    summary_off = {"n_permanence_pass": 4, "delta_sharpe_mean_sum": 1.0}
    summary_on = {"n_permanence_pass": 4, "delta_sharpe_mean_sum": 1.0}

    winner, _reason = mod.pick_better_hyperparam_config(summary_off, summary_on)

    assert winner == "off"


def test_original_t1_feature_ids_tem_7_features_e_nao_e_o_vetor_atual() -> None:
    from src.features.build import T1_FEATURE_IDS

    assert len(mod.ORIGINAL_T1_FEATURE_IDS) == 7
    assert mod.ORIGINAL_T1_FEATURE_IDS != T1_FEATURE_IDS
    assert set(mod.ORIGINAL_T1_FEATURE_IDS).issubset(set(T1_FEATURE_IDS))
