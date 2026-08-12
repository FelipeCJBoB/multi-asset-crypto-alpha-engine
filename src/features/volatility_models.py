"""Estimadores de volatilidade que exigem AJUSTE de parâmetro sobre o
treino — diferente dos `VolatilityEstimator` de `volatility.py`
(fórmula fechada, `estimate()` sozinho já é a resposta). PRD_V4_1.md
§3.2 M1: `HAR-RV` (Corsi 2009) e `EGARCH(1,1)` (Nelson 1991, MLE) são os
2 candidatos que precisam disso.

**EGARCH(1,1) é sequencial, HAR-RV não é — diferença que importa pro
walk-forward.** `day/week/month` do HAR-RV são médias causais que
independem do fit; dá pra computar uma vez e só trocar os coeficientes
por fold. A recursão do EGARCH (`sigma_t` depende de `sigma_{t-1}`) não
tem esse atalho — `predict_egarch` precisa RECOMPUTAR a trajetória
inteira desde o início da série a cada fold, com os coeficientes
daquele fold. Mais caro (`O(n)` por fold, não vetorizável — a recursão é
inerentemente sequencial), mas ainda `O(n × n_folds)` no total, não
`O(n²)`.

`mu` (média do retorno) fixado em 0 -- retorno de barra intraday em
cripto é ordens de magnitude menor que o desvio-padrão (∼1e-4 vs ∼1e-2),
estimar `mu` por MLE junto com os 4 parâmetros de variância adiciona uma
dimensão de instabilidade numérica sem ganho prático; convenção comum em
modelos GARCH de alta frequência.

**Interface deliberadamente distinta de `VolatilityEstimator`.**
`fit(train) -> HARRVFit` / `predict(fit, full_series) -> forecast_var`
em vez de `estimate(bars, horizon_minutes)` — porque HAR-RV não tem uma
resposta sem ver dado de treino primeiro. Isso só serve o harness de
avaliação walk-forward do M1 (`src/analysis/volatility_comparison.py`,
que refit a cada fold); não é uma decisão sobre como consumir isso
bar-a-bar num pipeline de produção — essa decisão (cadência de refit em
produção) é posterior ao M1 escolher um vencedor.

**`realized_var` já é a convenção do resto do módulo:**
`realized_var[t] = r_{t+1}^2` (`next_bar_realized_variance`,
`volatility_walkforward.py`) — o alvo de previsão em `t`, não a
variância JÁ realizada em `t`. HAR-RV regride esse alvo sobre médias
causais de `realized_var` em janelas ESTRITAMENTE anteriores a `t`
(dia/semana/mês em barras, derivado de `bars_per_day` — cripto 24/7, não
a convenção de 5/22 dias úteis de bolsa tradicional)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy import optimize

FloatArray = NDArray[np.float64]

_MIN_TRAIN_OBS = 10
_EGARCH_MIN_TRAIN_OBS = 50
_EGARCH_LOG_VAR_CLIP = 50.0  # exp(50) ~ 5e21 -- teto de sanidade numérica, nunca atingido por um fit real (variância de retorno de barra ~1e-6 a 1e-3, log_var típico entre -14 e -7); só existe pra recursão divergente não virar inf/overflow silencioso durante a busca do otimizador.
_SQRT_2_OVER_PI = float(np.sqrt(2.0 / np.pi))  # E|z| pra z~N(0,1), termo padrão do EGARCH (Nelson 1991)


def _rolling_mean_causal(x: FloatArray, window: int) -> FloatArray:
    """Média móvel causal (a barra `t` entra na própria janela) — NaN
    até a janela fechar. `O(n)` via soma cumulativa."""
    n = x.shape[0]
    out = np.full(n, np.nan, dtype=np.float64)
    if window <= 0 or n < window:
        return out
    x_filled = np.where(np.isnan(x), 0.0, x)
    valid = (~np.isnan(x)).astype(np.float64)
    csum = np.cumsum(np.insert(x_filled, 0, 0.0))
    vsum = np.cumsum(np.insert(valid, 0, 0.0))
    window_sum = csum[window:] - csum[:-window]
    window_n = vsum[window:] - vsum[:-window]
    with np.errstate(invalid="ignore", divide="ignore"):
        means = window_sum / window_n
    out[window - 1 :] = np.where(window_n == window, means, np.nan)
    return out


def _har_components(
    realized_var: FloatArray, *, bars_per_day: int
) -> tuple[FloatArray, FloatArray, FloatArray]:
    """`day[t]/week[t]/month[t] = média(realized_var[t-window:t])` --
    ESTRITAMENTE índices `< t` (desloca a série em 1 antes da média
    causal, não é a janela rolante "inclui `t`" de `support.py`). Regride
    contra `realized_var[t]` (= `r_{t+1}^2`) sem usar nada de `t` em
    diante nos regressores."""
    n = realized_var.shape[0]
    shifted = np.concatenate(([np.nan], realized_var[:-1])) if n else realized_var
    day = _rolling_mean_causal(shifted, bars_per_day)
    week = _rolling_mean_causal(shifted, bars_per_day * 7)
    month = _rolling_mean_causal(shifted, bars_per_day * 30)
    return day, week, month


@dataclass(frozen=True, slots=True)
class HARRVFit:
    """Coeficientes de `realized_var[t] = intercept + beta_day*day[t] +
    beta_week*week[t] + beta_month*month[t] + erro`, ajustados por OLS
    sobre `realized_var[:train_end_idx]`."""

    intercept: float
    beta_day: float
    beta_week: float
    beta_month: float
    n_train: int


def fit_har_rv(
    realized_var: FloatArray, *, bars_per_day: int, train_end_idx: int
) -> HARRVFit | None:
    """`None` se não houver `_MIN_TRAIN_OBS` pares válidos (dia/semana/mês
    + alvo todos finitos) no treino -- sinal explícito pro chamador pular
    o fold, nunca um ajuste fabricado sobre amostra insuficiente.

    Alvo vai só até `train_end_idx - 2` (não `train_end_idx - 1`): como
    `realized_var[t] = r_{t+1}²` (convenção do módulo), o último alvo
    "dentro do treino" seria `realized_var[train_end_idx-1]`, mas esse
    valor depende de `close[train_end_idx]` -- a primeira barra de TESTE.
    Cortar em `train_end_idx - 1` (exclusive) garante que nenhum par de
    treino depende de preço fora de `[0, train_end_idx)` (achado F1 do
    audit_engineering, 2026-08-11)."""
    day, week, month = _har_components(realized_var, bars_per_day=bars_per_day)
    fit_end_idx = train_end_idx - 1
    y = realized_var[:fit_end_idx]
    x_day = day[:fit_end_idx]
    x_week = week[:fit_end_idx]
    x_month = month[:fit_end_idx]
    mask = np.isfinite(y) & np.isfinite(x_day) & np.isfinite(x_week) & np.isfinite(x_month)
    n_valid = int(np.sum(mask))
    if n_valid < _MIN_TRAIN_OBS:
        return None
    design = np.column_stack(
        [np.ones(n_valid, dtype=np.float64), x_day[mask], x_week[mask], x_month[mask]]
    )
    coeffs, _residuals, _rank, _sv = np.linalg.lstsq(design, y[mask], rcond=None)
    return HARRVFit(
        intercept=float(coeffs[0]),
        beta_day=float(coeffs[1]),
        beta_week=float(coeffs[2]),
        beta_month=float(coeffs[3]),
        n_train=n_valid,
    )


def predict_har_rv(fit: HARRVFit, realized_var: FloatArray, *, bars_per_day: int) -> FloatArray:
    """Forecast de variância (não sigma -- diferente de `VolatilityEstimator.
    estimate()`, HAR-RV regride direto em escala de variância) para toda a
    série -- o chamador (`volatility_comparison.py`) recorta a região de
    teste do fold correspondente a este `fit`. Forecast `<= 0`
    (regressão linear não restringe sinal) vira NaN em vez de variância
    negativa silenciosa -- mesma disciplina de `qlike_loss` sobre
    forecast inválido."""
    day, week, month = _har_components(realized_var, bars_per_day=bars_per_day)
    forecast = fit.intercept + fit.beta_day * day + fit.beta_week * week + fit.beta_month * month
    out: FloatArray = np.where(forecast > 0, forecast, np.nan)
    return out


# ============================================================================
# EGARCH(1,1) -- Nelson (1991), MLE
# ============================================================================


def _egarch_log_var_recursion(
    log_return: FloatArray,
    *,
    omega: float,
    alpha: float,
    beta: float,
    gamma: float,
    log_var_seed: float,
) -> FloatArray:
    """`log_var[t] = log(sigma_t²)`, a variância CONDICIONAL de
    `log_return[t]` dado informação até `t-1` -- ancorada em
    `log_var_seed` no primeiro retorno válido, recursiva daí em diante:

        z_t = log_return[t] / sigma_t
        log_var[t+1] = omega + beta*log_var[t] + alpha*(|z_t| - E|z|) + gamma*z_t

    Sequencial por natureza (não vetorizável -- `sigma_t` depende de
    `sigma_{t-1}`). Se a recursão diverge (parâmetros fora da região
    estável, típico durante a busca do otimizador antes de convergir),
    para no primeiro `log_var` não-finito e deixa o resto NaN -- o
    chamador (`_egarch_neg_log_likelihood`) trata isso como log-
    verossimilhança inválida, não deixa propagar `inf`/`nan` silencioso."""
    n = log_return.shape[0]
    log_var = np.full(n, np.nan, dtype=np.float64)
    first_valid = 0
    while first_valid < n and np.isnan(log_return[first_valid]):
        first_valid += 1
    if first_valid >= n:
        return log_var
    log_var[first_valid] = log_var_seed
    for t in range(first_valid, n - 1):
        lv = log_var[t]
        if not np.isfinite(lv):
            break
        sigma_t = float(np.sqrt(np.exp(min(lv, _EGARCH_LOG_VAR_CLIP))))
        eps_t = log_return[t]
        if np.isnan(eps_t) or sigma_t <= 0.0:
            log_var[t + 1] = lv
            continue
        z_t = eps_t / sigma_t
        next_lv = omega + beta * lv + alpha * (abs(z_t) - _SQRT_2_OVER_PI) + gamma * z_t
        log_var[t + 1] = next_lv if np.isfinite(next_lv) else np.nan
    return log_var


def _egarch_neg_log_likelihood(
    params: FloatArray, log_return_train: FloatArray, log_var_seed: float
) -> float:
    omega, alpha, beta, gamma = params
    log_var = _egarch_log_var_recursion(
        log_return_train, omega=omega, alpha=alpha, beta=beta, gamma=gamma, log_var_seed=log_var_seed
    )
    valid = np.isfinite(log_var) & ~np.isnan(log_return_train)
    if int(np.sum(valid)) < _EGARCH_MIN_TRAIN_OBS:
        return 1e12
    var = np.exp(np.clip(log_var[valid], -_EGARCH_LOG_VAR_CLIP, _EGARCH_LOG_VAR_CLIP))
    eps = log_return_train[valid]
    log_lik = -0.5 * (np.log(2.0 * np.pi) + np.log(var) + eps**2 / var)
    total = -float(np.sum(log_lik))
    return total if np.isfinite(total) else 1e12


@dataclass(frozen=True, slots=True)
class EGARCHFit:
    """Coeficientes de EGARCH(1,1) ajustados por máxima verossimilhança
    sobre `log_return[:train_end_idx]`. `log_var_seed` (log da variância
    amostral do treino) é FIXO, não ajustado por MLE junto dos outros 4 --
    reduz a dimensão da otimização de 5 pra 4 parâmetros; é convenção
    comum tratar a variância pré-amostra como dado, não parâmetro livre."""

    omega: float
    alpha: float
    beta: float
    gamma: float
    log_var_seed: float
    n_train: int


def fit_egarch(log_return: FloatArray, *, train_end_idx: int) -> EGARCHFit | None:
    """`None` se `_EGARCH_MIN_TRAIN_OBS` não for atingido, variância
    amostral do treino for não-positiva/não-finita, ou o otimizador
    (`scipy.optimize.minimize`, L-BFGS-B) não convergir -- nunca devolve
    coeficientes de uma otimização que falhou, mesmo que `x` final pareça
    razoável."""
    train = log_return[:train_end_idx]
    valid_train = train[~np.isnan(train)]
    if valid_train.size < _EGARCH_MIN_TRAIN_OBS:
        return None
    sample_var = float(np.var(valid_train))
    if not np.isfinite(sample_var) or sample_var <= 0.0:
        return None
    log_var_seed = float(np.log(sample_var))

    x0 = np.array([log_var_seed * 0.1, 0.1, 0.9, 0.0], dtype=np.float64)
    bounds = [(-_EGARCH_LOG_VAR_CLIP, _EGARCH_LOG_VAR_CLIP), (-5.0, 5.0), (-0.999, 0.999), (-5.0, 5.0)]
    result = optimize.minimize(
        _egarch_neg_log_likelihood,
        x0,
        args=(train, log_var_seed),
        method="L-BFGS-B",
        bounds=bounds,
        options={"maxiter": 200},
    )
    if not result.success or not np.all(np.isfinite(result.x)):
        return None
    omega, alpha, beta, gamma = (float(v) for v in result.x)
    return EGARCHFit(
        omega=omega,
        alpha=alpha,
        beta=beta,
        gamma=gamma,
        log_var_seed=log_var_seed,
        n_train=int(valid_train.size),
    )


def predict_egarch(fit: EGARCHFit, log_return: FloatArray) -> FloatArray:
    """`forecast_var[t] = sigma_{t+1}²` -- mesma convenção de
    `predict_har_rv`/`realized_var` (`r_{t+1}²` é o alvo). Recomputa a
    recursão inteira desde o início da série com os coeficientes deste
    fit -- diferente de HAR-RV, não dá pra "aplicar" o fit numa janela
    isolada porque a recursão é sequencial (ver docstring do módulo)."""
    log_var = _egarch_log_var_recursion(
        log_return,
        omega=fit.omega,
        alpha=fit.alpha,
        beta=fit.beta,
        gamma=fit.gamma,
        log_var_seed=fit.log_var_seed,
    )
    n = log_return.shape[0]
    forecast_var = np.full(n, np.nan, dtype=np.float64)
    if n > 1:
        with np.errstate(over="ignore", invalid="ignore"):
            forecast_var[:-1] = np.exp(np.clip(log_var[1:], -_EGARCH_LOG_VAR_CLIP, _EGARCH_LOG_VAR_CLIP))
    return forecast_var
