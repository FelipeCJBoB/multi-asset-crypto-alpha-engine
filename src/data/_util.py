"""Helpers pequenos e sem estado, compartilhados por `checks.py`, `resample.py`,
`lake.py` e `validate.py` — nada aqui é específico de um dataset."""

from __future__ import annotations

from datetime import UTC, datetime

import polars as pl


def cast_price_columns(df: pl.DataFrame, columns: tuple[str, ...]) -> pl.DataFrame:
    """Casta para `Float64` as colunas de `columns` que hoje são `Utf8` — caso
    de `open/high/low/close` em klines_1m e derivados (ver `schemas.py` para o
    porquê de chegarem como string). Idempotente: coluna já `Float64` passa
    direto."""
    to_cast = [c for c in columns if c in df.columns and df.schema[c] == pl.Utf8]
    if not to_cast:
        return df
    return df.with_columns([pl.col(c).cast(pl.Float64) for c in to_cast])


def ms_to_iso(epoch_ms: int) -> str:
    """Epoch ms (UTC, sem ambiguidade de fuso por construção) -> ISO 8601
    truncado ao segundo, formato usado nos exemplos do §1.3."""
    return datetime.fromtimestamp(epoch_ms // 1000, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def metrics_timestamp_to_ms(
    df: pl.DataFrame, *, create_time_col: str = "create_time"
) -> pl.DataFrame:
    """`metrics` (D04) grava `create_time` como string `"YYYY-MM-DD HH:MM:SS"`
    (medido — ver `schemas.METRICS`), não epoch. Adiciona `_ts_ms` (Int64,
    epoch ms) para que os checks temporais genéricos (que operam em epoch ms)
    funcionem sem duplicar lógica de parsing string em cada check."""
    return df.with_columns(
        pl.col(create_time_col)
        .str.strptime(pl.Datetime, "%Y-%m-%d %H:%M:%S")
        .dt.replace_time_zone("UTC")
        .dt.epoch(time_unit="ms")
        .alias("_ts_ms")
    )
