"""Testes de `src/models/decomposition.py` — decomposição de PnL
carry/direcional (§16.6). O teste central é a RECONCILIAÇÃO EXATA:
`PnL_direcional_unit + PnL_carry_unit + PnL_execucao_unit == ret_net`,
porque os três termos vêm da mesma fórmula que
`src.labels.triple_barrier.build_labels` já usa para calcular `ret_net`."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl

from src.models import decomposition


def _synthetic_trades(
    n: int = 200, *, funding_bias_bps: float = 0.0, seed: int = 0
) -> pl.DataFrame:
    rng = np.random.default_rng(seed)
    side = rng.choice([1, -1], size=n).astype(np.int8)
    ret_gross = rng.normal(scale=0.01, size=n)
    funding_bps = rng.normal(loc=funding_bias_bps, scale=1.0, size=n)  # noqa: magic-number
    cost_entry_bps = np.full(n, 2.0)  # noqa: magic-number
    cost_exit_bps = np.full(n, 2.0)  # noqa: magic-number
    ret_net = ret_gross - (funding_bps + cost_entry_bps + cost_exit_bps) / 10_000.0
    t0 = [
        datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=i) for i in range(n)  # noqa: magic-number
    ]
    return pl.DataFrame(
        {
            "t0": pl.Series(t0).cast(pl.Datetime("ms")).dt.replace_time_zone("UTC"),
            "side_hat": side,
            "ret_gross": ret_gross,
            "funding_bps": funding_bps,
            "cost_entry_bps": cost_entry_bps,
            "cost_exit_bps": cost_exit_bps,
            "ret_net": ret_net,
        }
    )


def test_decompose_reconcilia_exatamente_com_ret_net() -> None:
    trades = _synthetic_trades()
    result = decomposition.decompose(trades)
    reconciled = result.pnl_direcional + result.pnl_carry + result.pnl_execucao
    assert abs(reconciled - result.pnl_total) < 1e-9


def test_decompose_carry_share_positivo_quando_funding_domina() -> None:
    """Funding fortemente enviesado (custo alto e constante) domina o
    PnL_total negativo — `carry_share` deve refletir isso com o sinal
    correto (PnL_carry negativo / PnL_total negativo = carry_share
    positivo, já que os dois têm o mesmo sinal)."""
    trades = _synthetic_trades(funding_bias_bps=50.0)  # noqa: magic-number
    result = decomposition.decompose(trades)
    assert result.pnl_carry < 0.0
    assert result.carry_share > 0.0


def test_decompose_gate3_directional_positive_flag() -> None:
    trades = _synthetic_trades(seed=1)
    result = decomposition.decompose(trades)
    assert result.gate3_directional_positive == (result.directional_sharpe > 0.0)


def test_decompose_vazio_retorna_nan_sem_quebrar() -> None:
    empty = pl.DataFrame(
        schema={
            "t0": pl.Datetime("ms", "UTC"),
            "side_hat": pl.Int8,
            "ret_gross": pl.Float64,
            "funding_bps": pl.Float64,
            "cost_entry_bps": pl.Float64,
            "cost_exit_bps": pl.Float64,
            "ret_net": pl.Float64,
        }
    )
    result = decomposition.decompose(empty)
    assert result.n_trades == 0
    assert result.gate3_directional_positive is False
