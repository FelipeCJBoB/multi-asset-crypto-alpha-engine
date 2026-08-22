"""**NÃO é diagnóstico -- é a execução REAL de produção do AG-100.** Vive
em `tools/diagnostics/` só porque não existe outro diretório de scripts
operacionais no repo hoje -- mesma justificativa/precedente de
`run_ag124_production_reprocessing.py`.

Backfill de `labels/` pros 5 símbolos sob `resolution_id="R2"` e `"R3"`
(dollar-bar, Parkinson w20) -- decisão de escopo do Manager já tomada
(`AG-100`, `decisao_manager_2026-08-21`), condicionada à recalibração
causal do threshold dollar-bar (`AG-124`) ter fechado -- fechou
2026-08-22 (15/15 células reprocessadas, validação item 22 positiva).
`_BAR_SOURCE_BY_RESOLUTION` (`src/models/dataset.py`) já ganhou R2/R3
na mesma sessão.

Reusa `src.labels.backfill_multi_symbol.run_and_write_labels_dollar_bar_
parkinson` (função já existente, usada pra produzir os labels R1 reais
em 2026-08-17/18 -- `docs/refactor_parkinson_canonico.md`) -- nenhum
mecanismo novo, só os 2 resolution_id que faltavam. Escreve em
`data/labels/{symbol}/R2/v1/labels.parquet` e `.../R3/v1/`, paths novos,
zero colisão com R1 (guarda de `labels_symbol_tf_dir`).

`data/capacity/dollar_bars_r2/`/`dollar_bars_r3/` já existem calibrados
CAUSALMENTE (mesmo reprocessamento do AG-124 que cobriu R1) --
confirmado antes desta rodada, não precisa re-verificar.

Sequencial por resolução (R2 depois R3), mas cada resolução já paraleliza
internamente os 5 símbolos (`ProcessPoolExecutor`, mesmo padrão da função
reusada) -- não adiciona paralelismo próprio, evita competir CPU com o
paralelismo interno da própria função.

Isolamento de falha por resolução -- se R2 falhar, R3 ainda é tentado, e
o resumo final reporta o que teve sucesso (mesmo padrão AG-019/AG-124).

Rodar (pode levar tempo -- histórico completo, os 5 símbolos, roda em
background e monitorado):
    uv run python tools/diagnostics/run_ag100_labels_r2_r3_backfill.py \
        --out experiments/ag100_labels_r2_r3_backfill_summary.json
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any, Final

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import orjson
import structlog

from src.core.provenance import report_provenance
from src.labels.backfill_multi_symbol import (
    ALL_SYMBOLS,
    END_DATE,
    run_and_write_labels_dollar_bar_parkinson,
)

logger = structlog.get_logger(__name__)

_RESOLUTIONS: Final[tuple[str, ...]] = ("R2", "R3")


def backfill_all(*, dry_run: bool = False) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for resolution_id in _RESOLUTIONS:
        t0 = time.monotonic()
        logger.info(
            "diagnostics.run_ag100_labels_r2_r3_backfill.resolution_starting",
            resolution_id=resolution_id,
            n_symbols=len(ALL_SYMBOLS),
        )
        if dry_run:
            results.append(
                {"resolution_id": resolution_id, "status": "dry_run", "elapsed_s": 0.0}
            )
            continue
        try:
            written = run_and_write_labels_dollar_bar_parkinson(
                symbols=ALL_SYMBOLS, end=END_DATE, resolution_id=resolution_id
            )
            elapsed_s = time.monotonic() - t0
            results.append(
                {
                    "resolution_id": resolution_id,
                    "status": "ok",
                    "symbols_written": {k: str(v) for k, v in written.items()},
                    "elapsed_s": elapsed_s,
                }
            )
            logger.info(
                "diagnostics.run_ag100_labels_r2_r3_backfill.resolution_done",
                resolution_id=resolution_id,
                elapsed_s=elapsed_s,
                n_symbols=len(written),
            )
        except Exception as exc:  # isolamento de falha por resolução, mesmo padrão AG-019
            elapsed_s = time.monotonic() - t0
            results.append(
                {
                    "resolution_id": resolution_id,
                    "status": "error",
                    "error": str(exc),
                    "elapsed_s": elapsed_s,
                }
            )
            logger.error(
                "diagnostics.run_ag100_labels_r2_r3_backfill.resolution_failed",
                resolution_id=resolution_id,
                error=str(exc),
                elapsed_s=elapsed_s,
            )

    n_ok = sum(1 for r in results if r["status"] == "ok")
    return {
        **report_provenance(),
        "task": "ag100_labels_r2_r3_backfill",
        "dry_run": dry_run,
        "symbols": list(ALL_SYMBOLS),
        "resolutions": list(_RESOLUTIONS),
        "n_total": len(_RESOLUTIONS),
        "n_ok": n_ok,
        "n_error": len(_RESOLUTIONS) - n_ok,
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=None, help="Se informado, grava JSON aqui")
    parser.add_argument("--dry-run", action="store_true", help="Não escreve nada, só loga o plano")
    args = parser.parse_args()

    result = backfill_all(dry_run=args.dry_run)

    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_bytes(orjson.dumps(result, option=orjson.OPT_INDENT_2))
        logger.info("diagnostics.run_ag100_labels_r2_r3_backfill.written", out=str(args.out))

    logger.info(
        "diagnostics.run_ag100_labels_r2_r3_backfill.summary",
        n_ok=result["n_ok"],
        n_error=result["n_error"],
        n_total=result["n_total"],
    )


if __name__ == "__main__":
    main()
