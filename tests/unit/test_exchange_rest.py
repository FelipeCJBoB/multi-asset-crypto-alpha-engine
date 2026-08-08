"""Testes de src/exchange/rest.py — assinatura HMAC (B32) e MissingCredentialsError
(B31). Nenhum destes testes faz rede real: a assinatura é verificada contra um
vetor determinístico calculado independentemente com `hmac`/`hashlib`, e as
chamadas de `_send` usam uma sessão fake em memória."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

import hashlib
import hmac

import pytest

from src.exchange.rate_limit import RateLimitManager
from src.exchange.rest import (
    BinanceRequestError,
    MissingCredentialsError,
    RestClient,
    sign_query,
)

# ---------------------------------------------------------------------------
# Vetor determinístico: secret e params fixos, digest calculado
# independentemente (hmac.new + hashlib.sha256, fora do código sob teste) e
# fixado como constante abaixo. Qualquer regressão na ordem "percent-encode
# ANTES de assinar" (B32) quebra este teste.
# ---------------------------------------------------------------------------
_SECRET = "unit_test_secret_never_real_ABC123"
_PARAMS: dict[str, Any] = {
    "symbol": "BTCUSDT",
    "side": "BUY",
    "type": "LIMIT",
    "quantity": "0.001",
    "price": "65000.10",
    "recvWindow": 5000,
    "timestamp": 1700000000000,
    "note": "hello world#1",  # espaço + '#' força percent-encoding de verdade
}
_EXPECTED_ENCODED_QUERY = (
    "note=hello+world%231&price=65000.10&quantity=0.001&recvWindow=5000"
    "&side=BUY&symbol=BTCUSDT&timestamp=1700000000000&type=LIMIT"
)
_EXPECTED_SIGNATURE = "2c9b283cb339e814e7d23bc847bc7405fe09dd3d028c5145de5a59112f33e47c"


def test_percent_encode_produz_a_query_esperada() -> None:
    encoded = urlencode(sorted(_PARAMS.items()), doseq=True)
    assert encoded == _EXPECTED_ENCODED_QUERY


def test_sign_query_bate_com_vetor_conhecido() -> None:
    encoded = urlencode(sorted(_PARAMS.items()), doseq=True)
    assert sign_query(_SECRET, encoded) == _EXPECTED_SIGNATURE


def test_assinar_string_nao_encoded_produz_assinatura_diferente() -> None:
    """B32: se a ordem for invertida (assinar antes de percent-encode), a
    Binance responde -1022 INVALID_SIGNATURE. Este teste prova que a ordem
    realmente muda o resultado — não é um detalhe cosmético."""
    naive = "&".join(f"{k}={v}" for k, v in sorted(_PARAMS.items()))
    naive_signature = hmac.new(_SECRET.encode(), naive.encode(), hashlib.sha256).hexdigest()
    assert naive_signature != _EXPECTED_SIGNATURE


# ---------------------------------------------------------------------------
# MissingCredentialsError
# ---------------------------------------------------------------------------


def test_chamada_assinada_sem_credencial_levanta_missing_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BINANCE_API_KEY", raising=False)
    monkeypatch.delenv("BINANCE_API_SECRET", raising=False)
    client = RestClient()
    with pytest.raises(MissingCredentialsError) as exc_info:
        client.account_info()
    message = str(exc_info.value)
    assert "BINANCE_API_KEY" in message
    assert "BINANCE_API_SECRET" in message


def test_chamada_user_stream_sem_credencial_tambem_levanta(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BINANCE_API_KEY", raising=False)
    monkeypatch.delenv("BINANCE_API_SECRET", raising=False)
    client = RestClient()
    with pytest.raises(MissingCredentialsError):
        client.create_listen_key()


# ---------------------------------------------------------------------------
# _send: sessão fake, sem rede real
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        json_data: Any = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self._json_data = json_data if json_data is not None else {}
        self.headers = headers or {}

    def json(self) -> Any:
        return self._json_data


class _FakeSession:
    def __init__(self, response: _FakeResponse) -> None:
        self.response = response
        self.last_request: dict[str, Any] | None = None

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> _FakeResponse:
        self.last_request = {"method": method, "url": url, "headers": headers, "timeout": timeout}
        return self.response


def test_chamada_publica_nao_exige_credencial_e_nao_manda_apikey() -> None:
    fake_session = _FakeSession(_FakeResponse(json_data={"serverTime": 123}))
    client = RestClient(session=fake_session)  # type: ignore[arg-type]

    result = client.server_time()

    assert result == 123
    assert fake_session.last_request is not None
    headers = fake_session.last_request["headers"] or {}
    assert "X-MBX-APIKEY" not in headers


def test_headers_de_rate_limit_sao_repassados_ao_manager() -> None:
    headers = {"X-MBX-USED-WEIGHT-1M": "7"}
    fake_session = _FakeSession(_FakeResponse(json_data={}, headers=headers))
    limiter = RateLimitManager(
        ip_weight_limit=100, order_count_limit_10s=10, order_count_limit_1m=50, reserve_pct=0.30
    )
    client = RestClient(session=fake_session, rate_limiter=limiter)  # type: ignore[arg-type]

    client.exchange_info()

    assert limiter.ip_weight.used == 7


def test_chamada_assinada_monta_signature_e_excecao_nao_vaza_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BINANCE_API_KEY", "fake-key-not-real")
    monkeypatch.setenv("BINANCE_API_SECRET", "fake-secret-not-real")
    error_body = {"code": -1022, "msg": "Signature for this request is not valid."}
    fake_session = _FakeSession(_FakeResponse(status_code=400, json_data=error_body))
    client = RestClient(session=fake_session)  # type: ignore[arg-type]

    with pytest.raises(BinanceRequestError) as exc_info:
        client.account_info()

    message = str(exc_info.value)
    assert "signature=" not in message
    assert "fake-secret-not-real" not in message

    # a request de fato enviada TEM assinatura — senão o teste anterior não provaria nada
    assert fake_session.last_request is not None
    assert "signature=" in fake_session.last_request["url"]
    assert "fake-secret-not-real" not in fake_session.last_request["url"]
