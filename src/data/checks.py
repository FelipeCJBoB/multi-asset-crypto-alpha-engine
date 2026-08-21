"""Primitivas atômicas do Data Quality Engine (§1.3 RF-003).

Cada função aqui implementa UM check da lista de 23 do PRD e não sabe nada
sobre JSON de saída, dataset específico ou gate PASS/FAIL — isso é
responsabilidade de `validate.py`, que compõe estas primitivas por dataset e
decide o que é aplicável. Mantém as duas responsabilidades separadas: testar
uma condição (`checks.py`) vs decidir o que fazer com o resultado
(`validate.py`).

Numeração de check no docstring de cada função é a do PRD §1.3, para
rastreabilidade — não é ordem de execução nem de definição.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import polars as pl

from . import schemas
from ._constants import load_constant

# ============================================================================
# check 1 — schema bate com o contrato (nomes, tipos, ordem)
# ============================================================================


@dataclass(frozen=True, slots=True)
class SchemaCheckResult:
    passed: bool
    missing_columns: tuple[str, ...]
    extra_columns: tuple[str, ...]
    dtype_mismatches: tuple[str, ...]
    order_matches: bool


def check_schema(df: pl.DataFrame, schema: schemas.DatasetSchema) -> SchemaCheckResult:
    expected_cols = list(schema.columns.keys())
    actual_cols = df.columns

    missing = tuple(c for c in expected_cols if c not in actual_cols)
    extra = tuple(c for c in actual_cols if c not in schema.columns)

    mismatches: list[str] = []
    for col, expected_dtype in schema.columns.items():
        if col not in df.schema:
            continue
        actual_dtype = df.schema[col]
        if actual_dtype != expected_dtype:
            mismatches.append(f"{col}: esperado {expected_dtype}, obtido {actual_dtype}")

    order_matches = actual_cols == expected_cols
    passed = not missing and not extra and not mismatches and order_matches
    return SchemaCheckResult(passed, missing, extra, tuple(mismatches), order_matches)


# ============================================================================
# check 3 — sem linhas duplicadas por chave primária
# ============================================================================


@dataclass(frozen=True, slots=True)
class DuplicatesResult:
    excess_rows: int  # total - distintas por PK (linhas "a mais")
    distinct_keys_with_duplicates: int
    example_keys: tuple[dict[str, object], ...]


def check_duplicates(df: pl.DataFrame, primary_key: tuple[str, ...]) -> DuplicatesResult:
    key_cols = list(primary_key)
    n_total = df.height
    n_distinct = df.select(key_cols).unique().height
    excess = n_total - n_distinct

    if len(key_cols) > 1:
        dup_expr = pl.struct(key_cols).is_duplicated()
    else:
        dup_expr = pl.col(key_cols[0]).is_duplicated()
    dup_keys_df = df.filter(dup_expr).select(key_cols).unique()
    examples = tuple(dup_keys_df.head(20).to_dicts())
    return DuplicatesResult(excess, dup_keys_df.height, examples)


# ============================================================================
# check 4 — sem valores nulos em colunas não-anuláveis
# ============================================================================


@dataclass(frozen=True, slots=True)
class NullsResult:
    counts: dict[str, int]

    @property
    def total(self) -> int:
        return sum(self.counts.values())


def check_nulls(df: pl.DataFrame, non_nullable: tuple[str, ...]) -> NullsResult:
    cols = [c for c in non_nullable if c in df.columns]
    if not cols:
        return NullsResult({})
    counts_df = df.select(cols).null_count()
    counts = {c: int(counts_df[c][0]) for c in cols}
    return NullsResult(counts)


# ============================================================================
# check 5 + check 8 — timestamps estritamente monotônicos / sem barras fora
# de ordem. As duas condições do PRD colapsam na mesma verificação: um
# "diff <= 0" captura tanto duplicata de timestamp (diff == 0, já coberto
# também pelo check 3) quanto barra fora de ordem (diff < 0).
# ============================================================================


@dataclass(frozen=True, slots=True)
class MonotonicResult:
    is_strictly_monotonic: bool
    non_positive_diff_count: int


def check_monotonic(df: pl.DataFrame, ts_col_ms: str) -> MonotonicResult:
    diffs = df.select(pl.col(ts_col_ms).diff().alias("_d")).drop_nulls()
    bad = diffs.filter(pl.col("_d") <= 0).height
    return MonotonicResult(bad == 0, bad)


# ============================================================================
# check 7 — close_time = open_time + intervalo - 1ms (convenção Binance)
# ============================================================================


@dataclass(frozen=True, slots=True)
class CloseTimeConventionResult:
    passed: bool
    violation_count: int


def check_close_time_convention(df: pl.DataFrame, step_ms: int) -> CloseTimeConventionResult:
    bad = df.filter(pl.col("close_time") != (pl.col("open_time") + step_ms - 1)).height
    return CloseTimeConventionResult(bad == 0, bad)


# ============================================================================
# check 9 — grade temporal completa, timestamps ausentes LISTADOS (não só
# contados — requisito explícito do PRD, "não silenciosa"). Implementado com
# anti-join do Polars em vez de um `set` Python — escala para o histórico
# inteiro (~3.5M timestamps de 1m) sem materializar uma estrutura Python por
# elemento.
# ============================================================================


@dataclass(frozen=True, slots=True)
class GridCompletenessResult:
    expected_count: int
    actual_count: int
    missing_count: int
    missing_timestamps_ms: tuple[int, ...]


def check_grid_completeness(
    df: pl.DataFrame,
    ts_col_ms: str,
    step_ms: int,
    *,
    start_ms: int | None = None,
    end_ms: int | None = None,
) -> GridCompletenessResult:
    if df.is_empty():
        return GridCompletenessResult(0, 0, 0, ())

    lo = start_ms if start_ms is not None else int(df[ts_col_ms].min())  # type: ignore[arg-type]
    hi = end_ms if end_ms is not None else int(df[ts_col_ms].max())  # type: ignore[arg-type]

    expected = pl.DataFrame({ts_col_ms: pl.arange(lo, hi + step_ms, step_ms, eager=True)}).filter(
        pl.col(ts_col_ms) <= hi
    )
    missing = expected.join(df.select(ts_col_ms).unique(), on=ts_col_ms, how="anti").sort(ts_col_ms)
    return GridCompletenessResult(
        expected_count=expected.height,
        actual_count=df.height,
        missing_count=missing.height,
        missing_timestamps_ms=tuple(missing[ts_col_ms].to_list()),
    )


# ============================================================================
# check 10 — gaps classificados: manutenção anunciada · falha de coleta ·
# ausência real. Sem uma fonte real de calendário de manutenção da Binance
# carregada, TODA lacuna cai em "unknown" — estado honesto, não uma
# classificação forçada (ver docstring de `classify_gaps`).
# ============================================================================


@dataclass(frozen=True, slots=True)
class GapClassification:
    maintenance: int
    collection: int
    unknown: int


def classify_gaps(
    missing_timestamps_ms: tuple[int, ...],
    *,
    maintenance_windows_ms: tuple[tuple[int, int], ...] = (),
) -> GapClassification:
    """`collection` (falha de coleta) só é atribuível com uma fonte
    independente que prove que o dado existia e não foi capturado — este
    módulo não tem essa fonte, então nunca atribui `collection` sozinho.
    `maintenance` só é atribuído se `maintenance_windows_ms` (calendário real
    de manutenção anunciada) cobrir o timestamp. Sem calendário carregado
    (default, `()`), tudo cai em `unknown` — B23 proíbe inventar a faixa
    esperada; aqui o equivalente é não inventar a fonte da classificação."""
    maintenance = 0
    unknown = 0
    for ts in missing_timestamps_ms:
        if any(lo <= ts <= hi for lo, hi in maintenance_windows_ms):
            maintenance += 1
        else:
            unknown += 1
    return GapClassification(maintenance=maintenance, collection=0, unknown=unknown)


# ============================================================================
# checks 11-14 — coerência OHLC, preços > 0, volume >= 0,
# taker_buy_volume <= volume
# ============================================================================


@dataclass(frozen=True, slots=True)
class OHLCCoherenceResult:
    violation_count: int


def check_ohlc_coherence(df_typed: pl.DataFrame) -> OHLCCoherenceResult:
    """`df_typed` precisa ter `open/high/low/close` já em Float64 —
    ver `_util.cast_price_columns`."""
    bad = df_typed.filter(
        (pl.col("low") > pl.col("open"))
        | (pl.col("open") > pl.col("high"))
        | (pl.col("low") > pl.col("close"))
        | (pl.col("close") > pl.col("high"))
        | (pl.col("low") > pl.col("high"))
    ).height
    return OHLCCoherenceResult(bad)


def check_positive_prices(df_typed: pl.DataFrame, price_cols: tuple[str, ...]) -> int:
    cond = pl.any_horizontal([pl.col(c) <= 0 for c in price_cols])
    return df_typed.filter(cond).height


def check_non_negative_volume(df: pl.DataFrame, volume_col: str = "volume") -> int:
    if volume_col not in df.columns:
        return 0
    return df.filter(pl.col(volume_col) < 0).height


def check_taker_buy_leq_volume(df: pl.DataFrame) -> int:
    if "taker_buy_volume" not in df.columns or "volume" not in df.columns:
        return 0
    return df.filter(pl.col("taker_buy_volume") > pl.col("volume")).height


# ============================================================================
# check 15 — saltos incompatíveis: |log(close_t/close_{t-1})| > 8*sigma,
# marcado para inspeção, NUNCA descartado automaticamente.
# ============================================================================


@dataclass(frozen=True, slots=True)
class OutlierResult:
    sigma_threshold: float
    measured_sigma: float
    flagged_count: int
    flagged_timestamps_ms: tuple[int, ...]


def check_outlier_log_returns(
    df_typed: pl.DataFrame, ts_col_ms: str, close_col: str = "close"
) -> OutlierResult:
    """sigma é medido na própria série (amostra completa passada), não
    assumido — check de qualidade de dado histórico offline, não uma feature
    online, então não há preocupação de vazamento temporal aqui (§2.0
    princípio 4 é sobre normalização de FEATURE, este é diagnóstico
    post-hoc)."""
    sigma_threshold = float(load_constant("outlier_log_return_sigma_threshold"))
    with_ret = df_typed.sort(ts_col_ms).with_columns(
        (pl.col(close_col).log() - pl.col(close_col).shift(1).log()).alias("_logret")
    )
    measured_sigma = float(with_ret.select(pl.col("_logret").std()).item() or 0.0)
    threshold_abs = sigma_threshold * measured_sigma
    flagged = with_ret.filter(pl.col("_logret").abs() > threshold_abs)
    return OutlierResult(
        sigma_threshold=sigma_threshold,
        measured_sigma=measured_sigma,
        flagged_count=flagged.height,
        flagged_timestamps_ms=tuple(flagged[ts_col_ms].to_list()),
    )


# ============================================================================
# checks 17/18 — mark_price / index_price dentro de +-2% do close do
# perpétuo / spot. Mesma primitiva serve para as duas (fontes diferentes,
# mesma forma de comparação); quem chama passa o threshold certo.
# ============================================================================


@dataclass(frozen=True, slots=True)
class DeviationResult:
    max_abs_deviation_pct: float
    mean_abs_deviation_pct: float
    rows_compared: int
    violation_count: int
    threshold_pct: float


def check_price_deviation(
    df_a: pl.DataFrame,
    df_b: pl.DataFrame,
    *,
    ts_col: str,
    price_a: str,
    price_b: str,
    threshold_pct: float,
) -> DeviationResult:
    joined = df_a.select([ts_col, pl.col(price_a).alias("_a")]).join(
        df_b.select([ts_col, pl.col(price_b).alias("_b")]), on=ts_col, how="inner"
    )
    # Guarda de denominador (achado F6) — `_a` é o denominador de `_dev_pct`
    # abaixo; preço <= 0 é dado corrompido (mesmo critério de
    # `check_positive_prices`), nunca um denominador estruturalmente seguro.
    # Filtra ANTES de calcular `_dev_pct`, não depois — uma linha com `_a<=0`
    # nunca chega a entrar em `rows_compared`/`violation_count`.
    joined = joined.filter(pl.col("_a") > 0)
    if joined.is_empty():
        return DeviationResult(0.0, 0.0, 0, 0, threshold_pct)
    # `joined` já filtrado a `_a>0` acima — guarda estrutural via `.filter()`,
    # não `if`/`assert`, por isso fora do heurístico AST de
    # tools/lint/check_unguarded_ratios.py; anotação explícita na linha da
    # divisão abaixo é o que o próprio script pede nesse caso.
    joined = joined.with_columns(
        ((pl.col("_b") - pl.col("_a")) / pl.col("_a") * 100)  # noqa: unguarded-ratio -- `_a`>0
        .abs()
        .alias("_dev_pct")
    )
    max_dev = float(joined.select(pl.col("_dev_pct").max()).item())
    mean_dev = float(joined.select(pl.col("_dev_pct").mean()).item())
    violations = joined.filter(pl.col("_dev_pct") > threshold_pct).height
    return DeviationResult(max_dev, mean_dev, joined.height, violations, threshold_pct)


# ============================================================================
# check 19 — timestamps de funding espaçados consistentemente, intervalo
# DERIVADO do dado (nunca assumir 8h, texto explícito do PRD).
# ============================================================================


@dataclass(frozen=True, slots=True)
class FundingIntervalResult:
    declared_hours_values: tuple[int, ...]
    measured_median_gap_hours: float
    measured_std_gap_hours: float
    inconsistent_rows: int


_MS_PER_HOUR = 3_600_000


def check_funding_interval(df_funding: pl.DataFrame) -> FundingIntervalResult:
    df = df_funding.sort("calc_time")
    declared = tuple(
        sorted(
            df.select(pl.col("funding_interval_hours").unique())["funding_interval_hours"].to_list()
        )
    )
    with_gap = df.with_columns((pl.col("calc_time").diff() / _MS_PER_HOUR).alias("_gap_h"))
    gap_stats = with_gap.select(pl.col("_gap_h").drop_nulls())
    median_gap = float(gap_stats.select(pl.col("_gap_h").median()).item() or 0.0)
    std_gap = float(gap_stats.select(pl.col("_gap_h").std()).item() or 0.0)

    with_measured = with_gap.with_columns(
        pl.col("_gap_h").round(0).cast(pl.Int64).alias("_measured_h")
    )
    inconsistent = with_measured.filter(
        pl.col("_measured_h").is_not_null()
        & (pl.col("_measured_h") != pl.col("funding_interval_hours"))
    ).height
    return FundingIntervalResult(declared, median_gap, std_gap, inconsistent)


# ============================================================================
# checks 21/22 — cobertura por feature / data de início efetiva = máximo das
# datas de início de todas as fontes T1. Implementado no nível de FONTE (D01,
# D03, ...), não de feature individual, porque `features/registry.yaml` ainda
# não existe (Sprint 4+, ver CLAUDE.md "Estado atual"). Mecânica idêntica
# quando o registro de feature existir — só troca a chave do dict.
# ============================================================================


@dataclass(frozen=True, slots=True)
class CoverageResult:
    coverage_by_source: dict[str, str]
    effective_start: str


def _stem_to_iso_date(stem: str) -> str:
    parts = stem.split("-")
    if len(parts) == 3:
        return f"{stem}T00:00:00Z"
    if len(parts) == 2:
        return f"{stem}-01T00:00:00Z"
    raise ValueError(f"nome de arquivo inesperado (não é yyyy-mm-dd nem yyyy-mm): {stem!r}")


def compute_coverage(source_dirs: dict[str, Path]) -> CoverageResult:
    coverage: dict[str, str] = {}
    for source_id, directory in source_dirs.items():
        files = sorted(directory.glob("*.parquet"))
        if not files:
            continue
        coverage[source_id] = _stem_to_iso_date(files[0].stem)
    effective_start = max(coverage.values()) if coverage else ""
    return CoverageResult(coverage, effective_start)


# ============================================================================
# check 23 — quebra semântica de fonte (config/venue_changelog.yaml). Aplica
# só a datasets que carregam FEATURES derivadas de um endpoint contaminado;
# OHLCV bruto (klines/mark/premium/agg_trades/metrics/funding) não é
# afetado pela quebra de 2025-11-20 (RPI), que é sobre bookTicker/bookDepth.
# ============================================================================


@dataclass(frozen=True, slots=True)
class VenueBreakResult:
    applicable: bool
    unresolved_breaks: tuple[str, ...]
    reason_not_applicable: str | None


def check_venue_semantic_breaks(
    feature_ids: tuple[str, ...],
    changelog_events: list[dict[str, object]],
    *,
    series_start_iso: str,
    series_end_iso: str,
) -> VenueBreakResult:
    if not feature_ids:
        return VenueBreakResult(
            applicable=False,
            unresolved_breaks=(),
            reason_not_applicable=(
                "nenhuma feature no escopo deste dataset — check 23 valida contaminação de "
                "FEATURE derivada, não OHLCV/evento bruto"
            ),
        )
    unresolved: list[str] = []
    for event in changelog_events:
        event_date_iso = f"{event['date']}T00:00:00Z"
        contaminated_raw = event.get("features_contaminadas", ())
        if isinstance(contaminated_raw, (list, tuple, set)):
            contaminated = set(contaminated_raw)
        else:
            contaminated = set()
        crosses = series_start_iso < event_date_iso < series_end_iso
        has_treatment = bool(event.get("tratamento"))
        if crosses and (contaminated & set(feature_ids)) and not has_treatment:
            unresolved.append(str(event["event"]))
    return VenueBreakResult(
        applicable=True, unresolved_breaks=tuple(unresolved), reason_not_applicable=None
    )
