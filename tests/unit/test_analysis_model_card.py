"""Testes de `src.analysis.model_card` — ADR-008 Fase 8. Núcleo puro
(Idioma A) — compõe sobre `StabilityMatrixResult`/`GateVerdict` já
construídos (Fases 5/6), fixtures montadas diretamente sem depender de
`src.models`."""

from __future__ import annotations

import math
from typing import Any

import pytest

from src.analysis import model_card as mc
from src.analysis import stability_matrix as sm
from src.analysis import walk_forward_gates as wfg


def _dispersion(mean: float, std: float) -> dict[str, float]:
    return {"n": 5.0, "mean": mean, "median": mean, "std": std, "min": mean, "max": mean}  # noqa: magic-number


def _stability(
    *,
    auc_long: float = 0.55,  # noqa: magic-number
    ic_long_mean: float = 0.1,  # noqa: magic-number
    ic_long_std: float = 0.05,  # noqa: magic-number
    q_long: float = 20.0,  # noqa: magic-number
    gain_freq_long: dict[str, float] | None = None,
) -> sm.StabilityMatrixResult:
    nan = float("nan")
    empty_disp = {"n": 0.0, "mean": nan, "median": nan, "std": nan, "min": nan, "max": nan}
    return sm.StabilityMatrixResult(
        symbol="BTCUSDT",
        resolution_id="R2",
        variant="camada1",
        n_folds_total=12,  # noqa: magic-number
        n_folds_usados=8,  # noqa: magic-number
        rows=(),
        dispersion_by_metric_and_side={
            "long": {
                "ic_spearman_pooled": _dispersion(ic_long_mean, ic_long_std),
                "roc_auc": _dispersion(auc_long, 0.1),  # noqa: magic-number
                "log_loss": empty_disp,
                "q10_minus_q1_bps": _dispersion(q_long, 5.0),  # noqa: magic-number
            },
            "short": {
                "ic_spearman_pooled": empty_disp,
                "roc_auc": empty_disp,
                "log_loss": empty_disp,
                "q10_minus_q1_bps": empty_disp,
            },
        },
        top_feature_frequency_by_side={
            "long": gain_freq_long if gain_freq_long is not None else {"A": 0.75},  # noqa: magic-number
            "short": {},
        },
        top_shap_feature_frequency_by_side={"long": {}, "short": {}},
        gain_shap_agreement_rate_by_side={"long": float("nan"), "short": float("nan")},
    )


def _gate_verdict(
    *, data_pass: bool = True, alpha_pass: bool = True, model_long_pass: bool = True
) -> wfg.GateVerdict:
    return wfg.GateVerdict(
        combo="BTCUSDT/R2",
        variant="camada1",
        n_folds_total=12,  # noqa: magic-number
        n_folds_usados=8,  # noqa: magic-number
        frac_folds_usados=8.0 / 12.0,  # noqa: magic-number
        data_gate_pass=data_pass,
        edge_bps_mean=5.0,  # noqa: magic-number
        alpha_gate_pass=alpha_pass,
        auc_mean_by_side={"long": 0.55, "short": float("nan")},  # noqa: magic-number
        model_gate_pass_by_side={"long": model_long_pass, "short": False},
    )


def _payload() -> dict[str, Any]:
    return {
        "n_folds_total": 12,  # noqa: magic-number
        "n_folds_usados": 8,  # noqa: magic-number
        "aggregate": {"mean": {"sharpe": 0.0, "edge_bps": 5.0, "win_rate": 0.5}},  # noqa: magic-number
    }


def test_build_model_card_metricas_reais_conferidas_a_mao() -> None:
    stability = _stability(auc_long=0.55, ic_long_mean=0.1, ic_long_std=0.05, q_long=20.0)  # noqa: magic-number
    gate_verdict = _gate_verdict()

    card = mc.build_model_card(_payload(), stability, gate_verdict, side="long")

    assert card.combo == "BTCUSDT/R2"
    assert card.variant == "camada1"
    assert card.side == "long"
    assert card.test_auc == pytest.approx(0.55)  # noqa: magic-number
    assert card.test_rank_ic == pytest.approx(0.1)  # noqa: magic-number
    assert card.ic_ir == pytest.approx(0.1 / 0.05)  # noqa: magic-number
    assert card.q10_minus_q1_bps == pytest.approx(20.0)  # noqa: magic-number
    assert card.oos_folds_usados == 8  # noqa: magic-number
    assert card.oos_folds_total == 12  # noqa: magic-number
    assert card.feature_stability_pct == pytest.approx(0.75)  # noqa: magic-number


def test_build_model_card_2_metricas_ficam_tbd_none() -> None:
    """B23 (CLAUDE.md) -- nunca inventar faixa esperada. `regime_
    stability_pct`/`generalization_gap_pct` não foram medidos nesta
    rodada -- `None`, não `0.0`/`NaN` fingindo medição."""
    card = mc.build_model_card(_payload(), _stability(), _gate_verdict(), side="long")

    assert card.regime_stability_pct is None
    assert card.generalization_gap_pct is None


def test_build_model_card_ic_ir_nan_quando_std_zero_ou_nao_finito() -> None:
    stability = _stability(ic_long_mean=0.1, ic_long_std=0.0)  # noqa: magic-number
    card = mc.build_model_card(_payload(), stability, _gate_verdict(), side="long")

    assert math.isnan(card.ic_ir)


def test_build_model_card_feature_stability_nan_sem_gain() -> None:
    stability = _stability(gain_freq_long={})
    card = mc.build_model_card(_payload(), stability, _gate_verdict(), side="long")

    assert math.isnan(card.feature_stability_pct)


def test_build_model_card_gate_pass_e_and_dos_3_gates() -> None:
    stability = _stability()

    # os 3 passam -> gate_pass True
    card_all_pass = mc.build_model_card(
        _payload(), stability, _gate_verdict(data_pass=True, alpha_pass=True, model_long_pass=True),
        side="long",
    )
    assert card_all_pass.gate_pass is True

    # 1 falha (data) -> gate_pass False, mesmo com os outros 2 passando
    gate_verdict_data_fail = _gate_verdict(data_pass=False, alpha_pass=True, model_long_pass=True)
    card_data_fail = mc.build_model_card(
        _payload(), stability, gate_verdict_data_fail, side="long"
    )
    assert card_data_fail.gate_pass is False
    assert card_data_fail.gate_data_pass is False
    assert card_data_fail.gate_alpha_pass is True
    assert card_data_fail.gate_model_pass is True


def test_build_model_cards_for_combo_devolve_long_e_short() -> None:
    cards = mc.build_model_cards_for_combo(_payload(), _stability(), _gate_verdict())

    assert {c.side for c in cards} == {"long", "short"}
    assert len(cards) == 2  # noqa: magic-number
