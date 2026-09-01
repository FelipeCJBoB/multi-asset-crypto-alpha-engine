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


def test_model_gate_std_zero_sempre_falha_mesmo_com_media_acima_de_0_5() -> None:
    """Correção 2026-08-31, rodada 2 (achado de audit_engineering) --
    dispersão zero com >=2 folds (teste-t degenera, divisão por zero)
    NÃO decide mais pela média sozinho -- diverge da convenção do
    módulo-irmão citado como espelho (`score_quality._ic_dispersion_
    stats` devolve NaN no mesmo caso). Ausência de teste válido nunca é
    aprovação por omissão, mesmo com média>0,5."""
    assert wfg.model_gate_passes(0.6, 0.0, 3, significance_level=0.05) is False  # noqa: magic-number
    assert wfg.model_gate_passes(0.5, 0.0, 3, significance_level=0.05) is False  # noqa: magic-number
    assert wfg.model_gate_passes(0.45, 0.0, 3, significance_level=0.05) is False  # noqa: magic-number


def test_model_gate_p_value_std_zero_e_nan_nao_zero_nem_um() -> None:
    """`model_gate_p_value` devolve NaN (não 0,0/1,0 inventado) quando
    std=0 -- sem teste válido, não há p-valor a reportar, mesmo achado
    da correção acima."""
    assert math.isnan(wfg.model_gate_p_value(0.6, 0.0, 3))  # noqa: magic-number
    assert math.isnan(wfg.model_gate_p_value(0.45, 0.0, 3))  # noqa: magic-number


def test_model_gate_p_value_menos_de_2_folds_e_nan() -> None:
    assert math.isnan(wfg.model_gate_p_value(0.9, 0.05, 1))  # noqa: magic-number


def test_model_gate_p_value_conferido_a_mao_contra_scipy_t_sf() -> None:
    """p = P(T > t_stat) unicaudal (H1: AUC>0,5), via `scipy.stats.t.sf`
    -- mesma estatística de `model_gate_passes`, exposta como p-valor em
    vez de booleano."""
    auc_mean, auc_std, n = 0.65, 0.10, 8  # noqa: magic-number
    t_stat = (auc_mean - 0.5) / (auc_std / math.sqrt(n))
    expected_p = float(student_t.sf(t_stat, df=n - 1))
    assert wfg.model_gate_p_value(auc_mean, auc_std, n) == pytest.approx(expected_p)
    # p < alpha <=> model_gate_passes -- mesma fonte de verdade
    assert (expected_p < 0.05) == wfg.model_gate_passes(  # noqa: magic-number
        auc_mean, auc_std, n, significance_level=0.05
    )


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
# alpha_gate_passes -- teste-t unicaudal (H0: edge_bps_medio<=min_edge_bps),
# não mais comparação de ponto estimado sem barra de erro (AG-400,
# correção 2026-08-31, achado N1 da auditoria adversarial externa)
# ============================================================================


def test_alpha_gate_nan_edge_bps_mean_sempre_falha() -> None:
    assert wfg.alpha_gate_passes(
        float("nan"), 2.0, 10, min_edge_bps=0.0, significance_level=0.05  # noqa: magic-number
    ) is False


def test_alpha_gate_nan_edge_bps_std_sempre_falha() -> None:
    assert wfg.alpha_gate_passes(
        5.0, float("nan"), 10, min_edge_bps=0.0, significance_level=0.05  # noqa: magic-number
    ) is False


def test_alpha_gate_menos_de_2_folds_sempre_falha() -> None:
    assert wfg.alpha_gate_passes(
        5.0, 2.0, 1, min_edge_bps=0.0, significance_level=0.05  # noqa: magic-number
    ) is False


def test_alpha_gate_std_zero_sempre_falha_mesmo_com_media_acima_do_piso() -> None:
    """Mesma convenção de `model_gate_passes` no mesmo caso degenerado --
    dispersão zero nunca decide pela média sozinha, mesmo com
    `edge_bps_mean > min_edge_bps`."""
    assert wfg.alpha_gate_passes(
        5.0, 0.0, 5, min_edge_bps=0.0, significance_level=0.05  # noqa: magic-number
    ) is False


def test_alpha_gate_p_value_std_zero_e_nan_nao_zero_nem_um() -> None:
    assert math.isnan(wfg.alpha_gate_p_value(5.0, 0.0, 5, min_edge_bps=0.0))  # noqa: magic-number


def test_alpha_gate_p_value_conferido_a_mao_contra_scipy_t_sf() -> None:
    edge_mean, edge_std, n = 8.0, 3.0, 10  # noqa: magic-number
    t_stat = (edge_mean - 0.0) / (edge_std / math.sqrt(n))
    expected_p = float(student_t.sf(t_stat, df=n - 1))
    assert wfg.alpha_gate_p_value(edge_mean, edge_std, n, min_edge_bps=0.0) == pytest.approx(
        expected_p
    )
    assert (expected_p < 0.05) == wfg.alpha_gate_passes(  # noqa: magic-number
        edge_mean, edge_std, n, min_edge_bps=0.0, significance_level=0.05
    )


def test_alpha_gate_conferido_a_mao_caso_que_deve_passar() -> None:
    """Edge grande, dispersão pequena, n razoável -- t bem acima do
    crítico, deve passar."""
    edge_mean, edge_std, n = 8.0, 3.0, 10  # noqa: magic-number
    alpha = 0.05
    t_stat = (edge_mean - 0.0) / (edge_std / math.sqrt(n))
    t_crit = float(student_t.ppf(1.0 - alpha, df=n - 1))
    assert t_stat > t_crit
    assert (
        wfg.alpha_gate_passes(edge_mean, edge_std, n, min_edge_bps=0.0, significance_level=alpha)
        is True
    )


def test_alpha_gate_conferido_a_mao_caso_que_deve_falhar_apesar_de_media_positiva() -> None:
    """AG-400, o achado central: média positiva, mas dispersão grande
    demais pro n disponível -- passava no critério antigo, falha no
    teste-t. Mesmos números do achado real (`BTCUSDT/R2` Camada0: mean
    ~1,35, std~10,3, n=7 -> t~0,35, não significativo)."""
    edge_mean, edge_std, n = 1.348, 10.303, 7  # noqa: magic-number
    alpha = 0.05
    t_stat = (edge_mean - 0.0) / (edge_std / math.sqrt(n))
    t_crit = float(student_t.ppf(1.0 - alpha, df=n - 1))
    assert t_stat < t_crit
    assert edge_mean > 0.0  # o criterio ANTIGO (ponto estimado) teria aprovado
    assert (
        wfg.alpha_gate_passes(edge_mean, edge_std, n, min_edge_bps=0.0, significance_level=alpha)
        is False
    )


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
    n_folds_total: int, n_folds_usados: int, edge_bps_mean: float, edge_bps_std: float = 2.0  # noqa: magic-number -- default de teste, sobrescrito quando o caso precisa de um valor específico
) -> dict[str, Any]:
    return {
        "n_folds_total": n_folds_total,
        "n_folds_usados": n_folds_usados,
        "aggregate": {
            "mean": {"sharpe": 0.0, "edge_bps": edge_bps_mean, "win_rate": 0.5},  # noqa: magic-number
            "std": {"sharpe": 0.0, "edge_bps": edge_bps_std, "win_rate": 0.0},
        },
    }


def test_evaluate_gates_composicao_real_conferida_a_mao() -> None:
    """10/12 folds usados (>= piso 10 -- Data passa); edge_bps médio=5,0,
    std=2,0, n=10 (teste-t: t~7,9, passa a alpha=0,05 -> Alpha passa);
    long: AUC=0,65 std=0,10 n=8 (teste-t passa a alpha=0,05), short:
    AUC=0,52 std=0,10 n=8 (teste-t falha)."""
    payload = _walk_forward_payload(12, 10, 5.0, 2.0)  # noqa: magic-number
    stability = _stability_result(
        auc_long=0.65, std_long=0.10, n_long=8, auc_short=0.52, std_short=0.10, n_short=8  # noqa: magic-number
    )

    verdict = wfg.evaluate_gates(
        payload,
        stability,
        data_min_folds_usados=10,  # noqa: magic-number
        significance_level=0.05,
        alpha_min_edge_bps=0.0,
    )

    assert verdict.combo == "BTCUSDT/R2"
    assert verdict.variant == "camada1"
    assert verdict.frac_folds_usados == pytest.approx(10.0 / 12.0)  # noqa: magic-number
    assert verdict.data_gate_pass is True
    assert verdict.alpha_gate_pass is True
    assert verdict.edge_bps_std == pytest.approx(2.0)  # noqa: magic-number
    assert verdict.edge_bps_p_value < 0.05  # noqa: magic-number
    assert verdict.model_gate_pass_by_side == {"long": True, "short": False}
    assert verdict.auc_mean_by_side["long"] == pytest.approx(0.65)  # noqa: magic-number
    assert verdict.auc_std_by_side["long"] == pytest.approx(0.10)  # noqa: magic-number
    assert verdict.n_folds_auc_by_side["long"] == 8  # noqa: magic-number


def test_evaluate_gates_edge_positivo_mas_disperso_demais_falha_alpha_gate() -> None:
    """AG-400 -- o achado central reproduzido em nível de `evaluate_gates`:
    edge_bps médio positivo (o critério ANTIGO teria aprovado), mas
    dispersão grande demais pro `n` disponível (mesmos números do achado
    real, `BTCUSDT/R2` Camada0) -- Alpha gate falha sob o teste-t."""
    payload = _walk_forward_payload(19, 7, 1.348, 10.303)  # noqa: magic-number
    stability = _stability_result(
        auc_long=0.5, std_long=0.1, n_long=4, auc_short=0.5, std_short=0.1, n_short=4  # noqa: magic-number
    )

    verdict = wfg.evaluate_gates(
        payload,
        stability,
        data_min_folds_usados=10,  # noqa: magic-number
        significance_level=0.05,
        alpha_min_edge_bps=0.0,
    )

    assert verdict.edge_bps_mean > 0.0  # criterio antigo teria aprovado
    assert verdict.alpha_gate_pass is False  # teste-t reprova


def test_evaluate_gates_zero_folds_totais_frac_nan_data_gate_falha() -> None:
    payload = _walk_forward_payload(0, 0, float("nan"), float("nan"))
    stability = _stability_result(
        auc_long=float("nan"), std_long=float("nan"), n_long=0,
        auc_short=float("nan"), std_short=float("nan"), n_short=0,
    )

    verdict = wfg.evaluate_gates(
        payload,
        stability,
        data_min_folds_usados=10,  # noqa: magic-number
        significance_level=0.05,
        alpha_min_edge_bps=0.0,
    )

    assert math.isnan(verdict.frac_folds_usados)
    assert verdict.data_gate_pass is False


def test_evaluate_gates_std_none_do_json_nao_quebra_math_isfinite() -> None:
    """Achado real (`scripts/evaluate_walk_forward_gates.py` contra os
    artefatos canônicos, 2026-08-31): `_aggregate_stats` devolve `NaN`
    com `n<2` folds, mas `orjson`/`json.load` grava/lê isso como `null`
    -- `None` no payload real (`SOLUSDT/R2`, 1 fold usável). `math.
    isfinite(None)` levanta `TypeError` sem o guard explícito."""
    payload: dict[str, Any] = {
        "n_folds_total": 12,  # noqa: magic-number
        "n_folds_usados": 1,
        "aggregate": {
            "mean": {"sharpe": None, "edge_bps": None, "win_rate": None},
            "std": {"sharpe": None, "edge_bps": None, "win_rate": None},
        },
    }
    stability = _stability_result(
        auc_long=float("nan"), std_long=float("nan"), n_long=0,
        auc_short=float("nan"), std_short=float("nan"), n_short=0,
    )

    verdict = wfg.evaluate_gates(
        payload,
        stability,
        data_min_folds_usados=10,  # noqa: magic-number
        significance_level=0.05,
        alpha_min_edge_bps=0.0,
    )

    assert math.isnan(verdict.edge_bps_mean)
    assert math.isnan(verdict.edge_bps_std)
    assert math.isnan(verdict.edge_bps_p_value)
    assert verdict.alpha_gate_pass is False


# ============================================================================
# apply_fdr_to_model_gates -- correção de múltiplas comparações sobre um
# LOTE de GateVerdict (correção 2026-08-31, rodada 2, achado de
# audit_engineering: p-valor não exposto, sem correção de FDR)
# ============================================================================


def _minimal_gate_verdict(*, combo: str, p_long: float, p_short: float) -> wfg.GateVerdict:
    return wfg.GateVerdict(
        combo=combo,
        variant="camada1",
        n_folds_total=12,  # noqa: magic-number
        n_folds_usados=10,  # noqa: magic-number
        frac_folds_usados=10.0 / 12.0,  # noqa: magic-number
        data_gate_pass=True,
        edge_bps_mean=5.0,  # noqa: magic-number
        edge_bps_std=2.0,  # noqa: magic-number
        edge_bps_p_value=0.01,  # noqa: magic-number
        alpha_gate_pass=True,
        auc_mean_by_side={"long": 0.6, "short": 0.6},  # noqa: magic-number
        auc_std_by_side={"long": 0.1, "short": 0.1},  # noqa: magic-number
        n_folds_auc_by_side={"long": 10, "short": 10},  # noqa: magic-number
        auc_p_value_by_side={"long": p_long, "short": p_short},
        model_gate_pass_by_side={"long": p_long < 0.05, "short": p_short < 0.05},  # noqa: magic-number
    )


def test_apply_fdr_to_model_gates_exclui_nan_da_familia() -> None:
    """Célula sem teste válido (`p_value=NaN`, ex. `std==0,0`/`n_folds<2`)
    nunca entra na família FDR -- não é `p=1,0` inventado, é ausente do
    conjunto de hipóteses simultâneas testado."""
    verdicts = [
        _minimal_gate_verdict(combo="BTCUSDT/R2", p_long=0.001, p_short=0.04),
        _minimal_gate_verdict(combo="SOLUSDT/R2", p_long=0.03, p_short=float("nan")),
        _minimal_gate_verdict(combo="XRPUSDT/R3", p_long=0.5, p_short=0.5),
    ]

    results = wfg.apply_fdr_to_model_gates(verdicts, significance_level=0.05)

    assert "SOLUSDT/R2/camada1/short" not in results
    assert set(results.keys()) == {
        "BTCUSDT/R2/camada1/long",
        "BTCUSDT/R2/camada1/short",
        "SOLUSDT/R2/camada1/long",
        "XRPUSDT/R3/camada1/long",
        "XRPUSDT/R3/camada1/short",
    }


def test_apply_fdr_to_model_gates_p_valor_bruto_e_bilateral_2x_o_unicaudal() -> None:
    """`apply_fdr_correction` espera p-valor bilateral já convertido pelo
    chamador (docstring dela) -- `model_gate_p_value` é unicaudal, então
    `apply_fdr_to_model_gates` converte via `min(2*p, 1.0)` antes de
    passar adiante."""
    verdicts = [_minimal_gate_verdict(combo="BTCUSDT/R2", p_long=0.001, p_short=0.4)]  # noqa: magic-number

    results = wfg.apply_fdr_to_model_gates(verdicts, significance_level=0.05)

    assert results["BTCUSDT/R2/camada1/long"].p_value_raw == pytest.approx(0.002)  # noqa: magic-number
    assert results["BTCUSDT/R2/camada1/short"].p_value_raw == pytest.approx(0.8)  # noqa: magic-number


def test_apply_fdr_to_model_gates_lista_vazia_devolve_dict_vazio() -> None:
    assert wfg.apply_fdr_to_model_gates([], significance_level=0.05) == {}
