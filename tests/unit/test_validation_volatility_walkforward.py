"""Testes de `src/validation/volatility_walkforward.py` -- PRD_V4_1.md
§3.2 M1. Splits ancorados por trimestre civil, alvo de avaliação (r²
da próxima barra), métricas (QLIKE/MSE/viés/Mincer-Zarnowitz) e os dois
checks de validação do "vencedor" (taxa de vitória por fold,
Diebold-Mariano)."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pytest

from src.validation import volatility_walkforward as vwf

# ============================================================================
# generate_anchored_walk_forward_splits
# ============================================================================


def _daily_open_time_ms(start: str, n_days: int) -> np.ndarray:
    start_dt = datetime.fromisoformat(start).replace(tzinfo=UTC)
    start_ms = int(start_dt.timestamp() * 1000)
    day_ms = 86_400_000
    return np.array([start_ms + i * day_ms for i in range(n_days)], dtype=np.int64)


def test_splits_ancorado_treino_sempre_comeca_no_indice_0() -> None:
    # 2021-01-01 .. ~2024-12-31 (2020 dias, ~5.5 anos) -- treino inicial 2
    # anos cobre 2021-2022, primeiro teste é Q1 2023.
    open_time = _daily_open_time_ms("2021-01-01", 1460)
    splits = vwf.generate_anchored_walk_forward_splits(open_time, initial_train_years=2)
    assert len(splits) > 0
    for s in splits:
        assert s.train_end_idx > 0
        assert s.test_start_idx == s.train_end_idx
        assert s.test_end_idx > s.test_start_idx


def test_splits_expandem_nunca_encolhem() -> None:
    open_time = _daily_open_time_ms("2021-01-01", 1460)
    splits = vwf.generate_anchored_walk_forward_splits(open_time, initial_train_years=2)
    train_ends = [s.train_end_idx for s in splits]
    assert train_ends == sorted(train_ends)
    assert len(set(train_ends)) == len(train_ends)  # estritamente crescente


def test_splits_fold_ids_sequenciais_a_partir_de_zero() -> None:
    open_time = _daily_open_time_ms("2021-01-01", 1460)
    splits = vwf.generate_anchored_walk_forward_splits(open_time, initial_train_years=2)
    assert [s.fold_id for s in splits] == list(range(len(splits)))


def test_splits_dado_insuficiente_para_treino_inicial_retorna_vazio() -> None:
    open_time = _daily_open_time_ms("2021-01-01", 200)  # ~6.5 meses, menos que 2 anos
    splits = vwf.generate_anchored_walk_forward_splits(open_time, initial_train_years=2)
    assert splits == ()


def test_splits_serie_vazia_retorna_vazio() -> None:
    splits = vwf.generate_anchored_walk_forward_splits(
        np.array([], dtype=np.int64), initial_train_years=2
    )
    assert splits == ()


def test_splits_cobre_toda_a_serie_ate_a_ultima_barra() -> None:
    open_time = _daily_open_time_ms("2021-01-01", 1460)
    splits = vwf.generate_anchored_walk_forward_splits(open_time, initial_train_years=2)
    assert splits[-1].test_end_idx == open_time.shape[0]


# ============================================================================
# next_bar_realized_variance
# ============================================================================


def test_next_bar_realized_variance_valor_conhecido() -> None:
    close = np.array([100.0, 110.0, 100.0])
    out = vwf.next_bar_realized_variance(close)
    expected_0 = np.log(110.0 / 100.0) ** 2
    expected_1 = np.log(100.0 / 110.0) ** 2
    assert out[0] == pytest.approx(expected_0)
    assert out[1] == pytest.approx(expected_1)
    assert np.isnan(out[2])  # última barra não tem t+1


def test_next_bar_realized_variance_preco_constante_da_zero() -> None:
    close = np.full(10, 100.0)
    out = vwf.next_bar_realized_variance(close)
    assert np.allclose(out[:-1], 0.0)


# ============================================================================
# qlike_loss / mse_loss / bias
# ============================================================================


def test_qlike_loss_forecast_igual_realizado_da_zero() -> None:
    forecast = np.array([0.01, 0.02, 0.05])
    realized = forecast.copy()
    out = vwf.qlike_loss(forecast, realized)
    assert np.allclose(out, 0.0, atol=1e-12)


def test_qlike_loss_forecast_nao_positivo_vira_nan() -> None:
    forecast = np.array([0.0, -0.01, 0.02])
    realized = np.array([0.01, 0.01, 0.01])
    out = vwf.qlike_loss(forecast, realized)
    assert np.isnan(out[0])
    assert np.isnan(out[1])
    assert not np.isnan(out[2])


def test_qlike_loss_valor_conhecido() -> None:
    # QLIKE(f, r) = r/f - ln(r/f) - 1; f=0.02, r=0.04 -> ratio=2
    out = vwf.qlike_loss(np.array([0.02]), np.array([0.04]))
    expected = 2.0 - np.log(2.0) - 1.0
    assert out[0] == pytest.approx(expected)


def test_mse_loss_valor_conhecido() -> None:
    out = vwf.mse_loss(np.array([0.02, 0.05]), np.array([0.03, 0.05]))
    assert out[0] == pytest.approx(0.0001)
    assert out[1] == pytest.approx(0.0)


def test_bias_positivo_quando_forecast_superestima() -> None:
    forecast = np.array([0.03, 0.03, 0.03])
    realized = np.array([0.01, 0.01, 0.01])
    assert vwf.bias(forecast, realized) == pytest.approx(0.02)


def test_bias_sem_observacao_valida_da_nan() -> None:
    forecast = np.array([np.nan, np.nan])
    realized = np.array([0.01, 0.02])
    assert np.isnan(vwf.bias(forecast, realized))


# ============================================================================
# mincer_zarnowitz
# ============================================================================


def test_mincer_zarnowitz_forecast_perfeito_intercept_0_slope_1() -> None:
    rng = np.random.default_rng(3)
    forecast = rng.uniform(0.01, 0.05, 100)
    realized = forecast.copy()  # forecast == realizado sempre
    result = vwf.mincer_zarnowitz(forecast, realized)
    assert result.intercept == pytest.approx(0.0, abs=1e-9)
    assert result.slope == pytest.approx(1.0, abs=1e-9)
    assert result.r_squared == pytest.approx(1.0, abs=1e-9)
    assert result.n == 100


def test_mincer_zarnowitz_forecast_constante_e_degenerado() -> None:
    forecast = np.full(20, 0.02)  # sem variância -> sxx=0
    realized = np.linspace(0.01, 0.05, 20)
    result = vwf.mincer_zarnowitz(forecast, realized)
    assert np.isnan(result.slope)
    assert np.isnan(result.intercept)


def test_mincer_zarnowitz_ignora_nan() -> None:
    forecast = np.array([0.01, 0.02, np.nan, 0.03])
    realized = np.array([0.01, 0.02, 0.5, 0.03])
    result = vwf.mincer_zarnowitz(forecast, realized)
    assert result.n == 3


# ============================================================================
# fold_win_rate / diebold_mariano
# ============================================================================


def test_fold_win_rate_candidato_vence_todos() -> None:
    candidate = np.array([0.1, 0.2, 0.05])
    baseline = np.array([0.3, 0.4, 0.3])
    assert vwf.fold_win_rate(candidate, baseline) == pytest.approx(1.0)


def test_fold_win_rate_candidato_perde_todos() -> None:
    candidate = np.array([0.5, 0.6])
    baseline = np.array([0.1, 0.2])
    assert vwf.fold_win_rate(candidate, baseline) == pytest.approx(0.0)


def test_fold_win_rate_ignora_nan() -> None:
    candidate = np.array([0.1, np.nan, 0.05])
    baseline = np.array([0.3, 0.4, 0.3])
    assert vwf.fold_win_rate(candidate, baseline) == pytest.approx(1.0)


def test_diebold_mariano_sem_diferenca_estatistica_zero() -> None:
    loss_candidate = np.array([0.1, 0.1, 0.1, 0.1])
    loss_baseline = np.array([0.1, 0.1, 0.1, 0.1])
    result = vwf.diebold_mariano(loss_candidate, loss_baseline)
    assert result.mean_loss_diff == pytest.approx(0.0)
    # std_d == 0 -> dm_stat/p_value indefinidos (retorna NaN, não erro)
    assert np.isnan(result.dm_stat)


def test_diebold_mariano_candidato_consistentemente_melhor() -> None:
    rng = np.random.default_rng(1)
    loss_candidate = 0.05 + rng.normal(0, 0.001, 200)
    loss_baseline = 0.10 + rng.normal(0, 0.001, 200)
    result = vwf.diebold_mariano(loss_candidate, loss_baseline)
    assert result.mean_loss_diff < 0  # candidato tem perda menor
    assert result.p_value < 0.01  # diferença grande e consistente -> significativa
    assert result.n == 200


def test_diebold_mariano_poucos_pontos_da_nan() -> None:
    result = vwf.diebold_mariano(np.array([0.1]), np.array([0.2]))
    assert np.isnan(result.dm_stat)
    assert result.n == 1


def test_diebold_mariano_ignora_bar_com_inf_de_um_lado_so() -> None:
    # candidate tem inf isolado num bar que o baseline NAO tem -- filtro
    # antigo (~np.isnan(d) DEPOIS de subtrair) deixaria "finite - inf =
    # -inf" passar direto pro mean_d/std_d, corrompendo o teste inteiro
    # com um unico bar degenerado. O filtro correto (isfinite dos dois
    # lados ANTES de subtrair) exclui esse bar e usa só os pares
    # genuinamente comparaveis.
    # valores com variância real entre pares (não todos -0.05 idênticos --
    # isso acionaria a guarda separada std_d==0.0, não o filtro isfinite
    # que este teste quer exercitar)
    loss_candidate = np.array([0.04, 0.06, np.inf, 0.05, 0.045])
    loss_baseline = np.array([0.10, 0.10, 0.10, 0.10, 0.10])
    result = vwf.diebold_mariano(loss_candidate, loss_baseline)
    assert result.n == 4  # o bar com inf foi excluido, não virou -inf
    assert np.isfinite(result.dm_stat)
    assert np.isfinite(result.mean_loss_diff)


def test_diebold_mariano_ambos_inf_no_mesmo_bar_tambem_e_excluido() -> None:
    # inf-inf ja daria NaN mesmo no filtro antigo -- caso de controle,
    # confirma que o comportamento correto (excluir) se mantém.
    loss_candidate = np.array([0.04, np.inf, 0.05, 0.045])
    loss_baseline = np.array([0.10, np.inf, 0.10, 0.10])
    result = vwf.diebold_mariano(loss_candidate, loss_baseline)
    assert result.n == 3
    assert np.isfinite(result.dm_stat)
