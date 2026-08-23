"""Data Quality Engine — §1.3 RF-003.

Orquestra as primitivas de `checks.py` por formato de dataset (klines-like,
agg_trades, metrics, funding, bars resampled, dollar bars) e produz
`quality_report_{dataset}_{symbol}_{version}.json` (achado F4 — nome default
inclui `symbol` desde que `QualityReport` ganhou esse campo; os 5 relatórios
gravados antes disso, sem `symbol` no nome, não foram migrados, decisão
separada do Manager) no formato do §1.3, salvo em `data/quality_reports/`
via escrita atômica (`.tmp` -> `fsync` -> `rename`, B29).

Duas decisões de design que não estavam 100% especificadas no PRD e que
precisaram ser resolvidas para este módulo existir — documentadas aqui, não
escondidas:

1. **`cross_source_max_deviation` é especificamente o resultado do check 16**
   (bars_30m reagregado vs. kline nativo), expresso como desvio absoluto de
   preço, comparado contra uma tolerância de `1e-8` — não é um campo
   genérico "qualquer desvio entre fontes". O check 17 (mark price, desvio
   em %, tolerância 2%) e o check 19 (funding, consistência de intervalo)
   têm resultado próprio em `diagnostics`, com gate próprio — não
   sobrescrevem este campo, que ficaria com unidades incompatíveis
   (fração ~1e-9 vs. percentual ~0.1) se misturados.

2. **O invariante `assert dataset_start >= report["effective_start"]`** do
   bloco INVARIANTES do §1.3 não é um gate do PRÓPRIO relatório — é uma
   asserção que o CONSUMIDOR do relatório faz ao decidir a partir de qual
   data cortar um dataset de treino. Ler literalmente como gate do relatório
   quebra no primeiro exemplo do próprio PRD (`start: "2020-09-01"` <
   `effective_start: "2022-01-01"` no JSON de exemplo do §1.3). Este módulo
   expõe `assert_ready_for_training(report, dataset_start)` para o
   consumidor chamar explicitamente, em vez de dobrar essa checagem dentro
   do `gate` do relatório.
"""

from __future__ import annotations

import argparse
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import orjson
import polars as pl
import structlog

from . import checks, schemas
from ._constants import load_constant
from ._paths import CAPACITY_DIR, QUALITY_REPORTS_DIR, VENUE_CHANGELOG_PATH
from ._util import cast_price_columns, metrics_timestamp_to_ms, ms_to_iso

logger = structlog.get_logger(__name__)

_REPORT_VERSION = "v1"
_MAX_MISSING_TIMESTAMPS_LISTED = 500  # ver nota em QualityReport.missing_timestamps
_EMPTY_DF_REASON = "DataFrame de entrada vazio (0 linhas ou 0 colunas)"


# ============================================================================
# Report
# ============================================================================


@dataclass(slots=True)
class QualityReport:
    """Espelha o JSON do §1.3. `missing_timestamps` lista até
    `_MAX_MISSING_TIMESTAMPS_LISTED` timestamps ISO (requisito "não
    silenciosa" do check 9) — `missing_bars` sempre tem a contagem
    completa, então truncar a lista não esconde o tamanho real do
    problema, só evita um JSON de dezenas de MB quando há uma lacuna
    estrutural grande (ex.: fonte inteira ausente por meses)."""

    dataset: str
    # Achado F4/AG-125 — sem `symbol` no relatório, `data/quality_reports/
    # quality_report_agg_trades_v1.json` foi citado como se fosse BTCUSDT
    # sem o arquivo declarar isso — estimativa, não medição (ver nota em
    # `src.data.bars`, achado de auditoria externa 2026-08-15). Migração
    # retroativa dos 5 relatórios antigos DECIDIDA pelo Manager 2026-08-21
    # (Tabela 1, item 3: "A — migrar") e EXECUTADA (`symbol` gravado,
    # arquivos renomeados pra `quality_report_{dataset}_BTCUSDT_{version}.json`).
    symbol: str
    version: str
    rows: int
    start: str | None
    end: str | None
    missing_bars: int
    missing_timestamps: list[str]
    gap_classification: dict[str, int]
    duplicates: int
    invalid_rows: int
    outliers_flagged: int
    cross_source_max_deviation: float | None
    coverage_by_feature: dict[str, str]
    effective_start: str | None
    quality_score: float
    gate: str
    # extensões além do JSON literal do §1.3 — auditabilidade do porquê do
    # gate, e o que foi pulado e por quê (instrução explícita do Sprint 2:
    # "pule com uma nota clara no relatório, não force").
    checks_skipped: list[dict[str, str]] = field(default_factory=list)
    failed_checks: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def assert_ready_for_training(report: QualityReport, dataset_start_iso: str) -> None:
    """Invariante do bloco INVARIANTES do §1.3, aplicada pelo CONSUMIDOR do
    relatório (ver nota 2 no docstring do módulo) — não pelo `gate` do
    relatório em si."""
    assert report.gate == "PASS", f"quality_report {report.dataset} não está em PASS"
    assert report.duplicates == 0, (
        f"quality_report {report.dataset} tem {report.duplicates} duplicata(s)"
    )
    if report.cross_source_max_deviation is not None:
        tolerance = float(load_constant("resample_cross_source_parity_tolerance"))
        assert report.cross_source_max_deviation < tolerance
    if report.effective_start is not None:
        assert dataset_start_iso >= report.effective_start, (
            f"dataset_start {dataset_start_iso} é anterior ao effective_start "
            f"{report.effective_start} — cortar o dataset de treino a partir de effective_start"
        )


def _quality_score(*, rows: int, missing_bars: int, duplicates: int, invalid_rows: int) -> float:
    """Descritivo, não gating (ver nota 2 do docstring do módulo — evita
    inventar um limiar de corte não especificado pelo PRD, B23). Universo
    esperado = observado + ausente; score = fração sem defeito."""
    denom = rows + missing_bars
    if denom <= 0:
        return 0.0
    bad = missing_bars + duplicates + invalid_rows
    return max(0.0, min(1.0, 1.0 - bad / denom))


def _empty_report(dataset_name: str, *, reason: str, symbol: str = "BTCUSDT") -> QualityReport:
    """`lake.query_*` retorna um `pl.DataFrame()` sem colunas quando nenhum
    arquivo intersecta o intervalo pedido (ex.: range fora da cobertura real
    da fonte — `agg_trades` só vai até 2026-07-31, ver `known_gaps`). Um
    DataFrame sem colunas quebraria toda primitiva de `checks.py` que
    referencia uma coluna por nome; este relatório "vazio" é o retorno
    honesto para esse caso, não um crash nem um PASS fabricado."""
    return QualityReport(
        dataset=dataset_name,
        symbol=symbol,
        version=_REPORT_VERSION,
        rows=0,
        start=None,
        end=None,
        missing_bars=0,
        missing_timestamps=[],
        gap_classification={"maintenance": 0, "collection": 0, "unknown": 0},
        duplicates=0,
        invalid_rows=0,
        outliers_flagged=0,
        cross_source_max_deviation=None,
        coverage_by_feature={},
        effective_start=None,
        quality_score=0.0,
        gate="FAIL",
        checks_skipped=[{"check": "all", "reason": reason}],
        failed_checks=["0_no_data"],
        diagnostics={},
    )


#: Campos comparados pra decidir se um relatório pré-existente é
#: "materialmente diferente" do novo (achado F4) — não é a comparação
#: campo-a-campo do dict inteiro: `diagnostics`/`checks_skipped`/`start`/`end`
#: mudam de forma esperada a cada corrida (janela diferente, nota redigida
#: diferente) e gerariam ruído, não sinal. Estes 5 são os que importam pra
#: decidir "algo relevante mudou desde a última vez que este relatório foi
#: escrito" — `gate` é o sinal primário (ex. PASS -> FAIL, o exemplo citado
#: no achado), os outros 4 são as contagens que o sustentam.
_MATERIAL_REPORT_FIELDS: tuple[str, ...] = (
    "gate",
    "rows",
    "duplicates",
    "invalid_rows",
    "missing_bars",
)


def _material_report_diff(existing: dict[str, Any], new: dict[str, Any]) -> list[str]:
    return [f for f in _MATERIAL_REPORT_FIELDS if existing.get(f) != new.get(f)]


def write_report_atomic(report: QualityReport, dest_path: Path | None = None) -> Path:
    """B29 — `.tmp` -> `fsync` -> `rename`. Nome default inclui `symbol`
    (achado F4/AG-125) — os 5 relatórios antigos migrados retroativamente
    2026-08-21 (Tabela 1, item 3: "A — migrar"), `symbol=BTCUSDT` gravado,
    `data/quality_reports/*.json` sem `symbol` no nome não existe mais.

    **Guarda de sobrescrita não-intencional** (mesmo espírito de
    `build_dollar_bars.write_dollar_bars_and_calibration`, que levanta
    `ValueError` se o threshold já gravado diverge — aqui o comportamento é
    mais brando de propósito: um quality_report pode legitimamente mudar de
    PASS pra FAIL entre corridas, ex. novo dado ruim chegou; isso não deveria
    BLOQUEAR a escrita do relatório novo, só tornar a mudança VISÍVEL. Se um
    relatório já existir pro mesmo `(dataset, symbol, version)` com
    `_MATERIAL_REPORT_FIELDS` divergente do que está sendo escrito agora,
    loga um warning claro (campos que mudaram, gate anterior vs novo) antes
    de sobrescrever — nunca silencioso, mas também nunca levanta."""
    if dest_path is None:
        dest_path = (
            QUALITY_REPORTS_DIR
            / f"quality_report_{report.dataset}_{report.symbol}_{report.version}.json"
        )
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    new_payload = report.to_dict()
    if dest_path.exists():
        try:
            existing_payload: dict[str, Any] = orjson.loads(dest_path.read_bytes())
        except orjson.JSONDecodeError:
            existing_payload = {}
        diff_fields = _material_report_diff(existing_payload, new_payload)
        if diff_fields:
            logger.warning(
                "validate.report_overwrite_material_change",
                dataset=report.dataset,
                symbol=report.symbol,
                version=report.version,
                path=str(dest_path),
                changed_fields=diff_fields,
                previous_gate=existing_payload.get("gate"),
                new_gate=report.gate,
            )

    tmp_path = dest_path.with_name(dest_path.name + ".tmp")
    payload = orjson.dumps(new_payload, option=orjson.OPT_INDENT_2)
    with tmp_path.open("wb") as fh:
        fh.write(payload)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, dest_path)
    logger.info(
        "validate.report_written",
        dataset=report.dataset,
        symbol=report.symbol,
        path=str(dest_path),
    )
    return dest_path


# ============================================================================
# T1 source dirs — usados por checks 21/22 (cobertura). Só entram as fontes
# já baixadas localmente (ver CLAUDE.md "contexto já existente").
# ============================================================================


def _default_t1_source_dirs(symbol: str = "BTCUSDT") -> dict[str, Path]:
    candidates = {
        "D01_agg_trades": CAPACITY_DIR / "agg_trades" / symbol,
        "D03_klines_1m": CAPACITY_DIR / "klines_1m" / symbol,
        "D04_metrics": CAPACITY_DIR / "metrics" / symbol,
        "D07_funding": CAPACITY_DIR / "funding" / symbol,
        "D10_mark_price_klines_1m": CAPACITY_DIR / "mark_price_klines_1m" / symbol,
        "D11_premium_index_klines_1m": CAPACITY_DIR / "premium_index_klines_1m" / symbol,
    }
    return {k: v for k, v in candidates.items() if v.is_dir()}


def _load_venue_changelog_events() -> list[dict[str, object]]:
    import yaml

    if not VENUE_CHANGELOG_PATH.exists():
        return []
    with VENUE_CHANGELOG_PATH.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    events: list[dict[str, object]] = data.get("events", [])
    return events


# ============================================================================
# klines-like (klines_1m, mark_price_klines_1m, premium_index_klines_1m)
# ============================================================================


def validate_klines_like(
    df: pl.DataFrame,
    *,
    dataset_name: str,
    mark_df: pl.DataFrame | None = None,
    compute_coverage: bool = True,
    symbol: str = "BTCUSDT",
) -> QualityReport:
    schema = schemas.get_schema(dataset_name)
    assert schema.is_klines_like, f"{dataset_name} não é klines-like"
    assert schema.grid_step_ms is not None

    if df.is_empty():
        return _empty_report(dataset_name, reason=_EMPTY_DF_REASON, symbol=symbol)

    checks_skipped: list[dict[str, str]] = [
        {
            "check": "2_checksum",
            "reason": (
                "src/data/download.py JÁ existe e já verifica checksum por download "
                "(_verify_checksum) e grava checksum_verified no manifest "
                "data/capacity/_download_log/multi_asset_backfill.jsonl (achado F7) — "
                "o que falta aqui é só o WIRE-UP: este check ainda não lê esse "
                "manifest nem cruza checksum_verified contra o dataset sendo "
                "validado. TODO: implementar a leitura/cruzamento, não a "
                "verificação de checksum em si (já existe)."
            ),
        },
        {
            "check": "16_cross_source_30m_parity",
            "reason": (
                f"aplica-se a um dataset RESAMPLED (ex.: bars_30m), não à fonte bruta "
                f"{dataset_name}. Ver validate_resampled_bars()."
            ),
        },
        {
            "check": "18_index_price_deviation",
            "reason": (
                "D12 index_price_1m ainda não baixado — sem fonte para comparar "
                "(known_gaps, constants.yaml)."
            ),
        },
        {
            "check": "23_venue_semantic_break",
            "reason": (
                f"{dataset_name} é OHLCV bruto; check 23 valida contaminação de FEATURE "
                "derivada de bookTicker/bookDepth (Grupo F) — não se aplica a este dataset."
            ),
        },
    ]
    failed: list[str] = []
    diagnostics: dict[str, Any] = {}

    df_typed = cast_price_columns(df, ("open", "high", "low", "close"))

    schema_result = checks.check_schema(df, schema)
    diagnostics["1_schema"] = asdict(schema_result)
    if not schema_result.passed:
        failed.append("1_schema")

    dup_result = checks.check_duplicates(df, schema.primary_key)
    diagnostics["3_duplicates"] = asdict(dup_result)
    if dup_result.excess_rows:
        failed.append("3_duplicates")

    null_result = checks.check_nulls(df, schema.non_nullable)
    diagnostics["4_nulls"] = null_result.counts
    if null_result.total:
        failed.append("4_nulls")

    mono_result = checks.check_monotonic(df, schema.timestamp_column)
    diagnostics["5_8_monotonic"] = asdict(mono_result)
    if not mono_result.is_strictly_monotonic:
        failed.append("5_8_monotonic")

    diagnostics["6_utc"] = (
        "timestamp em epoch ms (Int64) — sem ambiguidade de fuso por construção, "
        "não há string de data/hora a interpretar."
    )

    close_time_result = checks.check_close_time_convention(df, schema.grid_step_ms)
    diagnostics["7_close_time_convention"] = asdict(close_time_result)
    if not close_time_result.passed:
        failed.append("7_close_time_convention")

    grid_result = checks.check_grid_completeness(df, schema.timestamp_column, schema.grid_step_ms)
    diagnostics["9_grid_completeness"] = {
        "expected_count": grid_result.expected_count,
        "actual_count": grid_result.actual_count,
        "missing_count": grid_result.missing_count,
    }

    gap_result = checks.classify_gaps(grid_result.missing_timestamps_ms)
    diagnostics["10_gap_classification_note"] = (
        "sem calendário de manutenção anunciada carregado — toda lacuna cai em 'unknown' "
        "(ver checks.classify_gaps); não é uma classificação otimista, é o estado real."
    )

    ohlc_result = checks.check_ohlc_coherence(df_typed)
    diagnostics["11_ohlc_coherence"] = asdict(ohlc_result)
    price_violations = checks.check_positive_prices(df_typed, ("open", "high", "low", "close"))
    diagnostics["12_positive_prices"] = {"violation_count": price_violations}
    vol_violations = checks.check_non_negative_volume(df)
    diagnostics["13_non_negative_volume"] = {"violation_count": vol_violations}
    taker_violations = checks.check_taker_buy_leq_volume(df)
    diagnostics["14_taker_buy_leq_volume"] = {"violation_count": taker_violations}

    invalid_rows = (
        ohlc_result.violation_count + price_violations + vol_violations + taker_violations
    )
    # nota: uma mesma linha pode violar 2+ regras simultaneamente e ser contada mais de
    # uma vez aqui — o detalhamento por regra em diagnostics não tem esse problema.
    if invalid_rows:
        failed.append("11_14_value_checks")

    outlier_result = checks.check_outlier_log_returns(df_typed, schema.timestamp_column)
    diagnostics["15_outliers"] = {
        "sigma_threshold": outlier_result.sigma_threshold,
        "measured_sigma": outlier_result.measured_sigma,
        "flagged_count": outlier_result.flagged_count,
    }
    # check 15 é explicitamente "marca, não descarta" — nunca entra em failed_checks/invalid_rows.

    if mark_df is not None:
        mark_typed = cast_price_columns(mark_df, ("close",))
        threshold = float(load_constant("mark_price_deviation_max_pct"))
        dev = checks.check_price_deviation(
            df_typed,
            mark_typed,
            ts_col=schema.timestamp_column,
            price_a="close",
            price_b="close",
            threshold_pct=threshold,
        )
        diagnostics["17_mark_price_deviation_pct"] = asdict(dev)
        if dev.violation_count:
            failed.append("17_mark_price_deviation")
    else:
        checks_skipped.append(
            {"check": "17_mark_price_deviation", "reason": "mark_df não fornecido nesta chamada"}
        )

    coverage = checks.CoverageResult({}, "")
    if compute_coverage:
        coverage = checks.compute_coverage(_default_t1_source_dirs(symbol))

    rows = df.height
    start_ms = int(df[schema.timestamp_column].min()) if rows else None  # type: ignore[arg-type]
    end_ms = int(df[schema.timestamp_column].max()) if rows else None  # type: ignore[arg-type]

    quality_score = _quality_score(
        rows=rows,
        missing_bars=grid_result.missing_count,
        duplicates=dup_result.excess_rows,
        invalid_rows=invalid_rows,
    )
    gate = "PASS" if not failed else "FAIL"

    missing_ts = grid_result.missing_timestamps_ms[:_MAX_MISSING_TIMESTAMPS_LISTED]
    return QualityReport(
        dataset=dataset_name,
        symbol=symbol,
        version=_REPORT_VERSION,
        rows=rows,
        start=ms_to_iso(start_ms) if start_ms is not None else None,
        end=ms_to_iso(end_ms) if end_ms is not None else None,
        missing_bars=grid_result.missing_count,
        missing_timestamps=[ms_to_iso(t) for t in missing_ts],
        gap_classification={
            "maintenance": gap_result.maintenance,
            "collection": gap_result.collection,
            "unknown": gap_result.unknown,
        },
        duplicates=dup_result.excess_rows,
        invalid_rows=invalid_rows,
        outliers_flagged=outlier_result.flagged_count,
        cross_source_max_deviation=None,  # check 16 não é da fonte bruta (ver checks_skipped)
        coverage_by_feature=coverage.coverage_by_source,
        effective_start=coverage.effective_start or None,
        quality_score=quality_score,
        gate=gate,
        checks_skipped=checks_skipped,
        failed_checks=failed,
        diagnostics=diagnostics,
    )


# ============================================================================
# bars resampled (ex.: bars_30m) — check 16
# ============================================================================


def validate_resampled_bars(
    df_resampled: pl.DataFrame,
    *,
    timeframe: str,
    symbol: str = "BTCUSDT",
) -> QualityReport:
    from . import resample

    dataset_name = f"bars_{timeframe}"
    if df_resampled.is_empty():
        return _empty_report(dataset_name, reason=_EMPTY_DF_REASON, symbol=symbol)
    checks_skipped: list[dict[str, str]] = []
    failed: list[str] = []
    diagnostics: dict[str, Any] = {}

    native_dir = resample.find_native_klines(symbol, timeframe)
    cross_source_max_deviation: float | None = None
    if native_dir is None:
        checks_skipped.append(
            {
                "check": "16_cross_source_30m_parity",
                "reason": (
                    f"nenhum kline nativo de '{timeframe}' encontrado em data/capacity/ nem "
                    "data/raw/ (medido, não assumido — ver resample.find_native_klines). "
                    "Comparação PENDING até existir um D0x nativo desse timeframe baixado."
                ),
            }
        )
        diagnostics["16_parity"] = {"compared": False, "reason": "sem dataset nativo no disco"}
    else:
        parity = resample.compare_resample_to_native(df_resampled, native_dir)
        diagnostics["16_parity"] = asdict(parity)
        if parity.compared:
            cross_source_max_deviation = parity.max_abs_deviation
            if not parity.passed:
                failed.append("16_cross_source_parity")

    rows = df_resampled.height
    start_ms = int(df_resampled["open_time"].min()) if rows else None  # type: ignore[arg-type]
    end_ms = int(df_resampled["open_time"].max()) if rows else None  # type: ignore[arg-type]

    quality_score = _quality_score(rows=rows, missing_bars=0, duplicates=0, invalid_rows=0)
    gate = "PASS" if not failed else "FAIL"

    return QualityReport(
        dataset=dataset_name,
        symbol=symbol,
        version=_REPORT_VERSION,
        rows=rows,
        start=ms_to_iso(start_ms) if start_ms is not None else None,
        end=ms_to_iso(end_ms) if end_ms is not None else None,
        missing_bars=0,
        missing_timestamps=[],
        gap_classification={"maintenance": 0, "collection": 0, "unknown": 0},
        duplicates=0,
        invalid_rows=0,
        outliers_flagged=0,
        cross_source_max_deviation=cross_source_max_deviation,
        coverage_by_feature={},
        effective_start=None,
        quality_score=quality_score,
        gate=gate,
        checks_skipped=checks_skipped,
        failed_checks=failed,
        diagnostics=diagnostics,
    )


# ============================================================================
# dollar bars (dollar_bars_r1/r2/r3, AG-042) — achado F3. Barra event-driven
# (fecha quando o threshold de $ é atingido, não por relógio): `grid_step_ms`
# é `None` no schema (`schemas._dollar_bars_schema`), mesmo motivo de
# `AGG_TRADES` — check 9 (`check_grid_completeness`) pressupõe uma grade
# temporal fixa a priori e não se aplica aqui (ver docstring de
# `checks.check_grid_completeness`/`checks.GridCompletenessResult`: mede
# timestamps ausentes contra uma grade `arange(lo, hi, step_ms)`, que não
# existe pra uma barra calibrada por volume). Check 7 (close_time_convention)
# tem o mesmo problema — pressupõe `close_time == open_time + step_ms - 1`
# com `step_ms` CONSTANTE, e a duração de uma dollar bar é variável por
# construção. `open`/`high`/`low`/`close` já chegam `Float64` no schema
# (`schemas._DOLLAR_BARS_COLUMNS`, diferente de klines_1m que é `Utf8`) —
# sem necessidade de `cast_price_columns` aqui.
# ============================================================================


def validate_dollar_bars(
    df: pl.DataFrame,
    *,
    resolution_id: str,
    symbol: str = "BTCUSDT",
) -> QualityReport:
    dataset_name = f"dollar_bars_{resolution_id.lower()}"
    schema = schemas.get_schema(dataset_name)

    if df.is_empty():
        return _empty_report(dataset_name, reason=_EMPTY_DF_REASON, symbol=symbol)

    checks_skipped: list[dict[str, str]] = [
        {
            "check": "2_checksum",
            "reason": "ver nota em validate_klines_like",
        },
        {
            "check": "7_close_time_convention",
            "reason": (
                "pressupõe close_time == open_time + step_ms - 1 com step_ms "
                "CONSTANTE — dollar bar tem duração VARIÁVEL por construção "
                "(fecha ao atingir o threshold de $, não por relógio); sem step_ms "
                "fixo não há convenção a verificar (grid_step_ms=None no schema)."
            ),
        },
        {
            "check": "9_grid_completeness",
            "reason": (
                "barra event-driven — não existe grade fixa a priori "
                f"(grid_step_ms=None em schemas.{dataset_name.upper()})"
            ),
        },
        {
            "check": "16_cross_source_30m_parity",
            "reason": (
                "aplica-se a bars RESAMPLED por relógio (ex.: bars_30m), não a "
                "dollar bar calibrada por threshold de $. Ver validate_resampled_bars()."
            ),
        },
        {
            "check": "17_mark_price_deviation",
            "reason": "sem mark_df nesta função — dollar bar não compara contra mark price aqui",
        },
        {
            "check": "18_index_price_deviation",
            "reason": "D12 index_price_1m ainda não baixado — sem fonte para comparar",
        },
        {
            "check": "23_venue_semantic_break",
            "reason": (
                f"{dataset_name} é OHLCV agregado de aggTrades (D01), não FEATURE "
                "derivada de bookTicker/bookDepth (Grupo F) — não se aplica."
            ),
        },
    ]
    failed: list[str] = []
    diagnostics: dict[str, Any] = {}

    schema_result = checks.check_schema(df, schema)
    diagnostics["1_schema"] = asdict(schema_result)
    if not schema_result.passed:
        failed.append("1_schema")

    dup_result = checks.check_duplicates(df, schema.primary_key)
    diagnostics["3_duplicates"] = asdict(dup_result)
    if dup_result.excess_rows:
        failed.append("3_duplicates")

    null_result = checks.check_nulls(df, schema.non_nullable)
    diagnostics["4_nulls"] = null_result.counts
    if null_result.total:
        failed.append("4_nulls")

    mono_result = checks.check_monotonic(df, schema.timestamp_column)
    diagnostics["5_8_monotonic"] = asdict(mono_result)
    if not mono_result.is_strictly_monotonic:
        failed.append("5_8_monotonic")

    diagnostics["6_utc"] = (
        "timestamp em epoch ms (Int64) — sem ambiguidade de fuso por construção, "
        "não há string de data/hora a interpretar."
    )

    ohlc_result = checks.check_ohlc_coherence(df)
    diagnostics["11_ohlc_coherence"] = asdict(ohlc_result)
    price_violations = checks.check_positive_prices(df, ("open", "high", "low", "close"))
    diagnostics["12_positive_prices"] = {"violation_count": price_violations}
    vol_violations = checks.check_non_negative_volume(df)
    diagnostics["13_non_negative_volume"] = {"violation_count": vol_violations}
    taker_violations = checks.check_taker_buy_leq_volume(df)
    diagnostics["14_taker_buy_leq_volume"] = {"violation_count": taker_violations}

    invalid_rows = (
        ohlc_result.violation_count + price_violations + vol_violations + taker_violations
    )
    # nota: uma mesma linha pode violar 2+ regras simultaneamente e ser contada mais de
    # uma vez aqui — o detalhamento por regra em diagnostics não tem esse problema.
    if invalid_rows:
        failed.append("11_14_value_checks")

    outlier_result = checks.check_outlier_log_returns(df, schema.timestamp_column)
    diagnostics["15_outliers"] = {
        "sigma_threshold": outlier_result.sigma_threshold,
        "measured_sigma": outlier_result.measured_sigma,
        "flagged_count": outlier_result.flagged_count,
    }
    # check 15 é explicitamente "marca, não descarta" — nunca entra em failed_checks/invalid_rows.

    rows = df.height
    start_ms = int(df[schema.timestamp_column].min()) if rows else None  # type: ignore[arg-type]
    end_ms = int(df[schema.timestamp_column].max()) if rows else None  # type: ignore[arg-type]

    quality_score = _quality_score(
        rows=rows,
        missing_bars=0,  # sem grade fixa — "ausente" não é um conceito aplicável aqui
        duplicates=dup_result.excess_rows,
        invalid_rows=invalid_rows,
    )
    gate = "PASS" if not failed else "FAIL"

    return QualityReport(
        dataset=dataset_name,
        symbol=symbol,
        version=_REPORT_VERSION,
        rows=rows,
        start=ms_to_iso(start_ms) if start_ms is not None else None,
        end=ms_to_iso(end_ms) if end_ms is not None else None,
        missing_bars=0,
        missing_timestamps=[],
        gap_classification={"maintenance": 0, "collection": 0, "unknown": 0},
        duplicates=dup_result.excess_rows,
        invalid_rows=invalid_rows,
        outliers_flagged=outlier_result.flagged_count,
        cross_source_max_deviation=None,
        coverage_by_feature={},
        effective_start=None,
        quality_score=quality_score,
        gate=gate,
        checks_skipped=checks_skipped,
        failed_checks=failed,
        diagnostics=diagnostics,
    )


# ============================================================================
# agg_trades
# ============================================================================


def validate_agg_trades(df: pl.DataFrame, *, symbol: str = "BTCUSDT") -> QualityReport:
    schema = schemas.get_schema("agg_trades")
    if df.is_empty():
        return _empty_report("agg_trades", reason=_EMPTY_DF_REASON, symbol=symbol)
    checks_skipped = [
        {"check": "2_checksum", "reason": "ver nota em validate_klines_like"},
        {
            "check": "5_8_monotonic",
            "reason": (
                "agg_trade_id é crescente por definição da API; transact_time NÃO é "
                "estritamente monotônico entre trades simultâneos no mesmo ms — checado "
                "por agg_trade_id, não por timestamp"
            ),
        },
        {
            "check": "7_close_time_convention",
            "reason": "trades não têm close_time — evento pontual, não barra",
        },
        {
            "check": "9_grid_completeness",
            "reason": (
                "trades são event-driven — não existe grade fixa a priori "
                "(grid_step_ms=None em schemas.AGG_TRADES)"
            ),
        },
        {"check": "11_ohlc_coherence", "reason": "sem OHLC em agg_trades — é preço de trade único"},
        {
            "check": "15_outlier_returns",
            "reason": (
                "outlier de retorno é definido sobre close de barra, não sobre trade "
                "individual — aplicar em klines, não aqui"
            ),
        },
        {"check": "16_18_19_cross_source", "reason": "não aplicável a agg_trades"},
        {
            "check": "23_venue_semantic_break",
            "reason": "agg_trades não deriva de bookTicker/bookDepth",
        },
    ]
    failed: list[str] = []
    diagnostics: dict[str, Any] = {}

    schema_result = checks.check_schema(df, schema)
    diagnostics["1_schema"] = asdict(schema_result)
    if not schema_result.passed:
        failed.append("1_schema")

    dup_result = checks.check_duplicates(df, schema.primary_key)
    diagnostics["3_duplicates"] = asdict(dup_result)
    if dup_result.excess_rows:
        failed.append("3_duplicates")

    null_result = checks.check_nulls(df, schema.non_nullable)
    diagnostics["4_nulls"] = null_result.counts
    if null_result.total:
        failed.append("4_nulls")

    mono_by_id = checks.check_monotonic(df.sort("agg_trade_id"), "agg_trade_id")
    diagnostics["5_8_monotonic_by_agg_trade_id"] = asdict(mono_by_id)
    if not mono_by_id.is_strictly_monotonic:
        failed.append("5_8_monotonic_by_agg_trade_id")

    price_violations = checks.check_positive_prices(df, ("price",))
    diagnostics["12_positive_prices"] = {"violation_count": price_violations}
    qty_violations = df.filter(pl.col("quantity") < 0).height
    diagnostics["13_non_negative_quantity"] = {"violation_count": qty_violations}
    invalid_rows = price_violations + qty_violations
    if invalid_rows:
        failed.append("12_13_value_checks")

    rows = df.height
    start_ms = int(df["transact_time"].min()) if rows else None  # type: ignore[arg-type]
    end_ms = int(df["transact_time"].max()) if rows else None  # type: ignore[arg-type]

    quality_score = _quality_score(
        rows=rows, missing_bars=0, duplicates=dup_result.excess_rows, invalid_rows=invalid_rows
    )
    gate = "PASS" if not failed else "FAIL"

    return QualityReport(
        dataset="agg_trades",
        symbol=symbol,
        version=_REPORT_VERSION,
        rows=rows,
        start=ms_to_iso(start_ms) if start_ms is not None else None,
        end=ms_to_iso(end_ms) if end_ms is not None else None,
        missing_bars=0,
        missing_timestamps=[],
        gap_classification={"maintenance": 0, "collection": 0, "unknown": 0},
        duplicates=dup_result.excess_rows,
        invalid_rows=invalid_rows,
        outliers_flagged=0,
        cross_source_max_deviation=None,
        coverage_by_feature={},
        effective_start=None,
        quality_score=quality_score,
        gate=gate,
        checks_skipped=checks_skipped,
        failed_checks=failed,
        diagnostics=diagnostics,
    )


# ============================================================================
# metrics — check 20 (grade de 5m alinha em 30m sem interpolação para
# frente) implementado reusando check_grid_completeness a step=30min sobre a
# própria série de metrics: cada marca de 30m precisa ter um ponto NATIVO de
# metrics exatamente nela, senão o consumidor precisaria de forward-fill.
# ============================================================================

_THIRTY_MIN_MS = 1_800_000


def validate_metrics(df: pl.DataFrame, *, symbol: str = "BTCUSDT") -> QualityReport:
    schema = schemas.get_schema("metrics")
    if df.is_empty():
        return _empty_report("metrics", reason=_EMPTY_DF_REASON, symbol=symbol)
    checks_skipped = [
        {"check": "2_checksum", "reason": "ver nota em validate_klines_like"},
        {
            "check": "7_close_time_convention",
            "reason": "metrics não tem close_time — é ponto instantâneo, não barra OHLCV",
        },
        {"check": "11_ohlc_coherence", "reason": "sem OHLC em metrics"},
        {"check": "12_positive_prices", "reason": "sem coluna de preço em metrics"},
        {"check": "13_14_volume_checks", "reason": "sem volume em metrics"},
        {
            "check": "15_outlier_returns",
            "reason": "sem close de barra em metrics para calcular log-retorno",
        },
        {"check": "16_18_cross_source", "reason": "não aplicável a metrics"},
        {
            "check": "23_venue_semantic_break",
            "reason": (
                "metrics (D04, openInterest/long-short ratios) não deriva de bookTicker/bookDepth"
            ),
        },
    ]
    failed: list[str] = []
    diagnostics: dict[str, Any] = {}

    df_ts = metrics_timestamp_to_ms(df, create_time_col="create_time")

    schema_result = checks.check_schema(df, schema)
    diagnostics["1_schema"] = asdict(schema_result)
    if not schema_result.passed:
        failed.append("1_schema")

    dup_result = checks.check_duplicates(df, schema.primary_key)
    diagnostics["3_duplicates"] = asdict(dup_result)
    if dup_result.excess_rows:
        failed.append("3_duplicates")

    null_result = checks.check_nulls(df, schema.non_nullable)
    diagnostics["4_nulls"] = null_result.counts
    if null_result.total:
        failed.append("4_nulls")

    mono_result = checks.check_monotonic(df_ts, "_ts_ms")
    diagnostics["5_8_monotonic"] = asdict(mono_result)
    if not mono_result.is_strictly_monotonic:
        failed.append("5_8_monotonic")

    diagnostics["6_utc"] = (
        "create_time é string 'YYYY-MM-DD HH:MM:SS' sem marcador de fuso — documentação da "
        "Binance declara UTC; não verificável a partir da string isolada (limitação registrada, "
        "não contornada)."
    )

    grid_5m = checks.check_grid_completeness(df_ts, "_ts_ms", schema.grid_step_ms or 300_000)
    diagnostics["9_grid_completeness_5m"] = {
        "expected_count": grid_5m.expected_count,
        "actual_count": grid_5m.actual_count,
        "missing_count": grid_5m.missing_count,
    }

    grid_30m = checks.check_grid_completeness(df_ts, "_ts_ms", _THIRTY_MIN_MS)
    diagnostics["20_alignment_30m_no_forward_fill"] = {
        "expected_marks": grid_30m.expected_count,
        "marks_missing_native_point": grid_30m.missing_count,
    }
    if grid_30m.missing_count:
        failed.append("20_metrics_alignment_30m")

    gap_result = checks.classify_gaps(grid_5m.missing_timestamps_ms)

    rows = df.height
    start_ms = int(df_ts["_ts_ms"].min()) if rows else None  # type: ignore[arg-type]
    end_ms = int(df_ts["_ts_ms"].max()) if rows else None  # type: ignore[arg-type]

    quality_score = _quality_score(
        rows=rows,
        missing_bars=grid_5m.missing_count,
        duplicates=dup_result.excess_rows,
        invalid_rows=0,
    )
    gate = "PASS" if not failed else "FAIL"

    missing_ts = grid_5m.missing_timestamps_ms[:_MAX_MISSING_TIMESTAMPS_LISTED]
    return QualityReport(
        dataset="metrics",
        symbol=symbol,
        version=_REPORT_VERSION,
        rows=rows,
        start=ms_to_iso(start_ms) if start_ms is not None else None,
        end=ms_to_iso(end_ms) if end_ms is not None else None,
        missing_bars=grid_5m.missing_count,
        missing_timestamps=[ms_to_iso(t) for t in missing_ts],
        gap_classification={
            "maintenance": gap_result.maintenance,
            "collection": gap_result.collection,
            "unknown": gap_result.unknown,
        },
        duplicates=dup_result.excess_rows,
        invalid_rows=0,
        outliers_flagged=0,
        cross_source_max_deviation=None,
        coverage_by_feature={},
        effective_start=None,
        quality_score=quality_score,
        gate=gate,
        checks_skipped=checks_skipped,
        failed_checks=failed,
        diagnostics=diagnostics,
    )


# ============================================================================
# funding — check 19 (intervalo derivado do dado, nunca assumido)
# ============================================================================


def validate_funding(df: pl.DataFrame, *, symbol: str = "BTCUSDT") -> QualityReport:
    schema = schemas.get_schema("funding")
    if df.is_empty():
        return _empty_report("funding", reason=_EMPTY_DF_REASON, symbol=symbol)
    checks_skipped = [
        {"check": "2_checksum", "reason": "ver nota em validate_klines_like"},
        {
            "check": "7_close_time_convention",
            "reason": "funding não tem close_time — evento pontual",
        },
        {
            "check": "9_grid_completeness",
            "reason": (
                "grade não é fixa a priori (grid_step_ms=None) — check 19 mede o "
                "intervalo real em vez de exigir uma grade assumida"
            ),
        },
        {"check": "11_14_value_checks", "reason": "sem OHLCV em funding"},
        {"check": "15_outlier_returns", "reason": "sem close de barra em funding"},
        {"check": "16_18_cross_source", "reason": "não aplicável a funding"},
        {
            "check": "23_venue_semantic_break",
            "reason": "funding (D07) não deriva de bookTicker/bookDepth",
        },
    ]
    failed: list[str] = []
    diagnostics: dict[str, Any] = {}

    schema_result = checks.check_schema(df, schema)
    diagnostics["1_schema"] = asdict(schema_result)
    if not schema_result.passed:
        failed.append("1_schema")

    dup_result = checks.check_duplicates(df, schema.primary_key)
    diagnostics["3_duplicates"] = asdict(dup_result)
    if dup_result.excess_rows:
        failed.append("3_duplicates")

    null_result = checks.check_nulls(df, schema.non_nullable)
    diagnostics["4_nulls"] = null_result.counts
    if null_result.total:
        failed.append("4_nulls")

    mono_result = checks.check_monotonic(df, "calc_time")
    diagnostics["5_8_monotonic"] = asdict(mono_result)
    if not mono_result.is_strictly_monotonic:
        failed.append("5_8_monotonic")

    interval_result = checks.check_funding_interval(df)
    diagnostics["19_funding_interval"] = asdict(interval_result)
    if interval_result.inconsistent_rows:
        failed.append("19_funding_interval_inconsistent")

    rows = df.height
    start_ms = int(df["calc_time"].min()) if rows else None  # type: ignore[arg-type]
    end_ms = int(df["calc_time"].max()) if rows else None  # type: ignore[arg-type]

    quality_score = _quality_score(
        rows=rows, missing_bars=0, duplicates=dup_result.excess_rows, invalid_rows=0
    )
    gate = "PASS" if not failed else "FAIL"

    return QualityReport(
        dataset="funding",
        symbol=symbol,
        version=_REPORT_VERSION,
        rows=rows,
        start=ms_to_iso(start_ms) if start_ms is not None else None,
        end=ms_to_iso(end_ms) if end_ms is not None else None,
        missing_bars=0,
        missing_timestamps=[],
        gap_classification={"maintenance": 0, "collection": 0, "unknown": 0},
        duplicates=dup_result.excess_rows,
        invalid_rows=0,
        outliers_flagged=0,
        cross_source_max_deviation=None,
        coverage_by_feature={},
        effective_start=None,
        quality_score=quality_score,
        gate=gate,
        checks_skipped=checks_skipped,
        failed_checks=failed,
        diagnostics=diagnostics,
    )


# ============================================================================
# CLI — `python -m src.data.validate --dataset klines_1m --start ... --end ...`
# ============================================================================


def _run_cli() -> int:
    from . import lake, resample

    parser = argparse.ArgumentParser(
        description="Data Quality Engine (§1.3) — roda contra data/capacity/"
    )
    parser.add_argument(
        "--dataset",
        default="klines_1m",
        choices=[
            "klines_1m",
            "agg_trades",
            "metrics",
            "funding",
            "bars_15m",
            "bars_30m",
            "bars_1h",
            "dollar_bars_r1",
            "dollar_bars_r2",
            "dollar_bars_r3",
        ],
    )
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--start", required=True, help="yyyy-mm-dd")
    parser.add_argument("--end", required=True, help="yyyy-mm-dd")
    args = parser.parse_args()

    if args.dataset == "klines_1m":
        df = lake.query_bars(
            args.symbol, "1m", args.start, args.end, source="klines_1m", cast_prices=False
        )
        mark_df = lake.query_bars(
            args.symbol,
            "1m",
            args.start,
            args.end,
            source="mark_price_klines_1m",
            cast_prices=False,
        )
        report = validate_klines_like(
            df, dataset_name="klines_1m", mark_df=mark_df, symbol=args.symbol
        )
    elif args.dataset == "agg_trades":
        df = lake.query_agg_trades(args.symbol, args.start, args.end)
        report = validate_agg_trades(df, symbol=args.symbol)
    elif args.dataset == "metrics":
        df = lake.query_metrics(args.symbol, args.start, args.end)
        report = validate_metrics(df, symbol=args.symbol)
    elif args.dataset == "funding":
        df = lake.query_funding(args.symbol, args.start, args.end)
        report = validate_funding(df, symbol=args.symbol)
    elif args.dataset.startswith("bars_"):
        # Generaliza pras 3 grades de tempo (15m/30m/1h), mesma convenção
        # de src.data.build_dollar_bars.CALIBRATION_TF_BY_RESOLUTION —
        # achado real (mapa de dívida técnica multi-ativo, 2026-08-22):
        # o CLI só cobria 30m com valor cravado, apesar de
        # validate_resampled_bars/resample_klines já serem genéricos por
        # tf. NOTA: mesmo com as 3 grades disponíveis aqui, o check 16
        # (paridade cross-source) só produz resultado real se houver kline
        # NATIVO de 15m/30m/1h em disco — hoje só klines_1m nativo existe;
        # sem isso o gate cai em PENDING (ver validate_resampled_bars) —
        # baixar kline nativo é decisão de escopo/custo separada, fora
        # deste achado.
        tf = args.dataset.removeprefix("bars_")
        df_1m = lake.query_bars(args.symbol, "1m", args.start, args.end, source="klines_1m")
        df_resampled = resample.resample_klines(df_1m, tf)
        report = validate_resampled_bars(df_resampled, timeframe=tf, symbol=args.symbol)
    elif args.dataset in ("dollar_bars_r1", "dollar_bars_r2", "dollar_bars_r3"):
        resolution_id = args.dataset.removeprefix("dollar_bars_").upper()
        df = lake.query_dollar_bars(
            args.symbol, args.start, args.end, resolution_id=resolution_id
        )
        report = validate_dollar_bars(df, resolution_id=resolution_id, symbol=args.symbol)
    else:  # pragma: no cover — argparse choices já restringe
        raise ValueError(args.dataset)

    path = write_report_atomic(report)
    logger.info(
        "validate.cli_done",
        dataset=report.dataset,
        symbol=report.symbol,
        gate=report.gate,
        rows=report.rows,
        duplicates=report.duplicates,
        missing_bars=report.missing_bars,
        outliers_flagged=report.outliers_flagged,
        report_path=str(path),
    )
    return 0 if report.gate == "PASS" else 1


if __name__ == "__main__":
    # `data/` não importa `monitoring/` (mesmo padrão declarado em
    # src/monitoring/logging.py: camadas usam `structlog` direto e deixam a
    # configuração para o entry point). Este bloco é para execução manual
    # (`python -m src.data.validate ...`); um entry point real
    # (`scripts/run_validate.py`, fora da hierarquia de camadas) chamaria
    # `configure_logging()` antes de invocar `_run_cli()`.
    import sys

    sys.exit(_run_cli())
