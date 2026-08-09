"""Testes de `src/risk/kill_switch.py` — os 13 gatilhos (§10.2), `SystemState`
(§10.3) e o fluxo de reset.

Os 5 gatilhos computáveis hoje (K01-K03, K12, K13) são testados de verdade
(disparo e não-disparo, incluindo limiar). Os 8 "sensor pronto, sem fonte de
dado real ainda" (K04-K11) são testados nos dois lados: (a) `None` (o caso
real do pipeline hoje) produz `TriggerState.NOT_COMPUTABLE`, nunca um
`NOT_TRIGGERED` silencioso; (b) quando um valor real É passado, a lógica de
comparação funciona corretamente — mesmo padrão de teste que
`tests/unit/test_regime_stress.py` já usa para S2 (`spread_pctile_expanding`)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.exchange.filters import Filters
from src.regime.stress import TriggerState, compute_filters_hash
from src.risk import kill_switch
from src.risk._constants import load_constant
from src.risk.kill_switch import (
    KillSwitchDecision,
    KillSwitchInputs,
    KillSwitchResetRecord,
    SystemState,
    evaluate_kill_switch,
    reset_kill_switch,
)

_T0 = datetime(2026, 8, 8, 14, 30, tzinfo=UTC)


def _make_filters(**overrides: object) -> Filters:
    defaults: dict[str, object] = {
        "symbol": "BTCUSDT",
        "snapshot_date": _T0.date(),
        "is_reconstructed": False,
        "status": "TRADING",
        "tick_size": Decimal("0.10"),
        "min_price": Decimal("556.80"),
        "max_price": Decimal("4529764"),
        "step_size": Decimal("0.001"),
        "min_qty": Decimal("0.001"),
        "max_qty": Decimal("1000"),
        "market_step_size": Decimal("0.001"),
        "market_min_qty": Decimal("0.001"),
        "market_max_qty": Decimal("1000"),
        "min_notional": Decimal("50"),
        "max_num_orders": 200,
        "price_precision": 2,
        "quantity_precision": 3,
        "multiplier_up": Decimal("1.05"),
        "multiplier_down": Decimal("0.95"),
    }
    defaults.update(overrides)
    return Filters(**defaults)  # type: ignore[arg-type]


# ============================================================================
# SystemState — §10.3
# ============================================================================


def test_system_state_tem_os_9_estados_do_prd() -> None:
    names = {s.name for s in SystemState}
    assert names == {
        "BOOT", "INITIALIZING", "SYNCING", "READY",
        "RUNNING", "PAUSED", "ERROR", "HALTED", "KILLED",
    }  # fmt: skip


# ============================================================================
# K01 — perda diária > 2% do equity (computável)
# ============================================================================


def test_k01_nao_dispara_sem_perda() -> None:
    assert kill_switch.k01_daily_loss(Decimal("0"), Decimal("196.85")) == TriggerState.NOT_TRIGGERED


def test_k01_dispara_acima_do_limiar() -> None:
    threshold = Decimal(str(load_constant("daily_loss_limit_pct_equity")))
    equity = Decimal("196.85")
    loss = threshold * equity + Decimal("0.01")
    assert kill_switch.k01_daily_loss(loss, equity) == TriggerState.TRIGGERED


def test_k01_not_computable_com_equity_nao_positivo() -> None:
    assert kill_switch.k01_daily_loss(Decimal("1"), Decimal("0")) == TriggerState.NOT_COMPUTABLE
    assert kill_switch.k01_daily_loss(Decimal("1"), Decimal("-1")) == TriggerState.NOT_COMPUTABLE


# ============================================================================
# K02 — drawdown > 10% do pico (computável)
# ============================================================================


def test_k02_nao_dispara_sem_drawdown() -> None:
    result = kill_switch.k02_max_drawdown(Decimal("200"), Decimal("200"))
    assert result == TriggerState.NOT_TRIGGERED


def test_k02_dispara_acima_de_10pct() -> None:
    result = kill_switch.k02_max_drawdown(Decimal("170"), Decimal("200"))  # dd = 15%
    assert result == TriggerState.TRIGGERED


def test_k02_not_computable_sem_pico_estabelecido() -> None:
    result = kill_switch.k02_max_drawdown(Decimal("100"), Decimal("0"))
    assert result == TriggerState.NOT_COMPUTABLE


# ============================================================================
# K03 — perdas consecutivas > 5 (computável, sempre)
# ============================================================================


def test_k03_nao_dispara_ate_o_limite() -> None:
    assert kill_switch.k03_consecutive_losses(0) == TriggerState.NOT_TRIGGERED
    assert kill_switch.k03_consecutive_losses(5) == TriggerState.NOT_TRIGGERED


def test_k03_dispara_acima_do_limite() -> None:
    assert kill_switch.k03_consecutive_losses(6) == TriggerState.TRIGGERED


# ============================================================================
# K04-K11 — sensor pronto, sem fonte de dado real ainda: None -> NOT_COMPUTABLE
# ============================================================================


def test_gatilhos_sensor_ausente_sao_not_computable_com_none() -> None:
    assert kill_switch.k04_exchange_disconnected(None) == TriggerState.NOT_COMPUTABLE
    assert kill_switch.k05_position_divergence(None) == TriggerState.NOT_COMPUTABLE
    assert kill_switch.k06_unexpected_order(None) == TriggerState.NOT_COMPUTABLE
    assert kill_switch.k07_api_error_storm(None) == TriggerState.NOT_COMPUTABLE
    assert kill_switch.k08_data_corruption(None) == TriggerState.NOT_COMPUTABLE
    assert kill_switch.k09_model_unavailable(None) == TriggerState.NOT_COMPUTABLE
    assert kill_switch.k10_risk_engine_failure(None) == TriggerState.NOT_COMPUTABLE
    assert kill_switch.k11_unknown_order_state(None) == TriggerState.NOT_COMPUTABLE


def test_k04_funciona_de_verdade_quando_injetado() -> None:
    threshold = float(load_constant("exchange_disconnect_kill_switch_s"))
    assert kill_switch.k04_exchange_disconnected(threshold - 1) == TriggerState.NOT_TRIGGERED
    assert kill_switch.k04_exchange_disconnected(threshold + 1) == TriggerState.TRIGGERED


def test_k05_a_k06_e_k08_a_k10_booleanos_funcionam_quando_injetados() -> None:
    assert kill_switch.k05_position_divergence(False) == TriggerState.NOT_TRIGGERED
    assert kill_switch.k05_position_divergence(True) == TriggerState.TRIGGERED
    assert kill_switch.k06_unexpected_order(False) == TriggerState.NOT_TRIGGERED
    assert kill_switch.k06_unexpected_order(True) == TriggerState.TRIGGERED
    assert kill_switch.k08_data_corruption(False) == TriggerState.NOT_TRIGGERED
    assert kill_switch.k08_data_corruption(True) == TriggerState.TRIGGERED
    assert kill_switch.k09_model_unavailable(False) == TriggerState.NOT_TRIGGERED
    assert kill_switch.k09_model_unavailable(True) == TriggerState.TRIGGERED
    assert kill_switch.k10_risk_engine_failure(False) == TriggerState.NOT_TRIGGERED
    assert kill_switch.k10_risk_engine_failure(True) == TriggerState.TRIGGERED


def test_k07_funciona_de_verdade_quando_injetado() -> None:
    threshold = int(load_constant("api_error_storm_threshold_count"))
    assert kill_switch.k07_api_error_storm(threshold) == TriggerState.NOT_TRIGGERED
    assert kill_switch.k07_api_error_storm(threshold + 1) == TriggerState.TRIGGERED


def test_k11_funciona_de_verdade_quando_injetado() -> None:
    threshold = float(load_constant("unknown_order_state_kill_switch_s"))
    assert kill_switch.k11_unknown_order_state(threshold - 1) == TriggerState.NOT_TRIGGERED
    assert kill_switch.k11_unknown_order_state(threshold + 1) == TriggerState.TRIGGERED


# ============================================================================
# K12 — filters_hash mudou (computável — REUSA compute_filters_hash do
# Sprint 5, src.regime.stress)
# ============================================================================


def test_k12_not_computable_sem_hash_de_referencia() -> None:
    filters = _make_filters()
    result = kill_switch.k12_filters_hash_changed(filters, None)
    assert result == TriggerState.NOT_COMPUTABLE


def test_k12_nao_dispara_quando_hash_bate_com_a_referencia() -> None:
    filters = _make_filters()
    reference = compute_filters_hash(filters)
    result = kill_switch.k12_filters_hash_changed(filters, reference)
    assert result == TriggerState.NOT_TRIGGERED


def test_k12_dispara_quando_filtro_mudou_desde_a_ultima_revalidacao() -> None:
    filters = _make_filters(step_size=Decimal("0.01"))  # filtro "novo"
    old_filters = _make_filters(step_size=Decimal("0.001"))
    stale_reference = compute_filters_hash(old_filters)  # hash "antigo"
    result = kill_switch.k12_filters_hash_changed(filters, stale_reference)
    assert result == TriggerState.TRIGGERED


# ============================================================================
# K13 — equity abaixo do piso operacional (computável, diretamente)
# ============================================================================


def test_k13_nao_dispara_acima_do_piso() -> None:
    floor = Decimal(str(load_constant("equity_floor_usd")))
    assert kill_switch.k13_equity_floor(floor + Decimal("1")) == TriggerState.NOT_TRIGGERED
    # limiar exato ("< piso", estrito) não dispara:
    assert kill_switch.k13_equity_floor(floor) == TriggerState.NOT_TRIGGERED


def test_k13_dispara_abaixo_do_piso() -> None:
    floor = Decimal(str(load_constant("equity_floor_usd")))
    assert kill_switch.k13_equity_floor(floor - Decimal("1")) == TriggerState.TRIGGERED


# ============================================================================
# Composição — evaluate_kill_switch
# ============================================================================


def _make_inputs(**overrides: object) -> KillSwitchInputs:
    defaults: dict[str, object] = {
        "equity": Decimal("196.85"),
        "daily_loss_usd": Decimal("0"),
        "equity_peak_usd": Decimal("196.85"),
        "consecutive_losses": 0,
        "filters": _make_filters(),
        "last_revalidated_filters_hash": None,
    }
    defaults.update(overrides)
    return KillSwitchInputs(**defaults)  # type: ignore[arg-type]


def test_evaluate_kill_switch_ok_quando_nada_dispara() -> None:
    result = evaluate_kill_switch(_make_inputs())
    assert result.decision == KillSwitchDecision.OK
    assert result.triggered_ids == ()
    # K04-K11 ficam NOT_COMPUTABLE por padrão (None); K12 também (sem hash de
    # referência nestes inputs) -- 9 no total.
    assert set(result.not_computable_ids) == {
        "K04", "K05", "K06", "K07", "K08", "K09", "K10", "K11", "K12",
    }  # fmt: skip


def test_evaluate_kill_switch_killed_quando_equity_abaixo_do_piso() -> None:
    floor = Decimal(str(load_constant("equity_floor_usd")))
    result = evaluate_kill_switch(_make_inputs(equity=floor - Decimal("1")))
    assert result.decision == KillSwitchDecision.KILLED
    assert "K13" in result.triggered_ids


def test_evaluate_kill_switch_killed_quando_qualquer_gatilho_dispara() -> None:
    result = evaluate_kill_switch(_make_inputs(consecutive_losses=99))
    assert result.decision == KillSwitchDecision.KILLED
    assert result.triggered_ids == ("K03",)


def test_evaluate_kill_switch_not_computable_nunca_conta_como_triggered() -> None:
    result = evaluate_kill_switch(_make_inputs())
    for trigger_id in result.not_computable_ids:
        assert trigger_id not in result.triggered_ids


# ============================================================================
# Reset — só com registro humano explícito (§10.2)
# ============================================================================


def test_reset_kill_switch_exige_operator_e_reason() -> None:
    with pytest.raises(ValueError):
        reset_kill_switch(KillSwitchResetRecord(reset_at=_T0, operator="", reason="diagnosticado"))
    with pytest.raises(ValueError):
        reset_kill_switch(KillSwitchResetRecord(reset_at=_T0, operator="felipe", reason=""))
    with pytest.raises(ValueError):
        reset_kill_switch(KillSwitchResetRecord(reset_at=_T0, operator="   ", reason="   "))


def test_reset_kill_switch_com_registro_valido_devolve_paused() -> None:
    record = KillSwitchResetRecord(
        reset_at=_T0, operator="felipe", reason="reconciliado manualmente, contadores resetados"
    )
    assert reset_kill_switch(record) == SystemState.PAUSED


def test_reset_kill_switch_nunca_devolve_running_diretamente() -> None:
    """§10.2: PAUSED -> observação de 1h -> RUNNING é passo operacional
    separado, fora deste módulo — reset nunca pula direto pra RUNNING."""
    record = KillSwitchResetRecord(reset_at=_T0, operator="felipe", reason="motivo real")
    result = reset_kill_switch(record)
    assert result != SystemState.RUNNING
    assert result == SystemState.PAUSED
