"""Testes de `src/data/resample.py` — agregação sintética controlada +
verificações de causalidade explícitas (instrução do Sprint 2: escrever o
teste mesmo sabendo que a construção já garante o resultado)."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from src.data import resample


def _make_1m_bars(n: int, *, start_open_time: int = 0) -> pl.DataFrame:
    """`n` barras de 1 minuto sintéticas, OHLCV simples e determinístico:
    open=i, high=i+0.5, low=i-0.5, close=i, volume=1.0 por barra."""
    open_times = [start_open_time + i * 60_000 for i in range(n)]
    closes = [float(i) for i in range(n)]
    return pl.DataFrame(
        {
            "open_time": open_times,
            "open": [str(float(i)) for i in range(n)],
            "high": [str(float(i) + 0.5) for i in range(n)],
            "low": [str(float(i) - 0.5) for i in range(n)],
            "close": [str(c) for c in closes],
            "volume": [1.0] * n,
            "close_time": [t + 59_999 for t in open_times],
            "quote_volume": [1.0] * n,
            "count": [1] * n,
            "taker_buy_volume": [0.5] * n,
            "taker_buy_quote_volume": [0.5] * n,
        }
    )


def test_resample_agrega_ohlcv_corretamente() -> None:
    df_1m = _make_1m_bars(5)  # exatamente 1 bucket de 5m
    out = resample.resample_klines(df_1m, "5m")
    assert out.height == 1
    row = out.row(0, named=True)
    assert row["open"] == 0.0  # primeira barra
    assert row["close"] == 4.0  # última barra
    assert row["high"] == 4.5  # max de high
    assert row["low"] == -0.5  # min de low
    assert row["volume"] == 5.0  # soma
    assert row["count"] == 5
    assert row["open_time"] == 0
    assert row["close_time"] == 5 * 60_000 - 1


def test_resample_drop_incomplete_tail_por_padrao() -> None:
    df_1m = _make_1m_bars(7)  # 1 bucket completo de 5m + 2 barras soltas
    out = resample.resample_klines(df_1m, "5m")
    assert out.height == 1  # tail incompleto descartado


def test_resample_mantem_tail_incompleto_se_pedido() -> None:
    df_1m = _make_1m_bars(7)
    out = resample.resample_klines(df_1m, "5m", drop_incomplete_tail=False)
    assert out.height == 2


def test_resample_determinismo_bit_a_bit() -> None:
    df_1m = _make_1m_bars(30)
    out1 = resample.resample_klines(df_1m, "15m")
    out2 = resample.resample_klines(df_1m, "15m")
    assert out1.equals(out2)


def test_resample_timeframe_nao_suportado_levanta_erro() -> None:
    df_1m = _make_1m_bars(5)
    with pytest.raises(resample.UnsupportedTimeframeError):
        resample.resample_klines(df_1m, "3m")


def test_resample_df_vazio_retorna_vazio() -> None:
    df_1m = _make_1m_bars(0)
    out = resample.resample_klines(df_1m, "5m")
    assert out.is_empty()


def test_assert_no_lookahead_passa_para_resample_correto() -> None:
    df_1m = _make_1m_bars(30)
    out = resample.resample_klines(df_1m, "15m")
    resample.assert_no_lookahead(df_1m, out, "15m")  # não deve levantar


def test_assert_no_lookahead_passa_para_resample_correto_30m() -> None:
    """Complemento explícito do Sprint de validação (§11.5 teste 9): a
    cobertura acima só exercitava 5m/15m; o PRD (§11.5 #9) cita literalmente
    "agregação 1m->30m fecha em close_time" — mesma função genérica
    (`resample_klines`/`assert_no_lookahead`, parametrizada por `timeframe`),
    mas testada aqui contra 30m explicitamente, não só por generalização."""
    df_1m = _make_1m_bars(90)  # 3 buckets completos de 30m
    out = resample.resample_klines(df_1m, "30m")
    assert out.height == 3
    resample.assert_no_lookahead(df_1m, out, "30m")  # não deve levantar


def test_assert_no_lookahead_detecta_close_time_futuro_forjado() -> None:
    df_1m = _make_1m_bars(30)
    out = resample.resample_klines(df_1m, "15m")
    # forja um close_time ANTERIOR ao real da última constituinte — simula uma
    # barra "fechada cedo demais", o oposto do look-ahead mas mesma mecânica
    # de comparação: close_time da barra tem que ser >= max close_time das
    # constituintes.
    corrupted = out.with_columns(pl.col("close_time") - 1)
    with pytest.raises(AssertionError):
        resample.assert_no_lookahead(df_1m, corrupted, "15m")


# ============================================================================
# check 16 — busca de nativo + comparação de paridade
# ============================================================================


def test_find_native_klines_ausente_retorna_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    empty_root = tmp_path / "capacity_vazio"
    empty_root.mkdir()
    monkeypatch.setattr(resample, "_NATIVE_SEARCH_ROOTS", (empty_root,))
    assert resample.find_native_klines("BTCUSDT", "30m") is None


def test_find_native_klines_encontra_quando_presente(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "capacity"
    native_dir = root / "klines_30m" / "BTCUSDT"
    native_dir.mkdir(parents=True)
    (native_dir / "2024-01-01.parquet").write_bytes(b"")
    monkeypatch.setattr(resample, "_NATIVE_SEARCH_ROOTS", (root,))
    found = resample.find_native_klines("BTCUSDT", "30m")
    assert found == native_dir


def test_compare_resample_to_native_dentro_da_tolerancia(tmp_path: Path) -> None:
    df_1m = _make_1m_bars(5)
    resampled = resample.resample_klines(df_1m, "5m")

    native_dir = tmp_path / "native"
    native_dir.mkdir()
    native = resampled.select(["open_time", "open", "high", "low", "close", "volume"])
    native.write_parquet(native_dir / "2024-01-01.parquet")

    result = resample.compare_resample_to_native(resampled, native_dir)
    assert result.compared
    assert result.passed
    assert result.max_abs_deviation == pytest.approx(0.0)


def test_compare_resample_to_native_fora_da_tolerancia(tmp_path: Path) -> None:
    df_1m = _make_1m_bars(5)
    resampled = resample.resample_klines(df_1m, "5m")

    native_dir = tmp_path / "native"
    native_dir.mkdir()
    native = resampled.select(["open_time", "open", "high", "low", "close", "volume"]).with_columns(
        pl.col("close") + 1.0  # desvio grande, propositalmente fora de 1e-8
    )
    native.write_parquet(native_dir / "2024-01-01.parquet")

    result = resample.compare_resample_to_native(resampled, native_dir)
    assert result.compared
    assert not result.passed
    assert result.max_abs_deviation is not None and result.max_abs_deviation >= 1.0


def test_compare_resample_to_native_diretorio_vazio(tmp_path: Path) -> None:
    df_1m = _make_1m_bars(5)
    resampled = resample.resample_klines(df_1m, "5m")
    native_dir = tmp_path / "vazio"
    native_dir.mkdir()
    result = resample.compare_resample_to_native(resampled, native_dir)
    assert not result.compared
    assert result.reason_not_compared is not None
