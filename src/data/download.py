"""Downloader multi-símbolo de `data.binance.vision` (CDN público, sem
chave) para `klines_1m`, `metrics`, `funding`, `agg_trades`, `book_ticker`,
`mark_price_klines_1m` — PRD_V4_1.md T0.1-T0.4. O gap original que motivou
este módulo (ETHUSDT/SOLUSDT/BNBUSDT/XRPUSDT sem histórico anterior a 2023)
já foi fechado; `agg_trades`/`book_ticker` foram adicionadas depois, por
serem as únicas que ainda faltavam pros 4 alts (ver
`constants.yaml::known_gaps`). `mark_price_klines_1m` (2026-08-13,
§15.6 item 4 do PLANO_MESTRE) fecha um gap mais crítico: os 4 alts NUNCA
tiveram essa fonte baixada — bloqueador de dado bruto pro Label Engine
(B11 exige `mark_1m` pra resolução de barreira), não achado antes porque
ninguém tinha checado a cobertura em disco especificamente pra essa fonte.

`agg_trades`/`book_ticker`/`mark_price_klines_1m` são opt-in — não entram
em `DEFAULT_SOURCES`, só rodam com `--sources <fonte>` explícito.
`book_ticker`
recorta automaticamente `[start, end]` pra `BOOK_TICKER_WINDOW_START/_END`
abaixo: sondagem HTTP direta contra `data.binance.vision` em 2026-08-11
confirmou que a janela 2023-05-16..2024-03-30 (já medida só pra BTCUSDT em
`known_gaps.d05_d08_d09_upstream_availability_shorter_than_prd_claims`) é
global — 404 antes e depois pros 4 alts também, não peculiaridade de
BTCUSDT. `agg_trades`, ao contrário de `klines_1m`, não tem cutover
monthly/daily: `daily/aggTrades` respondeu 200 em toda data sondada, de
2021-12 a 2026-08 — partição sempre `daily`.

`book_ticker` grava em `data/raw/book_ticker/{symbol}/`, não em
`data/capacity/` (layout provisório do Sprint 1, ver `_paths.py`) — schema
próprio de 5 colunas (`transaction_time`, `best_bid_price/_qty`,
`best_ask_price/_qty`), igual ao que já existe em disco pra BTCUSDT e ao
que `src/execution/fill_simulator.py::_BOOK_TICKER_COLUMNS` espera ler; o
CSV bruto da Binance tem 7 colunas (mais `update_id`, `event_time`,
descartadas aqui). Por isso não usa `schemas.DatasetSchema`/`_parse_csv`
genérico (que exige 1:1 entre colunas do CSV e do contrato) — tem parser
próprio, `_parse_book_ticker_csv`.

`src/data/validate.py:227-228` já citava este arquivo por nome (`"TODO
quando src/data/download.py existir e puder gravar SHA256 no manifest"`) —
é a lacuna que o check 2 (checksum) do Data Quality Engine vinha pulando.

**F5/T0.3 (PRD_V4_1.md §2.5, §3.1):** `daily/klines` só existe a partir de
`klines_daily_partition_cutover_date` (`config/constants.yaml`); histórico
anterior tem que vir de `monthly/klines`. `klines_partition_for_date()`
decide isso — testado em `tests/unit/test_data_download.py` (o "teste
obrigatório" que o PRD pede e que não existia). `metrics` não tem variante
`monthly/` conhecida (não documentada em `PRD_V3_2_UNIFICADO.md` nem
encontrada em código); `funding` é `monthly/`-only, já bate com o
particionamento mensal local.

**Idempotente**: pula (`status: skipped_existing`) qualquer período cujo
parquet de destino já existe — reexecutar o comando não rebaixa nem
reprocessa nada.

**Proveniência corrigida em relação ao download original**: o log de
`data/capacity/_download_log/*.jsonl` existente não tem campo `symbol`
(achado A3 do mesmo adendo) — o manifest deste módulo
(`data/capacity/_download_log/multi_asset_backfill.jsonl`) tem, em toda
linha, junto com verificação de checksum SHA256 quando o `.CHECKSUM` da
Binance está disponível (antes disso, checksum era pulado por completo).

Não importa nada de `src/exchange/` — `data.binance.vision` é um CDN de
dumps estáticos, domínio HTTP diferente de `fapi.binance.com`
(`RestClient`/`RateLimitManager` não se aplicam, ver investigação desta
sessão)."""

from __future__ import annotations

import hashlib
import io
import os
import time
import zipfile
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Final, Literal

import orjson
import polars as pl
import requests
import structlog

from . import schemas
from ._constants import load_constant
from ._paths import CAPACITY_DIR, RAW_DIR

logger = structlog.get_logger(__name__)

# CDN público, sem autenticação — estrutura de caminho conforme
# PRD_V3_2_UNIFICADO.md "Catálogo completo de fontes" (D03/D04/D07), mais a
# variante monthly/klines (F5) que o catálogo original não precisou listar
# por só ter sido usada pro backfill do BTCUSDT em `daily/`.
BASE_URL = "https://data.binance.vision"

DEFAULT_SYMBOLS = ("ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")
DEFAULT_SOURCES = ("klines_1m", "metrics", "funding")

Partition = Literal["daily", "monthly"]
ManifestStatus = Literal["ok", "missing_upstream", "checksum_mismatch", "skipped_existing"]

_MANIFEST_PATH = CAPACITY_DIR / "_download_log" / "multi_asset_backfill.jsonl"


# ============================================================================
# F5/T0.3 — seleção de partição monthly vs daily
# ============================================================================


def klines_partition_for_date(d: date) -> Partition:
    """`"monthly"` antes de `klines_daily_partition_cutover_date`
    (`config/constants.yaml`, hoje 2023-06-01 — PRD_V4_1.md §2.5 F5),
    `"daily"` a partir dela (inclusive). Não reverificado ao vivo por este
    processo (Claude Code não roda HTTP/Python) — se a data escolhida
    estiver errada pra algum mês específico, `_download_with_retries`
    trata 404 como `missing_upstream` em vez de travar o processo."""
    cutover = date.fromisoformat(str(load_constant("klines_daily_partition_cutover_date")))
    return "monthly" if d < cutover else "daily"


# ============================================================================
# Construção de URL
# ============================================================================


def _klines_url(symbol: str, partition: Partition, d: date) -> str:
    if partition == "monthly":
        period = f"{d.year:04d}-{d.month:02d}"
        return f"{BASE_URL}/data/futures/um/monthly/klines/{symbol}/1m/{symbol}-1m-{period}.zip"
    day = d.isoformat()
    return f"{BASE_URL}/data/futures/um/daily/klines/{symbol}/1m/{symbol}-1m-{day}.zip"


def _metrics_url(symbol: str, d: date) -> str:
    day = d.isoformat()
    return f"{BASE_URL}/data/futures/um/daily/metrics/{symbol}/{symbol}-metrics-{day}.zip"


def _funding_url(symbol: str, year: int, month: int) -> str:
    period = f"{year:04d}-{month:02d}"
    return (
        f"{BASE_URL}/data/futures/um/monthly/fundingRate/{symbol}/"
        f"{symbol}-fundingRate-{period}.zip"
    )


def _agg_trades_url(symbol: str, d: date) -> str:
    day = d.isoformat()
    return f"{BASE_URL}/data/futures/um/daily/aggTrades/{symbol}/{symbol}-aggTrades-{day}.zip"


def _book_ticker_url(symbol: str, d: date) -> str:
    day = d.isoformat()
    return f"{BASE_URL}/data/futures/um/daily/bookTicker/{symbol}/{symbol}-bookTicker-{day}.zip"


def _mark_price_klines_url(symbol: str, partition: Partition, d: date) -> str:
    """Mesma estrutura de `_klines_url`, trocando só `klines`->
    `markPriceKlines` no path -- confirmado via `binance/binance-public-data`
    (script `download-futures-markPriceKlines.py` + `utility.py::get_path`,
    2026-08-13: `data/futures/{trading_type}/{period}/{market_data_type}/
    {SYMBOL}/{interval}/{SYMBOL}-{interval}-{period}.zip`) e via sondagem
    HTTP direta (`.CHECKSUM`, texto plano, mais barato que baixar o `.zip`
    inteiro só pra confirmar existência): `ETHUSDT-1m-2021-12.zip.CHECKSUM`
    (monthly, início da história do ativo neste projeto) e
    `XRPUSDT-1m-2026-08-01.zip.CHECKSUM` (daily, ponta recente) responderam
    com hash SHA256 real, não 404."""
    if partition == "monthly":
        period = f"{d.year:04d}-{d.month:02d}"
        return (
            f"{BASE_URL}/data/futures/um/monthly/markPriceKlines/{symbol}/1m/"
            f"{symbol}-1m-{period}.zip"
        )
    day = d.isoformat()
    return f"{BASE_URL}/data/futures/um/daily/markPriceKlines/{symbol}/1m/{symbol}-1m-{day}.zip"


# Janela MEDIDA, não estimada — sondagem HTTP direta (200/404) contra
# data.binance.vision em 2026-08-11 pros 4 alts, confirmando que a mesma
# janela já registrada só pra BTCUSDT em constants.yaml::known_gaps
# (d05_d08_d09_upstream_availability_shorter_than_prd_claims) é uma
# descontinuação global do dump, não peculiaridade de um símbolo. Duplicada
# de propósito de `src/execution/fill_simulator.py::BOOK_TICKER_WINDOW_START/
# _END` — `data/` não pode importar de `execution/` (§14.2, hierarquia de
# camadas, direção proibida), mesmo padrão de duplicação tática já usado
# entre `data/_paths.py` e `exchange/_paths.py`.
BOOK_TICKER_WINDOW_START: Final[date] = date(2023, 5, 16)
BOOK_TICKER_WINDOW_END: Final[date] = date(2024, 3, 30)


# ============================================================================
# HTTP com retry + checksum
# ============================================================================


def _get_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {"User-Agent": "btcusdt-quant-engine/data-download (+data.binance.vision)"}
    )
    return session


def _download_with_retries(session: requests.Session, url: str) -> bytes | None:
    """`None` = HTTP 404 (`missing_upstream`, não é erro). Levanta a exceção
    depois de esgotar `data_download_max_retries` pra qualquer outra falha
    (timeout, 5xx persistente) — isso NÃO deve virar `missing_upstream`
    silencioso, é uma falha de rede/servidor, não ausência de dado."""
    timeout = float(load_constant("data_download_request_timeout_s"))
    max_retries = int(load_constant("data_download_max_retries"))
    backoff_s = float(load_constant("data_download_retry_backoff_s"))
    last_exc: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = session.get(url, timeout=timeout)
        except requests.RequestException as exc:
            last_exc = exc
            time.sleep(backoff_s * attempt)
            continue
        if resp.status_code == 404:
            return None
        if resp.status_code == 200:
            return resp.content
        last_exc = RuntimeError(f"{url} -> HTTP {resp.status_code}")
        time.sleep(backoff_s * attempt)
    assert last_exc is not None
    raise last_exc


def _verify_checksum(session: requests.Session, url: str, payload: bytes) -> bool | None:
    """`True`/`False` = verificado; `None` = `.CHECKSUM` indisponível (não
    bloqueia a escrita — mesmo estado que o resto do repo já tem hoje pros
    dados existentes, `validate.py` check 2 "skipped"). Qualquer falha ao
    buscar o `.CHECKSUM` em si (rede, não 404) também vira `None`, não
    aborta o download principal por causa de um arquivo secundário."""
    try:
        checksum_bytes = _download_with_retries(session, url + ".CHECKSUM")
    except (requests.RequestException, RuntimeError) as exc:
        logger.warning("data.download.checksum_fetch_failed", url=url, error=str(exc))
        return None
    if checksum_bytes is None:
        return None
    expected = checksum_bytes.decode("utf-8").strip().split()[0].lower()
    actual = hashlib.sha256(payload).hexdigest()
    return actual == expected


# ============================================================================
# Parsing — zip -> CSV -> DataFrame no schema declarado
# ============================================================================


def _extract_single_csv(zip_bytes: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
        if len(names) != 1:
            raise ValueError(f"zip esperado com exatamente 1 arquivo, achou {len(names)}: {names}")
        return zf.read(names[0]).decode("utf-8")


def _has_header(first_line: str, first_column_name: str) -> bool:
    """Dumps antigos da Binance não têm header; dumps recentes têm. Detecção
    por comparação exata contra o nome da primeira coluna do schema
    declarado (`schemas.py`) — mais robusto que tentar fazer parse do valor
    e assumir que falha de parse == header."""
    first_field = first_line.split(",", 1)[0].strip().strip('"')
    return first_field.lower() == first_column_name.lower()


def _parse_csv(csv_text: str, schema: schemas.DatasetSchema) -> pl.DataFrame:
    column_names = list(schema.columns.keys())
    lines = csv_text.splitlines()
    if not lines:
        return pl.DataFrame(schema=dict(schema.columns))
    skip_rows = 1 if _has_header(lines[0], column_names[0]) else 0
    # Lê tudo como Utf8 primeiro (sem inferência ambígua entre versões do
    # Polars), depois casta explicitamente só as colunas não-Utf8 pro dtype
    # do contrato — mesma disciplina de `_util.cast_price_columns` citado em
    # `lake.py`, aplicada aqui na borda de ingestão em vez de leitura.
    raw = pl.read_csv(
        io.StringIO(csv_text),
        has_header=False,
        skip_rows=skip_rows,
        new_columns=column_names,
        schema_overrides=dict.fromkeys(column_names, pl.Utf8),
    )
    # `strict=True` só para colunas que o próprio `DatasetSchema.non_nullable`
    # declara obrigatórias — um valor ilegível ali é falha de integridade real
    # e deve levantar. Para o resto (`metrics` tem 6 colunas nullable por
    # contrato, ex. `count_long_short_ratio`), "" vira null em vez de
    # crashar: medido ao vivo em 2021-12-30 (as 4 rodadas de download desta
    # sessão) — Binance não populava essas colunas de razão nos primeiros
    # dias de metrics para os alts, "" no CSV cru, não erro de rede/parse.
    #
    # `pl.Boolean` é caso à parte: medido ao vivo em 2026-08-11 (rodando
    # `uv run python -m pytest` via agente autorizado) que `.cast(Boolean,
    # strict=...)` direto de Utf8 levanta `InvalidOperationError` nesta
    # versão do Polars ("casting from Utf8View to Boolean not supported") —
    # não existe conversão implícita Utf8->Boolean no engine pra strings
    # literais "true"/"false" (só pra numérico). `agg_trades.is_buyer_maker`
    # é a única coluna Boolean do repo; comparação de string preserva null
    # (three-valued logic do Polars: `null == "true"` -> null).
    casts = [
        (
            (pl.col(name).str.to_lowercase() == "true").alias(name)
            if dtype is pl.Boolean
            else pl.col(name).cast(dtype, strict=name in schema.non_nullable)
        )
        for name, dtype in schema.columns.items()
        if dtype is not pl.Utf8
    ]
    return raw.with_columns(casts).select(column_names) if casts else raw.select(column_names)


# CSV bruto da Binance tem 7 colunas (medido via amostra real em 2026-08-11,
# ETHUSDT-bookTicker-2023-06-01.zip: header
# "update_id,best_bid_price,best_bid_qty,best_ask_price,best_ask_qty,
# transaction_time,event_time"). O contrato local em disco (BTCUSDT já
# gravado, `fill_simulator.py::_BOOK_TICKER_COLUMNS`) mantém só 5 — descarta
# `update_id`/`event_time`.
_BOOK_TICKER_RAW_COLUMNS: dict[str, type[pl.DataType]] = {
    "update_id": pl.Int64,
    "best_bid_price": pl.Float64,
    "best_bid_qty": pl.Float64,
    "best_ask_price": pl.Float64,
    "best_ask_qty": pl.Float64,
    "transaction_time": pl.Int64,
    "event_time": pl.Int64,
}
_BOOK_TICKER_OUTPUT_COLUMNS: tuple[str, ...] = (
    "transaction_time",
    "best_bid_price",
    "best_bid_qty",
    "best_ask_price",
    "best_ask_qty",
)


def _parse_book_ticker_csv(csv_text: str) -> pl.DataFrame:
    """Mesma disciplina de `_parse_csv` (lê tudo Utf8, depois casta), mas
    sem passar por `schemas.DatasetSchema` — `book_ticker` não é uma fonte
    de `data/capacity/` (ver docstring do módulo) e as 7 colunas do CSV
    bruto não batem 1:1 com as 5 colunas do contrato de disco. `strict=True`
    em todas: as 7 colunas do dump bruto são identificadores/preços/
    timestamps, nenhuma delas tem motivo conhecido pra vir vazia (ao
    contrário das razões de `metrics`, §ver `_parse_csv`) — célula vazia
    aqui é falha de integridade real, deve levantar."""
    column_names = list(_BOOK_TICKER_RAW_COLUMNS.keys())
    lines = csv_text.splitlines()
    if not lines:
        return pl.DataFrame(
            schema={c: _BOOK_TICKER_RAW_COLUMNS[c] for c in _BOOK_TICKER_OUTPUT_COLUMNS}
        )
    skip_rows = 1 if _has_header(lines[0], column_names[0]) else 0
    raw = pl.read_csv(
        io.StringIO(csv_text),
        has_header=False,
        skip_rows=skip_rows,
        new_columns=column_names,
        schema_overrides=dict.fromkeys(column_names, pl.Utf8),
    )
    casts = [
        pl.col(name).cast(dtype, strict=True)
        for name, dtype in _BOOK_TICKER_RAW_COLUMNS.items()
        if dtype is not pl.Utf8
    ]
    parsed = raw.with_columns(casts) if casts else raw
    return parsed.select(list(_BOOK_TICKER_OUTPUT_COLUMNS))


def _split_klines_by_day(df: pl.DataFrame) -> dict[date, pl.DataFrame]:
    """Um mês de `klines_1m` (`monthly/` zip) vira N dataframes diários,
    pra bater com o particionamento local `{symbol}/{yyyy-mm-dd}.parquet`
    (`lake.py::_list_day_files`)."""
    with_date = df.with_columns(
        pl.from_epoch(pl.col("open_time"), time_unit="ms").dt.date().alias("_date")
    )
    parts = with_date.partition_by("_date", as_dict=True, include_key=False)
    out: dict[date, pl.DataFrame] = {}
    for key, frame in parts.items():
        day = key[0] if isinstance(key, tuple) else key
        out[day] = frame
    return out


# ============================================================================
# Escrita atômica + manifest de proveniência
# ============================================================================


def _write_parquet_atomic(df: pl.DataFrame, dest_path: Path) -> None:
    """B29 — `.tmp` -> `fsync` -> `rename`, mesmo padrão de
    `src.data.validate.write_report_atomic`."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest_path.with_name(dest_path.name + ".tmp")
    buffer = io.BytesIO()
    df.write_parquet(buffer)
    with tmp_path.open("wb") as fh:
        fh.write(buffer.getvalue())
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, dest_path)


def _log_manifest_entry(
    *,
    symbol: str,
    source: str,
    period: str,
    status: ManifestStatus,
    n_rows: int | None = None,
    checksum_verified: bool | None = None,
) -> None:
    """Corrige A3 (`audit/prd_v4_1_review.md`): campo `symbol` presente em
    toda linha, ao contrário de `_download_log/*.jsonl` existente."""
    _MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "symbol": symbol,
        "source": source,
        "period": period,
        "status": status,
        "n_rows": n_rows,
        "checksum_verified": checksum_verified,
        "ts": datetime.now(UTC).isoformat(),
    }
    line = orjson.dumps(entry) + b"\n"
    with _MANIFEST_PATH.open("ab") as fh:
        fh.write(line)
        fh.flush()
        os.fsync(fh.fileno())


# ============================================================================
# Ranges
# ============================================================================


def _date_range(start: date, end: date) -> Iterator[date]:
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def _month_range(start: date, end: date) -> Iterator[tuple[int, int]]:
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        yield year, month
        month += 1
        if month == 13:  # noqa: magic-number — rollover de calendário
            month = 1
            year += 1


# ============================================================================
# Orquestração por fonte
# ============================================================================


def download_metrics(symbol: str, start: date, end: date, *, session: requests.Session) -> None:
    schema = schemas.METRICS
    out_dir = CAPACITY_DIR / "metrics" / symbol
    for d in _date_range(start, end):
        period = d.isoformat()
        dest = out_dir / f"{period}.parquet"
        if dest.exists():
            _log_manifest_entry(
                symbol=symbol, source="metrics", period=period, status="skipped_existing"
            )
            continue
        url = _metrics_url(symbol, d)
        payload = _download_with_retries(session, url)
        if payload is None:
            logger.warning(
                "data.download.missing_upstream",
                symbol=symbol, source="metrics", period=period, url=url,
            )
            _log_manifest_entry(
                symbol=symbol, source="metrics", period=period, status="missing_upstream"
            )
            continue
        checksum_ok = _verify_checksum(session, url, payload)
        if checksum_ok is False:
            logger.error(
                "data.download.checksum_mismatch",
                symbol=symbol, source="metrics", period=period, url=url,
            )
            _log_manifest_entry(
                symbol=symbol, source="metrics", period=period, status="checksum_mismatch"
            )
            continue
        df = _parse_csv(_extract_single_csv(payload), schema)
        _write_parquet_atomic(df, dest)
        logger.info(
            "data.download.written",
            symbol=symbol, source="metrics", period=period,
            n_rows=df.height, checksum_verified=checksum_ok,
        )
        _log_manifest_entry(
            symbol=symbol, source="metrics", period=period, status="ok",
            n_rows=df.height, checksum_verified=checksum_ok,
        )


def download_funding(symbol: str, start: date, end: date, *, session: requests.Session) -> None:
    schema = schemas.FUNDING
    out_dir = CAPACITY_DIR / "funding" / symbol
    for year, month in _month_range(start, end):
        period = f"{year:04d}-{month:02d}"
        dest = out_dir / f"{period}.parquet"
        if dest.exists():
            _log_manifest_entry(
                symbol=symbol, source="funding", period=period, status="skipped_existing"
            )
            continue
        url = _funding_url(symbol, year, month)
        payload = _download_with_retries(session, url)
        if payload is None:
            logger.warning(
                "data.download.missing_upstream",
                symbol=symbol, source="funding", period=period, url=url,
            )
            _log_manifest_entry(
                symbol=symbol, source="funding", period=period, status="missing_upstream"
            )
            continue
        checksum_ok = _verify_checksum(session, url, payload)
        if checksum_ok is False:
            logger.error(
                "data.download.checksum_mismatch",
                symbol=symbol, source="funding", period=period, url=url,
            )
            _log_manifest_entry(
                symbol=symbol, source="funding", period=period, status="checksum_mismatch"
            )
            continue
        df = _parse_csv(_extract_single_csv(payload), schema)
        _write_parquet_atomic(df, dest)
        logger.info(
            "data.download.written",
            symbol=symbol, source="funding", period=period,
            n_rows=df.height, checksum_verified=checksum_ok,
        )
        _log_manifest_entry(
            symbol=symbol, source="funding", period=period, status="ok",
            n_rows=df.height, checksum_verified=checksum_ok,
        )


def download_klines_1m(symbol: str, start: date, end: date, *, session: requests.Session) -> None:
    schema = schemas.KLINES_1M
    out_dir = CAPACITY_DIR / "klines_1m" / symbol

    def _log_days(days: list[date], status: ManifestStatus) -> None:
        for d in days:
            _log_manifest_entry(
                symbol=symbol, source="klines_1m", period=d.isoformat(), status=status
            )

    for year, month in _month_range(start, end):
        month_start = date(year, month, 1)
        month_end = (
            date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
        ) - timedelta(days=1)
        range_start = max(start, month_start)
        range_end = min(end, month_end)
        target_days = list(_date_range(range_start, range_end))
        target_paths = {d: out_dir / f"{d.isoformat()}.parquet" for d in target_days}

        if all(p.exists() for p in target_paths.values()):
            _log_days(target_days, "skipped_existing")
            continue

        partition = klines_partition_for_date(month_start)
        url = _klines_url(symbol, partition, month_start)
        payload = _download_with_retries(session, url)
        if payload is None:
            logger.warning(
                "data.download.missing_upstream",
                symbol=symbol, source="klines_1m", period=f"{year:04d}-{month:02d}",
                partition=partition, url=url,
            )
            _log_days(target_days, "missing_upstream")
            continue
        checksum_ok = _verify_checksum(session, url, payload)
        if checksum_ok is False:
            logger.error(
                "data.download.checksum_mismatch",
                symbol=symbol, source="klines_1m", period=f"{year:04d}-{month:02d}", url=url,
            )
            _log_days(target_days, "checksum_mismatch")
            continue

        df = _parse_csv(_extract_single_csv(payload), schema)
        by_day = _split_klines_by_day(df)
        n_written = 0
        for d in target_days:
            day_df = by_day.get(d)
            period = d.isoformat()
            if day_df is None or day_df.is_empty():
                logger.warning(
                    "data.download.day_missing_within_month",
                    symbol=symbol, source="klines_1m", period=period, partition=partition,
                )
                _log_days([d], "missing_upstream")
                continue
            _write_parquet_atomic(day_df, target_paths[d])
            _log_manifest_entry(
                symbol=symbol, source="klines_1m", period=period, status="ok",
                n_rows=day_df.height, checksum_verified=checksum_ok,
            )
            n_written += 1
        logger.info(
            "data.download.month_processed",
            symbol=symbol, source="klines_1m", period=f"{year:04d}-{month:02d}",
            partition=partition, n_days_written=n_written, n_days_target=len(target_days),
        )


def download_mark_price_klines_1m(
    symbol: str, start: date, end: date, *, session: requests.Session
) -> None:
    """Preenche o gap real que motivou este achado: `mark_price_klines_1m`
    nunca foi baixado pros 4 alts (só BTCUSDT tinha, via processo anterior
    a este módulo) -- bloqueador de dado bruto pro Label Engine rodar
    multi-ativo (B11 exige `mark_1m` pra resolução de barreira). URL
    confirmada via `binance/binance-public-data` (`download-futures-
    markPriceKlines.py`) + sondagem HTTP direta em 2 arquivos reais
    (`ETHUSDT-1m-2021-12.zip.CHECKSUM` monthly, `XRPUSDT-1m-2026-08-01.zip.
    CHECKSUM` daily, 2026-08-13) -- ver `_mark_price_klines_url`.

    **Diverge de propósito de `download_klines_1m` no regime `"daily"`
    (achado AG-014, `audit/architecture_gaps_log.yaml`, não corrigido em
    `download_klines_1m` por estar fora do escopo desta função):**
    `download_klines_1m` usa `_klines_url(symbol, partition, month_start)`
    também no regime diário — mas o arquivo diário da Binance cobre só
    `month_start` (o dia 1º do mês), nunca o mês inteiro, então esse
    padrão devolveria só 1 de ~30 dias como `"ok"` e marcaria o resto
    `"missing_upstream"` incorretamente. Não é uma suposição: o manifest
    real (`multi_asset_backfill.jsonl`) só tem entradas `klines_1m` até
    2022-12 (regime `"monthly"` inteiro, cutover é 2023-06-01) — o regime
    `"daily"` desse código nunca foi exercitado de verdade em produção; o
    resto da cobertura em disco veio de outro processo, anterior a este
    módulo. Esta função corrige isso: regime `"monthly"` continua 1
    request cobrindo o mês inteiro (mesma otimização, mesmo padrão de
    `download_klines_1m`); regime `"daily"` faz 1 request POR DIA (mesmo
    padrão de `download_metrics`), não tenta economizar requests
    inventando uma cobertura que a Binance não publica."""
    schema = schemas.MARK_PRICE_KLINES_1M
    out_dir = CAPACITY_DIR / "mark_price_klines_1m" / symbol
    source = "mark_price_klines_1m"

    def _log_days(days: list[date], status: ManifestStatus) -> None:
        for d in days:
            _log_manifest_entry(symbol=symbol, source=source, period=d.isoformat(), status=status)

    for year, month in _month_range(start, end):
        month_start = date(year, month, 1)
        month_end = (
            date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
        ) - timedelta(days=1)
        range_start = max(start, month_start)
        range_end = min(end, month_end)
        target_days = list(_date_range(range_start, range_end))
        target_paths = {d: out_dir / f"{d.isoformat()}.parquet" for d in target_days}

        if all(p.exists() for p in target_paths.values()):
            _log_days(target_days, "skipped_existing")
            continue

        partition = klines_partition_for_date(month_start)

        if partition == "monthly":
            url = _mark_price_klines_url(symbol, "monthly", month_start)
            payload = _download_with_retries(session, url)
            if payload is None:
                logger.warning(
                    "data.download.missing_upstream",
                    symbol=symbol, source=source, period=f"{year:04d}-{month:02d}",
                    partition=partition, url=url,
                )
                _log_days(target_days, "missing_upstream")
                continue
            checksum_ok = _verify_checksum(session, url, payload)
            if checksum_ok is False:
                logger.error(
                    "data.download.checksum_mismatch",
                    symbol=symbol, source=source, period=f"{year:04d}-{month:02d}", url=url,
                )
                _log_days(target_days, "checksum_mismatch")
                continue

            df = _parse_csv(_extract_single_csv(payload), schema)
            by_day = _split_klines_by_day(df)
            n_written = 0
            for d in target_days:
                day_df = by_day.get(d)
                period = d.isoformat()
                if day_df is None or day_df.is_empty():
                    logger.warning(
                        "data.download.day_missing_within_month",
                        symbol=symbol, source=source, period=period, partition=partition,
                    )
                    _log_days([d], "missing_upstream")
                    continue
                _write_parquet_atomic(day_df, target_paths[d])
                _log_manifest_entry(
                    symbol=symbol, source=source, period=period, status="ok",
                    n_rows=day_df.height, checksum_verified=checksum_ok,
                )
                n_written += 1
            logger.info(
                "data.download.month_processed",
                symbol=symbol, source=source, period=f"{year:04d}-{month:02d}",
                partition=partition, n_days_written=n_written, n_days_target=len(target_days),
            )
            continue

        # partition == "daily" -- a Binance publica 1 arquivo POR DIA nesse
        # regime, não 1 por mês (ver docstring, AG-014). 1 request por dia,
        # mesmo padrão de `download_metrics`.
        for d in target_days:
            period = d.isoformat()
            dest = target_paths[d]
            if dest.exists():
                _log_manifest_entry(
                    symbol=symbol, source=source, period=period, status="skipped_existing"
                )
                continue
            url = _mark_price_klines_url(symbol, "daily", d)
            payload = _download_with_retries(session, url)
            if payload is None:
                logger.warning(
                    "data.download.missing_upstream",
                    symbol=symbol, source=source, period=period, url=url,
                )
                _log_manifest_entry(
                    symbol=symbol, source=source, period=period, status="missing_upstream"
                )
                continue
            checksum_ok = _verify_checksum(session, url, payload)
            if checksum_ok is False:
                logger.error(
                    "data.download.checksum_mismatch",
                    symbol=symbol, source=source, period=period, url=url,
                )
                _log_manifest_entry(
                    symbol=symbol, source=source, period=period, status="checksum_mismatch"
                )
                continue
            df = _parse_csv(_extract_single_csv(payload), schema)
            _write_parquet_atomic(df, dest)
            logger.info(
                "data.download.written",
                symbol=symbol, source=source, period=period,
                n_rows=df.height, checksum_verified=checksum_ok,
            )
            _log_manifest_entry(
                symbol=symbol, source=source, period=period, status="ok",
                n_rows=df.height, checksum_verified=checksum_ok,
            )


def download_agg_trades(symbol: str, start: date, end: date, *, session: requests.Session) -> None:
    schema = schemas.AGG_TRADES
    out_dir = CAPACITY_DIR / "agg_trades" / symbol
    for d in _date_range(start, end):
        period = d.isoformat()
        dest = out_dir / f"{period}.parquet"
        if dest.exists():
            _log_manifest_entry(
                symbol=symbol, source="agg_trades", period=period, status="skipped_existing"
            )
            continue
        url = _agg_trades_url(symbol, d)
        payload = _download_with_retries(session, url)
        if payload is None:
            logger.warning(
                "data.download.missing_upstream",
                symbol=symbol, source="agg_trades", period=period, url=url,
            )
            _log_manifest_entry(
                symbol=symbol, source="agg_trades", period=period, status="missing_upstream"
            )
            continue
        checksum_ok = _verify_checksum(session, url, payload)
        if checksum_ok is False:
            logger.error(
                "data.download.checksum_mismatch",
                symbol=symbol, source="agg_trades", period=period, url=url,
            )
            _log_manifest_entry(
                symbol=symbol, source="agg_trades", period=period, status="checksum_mismatch"
            )
            continue
        df = _parse_csv(_extract_single_csv(payload), schema)
        _write_parquet_atomic(df, dest)
        logger.info(
            "data.download.written",
            symbol=symbol, source="agg_trades", period=period,
            n_rows=df.height, checksum_verified=checksum_ok,
        )
        _log_manifest_entry(
            symbol=symbol, source="agg_trades", period=period, status="ok",
            n_rows=df.height, checksum_verified=checksum_ok,
        )


def _clip_to_book_ticker_window(start: date, end: date) -> tuple[date, date] | None:
    """`None` = interseção vazia entre `[start, end]` pedido e a janela
    medida (`BOOK_TICKER_WINDOW_START/_END`) — nenhum dia a baixar."""
    window_start = max(start, BOOK_TICKER_WINDOW_START)
    window_end = min(end, BOOK_TICKER_WINDOW_END)
    if window_start > window_end:
        return None
    return window_start, window_end


def download_book_ticker(symbol: str, start: date, end: date, *, session: requests.Session) -> None:
    out_dir = RAW_DIR / "book_ticker" / symbol
    clipped = _clip_to_book_ticker_window(start, end)
    if clipped is None:
        logger.warning(
            "data.download.book_ticker_out_of_window",
            symbol=symbol,
            requested_start=start.isoformat(), requested_end=end.isoformat(),
            window_start=BOOK_TICKER_WINDOW_START.isoformat(),
            window_end=BOOK_TICKER_WINDOW_END.isoformat(),
        )
        return
    window_start, window_end = clipped
    if window_start > start or window_end < end:
        logger.info(
            "data.download.book_ticker_clipped_to_measured_window",
            symbol=symbol,
            requested_start=start.isoformat(), requested_end=end.isoformat(),
            effective_start=window_start.isoformat(), effective_end=window_end.isoformat(),
        )
    for d in _date_range(window_start, window_end):
        period = d.isoformat()
        dest = out_dir / f"{period}.parquet"
        if dest.exists():
            _log_manifest_entry(
                symbol=symbol, source="book_ticker", period=period, status="skipped_existing"
            )
            continue
        url = _book_ticker_url(symbol, d)
        payload = _download_with_retries(session, url)
        if payload is None:
            logger.warning(
                "data.download.missing_upstream",
                symbol=symbol, source="book_ticker", period=period, url=url,
            )
            _log_manifest_entry(
                symbol=symbol, source="book_ticker", period=period, status="missing_upstream"
            )
            continue
        checksum_ok = _verify_checksum(session, url, payload)
        if checksum_ok is False:
            logger.error(
                "data.download.checksum_mismatch",
                symbol=symbol, source="book_ticker", period=period, url=url,
            )
            _log_manifest_entry(
                symbol=symbol, source="book_ticker", period=period, status="checksum_mismatch"
            )
            continue
        df = _parse_book_ticker_csv(_extract_single_csv(payload))
        _write_parquet_atomic(df, dest)
        logger.info(
            "data.download.written",
            symbol=symbol, source="book_ticker", period=period,
            n_rows=df.height, checksum_verified=checksum_ok,
        )
        _log_manifest_entry(
            symbol=symbol, source="book_ticker", period=period, status="ok",
            n_rows=df.height, checksum_verified=checksum_ok,
        )


SOURCE_DOWNLOADERS = {
    "klines_1m": download_klines_1m,
    "metrics": download_metrics,
    "funding": download_funding,
    "agg_trades": download_agg_trades,
    "book_ticker": download_book_ticker,
    "mark_price_klines_1m": download_mark_price_klines_1m,
}


def download_symbol(symbol: str, sources: tuple[str, ...], start: date, end: date) -> None:
    session = _get_session()
    for source in sources:
        fn = SOURCE_DOWNLOADERS.get(source)
        if fn is None:
            raise ValueError(
                f"fonte desconhecida: {source!r} (disponíveis: {sorted(SOURCE_DOWNLOADERS)})"
            )
        logger.info(
            "data.download.source_start",
            symbol=symbol, source=source, start=start.isoformat(), end=end.isoformat(),
        )
        fn(symbol, start, end, session=session)


if __name__ == "__main__":  # pragma: no cover — execução manual
    import argparse
    import sys

    def _parse_args() -> argparse.Namespace:
        parser = argparse.ArgumentParser(
            description=(
                "Downloader multi-ativo de data.binance.vision (klines_1m, "
                "metrics, funding, agg_trades, book_ticker, "
                "mark_price_klines_1m -- os 3 ultimos sao opt-in, precisam de "
                "--sources explicito; book_ticker recorta automaticamente "
                "para a janela medida 2023-05-16..2024-03-30). "
                "Idempotente (pula periodo ja existente em "
                "disco), verifica checksum SHA256 quando o .CHECKSUM da Binance "
                "esta disponivel, loga cada periodo com campo symbol em "
                "data/capacity/_download_log/multi_asset_backfill.jsonl "
                "(book_ticker loga em data/raw/book_ticker/{symbol}/)."
            )
        )
        parser.add_argument("--symbols", nargs="+", default=list(DEFAULT_SYMBOLS))
        parser.add_argument(
            "--sources",
            nargs="+",
            default=list(DEFAULT_SOURCES),
            choices=sorted(SOURCE_DOWNLOADERS),
        )
        parser.add_argument("--start", required=True, help="ISO date, ex. 2021-12-01")
        parser.add_argument("--end", required=True, help="ISO date, ex. 2022-12-31")
        return parser.parse_args()

    def _run_cli() -> int:
        args = _parse_args()
        start = date.fromisoformat(args.start)
        end = date.fromisoformat(args.end)
        for symbol in args.symbols:
            download_symbol(symbol, tuple(args.sources), start, end)
        logger.info(
            "data.download.cli_done",
            symbols=args.symbols, sources=args.sources, start=args.start, end=args.end,
            manifest=str(_MANIFEST_PATH),
        )
        return 0

    sys.exit(_run_cli())
