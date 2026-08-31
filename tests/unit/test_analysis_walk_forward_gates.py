"""Testes de `src.analysis.walk_forward_gates` — ADR-008 Fase 6. Núcleo
puro (Idioma A), mesmo padrão de `test_models_backtest_lite.py::
test_permanence_pass_criterion_*`/`test_models_hhi.py::test_gate3_4_*`:
passa nos dois lados da fronteira, falha em cada critério isoladamente,
fronteira exata."""

from __future__ import annotations

import math

import pytest

from src.analysis import stability_matrix as sm
from src.analysis import walk_forward_gates as wfg

# ============================================================================
# data_gate_passes -- >= threshold (empate passa, mesma convenção de
# permanence_pass_criterion, não a de gate3_4_passes)
# ============================================================================


def test_data_gate_passa_acima_do_threshold() -> None:
    assert wfg.data_gate_passes(0.6, threshold=0.5) is True  # noqa: magic-number


def test_data_gate_fronteira_exata_passa() -> None:
    assert wfg.data_gate_passes(0.5, threshold=0.5) is True  # noqa: magic-number


def test_data_gate_falha_abaixo_do_threshold() -> None:
    assert wfg.data_gate_passes(0.49, threshold=0.5) is False  # noqa: magic-number


def test_data_gate_nan_sempre_falha() -> None:
    assert wfg.data_gate_passes(float("nan"), threshold=0.0) is False


# ============================================================================
# model_gate_passes -- >= min_auc
# ============================================================================


def test_model_gate_passa_acima_do_minimo() -> None:
    assert wfg.model_gate_passes(0.55, min_auc=0.52) is True  # noqa: magic-number


def test_model_gate_fronteira_exata_passa() -> None:
    assert wfg.model_gate_passes(0.52, min_auc=0.52) is True  # noqa: magic-number


def test_model_gate_falha_perto_da_moeda_honesta() -> None:
    assert wfg.model_gate_passes(0.50, min_auc=0.52) is False  # noqa: magic-number


def test_model_gate_nan_sempre_falha() -> None:
    """Achado real (campanha 2026-08-31): vários combos/lados tiveram
    AUC=NaN (nenhum fold com trade suficiente pro AUC ser computável) --
    NaN nunca pode ser lido como aprovação por omissão."""
    assert wfg.model_gate_passes(float("nan"), min_auc=0.52) is False  # noqa: magic-number


# ============================================================================
# alpha_gate_passes -- > min_edge_bps (comparação ESTRITA, mesma
# convenção de edge_gate_pass sobre CPCV)
# ============================================================================


def test_alpha_gate_passa_com_edge_positivo() -> None:
    assert wfg.alpha_gate_passes(5.0, min_edge_bps=0.0) is True  # noqa: magic-number


def test_alpha_gate_fronteira_exata_falha_comparacao_estrita() -> None:
    """`>`, não `>=` -- break-even exato não é edge, mesma convenção
    documentada em `edge_gate_pass` (ag220_dual_gate_calibration.py)."""
    assert wfg.alpha_gate_passes(0.0, min_edge_bps=0.0) is False


def test_alpha_gate_falha_com_edge_negativo() -> None:
    assert wfg.alpha_gate_passes(-5.0, min_edge_bps=0.0) is False  # noqa: magic-number


def test_alpha_gate_nan_sempre_falha() -> None:
    assert wfg.alpha_gate_passes(float("nan"), min_edge_bps=0.0) is False


# ============================================================================
# evaluate_gates -- composição real sobre payload + StabilityMatrixResult
# ============================================================================


def _nan_stat() -> dict[str, float]:
    nan = float("nan")
    return {"n": 0.0, "mean": nan, "median": nan, "std": nan, "min": nan, "max": nan}


def _auc_stat(auc: float) -> dict[str, float]:
    return {"n": 1.0, "mean": auc, "median": auc, "std": float("nan"), "min": auc, "max": auc}


def _stability_result(auc_long: float, auc_short: float) -> sm.StabilityMatrixResult:
    return sm.StabilityMatrixResult(
        symbol="BTCUSDT",
        resolution_id="R2",
        variant="camada1",
        n_folds_total=12,  # noqa: magic-number
        n_folds_usados=8,  # noqa: magic-number
        rows=(),
        dispersion_by_metric_and_side={
            "long": {
                "ic_spearman_pooled": _nan_stat(),
                "roc_auc": _auc_stat(auc_long),
                "log_loss": _nan_stat(),
                "q10_minus_q1_bps": _nan_stat(),
            },
            "short": {
                "ic_spearman_pooled": _nan_stat(),
                "roc_auc": _auc_stat(auc_short),
                "log_loss": _nan_stat(),
                "q10_minus_q1_bps": _nan_stat(),
            },
        },
        top_feature_frequency_by_side={"long": {}, "short": {}},
    )


def _walk_forward_payload(n_folds_total: int, n_folds_usados: int, edge_bps_mean: float) -> dict:
    return {
        "n_folds_total": n_folds_total,
        "n_folds_usados": n_folds_usados,
        "aggregate": {"mean": {"sharpe": 0.0, "edge_bps": edge_bps_mean, "win_rate": 0.5}},  # noqa: magic-number
    }


def test_evaluate_gates_composicao_real_conferida_a_mao() -> None:
    """8/12 folds usados (frac=0,6667, >= 0,5 -> Data passa), edge_bps
    médio=5,0 (> 0,0 -> Alpha passa), AUC long=0,55 (>= 0,52 -> Model
    long passa), AUC short=0,48 (< 0,52 -> Model short falha)."""
    payload = _walk_forward_payload(12, 8, 5.0)  # noqa: magic-number
    stability = _stability_result(auc_long=0.55, auc_short=0.48)  # noqa: magic-number

    verdict = wfg.evaluate_gates(
        payload,
        stability,
        data_min_frac_folds_usados=0.5,  # noqa: magic-number
        model_min_auc=0.52,  # noqa: magic-number
        alpha_min_edge_bps=0.0,
    )

    assert verdict.combo == "BTCUSDT/R2"
    assert verdict.variant == "camada1"
    assert verdict.frac_folds_usados == pytest.approx(8.0 / 12.0)  # noqa: magic-number
    assert verdict.data_gate_pass is True
    assert verdict.alpha_gate_pass is True
    assert verdict.model_gate_pass_by_side == {"long": True, "short": False}
    assert verdict.auc_mean_by_side["long"] == pytest.approx(0.55)  # noqa: magic-number


def test_evaluate_gates_zero_folds_totais_frac_nan_data_gate_falha() -> None:
    payload = _walk_forward_payload(0, 0, float("nan"))
    stability = _stability_result(auc_long=float("nan"), auc_short=float("nan"))

    verdict = wfg.evaluate_gates(
        payload,
        stability,
        data_min_frac_folds_usados=0.5,  # noqa: magic-number
        model_min_auc=0.52,  # noqa: magic-number
        alpha_min_edge_bps=0.0,
    )

    assert math.isnan(verdict.frac_folds_usados)
    assert verdict.data_gate_pass is False
