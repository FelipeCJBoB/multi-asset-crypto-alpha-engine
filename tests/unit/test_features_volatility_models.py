"""Testes de `src/features/volatility_models.py` -- HAR-RV (Corsi 2009),
PRD_V4_1.md §3.2 M1. Eixos: causalidade dos regressores (dia/semana/mês
nunca usam `realized_var[t]` pra prever `realized_var[t]`), fit/predict
end-to-end sobre série sintética conhecida, dado insuficiente, e forecast
não-positivo virando NaN em vez de variância negativa silenciosa."""

from __future__ import annotations

import numpy as np
import pytest

from src.features import volatility_models as vm


def test_rolling_mean_causal_janela_fechada_valor_conhecido() -> None:
    x = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    out = vm._rolling_mean_causal(x, 3)
    assert np.isnan(out[0])
    assert np.isnan(out[1])
    assert out[2] == pytest.approx(2.0)  # mean(1,2,3)
    assert out[3] == pytest.approx(3.0)  # mean(2,3,4)
    assert out[4] == pytest.approx(4.0)  # mean(3,4,5)


def test_har_components_nunca_usa_realized_var_no_proprio_indice() -> None:
    # Perturbar realized_var[t] não pode mudar day[t]/week[t]/month[t] --
    # só pode mudar componentes em índices > t (janelas futuras que
    # incluem t no lookback deslocado).
    rng = np.random.default_rng(5)
    n = 400
    realized_var = rng.uniform(0.0001, 0.001, n)
    bars_per_day = 4  # janelas pequenas (4/28/120) pra caber no n=400 do teste

    day_a, week_a, month_a = vm._har_components(realized_var, bars_per_day=bars_per_day)

    perturbed = realized_var.copy()
    t = 200
    perturbed[t] = 999.0  # valor absurdo, se vazasse pra day[t] o teste pegaria
    day_b, week_b, month_b = vm._har_components(perturbed, bars_per_day=bars_per_day)

    assert day_a[t] == pytest.approx(day_b[t])
    assert week_a[t] == pytest.approx(week_b[t])
    assert month_a[t] == pytest.approx(month_b[t])
    # índices > t DEVEM mudar (t entra no lookback deslocado deles)
    assert day_a[t + 1] != pytest.approx(day_b[t + 1])


def test_fit_har_rv_dado_insuficiente_retorna_none() -> None:
    realized_var = np.full(5, 0.0005)
    fit = vm.fit_har_rv(realized_var, bars_per_day=4, train_end_idx=5)
    assert fit is None


def test_fit_e_predict_har_rv_serie_constante_reproduz_o_valor() -> None:
    # realized_var constante -> day=week=month=constante uma vez a janela
    # fecha -> fit+predict devem reproduzir a mesma constante (regressores
    # perfeitamente colineares, mas qualquer solução OLS válida satisfaz
    # intercept + (beta_day+beta_week+beta_month)*c == c exatamente).
    n = 400
    bars_per_day = 4
    const = 0.0004
    realized_var = np.full(n, const)

    fit = vm.fit_har_rv(realized_var, bars_per_day=bars_per_day, train_end_idx=n)
    assert fit is not None
    assert fit.n_train > 0

    forecast = vm.predict_har_rv(fit, realized_var, bars_per_day=bars_per_day)
    tail = forecast[bars_per_day * 30 + 10 :]  # após a janela mensal fechar
    valid = tail[~np.isnan(tail)]
    assert valid.size > 0
    assert np.allclose(valid, const, rtol=1e-6)


def test_fit_har_rv_causal_treino_nao_ve_teste() -> None:
    # Ajuste sobre [0, train_end_idx) não pode mudar se dado ALÉM de
    # train_end_idx for alterado.
    rng = np.random.default_rng(9)
    n = 500
    bars_per_day = 4
    realized_var = rng.uniform(0.0001, 0.001, n)
    train_end_idx = 300

    fit_a = vm.fit_har_rv(realized_var, bars_per_day=bars_per_day, train_end_idx=train_end_idx)
    perturbed = realized_var.copy()
    perturbed[train_end_idx:] = 999.0  # todo o "futuro" (fora do treino) vira absurdo
    fit_b = vm.fit_har_rv(perturbed, bars_per_day=bars_per_day, train_end_idx=train_end_idx)

    assert fit_a is not None and fit_b is not None
    assert fit_a.intercept == pytest.approx(fit_b.intercept)
    assert fit_a.beta_day == pytest.approx(fit_b.beta_day)
    assert fit_a.beta_week == pytest.approx(fit_b.beta_week)
    assert fit_a.beta_month == pytest.approx(fit_b.beta_month)


def test_predict_har_rv_forecast_nao_positivo_vira_nan() -> None:
    fit = vm.HARRVFit(intercept=-1.0, beta_day=0.0, beta_week=0.0, beta_month=0.0, n_train=100)
    realized_var = np.full(200, 0.0005)
    forecast = vm.predict_har_rv(fit, realized_var, bars_per_day=4)
    valid_region = forecast[4 * 30 + 5 :]
    assert valid_region.size > 0
    assert np.all(np.isnan(valid_region))


# ============================================================================
# EGARCH(1,1) -- Nelson (1991), MLE
# ============================================================================


def _synthetic_log_return(n: int, *, seed: int, std: float = 0.01) -> np.ndarray:
    rng = np.random.default_rng(seed)
    out = np.full(n, np.nan, dtype=np.float64)
    out[1:] = rng.normal(0.0, std, n - 1)
    return out


def test_egarch_recursion_persistencia_zero_fica_constante_em_omega() -> None:
    # alpha=beta=gamma=0 -> next_lv = omega sempre, independente do
    # retorno -- caso trivial que isola a fórmula da recursão em si.
    log_return = _synthetic_log_return(50, seed=1)
    log_var = vm._egarch_log_var_recursion(
        log_return, omega=-9.0, alpha=0.0, beta=0.0, gamma=0.0, log_var_seed=-9.0
    )
    valid = log_var[~np.isnan(log_var)]
    assert valid.size > 0
    assert np.allclose(valid, -9.0)


def test_egarch_recursion_causal_perturbar_t_nao_muda_ate_t() -> None:
    log_return = _synthetic_log_return(60, seed=2)
    log_var_a = vm._egarch_log_var_recursion(
        log_return, omega=-8.0, alpha=0.2, beta=0.9, gamma=-0.05, log_var_seed=-8.0
    )
    perturbed = log_return.copy()
    t = 30
    perturbed[t] = 5.0  # retorno absurdo
    log_var_b = vm._egarch_log_var_recursion(
        perturbed, omega=-8.0, alpha=0.2, beta=0.9, gamma=-0.05, log_var_seed=-8.0
    )
    assert np.allclose(log_var_a[: t + 1], log_var_b[: t + 1], equal_nan=True)
    # log_var[t+1] usa log_return[t] -- DEVE mudar
    assert log_var_a[t + 1] != pytest.approx(log_var_b[t + 1])


def test_fit_egarch_dado_insuficiente_retorna_none() -> None:
    log_return = _synthetic_log_return(20, seed=3)
    fit = vm.fit_egarch(log_return, train_end_idx=20)
    assert fit is None


def test_fit_e_predict_egarch_ruido_branco_forecast_plausivel() -> None:
    # retorno gaussiano i.i.d. com variância conhecida -- EGARCH ajustado
    # deve prever algo na ordem de grandeza certa (não exige recuperar os
    # coeficientes exatos, MLE em amostra finita não faz isso).
    n = 1500
    true_std = 0.01
    log_return = _synthetic_log_return(n, seed=4, std=true_std)
    train_end_idx = 1200

    fit = vm.fit_egarch(log_return, train_end_idx=train_end_idx)
    assert fit is not None
    assert fit.n_train > 0

    forecast = vm.predict_egarch(fit, log_return)
    test_region = forecast[train_end_idx:]
    valid = test_region[~np.isnan(test_region)]
    assert valid.size > 0
    assert np.all(valid > 0)
    assert np.all(np.isfinite(valid))
    # ordem de grandeza plausível: entre 1/100 e 100x a variância real
    # (faixa larga de propósito -- não é teste de precisão do MLE)
    true_var = true_std**2
    assert np.all(valid > true_var / 100)
    assert np.all(valid < true_var * 100)


def test_fit_egarch_causal_treino_nao_ve_teste() -> None:
    n = 800
    train_end_idx = 500
    log_return = _synthetic_log_return(n, seed=6)

    fit_a = vm.fit_egarch(log_return, train_end_idx=train_end_idx)
    perturbed = log_return.copy()
    perturbed[train_end_idx:] = 5.0  # todo o "futuro" vira absurdo
    fit_b = vm.fit_egarch(perturbed, train_end_idx=train_end_idx)

    assert fit_a is not None and fit_b is not None
    assert fit_a.omega == pytest.approx(fit_b.omega)
    assert fit_a.alpha == pytest.approx(fit_b.alpha)
    assert fit_a.beta == pytest.approx(fit_b.beta)
    assert fit_a.gamma == pytest.approx(fit_b.gamma)


def test_predict_egarch_ultimo_indice_e_nan_sem_t_mais_1() -> None:
    log_return = _synthetic_log_return(300, seed=7)
    fit = vm.fit_egarch(log_return, train_end_idx=300)
    assert fit is not None
    forecast = vm.predict_egarch(fit, log_return)
    assert np.isnan(forecast[-1])  # não existe t+1 pra última barra
    # forecast[0] = exp(log_var_seed) -- o "chute" antes de qualquer passo
    # real da recursão, não NaN: legítimo, só menos informado que os
    # forecasts posteriores (que já incorporaram retornos observados).
    assert np.isfinite(forecast[0])
    assert forecast[0] > 0
