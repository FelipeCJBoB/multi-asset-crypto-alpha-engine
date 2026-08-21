"""Mede p99 de duração de dollar-bar por (símbolo, resolução) real -- C.2
do plano de migração `horizon_bars` (AG-116, `PLANO_MESTRE_PRINCE2.md`
§15.12.3-A item 3 / §15.12.3-C.2).

PENDENTE-DE-EXECUÇÃO-HUMANA -- Claude não executa `.py` (CLAUDE.md,
"Protocolo de execução"). Rodar com:

    uv run python tools/diagnostics/measure_dollar_bar_duration_p99_by_resolution.py

**Problema que motiva este script.** `build_labels_for_symbol` (`src/
labels/triple_barrier.py`, `_resolve_prefetch_horizon_ms`) precisa
dimensionar a folga de prefetch de `mark_1m`/`funding` além de `end` sob
`resolution_id` (dollar bar) -- desde AG-116 o horizonte da barreira TIME
é `cfg.horizon_bars` barras à frente da decisão (contagem de barra), não
mais um relógio fixo (`time_stop_ms`, agora vestigial sob
`resolution_id`). Quanto relógio real `horizon_bars` barras futuras vão
cobrir depende de quão rápido o threshold de dollar acumula -- variável
por (símbolo, resolução), sem teto a priori (`PLANO_MESTRE_PRINCE2.md`
§15.12.3-C.2, abordagem aprovada: percentil alto MEDIDO da distribuição
REAL, não estipulado).

`experiments/dollar_bar_duration_distribution.json` (`tools/diagnostics/
measure_dollar_bar_duration_distribution.py`) já mede exatamente isso
(`duration_ms = close_time - open_time` por barra, real, sem recalcular
nada), mas só para `R1` (`data/capacity/dollar_bars_r1/`, hardcoded no
script) -- não tem granularidade por resolução que baste pra `R2`/`R3`
(achado ao ler aquele script antes de escrever este, 2026-08-20). Este
script generaliza a MESMA metodologia pras 3 resoluções (`R1`/`R2`/`R3`,
`src.data.build_dollar_bars.CALIBRATION_TF_BY_RESOLUTION`), reportando
p99 (+ contexto: mean/median/std/min/max/outros percentis) por (símbolo,
resolução) -- 15 combinações (5 símbolos × 3 resoluções).

**O que este script NÃO faz.** Não escreve em `constants.yaml` sozinho --
imprime/persiste a tabela completa; transcrever o(s) valor(es) finais
(`label_prefetch_p99_bar_duration_ms_placeholder`, ou constantes
granulares por resolução se o Manager decidir expandir depois de ver os
números reais) é decisão humana, mesmo padrão de `recalibrate_bocpd_
hazard_lambda_pretest.py` (B20: threshold nunca escolhido
programaticamente depois de ver o resultado). Até este script rodar,
`build_labels_for_symbol` usa um placeholder CONSERVADOR explicitamente
marcado como tal (`label_prefetch_p99_bar_duration_ms_placeholder`,
ASSUMED, `constants.yaml`) -- ver `_resolve_prefetch_horizon_ms` em
`src/labels/triple_barrier.py` e AG-116/`PLANO_MESTRE_PRINCE2.md`
§15.12.3.

Saída: `experiments/dollar_bar_duration_p99_by_resolution.json` (escrita
atômica, B29)."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

# Script standalone -- mesmo padrão de measure_dollar_bar_duration_
# distribution.py/measure_dollar_threshold_drift.py (achado real
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

logger = structlog.get_logger(__name__)

FloatArray = NDArray[np.float64]

_DEST_PATH: Final[Path] = (
    _REPO_ROOT / "experiments" / "dollar_bar_duration_p99_by_resolution.json"
)
_PERCENTILES: Final[tuple[int, ...]] = (1, 5, 10, 25, 50, 75, 90, 95, 99)
# Combos com menos barras que isto (após excluir o leftover final) não
# produzem um p99 confiável -- pulados com log explícito (skipped_combos
# no payload), nunca um número calculado sobre amostra degenerada.
_MIN_BARS_FOR_STATS: Final[int] = 30


@dataclass(slots=True, frozen=True)
class _DurationStats:
    n_bars: int
    mean_ms: float
    median_ms: float
    std_ms: float
    min_ms: float
    max_ms: float
    percentiles_ms: dict[str, float]


def _stats_from_durations(duration_ms: FloatArray) -> _DurationStats:
    percentiles = {f"p{p}": float(np.percentile(duration_ms, p)) for p in _PERCENTILES}
    return _DurationStats(
        n_bars=int(duration_ms.shape[0]),
        mean_ms=float(np.mean(duration_ms)),
        median_ms=float(np.median(duration_ms)),
        std_ms=float(np.std(duration_ms)),
        min_ms=float(np.min(duration_ms)),
        max_ms=float(np.max(duration_ms)),
        percentiles_ms=percentiles,
    )


def _source_name(resolution_id: str) -> str:
    # Mesma convenção de src.data.build_dollar_bars._dest_root_name/
    # src.data.lake.query_dollar_bars (f"dollar_bars_{resolution_id.
    # lower()}") -- duplicada aqui de propósito, script standalone, mesmo
    # padrão de measure_dollar_bar_duration_distribution.py.
    return f"dollar_bars_{resolution_id.lower()}"


def _load_symbol_resolution_frame(symbol: str, resolution_id: str) -> pl.DataFrame | None:
    symbol_dir = CAPACITY_DIR / _source_name(resolution_id) / symbol
    if not symbol_dir.is_dir():
        logger.warning(
            "diagnostics.measure_dollar_bar_duration_p99_by_resolution.symbol_dir_missing",
            symbol=symbol,
            resolution_id=resolution_id,
            path=str(symbol_dir),
        )
        return None
    files = sorted(symbol_dir.glob("*.parquet"))
    if not files:
        logger.warning(
            "diagnostics.measure_dollar_bar_duration_p99_by_resolution.no_parquet_files",
            symbol=symbol,
            resolution_id=resolution_id,
            path=str(symbol_dir),
        )
        return None
    return pl.concat([pl.read_parquet(f) for f in files]).sort("open_time")


def _drop_trailing_leftover_bar(
    frame: pl.DataFrame, symbol: str, resolution_id: str
) -> pl.DataFrame:
    """Mesmo achado de `measure_dollar_bar_duration_distribution.py`
    (`_drop_trailing_leftover_bar`) -- a ÚLTIMA barra (por `open_time`) de
    uma janela de reprocessamento finita não é uma barra fechada por
    threshold, é o "leftover" que `bars.threshold_bars_finish` flusha
    incondicionalmente no fim de `build_dollar_bars_for_window`. Mesmo
    raciocínio, generalizado por resolução (não é um fato específico de
    R1)."""
    last = frame.tail(1)
    logger.info(
        "diagnostics.measure_dollar_bar_duration_p99_by_resolution.leftover_bar_excluded",
        symbol=symbol,
        resolution_id=resolution_id,
        open_time=int(last["open_time"][0]),
        close_time=int(last["close_time"][0]),
        count=int(last["count"][0]),
    )
    return frame.head(frame.height - 1)


def _load_symbol_durations(frame: pl.DataFrame, symbol: str, resolution_id: str) -> FloatArray:
    """Mesma guarda de `measure_dollar_bar_duration_distribution.py` --
    `duration_ms == 0` é dado VÁLIDO sob rajada de liquidez real (AG-061,
    confirmado pra R1/SOLUSDT: várias barras podem fechar dentro do MESMO
    milissegundo sob atividade extrema); só `duration_ms < 0` é corrupção
    de verdade (cronologicamente impossível)."""
    open_time = frame["open_time"].cast(pl.Int64).to_numpy()
    close_time = frame["close_time"].cast(pl.Int64).to_numpy()
    duration_ms: FloatArray = (close_time - open_time).astype(np.float64)
    if np.any(duration_ms < 0):
        n_bad = int(np.sum(duration_ms < 0))
        raise ValueError(
            f"{symbol}/{resolution_id}: {n_bad} barra(s) com duration_ms<0 -- "
            "close_time anterior a open_time é cronologicamente impossível, dado "
            "corrompido de verdade"
        )
    return duration_ms


def _stats_to_dict(stats: _DurationStats) -> dict[str, Any]:
    return {
        "n_bars": stats.n_bars,
        "mean_ms": round(stats.mean_ms, 1),
        "mean_minutes": round(stats.mean_ms / 60_000, 3),
        "median_ms": round(stats.median_ms, 1),
        "median_minutes": round(stats.median_ms / 60_000, 3),
        "std_ms": round(stats.std_ms, 1),
        "min_ms": stats.min_ms,
        "max_ms": stats.max_ms,
        "max_hours": round(stats.max_ms / 3_600_000, 2),
        "p99_ms": round(stats.percentiles_ms["p99"], 1),
        "p99_minutes": round(stats.percentiles_ms["p99"] / 60_000, 3),
        "percentiles_minutes": {
            k: round(v / 60_000, 3) for k, v in stats.percentiles_ms.items()
        },
    }


def main() -> None:
    symbols = tuple(SYMBOL_START_DATE)
    resolutions = tuple(CALIBRATION_TF_BY_RESOLUTION)
    logger.info(
        "diagnostics.measure_dollar_bar_duration_p99_by_resolution.starting",
        n_symbols=len(symbols),
        resolutions=resolutions,
    )

    results: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for resolution_id in resolutions:
        for symbol in symbols:
            raw_frame = _load_symbol_resolution_frame(symbol, resolution_id)
            if raw_frame is None or raw_frame.height <= _MIN_BARS_FOR_STATS:
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
                continue
            frame = _drop_trailing_leftover_bar(raw_frame, symbol, resolution_id)
            duration_ms = _load_symbol_durations(frame, symbol, resolution_id)
            stats = _stats_from_durations(duration_ms)
            row = {
                "symbol": symbol,
                "resolution_id": resolution_id,
                "calibration_tf": CALIBRATION_TF_BY_RESOLUTION[resolution_id],
                "n_bars_total_incl_leftover": raw_frame.height,
                **_stats_to_dict(stats),
            }
            results.append(row)
            logger.info(
                "diagnostics.measure_dollar_bar_duration_p99_by_resolution.symbol_done",
                symbol=symbol,
                resolution_id=resolution_id,
                n_bars=stats.n_bars,
                p99_minutes=round(stats.percentiles_ms["p99"] / 60_000, 2),
                max_hours=round(stats.max_ms / 3_600_000, 2),
            )

    if skipped:
        logger.warning(
            "diagnostics.measure_dollar_bar_duration_p99_by_resolution.combos_skipped",
            n_skipped=len(skipped),
            skipped=skipped,
        )

    payload: dict[str, Any] = {
        **report_provenance(),
        "measurement_provenance": (
            "MEASURED -- duration_ms = close_time - open_time por barra, lido direto de "
            "data/capacity/dollar_bars_{r1,r2,r3}/{symbol}/*.parquet (schemas.DOLLAR_BARS_"
            "R1/R2/R3, já persistidos). Generaliza measure_dollar_bar_duration_"
            "distribution.py (só R1) pras 3 resoluções -- responde AG-116/"
            "PLANO_MESTRE_PRINCE2.md §15.12.3-C.2 (folga de prefetch de mark_1m/funding "
            "em build_labels_for_symbol sob resolution_id, "
            "_resolve_prefetch_horizon_ms em src/labels/triple_barrier.py)."
        ),
        "symbols": list(symbols),
        "resolutions": list(resolutions),
        "skipped_combos": skipped,
        "results": results,
        "next_step": (
            "Manager revisa a tabela `results` e decide o(s) valor(es) finais de "
            "label_prefetch_p99_bar_duration_ms_placeholder (constants.yaml) -- "
            "substituindo o placeholder ASSUMED atual por MEASURED, com "
            "provenance/source atualizados citando este arquivo. B20: nunca "
            "escolhido programaticamente aqui."
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
        "diagnostics.measure_dollar_bar_duration_p99_by_resolution.done",
        n_results=len(results),
        n_skipped=len(skipped),
        dest_path=str(dest_path),
    )


if __name__ == "__main__":
    main()
