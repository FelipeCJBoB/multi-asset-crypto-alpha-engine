"""Testes de src/exchange/filters.py — parsing do snapshot real e resolução
por data (§1.4): MIN_NOTIONAL mudou de 100 -> 50 USDT em 2026-04-14, e um
backtest que resolve "o filtro de hoje" para uma barra antiga usa o número
errado silenciosamente. Estes testes garantem que isso é estruturalmente
impossível."""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from src.exchange.filters import (
    NoFiltersAvailableError,
    SymbolNotFoundError,
    load_filters_asof,
    parse_exchange_info_snapshot,
    write_snapshot_atomic,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REAL_SNAPSHOT_PATH = (
    _REPO_ROOT / "data" / "raw" / "snapshots" / "exchange_info" / "2026-08-08.json"
)


def _load_real_snapshot() -> dict:
    with _REAL_SNAPSHOT_PATH.open(encoding="utf-8") as f:
        return json.load(f)


@pytest.mark.skipif(
    not _REAL_SNAPSHOT_PATH.exists(), reason="snapshot real ainda não presente em data/raw/"
)
def test_parse_snapshot_real_btcusdt() -> None:
    raw = _load_real_snapshot()
    filters = parse_exchange_info_snapshot(raw, symbol="BTCUSDT", snapshot_date=date(2026, 8, 8))

    assert filters.symbol == "BTCUSDT"
    assert filters.status == "TRADING"
    assert filters.tick_size == Decimal("0.10")
    assert filters.step_size == Decimal("0.001")
    assert filters.min_notional == Decimal("50")
    assert filters.min_qty == Decimal("0.001")
    assert filters.price_precision == 2
    assert filters.quantity_precision == 3
    assert filters.is_reconstructed is False


@pytest.mark.skipif(
    not _REAL_SNAPSHOT_PATH.exists(), reason="snapshot real ainda não presente em data/raw/"
)
def test_determinismo_mesmo_input_mesmo_resultado() -> None:
    raw = _load_real_snapshot()
    a = parse_exchange_info_snapshot(raw, symbol="BTCUSDT", snapshot_date=date(2026, 8, 8))
    b = parse_exchange_info_snapshot(raw, symbol="BTCUSDT", snapshot_date=date(2026, 8, 8))
    assert a == b


def test_parse_snapshot_simbolo_ausente_levanta_erro() -> None:
    raw = {"symbols": [{"symbol": "ETHUSDT", "filters": []}]}
    with pytest.raises(SymbolNotFoundError):
        parse_exchange_info_snapshot(raw, symbol="BTCUSDT", snapshot_date=date(2026, 1, 1))


def _make_snapshot_raw(
    *, min_notional: str, step_size: str = "0.001", tick_size: str = "0.10"
) -> dict:
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
                        "tickSize": tick_size,
                        "minPrice": "1",
                        "maxPrice": "1000000",
                    },
                    {
                        "filterType": "LOT_SIZE",
                        "stepSize": step_size,
                        "minQty": "0.001",
                        "maxQty": "1000",
                    },
                    {
                        "filterType": "MARKET_LOT_SIZE",
                        "stepSize": step_size,
                        "minQty": "0.001",
                        "maxQty": "120",
                    },
                    {"filterType": "MIN_NOTIONAL", "notional": min_notional},
                    {"filterType": "MAX_NUM_ORDERS", "limit": 200},
                ],
            }
        ]
    }


def test_load_filters_asof_escolhe_snapshot_mais_recente_anterior_a_t(tmp_path: Path) -> None:
    base_dir = tmp_path / "exchange_info"
    write_snapshot_atomic(_make_snapshot_raw(min_notional="100"), base_dir / "2026-01-01.json")
    write_snapshot_atomic(_make_snapshot_raw(min_notional="50"), base_dir / "2026-04-14.json")
    write_snapshot_atomic(_make_snapshot_raw(min_notional="50"), base_dir / "2026-08-08.json")

    # antes da mudança de MIN_NOTIONAL — deve resolver 100, não 50 (§0.2 R1)
    before = load_filters_asof(datetime(2026, 2, 1), symbol="BTCUSDT", snapshots_dir=base_dir)
    assert before.min_notional == Decimal("100")
    assert before.snapshot_date == date(2026, 1, 1)

    # exatamente no dia da mudança
    on_change = load_filters_asof(datetime(2026, 4, 14), symbol="BTCUSDT", snapshots_dir=base_dir)
    assert on_change.min_notional == Decimal("50")
    assert on_change.snapshot_date == date(2026, 4, 14)

    # bem depois — snapshot mais recente <= t
    later = load_filters_asof(datetime(2026, 12, 25), symbol="BTCUSDT", snapshots_dir=base_dir)
    assert later.snapshot_date == date(2026, 8, 8)


def test_load_filters_asof_sem_snapshot_algum_antes_de_t_levanta_erro(tmp_path: Path) -> None:
    base_dir = tmp_path / "exchange_info"
    write_snapshot_atomic(_make_snapshot_raw(min_notional="50"), base_dir / "2026-08-08.json")

    with pytest.raises(NoFiltersAvailableError):
        load_filters_asof(datetime(2020, 1, 1), symbol="BTCUSDT", snapshots_dir=base_dir)


def test_load_filters_asof_diretorio_vazio_levanta_erro(tmp_path: Path) -> None:
    base_dir = tmp_path / "exchange_info_vazio"
    with pytest.raises(NoFiltersAvailableError):
        load_filters_asof(datetime(2026, 1, 1), symbol="BTCUSDT", snapshots_dir=base_dir)


def test_reconstructed_flag_e_resolucao_antes_da_coleta_forward(tmp_path: Path) -> None:
    base_dir = tmp_path / "exchange_info"
    write_snapshot_atomic(
        _make_snapshot_raw(min_notional="100"), base_dir / "reconstructed" / "2020-01-01.json"
    )

    only_reconstructed = load_filters_asof(
        datetime(2020, 6, 1), symbol="BTCUSDT", snapshots_dir=base_dir
    )
    assert only_reconstructed.is_reconstructed is True
    assert only_reconstructed.snapshot_date == date(2020, 1, 1)


def test_canonico_vence_reconstruido_na_mesma_data(tmp_path: Path) -> None:
    base_dir = tmp_path / "exchange_info"
    write_snapshot_atomic(
        _make_snapshot_raw(min_notional="999"), base_dir / "reconstructed" / "2021-01-01.json"
    )
    write_snapshot_atomic(_make_snapshot_raw(min_notional="100"), base_dir / "2021-01-01.json")

    resolved = load_filters_asof(datetime(2021, 6, 1), symbol="BTCUSDT", snapshots_dir=base_dir)
    assert resolved.is_reconstructed is False
    assert resolved.min_notional == Decimal("100")


def test_floor_to_step_e_min_notional() -> None:
    raw = _make_snapshot_raw(min_notional="50", step_size="0.001")
    filters = parse_exchange_info_snapshot(raw, symbol="BTCUSDT", snapshot_date=date(2026, 1, 1))

    assert filters.floor_to_step(Decimal("0.0037")) == Decimal("0.003")
    assert filters.meets_min_notional(Decimal("0.001"), Decimal("65000")) is True
    assert filters.meets_min_notional(Decimal("0.0001"), Decimal("65000")) is False
