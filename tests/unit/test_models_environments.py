"""Testes de `src/models/environments.py` — os 6 ambientes da Camada 1
(§5.4): tercil de `E27f_cost_atr_ratio` x {RANGE, TREND}, R0/R5 excluídos."""

from __future__ import annotations

import polars as pl

from src.models import environments as env_mod


def _synthetic_df(n_per_cell: int = 10) -> pl.DataFrame:
    """3 tercis x {RANGE via R1, TREND via R3} x `n_per_cell` linhas, mais
    um bloco R5 (deve virar `env = null`) — cost_atr_ratio cresce
    monotonicamente dentro de cada grupo estrutural para que os cortes de
    tercil caiam onde o teste espera."""
    rows: list[dict[str, object]] = []
    for regime in ("R1", "R3"):
        for i in range(3 * n_per_cell):
            rows.append({"regime": regime, "E27f_cost_atr_ratio": float(i)})
    for i in range(n_per_cell):
        rows.append({"regime": "R5", "E27f_cost_atr_ratio": float(i)})
    return pl.DataFrame(rows)


def test_assign_environments_produz_6_categorias_nao_nulas() -> None:
    df = _synthetic_df()
    out = env_mod.assign_environments(df)
    non_null = out.filter(pl.col(env_mod.ENV_COL).is_not_null())
    assert set(non_null[env_mod.ENV_COL].unique().to_list()) == set(env_mod.ENVIRONMENTS)


def test_assign_environments_r5_vira_null() -> None:
    df = _synthetic_df()
    out = env_mod.assign_environments(df)
    r5_envs = out.filter(pl.col("regime") == "R5")[env_mod.ENV_COL]
    assert r5_envs.is_null().all()


def test_assign_environments_range_vs_trend() -> None:
    df = _synthetic_df()
    out = env_mod.assign_environments(df)
    range_envs = set(out.filter(pl.col("regime") == "R1")[env_mod.ENV_COL].unique().to_list())
    trend_envs = set(out.filter(pl.col("regime") == "R3")[env_mod.ENV_COL].unique().to_list())
    assert all(e.startswith("RANGE_") for e in range_envs)
    assert all(e.startswith("TREND_") for e in trend_envs)


def test_assign_environments_terciles_aproximadamente_balanceados() -> None:
    df = _synthetic_df(n_per_cell=30)
    out = env_mod.assign_environments(df)
    r1 = out.filter(pl.col("regime") == "R1")
    counts = r1[env_mod.ENV_COL].value_counts().sort(env_mod.ENV_COL)
    # 3 baldes de ~30 cada sobre 90 linhas com valores igualmente espaçados
    # (tolerância folgada — o corte "<=q_low" inclusivo desloca a fronteira
    # em +-poucas linhas dependendo de onde o quantil cai exatamente).
    for c in counts["count"].to_list():
        assert 20 <= c <= 40  # noqa: magic-number — tolerância de balde de tercil


def test_assign_environments_dataframe_vazio_nao_quebra() -> None:
    df = pl.DataFrame(schema={"regime": pl.Utf8, "E27f_cost_atr_ratio": pl.Float64})
    out = env_mod.assign_environments(df)
    assert out.height == 0
    assert env_mod.ENV_COL in out.columns
