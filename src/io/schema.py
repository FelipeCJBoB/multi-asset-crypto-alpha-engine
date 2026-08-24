"""Contrato de schema versionado para artefatos do lake local — INV-C
(causalidade por coluna) e INV-D (paridade como CI) do ADR-001
(`docs/ADR-001_arquitetura_artefatos_e_contratos_2026-08-19_base.md` §3.0,
ratificado pelo Manager 2026-08-20). Zero I/O aqui — só estrutura de dado
e validação; `src.io.artifact` importa este módulo, nunca o contrário.

`causality_class`/`availability_lag_ns` (INV-C) e `parity_class`/
`ulp_budget` (INV-D) são metadado OPCIONAL por coluna — este módulo não
interpreta o SIGNIFICADO desses campos (não decide o que "strict_past"
implica sobre o resto do pipeline), só carrega e valida a forma. Política
de domínio (ex. "feature sem `parity_class` não entra na matriz de
design") é responsabilidade de quem chama — mesma disciplina de
`src.core.metric.Metric` (carrega metadado, não decide política)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import orjson
import polars as pl

CausalityClass = Literal["strict_past", "at_close", "forward_looking"]
ParityClass = Literal["exact", "tolerance"]
ColumnRole = Literal["key", "payload", "partition"]

# Tipos escalares desde v1.
_DTYPE_BY_NAME: dict[str, type[pl.DataType]] = {
    "Int8": pl.Int8,
    "Int16": pl.Int16,
    "Int32": pl.Int32,
    "Int64": pl.Int64,
    "Float32": pl.Float32,
    "Float64": pl.Float64,
    "Utf8": pl.Utf8,
    "Boolean": pl.Boolean,
}

# Tipos PARAMETRIZADOS (instância, não classe -- `_DTYPE_BY_NAME` não
# serve, `pl.List(pl.Utf8)`/`pl.Datetime(...)` não são `type[pl.DataType]`
# comparável diretamente do mesmo jeito que `pl.Int64`). Achado real,
# migração LightGBM do Alpha (D-06): `io/artifact.py`/`io/schema.py`
# (ADR-001) nunca tinham um consumidor real até agora -- `v1` só cobria
# tipos escalares simples, nunca exercitado contra os 2 padrões que
# `labels.parquet`/`predictions.parquet` de fato usam: `t0` é
# `pl.Datetime(time_unit="ms", time_zone="UTC")` (nunca Int64
# nanoseconds, ao contrário do que a convenção `bar_id`/`*_ts_ns` do
# docstring do módulo sugeria), e
# `predictions.parquet::features_selecionadas` é `List[Utf8]`.
#
# CORREÇÃO 2026-08-23 (achado `audit_engineering`): a versão anterior
# deste comentário dizia "os 2 padrões que TODO artefato real do
# projeto usa" -- FALSO, verificado por leitura de código.
# `regimes.parquet` (`src/regime/classifier.py::classify_regimes`) usa
# `t0` como `Datetime(time_unit="ns", time_zone="UTC")` (não ms) e 3
# colunas (`regime`/`regime_raw`/`econ_regime`) como `pl.Enum(...)`;
# `labels.parquet` usa `pl.Categorical` pra `barrier_hit`. Nenhum dos 3
# (`Datetime[ns,UTC]`, `Enum`, `Categorical`) está coberto aqui --
# extensão MÍNIMA pro caso de uso real de hoje (`predictions.parquet`),
# não "todo tipo que qualquer artefato do projeto usa". Quem migrar
# `regimes.parquet`/`labels.parquet` pra este writer no futuro (`io/
# artifact.py:17-22` já nomeia os dois como candidatos) vai precisar
# estender `_PARAMETRIZED_DTYPE_BY_NAME` de novo. `Struct` genérico
# continua fora -- nenhum artefato real precisa.
_PARAMETRIZED_DTYPE_BY_NAME: dict[str, pl.DataType] = {
    "List[Utf8]": pl.List(pl.Utf8),
    "Datetime[ms,UTC]": pl.Datetime(time_unit="ms", time_zone="UTC"),
}


@dataclass(frozen=True, slots=True)
class ColumnSpec:
    """Declaração de 1 coluna do artefato. `dtype` é uma chave de
    `_DTYPE_BY_NAME`. `causality_class`/`availability_lag_ns`/
    `parity_class`/`ulp_budget` default `None` — coluna sem esse metadado
    é aceita (retrofit gradual do catálogo existente, não migração
    forçada de tudo de uma vez)."""

    name: str
    dtype: str
    nullable: bool = True
    role: ColumnRole = "payload"
    unit: str | None = None
    causality_class: CausalityClass | None = None
    availability_lag_ns: int | None = None
    parity_class: ParityClass | None = None
    ulp_budget: int | None = None

    def __post_init__(self) -> None:
        if self.dtype not in _DTYPE_BY_NAME and self.dtype not in _PARAMETRIZED_DTYPE_BY_NAME:
            raise ValueError(
                f"ColumnSpec({self.name!r}): dtype={self.dtype!r} não suportado -- "
                f"esperado um de {sorted({*_DTYPE_BY_NAME, *_PARAMETRIZED_DTYPE_BY_NAME})}"
            )
        if self.parity_class == "tolerance" and self.ulp_budget is None:
            raise ValueError(
                f"ColumnSpec({self.name!r}): parity_class='tolerance' exige "
                "ulp_budget declarado (INV-D, ADR-001 V-04) -- sem orçamento, o "
                "teste de paridade não sabe quanto de erro de ponto flutuante é aceitável"
            )

    def polars_dtype(self) -> pl.DataType | type[pl.DataType]:
        parametrized = _PARAMETRIZED_DTYPE_BY_NAME.get(self.dtype)
        if parametrized is not None:
            return parametrized
        return _DTYPE_BY_NAME[self.dtype]


def _check_unique(df: pl.DataFrame, cols: tuple[str, ...]) -> str | None:
    if df.select(list(cols)).is_duplicated().any():
        return f"unique({','.join(cols)}): valores duplicados encontrados"
    return None


def _check_monotonic_increasing(df: pl.DataFrame, col: str) -> str | None:
    if not df[col].is_sorted():
        return f"monotonic_increasing({col}): coluna não está ordenada crescente"
    return None


def _parse_and_run_check(df: pl.DataFrame, check: str) -> str | None:
    """Whitelist fechada, nunca `eval` — só 2 formatos reconhecidos:
    `unique(col[,col...])` e `monotonic_increasing(col)`. Formato
    desconhecido levanta `ValueError` (falha alto, nunca ignorado em
    silêncio)."""
    stripped = check.strip()
    if stripped.startswith("unique(") and stripped.endswith(")"):
        cols = tuple(c.strip() for c in stripped[len("unique(") : -1].split(","))
        return _check_unique(df, cols)
    if stripped.startswith("monotonic_increasing(") and stripped.endswith(")"):
        col = stripped[len("monotonic_increasing(") : -1].strip()
        return _check_monotonic_increasing(df, col)
    raise ValueError(
        f"check {check!r} não reconhecido -- formatos suportados: "
        "'unique(col[,col...])', 'monotonic_increasing(col)'"
    )


@dataclass(frozen=True, slots=True)
class ArtifactSchema:
    """Contrato de schema completo de 1 estágio — serializado como
    `schema.json`, validado na escrita E na leitura (INV-D: "o objetivo
    do feature store é servir em produção exatamente os valores usados no
    treino"). `schema_version` entra no payload do `config_hash` de quem
    chama (V-08) — este módulo não calcula `config_hash` sozinho, isso é
    responsabilidade de `src.io.artifact`."""

    schema_version: str
    primary_key: tuple[str, ...]
    columns: tuple[ColumnSpec, ...]
    checks: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        names = tuple(c.name for c in self.columns)
        if len(names) != len(set(names)):
            raise ValueError(f"ArtifactSchema: nomes de coluna duplicados em {names}")
        missing_pk = [k for k in self.primary_key if k not in names]
        if missing_pk:
            raise ValueError(
                f"ArtifactSchema: primary_key {missing_pk} não declarado(s) em columns"
            )
        # V-01 -- se `bar_id` compõe a chave primária, exige uma coluna
        # `*_ts_ns` companheira (payload, nunca removível): bar_id sozinho,
        # sem timestamp de auditoria, é exatamente o erro que V-01
        # documenta (bar_id só é seguro DENTRO de um config_hash; sem
        # timestamp, não dá pra auditar/realinhar entre configs
        # recalibrados). Nenhum artefato real hoje declara bar_id --
        # regra fica pronta pra quando o primeiro declarar.
        if "bar_id" in self.primary_key:
            has_ts_companion = any(c.name.endswith("_ts_ns") for c in self.columns)
            if not has_ts_companion:
                raise ValueError(
                    "ArtifactSchema: primary_key inclui 'bar_id' mas nenhuma coluna "
                    "'*_ts_ns' declarada -- V-01 exige timestamp de auditoria "
                    "acompanhando bar_id, nunca bar_id como única referência temporal"
                )

    def column_names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.columns)

    def polars_schema(self) -> dict[str, pl.DataType | type[pl.DataType]]:
        return {c.name: c.polars_dtype() for c in self.columns}


class SchemaValidationError(ValueError):
    """Levantado por `validate_schema` com TODAS as violações encontradas
    de uma vez (não fail-fast na primeira) — numa pipeline onde uma
    rodada já é lenta, descobrir os N problemas juntos custa menos que N
    round-trips."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def validate_schema(df: pl.DataFrame, schema: ArtifactSchema) -> None:
    """Valida `df` contra `schema` — colunas obrigatórias/extras,
    dtype/nulidade por coluna, unicidade de `primary_key`, e os `checks`
    declarados. Levanta `SchemaValidationError` com a lista completa de
    violações; não retorna nada em caso de sucesso."""
    errors: list[str] = []
    declared = schema.column_names()
    present = tuple(df.columns)

    missing = [c for c in declared if c not in present]
    if missing:
        errors.append(f"colunas obrigatórias ausentes: {missing}")
    extra = [c for c in present if c not in declared]
    if extra:
        errors.append(f"colunas não declaradas no schema: {extra}")

    for col in schema.columns:
        if col.name not in present:
            continue
        actual_dtype = df.schema[col.name]
        expected_dtype = col.polars_dtype()
        if actual_dtype != expected_dtype:
            errors.append(f"{col.name}: dtype={actual_dtype} esperado {expected_dtype}")
        if not col.nullable and df[col.name].null_count() > 0:
            errors.append(f"{col.name}: nullable=False mas tem valor nulo")

    if (
        schema.primary_key
        and all(k in present for k in schema.primary_key)
        and df.select(list(schema.primary_key)).is_duplicated().any()
    ):
        errors.append(f"primary_key {schema.primary_key}: valores duplicados")

    for check in schema.checks:
        msg = _parse_and_run_check(df, check)
        if msg is not None:
            errors.append(msg)

    if errors:
        raise SchemaValidationError(errors)


def schema_to_json_bytes(schema: ArtifactSchema) -> bytes:
    payload: dict[str, Any] = {
        "schema_version": schema.schema_version,
        "primary_key": list(schema.primary_key),
        "checks": list(schema.checks),
        "columns": [
            {
                "name": c.name,
                "dtype": c.dtype,
                "nullable": c.nullable,
                "role": c.role,
                "unit": c.unit,
                "causality_class": c.causality_class,
                "availability_lag_ns": c.availability_lag_ns,
                "parity_class": c.parity_class,
                "ulp_budget": c.ulp_budget,
            }
            for c in schema.columns
        ],
    }
    return orjson.dumps(payload, option=orjson.OPT_SORT_KEYS | orjson.OPT_INDENT_2)


def schema_from_json_bytes(raw: bytes) -> ArtifactSchema:
    payload = orjson.loads(raw)
    columns = tuple(
        ColumnSpec(
            name=c["name"],
            dtype=c["dtype"],
            nullable=c["nullable"],
            role=c["role"],
            unit=c.get("unit"),
            causality_class=c.get("causality_class"),
            availability_lag_ns=c.get("availability_lag_ns"),
            parity_class=c.get("parity_class"),
            ulp_budget=c.get("ulp_budget"),
        )
        for c in payload["columns"]
    )
    return ArtifactSchema(
        schema_version=payload["schema_version"],
        primary_key=tuple(payload["primary_key"]),
        columns=columns,
        checks=tuple(payload.get("checks", ())),
    )


__all__ = [
    "ArtifactSchema",
    "CausalityClass",
    "ColumnRole",
    "ColumnSpec",
    "ParityClass",
    "SchemaValidationError",
    "schema_from_json_bytes",
    "schema_to_json_bytes",
    "validate_schema",
]
