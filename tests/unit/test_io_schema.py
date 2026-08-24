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


def test_column_spec_list_utf8_aceito_e_polars_dtype_correto() -> None:
    """D-06 (docs/alpha_model_design_doc_2026-08-22.md) -- achado real:
    `predictions.parquet::features_selecionadas` é `List[Utf8]`, primeiro
    artefato real do projeto a precisar de coluna não-escalar. `v1` só
    aceitava tipos escalares (docstring do módulo) -- extensão mínima,
    não `Struct` genérico."""
    col = ColumnSpec(name="features_selecionadas", dtype="List[Utf8]")
    assert col.polars_dtype() == pl.List(pl.Utf8)


def test_validate_schema_aceita_coluna_list_utf8() -> None:
    schema = ArtifactSchema(
        schema_version="1.0.0",
        primary_key=("t0",),
        columns=(
            ColumnSpec(name="t0", dtype="Int64", nullable=False, role="key"),
            ColumnSpec(name="features_selecionadas", dtype="List[Utf8]"),
        ),
    )
    df = pl.DataFrame(
        {"t0": [1, 2], "features_selecionadas": [["A", "B"], ["A", "B"]]},
        schema={"t0": pl.Int64, "features_selecionadas": pl.List(pl.Utf8)},
    )
    validate_schema(df, schema)  # não levanta


def test_column_spec_datetime_ms_utc_aceito_e_polars_dtype_correto() -> None:
    """D-06 -- `t0` de `labels.parquet`/`predictions.parquet` é
    `pl.Datetime(time_unit="ms", time_zone="UTC")` (nunca Int64
    nanoseconds, ao contrário do que a convenção `*_ts_ns` do módulo
    `io/artifact.py` sugeria) -- `io/schema.py` nunca teve um consumidor
    real até D-06, esse gap nunca tinha sido exercitado. NÃO é o padrão
    de TODO artefato do projeto (achado `audit_engineering`,
    2026-08-23) -- `regimes.parquet` usa `Datetime[ns,UTC]`, fora do
    escopo desta extensão mínima."""
    col = ColumnSpec(name="t0", dtype="Datetime[ms,UTC]")
    assert col.polars_dtype() == pl.Datetime(time_unit="ms", time_zone="UTC")


def test_validate_schema_aceita_coluna_datetime_ms_utc() -> None:
    import datetime as dt

    schema = ArtifactSchema(
        schema_version="1.0.0",
        primary_key=("t0",),
        columns=(ColumnSpec(name="t0", dtype="Datetime[ms,UTC]", nullable=False, role="key"),),
    )
    df = pl.DataFrame(
        {"t0": [dt.datetime(2024, 1, 1, tzinfo=dt.UTC), dt.datetime(2024, 1, 2, tzinfo=dt.UTC)]},
        schema={"t0": pl.Datetime(time_unit="ms", time_zone="UTC")},
    )
    validate_schema(df, schema)  # não levanta


def test_validate_schema_datetime_pega_time_unit_diferente() -> None:
    """Achado real (`audit_engineering`, 2026-08-23): `Datetime` é o
    único tipo parametrizado do módulo com 2 parâmetros simultâneos
    (`time_unit`+`time_zone`) -- só o caso feliz e um mismatch de CLASSE
    inteira (List vs Int64) eram testados antes, nunca um mismatch de
    PARÂMETRO dentro da mesma classe. Verificado por leitura do
    código-fonte do polars que a comparação de instância já pega isso
    corretamente hoje (`Datetime.__eq__` compara `time_unit` E
    `time_zone`) -- este teste trava essa invariante como regressão."""
    schema = ArtifactSchema(
        schema_version="1.0.0",
        primary_key=("t0",),
        columns=(ColumnSpec(name="t0", dtype="Datetime[ms,UTC]", nullable=False, role="key"),),
    )
    df = pl.DataFrame({"t0": [1, 2]}, schema={"t0": pl.Datetime(time_unit="us", time_zone="UTC")})
    with pytest.raises(SchemaValidationError, match="dtype"):
        validate_schema(df, schema)


def test_validate_schema_datetime_pega_time_zone_ausente() -> None:
    schema = ArtifactSchema(
        schema_version="1.0.0",
        primary_key=("t0",),
        columns=(ColumnSpec(name="t0", dtype="Datetime[ms,UTC]", nullable=False, role="key"),),
    )
    df = pl.DataFrame({"t0": [1, 2]}, schema={"t0": pl.Datetime(time_unit="ms", time_zone=None)})
    with pytest.raises(SchemaValidationError, match="dtype"):
        validate_schema(df, schema)


def test_validate_schema_list_utf8_pega_dtype_errado() -> None:
    schema = ArtifactSchema(
        schema_version="1.0.0",
        primary_key=("t0",),
        columns=(ColumnSpec(name="t0", dtype="List[Utf8]"),),
    )
    df = pl.DataFrame({"t0": [1, 2, 3]})  # Int64, não List[Utf8]
    with pytest.raises(SchemaValidationError, match="dtype"):
        validate_schema(df, schema)


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


def test_schema_json_round_trip_preserva_list_utf8() -> None:
    schema = ArtifactSchema(
        schema_version="1.0.0",
        primary_key=("t0",),
        columns=(
            ColumnSpec(name="t0", dtype="Int64", nullable=False, role="key"),
            ColumnSpec(name="features_selecionadas", dtype="List[Utf8]"),
        ),
    )
    raw = schema_to_json_bytes(schema)
    restored = schema_from_json_bytes(raw)
    assert restored == schema
    assert restored.columns[1].polars_dtype() == pl.List(pl.Utf8)
