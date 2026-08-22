"""Validação sobre dado REAL reprocessado -- AG-124 item 22
(`docs/plano_acao_ag124_pos_auditoria_2026-08-21.md`), pós-conclusão do
reprocessamento real (2026-08-22, `run_ag124_production_reprocessing.py`,
15/15 células, zero erro,
`experiments/ag124_production_reprocessing_summary.json`).

**Leitura-only sobre `data/capacity/dollar_bars_r{1,2,3}/` REAL, histórico
inteiro** -- ao contrário de `measure_dollar_bar_return_quality.py` (que
constrói amostra em `tempdir` descartável, nunca `data/capacity/`, por
desenho), este lê o produto final já persistido -- não cerimonial, é a
mesma pergunta (autocorrelação, curtose/cauda robusta, dispersão de
barras-por-dia-da-semana) respondida sobre o dado que a produção de fato
usa.

Reusa as funções estatísticas puras de `measure_dollar_bar_return_quality`
(módulo v2, já revisado por auditor externo em 2 rodadas -- ver docstring
de lá) em vez de duplicar ~150 linhas de matemática: `_autocorr_lag1`,
`_excess_kurtosis`, `_robust_tail_stats`, `_top_extreme_bars`,
`_weekday_bar_count_dispersion`, `_standardized`.

Flag de "boundary bar" (1ª barra de cada período não-inicial, candidata a
artefato de troca de threshold com leftover em aberto -- ver docstring do
módulo v2, ponto 2) é reconstruído por CALENDÁRIO aqui (`period_ordinal =
dias desde SYMBOL_START_DATE[symbol] // cadence_days`), não a partir do
`_period_ordinal` em memória do builder (não disponível -- lendo parquet
já persistido, não uma rodada de `build_dollar_bars_walkforward` ao
vivo). É o mesmo resultado por construção: períodos são blocos de
calendário de `cadence_days` dias exatos, confirmado no log real da
reprocessagem (`app_start`/`app_end` sempre um bloco de `cadence_days`
dias, exceto o último, parcial). O período mínimo presente na série (1º
período com output real, sem leftover herdado de lugar nenhum -- o 1º
período do calendário foi descartado por cold-start, `n_cold_start_
dropped=1` em toda célula) nunca é boundary, mesma convenção do v2.

Rodar:
    uv run python tools/diagnostics/measure_ag124_post_reprocessing_validation.py \
        --out experiments/ag124_post_reprocessing_validation.json
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from typing import Any, Final

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import numpy as np
import orjson
import polars as pl
import structlog

from src.analysis.volatility_comparison import SYMBOL_START_DATE
from src.core.provenance import report_provenance
from src.data._constants import load_constant
from src.data.build_dollar_bars import CALIBRATION_TF_BY_RESOLUTION
from tools.diagnostics.measure_dollar_bar_return_quality import (
    _autocorr_lag1,
    _excess_kurtosis,
    _robust_tail_stats,
    _top_extreme_bars,
    _weekday_bar_count_dispersion,
)

logger = structlog.get_logger(__name__)

_RESOLUTIONS: Final[tuple[str, ...]] = tuple(sorted(CALIBRATION_TF_BY_RESOLUTION))
_TOP_N_EXTREME_BARS: Final[int] = 5


def _dest_dir(resolution_id: str, symbol: str) -> Path:
    suffix = resolution_id.lower()
    return _REPO_ROOT / "data" / "capacity" / f"dollar_bars_{suffix}" / symbol


def _read_full_history(resolution_id: str, symbol: str) -> tuple[pl.DataFrame, int]:
    """Concatena TODO `.parquet` diário persistido (histórico inteiro,
    não amostra), ordenado por `close_time`. Um dia sem barra (feriado de
    calendário do dollar-bar, volume insuficiente pra fechar 1 barra
    naquele dia) simplesmente não tem arquivo -- não é erro.

    **Achado real, item 22 (2026-08-22)**: o 1º período (cold-start, sem
    histórico causal válido pra calibrar) é corretamente pulado na
    ESCRITA pelo walkforward -- mas o `overwrite=True` do reprocessamento
    só sobrescreve os dias que de fato tiveram output novo, então o(s)
    arquivo(s) da calibração NÃO-causal antiga (pré-AG-124) continuam no
    disco pros dias do 1º período, sem coluna `threshold_quote` (schema
    antigo) e com `mtime` anterior ao reprocessamento -- indistinguíveis
    de dado válido sem essa checagem. Confirmado em TODAS as 15 células
    (5 símbolos × 3 resoluções): exatamente os `cadence_days` dias
    iniciais, nenhum outro ponto do histórico. Registrado como `AG-137`.
    Excluídos aqui (`threshold_quote` ausente é o discriminador) -- do
    contrário contaminariam a leitura de qualidade da recalibração causal
    com dado do método antigo que ela existe pra substituir."""
    dest_dir = _dest_dir(resolution_id, symbol)
    files = sorted(dest_dir.glob("*.parquet"))
    if not files:
        return pl.DataFrame(schema={"close_time": pl.Int64, "close": pl.Float64}), 0
    frames = []
    n_stale_excluded = 0
    for f in files:
        df = pl.read_parquet(f)
        if "threshold_quote" not in df.columns:
            n_stale_excluded += 1
            continue
        frames.append(df)
    if not frames:
        return pl.DataFrame(schema={"close_time": pl.Int64, "close": pl.Float64}), n_stale_excluded
    return pl.concat(frames).sort("close_time"), n_stale_excluded


def _log_returns_and_calendar_boundary_flags(
    bars_df: pl.DataFrame, *, start_date: str, cadence_days: int
) -> tuple[np.ndarray, np.ndarray]:
    """Mesma semântica de `_log_returns_and_boundary_flags` do módulo v2
    (`returns[i]` = transição barra `i`->`i+1`; `is_boundary[i]` = True
    quando a barra `i+1` é a 1ª barra de um período de calendário maior
    que o período mínimo presente), mas com `period_ordinal` reconstruído
    por calendário em vez de lido de `stats.periods` em memória -- ver
    docstring do módulo."""
    close = bars_df["close"].to_numpy()
    valid = close > 0
    if valid.sum() < 2:
        return np.array([], dtype=np.float64), np.array([], dtype=bool)
    valid_df = bars_df.filter(pl.Series(valid))

    start_date_obj = date.fromisoformat(start_date)
    days_since_start = (
        valid_df.select(
            (
                pl.from_epoch(pl.col("close_time"), time_unit="ms").dt.date()
                - pl.lit(start_date_obj)
            )
            .dt.total_days()
            .alias("_days")
        )["_days"].to_numpy()
    )
    period_ordinal = (days_since_start // cadence_days).astype(np.int64)
    close = valid_df["close"].to_numpy()

    returns = np.diff(np.log(close))
    period_min = int(period_ordinal.min())
    is_first_of_period = np.zeros(period_ordinal.shape[0], dtype=bool)
    seen: set[int] = set()
    for idx, ordinal in enumerate(period_ordinal):
        if ordinal not in seen:
            seen.add(int(ordinal))
            if ordinal > period_min:
                is_first_of_period[idx] = True
    is_boundary = is_first_of_period[1:]
    return returns, is_boundary


def measure_cell(resolution_id: str, symbol: str, *, cadence_days: int) -> dict[str, Any]:
    bars_df, n_stale_files_excluded = _read_full_history(resolution_id, symbol)
    start_date = SYMBOL_START_DATE[symbol]

    returns, is_boundary = _log_returns_and_calendar_boundary_flags(
        bars_df, start_date=start_date, cadence_days=cadence_days
    )
    n_boundary = int(is_boundary.sum())
    returns_excl = returns[~is_boundary]

    result: dict[str, Any] = {
        "symbol": symbol,
        "resolution_id": resolution_id,
        "start_date": start_date,
        "cadence_days": cadence_days,
        "n_bars": bars_df.height,
        "n_stale_pre_causal_files_excluded": n_stale_files_excluded,
        "n_returns": int(returns.shape[0]),
        "n_boundary_bars_excluded": n_boundary,
        "all_bars": {
            "autocorr_lag1": _autocorr_lag1(returns),
            "excess_kurtosis": _excess_kurtosis(returns),
            **_robust_tail_stats(returns),
        },
        "excluding_boundary_bars": {
            "n_returns": int(returns_excl.shape[0]),
            "autocorr_lag1": _autocorr_lag1(returns_excl),
            "excess_kurtosis": _excess_kurtosis(returns_excl),
            **_robust_tail_stats(returns_excl),
        },
        "top_extreme_bars": _top_extreme_bars(
            bars_df.filter(pl.col("close") > 0), returns, is_boundary, n=_TOP_N_EXTREME_BARS
        ),
        "weekday_dispersion": _weekday_bar_count_dispersion(bars_df),
    }
    logger.info(
        "diagnostics.measure_ag124_post_reprocessing_validation.cell_done",
        symbol=symbol,
        resolution_id=resolution_id,
        n_bars=result["n_bars"],
        n_boundary_bars_excluded=n_boundary,
        excess_kurtosis_all=result["all_bars"]["excess_kurtosis"],
        excess_kurtosis_excl_boundary=result["excluding_boundary_bars"]["excess_kurtosis"],
        hill_tail_index_all=result["all_bars"]["hill_tail_index"],
        cv_by_weekday=result["weekday_dispersion"]["cv_by_weekday"],
    )
    return result


def measure_all(symbols: list[str], resolutions: list[str]) -> dict[str, Any]:
    cadence_days = int(load_constant("dollar_bar_walkforward_cadence_days"))
    table: dict[str, dict[str, Any]] = {}
    for symbol in symbols:
        table[symbol] = {}
        for resolution_id in resolutions:
            table[symbol][resolution_id] = measure_cell(
                resolution_id, symbol, cadence_days=cadence_days
            )
    return {
        **report_provenance(),
        "task": "ag124_item22_post_reprocessing_validation",
        "source": "data/capacity/dollar_bars_r{1,2,3}/ REAL, histórico inteiro (não amostra)",
        "reprocessing_summary_ref": "experiments/ag124_production_reprocessing_summary.json",
        "cadence_days": cadence_days,
        "symbols": symbols,
        "resolutions": resolutions,
        "methodology": (
            "Leitura direta do parquet persistido em produção (não rebuild via "
            "build_dollar_bars_walkforward). all_bars = todas as barras do "
            "histórico completo; excluding_boundary_bars = exclui a 1ª barra de "
            "cada período de calendário não-inicial (candidata a artefato de "
            "troca de threshold com leftover em aberto, ver docstring do módulo "
            "v2 measure_dollar_bar_return_quality.py, ponto 2). top_extreme_bars "
            "= maiores |retorno padronizado|, com flag de boundary. "
            "weekday_dispersion = CV(contagem de barras por dia-da-semana), "
            "medida direto sobre as barras reais persistidas. "
            "None = NOT_COMPUTABLE (amostra pequena ou variância/mediana zero), "
            "nunca 0.0 silencioso."
        ),
        "table": table,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--symbols", nargs="+", default=list(SYMBOL_START_DATE), help="default: os 5 símbolos"
    )
    parser.add_argument(
        "--resolutions", nargs="+", default=list(_RESOLUTIONS), help="default: R1 R2 R3"
    )
    parser.add_argument(
        "--out", type=Path, default=None, help="Se informado, grava o resultado em JSON aqui"
    )
    args = parser.parse_args()

    result = measure_all(args.symbols, args.resolutions)

    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_bytes(orjson.dumps(result, option=orjson.OPT_INDENT_2))
        logger.info(
            "diagnostics.measure_ag124_post_reprocessing_validation.written", out=str(args.out)
        )

    logger.info(
        "diagnostics.measure_ag124_post_reprocessing_validation.summary",
        symbols=args.symbols,
        resolutions=args.resolutions,
    )


if __name__ == "__main__":
    main()
