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
    """OHLC + identidade de grade — o suficiente para qualquer
    `VolatilityEstimator` validar `horizon_minutes` (I2) sem precisar
    reconsultar o pipeline de barras. `frame` precisa ter `high`/`low`/
    `close` (outras colunas passam despercebidas).

    Exatamente um entre `timeframe_minutes` (grade de TEMPO, M15/M30/H1 —
    relógio fixo, toda barra cobre a mesma duração nominal) e
    `resolution_id` (grade DOLLAR-BAR, R1/R2/R3 — relógio de negócio;
    `symbol+resolution_id+threshold_usdt+calibration_version` é a
    IDENTIDADE da grade, ontologia formalizada em AG-042,
    `audit/architecture_gaps_log.yaml`) precisa estar presente — nunca os
    dois, nunca nenhum. `resolution_id` é só IDENTIDADE de grade, não
    confundir com relógio ("R1 ≈ 15m" já foi confirmado erro operacional
    6× neste projeto, AG-042); ver AG-036 para o motivo desta separação
    existir."""

    frame: pl.DataFrame
    timeframe_minutes: int | None = None
    resolution_id: str | None = None

    def __post_init__(self) -> None:
        # `bool(self.resolution_id)` (não `is not None`) -- achado LOW de
        # project_assurance (AG-036): resolution_id="" não é uma identidade
        # de grade válida (ontologia AG-042, symbol+resolution_id+
        # threshold_usdt+calibration_version), mesmo sendo tecnicamente
        # != None. Zero caller real passa isso hoje, mas o guard não deve
        # aceitar silenciosamente uma string vazia como grade dollar-bar
        # "válida" se um futuro harness montar resolution_id a partir de um
        # lookup que pode devolver "" por bug.
        if (self.timeframe_minutes is not None) == bool(self.resolution_id):
            raise ValueError(
                "Bars precisa de exatamente um entre timeframe_minutes (grade de "
                "tempo, M15/M30/H1) e resolution_id (grade dollar-bar, R1/R2/R3, "
                "não-vazio) -- recebeu timeframe_minutes="
                f"{self.timeframe_minutes!r}, resolution_id={self.resolution_id!r}"
            )


class VolatilityEstimator(Protocol):
    def estimate(self, bars: Bars, *, horizon_minutes: int) -> FloatArray:
        """Volatilidade prevista para os próximos `horizon_minutes`.
        Horizonte em RELÓGIO, não em barras (I2).
        Causal: só informação disponível no fechamento de cada barra.
        Retorna fração do preço. NaN no warmup; nunca zero, nunca parcial.

        `bars` carrega exatamente um entre `timeframe_minutes` (grade de
        tempo) e `resolution_id` (grade dollar-bar, ver `Bars`). Nem toda
        implementação suporta as duas grades — as 5 implementações de
        fórmula fechada deste módulo (ATRWilder/Parkinson/GarmanKlass/
        RogersSatchell/YangZhang) ainda só suportam grade de TEMPO e
        levantam `NotImplementedError` explícito sob `resolution_id`
        (AG-036, `audit/architecture_gaps_log.yaml`); `RealizedVolEstimator`
        é a primeira readaptada pra suportar as duas."""
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
    def from_constants() -> ATRWilderEstimator:
        return ATRWilderEstimator(window=int(load_constant("atr_window")))

    def estimate(self, bars: Bars, *, horizon_minutes: int) -> FloatArray:
        if bars.resolution_id is not None:
            raise NotImplementedError(
                "ATRWilderEstimator ainda não foi readaptado pra grade "
                f"dollar-bar (resolution_id={bars.resolution_id!r}) -- ver "
                "AG-036, audit/architecture_gaps_log.yaml"
            )
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


@dataclass(frozen=True, slots=True)
class ParkinsonEstimator:
    """Parkinson (1980) — um dos 6 candidatos de M1 (PRD_V4_1.md §3.2).
    `window` é sempre explícito no construtor: qual janela é "certa" por
    (symbol, tf) é exatamente o que a calibração walk-forward de M1
    decide, não algo que este módulo deveria presumir via
    `from_constants()` — não existe `atr_window`-equivalente ainda medido
    para este estimador."""

    window: int

    def estimate(self, bars: Bars, *, horizon_minutes: int) -> FloatArray:
        if bars.resolution_id is not None:
            raise NotImplementedError(
                "ParkinsonEstimator ainda não foi readaptado pra grade "
                f"dollar-bar (resolution_id={bars.resolution_id!r}) -- ver "
                "AG-036, audit/architecture_gaps_log.yaml"
            )
        if horizon_minutes != bars.timeframe_minutes:
            raise NotImplementedError(
                "ParkinsonEstimator so estima no horizonte nativo da barra "
                f"({bars.timeframe_minutes}min); horizon_minutes={horizon_minutes} "
                "pedido. Conversao clock-based entre TFs (I2) e escopo do M1."
            )
        high = bars.frame["high"].cast(pl.Float64).to_numpy()
        low = bars.frame["low"].cast(pl.Float64).to_numpy()
        return support.parkinson_vol(high, low, self.window)

    @property
    def warmup_bars(self) -> int:
        return self.window

    @property
    def estimator_id(self) -> str:
        return f"parkinson_w{self.window}"


@dataclass(frozen=True, slots=True)
class GarmanKlassEstimator:
    """Garman-Klass (1980) — candidato de M1. Mesmo racional de
    `ParkinsonEstimator` sobre `window` explícito, sem `from_constants()`."""

    window: int

    def estimate(self, bars: Bars, *, horizon_minutes: int) -> FloatArray:
        if bars.resolution_id is not None:
            raise NotImplementedError(
                "GarmanKlassEstimator ainda não foi readaptado pra grade "
                f"dollar-bar (resolution_id={bars.resolution_id!r}) -- ver "
                "AG-036, audit/architecture_gaps_log.yaml"
            )
        if horizon_minutes != bars.timeframe_minutes:
            raise NotImplementedError(
                "GarmanKlassEstimator so estima no horizonte nativo da barra "
                f"({bars.timeframe_minutes}min); horizon_minutes={horizon_minutes} "
                "pedido. Conversao clock-based entre TFs (I2) e escopo do M1."
            )
        high = bars.frame["high"].cast(pl.Float64).to_numpy()
        low = bars.frame["low"].cast(pl.Float64).to_numpy()
        open_ = bars.frame["open"].cast(pl.Float64).to_numpy()
        close = bars.frame["close"].cast(pl.Float64).to_numpy()
        return support.garman_klass_vol(high, low, open_, close, self.window)

    @property
    def warmup_bars(self) -> int:
        return self.window

    @property
    def estimator_id(self) -> str:
        return f"garman_klass_w{self.window}"


@dataclass(frozen=True, slots=True)
class RealizedVolEstimator:
    """Volatilidade realizada de retorno log — `sigma(log_return) *
    sqrt(window)` (`support.realized_vol`, já usada por C06/C07 do
    Feature Engine). Candidato de M1; mesmo racional de `window` explícito
    dos outros dois novos estimadores.

    Sob grade dollar-bar, ver AG-036 -- a fórmula `sigma*sqrt(window)`
    permanece válida por argumento de teoria de relógio de atividade/
    subordinação (Ané & Geman 2000, Journal of Finance) -- `window`
    continua sendo contagem de barra, e a contagem de barra É a unidade
    certa sob relógio de negócio. `horizon_minutes` não é validado contra
    duração de barra sob grade dollar-bar porque não existe conversão
    medida ainda (P-2 pendente, `docs/refactor_dollar_bar_canonico.md`) --
    o forecast retornado é sempre "pra o fechamento da PRÓXIMA barra"
    (mesma semântica do alvo de M1, `next_bar_realized_variance`,
    `volatility_walkforward.py`) independente do `horizon_minutes` pedido.
    Limitação DOCUMENTADA, não resolvida silenciosamente -- se
    `horizon_minutes` precisar significar algo diferente de "1 barra à
    frente" sob dollar bar no futuro, isso exige desenho novo, não
    incluído aqui."""

    window: int

    def estimate(self, bars: Bars, *, horizon_minutes: int) -> FloatArray:
        # grade de tempo -- comportamento ORIGINAL, idêntico ao pré-remoção
        if bars.timeframe_minutes is not None and horizon_minutes != bars.timeframe_minutes:
            raise NotImplementedError(
                "RealizedVolEstimator so estima no horizonte nativo da barra "
                f"({bars.timeframe_minutes}min); horizon_minutes={horizon_minutes} "
                "pedido. Conversao clock-based entre TFs (I2) e escopo do M1."
            )
        # grade dollar-bar (bars.resolution_id is not None, garantido pelo
        # __post_init__ de Bars): sem guarda de horizon_minutes -- ver docstring
        close = bars.frame["close"].cast(pl.Float64).to_numpy()
        n = close.shape[0]
        log_return = np.full(n, np.nan, dtype=np.float64)
        if n > 1:
            with np.errstate(divide="ignore", invalid="ignore"):
                log_return[1:] = np.log(close[1:] / close[:-1])
        return support.realized_vol(log_return, self.window)

    @property
    def warmup_bars(self) -> int:
        # +1: log_return[0] é sempre NaN (sem C_{-1}), então a janela de
        # `window` retornos válidos só fecha em `window` barras depois
        # do primeiro retorno computável.
        return self.window + 1

    @property
    def estimator_id(self) -> str:
        return f"realized_vol_w{self.window}"


@dataclass(frozen=True, slots=True)
class RogersSatchellEstimator:
    """Rogers-Satchell (1991) -- candidato de extensão PÓS-M1 (decisão do
    Manager, 2026-08-11; não é um dos 6 candidatos declarados em
    PRD_V4_1.md §3.2), avaliado contra o vencedor de M1 (Garman-Klass) na
    mesma família "fórmula fechada, sem MLE/OLS por fold". Mesmo racional
    de `ParkinsonEstimator` sobre `window` explícito, sem `from_constants()`."""

    window: int

    def estimate(self, bars: Bars, *, horizon_minutes: int) -> FloatArray:
        if bars.resolution_id is not None:
            raise NotImplementedError(
                "RogersSatchellEstimator ainda não foi readaptado pra grade "
                f"dollar-bar (resolution_id={bars.resolution_id!r}) -- ver "
                "AG-036, audit/architecture_gaps_log.yaml"
            )
        if horizon_minutes != bars.timeframe_minutes:
            raise NotImplementedError(
                "RogersSatchellEstimator so estima no horizonte nativo da barra "
                f"({bars.timeframe_minutes}min); horizon_minutes={horizon_minutes} "
                "pedido. Conversao clock-based entre TFs (I2) e escopo do M1."
            )
        high = bars.frame["high"].cast(pl.Float64).to_numpy()
        low = bars.frame["low"].cast(pl.Float64).to_numpy()
        open_ = bars.frame["open"].cast(pl.Float64).to_numpy()
        close = bars.frame["close"].cast(pl.Float64).to_numpy()
        return support.rogers_satchell_vol(high, low, open_, close, self.window)

    @property
    def warmup_bars(self) -> int:
        return self.window

    @property
    def estimator_id(self) -> str:
        return f"rogers_satchell_w{self.window}"


@dataclass(frozen=True, slots=True)
class YangZhangEstimator:
    """Yang-Zhang (2000) -- mesmo status de extensão PÓS-M1 de
    `RogersSatchellEstimator` (ver docstring). `warmup_bars` é `window + 1`
    (não `window`): o componente overnight precisa de `close[i-1]`, mesmo
    tipo de +1 que `next_bar_realized_variance` (`volatility_walkforward.py`)
    aplica por precisar de `close[t+1]`."""

    window: int

    def estimate(self, bars: Bars, *, horizon_minutes: int) -> FloatArray:
        if bars.resolution_id is not None:
            raise NotImplementedError(
                "YangZhangEstimator ainda não foi readaptado pra grade "
                f"dollar-bar (resolution_id={bars.resolution_id!r}) -- ver "
                "AG-036, audit/architecture_gaps_log.yaml"
            )
        if horizon_minutes != bars.timeframe_minutes:
            raise NotImplementedError(
                "YangZhangEstimator so estima no horizonte nativo da barra "
                f"({bars.timeframe_minutes}min); horizon_minutes={horizon_minutes} "
                "pedido. Conversao clock-based entre TFs (I2) e escopo do M1."
            )
        high = bars.frame["high"].cast(pl.Float64).to_numpy()
        low = bars.frame["low"].cast(pl.Float64).to_numpy()
        open_ = bars.frame["open"].cast(pl.Float64).to_numpy()
        close = bars.frame["close"].cast(pl.Float64).to_numpy()
        return support.yang_zhang_vol(high, low, open_, close, self.window)

    @property
    def warmup_bars(self) -> int:
        return self.window + 1

    @property
    def estimator_id(self) -> str:
        return f"yang_zhang_w{self.window}"
