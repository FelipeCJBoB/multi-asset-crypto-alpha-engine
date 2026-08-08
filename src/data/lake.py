"""Camada analítica fina sobre os parquets de `data/capacity/` (§1.2:
"Camada analítica: DuckDB sobre os arquivos. Nunca carregar `raw` inteiro em
memória.").

Duas podas acontecem antes de qualquer byte de parquet ser lido:

1. **Poda de arquivo** — os arquivos são um por dia (`yyyy-mm-dd.parquet`,
   exceto `funding`, mensal). O intervalo `[start, end]` pedido primeiro
   filtra a LISTA de arquivos pelo nome, em Python, e só os arquivos que
   intersectam o intervalo chegam ao DuckDB.
2. **Poda de predicado** — dentro dos arquivos selecionados, o DuckDB aplica
   o filtro de timestamp com pushdown a nível de row-group do Parquet, sem
   materializar o arquivo inteiro em memória Python antes de filtrar.

O resultado final vira um `pl.DataFrame` (`.pl()`) — é isso, e só isso, que
é materializado por completo; o "raw inteiro" nunca é.

Cobre as 4 fontes mais usadas (klines-like, agg_trades, metrics, funding).
Estender para uma 5ª fonte é: adicionar o `DatasetSchema` em `schemas.py` e,
se ela não for "um arquivo por dia", um caso em `_list_files_in_range`.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import duckdb
import polars as pl
import structlog

from . import schemas
from ._paths import capacity_symbol_dir
from ._util import cast_price_columns

logger = structlog.get_logger(__name__)

DateLike = date | datetime | str


def _as_date(value: DateLike) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        return date.fromisoformat(value)
    return value


def _list_day_files(symbol_dir: Path, start: date | None, end: date | None) -> list[Path]:
    files = []
    for p in sorted(symbol_dir.glob("*.parquet")):
        try:
            file_date = date.fromisoformat(p.stem)
        except ValueError:
            # arquivo fora do padrão yyyy-mm-dd.parquet — ignora (ex.: artefato solto na pasta)
            continue
        if start is not None and file_date < start:
            continue
        if end is not None and file_date > end:
            continue
        files.append(p)
    return files


def _list_month_files(symbol_dir: Path, start: date | None, end: date | None) -> list[Path]:
    files = []
    for p in sorted(symbol_dir.glob("*.parquet")):
        parts = p.stem.split("-")
        if len(parts) != 2:
            continue  # não é yyyy-mm.parquet
        try:
            year, month = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        month_start = date(year, month, 1)
        month_end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
        if start is not None and month_end <= start:
            continue
        if end is not None and month_start > end:
            continue
        files.append(p)
    return files


def _list_files_in_range(
    source: str, symbol: str, start: DateLike | None, end: DateLike | None
) -> list[Path]:
    symbol_dir = capacity_symbol_dir(source, symbol)
    start_d = _as_date(start) if start is not None else None
    end_d = _as_date(end) if end is not None else None
    schema = schemas.get_schema(source)
    if schema.name == "funding":
        return _list_month_files(symbol_dir, start_d, end_d)
    return _list_day_files(symbol_dir, start_d, end_d)


def _read_files(
    files: list[Path], *, ts_col: str | None, start_ms: int | None, end_ms: int | None
) -> pl.DataFrame:
    """DuckDB relation sobre exatamente `files` (já podados por nome), com
    filtro de timestamp e ordenação delegados ao motor — não ao Python."""
    if not files:
        return pl.DataFrame()

    con = duckdb.connect(database=":memory:")
    try:
        rel = con.read_parquet([str(f) for f in files])
        if ts_col is not None:
            conditions = []
            if start_ms is not None:
                conditions.append(f'"{ts_col}" >= {start_ms}')
            if end_ms is not None:
                conditions.append(f'"{ts_col}" <= {end_ms}')
            if conditions:
                rel = rel.filter(" AND ".join(conditions))
            rel = rel.order(f'"{ts_col}"')
        return rel.pl()
    finally:
        con.close()


def _day_bounds_ms(start: DateLike | None, end: DateLike | None) -> tuple[int | None, int | None]:
    """`start`/`end` (datas) -> limites em epoch ms UTC cobrindo o dia
    inteiro de `end` (00:00:00.000 de `start` até 23:59:59.999 de `end`).
    Todos os timestamps das fontes (`open_time`, `transact_time`,
    `calc_time`) são epoch ms UTC — construir os limites via `datetime`
    ingênuo (sem `tzinfo`) usaria o fuso LOCAL da máquina em `.timestamp()`,
    um bug de deslocamento silencioso; por isso `tzinfo=timezone.utc`
    explícito abaixo, sempre."""
    start_ms = None
    end_ms = None
    if start is not None:
        d = _as_date(start)
        start_ms = int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp() * 1000)
    if end is not None:
        d = _as_date(end)
        end_ms = (
            int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp() * 1000) + 86_400_000 - 1
        )
    return start_ms, end_ms


def query_bars(
    symbol: str = "BTCUSDT",
    tf: str = "1m",
    start: DateLike | None = None,
    end: DateLike | None = None,
    *,
    source: str = "klines_1m",
    cast_prices: bool = True,
) -> pl.DataFrame:
    """Barras OHLCV de `source` (`klines_1m`, `mark_price_klines_1m` ou
    `premium_index_klines_1m` — todas 1m no disco), reamostradas para `tf`
    se `tf != "1m"` via `resample.resample_klines`. Import de `resample`
    feito dentro da função para não criar um ciclo de import a nível de
    módulo (`resample` não precisa saber de `lake`, mas `lake` compõe
    `resample` neste único ponto)."""
    schema = schemas.get_schema(source)
    if not schema.is_klines_like:
        raise ValueError(
            f"source='{source}' não é um dataset klines-like (candidatos: klines_1m, "
            "mark_price_klines_1m, premium_index_klines_1m)"
        )

    files = _list_files_in_range(source, symbol, start, end)
    start_ms, end_ms = _day_bounds_ms(start, end)
    df = _read_files(files, ts_col="open_time", start_ms=start_ms, end_ms=end_ms)

    if cast_prices or tf != "1m":
        df = cast_price_columns(df, ("open", "high", "low", "close"))

    if tf == "1m" or df.is_empty():
        return df

    from . import resample  # import local — ver docstring

    return resample.resample_klines(df, tf)


def query_agg_trades(
    symbol: str = "BTCUSDT",
    start: DateLike | None = None,
    end: DateLike | None = None,
) -> pl.DataFrame:
    files = _list_files_in_range("agg_trades", symbol, start, end)
    start_ms, end_ms = _day_bounds_ms(start, end)
    return _read_files(files, ts_col="transact_time", start_ms=start_ms, end_ms=end_ms)


def query_metrics(
    symbol: str = "BTCUSDT",
    start: DateLike | None = None,
    end: DateLike | None = None,
) -> pl.DataFrame:
    """`create_time` é string (`"YYYY-MM-DD HH:MM:SS"`, medido — ver
    `schemas.METRICS`), não epoch — a poda fina por timestamp dentro do
    DuckDB não é aplicada aqui (comparação lexical de string funciona para
    ordenar, mas complicaria o filtro sem ganho real: a poda por ARQUIVO já
    é por dia). Quem precisa de epoch ms usa
    `_util.metrics_timestamp_to_ms` no resultado."""
    files = _list_files_in_range("metrics", symbol, start, end)
    return _read_files(files, ts_col=None, start_ms=None, end_ms=None).sort("create_time")


def query_funding(
    symbol: str = "BTCUSDT",
    start: DateLike | None = None,
    end: DateLike | None = None,
) -> pl.DataFrame:
    files = _list_files_in_range("funding", symbol, start, end)
    start_ms, end_ms = _day_bounds_ms(start, end)
    return _read_files(files, ts_col="calc_time", start_ms=start_ms, end_ms=end_ms)
