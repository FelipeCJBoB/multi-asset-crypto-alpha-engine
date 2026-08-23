"""Contratos de schema das fontes T1 já baixadas em `data/capacity/` (§1.3
check 1 — "schema bate com o contrato declarado: nomes, tipos, ordem").

Os dtypes abaixo não são o que se "esperaria" de um kline — são o que foi
medido nos parquets reais do backfill do Sprint 1 via
`pl.read_parquet(...).schema` (ver relatório do Sprint 2). Em particular:
`open`/`high`/`low`/`close` em `klines_1m` (e nos dois derivados de mesma
forma, `mark_price_klines_1m` e `premium_index_klines_1m`) são `Utf8`, não
`Float64` — o pipeline de download preserva a string decimal original da
Binance em vez de arredondar para float na conversão, o que importa porque
R1 (§0.2) é sensível a erro de quantização de última casa. Qualquer código
que precise de preço numérico casta explicitamente (ver `lake.py`).
"""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl


@dataclass(frozen=True, slots=True)
class DatasetSchema:
    """Contrato de uma fonte em `data/capacity/{name}/{symbol}/*.parquet`."""

    name: str
    columns: dict[str, type[pl.DataType]]  # ordem do dict == ordem de coluna esperada
    primary_key: tuple[str, ...]
    timestamp_column: str
    timestamp_unit: str  # "ms_epoch" | "string_datetime"
    non_nullable: tuple[str, ...]
    grid_step_ms: int | None  # None quando a fonte não tem grade fixa a priori (event-driven)
    is_klines_like: bool = False


_KLINES_LIKE_COLUMNS: dict[str, type[pl.DataType]] = {
    "open_time": pl.Int64,
    "open": pl.Utf8,
    "high": pl.Utf8,
    "low": pl.Utf8,
    "close": pl.Utf8,
    "volume": pl.Float64,
    "close_time": pl.Int64,
    "quote_volume": pl.Float64,
    "count": pl.Int64,
    "taker_buy_volume": pl.Float64,
    "taker_buy_quote_volume": pl.Float64,
    "ignore": pl.Utf8,
}

_KLINES_NON_NULLABLE = (
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
)

KLINES_1M = DatasetSchema(
    name="klines_1m",
    columns=dict(_KLINES_LIKE_COLUMNS),
    primary_key=("open_time",),
    timestamp_column="open_time",
    timestamp_unit="ms_epoch",
    non_nullable=_KLINES_NON_NULLABLE,
    grid_step_ms=60_000,
    is_klines_like=True,
)

MARK_PRICE_KLINES_1M = DatasetSchema(
    name="mark_price_klines_1m",
    columns=dict(_KLINES_LIKE_COLUMNS),
    primary_key=("open_time",),
    timestamp_column="open_time",
    timestamp_unit="ms_epoch",
    non_nullable=_KLINES_NON_NULLABLE,
    grid_step_ms=60_000,
    is_klines_like=True,
)

PREMIUM_INDEX_KLINES_1M = DatasetSchema(
    name="premium_index_klines_1m",
    columns=dict(_KLINES_LIKE_COLUMNS),
    primary_key=("open_time",),
    timestamp_column="open_time",
    timestamp_unit="ms_epoch",
    non_nullable=_KLINES_NON_NULLABLE,
    grid_step_ms=60_000,
    is_klines_like=True,
)

AGG_TRADES = DatasetSchema(
    name="agg_trades",
    columns={
        "agg_trade_id": pl.Int64,
        "price": pl.Float64,
        "quantity": pl.Float64,
        "first_trade_id": pl.Int64,
        "last_trade_id": pl.Int64,
        "transact_time": pl.Int64,
        "is_buyer_maker": pl.Boolean,
    },
    primary_key=("agg_trade_id",),
    timestamp_column="transact_time",
    timestamp_unit="ms_epoch",
    non_nullable=("agg_trade_id", "price", "quantity", "transact_time"),
    grid_step_ms=None,  # trades são event-driven — sem grade fixa
)

_DOLLAR_BARS_COLUMNS: dict[str, type[pl.DataType]] = {
    "open_time": pl.Int64,
    "close_time": pl.Int64,
    "open": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "close": pl.Float64,
    "volume": pl.Float64,
    "quote_volume": pl.Float64,
    "count": pl.UInt32,
    "taker_buy_volume": pl.Float64,
    "taker_buy_quote_volume": pl.Float64,
    # AG-124 (2026-08-21, Camada 0) -- threshold_usdt (em $) que fechou ESTA
    # barra especificamente, não um escalar único por diretório mais.
    # Necessário pra recalibração causal rolante (`build_dollar_bars_
    # walkforward`, `src.data.build_dollar_bars`): sob threshold que varia
    # por período de aplicação, "qual threshold gerou esta barra" deixa de
    # ser uma pergunta que `_calibration.json` sozinho consegue responder --
    # cada barra precisa carregar a própria resposta. Não-nullable (parte de
    # `non_nullable=tuple(_DOLLAR_BARS_COLUMNS)` abaixo) -- toda barra
    # escrita por `write_dollar_bars_and_calibration` vem de
    # `bars.threshold_bars_step`/`threshold_bars_finish`, que sempre
    # populam este campo com `carry.threshold` (nunca None) pro caminho de
    # dollar/volume bar.
    "threshold_quote": pl.Float64,
}


def _dollar_bars_schema(resolution_id: str) -> DatasetSchema:
    """Schema idêntico pras 3 resoluções de dollar bar (`R1`/`R2`/`R3`,
    `AG-042`) — só o `name`/dataset em disco muda
    (`data/capacity/dollar_bars_{r1,r2,r3}/{symbol}/*.parquet`), colunas e
    invariantes de timestamp são os mesmos porque a MECÂNICA de
    construção da barra (`src.data.bars.dollar_bars_carry`) não muda com
    o threshold calibrado, só o `resolution_id`/`threshold_usdt`."""
    return DatasetSchema(
        name=f"dollar_bars_{resolution_id.lower()}",
        columns=dict(_DOLLAR_BARS_COLUMNS),
        primary_key=("open_time",),
        # `close_time`, não `open_time` — usado tanto pra particionar por dia
        # calendário quanto pro filtro de range em `lake.query_dollar_bars`
        # (mesmo campo usado por `src.data.build_dollar_bars.
        # write_dollar_bars_and_calibration` pra decidir o arquivo do dia).
        timestamp_column="close_time",
        timestamp_unit="ms_epoch",
        non_nullable=tuple(_DOLLAR_BARS_COLUMNS),
        # event-driven (barra calibrada por threshold de $, não relógio) —
        # mesmo motivo de AGG_TRADES.
        grid_step_ms=None,
    )


DOLLAR_BARS_R1 = _dollar_bars_schema("R1")
DOLLAR_BARS_R2 = _dollar_bars_schema("R2")
DOLLAR_BARS_R3 = _dollar_bars_schema("R3")

_RESAMPLED_BARS_COLUMNS: dict[str, type[pl.DataType]] = {
    "open_time": pl.Int64,
    "open": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "close": pl.Float64,
    "volume": pl.Float64,
    "close_time": pl.Int64,
    "quote_volume": pl.Float64,
    "count": pl.Int64,
    "taker_buy_volume": pl.Float64,
    "taker_buy_quote_volume": pl.Float64,
}
"""Schema real de `resample.resample_klines` -- `_OHLCV_COLUMN_ORDER` de
`src/data/resample.py`, cast pra `Float64` (`cast_price_columns`) ANTES
da agregação, diferente de `_KLINES_LIKE_COLUMNS` (fonte crua, `open`/
`high`/`low`/`close` em `Utf8` por decisão de preservar a string decimal
original da Binance, §11 do docstring do módulo). Também sem a coluna
`ignore` (não sobrevive à agregação -- `_OHLCV_COLUMN_ORDER` nunca a
incluiu)."""


def _resampled_bars_schema(timeframe: str) -> DatasetSchema:
    """Schema de `bars_{timeframe}` (resampled -- `resample.resample_
    klines`, AG-174/AG-175) -- `grid_step_ms` derivado de
    `resample.step_ms(timeframe)`, a mesma função que `resample_klines`
    usa pra bucketizar, em vez de duplicar `_TIMEFRAME_MINUTES` aqui:
    a duplicação de "quanto tempo tem um TF" já causou drift real neste
    projeto por 3 vezes (`AG-004`/`AG-005`/`AG-017`) -- schemas.py importa
    de resample.py de propósito, não o contrário, sem ciclo (`resample.py`
    não importa `schemas.py`, confirmado por leitura direta)."""
    from .resample import step_ms

    return DatasetSchema(
        name=f"bars_{timeframe}",
        columns=dict(_RESAMPLED_BARS_COLUMNS),
        primary_key=("open_time",),
        timestamp_column="open_time",
        timestamp_unit="ms_epoch",
        non_nullable=tuple(_RESAMPLED_BARS_COLUMNS),
        grid_step_ms=step_ms(timeframe),
        is_klines_like=True,
    )


BARS_15M = _resampled_bars_schema("15m")
BARS_30M = _resampled_bars_schema("30m")
BARS_1H = _resampled_bars_schema("1h")

METRICS = DatasetSchema(
    name="metrics",
    columns={
        # "YYYY-MM-DD HH:MM:SS", não epoch — medido, não contrato Binance genérico
        "create_time": pl.Utf8,
        "symbol": pl.Utf8,
        "sum_open_interest": pl.Float64,
        "sum_open_interest_value": pl.Float64,
        "count_toptrader_long_short_ratio": pl.Float64,
        "sum_toptrader_long_short_ratio": pl.Float64,
        "count_long_short_ratio": pl.Float64,
        "sum_taker_long_short_vol_ratio": pl.Float64,
    },
    primary_key=("create_time",),
    timestamp_column="create_time",
    timestamp_unit="string_datetime",
    non_nullable=("create_time", "symbol"),
    # 5 minutos — medido em data/capacity/metrics/BTCUSDT (probe do Sprint 2,
    # ver relatório), não assumido da documentação da Binance. O check de
    # grade (validate.check_metrics_grid_alignment) reverifica isso a cada
    # execução; este valor é só a expectativa default para o report.
    grid_step_ms=300_000,
)

FUNDING = DatasetSchema(
    name="funding",
    columns={
        "calc_time": pl.Int64,
        "funding_interval_hours": pl.Int64,
        "last_funding_rate": pl.Utf8,
    },
    primary_key=("calc_time",),
    timestamp_column="calc_time",
    timestamp_unit="ms_epoch",
    non_nullable=("calc_time", "funding_interval_hours", "last_funding_rate"),
    # Explicitamente None — §1.3 check 19 exige derivar o intervalo do dado,
    # nunca assumir 8h (o PRD cita isso por nome). O grid_step de funding não
    # é um contrato a priori; é o próprio objeto medido pelo check 19.
    grid_step_ms=None,
)

REGISTRY: dict[str, DatasetSchema] = {
    s.name: s
    for s in (
        KLINES_1M,
        MARK_PRICE_KLINES_1M,
        PREMIUM_INDEX_KLINES_1M,
        AGG_TRADES,
        DOLLAR_BARS_R1,
        DOLLAR_BARS_R2,
        DOLLAR_BARS_R3,
        BARS_15M,
        BARS_30M,
        BARS_1H,
        METRICS,
        FUNDING,
    )
}


def get_schema(name: str) -> DatasetSchema:
    try:
        return REGISTRY[name]
    except KeyError as exc:
        raise KeyError(
            f"dataset '{name}' sem DatasetSchema registrado em src/data/schemas.py "
            f"(disponíveis: {sorted(REGISTRY)})"
        ) from exc
