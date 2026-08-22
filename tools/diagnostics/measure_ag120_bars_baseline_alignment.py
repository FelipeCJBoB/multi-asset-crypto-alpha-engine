"""Varredura de integridade dedicada -- AG-124/item 13 (B0)
(`docs/plano_acao_ag124_pos_auditoria_2026-08-21.md`), causa raiz do
`AG-120` (`audit/architecture_gaps_log.yaml`).

`AG-120` registrou 1 célula (BNBUSDT/RECENTE/R2) onde `bars_df`
(`lake.query_dollar_bars`) e `baseline_df` (`src.regime.build.
build_regimes`) -- que deveriam produzir a MESMA grade de timestamp pro
mesmo `(symbol, start, end, resolution_id)` -- divergiram (`t0` de
`baseline_df` != `open_time` de `bars_df` em pelo menos uma posição,
mesma checagem de `src.analysis.m4_regime_comparison._assert_bars_
baseline_aligned`), isolada com sucesso mas nunca investigada a fundo.

Este script reproduz a MESMA checagem em TODAS as ~90 células da
varredura original (`CRITICAL_WINDOWS` x 5 símbolos x 3 resoluções, com
a mesma cobertura por janela que o M4 usou -- `m4_critical_windows.
CRITICAL_WINDOWS`), mas SÓ a checagem de alinhamento (não a comparação
de regime completa -- HMM/Jump/BOCPD não são ajustados aqui, custo bem
menor que rodar o M4 inteiro de novo). Objetivo: (1) achar se há OUTRAS
células afetadas além da já conhecida, (2) pra cada célula que diverge,
diagnosticar ONDE a primeira divergência ocorre (índice, timestamps dos
dois lados, delta) -- suficiente pra decidir se é (a) gap de backfill
pontual, (b) bug de fronteira em `build_regimes`/`compute_t1_features`
sob alguma resolução específica, ou (c) outra causa. Roda só sobre dado
REAL já em `data/capacity/` -- leitura pura, não escreve nada."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Final

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import numpy as np
import orjson
import polars as pl
import structlog

from src.analysis.m4_critical_windows import CRITICAL_WINDOWS
from src.core.provenance import report_provenance
from src.data import lake
from src.regime.build import build_regimes

logger = structlog.get_logger(__name__)

_RESOLUTIONS: Final[tuple[str, ...]] = ("R1", "R2", "R3")
_BAR_SOURCE_BY_RESOLUTION: Final[dict[str, str]] = {
    "R1": "dollar_r1",
    "R2": "dollar_r2",
    "R3": "dollar_r3",
}


def _check_cell(symbol: str, start: str, end: str, resolution_id: str) -> dict[str, Any]:
    bars_df = lake.query_dollar_bars(symbol, start, end, resolution_id=resolution_id)
    baseline_df = build_regimes(
        symbol, start, end, bar_source=_BAR_SOURCE_BY_RESOLUTION[resolution_id]
    )

    result: dict[str, Any] = {
        "symbol": symbol,
        "start": start,
        "end": end,
        "resolution_id": resolution_id,
        "n_bars": bars_df.height,
        "n_baseline": baseline_df.height,
        "aligned": None,
        "failure_mode": None,
        "first_mismatch_index": None,
        "first_mismatch_bars_open_time_ms": None,
        "first_mismatch_baseline_t0_ms": None,
        "first_mismatch_delta_ms": None,
        "n_mismatched_positions": None,
    }

    if bars_df.height != baseline_df.height:
        result["aligned"] = False
        result["failure_mode"] = "height_mismatch"
        return result

    if bars_df.height == 0:
        result["aligned"] = True
        result["failure_mode"] = "empty_cell"
        return result

    bars_open_time_ms = bars_df["open_time"].cast(pl.Int64).to_numpy()
    baseline_t0_ms = (
        baseline_df["t0"].dt.epoch(time_unit="ms").to_numpy().astype(np.int64)
    )
    mismatch_mask = bars_open_time_ms != baseline_t0_ms
    n_mismatched = int(mismatch_mask.sum())

    if n_mismatched == 0:
        result["aligned"] = True
        result["failure_mode"] = None
        return result

    first_idx = int(np.argmax(mismatch_mask))
    result["aligned"] = False
    result["failure_mode"] = "value_mismatch"
    result["first_mismatch_index"] = first_idx
    result["first_mismatch_bars_open_time_ms"] = int(bars_open_time_ms[first_idx])
    result["first_mismatch_baseline_t0_ms"] = int(baseline_t0_ms[first_idx])
    result["first_mismatch_delta_ms"] = int(
        baseline_t0_ms[first_idx] - bars_open_time_ms[first_idx]
    )
    result["n_mismatched_positions"] = n_mismatched
    return result


def sweep() -> dict[str, Any]:
    cells: list[dict[str, Any]] = []
    for window in CRITICAL_WINDOWS:
        for symbol in window.symbols:
            for resolution_id in _RESOLUTIONS:
                try:
                    cell = _check_cell(symbol, window.start, window.end, resolution_id)
                    cell["window"] = window.name
                except Exception as exc:
                    # varredura de diagnóstico -- uma célula que falha (ex. dado ausente)
                    # não deve derrubar as outras ~89, mesmo padrão de isolamento do AG-019
                    cell = {
                        "symbol": symbol,
                        "start": window.start,
                        "end": window.end,
                        "resolution_id": resolution_id,
                        "window": window.name,
                        "aligned": None,
                        "failure_mode": f"exception: {type(exc).__name__}: {exc}",
                    }
                cells.append(cell)
                logger.info(
                    "diagnostics.measure_ag120_bars_baseline_alignment.cell_done",
                    window=cell.get("window"),
                    symbol=cell["symbol"],
                    resolution_id=cell["resolution_id"],
                    aligned=cell.get("aligned"),
                    failure_mode=cell.get("failure_mode"),
                    n_mismatched_positions=cell.get("n_mismatched_positions"),
                )

    n_total = len(cells)
    n_aligned = sum(1 for c in cells if c.get("aligned") is True)
    n_misaligned = sum(1 for c in cells if c.get("aligned") is False)
    n_errored = sum(1 for c in cells if c.get("aligned") is None)
    misaligned_cells = [c for c in cells if c.get("aligned") is False]

    return {
        **report_provenance(),
        "n_total_cells": n_total,
        "n_aligned": n_aligned,
        "n_misaligned": n_misaligned,
        "n_errored": n_errored,
        "misaligned_cells": misaligned_cells,
        "all_cells": cells,
        "methodology": (
            "Reproduz src.analysis.m4_regime_comparison._assert_bars_baseline_aligned "
            "(bars_df.open_time vs baseline_df.t0, elementwise) em toda célula "
            "(CRITICAL_WINDOWS x symbols x R1/R2/R3), sem ajustar nenhum candidato de "
            "regime (HMM/Jump/BOCPD) -- só a checagem de grade, custo bem menor que "
            "rodar o M4 inteiro. Dado real de data/capacity/, leitura pura."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", type=Path, default=None, help="Se informado, grava o resultado em JSON aqui"
    )
    args = parser.parse_args()

    result = sweep()

    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_bytes(orjson.dumps(result, option=orjson.OPT_INDENT_2))
        logger.info(
            "diagnostics.measure_ag120_bars_baseline_alignment.written", out=str(args.out)
        )

    logger.info(
        "diagnostics.measure_ag120_bars_baseline_alignment.summary",
        n_total_cells=result["n_total_cells"],
        n_aligned=result["n_aligned"],
        n_misaligned=result["n_misaligned"],
        n_errored=result["n_errored"],
        misaligned_cells=result["misaligned_cells"],
    )


if __name__ == "__main__":
    main()
