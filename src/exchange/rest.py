"""Cliente REST para Binance USDⓈ-M Futures (`https://fapi.binance.com`) — §9.4,
§9.7, B31, B32.

Três modos de chamada (`Security`):
  - `NONE` — pública, sem credencial (`exchange_info()`, `klines()`, ...).
  - `USER_STREAM` — exige o header `X-MBX-APIKEY` mas NÃO assinatura; é o
    comportamento documentado da Binance especificamente para os endpoints de
    `listenKey`.
  - `SIGNED` — exige `X-MBX-APIKEY` **e** assinatura HMAC-SHA256. A ordem é
    obrigatória (B32, verificado no changelog de 2026-01-15 citado no PRD
    §9.4): a query string é percent-encoded **primeiro**, e a assinatura é
    calculada sobre essa string já codificada — não sobre os parâmetros
    crus. Inverter a ordem produz uma assinatura diferente e a Binance
    responde `-1022 INVALID_SIGNATURE`.

Credenciais vêm de `BINANCE_API_KEY`/`BINANCE_API_SECRET` no ambiente (B31) —
nunca hardcoded, nunca logadas, nunca em mensagem de exceção. Este módulo não
importa `python-dotenv`: carregar `.env` para `os.environ` é responsabilidade
do processo de entrada (`scripts/`, `src/live/runner.py`, testnet, paper),
igual à convenção já estabelecida para `configure_logging()` em
`src/monitoring/logging.py` — a camada mais baixa não deveria decidir como o
ambiente é montado, só lê o resultado.

Toda resposta (pública ou assinada) repassa os headers
`X-MBX-USED-WEIGHT-1M` / `X-MBX-ORDER-COUNT-10S` / `X-MBX-ORDER-COUNT-1M`
para o `RateLimitManager` injetado, se houver um — nunca confiar apenas em
contagem própria (§9.4 regra 1).
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from enum import Enum
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

import requests
import structlog

from ._constants import load_constant

if TYPE_CHECKING:
    from .rate_limit import RateLimitManager

logger = structlog.get_logger(__name__)

DEFAULT_BASE_URL = "https://fapi.binance.com"

_API_KEY_ENV = "BINANCE_API_KEY"
_API_SECRET_ENV = "BINANCE_API_SECRET"


class ExchangeError(Exception):
    """Base para erros da camada exchange."""


class MissingCredentialsError(ExchangeError):
    """`BINANCE_API_KEY`/`BINANCE_API_SECRET` ausentes do ambiente para uma
    chamada que exige autenticação. Nunca crasha genérico, nunca loga o
    valor (mesmo vazio) das variáveis (B31)."""


class BinanceRequestError(ExchangeError):
    """Erro de rede ou resposta de erro HTTP da Binance. A mensagem NUNCA
    inclui a query string de uma chamada assinada — só o path e o status
    (B31/B32: a query pode conter `signature=...`)."""

    def __init__(
        self, message: str, *, status_code: int | None = None, payload: Any = None
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class Security(Enum):
    NONE = "NONE"
    USER_STREAM = "USER_STREAM"
    SIGNED = "SIGNED"


def _get_credentials() -> tuple[str, str]:
    api_key = os.environ.get(_API_KEY_ENV)
    api_secret = os.environ.get(_API_SECRET_ENV)
    if not api_key or not api_secret:
        raise MissingCredentialsError(
            f"{_API_KEY_ENV}/{_API_SECRET_ENV} não configuradas no ambiente — "
            "chamada assinada exige credencial (§16.7, B31)."
        )
    return api_key, api_secret


def _encode_query(params: dict[str, Any]) -> str:
    """Percent-encode determinístico (ordena por chave) — passo 1 de B32."""
    return urlencode(sorted(params.items()), doseq=True)


def sign_query(secret: str, encoded_query: str) -> str:
    """HMAC-SHA256 sobre a query JÁ percent-encoded — passo 2 de B32.

    `encoded_query` precisa já ter passado por `_encode_query` (ou
    equivalente). Assinar a string crua e codificar depois produz uma
    assinatura diferente — é exatamente o erro que B32 proíbe.
    """
    return hmac.new(
        secret.encode("utf-8"), encoded_query.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def _sanitize_for_log(path: str) -> str:
    """Nunca logar/expor a query string de uma chamada assinada — só o path
    (B31: a query pode conter `signature=...`)."""
    return path.split("?", 1)[0]


def _safe_json(response: requests.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


class RestClient:
    """Cliente REST fino sobre `requests`. Não conhece o significado de
    negócio de nenhum endpoint além do necessário para montar a chamada —
    isso é responsabilidade das camadas acima (`adapter.py` neste pacote é a
    primeira)."""

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        session: requests.Session | None = None,
        rate_limiter: RateLimitManager | None = None,
        timeout_s: float | None = None,
        recv_window_ms: int | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._session = session if session is not None else requests.Session()
        self._rate_limiter = rate_limiter
        self._timeout_s = (
            timeout_s if timeout_s is not None else load_constant("rest_request_timeout_s")
        )
        self._recv_window_ms = (
            recv_window_ms if recv_window_ms is not None else load_constant("recv_window_ms")
        )

    # ------------------------------------------------------------------ core

    def _send(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        security: Security = Security.NONE,
    ) -> Any:
        params = dict(params or {})
        headers: dict[str, str] = {}

        if security is Security.SIGNED:
            api_key, api_secret = _get_credentials()
            headers["X-MBX-APIKEY"] = api_key
            params.setdefault("timestamp", int(time.time() * 1000))
            params.setdefault("recvWindow", self._recv_window_ms)
            encoded = _encode_query(params)  # 1) percent-encode
            signature = sign_query(api_secret, encoded)  # 2) assina o já-encoded (B32)
            query = f"{encoded}&signature={signature}"
        elif security is Security.USER_STREAM:
            api_key, _secret = _get_credentials()
            headers["X-MBX-APIKEY"] = api_key
            query = _encode_query(params)
        else:
            query = _encode_query(params)

        url = f"{self._base_url}{path}"
        full_url = f"{url}?{query}" if query else url

        try:
            response = self._session.request(
                method, full_url, headers=headers, timeout=self._timeout_s
            )
        except requests.RequestException as exc:
            logger.error("rest.network_error", method=method, path=path, error=str(exc))
            raise BinanceRequestError(
                f"falha de rede em {method} {_sanitize_for_log(path)}"
            ) from exc

        if self._rate_limiter is not None:
            self._rate_limiter.update_from_headers(response.headers)

        if not response.ok:
            logger.error(
                "rest.error_response", method=method, path=path, status=response.status_code
            )
            raise BinanceRequestError(
                f"{method} {_sanitize_for_log(path)} -> HTTP {response.status_code}",
                status_code=response.status_code,
                payload=_safe_json(response),
            )

        return response.json()

    # ---------------------------------------------------------------- pública

    def ping(self) -> dict[str, Any]:
        result: dict[str, Any] = self._send("GET", "/fapi/v1/ping")
        return result

    def server_time(self) -> int:
        result: dict[str, Any] = self._send("GET", "/fapi/v1/time")
        return int(result["serverTime"])

    def exchange_info(self) -> dict[str, Any]:
        result: dict[str, Any] = self._send("GET", "/fapi/v1/exchangeInfo")
        return result

    def klines(
        self,
        symbol: str,
        interval: str,
        *,
        start_time: int | None = None,
        end_time: int | None = None,
        limit: int = 500,
    ) -> list[list[Any]]:
        params: dict[str, Any] = {"symbol": symbol, "interval": interval, "limit": limit}
        if start_time is not None:
            params["startTime"] = start_time
        if end_time is not None:
            params["endTime"] = end_time
        result: list[list[Any]] = self._send("GET", "/fapi/v1/klines", params=params)
        return result

    # --------------------------------------------------------------- assinada

    def account_info(self) -> dict[str, Any]:
        result: dict[str, Any] = self._send(
            "GET", "/fapi/v2/account", security=Security.SIGNED
        )
        return result

    def position_risk(self, symbol: str | None = None) -> list[dict[str, Any]]:
        params = {"symbol": symbol} if symbol else {}
        result: list[dict[str, Any]] = self._send(
            "GET", "/fapi/v2/positionRisk", params=params, security=Security.SIGNED
        )
        return result

    def open_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        params = {"symbol": symbol} if symbol else {}
        result: list[dict[str, Any]] = self._send(
            "GET", "/fapi/v1/openOrders", params=params, security=Security.SIGNED
        )
        return result

    def query_order(
        self,
        symbol: str,
        *,
        order_id: int | None = None,
        orig_client_order_id: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"symbol": symbol}
        if order_id is not None:
            params["orderId"] = order_id
        if orig_client_order_id is not None:
            params["origClientOrderId"] = orig_client_order_id
        result: dict[str, Any] = self._send(
            "GET", "/fapi/v1/order", params=params, security=Security.SIGNED
        )
        return result

    def cancel_order(
        self,
        symbol: str,
        *,
        order_id: int | None = None,
        orig_client_order_id: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"symbol": symbol}
        if order_id is not None:
            params["orderId"] = order_id
        if orig_client_order_id is not None:
            params["origClientOrderId"] = orig_client_order_id
        result: dict[str, Any] = self._send(
            "DELETE", "/fapi/v1/order", params=params, security=Security.SIGNED
        )
        return result

    # ---------------------------------------------------- user data stream (chave apenas)

    def create_listen_key(self) -> str:
        result: dict[str, Any] = self._send(
            "POST", "/fapi/v1/listenKey", security=Security.USER_STREAM
        )
        return str(result["listenKey"])

    def keepalive_listen_key(self, listen_key: str) -> None:
        self._send(
            "PUT",
            "/fapi/v1/listenKey",
            params={"listenKey": listen_key},
            security=Security.USER_STREAM,
        )

    def close_listen_key(self, listen_key: str) -> None:
        self._send(
            "DELETE",
            "/fapi/v1/listenKey",
            params={"listenKey": listen_key},
            security=Security.USER_STREAM,
        )
