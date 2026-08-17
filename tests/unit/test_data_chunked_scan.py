"""Testes de `src/data/_chunked_scan.py` -- utilitários de streaming/chunking
extraídos de `src.analysis.m2_worker` (2026-08-16, ver docstring do módulo).
IO mockado na fronteira (`lake.query_bars`/`lake.query_agg_trades`), mesmo
padrão de `tests/unit/test_analysis_m2_worker.py` (que continua passando sem
alteração nenhuma -- os nomes antigos `m2_worker._date_chunks`/etc. seguem
funcionando via import-as, inclusive sob `monkeypatch.setattr(m2_worker,
"_date_chunks", ...)`, porque o resto de `m2_worker.py` continua chamando
pelo nome local, só a origem da definição mudou). Este arquivo testa os
nomes PÚBLICOS novos direto, não os aliases."""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from src.data import _chunked_scan, lake


def _bars(*, close: list[float], close_time: list[int]) -> pl.DataFrame:
    n = len(close)
    assert len(close_time) == n
    return pl.DataFrame({"close": close, "close_time": close_time})


def _trades(n: int, *, price: float = 10.0, quantity: float = 1.0) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "transact_time": list(range(n)),
            "price": [price] * n,
            "quantity": [quantity] * n,
            "is_buyer_maker": [False] * n,
        },
        schema={
            "transact_time": pl.Int64,
            "price": pl.Float64,
            "quantity": pl.Float64,
            "is_buyer_maker": pl.Boolean,
        },
    )


# ============================================================================
# date_chunks
# ============================================================================


def test_date_chunks_fatia_em_janelas_do_tamanho_pedido() -> None:
    chunks = _chunked_scan.date_chunks("2024-01-01", "2024-01-10", chunk_days=3)
    assert chunks == [
        (date(2024, 1, 1), date(2024, 1, 3)),
        (date(2024, 1, 4), date(2024, 1, 6)),
        (date(2024, 1, 7), date(2024, 1, 9)),
        (date(2024, 1, 10), date(2024, 1, 10)),
    ]


def test_date_chunks_chunk_days_invalido_levanta_erro() -> None:
    with pytest.raises(ValueError, match="chunk_days"):
        _chunked_scan.date_chunks("2024-01-01", "2024-01-02", chunk_days=0)


def test_date_chunks_start_apos_end_levanta_erro() -> None:
    with pytest.raises(ValueError, match="posterior"):
        _chunked_scan.date_chunks("2024-01-05", "2024-01-01", chunk_days=1)


# ============================================================================
# TradesTotals / scan_trades_totals
# ============================================================================


def test_scan_trades_totals_soma_por_chunk(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[object, object]] = []

    def _fake_query_agg_trades(
        symbol: str,
        start: object,
        end: object,
        *,
        duckdb_memory_limit_gb: float,
        duckdb_threads: int,
    ) -> pl.DataFrame:
        calls.append((start, end))
        return _trades(2, price=10.0, quantity=1.0)

    monkeypatch.setattr(lake, "query_agg_trades", _fake_query_agg_trades)

    chunks = _chunked_scan.date_chunks("2024-01-01", "2024-01-02", chunk_days=5)
    totals = _chunked_scan.scan_trades_totals("BTCUSDT", "15m", chunks)

    assert len(calls) == 1  # 1 chunk só (5 dias >= janela de 2 dias)
    assert totals.total_dollar == pytest.approx(20.0)  # 2 trades * 10.0 * 1.0
    assert totals.total_volume == pytest.approx(2.0)
    assert totals.n_ticks == 2


def test_scan_trades_totals_chunk_vazio_e_no_op(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lake, "query_agg_trades", lambda *a, **k: pl.DataFrame())
    chunks = _chunked_scan.date_chunks("2024-01-01", "2024-01-01", chunk_days=1)
    totals = _chunked_scan.scan_trades_totals("BTCUSDT", "15m", chunks)
    assert totals.total_dollar == 0.0
    assert totals.total_volume == 0.0
    assert totals.n_ticks == 0


def test_scan_trades_totals_acumula_entre_multiplos_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        lake, "query_agg_trades", lambda *a, **k: _trades(1, price=5.0, quantity=2.0)
    )
    chunks = _chunked_scan.date_chunks("2024-01-01", "2024-01-03", chunk_days=1)  # 3 chunks
    totals = _chunked_scan.scan_trades_totals("BTCUSDT", "15m", chunks)
    assert totals.n_ticks == 3
    assert totals.total_dollar == pytest.approx(3 * 5.0 * 2.0)
    assert totals.total_volume == pytest.approx(3 * 2.0)


# ============================================================================
# query_baseline / target_n_bars
# ============================================================================


def test_query_baseline_delega_para_lake_query_bars(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def _fake_query_bars(
        symbol: str,
        tf: str,
        start: object,
        end: object,
        *,
        source: str,
        cast_prices: bool,
        duckdb_memory_limit_gb: float,
        duckdb_threads: int,
    ) -> pl.DataFrame:
        captured.update(symbol=symbol, tf=tf, start=start, end=end, source=source)
        return _bars(close=[1.0, 2.0], close_time=[0, 1_000])

    monkeypatch.setattr(lake, "query_bars", _fake_query_bars)

    out = _chunked_scan.query_baseline("BTCUSDT", "15m", start="2024-01-01", end="2024-01-02")

    assert captured == {
        "symbol": "BTCUSDT",
        "tf": "15m",
        "start": "2024-01-01",
        "end": "2024-01-02",
        "source": "klines_1m",
    }
    assert out.height == 2


def test_target_n_bars_baseline_vazio_levanta_erro() -> None:
    empty = pl.DataFrame(schema={"close": pl.Float64, "close_time": pl.Int64})
    with pytest.raises(ValueError, match="baseline vazio"):
        _chunked_scan.target_n_bars(
            "BTCUSDT", "15m", empty, start="2024-01-01", end="2024-01-02"
        )


def test_target_n_bars_devolve_altura_do_baseline() -> None:
    baseline = _bars(close=[1.0, 2.0, 3.0], close_time=[0, 1, 2])
    n = _chunked_scan.target_n_bars(
        "BTCUSDT", "15m", baseline, start="2024-01-01", end="2024-01-02"
    )
    assert n == 3


# ============================================================================
# duckdb_throttle
# ============================================================================


def test_duckdb_throttle_le_de_constants_yaml() -> None:
    throttle = _chunked_scan.duckdb_throttle()
    assert throttle.memory_limit_gb > 0
    assert throttle.threads > 0
