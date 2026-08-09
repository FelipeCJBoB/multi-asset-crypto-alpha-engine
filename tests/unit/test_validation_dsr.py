"""Testes de `src/validation/dsr.py` — DSR/PSR (§11.6), primeira
implementação neste repo. Propriedades matemáticas verificáveis
analiticamente (monotonicidade, simetria, casos degenerados Normais) —
não há um exemplo numérico de referência do artigo memorizado com
confiança suficiente pra travar um teste de valor exato contra ele."""

from __future__ import annotations

import numpy as np
import pytest

from src.validation import dsr


def test_expected_max_sharpe_cresce_com_n_trials() -> None:
    """Mais trials -> maior o "melhor de N" esperado por acaso, pra
    sigma_sr fixo -- propriedade central do multiple-testing correction."""
    sr0_10 = dsr.expected_max_sharpe_under_n_trials(10, sigma_sr=1.0)
    sr0_45 = dsr.expected_max_sharpe_under_n_trials(45, sigma_sr=1.0)
    sr0_1000 = dsr.expected_max_sharpe_under_n_trials(1000, sigma_sr=1.0)
    assert 0 < sr0_10 < sr0_45 < sr0_1000


def test_expected_max_sharpe_escala_linear_em_sigma() -> None:
    sr0_a = dsr.expected_max_sharpe_under_n_trials(45, sigma_sr=1.0)
    sr0_b = dsr.expected_max_sharpe_under_n_trials(45, sigma_sr=2.0)
    assert sr0_b == pytest.approx(2.0 * sr0_a, rel=1e-9)


def test_expected_max_sharpe_rejeita_n_trials_menor_que_2() -> None:
    with pytest.raises(ValueError):
        dsr.expected_max_sharpe_under_n_trials(1, sigma_sr=1.0)


def test_sharpe_se_normal_reduz_a_formula_classica() -> None:
    """skew=0, excess_kurtosis=0 (Normal) -> SE(SR) = sqrt(1/(n-1))."""
    se = dsr.sharpe_ratio_standard_error(sr=0.5, n_obs=101, skewness=0.0, excess_kurtosis=0.0)
    assert se == pytest.approx((1.0 / 100.0) ** 0.5, rel=1e-9)


def test_psr_e_meio_quando_observado_igual_benchmark() -> None:
    psr = dsr.probabilistic_sharpe_ratio(
        sr_observed=0.8, sr_benchmark=0.8, n_obs=500, skewness=0.0, excess_kurtosis=0.0
    )
    assert psr == pytest.approx(0.5, abs=1e-9)


def test_psr_alto_quando_observado_muito_acima_do_benchmark() -> None:
    psr = dsr.probabilistic_sharpe_ratio(
        sr_observed=2.0, sr_benchmark=0.1, n_obs=1000, skewness=0.0, excess_kurtosis=0.0
    )
    assert psr > 0.99


def test_compute_dsr_recupera_sharpe_de_retornos_sinteticos() -> None:
    rng = np.random.default_rng(7)
    true_sr_per_trade = 0.05
    returns = rng.normal(loc=true_sr_per_trade, scale=1.0, size=5000)
    result = dsr.compute_dsr(returns, n_trials=45, trades_per_year=650.0)
    assert result.sr_per_trade == pytest.approx(true_sr_per_trade, abs=0.02)
    assert result.n_obs == 5000
    assert 0.0 <= result.dsr <= 1.0


def test_compute_dsr_diminui_com_mais_trials_mesmo_sr() -> None:
    """Mesma amostra, N_lifetime maior -> DSR menor (mais ceticismo de
    multiplas comparacoes) -- propriedade central do DSR vs PSR simples."""
    rng = np.random.default_rng(11)
    returns = rng.normal(loc=0.05, scale=1.0, size=3000)
    dsr_low_n = dsr.compute_dsr(returns, n_trials=2, trades_per_year=650.0)
    dsr_high_n = dsr.compute_dsr(returns, n_trials=500, trades_per_year=650.0)
    assert dsr_high_n.dsr < dsr_low_n.dsr
    assert dsr_high_n.sr0_per_trade > dsr_low_n.sr0_per_trade


def test_compute_dsr_rejeita_amostra_pequena_demais() -> None:
    with pytest.raises(ValueError):
        dsr.compute_dsr(np.array([0.1, 0.2, 0.3]), n_trials=10, trades_per_year=100.0)


def test_sharpe_difference_bootstrap_series_identicas_da_diff_zero() -> None:
    rng = np.random.default_rng(3)
    x = rng.normal(loc=0.01, scale=1.0, size=400)
    result = dsr.sharpe_difference_block_bootstrap(
        x, x.copy(), n_boot=300, block_size=10, seed=1
    )
    assert result["observed_diff"] == pytest.approx(0.0, abs=1e-9)
    assert result["p_value_two_sided"] == pytest.approx(1.0, abs=1e-9)


def test_sharpe_difference_bootstrap_detecta_diferenca_grande() -> None:
    rng = np.random.default_rng(5)
    a = rng.normal(loc=0.5, scale=1.0, size=500)  # SR alto
    b = rng.normal(loc=-0.5, scale=1.0, size=500)  # SR baixo/negativo
    result = dsr.sharpe_difference_block_bootstrap(a, b, n_boot=500, block_size=10, seed=2)
    assert result["observed_diff"] > 0.5
    assert result["p_value_two_sided"] < 0.05
    assert result["ci95_low"] > 0.0


def test_sharpe_difference_bootstrap_exige_mesmo_comprimento() -> None:
    with pytest.raises(ValueError):
        dsr.sharpe_difference_block_bootstrap(
            np.zeros(10), np.zeros(20), n_boot=10, block_size=2, seed=1
        )
