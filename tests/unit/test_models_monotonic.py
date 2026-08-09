"""Testes de `src/models/monotonic.py` — Camada 1, IC de Spearman in-fold
por ambiente e atribuição de `monotone_constraints` (§5.3)."""

from __future__ import annotations

import numpy as np
import polars as pl

from src.models import monotonic
from src.models.environments import ENVIRONMENTS


def _synthetic_df(*, feature_sign: int, n_envs_consistent: int, n_per_env: int = 40) -> pl.DataFrame:
    """Monta um frame com as 6 células de ambiente já povoadas e uma
    feature (`feat`) cujo IC contra `ret_net` tem sinal `feature_sign` em
    exatamente `n_envs_consistent` das 6 células (as demais têm sinal
    oposto) — controle direto sobre o resultado esperado da triagem."""
    rng = np.random.default_rng(0)
    rows: list[pl.DataFrame] = []
    for i, env in enumerate(ENVIRONMENTS):
        sign = feature_sign if i < n_envs_consistent else -feature_sign
        x = rng.normal(size=n_per_env)
        noise = rng.normal(scale=0.01, size=n_per_env)
        y = sign * x + noise  # ret_net cresce/decresce com x conforme `sign`
        rows.append(
            pl.DataFrame(
                {
                    "env": [env] * n_per_env,
                    "feat": x,
                    "ret_net": y,
                }
            )
        )
    return pl.concat(rows, how="vertical")


def test_compute_ic_by_env_sinal_correto() -> None:
    df = _synthetic_df(feature_sign=1, n_envs_consistent=6)
    ic = monotonic.compute_ic_by_env(df, "feat", "ret_net")
    assert set(ic.keys()) == set(ENVIRONMENTS)
    assert all(v > 0 for v in ic.values())


def test_compute_ic_by_env_ambiente_sem_dado_vira_nan() -> None:
    df = _synthetic_df(feature_sign=1, n_envs_consistent=6).filter(pl.col("env") != ENVIRONMENTS[0])
    ic = monotonic.compute_ic_by_env(df, "feat", "ret_net")
    assert np.isnan(ic[ENVIRONMENTS[0]])


def test_assign_constraint_consistente_em_6_de_6() -> None:
    df = _synthetic_df(feature_sign=1, n_envs_consistent=6)
    ic = monotonic.compute_ic_by_env(df, "feat", "ret_net")
    constraint, mean_ic, n_consistent, n_with_data = monotonic._assign_from_ic(
        ic, min_consistent_envs=6
    )
    assert constraint == 1
    assert n_consistent == 6
    assert n_with_data == 6


def test_assign_constraint_5_de_6_nao_passa_no_limiar_6() -> None:
    df = _synthetic_df(feature_sign=1, n_envs_consistent=5)
    ic = monotonic.compute_ic_by_env(df, "feat", "ret_net")
    constraint, _mean_ic, n_consistent, _n = monotonic._assign_from_ic(ic, min_consistent_envs=6)
    assert n_consistent == 5
    assert constraint == 0  # limiar de 6 exige unanimidade


def test_assign_constraint_5_de_6_passa_no_limiar_5() -> None:
    df = _synthetic_df(feature_sign=1, n_envs_consistent=5)
    ic = monotonic.compute_ic_by_env(df, "feat", "ret_net")
    constraint, _mean_ic, n_consistent, _n = monotonic._assign_from_ic(ic, min_consistent_envs=5)
    assert n_consistent == 5
    assert constraint == 1


def _synthetic_screen_df(
    feature_col: str, *, feature_sign: int = 1, n_envs_consistent: int = 6,
    n_per_env: int = 40, seed: int = 1,
) -> pl.DataFrame:
    """Frame COMPLETO (`regime` + `E27f_cost_atr_ratio` + `feature_col` +
    `ret_net`) que passa pelo `assign_environments` de verdade (não um
    `env` pré-calculado) — necessário para os testes de
    `screen_monotone_constraints`, que chama `assign_environments`
    internamente. Os valores de `E27f_cost_atr_ratio` ficam em 3 grupos bem
    separados (~10/~50/~90) para que o corte de tercil global caia sempre
    entre os grupos, e a ordem dos 6 blocos bate exatamente com
    `environments.ENVIRONMENTS` (RANGE via R1, depois TREND via R3, cada um
    LOW/MID/HIGH nessa ordem) — os primeiros `n_envs_consistent` blocos têm
    IC(feature_col, ret_net) com sinal `feature_sign`; o resto, sinal
    oposto."""
    rng = np.random.default_rng(seed)
    cost_reps = (10.0, 50.0, 90.0)  # noqa: magic-number
    blocks: list[pl.DataFrame] = []
    env_i = 0
    for regime in ("R1", "R3"):
        for cost_val in cost_reps:
            sign = feature_sign if env_i < n_envs_consistent else -feature_sign
            x = rng.normal(size=n_per_env)
            y = sign * x + rng.normal(scale=0.01, size=n_per_env)  # noqa: magic-number
            cost_series = cost_val + rng.normal(scale=0.5, size=n_per_env)  # noqa: magic-number
            data: dict[str, object] = {
                "regime": [regime] * n_per_env,
                "E27f_cost_atr_ratio": cost_series,
                "ret_net": y,
            }
            if feature_col != "E27f_cost_atr_ratio":
                data[feature_col] = x
            blocks.append(pl.DataFrame(data))
            env_i += 1
    return pl.concat(blocks, how="vertical")


def test_screen_monotone_constraints_e27f_forcado_menos_1_mesmo_sem_sinal() -> None:
    """`E27f_cost_atr_ratio` recebe -1 por argumento econômico (§5.3),
    independente do IC medido — construído aqui SEM controle de sinal
    (n_envs_consistent=0, todo mundo "inconsistente") e o resultado ainda
    é -1."""
    df = _synthetic_screen_df("E27f_cost_atr_ratio", n_envs_consistent=0)
    results = monotonic.screen_monotone_constraints(
        df, ("E27f_cost_atr_ratio",), min_consistent_envs=6
    )
    assert results["E27f_cost_atr_ratio"].constraint == -1
    assert results["E27f_cost_atr_ratio"].forced_economic is True


def test_screen_monotone_constraints_le_limiar_de_constants_yaml_por_padrao() -> None:
    """Sem `min_consistent_envs` explícito, lê `alpha_monotonic_consistency_
    min_envs` de `constants.yaml` (valor atual: 6, ver a entrada para a
    investigação completa do '6 de 7' vs '6 de 6')."""
    df = _synthetic_screen_df("B01_rsi_14", feature_sign=-1, n_envs_consistent=6)
    results = monotonic.screen_monotone_constraints(df, ("B01_rsi_14",))
    assert results["B01_rsi_14"].constraint == -1


def test_min_obs_por_ambiente_insuficiente_vira_nan() -> None:
    tiny = pl.DataFrame(
        {"env": [ENVIRONMENTS[0]] * 2, "feat": [0.1, 0.2], "ret_net": [0.01, 0.02]}
    )
    ic = monotonic.compute_ic_by_env(tiny, "feat", "ret_net")
    assert np.isnan(ic[ENVIRONMENTS[0]])
