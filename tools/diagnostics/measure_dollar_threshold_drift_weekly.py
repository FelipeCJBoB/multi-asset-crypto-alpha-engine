"""Mede a deriva REAL do threshold de dollar bar em granularidade SEMANAL
CONTÍNUA, desde o início do histórico real de cada símbolo -- extensão do
achado de `measure_dollar_threshold_drift_monthly.py` (AG-124) pedida
explicitamente pelo Manager: "teste Semanal" -- checar se o padrão
monotônico (janela trailing mais curta = erro de calibração menor,
medido em 1/2/3/6 MESES) continua até granularidade semanal, ou se
reverte/estabiliza por causa de amostra pequena/ruído em janelas muito
curtas.

**Reuso, não reimplementação -- mesma primitiva do script mensal.**
`src.data._chunked_scan.date_chunks`/`scan_trades_totals` (streaming por
chunk sobre `lake.query_agg_trades`, memória limitada a 1 chunk de
`bars_streaming_chunk_days` dias), idênticas, sem modificação -- só a
FUNÇÃO DE PARTIÇÃO muda (`_week_windows` no lugar de `_month_windows`
de `measure_dollar_threshold_drift_monthly.py:102-123`). Checkpoint
incremental/retry em `os.replace` também copiados linha a linha do
script mensal (`measure_dollar_threshold_drift_monthly.py:163-202`,
achado real do Windows: `PermissionError: [WinError 5]` transiente por
lock de antivírus/indexador em `os.replace` durante a rodada mensal).

**Decisão de particionamento -- semana ROLANTE de 7 dias a partir de
`SYMBOL_START_DATE[symbol]`, NÃO semana ISO (segunda a domingo).**
O script mensal parte em MESES CALENDÁRIO porque mês é a unidade que o
Manager queria comparar (e tem convenção óbvia e única). Semana não tem
essa mesma âncora natural em relação a `SYMBOL_START_DATE[symbol]`: se
particionasse por semana ISO, a 1ª janela de cada símbolo ficaria
PARCIAL (de `SYMBOL_START_DATE[symbol]`, que quase nunca cai numa
segunda-feira, até o domingo seguinte) -- e essa janela parcial de
poucos dias seria justamente a candidata a distorcer a leitura da
janela trailing mais curta (1 semana), que é o ponto central desta
medição. Em vez disso, toda semana (exceto a ÚLTIMA de cada símbolo,
clipada em `END_DATE`) tem EXATAMENTE 7 dias -- 1 única fonte possível
de parcialidade por símbolo, não 2 (mês calendário tinha parcialidade
no primeiro E no último). `dollar_per_day` continua sendo uma TAXA
(total_dollar/n_days), então nenhuma semana (mesmo a última, mais
curta) precisa ser descartada -- mesmo racional do script mensal.

**Escopo: TODA janela de 7 dias desde `SYMBOL_START_DATE[symbol]` até
`END_DATE`, pros 5 símbolos** (mesma fonte de datas do script mensal --
`src.analysis.volatility_comparison.SYMBOL_START_DATE`/`END_DATE`,
CONFIRMADAS batendo com `experiments/dollar_threshold_drift_monthly.json`
antes de rodar, não reinventadas) -- ~1325 combinações (símbolo, semana)
no total (345 semanas de BTCUSDT desde 2019-12-31, 245 de cada um dos 4
alts desde 2021-12-01), ~4,3x o volume de combinações do relatório
mensal (309) -- mas o volume de DADO real lido do disco é o MESMO
(mesmo intervalo de datas por símbolo só particionado mais fino), então
o tempo de parede esperado não escala 4,3x, só o overhead fixo por
chunk/query.

Rodar: `uv run python tools/diagnostics/measure_dollar_threshold_drift_weekly.py`
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Final

# Script standalone -- mesmo achado/fix do script mensal (2026-08-16): sem
# isto, `from src...` abaixo falha com ModuleNotFoundError quando invocado
# por caminho direto.
_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import orjson
import structlog

from src.analysis.volatility_comparison import END_DATE, SYMBOL_START_DATE
from src.core.provenance import report_provenance
from src.data._chunked_scan import date_chunks, scan_trades_totals
from src.data._constants import load_constant as load_data_constant

logger = structlog.get_logger(__name__)

_DEST_PATH: Final[Path] = _REPO_ROOT / "experiments" / "dollar_threshold_drift_weekly.json"

# Mesmo racional de _TF_LOG_LABEL no script mensal -- a soma NÃO depende de
# `tf` (só aparece nos logs de chunk); rótulo explícito pra não sugerir uma
# dependência que não existe.
_TF_LOG_LABEL: Final[str] = "n/a-ag124-dollar-drift-weekly"

_WEEK_DAYS: Final[int] = 7


@dataclass(slots=True, frozen=True)
class _WeekResult:
    symbol: str
    week: str  # "wNNNN_YYYY-MM-DD" (índice da janela + data de início)
    start: str
    end: str
    n_days: int
    total_dollar: float
    total_volume: float
    n_ticks: int
    dollar_per_day: float


def _week_windows(start: date, end: date) -> list[tuple[str, date, date]]:
    """Toda janela ROLANTE de `_WEEK_DAYS` dias entre `[start, end]`,
    começando exatamente em `start` (não alinhada a semana ISO -- ver
    docstring do módulo). Só a ÚLTIMA janela por símbolo pode ser parcial
    (clipada em `end`). Label `"wNNNN_YYYY-MM-DD"` -- índice sequencial
    (1-based, estável independente de calendário) + data de início da
    janela, análogo ao `"YYYY-MM"` do script mensal mas sem semana ISO
    correspondente única."""
    if end < start:
        raise ValueError(f"end ({end}) anterior a start ({start})")
    windows: list[tuple[str, date, date]] = []
    cursor = start
    idx = 1
    step = timedelta(days=_WEEK_DAYS - 1)
    while cursor <= end:
        window_end = min(cursor + step, end)
        windows.append((f"w{idx:04d}_{cursor.isoformat()}", cursor, window_end))
        cursor = window_end + timedelta(days=1)
        idx += 1
    return windows


def _measure_symbol_week(symbol: str, week: str, start: date, end: date) -> _WeekResult:
    n_days = (end - start).days + 1
    chunk_days = int(load_data_constant("bars_streaming_chunk_days"))
    chunks = date_chunks(start.isoformat(), end.isoformat(), chunk_days=chunk_days)

    totals = scan_trades_totals(symbol, _TF_LOG_LABEL, chunks)
    if totals.n_ticks == 0:
        raise ValueError(
            f"aggTrades vazio para {symbol} na semana {week} ({start}..{end}) -- não dá "
            "pra medir deriva de threshold sem trades"
        )
    dollar_per_day = totals.total_dollar / n_days  # noqa: unguarded-ratio -- n_days>=1 por construção

    logger.info(
        "diagnostics.measure_dollar_threshold_drift_weekly.symbol_week_done",
        symbol=symbol,
        week=week,
        start=str(start),
        end=str(end),
        n_days=n_days,
        total_dollar=totals.total_dollar,
        n_ticks=totals.n_ticks,
        dollar_per_day=round(dollar_per_day, 2),
    )
    return _WeekResult(
        symbol=symbol,
        week=week,
        start=start.isoformat(),
        end=end.isoformat(),
        n_days=n_days,
        total_dollar=totals.total_dollar,
        total_volume=totals.total_volume,
        n_ticks=totals.n_ticks,
        dollar_per_day=dollar_per_day,
    )


# Mesmo achado real do script mensal (2026-08-21, combinação 107/309):
# `os.replace` pode falhar com `PermissionError: [WinError 5] Acesso negado`
# por lock transiente do Windows (antivírus/indexador) -- retry com backoff
# curto é a correção direta, copiada sem modificação (B29 preservado: ainda
# `.tmp` -> `fsync` -> `rename`, só tolera o rename falhar transitoriamente
# antes de desistir de vez).
_REPLACE_MAX_ATTEMPTS: Final[int] = 5
_REPLACE_RETRY_DELAY_S: Final[float] = 0.5


def _atomic_write_json(payload: dict[str, Any], dest_path: Path) -> None:
    """B29 -- mesmo padrão do script mensal (`_atomic_write_json`), com
    retry curto em `os.replace`."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest_path.with_name(dest_path.name + ".tmp")
    blob = orjson.dumps(payload, option=orjson.OPT_INDENT_2)
    with tmp_path.open("wb") as fh:
        fh.write(blob)
        fh.flush()
        os.fsync(fh.fileno())
    for attempt in range(1, _REPLACE_MAX_ATTEMPTS + 1):
        try:
            os.replace(tmp_path, dest_path)
            return
        except PermissionError:
            if attempt == _REPLACE_MAX_ATTEMPTS:
                raise
            logger.warning(
                "diagnostics.measure_dollar_threshold_drift_weekly.replace_retry",
                attempt=attempt,
                max_attempts=_REPLACE_MAX_ATTEMPTS,
                dest_path=str(dest_path),
            )
            time.sleep(_REPLACE_RETRY_DELAY_S)


def _payload(results: list[_WeekResult], *, partial: bool) -> dict[str, Any]:
    rows = [
        {
            "symbol": r.symbol,
            "week": r.week,
            "start": r.start,
            "end": r.end,
            "n_days": r.n_days,
            "total_dollar": r.total_dollar,
            "total_volume": r.total_volume,
            "n_ticks": r.n_ticks,
            "dollar_per_day": round(r.dollar_per_day, 2),
        }
        for r in results
    ]
    return {
        **report_provenance(),
        "partial": partial,
        "measurement_provenance": (
            "MEASURED -- soma real de price*quantity (aggTrades) por (symbol, janela "
            "rolante de 7 dias), via src.data._chunked_scan.scan_trades_totals (mesma "
            "função que measure_dollar_threshold_drift_monthly.py usa, reaproveitada "
            "sem reimplementação). Granularidade SEMANAL CONTÍNUA (toda janela de 7 "
            "dias desde o início real do histórico de cada símbolo até END_DATE) -- "
            "extensão de dollar_threshold_drift_monthly.json pedida pelo Manager pra "
            "checar se o padrão monotônico (janela trailing mais curta = erro de "
            "calibração menor) continua até granularidade semanal (AG-124)."
        ),
        "symbols": list(SYMBOL_START_DATE),
        "symbol_start_date": dict(SYMBOL_START_DATE),
        "end_date": END_DATE,
        "week_days": _WEEK_DAYS,
        "results": rows,
    }


def _load_existing_results() -> list[_WeekResult]:
    """Resume-from-checkpoint -- mesmo padrão do script mensal: ~1325
    combinações reais custam caro o suficiente pra isso importar.
    Silenciosamente vazio (`[]`) se o arquivo não existir ou estiver
    corrompido/no formato antigo -- resume é otimização, nunca motivo
    pra falhar a rodada inteira."""
    if not _DEST_PATH.exists():
        return []
    try:
        payload = orjson.loads(_DEST_PATH.read_bytes())
        rows = payload["results"]
        loaded = [
            _WeekResult(
                symbol=r["symbol"],
                week=r["week"],
                start=r["start"],
                end=r["end"],
                n_days=r["n_days"],
                total_dollar=r["total_dollar"],
                total_volume=r["total_volume"],
                n_ticks=r["n_ticks"],
                dollar_per_day=r["dollar_per_day"],
            )
            for r in rows
        ]
    except (orjson.JSONDecodeError, KeyError, TypeError) as exc:
        logger.warning(
            "diagnostics.measure_dollar_threshold_drift_weekly.resume_load_failed",
            dest_path=str(_DEST_PATH),
            error=str(exc),
            note="checkpoint existente não pôde ser lido -- rodando do zero, não falhando",
        )
        return []
    logger.info(
        "diagnostics.measure_dollar_threshold_drift_weekly.resumed",
        n_already_done=len(loaded),
        dest_path=str(_DEST_PATH),
    )
    return loaded


def main() -> None:
    symbols = tuple(SYMBOL_START_DATE)
    end_date = date.fromisoformat(END_DATE)

    all_windows: list[tuple[str, str, date, date]] = []
    for symbol in symbols:
        start_date = date.fromisoformat(SYMBOL_START_DATE[symbol])
        for week, window_start, window_end in _week_windows(start_date, end_date):
            all_windows.append((symbol, week, window_start, window_end))

    n_total = len(all_windows)

    results = _load_existing_results()
    done_keys = {(r.symbol, r.week) for r in results}
    remaining = [w for w in all_windows if (w[0], w[1]) not in done_keys]

    logger.info(
        "diagnostics.measure_dollar_threshold_drift_weekly.starting",
        n_symbols=len(symbols),
        n_combinations=n_total,
        n_already_done=len(results),
        n_remaining=len(remaining),
        note="medição REAL semanal contínua de soma(price*quantity) via aggTrades -- "
        "extensão semanal de dollar_threshold_drift_monthly.json (AG-124), pedido "
        "explícito do Manager: checar se o padrão monotônico continua até semanal",
    )

    for symbol, week, window_start, window_end in remaining:
        results.append(_measure_symbol_week(symbol, week, window_start, window_end))
        i = len(results)
        # Checkpoint incremental (mesmo padrão do script mensal) -- escreve de
        # novo a cada combinação, não só no fim. Marca partial=True até a
        # última combinação, para que uma leitura no meio do caminho seja
        # honesta sobre estar incompleta.
        _atomic_write_json(_payload(results, partial=(i < n_total)), _DEST_PATH)
        logger.info(
            "diagnostics.measure_dollar_threshold_drift_weekly.progress",
            n_done=i,
            n_total=n_total,
            symbol=symbol,
            week=week,
        )

    logger.info(
        "diagnostics.measure_dollar_threshold_drift_weekly.done",
        n_combinations=len(results),
        dest_path=str(_DEST_PATH),
    )


if __name__ == "__main__":
    main()
