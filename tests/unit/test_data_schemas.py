"""Verifica que os `DatasetSchema` de `src/data/schemas.py` batem com os
parquets REAIS do backfill (não com o que se "esperaria" de um kline) —
check 1 do §1.3 aplicado ao próprio contrato declarado."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from src.data import schemas
from src.data._paths import CAPACITY_DIR

_FIXTURE_DAY = "2024-01-15"
_FIXTURE_MONTH = "2024-01"


def _skip_if_missing(path: Path) -> None:
    if not path.exists():
        pytest.skip(f"fixture ausente no backfill local: {path}")


@pytest.mark.parametrize(
    "source_name",
    ["klines_1m", "mark_price_klines_1m", "premium_index_klines_1m"],
)
def test_klines_like_schema_bate_com_parquet_real(source_name: str) -> None:
    path = CAPACITY_DIR / source_name / "BTCUSDT" / f"{_FIXTURE_DAY}.parquet"
    _skip_if_missing(path)
    df = pl.read_parquet(path)
    schema = schemas.get_schema(source_name)
    assert df.columns == list(schema.columns.keys())
    for col, expected_dtype in schema.columns.items():
        actual_dtype = df.schema[col]
        assert actual_dtype == expected_dtype, (
            f"{source_name}.{col}: esperado {expected_dtype}, obtido {actual_dtype}"
        )


def test_agg_trades_schema_bate_com_parquet_real() -> None:
    path = CAPACITY_DIR / "agg_trades" / "BTCUSDT" / f"{_FIXTURE_DAY}.parquet"
    _skip_if_missing(path)
    df = pl.read_parquet(path)
    schema = schemas.AGG_TRADES
    assert df.columns == list(schema.columns.keys())


def test_metrics_schema_bate_com_parquet_real() -> None:
    path = CAPACITY_DIR / "metrics" / "BTCUSDT" / f"{_FIXTURE_DAY}.parquet"
    _skip_if_missing(path)
    df = pl.read_parquet(path)
    schema = schemas.METRICS
    assert df.columns == list(schema.columns.keys())
    # create_time é string, não epoch — a característica que motivou
    # timestamp_unit="string_datetime" em schemas.METRICS
    assert df.schema["create_time"] == pl.Utf8


def test_funding_schema_bate_com_parquet_real() -> None:
    path = CAPACITY_DIR / "funding" / "BTCUSDT" / f"{_FIXTURE_MONTH}.parquet"
    _skip_if_missing(path)
    df = pl.read_parquet(path)
    schema = schemas.FUNDING
    assert df.columns == list(schema.columns.keys())


def test_get_schema_dataset_desconhecido_levanta_keyerror() -> None:
    with pytest.raises(KeyError):
        schemas.get_schema("dataset_que_nao_existe")


def test_funding_grid_step_e_none_por_design() -> None:
    # §1.3 check 19 — intervalo DERIVADO do dado, nunca assumido a priori.
    assert schemas.FUNDING.grid_step_ms is None


def test_agg_trades_grid_step_e_none_por_ser_event_driven() -> None:
    assert schemas.AGG_TRADES.grid_step_ms is None
