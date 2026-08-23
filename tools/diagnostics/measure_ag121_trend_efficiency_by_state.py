"""Testa a hipótese "tendência ordeira vs. caótica" levantada sobre as 4
células de discordância MÉDIA×DESVIO-PADRÃO de `hmm_gaussian_k4_v1` em
`RECENTE` (`AG-121`, achado de `compare_canonicalization_criterion_
media_vs_desvio.py`): o estado escolhido como "mais volátil" pela MÉDIA
de `realized_vol_short` é sempre o mesmo estado de maior retorno médio;
o escolhido pelo DESVIO-PADRÃO é outro, tipicamente de retorno menor.
Hipótese não testada até aqui (opinião, não medição): o estado de maior
retorno em `RECENTE` é um estado de "subida ordeira" (retorno grande MAS
consistente, direcional) -- vol MÉDIA alta captura isso; o estado
escolhido pelo desvio-padrão é "caótico/errático" (vol que oscila muito
dentro do próprio estado, sem direção líquida) -- por isso os dois
critérios discordam de verdade, não por ruído.

PENDENTE-DE-EXECUÇÃO-HUMANA -- Claude não executa `.py` (CLAUDE.md,
"Protocolo de execução"). Rodar com:

    uv run python tools/diagnostics/measure_ag121_trend_efficiency_by_state.py

**Métrica usada -- Efficiency Ratio (Kaufman, "Smarter Trading", 1995),
padrão de literatura de TA pra distinguir tendência suave de ruído
lateral, não inventada aqui:**

    ER = |soma(log_return)| / soma(|log_return|)

por `canonical_id`, sobre as barras atribuídas àquele estado (não exige
contiguidade temporal -- é razão de deslocamento líquido sobre
deslocamento bruto, válida mesmo com barras do mesmo estado espalhadas
no tempo). ER perto de 1 = quase toda a variação bruta foi na MESMA
direção (ordeiro); ER perto de 0 = a variação bruta se cancelou (chop).

**Dado usado -- sem re-fit, sem medição nova (B23).** `canonical_id`/
`close_time_ms` de `experiments/m4_raw_labels/{resolution}/{window}/
{symbol}/{classifier_id}.parquet` (já persistido, mesmo dado do script
irmão `compare_canonicalization_criterion_media_vs_desvio.py`) joinado
com `log_return` derivado de `close` em `data/capacity/dollar_bars_r{N}/
{symbol}/*.parquet` (mesmo dado bruto, mesma convenção de leitura de
`measure_max_consecutive_bar_window_duration.py`) por `close_time`/
`close_time_ms`. `realized_vol_short` também rejuntado (mesma fonte do
script irmão) só para cross-referenciar mean_vol/std_vol já conhecidos
na mesma linha de saída -- não recalculado.

**O que este script NÃO faz.** Não decide o critério final de
`canonicalize_states` (isso já foi decidido -- MÉDIA, `AG-121`) e não
reabre essa decisão. Só testa se a divergência MÉDIA×DESVIO-PADRÃO tem
uma explicação econômica (tendência vs. chop) ou é artefato -- resultado
vira ressalva documentada no achado, não gate novo.

Saída: `experiments/ag121_trend_efficiency_by_state.json` (escrita
atômica, B29) -- por (resolution_id, window_name, symbol, classifier_id,
canonical_id): `n_bars`, `mean_log_return`, `efficiency_ratio`,
`mean_vol`, `std_vol` (rejuntados do script irmão via nova leitura, não
lidos do JSON dele). Resumo: para as células onde MÉDIA e DESVIO-PADRÃO
discordam sobre o estado mais volátil, `efficiency_ratio` do estado
escolhido pela MÉDIA vs. do estado escolhido pelo DESVIO-PADRÃO,
lado a lado."""

from __future__ import annotations

import os
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

from src.core.provenance import report_provenance

logger = structlog.get_logger(__name__)

_RAW_LABELS_DIR: Final[Path] = _REPO_ROOT / "experiments" / "m4_raw_labels"
_FORWARD_VOL_HISTORY_DIR: Final[Path] = _REPO_ROOT / "experiments" / "m4_forward_vol_history"
_CAPACITY_DIR: Final[Path] = _REPO_ROOT / "data" / "capacity"
_DEST_PATH: Final[Path] = (
    _REPO_ROOT / "experiments" / "ag121_trend_efficiency_by_state.json"
)
_EXCLUDED_CLASSIFIER_IDS: Final[frozenset[str]] = frozenset({"quantile_regime_v1"})
_MIN_BARS_PER_STATE: Final[int] = 30


def _source_name(resolution_id: str) -> str:
    # Mesma convenção de src.data.build_dollar_bars/src.data.lake.
    # query_dollar_bars -- duplicada aqui de propósito, mesmo padrão dos
    # irmãos deste diretório (measure_max_consecutive_bar_window_
    # duration.py).
    return f"dollar_bars_{resolution_id.lower()}"


def _load_returns(symbol: str, resolution_id: str) -> pl.DataFrame | None:
    symbol_dir = _CAPACITY_DIR / _source_name(resolution_id) / symbol
    if not symbol_dir.is_dir():
        return None
    files = sorted(symbol_dir.glob("*.parquet"))
    if not files:
        return None
    bars = pl.concat([pl.read_parquet(f) for f in files]).sort("open_time")
    bars = bars.with_columns(
        (pl.col("close").log() - pl.col("close").shift(1).log()).alias("log_return")
    ).drop_nulls("log_return")
    return bars.select(
        pl.col("close_time").alias("close_time_ms"),
        "log_return",
    )


def _forward_vol_history_path(resolution_id: str, symbol: str) -> Path:
    return _FORWARD_VOL_HISTORY_DIR / resolution_id / f"{symbol}.parquet"


def _compute_one_cell(
    raw_labels_path: Path, resolution_id: str, symbol: str
) -> list[dict[str, Any]] | None:
    returns = _load_returns(symbol, resolution_id)
    if returns is None:
        logger.warning(
            "diagnostics.ag121_trend_efficiency.returns_missing",
            resolution_id=resolution_id,
            symbol=symbol,
        )
        return None

    vol_history_path = _forward_vol_history_path(resolution_id, symbol)
    if not vol_history_path.is_file():
        return None
    vol_history = pl.read_parquet(vol_history_path).select("close_time_ms", "realized_vol_short")

    labels = pl.read_parquet(raw_labels_path).select("close_time_ms", "canonical_id")
    joined = labels.join(returns, on="close_time_ms", how="inner").join(
        vol_history, on="close_time_ms", how="inner"
    )
    if joined.height == 0:
        return None

    per_state = (
        joined.group_by("canonical_id")
        .agg(
            pl.len().alias("n_bars"),
            pl.col("log_return").mean().alias("mean_log_return"),
            pl.col("log_return").sum().alias("sum_log_return"),
            pl.col("log_return").abs().sum().alias("sum_abs_log_return"),
            pl.col("realized_vol_short").mean().alias("mean_vol"),
            pl.col("realized_vol_short").std(ddof=1).alias("std_vol"),
        )
        .sort("canonical_id")
    )
    per_state = per_state.filter(pl.col("n_bars") >= _MIN_BARS_PER_STATE)
    if per_state.height == 0:
        return None

    rows = []
    for row in per_state.iter_rows(named=True):
        sum_abs = row["sum_abs_log_return"]
        efficiency_ratio = (
            float(abs(row["sum_log_return"]) / sum_abs) if sum_abs > 0.0 else None
        )
        rows.append(
            {
                "canonical_id": int(row["canonical_id"]),
                "n_bars": int(row["n_bars"]),
                "mean_log_return": round(float(row["mean_log_return"]), 8),
                "efficiency_ratio": (
                    round(efficiency_ratio, 4) if efficiency_ratio is not None else None
                ),
                "mean_vol": round(float(row["mean_vol"]), 6),
                "std_vol": (
                    round(float(row["std_vol"]), 6) if row["std_vol"] is not None else None
                ),
            }
        )
    return rows


def main() -> None:
    if not _RAW_LABELS_DIR.is_dir():
        logger.warning("diagnostics.ag121_trend_efficiency.raw_labels_dir_missing")
        results: list[dict[str, Any]] = []
    else:
        results = []
        for raw_labels_path in sorted(_RAW_LABELS_DIR.rglob("*.parquet")):
            classifier_id = raw_labels_path.stem
            if classifier_id in _EXCLUDED_CLASSIFIER_IDS:
                continue
            symbol = raw_labels_path.parent.name
            window_name = raw_labels_path.parent.parent.name
            resolution_id = raw_labels_path.parent.parent.parent.name

            per_state_rows = _compute_one_cell(raw_labels_path, resolution_id, symbol)
            if per_state_rows is None:
                continue

            mean_vol = np.array([r["mean_vol"] for r in per_state_rows])
            std_vol = np.array(
                [r["std_vol"] if r["std_vol"] is not None else -np.inf for r in per_state_rows]
            )
            highest_by_mean = per_state_rows[int(np.argmax(mean_vol))]["canonical_id"]
            highest_by_std = per_state_rows[int(np.argmax(std_vol))]["canonical_id"]

            row = {
                "resolution_id": resolution_id,
                "window_name": window_name,
                "symbol": symbol,
                "classifier_id": classifier_id,
                "highest_vol_state_by_mean": highest_by_mean,
                "highest_vol_state_by_std": highest_by_std,
                "criteria_agree": highest_by_mean == highest_by_std,
                "per_state": per_state_rows,
            }
            results.append(row)
            logger.info(
                "diagnostics.ag121_trend_efficiency.cell_done",
                resolution_id=resolution_id,
                window_name=window_name,
                symbol=symbol,
                classifier_id=classifier_id,
                criteria_agree=row["criteria_agree"],
            )

    disagreement_comparison = []
    for row in results:
        if row["criteria_agree"]:
            continue
        by_state = {s["canonical_id"]: s for s in row["per_state"]}
        mean_state = by_state.get(row["highest_vol_state_by_mean"])
        std_state = by_state.get(row["highest_vol_state_by_std"])
        if mean_state is None or std_state is None:
            continue
        disagreement_comparison.append(
            {
                "resolution_id": row["resolution_id"],
                "window_name": row["window_name"],
                "symbol": row["symbol"],
                "classifier_id": row["classifier_id"],
                "mean_selected_state": mean_state,
                "std_selected_state": std_state,
            }
        )

    payload: dict[str, Any] = {
        **report_provenance(),
        "measurement_provenance": (
            "MEASURED -- Efficiency Ratio (Kaufman) por canonical_id, log_return derivado de "
            "data/capacity/dollar_bars_r{N}/{symbol}/*.parquet (close bruto, sem re-fit), "
            "realized_vol_short rejuntado de experiments/m4_forward_vol_history/ (mesma fonte "
            "do script irmao compare_canonicalization_criterion_media_vs_desvio.py). Testa a "
            "hipotese 'estado de maior retorno em RECENTE eh tendencia ordeira, estado de maior "
            "desvio-padrao de vol eh chop/erratico' levantada sobre o achado de AG-121. Nao "
            "decide o criterio final (ja decidido -- MEDIA), so caracteriza a divergencia "
            "MEDIA x DESVIO-PADRAO onde ela existe (B23: nada presumido, nada inventado)."
        ),
        "min_bars_per_state": _MIN_BARS_PER_STATE,
        "n_cells_computed": len(results),
        "disagreement_cells": disagreement_comparison,
        "results": results,
        "next_step": (
            "Comparar efficiency_ratio do mean_selected_state vs. std_selected_state em cada "
            "linha de disagreement_cells (buscar o canonical_id correspondente em 'results' -> "
            "per_state). Se mean_selected_state tiver efficiency_ratio sistematicamente maior "
            "(mais perto de 1) que std_selected_state nas celulas RECENTE, a hipotese de "
            "'tendencia ordeira vs. caotica' tem suporte empirico; se nao houver padrao claro, "
            "a divergencia fica registrada como nao-explicada, nao inventar explicacao."
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
        "diagnostics.ag121_trend_efficiency.done",
        n_cells_computed=len(results),
        n_disagreement_cells=len(disagreement_comparison),
        dest_path=str(dest_path),
    )


if __name__ == "__main__":
    main()
