"""Mede a deriva REAL do threshold de dollar bar em granularidade MENSAL
CONTÍNUA, desde o início do histórico real de cada símbolo -- insumo pra
decidir `cadence_days`/`trailing_window_days` de `build_dollar_bars_
walkforward` (AG-124, `src.data.build_dollar_bars`), NÃO a decisão em si
(ver docstring de `main()`).

**Por que um relatório NOVO, não estender `dollar_threshold_drift.json`.**
O relatório original (`measure_dollar_threshold_drift.py`) mede só 7
janelas ESPARSAS escolhidas a dedo (5 janelas de regime de M2 + 2020_h1/
h2) -- suficiente para responder "existe deriva?" (P-1,
`docs/refactor_dollar_bar_canonico.md` §7), insuficiente para escolher
`cadence_days`/`trailing_window_days`: essa escolha precisa saber COMO a
deriva se comporta MÊS A MÊS dentro de cada vintage (sobe suave? tem
saltos de regime abruptos? a deriva intra-mês já é grande?), não só o
contraste entre picos e vales de janelas distantes. Instrução explícita
do Manager: não sobrescrever o original, gerar `dollar_threshold_drift_
monthly.json` separado.

**Reuso, não reimplementação.** Mesmo padrão do script original: `_chunked_
scan.scan_trades_totals`/`date_chunks` (streaming por chunk sobre
`lake.query_agg_trades`, memória limitada a 1 chunk, mesmo throttle de
DuckDB que resolveu os `duckdb.OutOfMemoryException` reais de M2) --
reusadas sem modificação, wrapper fino em cima, não uma 2ª soma.

**Escopo: TODO mês calendário desde `SYMBOL_START_DATE[symbol]` até
`END_DATE`, pros 5 símbolos** (`src.analysis.volatility_comparison.
SYMBOL_START_DATE`/`END_DATE`, mesma fonte de datas que o resto do
projeto usa) -- ~309 combinações (símbolo, mês) no total (81 meses de
BTCUSDT desde 2019-12-31, 57 de cada um dos 4 alts desde 2021-12-01).
Mês parcial (o 1º e o último, se `SYMBOL_START_DATE`/`END_DATE` não caem
em fronteira de mês) é medido com a contagem de dias REAL do mês parcial,
não descartado nem preenchido com dado fantasma -- `dollar_per_day`
continua comparável entre meses de duração diferente porque já é uma
taxa, não um total bruto.

**Checkpoint incremental (mesmo padrão de `m4_critical_windows.py`,
AG-019).** ~309 combinações reais contra `aggTrades` de até 6+ anos de
histórico é uma rodada longa -- escreve o relatório (atômico, B29) de
novo a cada combinação processada, não só no fim. Uma interrupção a meio
caminho deixa um relatório PARCIAL válido (`"partial": true` no payload)
com tudo já medido até ali, não nada.

**O que este script NÃO faz.** Não escolhe `cadence_days`/
`trailing_window_days` -- só produz o dado mensal. A leitura de qual
cadência/janela minimiza deriva dentro de cada vintage fica pra quando o
Manager revisar este relatório; ele pode sugerir um valor candidato no
relatório de sessão, marcado como SUGESTÃO, não decisão (ver instrução
original). Não constrói NENHUMA barra (nem dollar, nem volume, nem tick
imbalance) -- só soma `price*quantity`/`quantity`/contagem de ticks.

Rodar: `uv run python tools/diagnostics/measure_dollar_threshold_drift_monthly.py`
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Final

# Script standalone -- mesmo achado/fix de measure_dollar_threshold_drift.py
# (2026-08-16): sem isto, `from src...` abaixo falha com ModuleNotFoundError
# quando invocado por caminho direto.
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

_DEST_PATH: Final[Path] = _REPO_ROOT / "experiments" / "dollar_threshold_drift_monthly.json"

# Mesmo racional de _TF_LOG_LABEL em measure_dollar_threshold_drift.py -- a
# soma NÃO depende de `tf` (só aparece nos logs de chunk); rótulo explícito
# pra não sugerir uma dependência que não existe.
_TF_LOG_LABEL: Final[str] = "n/a-ag124-dollar-drift-monthly"


@dataclass(slots=True, frozen=True)
class _MonthResult:
    symbol: str
    month: str  # "YYYY-MM"
    start: str
    end: str
    n_days: int
    total_dollar: float
    total_volume: float
    n_ticks: int
    dollar_per_day: float


def _month_windows(start: date, end: date) -> list[tuple[str, date, date]]:
    """Todo mês calendário que intersecta `[start, end]`, clipado nas
    duas pontas -- 1º/último mês podem ser parciais (ver docstring do
    módulo). `"YYYY-MM"` como label."""
    if end < start:
        raise ValueError(f"end ({end}) anterior a start ({start})")
    windows: list[tuple[str, date, date]] = []
    cursor_year, cursor_month = start.year, start.month
    while (cursor_year, cursor_month) <= (end.year, end.month):
        month_first = date(cursor_year, cursor_month, 1)
        next_month_first = (
            date(cursor_year + 1, 1, 1)
            if cursor_month == 12
            else date(cursor_year, cursor_month + 1, 1)
        )
        month_last = next_month_first.toordinal() - 1
        month_last_date = date.fromordinal(month_last)
        window_start = max(month_first, start)
        window_end = min(month_last_date, end)
        windows.append((f"{cursor_year:04d}-{cursor_month:02d}", window_start, window_end))
        cursor_year, cursor_month = next_month_first.year, next_month_first.month
    return windows


def _measure_symbol_month(symbol: str, month: str, start: date, end: date) -> _MonthResult:
    n_days = (end - start).days + 1
    chunk_days = int(load_data_constant("bars_streaming_chunk_days"))
    chunks = date_chunks(start.isoformat(), end.isoformat(), chunk_days=chunk_days)

    totals = scan_trades_totals(symbol, _TF_LOG_LABEL, chunks)
    if totals.n_ticks == 0:
        raise ValueError(
            f"aggTrades vazio para {symbol} no mês {month} ({start}..{end}) -- não dá "
            "pra medir deriva de threshold sem trades"
        )
    dollar_per_day = totals.total_dollar / n_days  # noqa: unguarded-ratio -- n_days>=1 por construção

    logger.info(
        "diagnostics.measure_dollar_threshold_drift_monthly.symbol_month_done",
        symbol=symbol,
        month=month,
        start=str(start),
        end=str(end),
        n_days=n_days,
        total_dollar=totals.total_dollar,
        n_ticks=totals.n_ticks,
        dollar_per_day=round(dollar_per_day, 2),
    )
    return _MonthResult(
        symbol=symbol,
        month=month,
        start=start.isoformat(),
        end=end.isoformat(),
        n_days=n_days,
        total_dollar=totals.total_dollar,
        total_volume=totals.total_volume,
        n_ticks=totals.n_ticks,
        dollar_per_day=dollar_per_day,
    )


#: Achado real (2026-08-21, 1ª rodada real deste script): `os.replace` falhou
#: com `PermissionError: [WinError 5] Acesso negado` na combinação 107/309 --
#: lock transiente do Windows (antivírus/indexador segurando o handle do
#: `.tmp` por uma fração de segundo logo após `fsync`), não um bug no padrão
#: atômico em si (B29 -- mesma escrita `.tmp` -> `fsync` -> `rename` usada em
#: todo o resto do projeto, sem problema). ~309 combinações reais tornam
#: plausível que isso aconteça de novo em QUALQUER checkpoint -- retry com
#: backoff curto é a correção direta (o lock é transiente, não permanente;
#: uma 2ª tentativa 200ms depois já bastaria na prática), não abrandar B29
#: nem trocar `os.replace` por algo não-atômico.
_REPLACE_MAX_ATTEMPTS: Final[int] = 5
_REPLACE_RETRY_DELAY_S: Final[float] = 0.5


def _atomic_write_json(payload: dict[str, Any], dest_path: Path) -> None:
    """B29 -- mesmo padrão de `measure_dollar_threshold_drift._atomic_write_json`,
    com retry curto em `os.replace` (ver `_REPLACE_MAX_ATTEMPTS` acima) --
    continua atômico (nunca um estado parcial visível no destino), só
    tolera o rename falhar transitoriamente antes de desistir de vez."""
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
                "diagnostics.measure_dollar_threshold_drift_monthly.replace_retry",
                attempt=attempt,
                max_attempts=_REPLACE_MAX_ATTEMPTS,
                dest_path=str(dest_path),
            )
            time.sleep(_REPLACE_RETRY_DELAY_S)


def _payload(results: list[_MonthResult], *, partial: bool) -> dict[str, Any]:
    rows = [
        {
            "symbol": r.symbol,
            "month": r.month,
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
            "MEASURED -- soma real de price*quantity (aggTrades) por (symbol, mês "
            "calendário), via src.data._chunked_scan.scan_trades_totals (mesma função "
            "que M2/calibrate_dollar_threshold_for_validation usam pra calibrar "
            "dollar_threshold, reaproveitada sem reimplementação). Granularidade "
            "MENSAL CONTÍNUA (todo mês desde o início real do histórico de cada "
            "símbolo), diferente de dollar_threshold_drift.json (7 janelas esparsas "
            "escolhidas a dedo) -- insumo pra decidir cadence_days/trailing_window_days "
            "de build_dollar_bars_walkforward (AG-124), não a decisão em si."
        ),
        "symbols": list(SYMBOL_START_DATE),
        "symbol_start_date": dict(SYMBOL_START_DATE),
        "end_date": END_DATE,
        "results": rows,
    }


def _load_existing_results() -> list[_MonthResult]:
    """Resume-from-checkpoint (achado real, 2026-08-21 -- ver `_REPLACE_MAX_
    ATTEMPTS`): se `_DEST_PATH` já existir (rodada anterior interrompida,
    por crash ou Ctrl-C), carrega o que já foi medido em vez de remedir do
    zero -- ~309 combinações reais custam caro o suficiente pra isso
    importar. Silenciosamente vazio (`[]`) se o arquivo não existir ou
    estiver corrompido/no formato antigo -- resume é otimização, nunca
    motivo pra falhar a rodada inteira."""
    if not _DEST_PATH.exists():
        return []
    try:
        payload = orjson.loads(_DEST_PATH.read_bytes())
        rows = payload["results"]
        loaded = [
            _MonthResult(
                symbol=r["symbol"],
                month=r["month"],
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
            "diagnostics.measure_dollar_threshold_drift_monthly.resume_load_failed",
            dest_path=str(_DEST_PATH),
            error=str(exc),
            note="checkpoint existente não pôde ser lido -- rodando do zero, não falhando",
        )
        return []
    logger.info(
        "diagnostics.measure_dollar_threshold_drift_monthly.resumed",
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
        for month, window_start, window_end in _month_windows(start_date, end_date):
            all_windows.append((symbol, month, window_start, window_end))

    n_total = len(all_windows)

    results = _load_existing_results()
    done_keys = {(r.symbol, r.month) for r in results}
    remaining = [w for w in all_windows if (w[0], w[1]) not in done_keys]

    logger.info(
        "diagnostics.measure_dollar_threshold_drift_monthly.starting",
        n_symbols=len(symbols),
        n_combinations=n_total,
        n_already_done=len(results),
        n_remaining=len(remaining),
        note="medição REAL mensal contínua de soma(price*quantity) via aggTrades -- "
        "insumo pra cadence_days/trailing_window_days de build_dollar_bars_walkforward "
        "(AG-124), não a decisão final",
    )

    for symbol, month, window_start, window_end in remaining:
        results.append(_measure_symbol_month(symbol, month, window_start, window_end))
        i = len(results)
        # Checkpoint incremental (mesmo padrão de m4_critical_windows.py, AG-019) --
        # escreve de novo a cada combinação, não só no fim. Marca partial=True até a
        # última combinação, para que uma leitura no meio do caminho seja honesta
        # sobre estar incompleta.
        _atomic_write_json(_payload(results, partial=(i < n_total)), _DEST_PATH)
        logger.info(
            "diagnostics.measure_dollar_threshold_drift_monthly.progress",
            n_done=i,
            n_total=n_total,
            symbol=symbol,
            month=month,
        )

    logger.info(
        "diagnostics.measure_dollar_threshold_drift_monthly.done",
        n_combinations=len(results),
        dest_path=str(_DEST_PATH),
    )


if __name__ == "__main__":
    main()
