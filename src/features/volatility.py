"""`VolatilityEstimator` (PRD_V4_1.md T0.1, §3.1) — interface que os 135
pontos de `fan_in` catalogados (`interface_existente: null`) devem migrar
para consumir, em vez de chamar `support.atr_wilder`/`group_c.c01_atr_20`
direto. Esta entrega cobre a interface + a primeira implementação +
os 2 impedimentos marcados "banned pattern ativo" (I-a, I-b); a migração
completa dos 135 pontos (G-C0-2) é trabalho subsequente, não fingido aqui
como concluído.

`ATRWilderEstimator` é **bit-idêntica** ao que já roda em produção — mesmo
`support.atr_wilder`, mesma normalização `ATR/close` de
`group_c.c02_atr_20_pct` (Sprint 4). T0.5 exige isso: o baseline
reprocessado na janela comum precisa ser "sem alteração alguma", então
trocar a implementação por baixo do capô não é opção aqui.

`horizon_minutes` (I2, PRD §2.7 — `atr_window`/`time_stop` não têm
conversão única entre TFs) é forward-looking para o M1 da Camada 1
("cada estimador é calibrado com horizonte em relógio fixo e janela em
barras derivada por TF" — isso é trabalho do M1, não deste módulo).
`ATRWilderEstimator` só aceita `horizon_minutes == bars.timeframe_minutes`
(a definição trivial de "1 barra = 1 estimativa") e levanta
`NotImplementedError` para qualquer outro valor — fabricar uma conversão
clock-based sem a calibração medida do M1 seria exatamente o tipo de
número plausível-mas-sem-base que a Regra Zero (CLAUDE.md) proíbe.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
import polars as pl
from numpy.typing import NDArray

from . import support
from ._constants import load_constant

FloatArray = NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class Bars:
    """OHLC + timeframe nativo em minutos — o suficiente para qualquer
    `VolatilityEstimator` validar `horizon_minutes` (I2) sem precisar
    reconsultar o pipeline de barras. `frame` precisa ter `high`/`low`/
    `close` (outras colunas passam despercebidas)."""

    frame: pl.DataFrame
    timeframe_minutes: int


class VolatilityEstimator(Protocol):
    def estimate(self, bars: Bars, *, horizon_minutes: int) -> FloatArray:
        """Volatilidade prevista para os próximos `horizon_minutes`.
        Horizonte em RELÓGIO, não em barras (I2).
        Causal: só informação disponível no fechamento de cada barra.
        Retorna fração do preço. NaN no warmup; nunca zero, nunca parcial."""
        ...

    @property
    def warmup_bars(self) -> int: ...

    @property
    def estimator_id(self) -> str: ...


@dataclass(frozen=True, slots=True)
class ATRWilderEstimator:
    """ATR de Wilder / close — mesma definição de `group_c.c01_atr_20` +
    `c02_atr_20_pct` (Sprint 4), zero alteração de comportamento (T0.5).
    `window` é explícito no construtor (nunca um literal solto no
    chamador — é exatamente isso que I-a/I-b violavam); `from_constants()`
    lê `constants.yaml::atr_window` para quem não tem motivo de passar
    outro valor."""

    window: int

    @staticmethod
    def from_constants() -> "ATRWilderEstimator":
        return ATRWilderEstimator(window=int(load_constant("atr_window")))

    def estimate(self, bars: Bars, *, horizon_minutes: int) -> FloatArray:
        if horizon_minutes != bars.timeframe_minutes:
            raise NotImplementedError(
                "ATRWilderEstimator so estima no horizonte nativo da barra "
                f"({bars.timeframe_minutes}min); horizon_minutes={horizon_minutes} "
                "pedido. Conversao clock-based entre TFs (I2, PRD_V4_1.md §2.7) "
                "e escopo do M1 (calibracao por TF), ainda nao implementada aqui "
                "-- nao fabricar um numero sem base medida (Regra Zero, CLAUDE.md)."
            )
        high = bars.frame["high"].cast(pl.Float64).to_numpy()
        low = bars.frame["low"].cast(pl.Float64).to_numpy()
        close = bars.frame["close"].cast(pl.Float64).to_numpy()
        atr_abs = support.atr_wilder(high, low, close, self.window)
        with np.errstate(divide="ignore", invalid="ignore"):
            out: FloatArray = atr_abs / close
        return out

    @property
    def warmup_bars(self) -> int:
        return self.window

    @property
    def estimator_id(self) -> str:
        return f"atr_wilder_w{self.window}"
