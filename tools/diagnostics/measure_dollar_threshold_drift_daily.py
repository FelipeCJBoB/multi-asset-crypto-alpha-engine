"""Mede a deriva REAL do threshold de dollar bar em granularidade DIÁRIA
CONTÍNUA, desde o início do histórico real de cada símbolo -- 2ª extensão do
achado de `measure_dollar_threshold_drift_monthly.py` (AG-124), pedida
explicitamente pelo Manager: "quero Diário" -- checar se o padrão
monotônico (janela trailing mais curta = erro de calibração menor, medido
em 1/2/3/6 MESES e depois em 1/2/4 SEMANAS, ambos sem exceção em nenhum
dos 5 símbolos) continua melhorando até granularidade DIÁRIA, a menor
testada até agora, ou se reverte/estabiliza por ruído de amostra pequena
(1 dia de trading tem muito menos volume que 1 semana, então a variância
relativa do "threshold calibrado" pode passar a dominar o sinal de deriva
real).

**Reuso, não reimplementação -- mesma primitiva dos scripts mensal/semanal.**
`src.data._chunked_scan.date_chunks`/`scan_trades_totals` (streaming por
chunk sobre `lake.query_agg_trades`, memória limitada a 1 chunk de
`bars_streaming_chunk_days` dias), idênticas, sem modificação -- só a
FUNÇÃO DE PARTIÇÃO muda (`_day_windows` no lugar de `_week_windows` de
`measure_dollar_threshold_drift_weekly.py:103-122`, generalizada com
`_WINDOW_DAYS=1` em vez de `7`). Checkpoint incremental/retry em
`os.replace` também copiados linha a linha do script semanal
(`measure_dollar_threshold_drift_weekly.py:172-195`, mesmo achado real do
Windows: `PermissionError: [WinError 5]` transiente por lock de
antivírus/indexador em `os.replace` durante a rodada mensal).

**Decisão de particionamento -- dia ROLANTE de 1 dia a partir de
`SYMBOL_START_DATE[symbol]`, mesmo racional do script semanal (não há
"dia ISO" com âncora diferente de calendário civil, então dia rolante ==
dia civil aqui -- a única diferença pro semanal é que `_WINDOW_DAYS=1`
não pode produzir NENHUMA janela parcial exceto a última (toda janela de
1 dia É um dia inteiro por construção; não existe "meio dia" no dado).**
`dollar_per_day` continua sendo uma TAXA (total_dollar/n_days, com
`n_days==1` sempre exceto potencialmente arredondamento de fronteira que
não ocorre aqui), mesmo racional dos 2 scripts anteriores.

**Escopo: TODO dia desde `SYMBOL_START_DATE[symbol]` até `END_DATE`, pros
5 símbolos** (mesma fonte de datas dos scripts mensal/semanal --
`src.analysis.volatility_comparison.SYMBOL_START_DATE`/`END_DATE`,
CONFIRMADAS batendo com `experiments/dollar_threshold_drift_weekly.json`
antes de rodar, não reinventadas) -- ~9256 combinações (símbolo, dia) no
total (2412 dias de BTCUSDT desde 2019-12-31, 1711 de cada um dos 4 alts
desde 2021-12-01) -- ~7x o volume de combinações do relatório semanal
(1325), ~30x o do mensal (309). O volume de DADO real lido do disco é o
MESMO (mesmo intervalo de datas por símbolo só particionado mais fino),
mas o Nº DE QUERIES individuais ao DuckDB sobe MUITO mais que
proporcionalmente ao Nº de combinações: com `bars_streaming_chunk_days=6`
uma janela semanal de 7 dias já precisa de 2 chunks (6+1), uma mensal de
~30 dias precisa de ~5 chunks -- uma janela DIÁRIA de 1 dia precisa de
exatamente 1 chunk, então o overhead FIXO por chunk/query (setup de
conexão DuckDB, throttle) domina proporcionalmente mais aqui que nos 2
relatórios anteriores. Tempo de parede esperado: mais alto que o semanal
em proporção maior que 7x (overhead fixo não amortizado por chunks
maiores) -- rodar em background, checkpoint incremental é o que torna
isso tolerável (interrupção no meio não perde trabalho).

Rodar: `uv run python tools/diagnostics/measure_dollar_threshold_drift_daily.py`
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Final

# Script standalone -- mesmo achado/fix dos scripts mensal/semanal (2026-08-16):
# sem isto, `from src...` abaixo falha com ModuleNotFoundError quando invocado
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

_DEST_PATH: Final[Path] = _REPO_ROOT / "experiments" / "dollar_threshold_drift_daily.json"

# Mesmo racional de _TF_LOG_LABEL nos scripts mensal/semanal -- a soma NÃO
# depende de `tf` (só aparece nos logs de chunk); rótulo explícito pra não
# sugerir uma dependência que não existe.
_TF_LOG_LABEL: Final[str] = "n/a-ag124-dollar-drift-daily"

_DAY_WINDOW_DAYS: Final[int] = 1


@dataclass(slots=True, frozen=True)
class _DayResult:
    symbol: str
    day: str  # "dNNNNN_YYYY-MM-DD" (índice da janela + data de início)
    start: str
    end: str
    n_days: int
    total_dollar: float
    total_volume: float
    n_ticks: int
    dollar_per_day: float


def _day_windows(start: date, end: date) -> list[tuple[str, date, date]]:
    """Toda janela ROLANTE de `_DAY_WINDOW_DAYS` dia entre `[start, end]`,
    começando exatamente em `start` -- generalização direta de
    `measure_dollar_threshold_drift_weekly._week_windows`
    (`tools/diagnostics/measure_dollar_threshold_drift_weekly.py:103-122`)
    com `_DAY_WINDOW_DAYS=1` no lugar de `_WEEK_DAYS=7`. Com janela de 1
    dia, `step=timedelta(days=0)` e toda janela é `[cursor, cursor]` --
    não há janela parcial possível (cada dia é sempre um dia inteiro),
    diferente do semanal onde só a última podia ser parcial. Label
    `"dNNNNN_YYYY-MM-DD"` -- índice sequencial (1-based, estável
    independente de calendário) + data do dia, análogo ao `"wNNNN_..."`
    do script semanal."""
    if end < start:
        raise ValueError(f"end ({end}) anterior a start ({start})")
    windows: list[tuple[str, date, date]] = []
    cursor = start
    idx = 1
    step = timedelta(days=_DAY_WINDOW_DAYS - 1)
    while cursor <= end:
        window_end = min(cursor + step, end)
        windows.append((f"d{idx:05d}_{cursor.isoformat()}", cursor, window_end))
        cursor = window_end + timedelta(days=1)
        idx += 1
    return windows


def _measure_symbol_day(symbol: str, day: str, start: date, end: date) -> _DayResult:
    n_days = (end - start).days + 1
    chunk_days = int(load_data_constant("bars_streaming_chunk_days"))
    chunks = date_chunks(start.isoformat(), end.isoformat(), chunk_days=chunk_days)

    totals = scan_trades_totals(symbol, _TF_LOG_LABEL, chunks)
    if totals.n_ticks == 0:
        raise ValueError(
            f"aggTrades vazio para {symbol} no dia {day} ({start}..{end}) -- não dá "
            "pra medir deriva de threshold sem trades"
        )
    dollar_per_day = totals.total_dollar / n_days  # noqa: unguarded-ratio -- n_days>=1 por construção

    logger.info(
        "diagnostics.measure_dollar_threshold_drift_daily.symbol_day_done",
        symbol=symbol,
        day=day,
        start=str(start),
        end=str(end),
        n_days=n_days,
        total_dollar=totals.total_dollar,
        n_ticks=totals.n_ticks,
        dollar_per_day=round(dollar_per_day, 2),
    )
    return _DayResult(
        symbol=symbol,
        day=day,
        start=start.isoformat(),
        end=end.isoformat(),
        n_days=n_days,
        total_dollar=totals.total_dollar,
        total_volume=totals.total_volume,
        n_ticks=totals.n_ticks,
        dollar_per_day=dollar_per_day,
    )


# Mesmo achado real dos scripts mensal/semanal (2026-08-21): `os.replace` pode
# falhar com `PermissionError: [WinError 5] Acesso negado` por lock transiente
# do Windows (antivírus/indexador) -- retry com backoff curto é a correção
# direta, copiada sem modificação (B29 preservado: ainda `.tmp` -> `fsync` ->
# `rename`, só tolera o rename falhar transitoriamente antes de desistir de
# vez). Aqui ainda MAIS provável de disparar pelo menos uma vez -- ~9256
# checkpoints em vez de ~1325/~309.
_REPLACE_MAX_ATTEMPTS: Final[int] = 5
_REPLACE_RETRY_DELAY_S: Final[float] = 0.5


def _atomic_write_json(payload: dict[str, Any], dest_path: Path) -> None:
    """B29 -- mesmo padrão dos scripts mensal/semanal (`_atomic_write_json`),
    com retry curto em `os.replace`."""
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
                "diagnostics.measure_dollar_threshold_drift_daily.replace_retry",
                attempt=attempt,
                max_attempts=_REPLACE_MAX_ATTEMPTS,
                dest_path=str(dest_path),
            )
            time.sleep(_REPLACE_RETRY_DELAY_S)


def _payload(results: list[_DayResult], *, partial: bool) -> dict[str, Any]:
    rows = [
        {
            "symbol": r.symbol,
            "day": r.day,
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
            "rolante de 1 dia), via src.data._chunked_scan.scan_trades_totals (mesma "
            "função que measure_dollar_threshold_drift_monthly.py/_weekly.py usam, "
            "reaproveitada sem reimplementação). Granularidade DIÁRIA CONTÍNUA (todo "
            "dia desde o início real do histórico de cada símbolo até END_DATE) -- "
            "2ª extensão de dollar_threshold_drift_monthly.json pedida pelo Manager "
            "('quero Diário') pra checar se o padrão monotônico (janela trailing mais "
            "curta = erro de calibração menor) continua melhorando até granularidade "
            "diária, ou reverte/estabiliza por ruído de amostra pequena (AG-124)."
        ),
        "symbols": list(SYMBOL_START_DATE),
        "symbol_start_date": dict(SYMBOL_START_DATE),
        "end_date": END_DATE,
        "day_window_days": _DAY_WINDOW_DAYS,
        "results": rows,
    }


def _load_existing_results() -> list[_DayResult]:
    """Resume-from-checkpoint -- mesmo padrão dos scripts mensal/semanal:
    ~9256 combinações reais custam MUITO caro o suficiente pra isso
    importar (mais que os 2 relatórios anteriores juntos). Silenciosamente
    vazio (`[]`) se o arquivo não existir ou estiver corrompido/no formato
    antigo -- resume é otimização, nunca motivo pra falhar a rodada
    inteira."""
    if not _DEST_PATH.exists():
        return []
    try:
        payload = orjson.loads(_DEST_PATH.read_bytes())
        rows = payload["results"]
        loaded = [
            _DayResult(
                symbol=r["symbol"],
                day=r["day"],
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
            "diagnostics.measure_dollar_threshold_drift_daily.resume_load_failed",
            dest_path=str(_DEST_PATH),
            error=str(exc),
            note="checkpoint existente não pôde ser lido -- rodando do zero, não falhando",
        )
        return []
    logger.info(
        "diagnostics.measure_dollar_threshold_drift_daily.resumed",
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
        for day, window_start, window_end in _day_windows(start_date, end_date):
            all_windows.append((symbol, day, window_start, window_end))

    n_total = len(all_windows)

    results = _load_existing_results()
    done_keys = {(r.symbol, r.day) for r in results}
    remaining = [w for w in all_windows if (w[0], w[1]) not in done_keys]

    logger.info(
        "diagnostics.measure_dollar_threshold_drift_daily.starting",
        n_symbols=len(symbols),
        n_combinations=n_total,
        n_already_done=len(results),
        n_remaining=len(remaining),
        note="medição REAL diária contínua de soma(price*quantity) via aggTrades -- "
        "2ª extensão de dollar_threshold_drift_monthly.json (AG-124), pedido explícito "
        "do Manager ('quero Diário'): checar se o padrão monotônico continua até diário",
    )

    for symbol, day, window_start, window_end in remaining:
        results.append(_measure_symbol_day(symbol, day, window_start, window_end))
        i = len(results)
        # Checkpoint incremental (mesmo padrão dos scripts mensal/semanal) -- escreve
        # de novo a cada combinação, não só no fim. Marca partial=True até a última
        # combinação, para que uma leitura no meio do caminho seja honesta sobre estar
        # incompleta.
        _atomic_write_json(_payload(results, partial=(i < n_total)), _DEST_PATH)
        logger.info(
            "diagnostics.measure_dollar_threshold_drift_daily.progress",
            n_done=i,
            n_total=n_total,
            symbol=symbol,
            day=day,
        )

    logger.info(
        "diagnostics.measure_dollar_threshold_drift_daily.done",
        n_combinations=len(results),
        dest_path=str(_DEST_PATH),
    )


if __name__ == "__main__":
    main()
