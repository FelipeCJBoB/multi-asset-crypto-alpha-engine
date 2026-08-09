"""Testes de `src/models/stability.py` — Camada 2, triagem de estabilidade
entre ambientes in-fold (§5.4): `estabilidade = forca * consistencia**2`,
denominador FIXO 6, e o diagnóstico PRE/POST (`ic_by_rpi_regime`) que fica
FORA da fórmula (decisão do Manager 2026-08-09 — ver docstring do módulo)."""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from src.models import stability
from src.models.environments import ENVIRONMENTS


def _synthetic_screen_df(
    feature_col: str,
    *,
    feature_sign: int = 1,
    n_envs_consistent: int = 6,
    n_per_env: int = 40,
    seed: int = 1,
    ic_scale: float = 1.0,
) -> pl.DataFrame:
    """Mesmo padrão de `tests/unit/test_models_monotonic.py::_synthetic_screen_df`
    — frame COMPLETO (`regime` + `E27f_cost_atr_ratio` + `feature_col` +
    `ret_net`) que passa por `assign_environments` de verdade dentro de
    `stability_screen`. Os primeiros `n_envs_consistent` dos 6 blocos têm
    IC(feature_col, ret_net) com sinal `feature_sign`; o resto, sinal
    oposto. `ic_scale` controla a força do sinal (relação sinal/ruído)."""
    rng = np.random.default_rng(seed)
    cost_reps = (10.0, 50.0, 90.0)  # noqa: magic-number -- 3 grupos bem separados p/ tercil
    blocks: list[pl.DataFrame] = []
    env_i = 0
    for regime in ("R1", "R3"):
        for cost_val in cost_reps:
            sign = feature_sign if env_i < n_envs_consistent else -feature_sign
            x = rng.normal(size=n_per_env)
            noise_scale = 1.0 / ic_scale if ic_scale > 0 else 1.0
            y = sign * x + rng.normal(scale=noise_scale, size=n_per_env)
            cost_series = cost_val + rng.normal(scale=0.5, size=n_per_env)  # noqa: magic-number
            data: dict[str, object] = {
                "regime": [regime] * n_per_env,
                "E27f_cost_atr_ratio": cost_series,
                "ret_net": y,
                "t0": pl.datetime_range(
                    pl.datetime(2024, 1, 1),
                    pl.datetime(2024, 1, 1) + pl.duration(minutes=15 * (n_per_env - 1)),
                    interval="15m",
                    eager=True,
                ),
            }
            if feature_col != "E27f_cost_atr_ratio":
                data[feature_col] = x
            blocks.append(pl.DataFrame(data))
            env_i += 1
    return pl.concat(blocks, how="vertical")


def test_score_from_ic_unanime_da_consistencia_1() -> None:
    ic = dict.fromkeys(ENVIRONMENTS, 0.1)
    forca, consistencia, estabilidade, n_with_data = stability._score_from_ic(ic)
    assert consistencia == pytest.approx(1.0)
    assert forca == pytest.approx(0.1)
    assert estabilidade == pytest.approx(0.1)
    assert n_with_data == 6


def test_score_from_ic_ambiente_sem_dado_nao_infla_forca_nem_consistencia() -> None:
    """2 de 6 ambientes com IC=0,3 (concordante) e 4 sem dado (NaN) --
    denominador FIXO 6: forca=(0,3+0,3)/6=0,1, NÃO 0,3 (que seria a média
    só dos 2 medidos); consistencia=2/6, NÃO 2/2=1,0 (que pareceria
    unânime ignorando os 4 sem voto)."""
    ic = {env: (0.3 if i < 2 else float("nan")) for i, env in enumerate(ENVIRONMENTS)}
    forca, consistencia, estabilidade, n_with_data = stability._score_from_ic(ic)
    assert n_with_data == 2
    assert forca == pytest.approx(0.6 / 6)
    assert consistencia == pytest.approx(2 / 6)
    assert estabilidade == pytest.approx((0.6 / 6) * (2 / 6) ** 2)


def test_score_from_ic_sem_nenhum_dado_da_zero() -> None:
    ic = {env: float("nan") for env in ENVIRONMENTS}
    forca, consistencia, estabilidade, n_with_data = stability._score_from_ic(ic)
    assert (forca, consistencia, estabilidade, n_with_data) == (0.0, 0.0, 0.0, 0)


def test_stability_screen_consistente_e_forte_sobrevive_limiar_baixo() -> None:
    df = _synthetic_screen_df("feat", feature_sign=1, n_envs_consistent=6, ic_scale=5.0)
    results = stability.stability_screen(df, ("feat",), limiar=0.01)
    assert results["feat"].survives is True
    assert results["feat"].consistencia == pytest.approx(1.0)


def test_stability_screen_inconsistente_nao_sobrevive() -> None:
    """3 de 6 concordam -- sinal dominante indefinido/fraco, consistência
    baixa o suficiente pra `estabilidade` ficar abaixo de um limiar
    moderado mesmo com força individual razoável."""
    df = _synthetic_screen_df("feat", feature_sign=1, n_envs_consistent=3, ic_scale=5.0)
    results = stability.stability_screen(df, ("feat",), limiar=0.3)
    assert results["feat"].consistencia == pytest.approx(0.5)
    assert results["feat"].survives is False


def test_stability_screen_limiar_alto_rejeita_sinal_fraco() -> None:
    df = _synthetic_screen_df("feat", feature_sign=1, n_envs_consistent=6, ic_scale=0.05)
    results = stability.stability_screen(df, ("feat",), limiar=0.9)
    assert results["feat"].survives is False


def test_stability_screen_usa_limiar_de_constants_quando_nao_passado() -> None:
    df = _synthetic_screen_df("feat", feature_sign=1, n_envs_consistent=6, ic_scale=5.0)
    results_default = stability.stability_screen(df, ("feat",))
    results_explicit = stability.stability_screen(
        df, ("feat",), limiar=stability.load_constant("alpha_stability_screen_limiar")
    )
    assert results_default["feat"].survives == results_explicit["feat"].survives


def test_ic_by_rpi_regime_retorna_pre_e_post_por_feature() -> None:
    df = _synthetic_screen_df("feat", feature_sign=1, n_envs_consistent=6, ic_scale=5.0)
    df = df.with_columns(
        pl.when(pl.int_range(pl.len()) < pl.len() // 2)
        .then(pl.datetime(2025, 1, 1))
        .otherwise(pl.datetime(2026, 1, 1))
        .alias("t0")
    )
    out = stability.ic_by_rpi_regime(df, ("feat",))
    assert set(out["feat"].keys()) == {"PRE", "POST"}


def test_ic_by_rpi_regime_pouco_dado_vira_nan() -> None:
    df = _synthetic_screen_df("feat", feature_sign=1, n_envs_consistent=6, n_per_env=2)
    out = stability.ic_by_rpi_regime(df, ("feat",))
    assert np.isnan(out["feat"]["PRE"]) or np.isnan(out["feat"]["POST"])
