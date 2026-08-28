"""Varredura de higiene de proveniência dos 4 cutoffs do Regime Engine
(`regime_er_cutoff`/`regime_vol_cutoff` + variantes `_exit`) — achado
`AG-342` (`project_assurance`, 2026-08-27): os 4 são `class: A`/
`provenance: ASSUMED` desde a criação, `sweep_required: true`,
`review_by: sprint_5` — vencido há dezenas de sprints. Nunca rodou uma
varredura real (confirmado por busca ativa em `experiments/`/
`src/analysis/`).

**Escopo desta varredura — Opção 1 do mapa de arquitetura (2026-08-27),
decisão do chief architect, não a única opção listada lá:** grade GLOBAL
(não por-ativo — isso fica pra uma Opção 2 condicional, só se esta rodada
mostrar dispersão real entre símbolos), 2 graus de liberdade livres
(`er_cutoff_enter`/`vol_cutoff_enter`), os 2 cutoffs `_exit` DERIVADOS por
um gap de histerese fixo (medido dos valores de produção atuais, não
outro grau de liberdade solto — reduz 4 dimensões livres a 2). Não
reativa `control_01_regime_tradeavel` (desligado desde 2026-08-22,
`AG-259`) nem reabre `AG-244`/`AG-259` — mede só o que muda no próprio
Regime Engine (distribuição de regime, persistência, taxa de transição),
não decisão de risco.

**Ponto de injeção reusado, não um caminho novo**: `classifier.
classify_regimes` já aceita `thresholds` explícito — a grade inteira roda
sem tocar `constants.yaml` em nenhum momento da busca (só no relatório
final, como registro do que foi medido). `features_build.build_t1_features`
+ `stress.compute_stress_triggers` (as duas metades caras de IO) rodam UMA
vez por símbolo — nenhuma das 4 features de entrada (`B07_efficiency_
ratio_48`/`C07_vol_pctile_expanding`/`E02f_funding_z_expanding`/
`E27f_cost_atr_ratio`) nem os gatilhos de stress dependem dos cutoffs de
regime; só o laço de estado (`classify_regimes`) muda por ponto da grade.
Recomputar as duas por ponto seria custo de IO pago à toa 25x por símbolo.

**Deliberadamente FORA de escopo nesta 1a rodada** (não é lacuna
escondida): estabilidade do baseline B3 (`src.models.baselines.
run_b3_regime_only`) não é medida aqui — exigiria juntar com `labels`/
rodar backtest, e o objetivo desta rodada é só fechar a proveniência
`ASSUMED` dos 4 cutoffs com uma métrica que o próprio Regime Engine já
produz, sem cruzar pra `src/models/`. Se o Manager quiser o efeito no B3
depois, isso é uma extensão explícita, não parte desta medição.

Rodar: `uv run python -m src.analysis.regime_cutoff_sweep` — grava
`experiments/regime_cutoff_sweep_report.json`."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np
import orjson
import polars as pl
import structlog
from numpy.typing import NDArray

from src.analysis.m4_regime_comparison import ALL_SYMBOLS, END_DATE, SYMBOL_START_DATE
from src.features import build as features_build
from src.models._paths import EXPERIMENTS_DIR
from src.regime import stress as stress_mod
from src.regime._constants import _load_all, load_constant
from src.regime.classifier import (
    REGIME_LABELS,
    RegimeThresholds,
    classify_regimes,
)

logger = structlog.get_logger(__name__)

FloatArray = NDArray[np.float64]

BAR_SOURCE: str = "dollar_r1"
VOL_ESTIMATOR_ID: str = "parkinson_w20"

#: Nº de pontos por eixo da grade — parâmetro de METODOLOGIA desta
#: varredura (não constante de pipeline com proveniência própria; a
#: proveniência real está nos `sweep_range` DECLARADOS que a grade
#: percorre, lidos abaixo de `constants.yaml`).
N_GRID_POINTS = 5


@dataclass(frozen=True, slots=True)
class RegimeCutoffSweepCell:
    """1 célula da grade: 1 (símbolo, er_cutoff_enter, vol_cutoff_enter).
    Núcleo puro produz isto a partir de um `pl.DataFrame` já em memória —
    nenhuma chamada de IO aqui dentro."""

    symbol: str
    er_cutoff_enter: float
    er_cutoff_exit: float
    vol_cutoff_enter: float
    vol_cutoff_exit: float
    n_bars: int
    regime_fraction: dict[str, float]
    tradeable_fraction: float
    bars_in_regime_median: float
    bars_in_regime_p10: float
    bars_in_regime_p90: float
    n_transitions: int
    transitions_per_1000_bars: float


@dataclass(frozen=True, slots=True)
class RegimeCutoffSweepResult:
    bar_source: str
    vol_estimator_id: str
    symbols: tuple[str, ...]
    er_cutoff_enter_grid: tuple[float, ...]
    vol_cutoff_enter_grid: tuple[float, ...]
    er_hysteresis_gap: float
    vol_hysteresis_gap: float
    er_sweep_range_declared: tuple[float, float]
    vol_sweep_range_declared: tuple[float, float]
    production_er_cutoff_enter: float
    production_vol_cutoff_enter: float
    cells: tuple[RegimeCutoffSweepCell, ...]


def _linspace_grid(lo: float, hi: float, n: int) -> tuple[float, ...]:
    """Núcleo puro — `n` pontos igualmente espaçados em `[lo, hi]`,
    inclusive nas duas pontas. `n` ímpar inclui o ponto médio exato
    (é assim que a grade acaba incluindo o valor de produção atual,
    quando ele é o ponto médio do `sweep_range` declarado)."""
    if n < 2:
        raise ValueError(f"_linspace_grid: n deve ser >= 2, recebido {n}")
    step = (hi - lo) / (n - 1)  # noqa: unguarded-ratio — n>=2 garantido pelo raise acima, n-1>=1
    return tuple(round(lo + i * step, 10) for i in range(n))


def _summarize_regime_distribution(
    df: pl.DataFrame,
    *,
    symbol: str,
    er_cutoff_enter: float,
    er_cutoff_exit: float,
    vol_cutoff_enter: float,
    vol_cutoff_exit: float,
) -> RegimeCutoffSweepCell:
    """Núcleo puro (Idioma A) — recebe a saída já pronta de
    `classify_regimes` (colunas `regime`/`bars_in_regime`/`tradeable`) e
    resume em estatísticas cross-comparáveis entre símbolos/pontos da
    grade. Não lê disco, não conhece thresholds/produção — só sumariza o
    que já está no frame."""
    n_bars = df.height
    counts = df["regime"].value_counts().sort("regime")
    regime_fraction = {
        str(label): 0.0 for label in REGIME_LABELS
    }
    for row in counts.iter_rows(named=True):
        regime_fraction[str(row["regime"])] = (
            row["count"] / n_bars if n_bars > 0 else 0.0  # noqa: unguarded-ratio — guarda inline
        )

    tradeable_fraction = (
        float(df["tradeable"].mean()) if n_bars > 0 else float("nan")  # type: ignore[arg-type]
    )

    non_r0 = df.filter(pl.col("regime") != "R0")
    if non_r0.height > 0:
        bars_in_regime_median = float(non_r0["bars_in_regime"].median())  # type: ignore[arg-type]
        # p10/p90: escolha de relatório desta varredura (dispersão da
        # persistência), não parâmetro de decisão de pipeline -- sem
        # entrada em constants.yaml por não influenciar nenhuma decisão
        # de trade/gate. noqa: magic-number
        bars_in_regime_p10 = float(
            non_r0["bars_in_regime"].quantile(0.10, interpolation="linear")  # type: ignore[arg-type]  # noqa: magic-number
        )
        bars_in_regime_p90 = float(
            non_r0["bars_in_regime"].quantile(0.90, interpolation="linear")  # type: ignore[arg-type]  # noqa: magic-number
        )
    else:
        bars_in_regime_median = float("nan")
        bars_in_regime_p10 = float("nan")
        bars_in_regime_p90 = float("nan")

    regime_arr = df["regime"].to_numpy()
    n_transitions = int(np.sum(regime_arr[1:] != regime_arr[:-1])) if n_bars > 1 else 0
    # Escala de taxa de transição (por 1000 barras) -- unidade de
    # apresentação do relatório, não constante de pipeline; divisão
    # guardada pelo mesmo "if n_bars > 0" inline.
    transitions_per_1000_bars = (n_transitions / n_bars) * 1000.0 if n_bars > 0 else float("nan")  # noqa: magic-number — escala de apresentação // noqa: unguarded-ratio — guarda inline (n_bars > 0)

    return RegimeCutoffSweepCell(
        symbol=symbol,
        er_cutoff_enter=er_cutoff_enter,
        er_cutoff_exit=er_cutoff_exit,
        vol_cutoff_enter=vol_cutoff_enter,
        vol_cutoff_exit=vol_cutoff_exit,
        n_bars=n_bars,
        regime_fraction=regime_fraction,
        tradeable_fraction=tradeable_fraction,
        bars_in_regime_median=bars_in_regime_median,
        bars_in_regime_p10=bars_in_regime_p10,
        bars_in_regime_p90=bars_in_regime_p90,
        n_transitions=n_transitions,
        transitions_per_1000_bars=transitions_per_1000_bars,
    )


def _symbol_inputs(
    symbol: str, start: str, end: str
) -> tuple[FloatArray, FloatArray, FloatArray, stress_mod.StressResult, NDArray[np.int64]]:
    """Casca com IO — roda UMA vez por símbolo: carrega as 4 features de
    entrada do Regime Engine (`build_t1_features`, sem máscara de warmup,
    mesmo contrato de `src.regime.build.build_regimes`) e os gatilhos de
    stress. Nenhuma das duas depende de cutoff de regime — reuso across
    toda a grade de um símbolo, ver docstring do módulo."""
    features_df = features_build.build_t1_features(
        symbol,
        start,
        end,
        apply_warmup_mask=False,
        bar_source=BAR_SOURCE,
        vol_estimator_id=VOL_ESTIMATOR_ID,
        load_taker_imbalance_1m=False,
        load_futures_positioning=False,
    )
    open_time_ms = features_df["open_time"].cast(pl.Int64).to_numpy()
    er_48 = features_df["B07_efficiency_ratio_48"].cast(pl.Float64).to_numpy()
    vol_pctile = features_df["C07_vol_pctile_expanding"].cast(pl.Float64).to_numpy()
    funding_z = features_df["E02f_funding_z_expanding"].cast(pl.Float64).to_numpy()
    cost_atr_ratio = features_df["E27f_cost_atr_ratio"].cast(pl.Float64).to_numpy()
    close_time_ms = features_df["close_time"].cast(pl.Int64).to_numpy()

    filters_snapshots = stress_mod.discover_filters_hash_snapshots(symbol)
    stress_inputs = stress_mod.StressInputs(
        n=features_df.height,
        open_time_ms=open_time_ms,
        vol_pctile_expanding=vol_pctile,
        funding_z_expanding=funding_z,
        spread_pctile_expanding=None,
        filters_hash_snapshots=filters_snapshots,
        bar_source=BAR_SOURCE,
        close_time_ms=close_time_ms,
    )
    stress_result = stress_mod.compute_stress_triggers(stress_inputs)

    logger.info(
        "analysis.regime_cutoff_sweep.symbol_inputs_loaded",
        symbol=symbol,
        n_bars=features_df.height,
    )
    return er_48, vol_pctile, cost_atr_ratio, stress_result, open_time_ms


def run_regime_cutoff_sweep(
    symbols: tuple[str, ...] = ALL_SYMBOLS,
) -> RegimeCutoffSweepResult:
    """Casca — orquestra a grade completa. `min_common_history_bars=None`
    na base de thresholds: mesma regra de `src.regime.build.build_regimes`
    pra `bar_source != "time_15m"` (a constante foi calibrada em contagem
    de barra de TEMPO, não comparável cross-asset sob dollar bar)."""
    base_thresholds = replace(RegimeThresholds.from_constants(), min_common_history_bars=None)
    er_gap = round(base_thresholds.er_cutoff_enter - base_thresholds.er_cutoff_exit, 10)
    vol_gap = round(base_thresholds.vol_cutoff_enter - base_thresholds.vol_cutoff_exit, 10)

    _er_raw = _load_all()["regime_er_cutoff"]["sweep_range"]
    _vol_raw = _load_all()["regime_vol_cutoff"]["sweep_range"]
    _er_exit_raw = _load_all()["regime_er_cutoff_exit"]["sweep_range"]
    _vol_exit_raw = _load_all()["regime_vol_cutoff_exit"]["sweep_range"]
    er_range: tuple[float, float] = (float(_er_raw[0]), float(_er_raw[1]))
    vol_range: tuple[float, float] = (float(_vol_raw[0]), float(_vol_raw[1]))
    er_exit_range: tuple[float, float] = (float(_er_exit_raw[0]), float(_er_exit_raw[1]))
    vol_exit_range: tuple[float, float] = (float(_vol_exit_raw[0]), float(_vol_exit_raw[1]))

    er_grid = _linspace_grid(er_range[0], er_range[1], N_GRID_POINTS)
    vol_grid = _linspace_grid(vol_range[0], vol_range[1], N_GRID_POINTS)

    for er_enter in er_grid:
        er_exit = round(er_enter - er_gap, 10)
        if not (er_exit_range[0] <= er_exit <= er_exit_range[1]):
            raise ValueError(
                f"regime_cutoff_sweep: er_cutoff_exit derivado ({er_exit}) de "
                f"er_cutoff_enter={er_enter} cai fora do sweep_range declarado de "
                f"regime_er_cutoff_exit ({er_exit_range}) -- grade ou gap precisam de ajuste, "
                "não seguir adiante com um _exit fora da faixa aprovada"
            )
    for vol_enter in vol_grid:
        vol_exit = round(vol_enter - vol_gap, 10)
        if not (vol_exit_range[0] <= vol_exit <= vol_exit_range[1]):
            raise ValueError(
                f"regime_cutoff_sweep: vol_cutoff_exit derivado ({vol_exit}) de "
                f"vol_cutoff_enter={vol_enter} cai fora do sweep_range declarado de "
                f"regime_vol_cutoff_exit ({vol_exit_range}) -- grade ou gap precisam de ajuste"
            )

    cells: list[RegimeCutoffSweepCell] = []
    for symbol in symbols:
        start = SYMBOL_START_DATE[symbol]
        er_48, vol_pctile, cost_atr_ratio, stress_result, open_time_ms = _symbol_inputs(
            symbol, start, END_DATE
        )
        for er_enter in er_grid:
            er_exit = round(er_enter - er_gap, 10)
            for vol_enter in vol_grid:
                vol_exit = round(vol_enter - vol_gap, 10)
                thresholds = replace(
                    base_thresholds,
                    er_cutoff_enter=er_enter,
                    er_cutoff_exit=er_exit,
                    vol_cutoff_enter=vol_enter,
                    vol_cutoff_exit=vol_exit,
                )
                df = classify_regimes(
                    open_time_ms,
                    er_48,
                    vol_pctile,
                    cost_atr_ratio,
                    stress_result,
                    thresholds=thresholds,
                )
                cells.append(
                    _summarize_regime_distribution(
                        df,
                        symbol=symbol,
                        er_cutoff_enter=er_enter,
                        er_cutoff_exit=er_exit,
                        vol_cutoff_enter=vol_enter,
                        vol_cutoff_exit=vol_exit,
                    )
                )
        logger.info(
            "analysis.regime_cutoff_sweep.symbol_done",
            symbol=symbol,
            n_grid_points=len(er_grid) * len(vol_grid),
        )

    return RegimeCutoffSweepResult(
        bar_source=BAR_SOURCE,
        vol_estimator_id=VOL_ESTIMATOR_ID,
        symbols=tuple(symbols),
        er_cutoff_enter_grid=er_grid,
        vol_cutoff_enter_grid=vol_grid,
        er_hysteresis_gap=er_gap,
        vol_hysteresis_gap=vol_gap,
        er_sweep_range_declared=er_range,
        vol_sweep_range_declared=vol_range,
        production_er_cutoff_enter=float(load_constant("regime_er_cutoff")),
        production_vol_cutoff_enter=float(load_constant("regime_vol_cutoff")),
        cells=tuple(cells),
    )


def write_report_atomic(result: RegimeCutoffSweepResult) -> Path:
    """B29 -- `.tmp` -> `fsync` -> `rename`."""
    EXPERIMENTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = EXPERIMENTS_DIR / "regime_cutoff_sweep_report.json"
    payload: dict[str, Any] = {
        **{k: v for k, v in asdict(result).items() if k != "cells"},
        "cells": [asdict(c) for c in result.cells],
    }
    tmp_path = out_path.with_name(out_path.name + ".tmp")
    blob = orjson.dumps(payload, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS)
    with tmp_path.open("wb") as fh:
        fh.write(blob)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, out_path)
    logger.info(
        "analysis.regime_cutoff_sweep.report_written",
        path=str(out_path),
        n_cells=len(result.cells),
    )
    return out_path


def _run_cli() -> int:
    result = run_regime_cutoff_sweep()
    out_path = write_report_atomic(result)
    logger.info(
        "analysis.regime_cutoff_sweep.cli_done",
        n_symbols=len(result.symbols),
        n_cells=len(result.cells),
        report_path=str(out_path),
    )
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(_run_cli())
