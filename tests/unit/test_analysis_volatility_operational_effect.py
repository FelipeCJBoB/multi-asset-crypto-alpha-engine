"""Testes de `src/analysis/volatility_operational_effect.py` -- PRD_V4_1.md
§3.2 M1, linha 354/356. Eixo principal: `_r1_vectorized` (float64/numpy)
precisa concordar com `src.risk.sizing.compute_sizing` (Decimal, produção
real) dentro de tolerância de ponto flutuante -- é a alegação central da
docstring do módulo, testada aqui, não só afirmada."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import numpy as np
import pytest

from src.exchange.filters import Filters
from src.risk import limits as risk_limits
from src.risk._constants import load_constant as load_risk_constant
from src.risk.sizing import compute_sizing

from src.analysis.volatility_operational_effect import _r1_pass, _r1_vectorized

_T0 = datetime(2026, 8, 8, 14, 30, tzinfo=UTC)
_EQUITY_USD = 196.85  # capital do projeto, mesmo valor de test_risk_sizing.py


def _make_filters(*, step_size: str = "0.001") -> Filters:
    return Filters(
        symbol="BTCUSDT",
        snapshot_date=_T0.date(),
        is_reconstructed=False,
        status="TRADING",
        tick_size=Decimal("0.10"),
        min_price=Decimal("556.80"),
        max_price=Decimal("4529764"),
        step_size=Decimal(step_size),
        min_qty=Decimal(step_size),
        max_qty=Decimal("1000"),
        market_step_size=Decimal(step_size),
        market_min_qty=Decimal(step_size),
        market_max_qty=Decimal("1000"),
        min_notional=Decimal("50"),
        max_num_orders=200,
        price_precision=2,
        quantity_precision=3,
        multiplier_up=Decimal("1.05"),
        multiplier_down=Decimal("0.95"),
    )


def test_r1_vectorized_bate_com_compute_sizing_producao() -> None:
    filters = _make_filters(step_size="0.001")
    mark_price_val = 64940.0
    risk_per_trade = float(load_risk_constant("risk_per_trade"))
    sl_atr_mult = float(load_risk_constant("sl_atr_mult"))

    # amostra de atr_pct cobrindo a janela viável e fora dela dos dois lados
    atr_pct_values = [0.001, 0.003, 0.00305, 0.005, 0.008, 0.02]
    estimator_pct = np.array(atr_pct_values, dtype=np.float64)
    mark_price = np.full(len(atr_pct_values), mark_price_val, dtype=np.float64)

    quant_error, n_req_over_unit = _r1_vectorized(
        estimator_pct=estimator_pct,
        mark_price=mark_price,
        equity_usd=_EQUITY_USD,
        risk_per_trade=risk_per_trade,
        sl_atr_mult=sl_atr_mult,
        step_size=float(filters.step_size),
        quantization_tolerance=float(load_risk_constant("quantization_tolerance")),
        min_sizing_resolution_units=float(load_risk_constant("min_sizing_resolution_units")),
    )

    for i, atr_pct in enumerate(atr_pct_values):
        sizing = compute_sizing(
            t0=_T0,
            equity=Decimal(str(_EQUITY_USD)),
            atr_pct=Decimal(str(atr_pct)),
            mark_price=Decimal(str(mark_price_val)),
            filters=filters,
        )
        expected_quant_error = float(sizing.quant_error)
        expected_n_req_over_unit = float(sizing.notional_req / sizing.unit_notional)

        assert quant_error[i] == pytest.approx(expected_quant_error, abs=1e-6), atr_pct
        assert n_req_over_unit[i] == pytest.approx(expected_n_req_over_unit, rel=1e-6), atr_pct

        # controles REAIS de producao (src.risk.limits) como segunda fonte de verdade
        r1a = risk_limits.control_09a_erro_quantizacao(sizing)
        r1b = risk_limits.control_09b_resolucao_sizing(sizing)
        expected_pass = (
            r1a == risk_limits.ControlOutcome.PASS and r1b == risk_limits.ControlOutcome.PASS
        )
        got_pass = bool(
            _r1_pass(
                quant_error[i : i + 1],
                n_req_over_unit[i : i + 1],
                tolerance=float(load_risk_constant("quantization_tolerance")),
                min_units=float(load_risk_constant("min_sizing_resolution_units")),
            )[0]
        )
        assert got_pass == expected_pass, atr_pct


def test_r1_pass_janela_viavel_e_estritamente_and() -> None:
    quant_error = np.array([0.0, 0.5])
    n_req_over_unit = np.array([10.0, 10.0])
    out = _r1_pass(quant_error, n_req_over_unit, tolerance=0.25, min_units=2.0)
    assert out[0]
    assert not out[1]  # quant_error acima da tolerância derruba mesmo com N_req/unit ok
