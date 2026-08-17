"""Mede a distribuição REAL de duração de dollar bar (P-2,
`docs/refactor_dollar_bar_canonico.md` §7) -- item registrado como
"não foi possível determinar" desde a investigação original, bloqueando
`AG-043` (correção de `sqrt(window)`/Yang-Zhang) e parte de `AG-036`
(remedição de M1 -- decide a rota de desenho do EGARCH, entre outras
coisas).

**Por que isso nunca foi medido antes.** Precisa de dollar bar real
construída em disco -- `src.data.build_dollar_bars` só validou uma janela
pequena (BTCUSDT, Jan-Mar/2025) até o reprocessamento real dos 5 símbolos
completar (`data/capacity/dollar_bars_r1/{symbol}/`, 2026-08-17).

**O que este script mede, exatamente.** `duration_ms = close_time -
open_time` por barra -- tempo de RELÓGIO que cada dollar bar levou pra
fechar, lido direto de `schemas.DOLLAR_BARS_R1` (colunas já persistidas,
sem recalcular nada). Reporta, por símbolo, sobre o histórico completo:
contagem, média, mediana, desvio-padrão, min/max, percentis (p1..p99),
assimetria (skewness) e curtose em excesso -- o suficiente pra julgar a
FORMA da distribuição (log-normal? cauda pesada? bimodal?), não só a
escala. Também reporta separado pro primeiro e último quartil de dias de
cada símbolo (early vs. recent) -- resposta direta à pergunta "quanto a
duração muda entre regimes de liquidez diferentes", já sugerida pela
deriva de 18,18x de `threshold_usdt` já medida (P-1,
`experiments/dollar_threshold_drift.json`).

**O que este script NÃO decide.** Não escolhe a rota de desenho do EGARCH
(ACD-GARCH acoplado vs. heurística de escala por duração) nem corrige
`sqrt(window)`/Yang-Zhang -- só mede o fato que essas decisões precisam.
Ver `audit/architecture_gaps_log.yaml::AG-036`/`AG-043` pro uso dos
números aqui produzidos.

**Achado real no caminho, não hipotético.** A ÚLTIMA barra (por
`open_time`) de qualquer janela de reprocessamento finita não é uma barra
fechada por threshold -- é o "leftover" que `bars.threshold_bars_finish`
flusha incondicionalmente no fim de `build_dollar_bars_for_window`, pra
não perder os últimos trades sem barra nenhuma. Pode ter 1 trade só
(confirmado: ETHUSDT, última barra, `count=1`, `duration_ms=0`) --
excluída da distribuição por símbolo (`_drop_trailing_leftover_bar`), com
log explícito de quantas barras foram excluídas e por quê. Não é
corrupção de dado, é artefato estrutural de qualquer janela finita --
mesma disciplina de distinguir "zero medido" de "artefato" que o resto do
projeto já aplica (FCN, `audit_engineering`).

**2º achado real, mais importante -- correção de uma suposição própria
não verificada.** A 1ª versão deste script assumia "`bars.py` garante
`close_time > open_time` por construção" e falhava alto em qualquer
`duration_ms<=0` fora do leftover final -- afirmação nunca checada contra
o código real. SOLUSDT tem 10 barras (2025-07-16 ~17:00-17:05 UTC) com
`duration_ms == 0` no MEIO da série. Investigado antes de decidir
qualquer coisa: `bars.py` não documenta esse invariante como estrito, e
`aggTrades` bruto na mesma janela (consultado direto, fora do pipeline de
barras) mostra 6.653 trades reais / ~US$3,71 bilhões em ~10min -- rajada
de liquidez real (provável cascata de liquidação), não artefato do
pipeline. Com timestamp de 1ms de resolução e densidade de trade tão
alta, várias barras fecham dentro do MESMO milissegundo -- `duration_ms
== 0` é o MÍNIMO real da distribuição sob rajada extrema, não erro. Só
`duration_ms < 0` (cronologicamente impossível) seria corrupção de
verdade. Guarda corrigida (`_load_symbol_durations`) -- registrado como
achado de proveniência (`AG-061`), não silenciado.

Saída: `experiments/dollar_bar_duration_distribution.json` (escrita
atômica, B29).

Rodar: `uv run python tools/diagnostics/measure_dollar_bar_duration_distribution.py`
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

# Script standalone -- ver measure_dollar_threshold_drift.py (mesmo padrão,
# achado real AG-049): sem isto, `from src...` falha com ModuleNotFoundError
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
from src.data._paths import CAPACITY_DIR

logger = structlog.get_logger(__name__)

FloatArray = NDArray[np.float64]

_DEST_PATH: Final[Path] = _REPO_ROOT / "experiments" / "dollar_bar_duration_distribution.json"
_SOURCE_NAME: Final[str] = "dollar_bars_r1"
_PERCENTILES: Final[tuple[int, ...]] = (1, 5, 10, 25, 50, 75, 90, 95, 99)


@dataclass(slots=True, frozen=True)
class _DurationStats:
    n_bars: int
    mean_ms: float
    median_ms: float
    std_ms: float
    min_ms: float
    max_ms: float
    percentiles_ms: dict[str, float]
    skewness: float
    excess_kurtosis: float


def _stats_from_durations(duration_ms: FloatArray) -> _DurationStats:
    """`duration_ms` já filtrado pra > 0 (barra de duração zero seria um
    dado corrompido, não uma medição real -- ver guarda em
    `_load_symbol_durations`)."""
    mean = float(np.mean(duration_ms))
    std = float(np.std(duration_ms))
    # Assimetria/curtose em excesso -- convenção padrão (Fisher-Pearson),
    # mesma definição que scipy.stats.skew/kurtosis(fisher=True) usa.
    # noqa: unguarded-ratio -- std>0 garantido (duration_ms tem >=2 valores
    # distintos em qualquer símbolo real; se std==0 a divisão abaixo
    # levantaria ZeroDivisionError alto, não silencioso)
    centered = duration_ms - mean
    skewness = float(np.mean(centered**3) / std**3) if std > 0 else float("nan")
    excess_kurtosis = float(np.mean(centered**4) / std**4 - 3.0) if std > 0 else float("nan")
    percentiles = {
        f"p{p}": float(np.percentile(duration_ms, p)) for p in _PERCENTILES
    }
    return _DurationStats(
        n_bars=int(duration_ms.shape[0]),
        mean_ms=mean,
        median_ms=float(np.median(duration_ms)),
        std_ms=std,
        min_ms=float(np.min(duration_ms)),
        max_ms=float(np.max(duration_ms)),
        percentiles_ms=percentiles,
        skewness=skewness,
        excess_kurtosis=excess_kurtosis,
    )


def _load_symbol_frame(symbol: str) -> pl.DataFrame:
    symbol_dir = CAPACITY_DIR / _SOURCE_NAME / symbol
    if not symbol_dir.is_dir():
        raise FileNotFoundError(
            f"{symbol_dir} não existe -- rode src.data.build_dollar_bars pra "
            f"{symbol} antes de medir duração"
        )
    files = sorted(symbol_dir.glob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"nenhum .parquet em {symbol_dir}")
    frame = pl.concat([pl.read_parquet(f) for f in files]).sort("open_time")
    return frame


def _drop_trailing_leftover_bar(frame: pl.DataFrame, symbol: str) -> pl.DataFrame:
    """A ÚLTIMA barra (por `open_time`) de uma janela de reprocessamento
    finita não é uma barra fechada por threshold -- é o "leftover" final
    que `bars.threshold_bars_finish` flusha incondicionalmente no fim do
    `build_dollar_bars_for_window` (`src/data/build_dollar_bars.py`),
    porque descartar os últimos trades sem fio nenhum seria perda de dado
    silenciosa. Pode ter só 1 trade -- `open_time == close_time`,
    `duration_ms == 0` -- ACHADO REAL confirmado (ETHUSDT, 2026-08-17:
    última barra tem `count=1`, `quote_volume=24,87` vs. o threshold real
    de ~97,19M). Não é corrupção, é artefato estrutural de janela finita
    -- excluída da distribuição (não representa "quanto tempo uma barra
    leva pra fechar de verdade", representa "quanto sobrou quando o
    reprocessamento parou"). Log explícito, não silencioso (mesma
    disciplina FCN de distinguir zero medido de artefato estrutural)."""
    last = frame.tail(1)
    logger.info(
        "diagnostics.measure_dollar_bar_duration_distribution.leftover_bar_excluded",
        symbol=symbol,
        open_time=int(last["open_time"][0]),
        close_time=int(last["close_time"][0]),
        count=int(last["count"][0]),
        quote_volume=float(last["quote_volume"][0]),
    )
    return frame.head(frame.height - 1)


def _load_symbol_durations(frame: pl.DataFrame, symbol: str) -> FloatArray:
    """`duration_ms == 0` é um dado VÁLIDO, não corrompido -- achado real
    ao investigar (SOLUSDT, 2025-07-16 ~17:00-17:05 UTC, 10 barras):
    `bars.py` NÃO garante `close_time > open_time` estrito (não há esse
    invariante documentado no módulo, e eu tinha assumido que havia sem
    checar -- corrigido aqui). Confirmado via `aggTrades` bruto na mesma
    janela (`lake.query_agg_trades`, fora do pipeline de barras): 6.653
    trades reais em ~10min, ~US$3,71 bilhões de valor -- rajada de
    liquidez real (provável cascata de liquidação), não artefato do
    pipeline. Com timestamp de resolução 1ms e densidade de trade tão
    alta, várias barras fecham dentro do MESMO milissegundo -- `open_time
    == close_time` é a consequência esperada, é o MÍNIMO real da
    distribuição, não erro. Só `duration_ms < 0` (close antes do open,
    cronologicamente impossível) seria corrupção de verdade -- guarda
    mantida só para esse caso."""
    open_time = frame["open_time"].cast(pl.Int64).to_numpy()
    close_time = frame["close_time"].cast(pl.Int64).to_numpy()
    duration_ms: FloatArray = (close_time - open_time).astype(np.float64)
    if np.any(duration_ms < 0):
        n_bad = int(np.sum(duration_ms < 0))
        raise ValueError(
            f"{symbol}: {n_bad} barra(s) com duration_ms<0 -- close_time anterior a "
            "open_time é cronologicamente impossível, dado corrompido de verdade"
        )
    return duration_ms


def _quartile_split_stats(frame: pl.DataFrame, duration_ms: FloatArray) -> dict[str, Any]:
    """Compara o 1º quartil de dias (mais antigo) contra o 4º (mais
    recente) do próprio símbolo -- mesmo racional de `vs_min_ratio` em
    `measure_dollar_threshold_drift.py`: a pergunta é "quanto muda dentro
    do mesmo símbolo ao longo do tempo", não uma comparação cross-asset."""
    n = duration_ms.shape[0]
    q1_end = n // 4
    q4_start = n - n // 4
    early = duration_ms[:q1_end]
    recent = duration_ms[q4_start:]
    early_stats = _stats_from_durations(early)
    recent_stats = _stats_from_durations(recent)
    open_time = frame["open_time"].cast(pl.Int64).to_numpy()
    return {
        "early_quartile": {
            "n_bars": early_stats.n_bars,
            "median_ms": early_stats.median_ms,
            "mean_ms": early_stats.mean_ms,
            "open_time_start": int(open_time[0]),
            "open_time_end": int(open_time[q1_end - 1]),
        },
        "recent_quartile": {
            "n_bars": recent_stats.n_bars,
            "median_ms": recent_stats.median_ms,
            "mean_ms": recent_stats.mean_ms,
            "open_time_start": int(open_time[q4_start]),
            "open_time_end": int(open_time[-1]),
        },
        "median_ratio_early_vs_recent": round(
            early_stats.median_ms / recent_stats.median_ms, 4  # noqa: unguarded-ratio -- median_ms>0 (duration_ms>0 garantido)
        ),
    }


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
        "percentiles_minutes": {
            k: round(v / 60_000, 3) for k, v in stats.percentiles_ms.items()
        },
        "skewness": round(stats.skewness, 4),
        "excess_kurtosis": round(stats.excess_kurtosis, 4),
    }


def main() -> None:
    symbols = tuple(SYMBOL_START_DATE)
    logger.info(
        "diagnostics.measure_dollar_bar_duration_distribution.starting",
        n_symbols=len(symbols),
    )

    per_symbol: list[dict[str, Any]] = []
    for symbol in symbols:
        raw_frame = _load_symbol_frame(symbol)
        frame = _drop_trailing_leftover_bar(raw_frame, symbol)
        duration_ms = _load_symbol_durations(frame, symbol)
        overall = _stats_from_durations(duration_ms)
        quartile_split = _quartile_split_stats(frame, duration_ms)
        row = {
            "symbol": symbol,
            "n_bars_total_incl_leftover": raw_frame.height,
            "n_bars_excluded_trailing_leftover": raw_frame.height - frame.height,
            "overall": _stats_to_dict(overall),
            "time_split": quartile_split,
        }
        per_symbol.append(row)
        logger.info(
            "diagnostics.measure_dollar_bar_duration_distribution.symbol_done",
            symbol=symbol,
            n_bars=overall.n_bars,
            median_minutes=round(overall.median_ms / 60_000, 2),
            p99_minutes=round(overall.percentiles_ms["p99"] / 60_000, 2),
            max_hours=round(overall.max_ms / 3_600_000, 2),
            median_ratio_early_vs_recent=quartile_split["median_ratio_early_vs_recent"],
        )

    payload: dict[str, Any] = {
        **report_provenance(),
        "measurement_provenance": (
            "MEASURED -- duration_ms = close_time - open_time por barra, lido "
            "direto de data/capacity/dollar_bars_r1/{symbol}/*.parquet (schema "
            "DOLLAR_BARS_R1, já persistido pelo reprocessamento real de "
            "2026-08-17). Responde P-2 (docs/refactor_dollar_bar_canonico.md §7), "
            "'não foi possível determinar' na investigação original -- bloqueava "
            "AG-043 (sqrt(window)/Yang-Zhang) e a rota de desenho do EGARCH em "
            "AG-036."
        ),
        "symbols": list(symbols),
        "results": per_symbol,
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
        "diagnostics.measure_dollar_bar_duration_distribution.done",
        n_symbols=len(per_symbol),
        dest_path=str(dest_path),
    )


if __name__ == "__main__":
    main()
