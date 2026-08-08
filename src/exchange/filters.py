"""Filtros de instrumento versionados por data (§1.4).

`MIN_NOTIONAL` mudou de 100 -> 50 USDT em 2026-04-14 (§0.2 R1) — é a restrição
dominante do projeto inteiro. Um backtest que resolve "o filtro de hoje" para
uma barra de 2026-01-01 usa o número errado silenciosamente (B01). Por isso
`load_filters_asof(t)` existe e `load_filters_current()` não: o único jeito de
obter um `Filters` neste módulo é declarando a data.

Snapshots canônicos (coletados forward, dia a dia) ficam em
`data/raw/snapshots/exchange_info/{yyyy-mm-dd}.json` — schema real de
`GET /fapi/v1/exchangeInfo`, verificado contra o snapshot capturado em
2026-08-08. Para o período anterior ao início da coleta forward, snapshots
*reconstruídos* por anúncio da Binance ficam em
`data/raw/snapshots/exchange_info/reconstructed/{yyyy-mm-dd}.json`, com
`is_reconstructed=True` no `Filters` resolvido — o mecanismo existe mesmo que
a lista de reconstruções esteja vazia por enquanto.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_FLOOR, Decimal
from pathlib import Path
from typing import Any

import orjson
import structlog

from ._paths import DEFAULT_SNAPSHOTS_DIR

logger = structlog.get_logger(__name__)

_SNAPSHOT_FILENAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.json$")
_RECONSTRUCTED_DIRNAME = "reconstructed"


class FiltersError(Exception):
    """Base para erros de resolução/parsing de filtros de instrumento."""


class NoFiltersAvailableError(FiltersError):
    """Nenhum snapshot (canônico ou reconstruído) disponível na ou antes da
    data pedida. Cair silenciosamente para o snapshot mais antigo disponível
    reintroduziria exatamente o vazamento temporal que `load_filters_asof`
    existe para prevenir (B01) — por isso isto é um erro, não um fallback."""


class SymbolNotFoundError(FiltersError):
    """Símbolo ausente no snapshot resolvido."""


@dataclass(frozen=True, slots=True)
class Filters:
    """Filtros de instrumento vigentes numa data — subconjunto de
    `exchangeInfo` relevante para quantização (§0.2 R1) e validação de ordem."""

    symbol: str
    snapshot_date: date
    is_reconstructed: bool

    status: str
    tick_size: Decimal
    min_price: Decimal
    max_price: Decimal
    step_size: Decimal
    min_qty: Decimal
    max_qty: Decimal
    market_step_size: Decimal
    market_min_qty: Decimal
    market_max_qty: Decimal
    min_notional: Decimal
    max_num_orders: int
    price_precision: int
    quantity_precision: int
    multiplier_up: Decimal
    multiplier_down: Decimal

    def floor_to_step(self, quantity: Decimal) -> Decimal:
        """Arredonda `quantity` para baixo no múltiplo de `step_size` — a
        mecânica de quantização de R1. A decisão de *quanto* arriscar é de
        `risk/`; isto só garante que o resultado é um múltiplo válido de lote."""
        if self.step_size == 0:
            return quantity
        steps = (quantity / self.step_size).to_integral_value(rounding=ROUND_FLOOR)
        return steps * self.step_size

    def meets_min_notional(self, quantity: Decimal, price: Decimal) -> bool:
        return quantity * price >= self.min_notional


def _read_json(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    data: dict[str, Any] = orjson.loads(raw)
    return data


def _parse_decimal(value: Any, *, default: str = "0") -> Decimal:
    return Decimal(str(value)) if value is not None else Decimal(default)


def parse_exchange_info_snapshot(
    raw: dict[str, Any],
    *,
    symbol: str,
    snapshot_date: date,
    is_reconstructed: bool = False,
) -> Filters:
    """Extrai os filtros de `symbol` de um payload bruto de
    `GET /fapi/v1/exchangeInfo` — schema verificado contra
    `data/raw/snapshots/exchange_info/2026-08-08.json` (dado real, não
    inventado). Determinístico: mesmo `raw` produz sempre o mesmo `Filters`."""
    symbols = raw.get("symbols", [])
    entry = next((s for s in symbols if s.get("symbol") == symbol), None)
    if entry is None:
        raise SymbolNotFoundError(
            f"símbolo '{symbol}' não encontrado no snapshot de {snapshot_date.isoformat()}"
        )

    by_type: dict[str, dict[str, Any]] = {f["filterType"]: f for f in entry.get("filters", [])}

    price_filter = by_type.get("PRICE_FILTER", {})
    lot_size = by_type.get("LOT_SIZE", {})
    market_lot_size = by_type.get("MARKET_LOT_SIZE", {})
    min_notional_filter = by_type.get("MIN_NOTIONAL", {})
    max_orders_filter = by_type.get("MAX_NUM_ORDERS", {})
    percent_price = by_type.get("PERCENT_PRICE", {})

    return Filters(
        symbol=symbol,
        snapshot_date=snapshot_date,
        is_reconstructed=is_reconstructed,
        status=str(entry.get("status", "UNKNOWN")),
        tick_size=_parse_decimal(price_filter.get("tickSize")),
        min_price=_parse_decimal(price_filter.get("minPrice")),
        max_price=_parse_decimal(price_filter.get("maxPrice")),
        step_size=_parse_decimal(lot_size.get("stepSize")),
        min_qty=_parse_decimal(lot_size.get("minQty")),
        max_qty=_parse_decimal(lot_size.get("maxQty")),
        market_step_size=_parse_decimal(market_lot_size.get("stepSize")),
        market_min_qty=_parse_decimal(market_lot_size.get("minQty")),
        market_max_qty=_parse_decimal(market_lot_size.get("maxQty")),
        min_notional=_parse_decimal(min_notional_filter.get("notional")),
        max_num_orders=int(max_orders_filter.get("limit", 0)),
        price_precision=int(entry.get("pricePrecision", 0)),
        quantity_precision=int(entry.get("quantityPrecision", 0)),
        multiplier_up=_parse_decimal(percent_price.get("multiplierUp"), default="1"),
        multiplier_down=_parse_decimal(percent_price.get("multiplierDown"), default="1"),
    )


@dataclass(frozen=True, slots=True)
class _SnapshotRef:
    snapshot_date: date
    path: Path
    is_reconstructed: bool


def _list_snapshots(base_dir: Path) -> list[_SnapshotRef]:
    refs: list[_SnapshotRef] = []
    if base_dir.is_dir():
        for p in base_dir.iterdir():
            m = _SNAPSHOT_FILENAME_RE.match(p.name)
            if p.is_file() and m:
                refs.append(_SnapshotRef(date.fromisoformat(m.group(1)), p, is_reconstructed=False))

    reconstructed_dir = base_dir / _RECONSTRUCTED_DIRNAME
    if reconstructed_dir.is_dir():
        for p in reconstructed_dir.iterdir():
            m = _SNAPSHOT_FILENAME_RE.match(p.name)
            if p.is_file() and m:
                refs.append(_SnapshotRef(date.fromisoformat(m.group(1)), p, is_reconstructed=True))

    return refs


def load_filters_asof(
    t: datetime | date,
    *,
    symbol: str = "BTCUSDT",
    snapshots_dir: Path | None = None,
) -> Filters:
    """Resolve o filtro vigente NA DATA `t` — nunca "o de hoje" (§1.4).

    Usa o snapshot mais recente com `snapshot_date <= t` (canônico ou
    reconstruído; canônico vence em caso de empate na mesma data, porque dado
    real > reconstrução). Se nada cobrir `t`, levanta `NoFiltersAvailableError`.
    """
    base_dir = snapshots_dir if snapshots_dir is not None else DEFAULT_SNAPSHOTS_DIR
    t_date = t.date() if isinstance(t, datetime) else t

    candidates = [c for c in _list_snapshots(base_dir) if c.snapshot_date <= t_date]
    if not candidates:
        raise NoFiltersAvailableError(
            f"nenhum snapshot de exchangeInfo (canônico ou reconstruído) em ou antes de "
            f"{t_date.isoformat()} para {symbol!r} em {base_dir}"
        )

    chosen = max(candidates, key=lambda c: (c.snapshot_date, not c.is_reconstructed))

    raw = _read_json(chosen.path)
    filters = parse_exchange_info_snapshot(
        raw,
        symbol=symbol,
        snapshot_date=chosen.snapshot_date,
        is_reconstructed=chosen.is_reconstructed,
    )
    logger.debug(
        "filters.resolved",
        symbol=symbol,
        requested_date=t_date.isoformat(),
        snapshot_date=chosen.snapshot_date.isoformat(),
        is_reconstructed=chosen.is_reconstructed,
    )
    return filters


def write_snapshot_atomic(raw: dict[str, Any], dest_path: Path) -> None:
    """Escrita atômica de snapshot: `.tmp` -> `fsync` -> `rename` (B29)."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest_path.with_name(dest_path.name + ".tmp")
    payload = orjson.dumps(raw, option=orjson.OPT_INDENT_2)
    with tmp_path.open("wb") as fh:
        fh.write(payload)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, dest_path)
