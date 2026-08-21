"""Testes de `src/data/validate.py` — orquestração dos checks em
`QualityReport`, com dados sintéticos onde a violação é conhecida a priori
(permite afirmar exatamente o que o relatório deveria dizer), e um teste de
formato de JSON contra o schema literal do §1.3."""

from __future__ import annotations

import orjson
import polars as pl
import pytest

from src.data import validate
from src.data._constants import load_constant


def _make_1m_bars(n: int, *, start_open_time: int = 0) -> pl.DataFrame:
    open_times = [start_open_time + i * 60_000 for i in range(n)]
    return pl.DataFrame(
        {
            "open_time": open_times,
            "open": [str(100.0 + i) for i in range(n)],
            "high": [str(100.5 + i) for i in range(n)],
            "low": [str(99.5 + i) for i in range(n)],
            "close": [str(100.0 + i) for i in range(n)],
            "volume": [1.0] * n,
            "close_time": [t + 59_999 for t in open_times],
            "quote_volume": [1.0] * n,
            "count": [1] * n,
            "taker_buy_volume": [0.5] * n,
            "taker_buy_quote_volume": [0.5] * n,
            "ignore": ["0"] * n,
        }
    )


def test_validate_klines_like_dado_limpo_passa() -> None:
    df = _make_1m_bars(10)
    report = validate.validate_klines_like(df, dataset_name="klines_1m", compute_coverage=False)
    assert report.gate == "PASS"
    assert report.duplicates == 0
    assert report.missing_bars == 0
    assert report.invalid_rows == 0
    assert report.rows == 10


def test_validate_klines_like_detecta_duplicata_e_falha_gate() -> None:
    df = _make_1m_bars(10)
    df = pl.concat([df, df.slice(0, 1)])  # duplica a primeira linha
    report = validate.validate_klines_like(df, dataset_name="klines_1m", compute_coverage=False)
    assert report.gate == "FAIL"
    assert report.duplicates == 1
    assert "3_duplicates" in report.failed_checks


def test_validate_klines_like_detecta_gap_na_grade() -> None:
    df = _make_1m_bars(10)
    df = df.filter(pl.col("open_time") != 5 * 60_000)  # remove a barra do minuto 5
    report = validate.validate_klines_like(df, dataset_name="klines_1m", compute_coverage=False)
    assert report.missing_bars == 1
    assert len(report.missing_timestamps) == 1


def test_validate_klines_like_detecta_ohlc_incoerente() -> None:
    df = _make_1m_bars(5)
    # quebra a coerência OHLC da primeira linha: high < low
    df = df.with_columns(
        pl.when(pl.col("open_time") == 0)
        .then(pl.lit("1.0"))
        .otherwise(pl.col("high"))
        .alias("high")
    )
    report = validate.validate_klines_like(df, dataset_name="klines_1m", compute_coverage=False)
    assert report.invalid_rows >= 1
    assert report.gate == "FAIL"


def test_validate_klines_like_outlier_nao_falha_gate() -> None:
    # check 15 é "marca, não descarta" — outlier isolado não deve reprovar o gate.
    # Ajusta open/high/low/close JUNTOS na barra do salto para não disparar
    # também o check 11 (coerência OHLC) por acidente — o teste quer isolar
    # só o comportamento do check 15. Amostra de 300 barras (não 30): sigma é
    # medido na própria série, e um único salto numa amostra pequena infla o
    # desvio-padrão o bastante para se mascarar do limiar de 8*sigma (ver
    # nota equivalente em tests/unit/test_data_checks.py) — precisa de n
    # grande o bastante para o salto realmente ultrapassar 8*sigma medido.
    df = _make_1m_bars(300)
    is_outlier_bar = pl.col("open_time") == 150 * 60_000
    df = df.with_columns(
        [
            pl.when(is_outlier_bar).then(pl.lit("100000.0")).otherwise(pl.col(c)).alias(c)
            for c in ("open", "high", "low", "close")
        ]
    )
    report = validate.validate_klines_like(df, dataset_name="klines_1m", compute_coverage=False)
    assert report.outliers_flagged >= 1
    assert "15_outliers" not in report.failed_checks
    assert report.gate == "PASS"


def test_validate_klines_like_com_mark_df_dentro_da_tolerancia() -> None:
    df = _make_1m_bars(10)
    mark_df = _make_1m_bars(10)  # idêntico -> desvio 0
    report = validate.validate_klines_like(
        df, dataset_name="klines_1m", mark_df=mark_df, compute_coverage=False
    )
    assert "17_mark_price_deviation" not in report.failed_checks
    assert report.diagnostics["17_mark_price_deviation_pct"]["violation_count"] == 0


def test_validate_klines_like_dataframe_vazio() -> None:
    df = _make_1m_bars(0)
    report = validate.validate_klines_like(df, dataset_name="klines_1m", compute_coverage=False)
    assert report.gate == "FAIL"
    assert report.rows == 0
    assert report.dataset == "klines_1m"


def test_quality_score_zero_rows_e_zero_missing() -> None:
    assert validate._quality_score(rows=0, missing_bars=0, duplicates=0, invalid_rows=0) == 0.0


def test_quality_score_perfeito() -> None:
    assert validate._quality_score(rows=100, missing_bars=0, duplicates=0, invalid_rows=0) == 1.0


def test_quality_score_com_defeitos() -> None:
    score = validate._quality_score(rows=90, missing_bars=10, duplicates=0, invalid_rows=0)
    assert score == pytest.approx(0.9)


# ============================================================================
# formato de saída — chaves literais do §1.3
# ============================================================================

_PRD_TOP_LEVEL_KEYS = {
    "dataset",
    "version",
    "rows",
    "start",
    "end",
    "missing_bars",
    "missing_timestamps",
    "gap_classification",
    "duplicates",
    "invalid_rows",
    "outliers_flagged",
    "cross_source_max_deviation",
    "coverage_by_feature",
    "effective_start",
    "quality_score",
    "gate",
}


def test_write_report_atomic_json_tem_as_chaves_do_prd(tmp_path) -> None:  # type: ignore[no-untyped-def]
    df = _make_1m_bars(10)
    report = validate.validate_klines_like(df, dataset_name="klines_1m", compute_coverage=False)
    dest = tmp_path / "quality_report_klines_1m_v1.json"
    validate.write_report_atomic(report, dest)

    assert dest.exists()
    assert not dest.with_name(dest.name + ".tmp").exists()  # tmp não sobrevive (B29)

    loaded = orjson.loads(dest.read_bytes())
    assert _PRD_TOP_LEVEL_KEYS.issubset(loaded.keys())
    assert loaded["dataset"] == "klines_1m"
    assert loaded["gate"] == "PASS"


# ============================================================================
# assert_ready_for_training — invariante do consumidor (ver nota 2 no
# docstring do módulo)
# ============================================================================


def test_assert_ready_for_training_passa_em_report_pass() -> None:
    df = _make_1m_bars(10)
    report = validate.validate_klines_like(df, dataset_name="klines_1m", compute_coverage=False)
    validate.assert_ready_for_training(report, "2020-01-01T00:00:00Z")  # não deve levantar


def test_assert_ready_for_training_falha_em_report_fail() -> None:
    df = _make_1m_bars(10)
    df = pl.concat([df, df.slice(0, 1)])
    report = validate.validate_klines_like(df, dataset_name="klines_1m", compute_coverage=False)
    with pytest.raises(AssertionError):
        validate.assert_ready_for_training(report, "2020-01-01T00:00:00Z")


def test_assert_ready_for_training_falha_se_dataset_start_antes_do_effective_start() -> None:
    df = _make_1m_bars(10)
    report = validate.validate_klines_like(df, dataset_name="klines_1m", compute_coverage=False)
    # QualityReport não é frozen — mutação direta no teste
    report.effective_start = "2022-01-01T00:00:00Z"
    with pytest.raises(AssertionError):
        validate.assert_ready_for_training(report, "2020-01-01T00:00:00Z")


# ============================================================================
# outros formatos de dataset — smoke test sintético
# ============================================================================


def test_validate_agg_trades_dado_limpo() -> None:
    df = pl.DataFrame(
        {
            "agg_trade_id": [1, 2, 3],
            "price": [100.0, 100.1, 99.9],
            "quantity": [0.1, 0.2, 0.1],
            "first_trade_id": [1, 2, 3],
            "last_trade_id": [1, 2, 3],
            "transact_time": [0, 100, 200],
            "is_buyer_maker": [True, False, True],
        }
    )
    report = validate.validate_agg_trades(df)
    assert report.gate == "PASS"


def test_validate_metrics_dado_limpo() -> None:
    df = pl.DataFrame(
        {
            "create_time": ["2024-01-15 00:00:00", "2024-01-15 00:05:00", "2024-01-15 00:30:00"],
            "symbol": ["BTCUSDT"] * 3,
            "sum_open_interest": [1.0, 1.0, 1.0],
            "sum_open_interest_value": [1.0, 1.0, 1.0],
            "count_toptrader_long_short_ratio": [1.0, 1.0, 1.0],
            "sum_toptrader_long_short_ratio": [1.0, 1.0, 1.0],
            "count_long_short_ratio": [1.0, 1.0, 1.0],
            "sum_taker_long_short_vol_ratio": [1.0, 1.0, 1.0],
        }
    )
    report = validate.validate_metrics(df)
    assert report.dataset == "metrics"
    # 00:05 -> 00:30 tem lacuna na grade de 5m (faltam 00:10,00:15,00:20,00:25)
    assert report.missing_bars == 4


def test_validate_funding_dado_limpo() -> None:
    hour = 3_600_000
    df = pl.DataFrame(
        {
            "calc_time": [0, 8 * hour, 16 * hour],
            "funding_interval_hours": [8, 8, 8],
            "last_funding_rate": ["0.0001", "0.0001", "0.0001"],
        }
    )
    report = validate.validate_funding(df)
    assert report.gate == "PASS"
    assert report.diagnostics["19_funding_interval"]["inconsistent_rows"] == 0


def test_load_constant_outlier_threshold_e_8() -> None:
    assert load_constant("outlier_log_return_sigma_threshold") == 8.0


# ============================================================================
# dollar bars (achado F3) — validate_dollar_bars
# ============================================================================


def _make_dollar_bars(n: int, *, start_time: int = 0, step_ms: int = 900_000) -> pl.DataFrame:
    open_times = [start_time + i * step_ms for i in range(n)]
    close_times = [t + step_ms - 1 for t in open_times]
    return pl.DataFrame(
        {
            "open_time": open_times,
            "close_time": close_times,
            "open": [100.0 + i for i in range(n)],
            "high": [100.5 + i for i in range(n)],
            "low": [99.5 + i for i in range(n)],
            "close": [100.0 + i for i in range(n)],
            "volume": [1.0] * n,
            "quote_volume": [100.0] * n,
            "count": pl.Series([1] * n, dtype=pl.UInt32),
            "taker_buy_volume": [0.5] * n,
            "taker_buy_quote_volume": [50.0] * n,
            # AG-124 -- threshold_quote agora faz parte de
            # schemas._DOLLAR_BARS_COLUMNS (Camada 0); fixture precisa
            # incluir a coluna pra check_schema (1_schema) continuar PASS.
            "threshold_quote": pl.Series([1_000_000.0] * n, dtype=pl.Float64),
        }
    )


def test_validate_dollar_bars_dado_limpo_passa() -> None:
    df = _make_dollar_bars(10)
    report = validate.validate_dollar_bars(df, resolution_id="R1")
    assert report.gate == "PASS"
    assert report.dataset == "dollar_bars_r1"
    assert report.duplicates == 0
    assert report.invalid_rows == 0
    assert report.rows == 10
    # sem grade fixa a priori — "ausente" não é conceito aplicável (achado F3)
    assert report.missing_bars == 0


def test_validate_dollar_bars_nao_roda_grid_completeness() -> None:
    # check 9 explicitamente EXCLUÍDO (barra event-driven) — precisa aparecer
    # em checks_skipped, e não deve ter rodado check_grid_completeness de
    # verdade (sem chave de diagnóstico "9_grid_completeness" com resultado).
    df = _make_dollar_bars(5)
    report = validate.validate_dollar_bars(df, resolution_id="R1")
    skipped_checks = {c["check"] for c in report.checks_skipped}
    assert "9_grid_completeness" in skipped_checks
    assert "9_grid_completeness" not in report.diagnostics


def test_validate_dollar_bars_detecta_duplicata_e_falha_gate() -> None:
    df = _make_dollar_bars(10)
    df = pl.concat([df, df.slice(0, 1)])  # duplica a primeira barra (open_time repetido)
    report = validate.validate_dollar_bars(df, resolution_id="R1")
    assert report.gate == "FAIL"
    assert report.duplicates == 1
    assert "3_duplicates" in report.failed_checks


def test_validate_dollar_bars_detecta_ohlc_incoerente() -> None:
    df = _make_dollar_bars(5)
    df = df.with_columns(
        pl.when(pl.col("open_time") == 0).then(1.0).otherwise(pl.col("high")).alias("high")
    )
    report = validate.validate_dollar_bars(df, resolution_id="R1")
    assert report.invalid_rows >= 1
    assert report.gate == "FAIL"


def test_validate_dollar_bars_dataframe_vazio() -> None:
    df = _make_dollar_bars(0)
    report = validate.validate_dollar_bars(df, resolution_id="R1", symbol="ETHUSDT")
    assert report.gate == "FAIL"
    assert report.rows == 0
    assert report.dataset == "dollar_bars_r1"
    assert report.symbol == "ETHUSDT"


def test_validate_dollar_bars_dataset_name_por_resolucao() -> None:
    df = _make_dollar_bars(3)
    for resolution_id, expected_dataset in (
        ("R1", "dollar_bars_r1"),
        ("R2", "dollar_bars_r2"),
        ("R3", "dollar_bars_r3"),
    ):
        report = validate.validate_dollar_bars(df, resolution_id=resolution_id)
        assert report.dataset == expected_dataset


def test_validate_dollar_bars_symbol_propaga() -> None:
    df = _make_dollar_bars(5)
    report = validate.validate_dollar_bars(df, resolution_id="R1", symbol="SOLUSDT")
    assert report.symbol == "SOLUSDT"


# ============================================================================
# QualityReport.symbol + write_report_atomic (achado F4)
# ============================================================================


def test_quality_report_tem_campo_symbol() -> None:
    df = _make_1m_bars(10)
    report = validate.validate_klines_like(
        df, dataset_name="klines_1m", compute_coverage=False, symbol="ETHUSDT"
    )
    assert report.symbol == "ETHUSDT"


def test_quality_report_symbol_default_btcusdt() -> None:
    df = _make_1m_bars(10)
    report = validate.validate_klines_like(df, dataset_name="klines_1m", compute_coverage=False)
    assert report.symbol == "BTCUSDT"


def test_write_report_atomic_nome_default_inclui_symbol(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(validate, "QUALITY_REPORTS_DIR", tmp_path)
    df = _make_1m_bars(10)
    report = validate.validate_klines_like(
        df, dataset_name="klines_1m", compute_coverage=False, symbol="ETHUSDT"
    )
    path = validate.write_report_atomic(report)
    assert path.name == "quality_report_klines_1m_ETHUSDT_v1.json"
    assert path.exists()


def test_write_report_atomic_loga_warning_em_mudanca_material_mas_nao_bloqueia(tmp_path) -> None:  # type: ignore[no-untyped-def]
    import structlog.testing

    dest = tmp_path / "quality_report_klines_1m_BTCUSDT_v1.json"

    df_clean = _make_1m_bars(10)
    report_pass = validate.validate_klines_like(
        df_clean, dataset_name="klines_1m", compute_coverage=False
    )
    validate.write_report_atomic(report_pass, dest)
    assert orjson.loads(dest.read_bytes())["gate"] == "PASS"

    df_dup = pl.concat([df_clean, df_clean.slice(0, 1)])
    report_fail = validate.validate_klines_like(
        df_dup, dataset_name="klines_1m", compute_coverage=False
    )
    with structlog.testing.capture_logs() as logs:
        validate.write_report_atomic(report_fail, dest)

    warnings = [e for e in logs if e.get("log_level") == "warning"]
    assert len(warnings) == 1
    assert warnings[0]["event"] == "validate.report_overwrite_material_change"
    assert "gate" in warnings[0]["changed_fields"]
    assert warnings[0]["previous_gate"] == "PASS"
    assert warnings[0]["new_gate"] == "FAIL"

    # a escrita acontece de qualquer forma — warning não bloqueia (diferente
    # da guarda de build_dollar_bars.write_dollar_bars_and_calibration, que
    # levanta ValueError; aqui o comportamento é deliberadamente mais brando)
    assert orjson.loads(dest.read_bytes())["gate"] == "FAIL"


def test_write_report_atomic_sem_warning_quando_reescreve_sem_mudanca_material(  # type: ignore[no-untyped-def]
    tmp_path,
) -> None:
    import structlog.testing

    dest = tmp_path / "quality_report_klines_1m_BTCUSDT_v1.json"
    df = _make_1m_bars(10)
    report = validate.validate_klines_like(df, dataset_name="klines_1m", compute_coverage=False)
    validate.write_report_atomic(report, dest)

    with structlog.testing.capture_logs() as logs:
        validate.write_report_atomic(report, dest)  # mesmo report, reescreve idêntico

    warnings = [e for e in logs if e.get("log_level") == "warning"]
    assert not warnings


# ============================================================================
# achado F7 — texto do skip do check 2_checksum não pode afirmar que
# src/data/download.py "não existe ainda" (já existe e já verifica checksum)
# ============================================================================


def test_checksum_skip_reason_nao_afirma_que_download_nao_existe() -> None:
    df = _make_1m_bars(10)
    report = validate.validate_klines_like(df, dataset_name="klines_1m", compute_coverage=False)
    reason = next(c["reason"] for c in report.checks_skipped if c["check"] == "2_checksum")
    assert "não existe ainda" not in reason
    assert "download.py" in reason
    assert "wire-up" in reason.lower() or "WIRE-UP" in reason
