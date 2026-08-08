"""Interface unificadora que o resto do sistema chama (§13.3): venue único é
risco — uma segunda implementação (testnet, outra exchange) deve ser
plugável trocando só `BinanceFuturesAdapter` por outra subclasse de
`ExchangeAdapter`, sem tocar em nenhuma camada acima de `exchange/`.

`place_order` aqui é CONTRATO, não implementação: execução real de ordem
(máquina de estados §9.2, SL sempre antes de TP §16.2, idempotência de
`client_order_id` §9.7) é Sprint 13. As demais operações (leitura de
filtros/klines, consulta/cancelamento de ordem, posição, conta) já são
chamadas REST reais — não há máquina de estados de execução envolvida nelas.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from .filters import Filters, load_filters_asof
from .rate_limit import RateLimitManager
from .rest import RestClient


class ExchangeAdapter(ABC):
    """Contrato que `data/`, `risk/`, `execution/`, `live/` etc. chamam —
    nunca `rest.py`/`ws.py` diretamente. Isola o resto do sistema de qual
    venue/API concreta está por trás (§13.3)."""

    @abstractmethod
    def get_filters(self, t: datetime, *, symbol: str = "BTCUSDT") -> Filters: ...

    @abstractmethod
    def get_klines(
        self,
        symbol: str,
        interval: str,
        *,
        start_time: int | None = None,
        end_time: int | None = None,
        limit: int = 500,
    ) -> list[list[Any]]: ...

    @abstractmethod
    def get_account_info(self) -> dict[str, Any]: ...

    @abstractmethod
    def get_position_risk(self, symbol: str | None = None) -> list[dict[str, Any]]: ...

    @abstractmethod
    def get_open_orders(self, symbol: str | None = None) -> list[dict[str, Any]]: ...

    @abstractmethod
    def query_order(
        self, symbol: str, *, order_id: int | None = None, orig_client_order_id: str | None = None
    ) -> dict[str, Any]: ...

    @abstractmethod
    def cancel_order(
        self, symbol: str, *, order_id: int | None = None, orig_client_order_id: str | None = None
    ) -> dict[str, Any]: ...

    @abstractmethod
    def place_order(
        self,
        *,
        symbol: str,
        side: str,
        order_type: str,
        quantity: Decimal,
        price: Decimal | None = None,
        time_in_force: str = "GTX",
        reduce_only: bool = False,
        client_order_id: str | None = None,
    ) -> dict[str, Any]:
        """Contrato de envio de ordem (§9.1, §9.7). A implementação real —
        máquina de estados de ordem (§9.2), invariantes de execução (§9.7: SL
        antes de TP, `client_order_id` idempotente, nenhuma ordem nova com
        outra em `UNKNOWN`) — é Sprint 13."""
        ...


class BinanceFuturesAdapter(ExchangeAdapter):
    """Implementação de referência sobre Binance USDⓈ-M Futures."""

    def __init__(
        self,
        *,
        rest_client: RestClient | None = None,
        rate_limiter: RateLimitManager | None = None,
        snapshots_dir: Path | None = None,
    ) -> None:
        self._rate_limiter = rate_limiter if rate_limiter is not None else RateLimitManager()
        self._rest = (
            rest_client if rest_client is not None else RestClient(rate_limiter=self._rate_limiter)
        )
        self._snapshots_dir = snapshots_dir

    def get_filters(self, t: datetime, *, symbol: str = "BTCUSDT") -> Filters:
        return load_filters_asof(t, symbol=symbol, snapshots_dir=self._snapshots_dir)

    def get_klines(
        self,
        symbol: str,
        interval: str,
        *,
        start_time: int | None = None,
        end_time: int | None = None,
        limit: int = 500,
    ) -> list[list[Any]]:
        return self._rest.klines(
            symbol, interval, start_time=start_time, end_time=end_time, limit=limit
        )

    def get_account_info(self) -> dict[str, Any]:
        return self._rest.account_info()

    def get_position_risk(self, symbol: str | None = None) -> list[dict[str, Any]]:
        return self._rest.position_risk(symbol)

    def get_open_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        return self._rest.open_orders(symbol)

    def query_order(
        self,
        symbol: str,
        *,
        order_id: int | None = None,
        orig_client_order_id: str | None = None,
    ) -> dict[str, Any]:
        return self._rest.query_order(
            symbol, order_id=order_id, orig_client_order_id=orig_client_order_id
        )

    def cancel_order(
        self,
        symbol: str,
        *,
        order_id: int | None = None,
        orig_client_order_id: str | None = None,
    ) -> dict[str, Any]:
        return self._rest.cancel_order(
            symbol, order_id=order_id, orig_client_order_id=orig_client_order_id
        )

    def place_order(
        self,
        *,
        symbol: str,
        side: str,
        order_type: str,
        quantity: Decimal,
        price: Decimal | None = None,
        time_in_force: str = "GTX",
        reduce_only: bool = False,
        client_order_id: str | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError(
            "place_order é contrato, não implementação — execução real de ordem "
            "(máquina de estados §9.2, SL antes de TP §16.2, idempotência de "
            "client_order_id §9.7) é Sprint 13."
        )
