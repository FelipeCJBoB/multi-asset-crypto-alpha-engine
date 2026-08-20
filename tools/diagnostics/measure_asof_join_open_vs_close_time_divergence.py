"""Mede o alcance REAL do achado de auditoria (2026-08-18): `_asof_join_
btc_labels`/`_asof_join_regime_onto_labels` (`src/analysis/m4_regime_
comparison.py`/`m4_critical_windows.py`) usam `RawLabels.open_time_ms`
(derivado de `bars_df["open_time"]`, o INÍCIO da dollar bar) como chave de
as-of join causal — mas `canonical_id[i]` só é matematicamente conhecível a
partir de `close_time[i]` (depende de `log_return_1[i] = ln(close[i]/
close[i-1])`). Ver docstring completa do achado no relatório da auditoria
(fora deste script) — este arquivo só MEDE, não corrige nada.

**O que este script mede, exatamente.** Sem rodar NENHUM fit de classificador
de regime (HMM/Jump Model/BOCPD/baseline) — a pergunta respondida aqui não
depende de qual candidato gerou `canonical_id`, só da GEOMETRIA do join
entre duas grades (labels de 15m vs. dollar bar R1/R2/R3): para cada `t0`
real de `labels.parquet` (o mesmo `t0` que `_asof_join_regime_onto_labels`
usa como chave esquerda — close_time do label, correto), acha a dollar bar
`i` mais recente com `open_time[i] <= t0` (exatamente o que `join_asof(
strategy="backward")` faria hoje, por baixo, contra a chave direita
`open_time_ms` — comportamento ATUAL, não o corrigido) e verifica se
`t0 < close_time[i]` — se sim, o rótulo daquela barra `i` NÃO estava
conhecível ainda em `t0` (a barra só fecha, e só então `canonical_id[i]`
passa a existir, em `close_time[i] > t0`), e o join atual devolveria um
rótulo do futuro. Reporta, por (símbolo, resolução): `n_labels_total`,
`n_labels_affected` (caiu dentro de `[open_time[i], close_time[i])` de
alguma barra), `pct_affected`, e a distribuição (percentis) de
`borrowed_ms = close_time[i] - t0` SÓ entre as linhas afetadas — quanto de
informação futura estava sendo emprestada, em cada caso real.

**O que este script NÃO mede.** Não roda nenhum classificador de regime,
então não diz "quantas linhas teriam `canonical_id` REALMENTE diferente"
sob a correção (isso exigiria fit real de cada candidato — fora de escopo
aqui, e não muda a resposta de "o join está estruturalmente errado", só
quantificaria o efeito final em cada candidato específico). O número aqui é
um LIMITE SUPERIOR honesto de "quantas linhas o join atual trata com uma
chave errada", não "quantas linhas teriam resultado numericamente
diferente" (a barra `i-1` PODE, por acaso, ter o mesmo `canonical_id` da
barra `i` — não muda o fato de que a barra `i` era a informação errada a
consultar).

Saída: `experiments/asof_join_open_vs_close_time_divergence.json` (escrita
atômica, B29).

Rodar (5-10min esperado, só leitura de parquet + numpy — sem fit de
modelo): `uv run python tools/diagnostics/measure_asof_join_open_vs_close_time_divergence.py`
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

# Script standalone -- mesmo padrão de measure_dollar_bar_duration_distribution.py
# (achado real AG-049): sem isto, `from src...` falha com ModuleNotFoundError
# quando invocado por caminho direto.
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
from src.data import lake
from src.validation import cpcv

logger = structlog.get_logger(__name__)

IntArray = NDArray[np.int64]

_DEST_PATH: Final[Path] = (
    _REPO_ROOT / "experiments" / "asof_join_open_vs_close_time_divergence.json"
)
_RESOLUTIONS: Final[tuple[str, ...]] = ("R1", "R2", "R3")
_PERCENTILES: Final[tuple[int, ...]] = (5, 25, 50, 75, 90, 95, 99, 100)


@dataclass(slots=True, frozen=True)
class _DivergenceResult:
    symbol: str
    resolution_id: str
    n_labels_total: int
    n_labels_before_first_bar: int
    n_labels_affected: int
    pct_affected: float
    borrowed_ms_percentiles: dict[str, float] | None


def _load_labels_t0_ms(symbol: str) -> IntArray:
    labels = cpcv.load_labels_v1(symbol=symbol)
    return labels["t0"].dt.epoch(time_unit="ms").cast(pl.Int64).to_numpy().astype(np.int64)


def _load_bars_open_close_ms(symbol: str, resolution_id: str) -> tuple[IntArray, IntArray]:
    bars = lake.query_dollar_bars(symbol, resolution_id=resolution_id).sort("open_time")
    open_time_ms = bars["open_time"].cast(pl.Int64).to_numpy().astype(np.int64)
    close_time_ms = bars["close_time"].cast(pl.Int64).to_numpy().astype(np.int64)
    return open_time_ms, close_time_ms


def _measure_one(symbol: str, resolution_id: str) -> _DivergenceResult:
    t0_ms = _load_labels_t0_ms(symbol)
    open_time_ms, close_time_ms = _load_bars_open_close_ms(symbol, resolution_id)

    # Mesma semântica de join_asof(strategy="backward") contra open_time_ms:
    # pra cada t0, o índice da última barra com open_time[i] <= t0.
    # searchsorted(..., side="right") - 1 é o "backward" padrão do polars.
    idx = np.searchsorted(open_time_ms, t0_ms, side="right") - 1

    before_first_bar = idx < 0
    n_before_first_bar = int(before_first_bar.sum())

    valid = ~before_first_bar
    idx_valid = idx[valid]
    t0_valid = t0_ms[valid]
    close_at_idx = close_time_ms[idx_valid]

    # Afetado = join atual (por open_time) devolveria uma barra cujo
    # close_time (quando canonical_id passa a existir de verdade) é
    # ESTRITAMENTE POSTERIOR a t0 -- rótulo do futuro sendo usado.
    affected_mask = t0_valid < close_at_idx
    n_affected = int(affected_mask.sum())
    n_total = int(t0_ms.shape[0])
    pct_affected = round(100.0 * n_affected / n_total, 3) if n_total > 0 else float("nan")

    borrowed_pcts: dict[str, float] | None = None
    if n_affected > 0:
        borrowed_ms = (close_at_idx[affected_mask] - t0_valid[affected_mask]).astype(np.float64)
        borrowed_pcts = {
            f"p{p}": round(float(np.percentile(borrowed_ms, p)), 1) for p in _PERCENTILES
        }

    result = _DivergenceResult(
        symbol=symbol,
        resolution_id=resolution_id,
        n_labels_total=n_total,
        n_labels_before_first_bar=n_before_first_bar,
        n_labels_affected=n_affected,
        pct_affected=pct_affected,
        borrowed_ms_percentiles=borrowed_pcts,
    )
    logger.info(
        "diagnostics.measure_asof_join_open_vs_close_time_divergence.pair_done",
        symbol=symbol,
        resolution_id=resolution_id,
        n_labels_total=n_total,
        n_labels_affected=n_affected,
        pct_affected=pct_affected,
        borrowed_ms_p50=borrowed_pcts["p50"] if borrowed_pcts else None,
        borrowed_ms_p99=borrowed_pcts["p99"] if borrowed_pcts else None,
    )
    return result


def _result_to_dict(r: _DivergenceResult) -> dict[str, Any]:
    return {
        "symbol": r.symbol,
        "resolution_id": r.resolution_id,
        "n_labels_total": r.n_labels_total,
        "n_labels_before_first_bar": r.n_labels_before_first_bar,
        "n_labels_affected": r.n_labels_affected,
        "pct_affected": r.pct_affected,
        "borrowed_ms_percentiles": r.borrowed_ms_percentiles,
        "borrowed_minutes_percentiles": (
            {k: round(v / 60_000, 3) for k, v in r.borrowed_ms_percentiles.items()}
            if r.borrowed_ms_percentiles is not None
            else None
        ),
    }


def main() -> None:
    symbols = tuple(SYMBOL_START_DATE)
    logger.info(
        "diagnostics.measure_asof_join_open_vs_close_time_divergence.starting",
        n_symbols=len(symbols),
        resolutions=_RESOLUTIONS,
    )

    results: list[dict[str, Any]] = []
    for symbol in symbols:
        for resolution_id in _RESOLUTIONS:
            try:
                r = _measure_one(symbol, resolution_id)
            except FileNotFoundError as exc:
                logger.warning(
                    "diagnostics.measure_asof_join_open_vs_close_time_divergence.skip_missing",
                    symbol=symbol,
                    resolution_id=resolution_id,
                    reason=str(exc),
                )
                continue
            results.append(_result_to_dict(r))

    payload: dict[str, Any] = {
        **report_provenance(),
        "measurement_provenance": (
            "MEASURED -- para cada t0 real de data/labels/{symbol}/15m/v1/"
            "labels.parquet, acha a dollar bar (data/capacity/dollar_bars_"
            "{r1,r2,r3}/{symbol}/*.parquet) que join_asof(strategy='backward', "
            "on=open_time) selecionaria HOJE, e verifica se close_time dessa "
            "barra (quando canonical_id se torna matematicamente conhecível) "
            "é posterior a t0 -- sem rodar nenhum fit de classificador de "
            "regime, só a geometria dos dois grids reais. Responde o item 3 "
            "do pedido de auditoria (alcance real do bug de causalidade em "
            "_asof_join_btc_labels/_asof_join_regime_onto_labels)."
        ),
        "symbols": list(symbols),
        "resolutions_evaluated": list(_RESOLUTIONS),
        "results": results,
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
        "diagnostics.measure_asof_join_open_vs_close_time_divergence.done",
        n_pairs=len(results),
        dest_path=str(dest_path),
    )


if __name__ == "__main__":
    main()
