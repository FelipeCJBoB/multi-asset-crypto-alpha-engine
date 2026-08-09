"""GRUPO B — Momentum e reversão (§2.3). Escopo do Sprint 4: B01 (T1) e
B07 (T2, mas implementado agora — insumo do Regime Engine, §4.2, Sprint 5)."""

from __future__ import annotations

from .. import support
from ..support import FloatArray


def b01_rsi_14(close: FloatArray, window: int) -> FloatArray:
    """RSI de Wilder escalado para `[-1, 1]` via `(RSI-50)/50` — §2.3 B01."""
    rsi = support.rsi_wilder(close, window)
    out: FloatArray = (rsi - 50.0) / 50.0  # reescala fixa [0,100] do RSI [noqa: magic-number]
    return out


def b07_efficiency_ratio_48(close: FloatArray, window: int) -> FloatArray:
    """`|C_t − C_{t−48}| / Σ|C_i − C_{i−1}|` — §2.3 B07. T2 no vetor de
    treino do Alpha V1, mas eixo de partição do Regime Engine (§4.2) — por
    isso implementado no Sprint 4 junto com T1, não adiado para quando B07
    for promovido por ablação (§2.0.1)."""
    return support.efficiency_ratio(close, window)
