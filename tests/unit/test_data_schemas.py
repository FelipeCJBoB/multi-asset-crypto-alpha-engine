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


@pytest.mark.integration
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


@pytest.mark.integration
def test_agg_trades_schema_bate_com_parquet_real() -> None:
    path = CAPACITY_DIR / "agg_trades" / "BTCUSDT" / f"{_FIXTURE_DAY}.parquet"
    _skip_if_missing(path)
    df = pl.read_parquet(path)
    schema = schemas.AGG_TRADES
    assert df.columns == list(schema.columns.keys())


@pytest.mark.integration
def test_metrics_schema_bate_com_parquet_real() -> None:
    path = CAPACITY_DIR / "metrics" / "BTCUSDT" / f"{_FIXTURE_DAY}.parquet"
    _skip_if_missing(path)
    df = pl.read_parquet(path)
    schema = schemas.METRICS
    assert df.columns == list(schema.columns.keys())
    # create_time é string, não epoch — a característica que motivou
    # timestamp_unit="string_datetime" em schemas.METRICS
    assert df.schema["create_time"] == pl.Utf8


@pytest.mark.integration
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


# ============================================================================
# DOLLAR_BARS_R1/R2/R3 -- remediação completa de M1 (AG-036, 2026-08-17):
# mesmo schema pras 3 resoluções, só o dataset name muda.
# ============================================================================


@pytest.mark.parametrize(
    ("resolution_id", "schema", "expected_name"),
    [
        ("R1", schemas.DOLLAR_BARS_R1, "dollar_bars_r1"),
        ("R2", schemas.DOLLAR_BARS_R2, "dollar_bars_r2"),
        ("R3", schemas.DOLLAR_BARS_R3, "dollar_bars_r3"),
    ],
)
def test_dollar_bars_schema_por_resolucao_tem_nome_certo(
    resolution_id: str, schema: schemas.DatasetSchema, expected_name: str
) -> None:
    assert schema.name == expected_name
    assert schema.timestamp_column == "close_time"
    assert schema.grid_step_ms is None


def test_dollar_bars_schema_r2_r3_tem_mesmas_colunas_que_r1() -> None:
    # a MECÂNICA de construção da barra não muda com o threshold calibrado
    # (só resolution_id/threshold_usdt mudam) -- as 3 resoluções precisam
    # ser estruturalmente idênticas, exceto o nome do dataset.
    assert schemas.DOLLAR_BARS_R2.columns == schemas.DOLLAR_BARS_R1.columns
    assert schemas.DOLLAR_BARS_R3.columns == schemas.DOLLAR_BARS_R1.columns
    assert schemas.DOLLAR_BARS_R2.primary_key == schemas.DOLLAR_BARS_R1.primary_key
    assert schemas.DOLLAR_BARS_R2.non_nullable == schemas.DOLLAR_BARS_R1.non_nullable


@pytest.mark.parametrize(
    "name", ["dollar_bars_r1", "dollar_bars_r2", "dollar_bars_r3"]
)
def test_get_schema_registry_tem_as_3_resolucoes(name: str) -> None:
    assert schemas.get_schema(name).name == name
