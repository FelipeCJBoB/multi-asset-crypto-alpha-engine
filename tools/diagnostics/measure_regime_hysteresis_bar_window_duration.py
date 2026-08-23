"""Mede a duração REAL de relógio coberta por janelas de N barras
CONSECUTIVAS de dollar-bar, para os 3 N's que a histerese do Regime
Engine usa hoje (`regime_confirmation_bars`, `regime_stress_exit_
confirmation_bars`, `min_warmup_bars`) -- responde `AG-180`
(`audit/architecture_gaps_log.yaml`), D-04 de
`docs/regime_feature_engine_design_doc_2026-08-23.md`.

PENDENTE-DE-EXECUÇÃO-HUMANA -- Claude não executa `.py` (CLAUDE.md,
"Protocolo de execução"). Rodar com:

    uv run python tools/diagnostics/measure_regime_hysteresis_bar_window_duration.py

**Problema que motiva este script.** `_run_state_machine`
(`src/regime/classifier.py`) usa `regime_confirmation_bars`/
`regime_stress_exit_confirmation_bars`/`min_warmup_bars` como CONTAGEM DE
BARRA pra suavizar troca de regime (§4.5 do PRD: "mudança só é efetivada
após N barras consecutivas"). Sob grade de 15m isso é uma janela de
relógio FIXA (2 barras = 30min). Sob dollar-bar, a mesma contagem cobre
uma janela de relógio VARIÁVEL -- `docs/refactor_dollar_bar_
canonico.md:206-207` (2026-08-16) já suspeitava disso em prosa ("pode ser
40 segundos numa rajada"), nunca medido contra dado real. Este script
mede.

**Por que não é só `p1_duração_de_1_barra × N`.** Barras de dollar-bar
anomalamente rápidas tendem a se AGRUPAR (rajada de liquidez = várias
barras rápidas em sequência, não uma isolada) -- extrapolar o percentil
de UMA barra pra N barras assumiria independência que provavelmente não
existe, e poderia errar pra qualquer lado (mais otimista OU mais
pessimista que a realidade, dependendo do grau de agrupamento real). Este
script mede a janela de N barras CONSECUTIVAS diretamente
(`close_time[i+N-1] - open_time[i]`, pra todo `i` válido), sobre o dado
já persistido -- sem esse viés de extrapolação, mesmo princípio de "medir
o agregado real, não somar/multiplicar estatísticas marginais" já
aplicado em outros pontos do projeto (ex. `AG-092`, unidade de permutação
por episódio, não por barra).

**O que este script NÃO faz.** Não decide a fórmula de conversão
(contagem-de-barra fixa vs. relógio fixo vs. híbrido) nem edita
`regime_confirmation_bars`/`regime_stress_exit_confirmation_bars`/
`min_warmup_bars` -- só mede a distribuição real que qualquer decisão
precisa (B23: "faixa esperada inventada... -- TBD, medir"). Decisão fica
com o Manager, mesmo padrão de `measure_dollar_bar_duration_p99_by_
resolution.py`.

Saída: `experiments/regime_hysteresis_bar_window_duration.json` (escrita
atômica, B29)."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

# Script standalone -- mesmo padrão de measure_dollar_bar_duration_p99_
# by_resolution.py/measure_dollar_threshold_drift.py (achado real
# AG-049): sem isto, `from src...` falha com ModuleNotFoundError quando
# invocado por caminho direto.
_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import numpy as np
import orjson
import polars as pl
import structlog
from numpy.typing import NDArray

from src.analysis.volatility_comparison import SYMBOL_START_DATE
from src.core.provenance import report_provenance
from src.data._paths import CAPACITY_DIR
from src.data.build_dollar_bars import CALIBRATION_TF_BY_RESOLUTION
from src.regime._constants import load_constant

logger = structlog.get_logger(__name__)

IntArray = NDArray[np.int64]
FloatArray = NDArray[np.float64]

_DEST_PATH: Final[Path] = (
    _REPO_ROOT / "experiments" / "regime_hysteresis_bar_window_duration.json"
)
_PERCENTILES: Final[tuple[int, ...]] = (1, 5, 10, 25, 50, 75, 90, 95, 99)
# Combos com menos barras que isto (após excluir o leftover final) não
# produzem uma distribuição de janela confiável -- pulados com log
# explícito, nunca um número calculado sobre amostra degenerada.
_MIN_BARS_FOR_STATS: Final[int] = 30


@dataclass(slots=True, frozen=True)
class _HysteresisConstant:
    """Os 3 N's que a histerese do Regime Engine usa hoje -- lidos de
    `constants.yaml` (não hardcoded aqui: se o valor mudar, este script
    mede contra o valor REAL vigente, não um número congelado no
    momento em que foi escrito)."""

    label: str
    constant_name: str
    n_bars: int


def _load_hysteresis_constants() -> tuple[_HysteresisConstant, ...]:
    return (
        _HysteresisConstant(
            "regime_confirmation_bars",
            "regime_confirmation_bars",
            int(load_constant("regime_confirmation_bars")),
        ),
        _HysteresisConstant(
            "regime_stress_exit_confirmation_bars",
            "regime_stress_exit_confirmation_bars",
            int(load_constant("regime_stress_exit_confirmation_bars")),
        ),
        _HysteresisConstant(
            "min_warmup_bars", "min_warmup_bars", int(load_constant("min_warmup_bars"))
        ),
    )


@dataclass(slots=True, frozen=True)
class _WindowStats:
    n_windows: int
    mean_ms: float
    median_ms: float
    std_ms: float
    min_ms: float
    max_ms: float
    percentiles_ms: dict[str, float]


def _stats_from_window_durations(duration_ms: FloatArray) -> _WindowStats:
    percentiles = {f"p{p}": float(np.percentile(duration_ms, p)) for p in _PERCENTILES}
    return _WindowStats(
        n_windows=int(duration_ms.shape[0]),
        mean_ms=float(np.mean(duration_ms)),
        median_ms=float(np.median(duration_ms)),
        std_ms=float(np.std(duration_ms)),
        min_ms=float(np.min(duration_ms)),
        max_ms=float(np.max(duration_ms)),
        percentiles_ms=percentiles,
    )


def _source_name(resolution_id: str) -> str:
    # Mesma convenção de src.data.lake.query_dollar_bars/measure_dollar_
    # bar_duration_p99_by_resolution.py -- duplicada aqui de propósito,
    # script standalone.
    return f"dollar_bars_{resolution_id.lower()}"


def _load_symbol_resolution_frame(symbol: str, resolution_id: str) -> pl.DataFrame | None:
    symbol_dir = CAPACITY_DIR / _source_name(resolution_id) / symbol
    if not symbol_dir.is_dir():
        logger.warning(
            "diagnostics.measure_regime_hysteresis_bar_window_duration.symbol_dir_missing",
            symbol=symbol,
            resolution_id=resolution_id,
            path=str(symbol_dir),
        )
        return None
    files = sorted(symbol_dir.glob("*.parquet"))
    if not files:
        logger.warning(
            "diagnostics.measure_regime_hysteresis_bar_window_duration.no_parquet_files",
            symbol=symbol,
            resolution_id=resolution_id,
            path=str(symbol_dir),
        )
        return None
    return pl.concat([pl.read_parquet(f) for f in files]).sort("open_time")


def _drop_trailing_leftover_bar(
    frame: pl.DataFrame, symbol: str, resolution_id: str
) -> pl.DataFrame:
    """Mesmo achado de `measure_dollar_bar_duration_p99_by_resolution.py`
    -- a ÚLTIMA barra (por `open_time`) de uma janela de reprocessamento
    finita não é uma barra fechada por threshold, é o "leftover" que
    `bars.threshold_bars_finish` flusha incondicionalmente no fim de
    `build_dollar_bars_for_window`. Excluída ANTES de formar qualquer
    janela de N barras -- senão o leftover contaminaria a última janela
    de cada símbolo/resolução com uma barra que não representa cadência
    real."""
    last = frame.tail(1)
    logger.info(
        "diagnostics.measure_regime_hysteresis_bar_window_duration.leftover_bar_excluded",
        symbol=symbol,
        resolution_id=resolution_id,
        open_time=int(last["open_time"][0]),
        close_time=int(last["close_time"][0]),
        count=int(last["count"][0]),
    )
    return frame.head(frame.height - 1)


def _window_durations_ms(frame: pl.DataFrame, n_bars: int) -> FloatArray:
    """`duration[i] = close_time[i+n_bars-1] - open_time[i]` -- o relógio
    de parede coberto por `n_bars` barras CONSECUTIVAS começando em `i`,
    pra todo `i` válido (`0 <= i <= altura - n_bars`). `n_bars=1` reduz a
    `close_time[i] - open_time[i]` (duração de 1 barra só, caso trivial,
    não usado por este script mas mantido correto por construção)."""
    open_time = frame["open_time"].cast(pl.Int64).to_numpy()
    close_time = frame["close_time"].cast(pl.Int64).to_numpy()
    n = open_time.shape[0]
    if n < n_bars:
        return np.array([], dtype=np.float64)
    window_close = close_time[n_bars - 1 :]
    window_open = open_time[: n - n_bars + 1]
    duration_ms: FloatArray = (window_close - window_open).astype(np.float64)
    if np.any(duration_ms < 0):
        n_bad = int(np.sum(duration_ms < 0))
        raise ValueError(
            f"{n_bad} janela(s) de {n_bars} barra(s) com duration_ms<0 -- "
            "close_time da última barra anterior ao open_time da primeira é "
            "cronologicamente impossível, dado corrompido de verdade"
        )
    return duration_ms


def _stats_to_dict(stats: _WindowStats) -> dict[str, Any]:
    return {
        "n_windows": stats.n_windows,
        "mean_ms": round(stats.mean_ms, 1),
        "mean_minutes": round(stats.mean_ms / 60_000, 3),
        "median_ms": round(stats.median_ms, 1),
        "median_minutes": round(stats.median_ms / 60_000, 3),
        "std_ms": round(stats.std_ms, 1),
        "min_ms": stats.min_ms,
        "min_seconds": round(stats.min_ms / 1_000, 2),
        "max_ms": stats.max_ms,
        "max_hours": round(stats.max_ms / 3_600_000, 2),
        "percentiles_minutes": {k: round(v / 60_000, 4) for k, v in stats.percentiles_ms.items()},
        "p1_seconds": round(stats.percentiles_ms["p1"] / 1_000, 2),
        "p5_seconds": round(stats.percentiles_ms["p5"] / 1_000, 2),
    }


def main() -> None:
    symbols = tuple(SYMBOL_START_DATE)
    resolutions = tuple(CALIBRATION_TF_BY_RESOLUTION)
    hysteresis_constants = _load_hysteresis_constants()
    logger.info(
        "diagnostics.measure_regime_hysteresis_bar_window_duration.starting",
        n_symbols=len(symbols),
        resolutions=resolutions,
        hysteresis_constants={h.label: h.n_bars for h in hysteresis_constants},
    )

    results: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    frame_cache: dict[tuple[str, str], pl.DataFrame | None] = {}

    for resolution_id in resolutions:
        for symbol in symbols:
            cache_key = (symbol, resolution_id)
            if cache_key not in frame_cache:
                raw_frame = _load_symbol_resolution_frame(symbol, resolution_id)
                if raw_frame is None or raw_frame.height <= _MIN_BARS_FOR_STATS:
                    frame_cache[cache_key] = None
                    skipped.append(
                        {
                            "symbol": symbol,
                            "resolution_id": resolution_id,
                            "reason": (
                                "diretorio/parquet ausente"
                                if raw_frame is None
                                else f"n_bars<={_MIN_BARS_FOR_STATS} apos excluir leftover"
                            ),
                        }
                    )
                else:
                    frame_cache[cache_key] = _drop_trailing_leftover_bar(
                        raw_frame, symbol, resolution_id
                    )
            frame = frame_cache[cache_key]
            if frame is None:
                continue

            for hc in hysteresis_constants:
                duration_ms = _window_durations_ms(frame, hc.n_bars)
                if duration_ms.shape[0] == 0:
                    skipped.append(
                        {
                            "symbol": symbol,
                            "resolution_id": resolution_id,
                            "hysteresis_constant": hc.label,
                            "reason": f"menos de {hc.n_bars} barras disponiveis",
                        }
                    )
                    continue
                stats = _stats_from_window_durations(duration_ms)
                row = {
                    "symbol": symbol,
                    "resolution_id": resolution_id,
                    "calibration_tf": CALIBRATION_TF_BY_RESOLUTION[resolution_id],
                    "hysteresis_constant": hc.label,
                    "n_bars": hc.n_bars,
                    **_stats_to_dict(stats),
                }
                results.append(row)
                logger.info(
                    "diagnostics.measure_regime_hysteresis_bar_window_duration.combo_done",
                    symbol=symbol,
                    resolution_id=resolution_id,
                    hysteresis_constant=hc.label,
                    n_bars=hc.n_bars,
                    median_minutes=round(stats.median_ms / 60_000, 3),
                    p1_seconds=round(stats.percentiles_ms["p1"] / 1_000, 2),
                    max_hours=round(stats.max_ms / 3_600_000, 2),
                )

    if skipped:
        logger.warning(
            "diagnostics.measure_regime_hysteresis_bar_window_duration.combos_skipped",
            n_skipped=len(skipped),
            skipped=skipped,
        )

    # Referência: o que cada constante representa sob grade de 15m (fixo,
    # "time_15m" já é o comportamento de produção hoje) -- pra comparar
    # lado a lado com a distribuição medida sob dollar-bar acima.
    time_grade_reference = {
        h.label: {"n_bars": h.n_bars, "ms_under_15m": h.n_bars * 900_000}
        for h in hysteresis_constants
    }

    payload: dict[str, Any] = {
        **report_provenance(),
        "measurement_provenance": (
            "MEASURED -- duration[i] = close_time[i+n_bars-1] - open_time[i] sobre janelas "
            "REAIS de n_bars consecutivas, lido direto de data/capacity/dollar_bars_"
            "{r1,r2,r3}/{symbol}/*.parquet (schemas.DOLLAR_BARS_R1/R2/R3, já persistidos). "
            "Responde AG-180/docs/regime_feature_engine_design_doc_2026-08-23.md D-04 -- "
            "quanto tempo de relógio real regime_confirmation_bars/regime_stress_exit_"
            "confirmation_bars/min_warmup_bars cobrem sob dollar-bar, medido, não "
            "extrapolado de percentil de barra única (barras rápidas se agrupam em "
            "rajada, extrapolação assumiria independência que não está confirmada)."
        ),
        "symbols": list(symbols),
        "resolutions": list(resolutions),
        "hysteresis_constants": {h.label: h.n_bars for h in hysteresis_constants},
        "time_grade_reference": time_grade_reference,
        "skipped_combos": skipped,
        "results": results,
        "next_step": (
            "Manager revisa a tabela `results` (comparando contra `time_grade_reference`) e "
            "decide a fórmula de conversão de regime_confirmation_bars/regime_stress_exit_"
            "confirmation_bars/min_warmup_bars sob resolution_id (contagem de barra fixa? "
            "relógio fixo convertido pra barras via mediana? híbrido com piso mínimo?) -- "
            "B20/B23: nunca escolhido programaticamente aqui."
        ),
    }
    dest_path = _DEST_PATH
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest_path.with_name(dest_path.name + ".tmp")
    blob = orjson.dumps(payload, option=orjson.OPT_INDENT_2)
    with tmp_path.open("wb") as fh:
        fh.write(blob)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, dest_path)

    logger.info(
        "diagnostics.measure_regime_hysteresis_bar_window_duration.done",
        n_results=len(results),
        n_skipped=len(skipped),
        dest_path=str(dest_path),
    )


if __name__ == "__main__":
    main()
