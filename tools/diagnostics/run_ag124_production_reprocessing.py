"""**NÃO é diagnóstico -- é a execução REAL de produção do AG-124 (Fase
5, `docs/plano_acao_ag124_pos_auditoria_2026-08-21.md`).** Vive em
`tools/diagnostics/` só porque não existe outro diretório de scripts
operacionais no repo hoje -- não confundir com os demais scripts deste
diretório (todos leitura-only sobre amostra/tempdir).

Reprocessa `data/capacity/dollar_bars_r{1,2,3}/` REAL pros 5 símbolos,
histórico completo (`SYMBOL_START_DATE`/`END_DATE`,
`src.analysis.volatility_comparison` -- reusado, não duplicado), via
`build_dollar_bars_walkforward` (AG-124, recalibração causal rolante),
com `trailing_window_days`/`cadence_days` carregados de `config/
constants.yaml` (`dollar_bar_walkforward_trailing_window_days`/
`dollar_bar_walkforward_cadence_days` -- decisão do Manager, PROVISÓRIA,
ver `AG-124::addendum_RETRATACAO_teste_decisivo_2026-08-21`), nunca
hardcoded aqui (B23).

**`overwrite=True` sempre** -- `data/capacity/dollar_bars_r*/` real
reflete a calibração NÃO-causal antiga (calibrada sobre a janela inteira
sendo construída, o vazamento que o AG-124 existe pra corrigir) -- author
precisa ser substituído por completo, não mesclado.

**Sequencial, não concorrente** -- BTCUSDT sozinho já é ~3,4 bilhões de
trades; rodar os 15 pares (5 símbolos x 3 resoluções) concorrentemente
multiplicaria o pico de memória por processo simultâneo sem necessidade
(recomendação de engenharia registrada em `AG-124`, resolution original).

**Isolamento de falha por (símbolo, resolução)** -- mesmo padrão AG-019
(M4): 1 combinação que falhar (ex. gap de dado real) é logada e NÃO
derruba as outras 14. Resumo final reporta quais tiveram sucesso.

Rodar (pode levar HORAS -- histórico completo, os 5 símbolos, roda em
background e monitorado):
    uv run python tools/diagnostics/run_ag124_production_reprocessing.py \
        --out experiments/ag124_production_reprocessing_summary.json
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

from src.analysis.volatility_comparison import END_DATE, SYMBOL_START_DATE
from src.core.provenance import report_provenance
from src.data._constants import load_constant
from src.data.build_dollar_bars import CALIBRATION_TF_BY_RESOLUTION, build_dollar_bars_walkforward

logger = structlog.get_logger(__name__)

_RESOLUTIONS: Final[tuple[str, ...]] = tuple(sorted(CALIBRATION_TF_BY_RESOLUTION))


def reprocess_all(*, dry_run: bool = False) -> dict[str, Any]:
    trailing_window_days = int(load_constant("dollar_bar_walkforward_trailing_window_days"))
    cadence_days = int(load_constant("dollar_bar_walkforward_cadence_days"))

    results: list[dict[str, Any]] = []
    for symbol in SYMBOL_START_DATE:
        start = SYMBOL_START_DATE[symbol]
        end = END_DATE
        for resolution_id in _RESOLUTIONS:
            logger.info(
                "diagnostics.run_ag124_production_reprocessing.cell_start",
                symbol=symbol,
                resolution_id=resolution_id,
                start=start,
                end=end,
                trailing_window_days=trailing_window_days,
                cadence_days=cadence_days,
                dry_run=dry_run,
            )
            t_start = time.monotonic()
            if dry_run:
                results.append(
                    {
                        "symbol": symbol,
                        "resolution_id": resolution_id,
                        "start": start,
                        "end": end,
                        "status": "dry_run_skipped",
                    }
                )
                continue
            try:
                stats = build_dollar_bars_walkforward(
                    symbol,
                    start,
                    end,
                    resolution_id=resolution_id,
                    trailing_window_days=trailing_window_days,
                    cadence_days=cadence_days,
                    dest_root=None,
                )
                elapsed_s = time.monotonic() - t_start
                results.append(
                    {
                        "symbol": symbol,
                        "resolution_id": resolution_id,
                        "start": start,
                        "end": end,
                        "status": "ok",
                        "n_periods": stats.n_periods,
                        "n_cold_start_dropped": stats.n_cold_start_dropped,
                        "n_periods_written": stats.n_periods_written,
                        "calibration_hash": stats.calibration_identity.config_hash,
                        "elapsed_s": elapsed_s,
                    }
                )
                logger.info(
                    "diagnostics.run_ag124_production_reprocessing.cell_done",
                    symbol=symbol,
                    resolution_id=resolution_id,
                    n_periods=stats.n_periods,
                    n_periods_written=stats.n_periods_written,
                    n_cold_start_dropped=stats.n_cold_start_dropped,
                    elapsed_s=round(elapsed_s, 1),
                )
            except Exception as exc:
                elapsed_s = time.monotonic() - t_start
                results.append(
                    {
                        "symbol": symbol,
                        "resolution_id": resolution_id,
                        "start": start,
                        "end": end,
                        "status": "error",
                        "error": f"{type(exc).__name__}: {exc}",
                        "elapsed_s": elapsed_s,
                    }
                )
                logger.error(
                    "diagnostics.run_ag124_production_reprocessing.cell_failed",
                    symbol=symbol,
                    resolution_id=resolution_id,
                    error=f"{type(exc).__name__}: {exc}",
                    elapsed_s=round(elapsed_s, 1),
                )

    n_ok = sum(1 for r in results if r["status"] == "ok")
    n_error = sum(1 for r in results if r["status"] == "error")
    return {
        **report_provenance(),
        "trailing_window_days": trailing_window_days,
        "cadence_days": cadence_days,
        "dry_run": dry_run,
        "n_total": len(results),
        "n_ok": n_ok,
        "n_error": n_error,
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="lista as 15 combinações símbolo/resolução sem rodar (checagem de escopo)",
    )
    parser.add_argument(
        "--out", type=Path, default=None, help="Se informado, grava o resumo em JSON aqui"
    )
    args = parser.parse_args()

    result = reprocess_all(dry_run=args.dry_run)

    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_bytes(orjson.dumps(result, option=orjson.OPT_INDENT_2))
        logger.info(
            "diagnostics.run_ag124_production_reprocessing.written", out=str(args.out)
        )

    logger.info(
        "diagnostics.run_ag124_production_reprocessing.summary",
        n_total=result["n_total"],
        n_ok=result["n_ok"],
        n_error=result["n_error"],
        trailing_window_days=result["trailing_window_days"],
        cadence_days=result["cadence_days"],
    )


if __name__ == "__main__":
    main()
