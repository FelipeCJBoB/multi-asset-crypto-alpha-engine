"""Walk-forward ancorado + métricas de comparação de estimadores de
volatilidade — PRD_V4_1.md §3.2 M1. Núcleo puro (sem IO): splits,
QLIKE/MSE/viés/Mincer-Zarnowitz, teste de significância (Diebold-Mariano)
e taxa de vitória por fold. Análogo a `cpcv.py`/`dsr.py` deste mesmo
pacote — primitivos estatísticos reusáveis, não a orquestração real do M1
(comparar os 6 candidatos sobre bars reais das 15 combinações symbol×tf,
que fica em `src/analysis/` junto dos outros scripts de medição — não
escrita ainda nesta rodada).

**Alvo de avaliação — retorno² da PRÓXIMA barra.** `estimate()` de
qualquer `VolatilityEstimator` (T0.1) já é causal por construção (só usa
`<= t`); o alvo contra o qual comparamos precisa ser estritamente
POSTERIOR a `t` — `r_{t+1}^2` (log-retorno da barra seguinte, ao
quadrado) é o proxy padrão de variância realizada num horizonte de 1
barra na literatura de avaliação de forecast de volatilidade (QLIKE,
Patton 2011). Isso não é vazamento: é o próprio objeto que o forecast
tenta prever, nunca usado para CALCULAR o forecast.

**Papel do walk-forward aqui, sendo honesto sobre o que ele realmente
protege.** Os 4 candidatos hoje implementados (`ATRWilder`, `Parkinson`,
`GarmanKlass`, `RealizedVol`) são fórmula fechada sobre janela fixa — não
ajustam parâmetro nenhum a partir do "treino", e já são causais por
construção (T0.1). Para esses 4, o corte treino/teste não previne
vazamento adicional; o que ele dá é uma quebra por trimestre civil real
pra alimentar a checagem de robustez (`fold_win_rate`) — "o candidato
vence na maioria dos trimestres, não só na média pooled". Fica
estruturalmente essencial quando `HAR-RV`/`EGARCH(1,1)` entrarem (esses
sim ajustam parâmetro sobre o treino de cada fold)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import polars as pl
from numpy.typing import NDArray
from scipy.stats import norm

IntArray = NDArray[np.int64]
FloatArray = NDArray[np.float64]


# ============================================================================
# Splits — ancorado, trimestre civil (não N dias fixos)
# ============================================================================


@dataclass(frozen=True, slots=True)
class WalkForwardSplit:
    """`fold_id` sequencial a partir de 0. Treino = `bars[0:train_end_idx]`
    (sempre âncorado em 0 — "ancorado" = início nunca se move, só
    expande). Teste = `bars[test_start_idx:test_end_idx]`, um trimestre
    civil inteiro."""

    fold_id: int
    train_end_idx: int
    test_start_idx: int
    test_end_idx: int


def generate_anchored_walk_forward_splits(
    open_time_ms: IntArray, *, initial_train_years: int
) -> tuple[WalkForwardSplit, ...]:
    """PRD_V4_1.md §3.2 M1 — "treino inicial 2 anos, passo trimestral".
    Passo é TRIMESTRE CIVIL (Q1/Q2/Q3/Q4 do calendário), não uma contagem
    fixa de dias — trimestres civis têm 90-92 dias, um passo fixo em dias
    deriva ao longo dos anos. Cada fold de teste é um trimestre civil
    inteiro (ou parcial, se for o último trimestre disponível na série);
    o treino do fold seguinte inclui esse trimestre inteiro (expansão
    real, não sobreposição parcial)."""
    n = open_time_ms.shape[0]
    if n == 0:
        return ()

    dates = pl.from_epoch(pl.Series(open_time_ms), time_unit="ms").dt.date()
    period = (dates.dt.year() * 4 + dates.dt.quarter()).to_numpy()

    unique_periods = np.unique(period)
    n_initial_periods = initial_train_years * 4
    if unique_periods.shape[0] <= n_initial_periods:
        return ()

    first_test_period = unique_periods[n_initial_periods]
    splits: list[WalkForwardSplit] = []
    fold_id = 0
    for p in unique_periods:
        if p < first_test_period:
            continue
        train_end_idx = int(np.searchsorted(period, p, side="left"))
        test_end_idx = int(np.searchsorted(period, p, side="right"))
        if train_end_idx == 0 or train_end_idx == test_end_idx:
            continue
        splits.append(WalkForwardSplit(fold_id, train_end_idx, train_end_idx, test_end_idx))
        fold_id += 1
    return tuple(splits)


# ============================================================================
# Alvo de avaliação
# ============================================================================


def next_bar_realized_variance(close: FloatArray) -> FloatArray:
    """`r_{t+1}^2`, `r = ln(C_{t+1}/C_t)` — proxy padrão de variância
    realizada num horizonte de 1 barra. Índice `t=n-1` (última barra) não
    tem `t+1` -> NaN."""
    n = close.shape[0]
    out = np.full(n, np.nan, dtype=np.float64)
    if n > 1:
        with np.errstate(divide="ignore", invalid="ignore"):
            out[:-1] = np.log(close[1:] / close[:-1]) ** 2
    return out


# ============================================================================
# Métricas — QLIKE (primária), MSE, viés, Mincer-Zarnowitz
# ============================================================================


def qlike_loss(forecast_var: FloatArray, realized_var: FloatArray) -> FloatArray:
    """QLIKE (Patton 2011) — `realized/forecast - ln(realized/forecast) - 1`,
    por observação. Robusta a outlier no alvo em comparação a MSE puro
    (log em vez de nível). `forecast_var <= 0` ou qualquer NaN de entrada
    vira NaN na saída, nunca `inf`/erro silencioso."""
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = realized_var / forecast_var
        out: FloatArray = ratio - np.log(ratio) - 1.0
    out = np.where(forecast_var > 0, out, np.nan)
    return out


def mse_loss(forecast_var: FloatArray, realized_var: FloatArray) -> FloatArray:
    """`(forecast - realized)^2`, na escala de VARIÂNCIA (não desvio-padrão),
    mesma escala de `qlike_loss`/`next_bar_realized_variance`."""
    out: FloatArray = (forecast_var - realized_var) ** 2
    return out


def bias(forecast_var: FloatArray, realized_var: FloatArray) -> float:
    """`mean(forecast - realized)` — positivo = superestima variância em
    média. `NaN` se não sobrar observação válida (nunca 0 silencioso)."""
    diff = forecast_var - realized_var
    valid = diff[~np.isnan(diff)]
    return float(np.mean(valid)) if valid.size else float("nan")


@dataclass(frozen=True, slots=True)
class MincerZarnowitzResult:
    """Regressão `realized = intercept + slope*forecast`. Forecast bem
    calibrado: `intercept≈0`, `slope≈1`. `r_squared` é poder explicativo
    do forecast sobre o realizado, não qualidade de calibração por si —
    os dois são propriedades distintas (mesma distinção que o achado de
    `confidence_rank` do PRD §4.4: "não ordena mas funciona como
    porta")."""

    intercept: float
    slope: float
    r_squared: float
    n: int


def mincer_zarnowitz(forecast_var: FloatArray, realized_var: FloatArray) -> MincerZarnowitzResult:
    mask = ~(np.isnan(forecast_var) | np.isnan(realized_var))
    x = forecast_var[mask]
    y = realized_var[mask]
    n = x.shape[0]
    if n < 2:
        return MincerZarnowitzResult(float("nan"), float("nan"), float("nan"), n)
    x_mean, y_mean = float(np.mean(x)), float(np.mean(y))
    sxx = float(np.sum((x - x_mean) ** 2))
    # Degenerado (forecast sem variância) -- checagem RELATIVA, não `sxx
    # == 0.0` exato: erro de ponto flutuante na média de valores
    # repetidos deixa `sxx` numericamente != 0 mesmo quando `x` é
    # matematicamente constante (medido: `np.full(20, 0.02)` dá
    # `sxx ~ 1e-20`, não `0.0` — `== 0.0` exato deixava passar e produzia
    # slope/intercept de ruído numérico em vez de NaN).
    scale = max(abs(x_mean), 1.0) ** 2
    if sxx < 1e-9 * scale * n:
        return MincerZarnowitzResult(float("nan"), float("nan"), float("nan"), n)
    slope = float(np.sum((x - x_mean) * (y - y_mean)) / sxx)
    intercept = y_mean - slope * x_mean
    y_pred = intercept + slope * x
    ss_res = float(np.sum((y - y_pred) ** 2))
    ss_tot = float(np.sum((y - y_mean) ** 2))
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0.0 else float("nan")
    return MincerZarnowitzResult(intercept, slope, r_squared, n)


# ============================================================================
# Validação do "vencedor" — robustez por fold + significância (propostos,
# não texto literal do PRD; ver artifact "M1 — Volatilidade: 15
# combinações", painel 05 — precisam de confirmação antes de virar gate)
# ============================================================================


def fold_win_rate(per_fold_loss_candidate: FloatArray, per_fold_loss_baseline: FloatArray) -> float:
    """Fração de folds em que `candidate` tem perda MENOR que `baseline`.
    `> 0.5` = vence na maioria dos trimestres, não só na média pooled.
    `NaN` se não houver par válido."""
    valid = ~(np.isnan(per_fold_loss_candidate) | np.isnan(per_fold_loss_baseline))
    a = per_fold_loss_candidate[valid]
    b = per_fold_loss_baseline[valid]
    if a.shape[0] == 0:
        return float("nan")
    return float(np.mean(a < b))


@dataclass(frozen=True, slots=True)
class DieboldMarianoResult:
    """`dm_stat`/`p_value` do teste de Diebold-Mariano (1995) sobre
    `d_t = loss_candidate_t - loss_baseline_t`, H0: `E[d]=0`.
    `mean_loss_diff < 0` = candidato tem perda média menor (melhor)."""

    dm_stat: float
    p_value: float
    mean_loss_diff: float
    n: int


def diebold_mariano(loss_candidate: FloatArray, loss_baseline: FloatArray) -> DieboldMarianoResult:
    """Variância de `d_t` estimada sem correção HAC/Newey-West — válido
    para horizonte de previsão de 1 passo à frente (o caso de M1:
    `horizon_minutes == timeframe_minutes`, uma barra), onde `d_t` não
    carrega a estrutura de médias móveis que overlap de horizonte > 1
    passo induziria. Se M1 evoluir para `horizon_minutes` multi-barra,
    este teste precisa de correção HAC antes de ser usado — não
    implementado aqui porque não existe caso de uso real ainda (I2 do
    T0.1 continua sem resolver conversão clock-based entre TFs)."""
    d = loss_candidate - loss_baseline
    valid = d[~np.isnan(d)]
    n = valid.shape[0]
    if n < 2:
        return DieboldMarianoResult(float("nan"), float("nan"), float("nan"), n)
    mean_d = float(np.mean(valid))
    std_d = float(np.std(valid, ddof=1))
    if std_d == 0.0:
        return DieboldMarianoResult(float("nan"), float("nan"), mean_d, n)
    dm_stat = float(mean_d / (std_d / np.sqrt(n)))
    p_value = float(2.0 * (1.0 - norm.cdf(abs(dm_stat))))
    return DieboldMarianoResult(dm_stat, p_value, mean_d, n)
