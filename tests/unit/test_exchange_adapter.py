"""Testes de src/exchange/adapter.py — contrato do ExchangeAdapter e stub de
place_order (execução real de ordem é Sprint 13, §13.3)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from src.exchange.adapter import BinanceFuturesAdapter, ExchangeAdapter
from src.exchange.filters import write_snapshot_atomic


def _make_snapshot_raw() -> dict:
    return {
        "symbols": [
            {
                "symbol": "BTCUSDT",
                "status": "TRADING",
                "pricePrecision": 2,
                "quantityPrecision": 3,
                "filters": [
                    {
                        "filterType": "PRICE_FILTER",
                        "tickSize": "0.10",
                        "minPrice": "1",
                        "maxPrice": "1000000",
                    },
                    {
                        "filterType": "LOT_SIZE",
                        "stepSize": "0.001",
                        "minQty": "0.001",
                        "maxQty": "1000",
                    },
                    {"filterType": "MIN_NOTIONAL", "notional": "50"},
                ],
            }
        ]
    }


def test_binance_futures_adapter_e_um_exchange_adapter() -> None:
    assert issubclass(BinanceFuturesAdapter, ExchangeAdapter)


def test_get_filters_delega_para_load_filters_asof(tmp_path: Path) -> None:
    base_dir = tmp_path / "exchange_info"
    write_snapshot_atomic(_make_snapshot_raw(), base_dir / "2026-01-01.json")
    adapter = BinanceFuturesAdapter(snapshots_dir=base_dir)

    filters = adapter.get_filters(datetime(2026, 6, 1), symbol="BTCUSDT")

    assert filters.min_notional == Decimal("50")
    assert filters.symbol == "BTCUSDT"


def test_place_order_e_apenas_contrato_por_enquanto() -> None:
    adapter = BinanceFuturesAdapter()
    with pytest.raises(NotImplementedError):
        adapter.place_order(
            symbol="BTCUSDT",
            side="BUY",
            order_type="LIMIT",
            quantity=Decimal("0.001"),
            price=Decimal("65000"),
        )
