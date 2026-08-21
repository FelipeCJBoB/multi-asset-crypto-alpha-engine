"""Testes das primitivas atômicas de `src/data/checks.py` — dados sintéticos
pequenos e controlados, um cenário por check, para que cada teste isole
exatamente a condição que o check existe para detectar."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from src.data import checks, schemas

# ============================================================================
# check 1 — schema
# ============================================================================


def test_check_schema_passa_com_schema_correto() -> None:
    df = pl.DataFrame(
        {
            "open_time": [0],
            "open": ["1.0"],
            "high": ["1.0"],
            "low": ["1.0"],
            "close": ["1.0"],
            "volume": [1.0],
            "close_time": [59999],
            "quote_volume": [1.0],
            "count": [1],
            "taker_buy_volume": [1.0],
            "taker_buy_quote_volume": [1.0],
            "ignore": ["0"],
        }
    )
    result = checks.check_schema(df, schemas.KLINES_1M)
    assert result.passed
    assert not result.missing_columns
    assert not result.extra_columns
    assert not result.dtype_mismatches


def test_check_schema_detecta_coluna_ausente() -> None:
    df = pl.DataFrame({"open_time": [0]})
    result = checks.check_schema(df, schemas.KLINES_1M)
    assert not result.passed
    assert "open" in result.missing_columns


def test_check_schema_detecta_dtype_errado() -> None:
    df = pl.DataFrame(
        {
            "open_time": [0],
            "open": [1.0],  # deveria ser Utf8, não Float64 — ver schemas.py
            "high": ["1.0"],
            "low": ["1.0"],
            "close": ["1.0"],
            "volume": [1.0],
            "close_time": [59999],
            "quote_volume": [1.0],
            "count": [1],
            "taker_buy_volume": [1.0],
            "taker_buy_quote_volume": [1.0],
            "ignore": ["0"],
        }
    )
    result = checks.check_schema(df, schemas.KLINES_1M)
    assert not result.passed
    assert any("open" in m for m in result.dtype_mismatches)


# ============================================================================
# check 3 — duplicatas
# ============================================================================


def test_check_duplicates_sem_duplicata() -> None:
    df = pl.DataFrame({"open_time": [0, 60_000, 120_000]})
    result = checks.check_duplicates(df, ("open_time",))
    assert result.excess_rows == 0
    assert result.distinct_keys_with_duplicates == 0


def test_check_duplicates_detecta_e_conta_excesso() -> None:
    # open_time=60000 aparece 3x -> 2 linhas "a mais"
    df = pl.DataFrame({"open_time": [0, 60_000, 60_000, 60_000, 120_000]})
    result = checks.check_duplicates(df, ("open_time",))
    assert result.excess_rows == 2
    assert result.distinct_keys_with_duplicates == 1
    assert result.example_keys[0]["open_time"] == 60_000


# ============================================================================
# check 4 — nulos
# ============================================================================


def test_check_nulls_conta_por_coluna() -> None:
    df = pl.DataFrame({"a": [1, None, 3], "b": [None, None, 1]})
    result = checks.check_nulls(df, ("a", "b"))
    assert result.counts == {"a": 1, "b": 2}
    assert result.total == 3


# ============================================================================
# check 5/8 — monotonicidade
# ============================================================================


def test_check_monotonic_passa_em_serie_crescente() -> None:
    df = pl.DataFrame({"t": [0, 60_000, 120_000, 180_000]})
    result = checks.check_monotonic(df, "t")
    assert result.is_strictly_monotonic
    assert result.non_positive_diff_count == 0


def test_check_monotonic_detecta_fora_de_ordem() -> None:
    df = pl.DataFrame({"t": [0, 120_000, 60_000, 180_000]})  # 60_000 depois de 120_000
    result = checks.check_monotonic(df, "t")
    assert not result.is_strictly_monotonic
    assert result.non_positive_diff_count == 1


# ============================================================================
# check 7 — convenção close_time
# ============================================================================


def test_check_close_time_convention() -> None:
    step = 60_000
    df_ok = pl.DataFrame({"open_time": [0, step], "close_time": [step - 1, 2 * step - 1]})
    assert checks.check_close_time_convention(df_ok, step).passed

    df_bad = pl.DataFrame({"open_time": [0], "close_time": [step]})  # deveria ser step - 1
    result = checks.check_close_time_convention(df_bad, step)
    assert not result.passed
    assert result.violation_count == 1


# ============================================================================
# check 9 — grade completa, timestamps ausentes LISTADOS
# ============================================================================


def test_check_grid_completeness_lista_ausentes_nominalmente() -> None:
    step = 60_000
    # grade 0..300000 de 60000 em 60000 = [0,60000,120000,180000,240000,300000] (6 pontos)
    # falta 120000 e 240000
    df = pl.DataFrame({"t": [0, 60_000, 180_000, 300_000]})
    result = checks.check_grid_completeness(df, "t", step)
    assert result.expected_count == 6
    assert result.actual_count == 4
    assert result.missing_count == 2
    assert set(result.missing_timestamps_ms) == {120_000, 240_000}


def test_check_grid_completeness_vazio() -> None:
    df = pl.DataFrame({"t": pl.Series([], dtype=pl.Int64)})
    result = checks.check_grid_completeness(df, "t", 60_000)
    assert result.expected_count == 0
    assert result.missing_count == 0


# ============================================================================
# check 10 — classificação de gaps
# ============================================================================


def test_classify_gaps_sem_calendario_cai_tudo_em_unknown() -> None:
    result = checks.classify_gaps((100, 200, 300))
    assert result.maintenance == 0
    assert result.collection == 0
    assert result.unknown == 3


def test_classify_gaps_com_janela_de_manutencao() -> None:
    result = checks.classify_gaps((100, 200, 300), maintenance_windows_ms=((150, 250),))
    assert result.maintenance == 1  # só 200 cai na janela [150,250]
    assert result.unknown == 2


# ============================================================================
# checks 11-14 — valores
# ============================================================================


def test_check_ohlc_coherence() -> None:
    df_ok = pl.DataFrame({"open": [10.0], "high": [12.0], "low": [9.0], "close": [11.0]})
    assert checks.check_ohlc_coherence(df_ok).violation_count == 0

    # high < open e < close
    df_bad = pl.DataFrame({"open": [10.0], "high": [8.0], "low": [9.0], "close": [11.0]})
    assert checks.check_ohlc_coherence(df_bad).violation_count == 1


def test_check_positive_prices() -> None:
    df = pl.DataFrame(
        {"open": [10.0, -1.0], "high": [12.0, 1.0], "low": [9.0, 0.0], "close": [11.0, 1.0]}
    )
    n = checks.check_positive_prices(df, ("open", "high", "low", "close"))
    assert n == 1  # a segunda linha tem open=-1 e low=0, mas conta como 1 linha inválida


def test_check_non_negative_volume() -> None:
    df = pl.DataFrame({"volume": [1.0, -0.5, 2.0]})
    assert checks.check_non_negative_volume(df) == 1


def test_check_taker_buy_leq_volume() -> None:
    df = pl.DataFrame({"volume": [10.0, 10.0], "taker_buy_volume": [5.0, 11.0]})
    assert checks.check_taker_buy_leq_volume(df) == 1


# ============================================================================
# check 15 — outliers marcados, não descartados
# ============================================================================


def test_check_outlier_log_returns_marca_sem_descartar() -> None:
    # sigma é medido na PRÓPRIA amostra (inclui o outlier) — um único salto
    # em uma amostra pequena infla o próprio desvio-padrão o bastante para
    # se "mascarar" do limiar de 8*sigma (efeito real de breakdown point de
    # desvio-padrão como estimador). Por isso a amostra sintética precisa de
    # n grande o bastante (>=130 diffs, aqui 299) para o efeito de diluição
    # que existe no dado real (86400 pontos, ver quality_report real do
    # Sprint 2) se reproduzir num teste pequeno.
    closes = [100.0] * 300
    closes[150] = 1000.0  # salto de 10x e volta — dois log-retornos grandes, resto zero
    df = pl.DataFrame({"t": list(range(len(closes))), "close": closes})
    result = checks.check_outlier_log_returns(df, "t", "close")
    assert result.flagged_count >= 1
    # "marca para inspeção, nunca descarta" — o check não filtra linhas do df de entrada
    assert result.sigma_threshold == 8.0


# ============================================================================
# checks 17/18 — desvio de preço entre fontes
# ============================================================================


def test_check_price_deviation() -> None:
    df_a = pl.DataFrame({"t": [0, 1, 2], "close": [100.0, 100.0, 100.0]})
    df_b = pl.DataFrame({"t": [0, 1, 2], "close": [100.5, 105.0, 100.0]})  # 0.5%, 5%, 0%
    result = checks.check_price_deviation(
        df_a, df_b, ts_col="t", price_a="close", price_b="close", threshold_pct=2.0
    )
    assert result.rows_compared == 3
    assert result.violation_count == 1  # só a linha de 5%
    assert result.max_abs_deviation_pct == pytest.approx(5.0)


def test_check_price_deviation_filtra_denominador_nao_positivo() -> None:
    # achado F6 — `_a` (price_a) é o denominador de `_dev_pct`; uma linha com
    # close<=0 (dado corrompido) precisa ser excluída ANTES da divisão, não
    # só ter o resultado ignorado depois — denominador <=0 nunca deveria
    # chegar a `_dev_pct`/`rows_compared`/`violation_count`.
    df_a = pl.DataFrame({"t": [0, 1, 2], "close": [100.0, 0.0, -5.0]})
    df_b = pl.DataFrame({"t": [0, 1, 2], "close": [100.5, 999.0, 999.0]})
    result = checks.check_price_deviation(
        df_a, df_b, ts_col="t", price_a="close", price_b="close", threshold_pct=2.0
    )
    # só a linha t=0 (close=100.0>0) sobrevive ao filtro do denominador
    assert result.rows_compared == 1
    assert result.violation_count == 0
    assert result.max_abs_deviation_pct == pytest.approx(0.5)


def test_check_price_deviation_todos_denominadores_nao_positivos() -> None:
    df_a = pl.DataFrame({"t": [0, 1], "close": [0.0, -1.0]})
    df_b = pl.DataFrame({"t": [0, 1], "close": [1.0, 1.0]})
    result = checks.check_price_deviation(
        df_a, df_b, ts_col="t", price_a="close", price_b="close", threshold_pct=2.0
    )
    assert result.rows_compared == 0
    assert result.violation_count == 0
    assert result.max_abs_deviation_pct == 0.0


# ============================================================================
# check 19 — intervalo de funding derivado do dado
# ============================================================================


def test_check_funding_interval_consistente() -> None:
    hour = 3_600_000
    df = pl.DataFrame(
        {
            "calc_time": [0, 8 * hour, 16 * hour, 24 * hour],
            "funding_interval_hours": [8, 8, 8, 8],
        }
    )
    result = checks.check_funding_interval(df)
    assert result.declared_hours_values == (8,)
    assert result.measured_median_gap_hours == pytest.approx(8.0)
    assert result.inconsistent_rows == 0


def test_check_funding_interval_detecta_inconsistencia() -> None:
    hour = 3_600_000
    df = pl.DataFrame(
        {
            # segundo intervalo é 4h de verdade, mas a linha declara 8h
            "calc_time": [0, 8 * hour, 12 * hour],
            "funding_interval_hours": [8, 8, 8],
        }
    )
    result = checks.check_funding_interval(df)
    assert result.inconsistent_rows == 1


# ============================================================================
# checks 21/22 — cobertura por fonte / effective_start
# ============================================================================


def test_compute_coverage(tmp_path: Path) -> None:
    d01 = tmp_path / "d01"
    d03 = tmp_path / "d03"
    d01.mkdir()
    d03.mkdir()
    (d01 / "2020-01-01.parquet").write_bytes(b"")
    (d01 / "2020-06-01.parquet").write_bytes(b"")
    (d03 / "2021-03-01.parquet").write_bytes(b"")

    result = checks.compute_coverage({"D01": d01, "D03": d03})
    assert result.coverage_by_source["D01"] == "2020-01-01T00:00:00Z"
    assert result.coverage_by_source["D03"] == "2021-03-01T00:00:00Z"
    assert result.effective_start == "2021-03-01T00:00:00Z"  # máximo das duas


def test_compute_coverage_fonte_vazia_nao_entra(tmp_path: Path) -> None:
    vazio = tmp_path / "vazio"
    vazio.mkdir()
    result = checks.compute_coverage({"VAZIO": vazio})
    assert "VAZIO" not in result.coverage_by_source
    assert result.effective_start == ""


# ============================================================================
# check 23 — quebra semântica de venue
# ============================================================================


_ISO_2020 = "2020-01-01T00:00:00Z"
_ISO_2024 = "2024-01-01T00:00:00Z"
_ISO_2026 = "2026-01-01T00:00:00Z"


def test_check_venue_semantic_breaks_nao_aplicavel_sem_features() -> None:
    result = checks.check_venue_semantic_breaks(
        (), [], series_start_iso=_ISO_2020, series_end_iso=_ISO_2026
    )
    assert not result.applicable
    assert result.reason_not_applicable is not None


def test_check_venue_semantic_breaks_detecta_quebra_sem_tratamento() -> None:
    events = [
        {
            "date": "2025-11-20",
            "event": "Binance Futures lança ordens RPI",
            "features_contaminadas": ["F01f", "F04f"],
            "tratamento": None,
        }
    ]
    result = checks.check_venue_semantic_breaks(
        ("F01f",), events, series_start_iso=_ISO_2020, series_end_iso=_ISO_2026
    )
    assert result.applicable
    assert result.unresolved_breaks == ("Binance Futures lança ordens RPI",)


def test_check_venue_semantic_breaks_com_tratamento_nao_e_unresolved() -> None:
    events = [
        {
            "date": "2025-11-20",
            "event": "Binance Futures lança ordens RPI",
            "features_contaminadas": ["F01f"],
            "tratamento": "ver PRD §2.7.1",
        }
    ]
    result = checks.check_venue_semantic_breaks(
        ("F01f",), events, series_start_iso=_ISO_2020, series_end_iso=_ISO_2026
    )
    assert result.unresolved_breaks == ()


def test_check_venue_semantic_breaks_serie_nao_cruza_a_quebra() -> None:
    events = [
        {
            "date": "2025-11-20",
            "event": "Binance Futures lança ordens RPI",
            "features_contaminadas": ["F01f"],
            "tratamento": None,
        }
    ]
    # série termina antes da quebra
    result = checks.check_venue_semantic_breaks(
        ("F01f",), events, series_start_iso=_ISO_2020, series_end_iso=_ISO_2024
    )
    assert result.unresolved_breaks == ()
