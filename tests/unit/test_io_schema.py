"""Testes de `src.io.schema` — ADR-001 INV-C/INV-D."""

from __future__ import annotations

import polars as pl
import pytest

from src.io.schema import (
    ArtifactSchema,
    ColumnSpec,
    SchemaValidationError,
    schema_from_json_bytes,
    schema_to_json_bytes,
    validate_schema,
)


def test_column_spec_rejeita_dtype_nao_suportado() -> None:
    with pytest.raises(ValueError, match="dtype"):
        ColumnSpec(name="x", dtype="Decimal128")


def test_column_spec_tolerance_exige_ulp_budget() -> None:
    with pytest.raises(ValueError, match="ulp_budget"):
        ColumnSpec(name="x", dtype="Float64", parity_class="tolerance")


def test_column_spec_tolerance_com_ulp_budget_ok() -> None:
    col = ColumnSpec(name="x", dtype="Float64", parity_class="tolerance", ulp_budget=4)
    assert col.ulp_budget == 4


def test_artifact_schema_rejeita_coluna_duplicada() -> None:
    with pytest.raises(ValueError, match="duplicados"):
        ArtifactSchema(
            schema_version="1.0.0",
            primary_key=("a",),
            columns=(
                ColumnSpec(name="a", dtype="Int64"),
                ColumnSpec(name="a", dtype="Float64"),
            ),
        )


def test_artifact_schema_rejeita_primary_key_nao_declarada() -> None:
    with pytest.raises(ValueError, match="primary_key"):
        ArtifactSchema(
            schema_version="1.0.0",
            primary_key=("nao_existe",),
            columns=(ColumnSpec(name="a", dtype="Int64"),),
        )


def test_artifact_schema_bar_id_exige_ts_companion() -> None:
    with pytest.raises(ValueError, match="bar_id"):
        ArtifactSchema(
            schema_version="1.0.0",
            primary_key=("bar_id",),
            columns=(ColumnSpec(name="bar_id", dtype="Int64"),),
        )


def test_artifact_schema_bar_id_com_ts_companion_ok() -> None:
    schema = ArtifactSchema(
        schema_version="1.0.0",
        primary_key=("bar_id",),
        columns=(
            ColumnSpec(name="bar_id", dtype="Int64"),
            ColumnSpec(name="bar_close_ts_ns", dtype="Int64"),
        ),
    )
    assert schema.primary_key == ("bar_id",)


def _schema_simples() -> ArtifactSchema:
    return ArtifactSchema(
        schema_version="1.0.0",
        primary_key=("t0",),
        columns=(
            ColumnSpec(name="t0", dtype="Int64", nullable=False, role="key"),
            ColumnSpec(name="close", dtype="Float64", nullable=False),
        ),
        checks=("unique(t0)", "monotonic_increasing(t0)"),
    )


def test_validate_schema_passa_com_dado_valido() -> None:
    schema = _schema_simples()
    df = pl.DataFrame({"t0": [1, 2, 3], "close": [10.0, 11.0, 12.0]})  # noqa: magic-number
    validate_schema(df, schema)  # não levanta


def test_validate_schema_acumula_todas_as_violacoes() -> None:
    schema = _schema_simples()
    df = pl.DataFrame({"t0": [1, 1], "close": [None, 2.0]}).with_columns(
        pl.col("close").cast(pl.Float64)
    )
    with pytest.raises(SchemaValidationError) as excinfo:
        validate_schema(df, schema)
    errors = excinfo.value.errors
    assert any("primary_key" in e for e in errors)
    assert any("unique(t0)" in e for e in errors)
    assert any("nullable=False" in e for e in errors)


def test_validate_schema_pega_coluna_ausente_e_extra() -> None:
    schema = _schema_simples()
    df = pl.DataFrame({"t0": [1, 2], "outra": ["a", "b"]})
    with pytest.raises(SchemaValidationError) as excinfo:
        validate_schema(df, schema)
    errors = excinfo.value.errors
    assert any("ausentes" in e for e in errors)
    assert any("não declaradas" in e for e in errors)


def test_validate_schema_pega_dtype_errado() -> None:
    schema = _schema_simples()
    df = pl.DataFrame({"t0": [1, 2, 3], "close": [10, 11, 12]})  # Int64, não Float64
    with pytest.raises(SchemaValidationError, match="dtype"):
        validate_schema(df, schema)


def test_validate_schema_pega_nao_monotonico() -> None:
    schema = _schema_simples()
    df = pl.DataFrame({"t0": [2, 1, 3], "close": [10.0, 11.0, 12.0]})  # noqa: magic-number
    with pytest.raises(SchemaValidationError, match="monotonic_increasing"):
        validate_schema(df, schema)


def test_check_formato_desconhecido_levanta_valueerror() -> None:
    schema = ArtifactSchema(
        schema_version="1.0.0",
        primary_key=("t0",),
        columns=(ColumnSpec(name="t0", dtype="Int64"),),
        checks=("formato_nao_existe(t0)",),
    )
    df = pl.DataFrame({"t0": [1, 2, 3]})
    with pytest.raises(ValueError, match="não reconhecido"):
        validate_schema(df, schema)


def test_schema_json_round_trip_preserva_tudo() -> None:
    schema = ArtifactSchema(
        schema_version="2.1.0",
        primary_key=("t0", "symbol"),
        columns=(
            ColumnSpec(
                name="t0",
                dtype="Int64",
                nullable=False,
                role="key",
                causality_class="at_close",
            ),
            ColumnSpec(name="symbol", dtype="Utf8", nullable=False, role="key"),
            ColumnSpec(
                name="feat_1",
                dtype="Float64",
                unit="atr_units",
                parity_class="tolerance",
                ulp_budget=8,
                availability_lag_ns=3_600_000_000_000,
            ),
        ),
        checks=("unique(t0,symbol)",),
    )
    raw = schema_to_json_bytes(schema)
    restored = schema_from_json_bytes(raw)
    assert restored == schema
