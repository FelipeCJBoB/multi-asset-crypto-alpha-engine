"""Camada 1 — restrições monotônicas por sinal medido (§5.3), triagem
in-fold. Para cada feature T1 (exceto `E27f_cost_atr_ratio`, forçada a -1
por identidade contábil, não por padrão estatístico), calcula o IC de
Spearman contra `ret_net` (o "retorno futuro" realizado daquele lado, já
líquido de custo — §3.4) dentro de cada um dos 6 ambientes de
`src.models.environments` (só treino do fold, nunca vazando — B02/B06).

Sinal dominante = sinal da MÉDIA dos ICs válidos (ambientes sem dado
suficiente contam como NaN, não como zero). Consistência = quantos dos 6
ambientes (denominador SEMPRE 6, não o subconjunto com dado — task
explícita) concordam em sinal com o dominante. Atribui a restrição só se
consistência >= `alpha_monotonic_consistency_min_envs` (constants.yaml —
ver a entrada para a investigação completa do "6 de 7" vs "6 de 6" do
§5.3/§5.4); senão, `0` (sem restrição)."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import polars as pl
import structlog
from scipy.stats import spearmanr

from ._constants import load_constant
from .environments import ENV_COL, ENVIRONMENTS, assign_environments

logger = structlog.get_logger(__name__)

# Feature com restrição -1 por ARGUMENTO ECONÔMICO direto (§5.3): custo alto
# não pode melhorar o resultado esperado — identidade contábil, não padrão
# aprendido. Não passa pelo teste de consistência (mas o IC medido ainda é
# reportado, só não decide).
_ECONOMIC_FORCED_CONSTRAINT: dict[str, int] = {"E27f_cost_atr_ratio": -1}

# Mínimo de observações válidas (não-NaN, variância > 0 nos dois lados) para
# calcular Spearman num ambiente — abaixo disso o IC daquele ambiente é NaN
# e não entra nem no sinal dominante nem na contagem de consistência. Não é
# constante de domínio (é o mínimo matemático para spearmanr não degenerar:
# < 3 pontos ou variância nula não produz correlação com sentido); mesma
# categoria de `valid_cost.len() < 3` em `environments.py`.
_MIN_OBS_PER_ENV = 5  # noqa: magic-number


@dataclass(frozen=True, slots=True)
class FeatureICResult:
    feature: str
    ic_by_env: dict[str, float]
    mean_ic: float
    n_consistent_envs: int
    n_envs_with_data: int
    constraint: int
    forced_economic: bool


def compute_ic_by_env(
    df_env: pl.DataFrame, feature_col: str, target_col: str = "ret_net"
) -> dict[str, float]:
    """`df_env` já precisa ter a coluna `env` (ver `assign_environments`).
    Retorna `{ambiente: IC de Spearman}` para os 6 ambientes fixos —
    `float("nan")` se o ambiente não tiver dado suficiente no fold."""
    out: dict[str, float] = {}
    for env in ENVIRONMENTS:
        sub = df_env.filter(pl.col(ENV_COL) == env)
        x = sub[feature_col].to_numpy().astype(np.float64)
        y = sub[target_col].to_numpy().astype(np.float64)
        mask = np.isfinite(x) & np.isfinite(y)
        n_valid = int(mask.sum())
        if n_valid < _MIN_OBS_PER_ENV or np.std(x[mask]) == 0.0 or np.std(y[mask]) == 0.0:
            out[env] = float("nan")
            continue
        rho, _p = spearmanr(x[mask], y[mask])
        out[env] = float(rho) if np.isfinite(rho) else float("nan")
    return out


def _assign_from_ic(
    ic_by_env: dict[str, float], *, min_consistent_envs: int
) -> tuple[int, float, int, int]:
    valid = {e: v for e, v in ic_by_env.items() if not math.isnan(v)}
    n_envs_with_data = len(valid)
    if not valid:
        return 0, float("nan"), 0, n_envs_with_data

    mean_ic = float(sum(valid.values()) / len(valid))
    dominant = 1 if mean_ic > 0 else (-1 if mean_ic < 0 else 0)
    if dominant == 0:
        return 0, mean_ic, 0, n_envs_with_data

    n_consistent = sum(1 for v in valid.values() if (v > 0) == (dominant > 0))
    constraint = dominant if n_consistent >= min_consistent_envs else 0
    return constraint, mean_ic, n_consistent, n_envs_with_data


def screen_monotone_constraints(
    df_train_side: pl.DataFrame,
    feature_ids: tuple[str, ...],
    *,
    target_col: str = "ret_net",
    min_consistent_envs: int | None = None,
) -> dict[str, FeatureICResult]:
    """Núcleo da Camada 1 para UM lado, UM fold: `df_train_side` é o
    subconjunto de TREINO já filtrado por `src.models.dataset.side_subset`
    (NOFILL descartado, warmup descartado) — nunca o teste do fold, nunca o
    dataset inteiro. Retorna `{feature_id: FeatureICResult}` para todas as
    `feature_ids`, incluindo `E27f_cost_atr_ratio` (que recebe -1 forçado,
    mas com o IC medido reportado para transparência, não usado na
    decisão)."""
    if min_consistent_envs is None:
        min_consistent_envs = int(load_constant("alpha_monotonic_consistency_min_envs"))

    df_env = assign_environments(df_train_side)

    results: dict[str, FeatureICResult] = {}
    for feature in feature_ids:
        ic_by_env = compute_ic_by_env(df_env, feature, target_col)
        forced = feature in _ECONOMIC_FORCED_CONSTRAINT
        constraint, mean_ic, n_consistent, n_with_data = _assign_from_ic(
            ic_by_env, min_consistent_envs=min_consistent_envs
        )
        if forced:
            constraint = _ECONOMIC_FORCED_CONSTRAINT[feature]
        results[feature] = FeatureICResult(
            feature=feature,
            ic_by_env=ic_by_env,
            mean_ic=mean_ic,
            n_consistent_envs=n_consistent,
            n_envs_with_data=n_with_data,
            constraint=constraint,
            forced_economic=forced,
        )

    logger.info(
        "models.monotonic.screen_monotone_constraints",
        n_rows_train=df_train_side.height,
        min_consistent_envs=min_consistent_envs,
        constraints={f: r.constraint for f, r in results.items()},
    )
    return results
