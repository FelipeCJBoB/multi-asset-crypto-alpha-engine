"""Testes de `src.analysis.walk_forward_gates` — ADR-008 Fase 6, forma
corrigida 2026-08-31 ("investigar e medir os thresholds corretamente").
Núcleo puro (Idioma A): passa nos dois lados da fronteira, falha em cada
critério isoladamente, fronteira exata. `model_gate_passes` agora é um
teste-t de uma amostra (não mais comparação contra um AUC fixo) — os
testes incluem valores conferidos a mão contra `scipy.stats.t.ppf`."""

from __future__ import annotations

import math
from typing import Any

import pytest
from scipy.stats import t as student_t

from src.analysis import stability_matrix as sm
from src.analysis import walk_forward_gates as wfg

# ============================================================================
# data_gate_passes -- >= min_folds (piso ABSOLUTO, não fração -- correção
# 2026-08-31, empate passa, mesma convenção de permanence_pass_criterion)
# ============================================================================


def test_data_gate_passa_acima_do_piso() -> None:
    assert wfg.data_gate_passes(12, min_folds=10) is True  # noqa: magic-number


def test_data_gate_fronteira_exata_passa() -> None:
    assert wfg.data_gate_passes(10, min_folds=10) is True  # noqa: magic-number


def test_data_gate_falha_abaixo_do_piso() -> None:
    assert wfg.data_gate_passes(9, min_folds=10) is False  # noqa: magic-number


def test_data_gate_zero_folds_usados_falha() -> None:
    assert wfg.data_gate_passes(0, min_folds=10) is False  # noqa: magic-number


# ============================================================================
# model_gate_passes -- teste-t unicaudal (H0: AUC_medio<=0,5), não mais
# comparação contra AUC fixo (correção 2026-08-31)
# ============================================================================


def test_model_gate_nan_auc_mean_sempre_falha() -> None:
    assert wfg.model_gate_passes(float("nan"), 0.1, 5, significance_level=0.05) is False  # noqa: magic-number


def test_model_gate_nan_auc_std_sempre_falha() -> None:
    assert wfg.model_gate_passes(0.6, float("nan"), 5, significance_level=0.05) is False  # noqa: magic-number


def test_model_gate_menos_de_2_folds_sempre_falha() -> None:
    """Sem >=2 pontos não há desvio-padrão amostral (ddof=1) nem teste-t
    possível -- ausência de dado nunca é aprovação por omissão."""
    assert wfg.model_gate_passes(0.9, 0.05, 1, significance_level=0.05) is False  # noqa: magic-number


def test_model_gate_std_zero_passa_se_media_acima_de_0_5() -> None:
    """Dispersão zero com >=2 folds -- todos os folds deram o mesmo AUC;
    teste-t degenera (divisão por zero), decide direto pela média."""
    assert wfg.model_gate_passes(0.6, 0.0, 3, significance_level=0.05) is True  # noqa: magic-number


def test_model_gate_std_zero_falha_se_media_igual_ou_abaixo_de_0_5() -> None:
    assert wfg.model_gate_passes(0.5, 0.0, 3, significance_level=0.05) is False  # noqa: magic-number
    assert wfg.model_gate_passes(0.45, 0.0, 3, significance_level=0.05) is False  # noqa: magic-number


def test_model_gate_conferido_a_mao_contra_scipy_t_ppf() -> None:
    """t = (mean-0,5)/(std/sqrt(n)); passa sse t > t_critico(df=n-1,
    1-alpha) -- reproduz a fórmula de fora pra bater com a implementação."""
    auc_mean, auc_std, n = 0.65, 0.10, 8  # noqa: magic-number
    alpha = 0.05
    t_stat = (auc_mean - 0.5) / (auc_std / math.sqrt(n))
    t_crit = float(student_t.ppf(1.0 - alpha, df=n - 1))
    assert t_stat > t_crit  # pré-condição do teste: este caso deve passar
    assert wfg.model_gate_passes(auc_mean, auc_std, n, significance_level=alpha) is True


def test_model_gate_conferido_a_mao_caso_que_deve_falhar() -> None:
    """Mesmo desvio-padrão/n do teste anterior, média menor -- t cai
    abaixo do crítico, deve falhar."""
    auc_mean, auc_std, n = 0.53, 0.10, 8  # noqa: magic-number
    alpha = 0.05
    t_stat = (auc_mean - 0.5) / (auc_std / math.sqrt(n))
    t_crit = float(student_t.ppf(1.0 - alpha, df=n - 1))
    assert t_stat < t_crit  # pré-condição do teste: este caso deve falhar
    assert wfg.model_gate_passes(auc_mean, auc_std, n, significance_level=alpha) is False


def test_model_gate_significance_level_maior_facilita_passagem() -> None:
    """Mesmo mean/std/n -- alpha maior (teste menos exigente) tem t_crit
    menor, então um caso que falha a 0,01 pode passar a 0,20."""
    auc_mean, auc_std, n = 0.60, 0.15, 6  # noqa: magic-number
    assert wfg.model_gate_passes(auc_mean, auc_std, n, significance_level=0.01) is False  # noqa: magic-number
    assert wfg.model_gate_passes(auc_mean, auc_std, n, significance_level=0.20) is True  # noqa: magic-number


# ============================================================================
# alpha_gate_passes -- > min_edge_bps (comparação ESTRITA, mesma
# convenção de edge_gate_pass sobre CPCV) -- inalterado nesta correção
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


def _auc_stat(auc: float, *, std: float, n: int) -> dict[str, float]:
    return {"n": float(n), "mean": auc, "median": auc, "std": std, "min": auc, "max": auc}


def _stability_result(
    auc_long: float,
    auc_short: float,
    *,
    std_long: float,
    n_long: int,
    std_short: float,
    n_short: int,
) -> sm.StabilityMatrixResult:
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
                "roc_auc": _auc_stat(auc_long, std=std_long, n=n_long),
                "log_loss": _nan_stat(),
                "q10_minus_q1_bps": _nan_stat(),
            },
            "short": {
                "ic_spearman_pooled": _nan_stat(),
                "roc_auc": _auc_stat(auc_short, std=std_short, n=n_short),
                "log_loss": _nan_stat(),
                "q10_minus_q1_bps": _nan_stat(),
            },
        },
        top_feature_frequency_by_side={"long": {}, "short": {}},
        top_shap_feature_frequency_by_side={"long": {}, "short": {}},
        gain_shap_agreement_rate_by_side={"long": float("nan"), "short": float("nan")},
    )


def _walk_forward_payload(
    n_folds_total: int, n_folds_usados: int, edge_bps_mean: float
) -> dict[str, Any]:
    return {
        "n_folds_total": n_folds_total,
        "n_folds_usados": n_folds_usados,
        "aggregate": {"mean": {"sharpe": 0.0, "edge_bps": edge_bps_mean, "win_rate": 0.5}},  # noqa: magic-number
    }


def test_evaluate_gates_composicao_real_conferida_a_mao() -> None:
    """10/12 folds usados (>= piso 10 -- Data passa), edge_bps médio=5,0
    (> 0,0 -> Alpha passa), long: AUC=0,65 std=0,10 n=8 (teste-t passa a
    alpha=0,05), short: AUC=0,52 std=0,10 n=8 (teste-t falha)."""
    payload = _walk_forward_payload(12, 10, 5.0)  # noqa: magic-number
    stability = _stability_result(
        auc_long=0.65, std_long=0.10, n_long=8, auc_short=0.52, std_short=0.10, n_short=8  # noqa: magic-number
    )

    verdict = wfg.evaluate_gates(
        payload,
        stability,
        data_min_folds_usados=10,  # noqa: magic-number
        model_significance_level=0.05,
        alpha_min_edge_bps=0.0,
    )

    assert verdict.combo == "BTCUSDT/R2"
    assert verdict.variant == "camada1"
    assert verdict.frac_folds_usados == pytest.approx(10.0 / 12.0)  # noqa: magic-number
    assert verdict.data_gate_pass is True
    assert verdict.alpha_gate_pass is True
    assert verdict.model_gate_pass_by_side == {"long": True, "short": False}
    assert verdict.auc_mean_by_side["long"] == pytest.approx(0.65)  # noqa: magic-number
    assert verdict.auc_std_by_side["long"] == pytest.approx(0.10)  # noqa: magic-number
    assert verdict.n_folds_auc_by_side["long"] == 8  # noqa: magic-number


def test_evaluate_gates_zero_folds_totais_frac_nan_data_gate_falha() -> None:
    payload = _walk_forward_payload(0, 0, float("nan"))
    stability = _stability_result(
        auc_long=float("nan"), std_long=float("nan"), n_long=0,
        auc_short=float("nan"), std_short=float("nan"), n_short=0,
    )

    verdict = wfg.evaluate_gates(
        payload,
        stability,
        data_min_folds_usados=10,  # noqa: magic-number
        model_significance_level=0.05,
        alpha_min_edge_bps=0.0,
    )

    assert math.isnan(verdict.frac_folds_usados)
    assert verdict.data_gate_pass is False
