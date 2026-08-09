"""Camada risk — Risk Engine: sizing quantizado (§8.2), 18 controles (§8.3),
kill switch e estados do sistema (§10.2/§10.3). Importa `src.exchange`,
`src.features` e `src.regime`; NÃO importa `src.execution` nem `src.models`
(§14.2 — risk vem antes de execution na cadeia `backtest <- risk <-
execution <- live`, contrato formalizado em `pyproject.toml`
`[tool.importlinter]`).

Sprint 9: `sizing.py` (§8.2), `limits.py` (os 18/19 controles de §8.3),
`kill_switch.py` (os 13 gatilhos de §10.2 + `SystemState`, §10.3). Testado
com sinal SINTÉTICO (`side_hat`/`confidence` inventados nos testes) — o Alpha
real (Sprint 8) roda em paralelo, sem dependência mútua."""

from __future__ import annotations

from .kill_switch import (
    KillSwitchDecision,
    KillSwitchInputs,
    KillSwitchResetRecord,
    KillSwitchResult,
    SystemState,
    evaluate_kill_switch,
    reset_kill_switch,
)
from .limits import (
    ControlOutcome,
    RejectionReason,
    RiskDecision,
    RiskEngineInputs,
    evaluate_all,
)
from .sizing import SizingResult, ZeroStopDistanceError, compute_sizing, compute_sizing_asof

__all__ = [
    "ControlOutcome",
    "KillSwitchDecision",
    "KillSwitchInputs",
    "KillSwitchResetRecord",
    "KillSwitchResult",
    "RejectionReason",
    "RiskDecision",
    "RiskEngineInputs",
    "SizingResult",
    "SystemState",
    "ZeroStopDistanceError",
    "compute_sizing",
    "compute_sizing_asof",
    "evaluate_all",
    "evaluate_kill_switch",
    "reset_kill_switch",
]
