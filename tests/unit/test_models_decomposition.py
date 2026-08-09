"""Testes de `src/models/decomposition.py` — decomposição de PnL
carry/direcional (§16.6). O teste central é a RECONCILIAÇÃO EXATA:
`PnL_direcional_unit + PnL_carry_unit + PnL_execucao_unit == ret_net`,
porque os três termos vêm da mesma fórmula que
`src.labels.triple_barrier.build_labels` já usa para calcular `ret_net`."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl

from src.core.metric import Unit
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
    assert abs(reconciled.value - result.pnl_total.value) < 1e-9
    assert reconciled.valid  # mesmos n_trades/n_semantics nos 3 termos, ver Metric.__add__


def test_decompose_carry_share_invalido_quando_pnl_total_negativo() -> None:
    """Achado nº1 da auditoria: com funding fortemente enviesado, o
    `pnl_total` fica negativo (mesmo sinal dos dados reais de hoje) — sob a
    fórmula ingênua, `carry_share = pnl_carry / pnl_total` seria positivo
    (dois negativos) e "passaria" o gate por acidente, testando o sinal
    errado do que §16.6 pretende ("carry é majoritariamente do PnL", não
    "carry e total têm o mesmo sinal"). Com o guard de `safe_ratio`
    (`require_den_positive=True`), a razão NUNCA É CALCULADA nesse caso —
    `carry_share.value` é `nan` por construção (não um número que dá pra
    conferir o sinal), `carry_share.valid` é `False`, e B3 ("gate que
    recebe Metric inválido FALHA, não passa") reprova `gate3_carry_share_ok`
    em vez de deixá-lo passar em silêncio como antes desta mudança."""
    trades = _synthetic_trades(funding_bias_bps=50.0)  # noqa: magic-number
    result = decomposition.decompose(trades)
    assert result.pnl_carry.value < 0.0
    assert result.pnl_total.value < 0.0  # funding domina o net -> total também negativo
    assert result.carry_share.valid is False  # guard de safe_ratio: denominador <= 0
    assert math.isnan(result.carry_share.value)  # não calculada, não só "suspeita"
    assert result.gate3_carry_share_ok is False  # B3 — Metric inválido reprova o gate


def test_decompose_carry_share_valido_quando_pnl_total_positivo() -> None:
    """Contraponto do teste acima: com `pnl_total > 0`, `safe_ratio` calcula
    normalmente e `carry_share.valid` é `True`."""
    trades = _synthetic_trades(funding_bias_bps=-50.0, seed=2)  # noqa: magic-number
    result = decomposition.decompose(trades)
    assert result.pnl_total.value > 0.0
    assert result.carry_share.valid is True


def test_decompose_gate3_directional_positive_flag() -> None:
    trades = _synthetic_trades(seed=1)
    result = decomposition.decompose(trades)
    assert result.gate3_directional_positive == (result.directional_sharpe.value > 0.0)


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
    assert result.pnl_total.valid is False
    assert result.pnl_total.n == 0
    assert math.isnan(result.pnl_total.value)


def test_decompose_metric_fields_tem_unit_e_source_corretos() -> None:
    trades = _synthetic_trades()
    result = decomposition.decompose(trades)
    assert result.pnl_total.unit == Unit.FRACTION_OF_NOTIONAL
    assert result.carry_share.unit == Unit.RATIO
    assert result.total_sharpe.unit == Unit.SHARPE_ANNUALIZED
    assert result.directional_sharpe.unit == Unit.SHARPE_ANNUALIZED
    assert result.pnl_total.n == result.n_trades
    assert result.pnl_total.n_semantics == "trades"
    assert result.pnl_total.source == "models.decomposition.decompose"


def test_decompose_aceita_source_override_sem_quebrar_chamada_posicional() -> None:
    """`source` é kwarg com default — chamada posicional existente em
    `src.models.pipeline.run_layer1_sprint` (`decomposition.decompose(df)`)
    continua funcionando; quem tem contexto melhor pode sobrescrever."""
    trades = _synthetic_trades()
    result = decomposition.decompose(trades, source="experiments/alpha_layer1_report.json")
    assert result.pnl_total.source == "experiments/alpha_layer1_report.json"
