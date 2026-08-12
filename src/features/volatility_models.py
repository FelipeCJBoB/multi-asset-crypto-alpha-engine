"""Estimadores de volatilidade que exigem AJUSTE de parâmetro sobre o
treino — diferente dos `VolatilityEstimator` de `volatility.py`
(fórmula fechada, `estimate()` sozinho já é a resposta). PRD_V4_1.md
§3.2 M1: `HAR-RV` (Corsi 2009) é o primeiro dos 2 candidatos que
precisam disso; `EGARCH(1,1)` (MLE) é o segundo, ainda não implementado
aqui.

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

FloatArray = NDArray[np.float64]

_MIN_TRAIN_OBS = 10


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
    o fold, nunca um ajuste fabricado sobre amostra insuficiente."""
    day, week, month = _har_components(realized_var, bars_per_day=bars_per_day)
    y = realized_var[:train_end_idx]
    x_day = day[:train_end_idx]
    x_week = week[:train_end_idx]
    x_month = month[:train_end_idx]
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
