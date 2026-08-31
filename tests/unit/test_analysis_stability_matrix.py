"""Testes de `src.analysis.stability_matrix` — ADR-008 Fase 5. Núcleo
puro (Idioma A) — opera sobre dicts no MESMO schema de
`dataclasses.asdict(WalkForwardResult)` (um `variant` do payload de
`experiments/alpha_walk_forward_{symbol}_{resolution_id}.json`), sem IO
nenhum. Fixtures constroem esse dict diretamente, sem depender de
`src.models`."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from src.analysis import stability_matrix as sm


def _fold(
    fold_id: int,
    *,
    degenerado: bool = False,
    gain_by_side: dict[str, dict[str, float]] | None = None,
    score_quality_by_side: dict[str, dict[str, Any]] | None = None,
    decile_profile_by_side: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "fold_id": fold_id,
        "degenerado": degenerado,
        "gain_by_column_by_side": gain_by_side if gain_by_side is not None else {},
        "score_quality_by_side": score_quality_by_side if score_quality_by_side is not None else {},
        "decile_profile_by_side": (
            decile_profile_by_side if decile_profile_by_side is not None else {}
        ),
    }


def _payload(
    fold_results: list[dict[str, Any]], *, n_folds_total: int, n_folds_usados: int
) -> dict[str, Any]:
    return {
        "fold_results": fold_results,
        "n_folds_total": n_folds_total,
        "n_folds_usados": n_folds_usados,
    }


def _sq(
    spearman_ic_pooled: float, roc_auc: float, log_loss: float, n_trades: int
) -> dict[str, Any]:
    return {
        "n_trades": n_trades,
        "spearman_ic_pooled": spearman_ic_pooled,
        "roc_auc": roc_auc,
        "log_loss": log_loss,
    }


def _decile(q10_minus_q1_bps: float) -> dict[str, Any]:
    return {"q10_minus_q1_bps": q10_minus_q1_bps}


def _build(payload: dict[str, Any]) -> sm.StabilityMatrixResult:
    return sm.build_stability_matrix(
        payload, symbol="BTCUSDT", resolution_id="R2", variant="camada1"
    )


def test_build_stability_matrix_pula_folds_degenerados() -> None:
    payload = _payload(
        [
            _fold(0, degenerado=True, gain_by_side={"long": {"A": 1.0}}),
            _fold(
                1,
                gain_by_side={"long": {"A": 1.0}},
                score_quality_by_side={"long": _sq(0.5, 0.6, 0.7, 10)},  # noqa: magic-number
                decile_profile_by_side={"long": _decile(5.0)},  # noqa: magic-number
            ),
        ],
        n_folds_total=2,
        n_folds_usados=1,
    )

    out = _build(payload)

    assert {r.fold_id for r in out.rows} == {1}


def test_build_stability_matrix_uma_linha_por_lado_treinado_short_sem_trade_fica_nan() -> None:
    """Os 2 lados TREINAM sempre (gain presente pros 2), mas só `long`
    teve trade OOF nesse fold (`score_quality_by_side` só tem `long`) --
    `short` ainda vira uma linha, com as métricas de trade em `NaN` (não
    ausente: treinar não exige ter sinalizado)."""
    payload = _payload(
        [
            _fold(
                0,
                gain_by_side={"long": {"A": 1.0}, "short": {"B": 1.0}},
                score_quality_by_side={"long": _sq(0.5, 0.6, 0.7, 10)},  # noqa: magic-number
                decile_profile_by_side={"long": _decile(5.0)},  # noqa: magic-number
            ),
        ],
        n_folds_total=1,
        n_folds_usados=1,
    )

    out = _build(payload)

    assert {r.side for r in out.rows} == {"long", "short"}
    short_row = next(r for r in out.rows if r.side == "short")
    assert short_row.n_trades == 0
    assert np.isnan(short_row.ic_spearman_pooled)
    assert np.isnan(short_row.q10_minus_q1_bps)
    assert short_row.top_feature_by_gain == "B"  # gain existe mesmo sem trade


def test_build_stability_matrix_top_feature_por_gain_conferido_a_mao() -> None:
    payload = _payload(
        [
            _fold(
                0,
                gain_by_side={"long": {"A": 10.0, "B": 30.0, "C": 5.0}},  # noqa: magic-number
                score_quality_by_side={"long": _sq(0.5, 0.6, 0.7, 10)},  # noqa: magic-number
                decile_profile_by_side={"long": _decile(5.0)},  # noqa: magic-number
            ),
        ],
        n_folds_total=1,
        n_folds_usados=1,
    )

    out = _build(payload)

    row = next(r for r in out.rows if r.side == "long")
    assert row.top_feature_by_gain == "B"
    assert row.top_feature_gain_share == pytest.approx(30.0 / 45.0)  # noqa: magic-number


def test_build_stability_matrix_gain_vazio_ou_zero_devolve_none() -> None:
    payload = _payload(
        [
            _fold(0, gain_by_side={"long": {}}),
            _fold(1, gain_by_side={"long": {"A": 0.0, "B": 0.0}}),
        ],
        n_folds_total=2,
        n_folds_usados=2,
    )

    out = _build(payload)

    assert len(out.rows) == 2
    for row in out.rows:
        assert row.top_feature_by_gain is None
        assert np.isnan(row.top_feature_gain_share)


def test_build_stability_matrix_dispersion_conferida_a_mao() -> None:
    """2 folds, `ic_spearman_pooled` = [0.2, 0.6] -- mean=0,4, std(ddof=1)
    calculado explicitamente abaixo, não assumido."""
    payload = _payload(
        [
            _fold(
                0,
                gain_by_side={"long": {"A": 1.0}},
                score_quality_by_side={"long": _sq(0.2, 0.6, 0.7, 10)},  # noqa: magic-number
                decile_profile_by_side={"long": _decile(5.0)},  # noqa: magic-number
            ),
            _fold(
                1,
                gain_by_side={"long": {"A": 1.0}},
                score_quality_by_side={"long": _sq(0.6, 0.6, 0.7, 10)},  # noqa: magic-number
                decile_profile_by_side={"long": _decile(5.0)},  # noqa: magic-number
            ),
        ],
        n_folds_total=2,
        n_folds_usados=2,
    )

    out = _build(payload)

    disp = out.dispersion_by_metric_and_side["long"]["ic_spearman_pooled"]
    expected_mean = float(np.mean([0.2, 0.6]))  # noqa: magic-number
    expected_std = float(np.std([0.2, 0.6], ddof=1))  # noqa: magic-number
    assert disp["mean"] == pytest.approx(expected_mean)
    assert disp["std"] == pytest.approx(expected_std)
    assert disp["min"] == pytest.approx(0.2)  # noqa: magic-number
    assert disp["max"] == pytest.approx(0.6)  # noqa: magic-number


def test_build_stability_matrix_top_feature_frequency_conferida_a_mao() -> None:
    """3 folds long: feature A vence 2x, B vence 1x -> frequência
    {A: 2/3, B: 1/3}, ordenado decrescente."""
    payload = _payload(
        [
            _fold(
                i,
                gain_by_side={"long": {"A": 10.0, "B": 1.0}},  # noqa: magic-number
                score_quality_by_side={"long": _sq(0.5, 0.6, 0.7, 10)},  # noqa: magic-number
                decile_profile_by_side={"long": _decile(5.0)},  # noqa: magic-number
            )
            for i in range(2)
        ]
        + [
            _fold(
                2,
                gain_by_side={"long": {"A": 1.0, "B": 10.0}},  # noqa: magic-number
                score_quality_by_side={"long": _sq(0.5, 0.6, 0.7, 10)},  # noqa: magic-number
                decile_profile_by_side={"long": _decile(5.0)},  # noqa: magic-number
            )
        ],
        n_folds_total=3,  # noqa: magic-number
        n_folds_usados=3,  # noqa: magic-number
    )

    out = _build(payload)

    freq = out.top_feature_frequency_by_side["long"]
    assert list(freq.keys()) == ["A", "B"]  # ordenado decrescente
    assert freq["A"] == pytest.approx(2.0 / 3.0)  # noqa: magic-number
    assert freq["B"] == pytest.approx(1.0 / 3.0)  # noqa: magic-number


def test_build_stability_matrix_lado_sem_gain_nenhum_fica_fora_das_linhas() -> None:
    payload = _payload(
        [_fold(0, gain_by_side={"long": {"A": 1.0}})],  # short nunca aparece
        n_folds_total=1,
        n_folds_usados=1,
    )

    out = _build(payload)

    assert {r.side for r in out.rows} == {"long"}


def test_build_stability_matrix_propaga_metadados_do_payload() -> None:
    payload = _payload([], n_folds_total=12, n_folds_usados=4)  # noqa: magic-number

    out = sm.build_stability_matrix(
        payload, symbol="SOLUSDT", resolution_id="R3", variant="camada0"
    )

    assert out.symbol == "SOLUSDT"
    assert out.resolution_id == "R3"
    assert out.variant == "camada0"
    assert out.n_folds_total == 12  # noqa: magic-number
    assert out.n_folds_usados == 4  # noqa: magic-number
    assert out.rows == ()
