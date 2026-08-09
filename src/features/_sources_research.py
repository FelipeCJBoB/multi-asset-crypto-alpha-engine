"""Carregadores de fonte NOVOS para o passe de pesquisa E2 (Faixa 2) —
não tocam `_sources.py` de produção (aditivo, não modifica nada que
`build_t1_features` já usa). Mesma disciplina causal de `_sources.py`
(asof-join `backward`, nunca um evento futuro) aplicada às fontes que
`_sources.py` ainda não carrega: `metrics` com as colunas de
posicionamento (D04, além de `sum_open_interest`), BVOL (D05, via
`data/raw/`, fora do `lake.py` capacity), e o CSV on-chain (E01, CoinMetrics)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import polars as pl
import structlog

from src.data._util import metrics_timestamp_to_ms
from src.data.lake import _list_files_in_range

from ._paths import DATA_ROOT, capacity_symbol_dir
from ._sources import DateLike, _as_date, asof_align_backward

logger = structlog.get_logger(__name__)

_METRICS_WIDE_COLUMNS: tuple[str, ...] = (
    "create_time",
    "sum_open_interest",
    "sum_open_interest_value",
    "sum_toptrader_long_short_ratio",
    "count_long_short_ratio",
    "sum_taker_long_short_vol_ratio",
)


def _list_metrics_day_files(symbol: str, start: date, end: date) -> list[Path]:
    symbol_dir = capacity_symbol_dir("metrics", symbol)
    files = []
    for p in sorted(symbol_dir.glob("*.parquet")):
        try:
            file_date = date.fromisoformat(p.stem)
        except ValueError:
            continue
        if file_date < start or file_date > end:
            continue
        files.append(p)
    return files


def load_metrics_series_wide(symbol: str, start: DateLike, end: DateLike) -> pl.DataFrame:
    """Igual a `_sources.load_oi_series_deduped`, mas lê TODAS as colunas
    de posicionamento (`_METRICS_WIDE_COLUMNS`), não só `sum_open_
    interest` -- MESMA lógica de deduplicação (mantém a linha do arquivo
    cujo nome bate com a data do `create_time`; ver docstring completa em
    `_sources.load_oi_series_deduped`, não repetida aqui). `sum_open_
    interest <= 0` também é nulado (mesmo achado do Sprint 4)."""
    start_d = _as_date(start)
    end_d = _as_date(end)
    files = _list_metrics_day_files(symbol, start_d, end_d)
    empty_schema: dict[str, pl.DataType | type[pl.DataType]] = {
        c: pl.Float64 for c in _METRICS_WIDE_COLUMNS if c != "create_time"
    }
    empty_schema = {"create_time": pl.Utf8, **empty_schema, "_ts_ms": pl.Int64}
    if not files:
        return pl.DataFrame(schema=empty_schema)

    numeric_cols = [c for c in _METRICS_WIDE_COLUMNS if c != "create_time"]
    frames = []
    for f in files:
        df = pl.read_parquet(f, columns=list(_METRICS_WIDE_COLUMNS))
        # dtype de coluna numérica varia entre arquivos diários (String em
        # alguns, Float64/Int64 em outros -- schema drift real do dump,
        # não um erro de leitura) -- normaliza ANTES do concat, senão
        # `pl.concat` levanta SchemaError na primeira divergência.
        df = df.with_columns([pl.col(c).cast(pl.Float64, strict=False) for c in numeric_cols])
        df = df.with_columns(pl.lit(f.stem).alias("_file_date"))
        frames.append(df)
    raw = pl.concat(frames, how="vertical")
    raw = raw.with_columns(pl.col("create_time").str.slice(0, 10).alias("_create_date"))
    raw = raw.with_columns((pl.col("_file_date") == pl.col("_create_date")).alias("_is_native"))
    deduped = (
        raw.sort(["create_time", "_is_native"], descending=[False, True], maintain_order=True)
        .unique(subset=["create_time"], keep="first", maintain_order=True)
        .sort("create_time")
        .drop(["_file_date", "_create_date", "_is_native"])
    )
    deduped = deduped.with_columns(
        pl.when(pl.col("sum_open_interest") <= 0)
        .then(None)
        .otherwise(pl.col("sum_open_interest"))
        .alias("sum_open_interest")
    )
    result: pl.DataFrame = metrics_timestamp_to_ms(deduped, create_time_col="create_time")
    return result


def load_metrics_wide_aligned(
    bars_15m: pl.DataFrame, symbol: str, start: DateLike, end: DateLike
) -> dict[str, pl.Series]:
    metrics = load_metrics_series_wide(symbol, start, end)
    out: dict[str, pl.Series] = {}
    for col in _METRICS_WIDE_COLUMNS[1:]:
        if metrics.is_empty():
            out[col] = pl.Series(col, [None] * bars_15m.height, dtype=pl.Float64)
        else:
            out[col] = asof_align_backward(bars_15m, metrics, "_ts_ms", col)
    return out


# ============================================================================
# BVOL (D05) — vive em data/raw/, fora do lake.py de capacity. Cobertura
# real: 2023-06-20 em diante (~3,1 anos de 6,6), granularidade ~1s. Ver
# aviso de cobertura na docstring de research_t2.py.
# ============================================================================

_BVOL_SYMBOL_DIR_NAME = "BTCBVOLUSDT"


def load_bvol_series(start: DateLike, end: DateLike) -> pl.DataFrame:
    bvol_dir = DATA_ROOT / "raw" / "bvol_index" / _BVOL_SYMBOL_DIR_NAME
    start_d, end_d = _as_date(start), _as_date(end)
    empty_schema = {"calc_time": pl.Int64, "index_value": pl.Float64}
    if not bvol_dir.exists():
        return pl.DataFrame(schema=empty_schema)
    files = []
    for p in sorted(bvol_dir.glob("*.parquet")):
        try:
            file_date = date.fromisoformat(p.stem)
        except ValueError:
            continue
        if file_date < start_d or file_date > end_d:
            continue
        files.append(p)
    if not files:
        return pl.DataFrame(schema=empty_schema)
    frames = [pl.read_parquet(f, columns=["calc_time", "index_value"]) for f in files]
    return pl.concat(frames, how="vertical").sort("calc_time")


def load_bvol_aligned(bars_15m: pl.DataFrame, start: DateLike, end: DateLike) -> pl.Series:
    bvol = load_bvol_series(start, end)
    if bvol.is_empty():
        return pl.Series("index_value", [None] * bars_15m.height, dtype=pl.Float64)
    bvol = bvol.with_columns(pl.col("calc_time").cast(pl.Int64))
    return asof_align_backward(bars_15m, bvol, "calc_time", "index_value")


# ============================================================================
# On-chain (E01, CoinMetrics CSV) — data/capacity/onchain/, granularidade
# diária. Série termina 2026-05-24 (75 dias defasada do resto do dataset
# no snapshot medido) -- barras depois disso recebem o ÚLTIMO valor
# conhecido via asof backward (nunca um valor futuro), não um valor
# inventado; ficam efetivamente "congeladas" na cauda, sinalizado no
# relatório de ranking, não escondido.
# ============================================================================

_ONCHAIN_CSV_PATH = DATA_ROOT / "capacity" / "onchain" / "btc_coinmetrics.csv"
ONCHAIN_COLUMNS: tuple[str, ...] = (
    "FlowInExUSD",
    "FlowOutExUSD",
    "AdrActCnt",
    "CapMVRVCur",
    "HashRate",
    "SplyCur",
    "SplyExNtv",
)


def load_onchain_series() -> pl.DataFrame:
    if not _ONCHAIN_CSV_PATH.exists():
        empty_schema = {"_ts_ms": pl.Int64, **dict.fromkeys(ONCHAIN_COLUMNS, pl.Float64)}
        return pl.DataFrame(schema=empty_schema)
    df = pl.read_csv(
        _ONCHAIN_CSV_PATH,
        columns=["time", *ONCHAIN_COLUMNS],
        schema_overrides=dict.fromkeys(ONCHAIN_COLUMNS, pl.Float64),
    )
    ts_expr = (
        pl.col("time")
        .str.strptime(pl.Date, "%Y-%m-%d")
        .cast(pl.Datetime("ms"))
        .dt.epoch(time_unit="ms")
        .alias("_ts_ms")
    )
    df = df.with_columns(ts_expr)
    return df.sort("_ts_ms")


def load_onchain_aligned(bars_15m: pl.DataFrame) -> pl.DataFrame:
    onchain = load_onchain_series()
    out: dict[str, pl.Series] = {}
    for col in ONCHAIN_COLUMNS:
        if onchain.is_empty():
            out[col] = pl.Series(col, [None] * bars_15m.height, dtype=pl.Float64)
        else:
            out[col] = asof_align_backward(bars_15m, onchain, "_ts_ms", col)
    return pl.DataFrame(out)


# ============================================================================
# D12f agg_order_flow_imb (D01, agg_trades) — agregação por bucket de 15m
# DIRETO no DuckDB (SUM(quantity) por lado do agressor, pushdown de
# parquet) -- nunca materializa trade-a-trade em Python/polars (seriam
# potencialmente bilhões de linhas em 6,6 anos). D11f/D13f seguem adiados
# (precisam de agregação em nível de trade dentro do bucket -- percentil e
# comprimento de sequência não são `SUM`/`GROUP BY` simples).
# ============================================================================

_BAR_MS_15M = 15 * 60_000


def load_agg_order_flow_imbalance(symbol: str, start: DateLike, end: DateLike) -> pl.DataFrame:
    """`(Σ vol_agressor_compra − Σ vol_agressor_venda) / Σ vol`, por
    bucket de 15m alinhado ao `close_time` das barras (`floor(transact_
    time / 900000) * 900000 + 900000 - 1`, mesma convenção de close_time
    exclusivo-no-fim das klines de 15m já usada no resto do repo).
    `is_buyer_maker=True` -- o AGRESSOR vendeu (bateu no bid); `False` --
    o agressor comprou (bateu no ask), convenção padrão da Binance."""
    files = _list_files_in_range("agg_trades", symbol, start, end)
    if not files:
        return pl.DataFrame(schema={"close_time": pl.Int64, "agg_order_flow_imb": pl.Float64})

    con = duckdb.connect(database=":memory:")
    try:
        rel = con.read_parquet([str(f) for f in files])  # noqa: F841 -- lido por nome via SQL abaixo
        query = f"""
            SELECT
                (CAST(transact_time / {_BAR_MS_15M} AS BIGINT) * {_BAR_MS_15M})
                    + {_BAR_MS_15M} - 1 AS close_time,
                SUM(CASE WHEN NOT is_buyer_maker THEN quantity ELSE 0 END) AS buy_vol,
                SUM(CASE WHEN is_buyer_maker THEN quantity ELSE 0 END) AS sell_vol
            FROM rel
            GROUP BY 1
            ORDER BY 1
        """
        result = con.sql(query).pl()
    finally:
        con.close()
    if result.is_empty():
        return pl.DataFrame(schema={"close_time": pl.Int64, "agg_order_flow_imb": pl.Float64})
    total = result["buy_vol"] + result["sell_vol"]
    imb = (result["buy_vol"] - result["sell_vol"]) / total
    return result.select("close_time").with_columns(imb.alias("agg_order_flow_imb"))


def load_agg_order_flow_imbalance_aligned(
    bars_15m: pl.DataFrame, symbol: str, start: DateLike, end: DateLike
) -> pl.Series:
    imb = load_agg_order_flow_imbalance(symbol, start, end)
    if imb.is_empty():
        return pl.Series("agg_order_flow_imb", [None] * bars_15m.height, dtype=pl.Float64)
    bars_close_time = bars_15m.select(
        pl.col("close_time").cast(pl.Int64), pl.arange(0, bars_15m.height).alias("_row_idx")
    )
    joined = bars_close_time.join(imb, on="close_time", how="left").sort("_row_idx")
    result: pl.Series = joined["agg_order_flow_imb"]
    return result
