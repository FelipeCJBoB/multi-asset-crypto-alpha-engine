"""Mede a deriva REAL do threshold de dollar bar entre as 5 janelas de
regime de M2 -- resposta a P-1 (`docs/refactor_dollar_bar_canonico.md` §7,
bloqueador 2/§3.1).

**O que existia antes disso, e por que não bastava.** `§3.1` do doc tem só
um PROXY: bytes comprimidos de `aggTrades` por janela (`du -cb`), que mede
CONTAGEM DE TRADES (bytes ∝ nº de linhas), não volume em dólar. O número
que decide de verdade o threshold é `Σ price×quantity` — `m2_worker.py:437`,
`dollar_threshold = totals.total_dollar / target_n_bars`. A proveniência
honesta registrada no doc é explícita: "a deriva real do threshold pode ser
maior, menor OU DE SINAL OPOSTO" ao proxy de bytes. Este script mede a
coisa certa, não o proxy.

**Por que reusar `m2_worker._scan_trades_totals`/`_date_chunks` em vez de
reimplementar a soma.** `_scan_trades_totals` já É exatamente essa soma —
streaming por chunk sobre `lake.query_agg_trades`, memória limitada a 1
chunk (nunca ao histórico inteiro), com o mesmo throttle de DuckDB
(`_duckdb_throttle`, embutido dentro dela) que resolveu os
`duckdb.OutOfMemoryException` reais de M2. Reimplementar a mesma soma aqui
seria uma 2ª fonte de verdade que pode divergir da que M2 realmente usa pra
calibrar — o objetivo deste script é ser um wrapper FINO em cima da função
de produção de M2, não uma segunda implementação. `_scan_trades_totals`/
`_date_chunks` são "privadas" só por convenção de nome (prefixo `_`) --
aceitável importar de fora do módulo aqui porque isto é medição
descritiva (mesma categoria de `src/analysis/`, fora do contrato de
camada do `importlinter`), não código de produção que outro módulo passa
a depender.

**O que este script NÃO faz.** Não constrói NENHUMA barra (nem dollar, nem
volume, nem tick_imbalance) -- `_scan_trades_totals` só soma
`price*quantity`/`quantity`/contagem de ticks por chunk e descarta o chunk,
nunca chama `threshold_bars_step`/`tick_imbalance_bars_step`. Isso é muito
mais barato que rodar M2 inteiro (a alternativa registrada no doc: 5
re-runs de `m2_bar_comparison`, ~10min cada, só para ler
`totals.total_dollar` de um log que M2 não persiste).

**Escopo: as mesmas 5 janelas × os mesmos 5 símbolos que M2 já mediu**,
confirmado lendo `symbols` de `experiments/m2_report_{luna,ftx,winter,etf,
recente}.json` (todos `partial: false`, mesmos 5 símbolos em todos) --
`total_dollar` não depende de `tf` (`m2_worker.compute_trades_dependent_
bars_for_symbol_tf`, docstring: "o volume total... NÃO depende de TF -- é
somado 1x por símbolo"), então a granularidade certa desta medição é
(símbolo, janela), não (símbolo, tf, janela) -- 25 combinações, não 75.

Métrica de densidade: `dollar_per_day = total_dollar / n_days` por
(símbolo, janela) -- comparável entre janelas de duração parecida (~30-31
dias, como as 5 de M2), e proporcional ao `dollar_threshold` real que M2
calibraria para qualquer `tf` fixo naquela janela (já que `target_n_bars`
é ~fixo entre janelas de mesma duração -- 2.976/2.880 barras de 15m para
31/30 dias, confirmado nos 5 relatórios de M2). Resumo de deriva por
símbolo: razão entre a janela de maior e a de menor densidade -- mesmo
formato da tabela de proxy do doc (`window | ... | vs. mínimo`).

Saída: `experiments/dollar_threshold_drift.json` (escrita atômica, B29),
com `report_provenance()` (mesmo padrão de todo `experiments/*.json` do
projeto) + proveniência textual explícita (`MEASURED`, não o proxy) + os
números por (símbolo, janela) + o resumo de deriva por símbolo.

Rodar: `uv run python tools/diagnostics/measure_dollar_threshold_drift.py`
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Final

# Script standalone -- sem isto, `from src...` abaixo falha com
# `ModuleNotFoundError: No module named 'src'` quando invocado por caminho
# direto (`uv run python tools/diagnostics/<este arquivo>.py`), já que só o
# diretório do script entra em sys.path[0] nesse modo (diferente de `-m`, que
# usa o cwd). Achado real (2026-08-16): os 8 scripts de tools/diagnostics/
# que importam de `src.*` tinham este mesmo bug.
_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import orjson
import structlog

from src.analysis.m2_worker import _date_chunks, _scan_trades_totals
from src.analysis.volatility_comparison import SYMBOL_START_DATE
from src.core.provenance import report_provenance
from src.data._constants import load_constant as load_data_constant

logger = structlog.get_logger(__name__)

_DEST_PATH: Final[Path] = _REPO_ROOT / "experiments" / "dollar_threshold_drift.json"

# As mesmas 5 janelas de regime de M2 (`docs/refactor_dollar_bar_canonico.md`
# §7 P-1, comandos exatos de `m2_bar_comparison`) -- LUNA/UST, FTX, crypto
# winter, ETF/halving, recente. Replicadas literalmente, não reinventadas.
_WINDOWS: Final[tuple[tuple[str, str, str], ...]] = (
    ("luna", "2022-05-01", "2022-05-31"),
    ("ftx", "2022-11-01", "2022-11-30"),
    ("winter", "2023-06-01", "2023-06-30"),
    ("etf", "2024-03-01", "2024-03-31"),
    ("recente", "2026-07-01", "2026-07-31"),
)

# Rótulo passado a `_scan_trades_totals` no lugar de um `tf` real -- a soma
# NÃO depende de `tf` (ver docstring do módulo), ele só aparece nos logs
# `analysis.m2_worker.totals_chunk_done` por chunk. Passar um `tf` de
# verdade (ex. "15m") sugeriria uma dependência que não existe.
_TF_LOG_LABEL: Final[str] = "n/a-p1-dollar-drift"


@dataclass(slots=True, frozen=True)
class _WindowResult:
    symbol: str
    window: str
    start: str
    end: str
    n_days: int
    total_dollar: float
    total_volume: float
    n_ticks: int
    dollar_per_day: float


def _n_days(start: str, end: str) -> int:
    start_date = date.fromisoformat(start)
    end_date = date.fromisoformat(end)
    if end_date < start_date:
        raise ValueError(f"end ({end}) anterior a start ({start})")
    return (end_date - start_date).days + 1


def _measure_symbol_window(symbol: str, window: str, start: str, end: str) -> _WindowResult:
    n_days = _n_days(start, end)
    chunk_days = int(load_data_constant("bars_streaming_chunk_days"))
    chunks = _date_chunks(start, end, chunk_days=chunk_days)

    totals = _scan_trades_totals(symbol, _TF_LOG_LABEL, chunks)
    if totals.n_ticks == 0:
        raise ValueError(
            f"aggTrades vazio para {symbol} na janela {window} ({start}..{end}) -- "
            "não dá pra medir deriva de threshold sem trades"
        )
    dollar_per_day = totals.total_dollar / n_days  # noqa: unguarded-ratio -- n_days>=1 (_n_days acima)

    logger.info(
        "diagnostics.measure_dollar_threshold_drift.symbol_window_done",
        symbol=symbol,
        window=window,
        start=start,
        end=end,
        n_days=n_days,
        total_dollar=totals.total_dollar,
        total_volume=totals.total_volume,
        n_ticks=totals.n_ticks,
        dollar_per_day=round(dollar_per_day, 2),
    )
    return _WindowResult(
        symbol=symbol,
        window=window,
        start=start,
        end=end,
        n_days=n_days,
        total_dollar=totals.total_dollar,
        total_volume=totals.total_volume,
        n_ticks=totals.n_ticks,
        dollar_per_day=dollar_per_day,
    )


def _rows_and_drift_summary(
    results: list[_WindowResult],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Agrupa por símbolo (as 5 janelas dele) -- por linha, `vs_min_ratio`
    contra a janela menos densa DO MESMO símbolo (mesmo formato da tabela
    de proxy do doc, coluna "vs. mínimo"); por símbolo, um resumo único
    (janela mais densa vs. menos densa, razão entre elas -- a resposta
    direta a P-1)."""
    rows: list[dict[str, Any]] = []
    summary: list[dict[str, Any]] = []
    for symbol in SYMBOL_START_DATE:
        symbol_results = [r for r in results if r.symbol == symbol]
        if not symbol_results:
            continue
        densest = max(symbol_results, key=lambda r: r.dollar_per_day)
        sparsest = min(symbol_results, key=lambda r: r.dollar_per_day)
        if sparsest.dollar_per_day <= 0:
            raise ValueError(
                f"{symbol}: dollar_per_day mínimo (janela {sparsest.window}) <= 0 -- "
                "não dá pra medir deriva relativa"
            )
        for r in symbol_results:
            rows.append(
                {
                    "symbol": r.symbol,
                    "window": r.window,
                    "start": r.start,
                    "end": r.end,
                    "n_days": r.n_days,
                    "total_dollar": r.total_dollar,
                    "total_volume": r.total_volume,
                    "n_ticks": r.n_ticks,
                    "dollar_per_day": round(r.dollar_per_day, 2),
                    "vs_min_ratio": round(
                        r.dollar_per_day / sparsest.dollar_per_day, 4  # noqa: unguarded-ratio -- guardado acima
                    ),
                }
            )
        summary.append(
            {
                "symbol": symbol,
                "max_window": densest.window,
                "max_dollar_per_day": round(densest.dollar_per_day, 2),
                "min_window": sparsest.window,
                "min_dollar_per_day": round(sparsest.dollar_per_day, 2),
                "drift_ratio": round(
                    densest.dollar_per_day / sparsest.dollar_per_day, 4  # noqa: unguarded-ratio -- guardado acima
                ),
            }
        )
    return rows, summary


def _atomic_write_json(payload: dict[str, Any], dest_path: Path) -> None:
    """B29 -- mesmo padrão de `m2_bar_comparison._atomic_write_json`/
    `measure_cpcv_embargo_clock_candidate._atomic_write_json`."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest_path.with_name(dest_path.name + ".tmp")
    blob = orjson.dumps(payload, option=orjson.OPT_INDENT_2)
    with tmp_path.open("wb") as fh:
        fh.write(blob)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, dest_path)


def main() -> None:
    symbols = tuple(SYMBOL_START_DATE)
    n_total = len(symbols) * len(_WINDOWS)
    logger.info(
        "diagnostics.measure_dollar_threshold_drift.starting",
        n_symbols=len(symbols),
        n_windows=len(_WINDOWS),
        n_combinations=n_total,
        note="medição REAL de soma(price*quantity) via aggTrades -- não é o proxy "
        "de bytes/contagem de trades de docs/refactor_dollar_bar_canonico.md §3.1",
    )

    results: list[_WindowResult] = []
    n_done = 0
    for window, start, end in _WINDOWS:
        for symbol in symbols:
            results.append(_measure_symbol_window(symbol, window, start, end))
            n_done += 1
            logger.info(
                "diagnostics.measure_dollar_threshold_drift.progress",
                n_done=n_done,
                n_total=n_total,
            )

    rows, drift_summary = _rows_and_drift_summary(results)

    payload: dict[str, Any] = {
        **report_provenance(),
        "measurement_provenance": (
            "MEASURED -- soma real de price*quantity (aggTrades) por (symbol, "
            "window), via src.analysis.m2_worker._scan_trades_totals (mesma função "
            "que M2 usa para calibrar dollar_threshold, reaproveitada sem "
            "reimplementação -- ver docstring do módulo). NÃO é o proxy de bytes/"
            "contagem de trades de docs/refactor_dollar_bar_canonico.md §3.1: "
            "aquele media contagem de linhas (bytes comprimidos ∝ nº de trades), "
            "não volume em dólar. Responde P-1 (§7) do mesmo doc."
        ),
        "windows": [
            {"name": name, "start": start, "end": end, "n_days": _n_days(start, end)}
            for name, start, end in _WINDOWS
        ],
        "symbols": list(symbols),
        "results": rows,
        "drift_summary": drift_summary,
    }
    _atomic_write_json(payload, _DEST_PATH)

    logger.info(
        "diagnostics.measure_dollar_threshold_drift.done",
        n_combinations=len(results),
        drift_summary=drift_summary,
        dest_path=str(_DEST_PATH),
    )


if __name__ == "__main__":
    main()
