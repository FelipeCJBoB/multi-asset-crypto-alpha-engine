"""Mede a duração REAL máxima (relógio) de qualquer janela de N barras
consecutivas, por (símbolo, resolução) -- D-02, `AG-159`
(`docs/regime_feature_engine_design_doc_2026-08-23.md` §3, ressalva 3).

PENDENTE-DE-EXECUÇÃO-HUMANA -- Claude não executa `.py` (CLAUDE.md,
"Protocolo de execução"). Rodar com:

    uv run python tools/diagnostics/measure_max_consecutive_bar_window_duration.py

**Problema que motiva este script.** `compute_max_feature_lookback_ms`
(`src/features/build.py`) dimensiona a proteção de purge do CPCV
(`CPCVConfig.max_feature_lookback_ms`, componente 96) sob `resolution_id`
(dollar-bar) usando `label_prefetch_p99_bar_duration_ms * N` -- um proxy
MEDIDO, mas pra um modelo de custo DIFERENTE (prefetch de `mark_1m`/
funding, sub-cobertura tolerável e visível) do que o purge precisa
(sub-cobertura = vazamento SILENCIOSO, B02/B09). `N` = maior janela
FINITA de lookback entre as features do conjunto ativo
(`src.features.build.max_feature_window_bars`, hoje 96 barras, `C06_vol_
ratio_12_96`) -- lido dinamicamente aqui, nunca hardcoded (se o conjunto
ativo mudar, este script acompanha sem edição).

Achado já registrado (`AG-159` addendum, `project_assurance`
2026-08-23, medição pontual sobre 1 combinação): `max_ms` real de
SOLUSDT/R3 chega a ~5,8x o `p99` usado -- ressalva de MAGNITUDE, não de
UNIDADE (a unidade já foi corrigida, commit `6902352`). Este script
generaliza essa medição pras 15 combinações reais (5 símbolos × 3
resoluções), sobre os parquets JÁ PERSISTIDOS
(`data/capacity/dollar_bars_r{1,2,3}/{symbol}/*.parquet`) -- sem
medição nova de trade bruto, só agregação sobre dado que já existe (B23:
nada inventado, nada re-coletado).

**O que este script NÃO faz.** Não escreve em `constants.yaml` sozinho,
não altera `compute_max_feature_lookback_ms` -- imprime/persiste a
tabela completa (max real vs. proxy atual, ratio, por combinação);
decidir se/como registrar uma constante `MEASURED` nova (e se a guarda
de runtime vira comparação exata ou um multiplicador de segurança sobre
o proxy) é decisão humana, mesmo padrão de `measure_dollar_bar_
duration_p99_by_resolution.py` (B20: threshold nunca escolhido
programaticamente depois de ver o resultado).

**Nota de gate (2026-08-23):** até 2026-08-23 este código nunca era
alcançado em produção real -- `assert_no_expanding_lookback_in_active_set`
bloqueava incondicionalmente (3 features `expanding` no conjunto ativo
T1). O Manager decidiu excluir essas 3 features do conjunto ativo
(`AG-032`, `T1_FEATURE_IDS`) -- o gate que mascarava esta lacuna foi
removido, então o resultado deste script deixa de ser "preparação pra um
dia" e passa a ser pré-requisito real antes do primeiro treino sob
`resolution_id` (R2/R3) com purge ativo.

Saída: `experiments/max_consecutive_bar_window_duration.json` (escrita
atômica, B29)."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

# Script standalone -- mesmo padrão de measure_dollar_bar_duration_p99_
# by_resolution.py/measure_dollar_bar_duration_distribution.py (achado
# real AG-049): sem isto, `from src...` falha com ModuleNotFoundError
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
from src.data.build_dollar_bars import CALIBRATION_TF_BY_RESOLUTION
from src.features._constants import load_constant
from src.features.build import max_feature_window_bars

logger = structlog.get_logger(__name__)

IntArray = NDArray[np.int64]

_DEST_PATH: Final[Path] = (
    _REPO_ROOT / "experiments" / "max_consecutive_bar_window_duration.json"
)
# Mesmo piso de amostra mínima de measure_dollar_bar_duration_p99_by_
# resolution.py -- combo com menos barras que a janela + este piso não
# produz uma medição de máximo confiável (janela mal coberta).
_MIN_BARS_FOR_STATS: Final[int] = 30


@dataclass(slots=True, frozen=True)
class _WindowDurationResult:
    symbol: str
    resolution_id: str
    n_bars_total_incl_leftover: int
    n_windows: int
    max_window_duration_ms: int
    max_window_start_open_time_ms: int
    max_window_end_close_time_ms: int
    proxy_ms_used_today: int
    ratio_max_over_proxy: float


def _source_name(resolution_id: str) -> str:
    # Mesma convenção de src.data.build_dollar_bars/src.data.lake.
    # query_dollar_bars -- duplicada aqui de propósito, script
    # standalone, mesmo padrão dos irmãos deste diretório.
    return f"dollar_bars_{resolution_id.lower()}"


def _load_symbol_resolution_frame(symbol: str, resolution_id: str) -> pl.DataFrame | None:
    symbol_dir = CAPACITY_DIR / _source_name(resolution_id) / symbol
    if not symbol_dir.is_dir():
        logger.warning(
            "diagnostics.measure_max_consecutive_bar_window_duration.symbol_dir_missing",
            symbol=symbol,
            resolution_id=resolution_id,
            path=str(symbol_dir),
        )
        return None
    files = sorted(symbol_dir.glob("*.parquet"))
    if not files:
        logger.warning(
            "diagnostics.measure_max_consecutive_bar_window_duration.no_parquet_files",
            symbol=symbol,
            resolution_id=resolution_id,
            path=str(symbol_dir),
        )
        return None
    return pl.concat([pl.read_parquet(f) for f in files]).sort("open_time")


def _drop_trailing_leftover_bar(
    frame: pl.DataFrame, symbol: str, resolution_id: str
) -> pl.DataFrame:
    """Mesmo achado de measure_dollar_bar_duration_p99_by_resolution.py
    -- a ÚLTIMA barra (por `open_time`) de uma janela de reprocessamento
    finita não é uma barra fechada por threshold, é o "leftover" que
    `bars.threshold_bars_finish` flusha incondicionalmente."""
    last = frame.tail(1)
    logger.info(
        "diagnostics.measure_max_consecutive_bar_window_duration.leftover_bar_excluded",
        symbol=symbol,
        resolution_id=resolution_id,
        open_time=int(last["open_time"][0]),
        close_time=int(last["close_time"][0]),
    )
    return frame.head(frame.height - 1)


def _max_consecutive_window_duration(
    frame: pl.DataFrame, window_bars: int
) -> tuple[int, int, int, int]:
    """Duração de relógio de CADA janela de `window_bars` barras
    consecutivas (`close_time[i+window_bars-1] - open_time[i]`, todas as
    posições `i` válidas) -- retorna (max_duration_ms, n_windows,
    open_time da janela do máximo, close_time da janela do máximo).
    Vetorizado (`polars.Series.shift`), não um loop Python sobre milhares
    de barras."""
    open_time: IntArray = frame["open_time"].cast(pl.Int64).to_numpy()
    close_time: IntArray = frame["close_time"].cast(pl.Int64).to_numpy()
    n = open_time.shape[0]
    n_windows = n - window_bars + 1
    window_start_open = open_time[: n_windows if n_windows > 0 else 0]
    window_end_close = close_time[window_bars - 1 :]
    duration_ms: IntArray = window_end_close - window_start_open
    if np.any(duration_ms < 0):
        n_bad = int(np.sum(duration_ms < 0))
        raise ValueError(
            f"{n_bad} janela(s) com duração<0 -- close_time anterior a open_time é "
            "cronologicamente impossível, dado corrompido de verdade"
        )
    argmax_idx = int(np.argmax(duration_ms))
    return (
        int(duration_ms[argmax_idx]),
        n_windows,
        int(window_start_open[argmax_idx]),
        int(window_end_close[argmax_idx]),
    )


def main() -> None:
    symbols = tuple(SYMBOL_START_DATE)
    resolutions = tuple(CALIBRATION_TF_BY_RESOLUTION)
    window_bars = max_feature_window_bars()
    proxy_ms = int(load_constant("label_prefetch_p99_bar_duration_ms"))
    proxy_window_ms = proxy_ms * window_bars
    logger.info(
        "diagnostics.measure_max_consecutive_bar_window_duration.starting",
        n_symbols=len(symbols),
        resolutions=resolutions,
        window_bars=window_bars,
        proxy_ms_per_bar=proxy_ms,
        proxy_window_ms=proxy_window_ms,
    )

    results: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for resolution_id in resolutions:
        for symbol in symbols:
            raw_frame = _load_symbol_resolution_frame(symbol, resolution_id)
            min_required = window_bars + _MIN_BARS_FOR_STATS
            if raw_frame is None or raw_frame.height <= min_required:
                skipped.append(
                    {
                        "symbol": symbol,
                        "resolution_id": resolution_id,
                        "reason": (
                            "diretorio/parquet ausente"
                            if raw_frame is None
                            else f"n_bars<={min_required} (window_bars+piso) apos excluir leftover"
                        ),
                    }
                )
                continue
            frame = _drop_trailing_leftover_bar(raw_frame, symbol, resolution_id)
            max_ms, n_windows, window_open, window_close = _max_consecutive_window_duration(
                frame, window_bars
            )
            result = _WindowDurationResult(
                symbol=symbol,
                resolution_id=resolution_id,
                n_bars_total_incl_leftover=raw_frame.height,
                n_windows=n_windows,
                max_window_duration_ms=max_ms,
                max_window_start_open_time_ms=window_open,
                max_window_end_close_time_ms=window_close,
                proxy_ms_used_today=proxy_window_ms,
                ratio_max_over_proxy=(
                    round(max_ms / proxy_window_ms, 3) if proxy_window_ms > 0 else float("inf")
                ),
            )
            results.append(
                {
                    "symbol": result.symbol,
                    "resolution_id": result.resolution_id,
                    "n_bars_total_incl_leftover": result.n_bars_total_incl_leftover,
                    "n_windows": result.n_windows,
                    "max_window_duration_ms": result.max_window_duration_ms,
                    "max_window_duration_hours": round(
                        result.max_window_duration_ms / 3_600_000, 2
                    ),
                    "max_window_start_open_time_ms": result.max_window_start_open_time_ms,
                    "max_window_end_close_time_ms": result.max_window_end_close_time_ms,
                    "proxy_ms_used_today": result.proxy_ms_used_today,
                    "proxy_hours_used_today": round(result.proxy_ms_used_today / 3_600_000, 2),
                    "ratio_max_over_proxy": result.ratio_max_over_proxy,
                }
            )
            logger.info(
                "diagnostics.measure_max_consecutive_bar_window_duration.symbol_done",
                symbol=symbol,
                resolution_id=resolution_id,
                max_window_duration_hours=round(max_ms / 3_600_000, 2),
                ratio_max_over_proxy=result.ratio_max_over_proxy,
            )

    if skipped:
        logger.warning(
            "diagnostics.measure_max_consecutive_bar_window_duration.combos_skipped",
            n_skipped=len(skipped),
            skipped=skipped,
        )

    worst_ratio = max((r["ratio_max_over_proxy"] for r in results), default=None)
    payload: dict[str, Any] = {
        **report_provenance(),
        "measurement_provenance": (
            "MEASURED -- max_window_duration_ms = max(close_time[i+window_bars-1] - "
            "open_time[i]) sobre todas as janelas de window_bars barras consecutivas, "
            "lido direto de data/capacity/dollar_bars_{r1,r2,r3}/{symbol}/*.parquet "
            "(já persistidos, AG-124 causal). window_bars = "
            "src.features.build.max_feature_window_bars() no momento da execução "
            "(dinâmico, não hardcoded). Responde AG-159/D-02 ressalva 3 "
            "(docs/regime_feature_engine_design_doc_2026-08-23.md §3) -- generaliza a "
            "medição pontual de SOLUSDT/R3 (achado do project_assurance, 2026-08-23) "
            "pras 15 combinações reais."
        ),
        "window_bars": window_bars,
        "symbols": list(symbols),
        "resolutions": list(resolutions),
        "skipped_combos": skipped,
        "results": results,
        "worst_case_ratio_max_over_proxy": worst_ratio,
        "next_step": (
            "Manager revisa a tabela `results` e decide como o purge do CPCV "
            "(compute_max_feature_lookback_ms, src/features/build.py) deve se proteger "
            "sob resolution_id != None: registrar uma constante nova MEASURED (ex. "
            "max_consecutive_bar_window_duration_ms, por resolução ou pior-caso "
            "cross-symbol) e substituir/multiplicar o proxy de prefetch por ela, e/ou "
            "adicionar a guarda de runtime (structlog.warning ou fail-fast quando o "
            "lookback calculado for menor que este máximo medido) -- D-02 ressalva 4. "
            "B20: threshold nunca escolhido programaticamente aqui."
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
        "diagnostics.measure_max_consecutive_bar_window_duration.done",
        n_results=len(results),
        n_skipped=len(skipped),
        worst_case_ratio_max_over_proxy=worst_ratio,
        dest_path=str(dest_path),
    )


if __name__ == "__main__":
    main()
