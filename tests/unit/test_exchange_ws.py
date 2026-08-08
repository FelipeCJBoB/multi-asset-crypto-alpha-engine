"""Testes de src/exchange/ws.py — ciclo de vida do listenKey (§16.3): keepalive
no intervalo certo, backoff 1s/2s/4s, watchdog de silêncio, gatilho 14 do kill
switch. Tudo com clock e sleep fakes — nenhum teste espera tempo real nem toca
rede/socket de verdade."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from src.exchange.ws import (
    EventWatchdog,
    ListenKeyLifecycle,
    ReconnectPolicy,
    UserDataStreamClient,
    build_combined_stream_url,
    build_user_data_stream_url,
)


class _FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _lifecycle(
    *,
    clock: _FakeClock,
    keepalive_fn: Callable[[str], None],
    sleeps: list[float] | None = None,
) -> ListenKeyLifecycle:
    return ListenKeyLifecycle(
        create_fn=lambda: "lk-1",
        keepalive_fn=keepalive_fn,
        now_fn=clock,
        sleep_fn=(sleeps.append if sleeps is not None else (lambda _s: None)),
        keepalive_interval_s=1800.0,
        backoff_schedule_s=[1.0, 2.0, 4.0],
        max_retries=3,
        recreate_deadline_s=120.0,
    )


# --------------------------------------------------------------------- URLs


def test_build_combined_stream_url() -> None:
    url = build_combined_stream_url(["btcusdt@kline_15m", "btcusdt@aggTrade"])
    assert url == "wss://fstream.binance.com/stream?streams=btcusdt@kline_15m/btcusdt@aggTrade"


def test_build_combined_stream_url_vazio_levanta_erro() -> None:
    with pytest.raises(ValueError):
        build_combined_stream_url([])


def test_build_user_data_stream_url() -> None:
    assert build_user_data_stream_url("lk-123") == "wss://fstream.binance.com/ws/lk-123"


# ------------------------------------------------------------ ListenKeyLifecycle


def test_due_for_keepalive_respeita_intervalo_de_1800s() -> None:
    clock = _FakeClock()
    lifecycle = _lifecycle(clock=clock, keepalive_fn=lambda _lk: None)
    lifecycle.start()

    assert lifecycle.due_for_keepalive() is False
    clock.advance(1799.0)
    assert lifecycle.due_for_keepalive() is False
    clock.advance(1.0)  # total 1800.0
    assert lifecycle.due_for_keepalive() is True


def test_keepalive_sucesso_reseta_o_relogio() -> None:
    clock = _FakeClock()
    calls: list[str] = []
    lifecycle = _lifecycle(clock=clock, keepalive_fn=calls.append)
    lifecycle.start()
    clock.advance(1800.0)

    assert lifecycle.due_for_keepalive() is True
    assert lifecycle.keepalive() is True
    assert calls == ["lk-1"]
    assert lifecycle.due_for_keepalive() is False


def test_keepalive_falha_aplica_backoff_1_2_4_e_esgota() -> None:
    clock = _FakeClock()
    sleeps: list[float] = []

    def always_fails(_lk: str) -> None:
        raise RuntimeError("network down")

    lifecycle = _lifecycle(clock=clock, keepalive_fn=always_fails, sleeps=sleeps)
    lifecycle.start()

    result = lifecycle.keepalive()

    assert result is False
    assert sleeps == [1.0, 2.0, 4.0]


def test_keepalive_chamado_antes_de_start_levanta_erro() -> None:
    clock = _FakeClock()
    lifecycle = _lifecycle(clock=clock, keepalive_fn=lambda _lk: None)
    with pytest.raises(RuntimeError):
        lifecycle.keepalive()


def test_recreate_deadline_gatilho_14() -> None:
    clock = _FakeClock()

    def always_fails(_lk: str) -> None:
        raise RuntimeError("network down")

    lifecycle = _lifecycle(clock=clock, keepalive_fn=always_fails)
    lifecycle.start()
    lifecycle.keepalive()  # esgota e marca invalid_since

    assert lifecycle.recreate_deadline_breached() is False
    clock.advance(119.0)
    assert lifecycle.recreate_deadline_breached() is False
    clock.advance(1.0)  # total 120.0
    assert lifecycle.recreate_deadline_breached() is True

    lifecycle.recreate()
    assert lifecycle.recreate_deadline_breached() is False


# --------------------------------------------------------------- EventWatchdog


def test_watchdog_ping_sintetico_em_300s_e_trading_halt_em_60s_depois() -> None:
    clock = _FakeClock()
    watchdog = EventWatchdog(now_fn=clock, no_event_timeout_s=300.0, no_response_timeout_s=60.0)
    watchdog.record_event()

    assert watchdog.needs_synthetic_ping() is False
    clock.advance(300.0)
    assert watchdog.needs_synthetic_ping() is True

    watchdog.record_ping_sent()
    assert watchdog.needs_synthetic_ping() is False  # já tem ping pendente, não duplica
    assert watchdog.needs_trading_halt() is False

    clock.advance(60.0)
    assert watchdog.needs_trading_halt() is True


def test_watchdog_evento_novo_cancela_ping_pendente() -> None:
    clock = _FakeClock()
    watchdog = EventWatchdog(now_fn=clock, no_event_timeout_s=300.0, no_response_timeout_s=60.0)
    watchdog.record_event()
    clock.advance(300.0)
    watchdog.record_ping_sent()
    clock.advance(10.0)

    watchdog.record_event()  # chegou evento novo — ping "respondido" implicitamente

    assert watchdog.needs_trading_halt() is False
    assert watchdog.needs_synthetic_ping() is False


# --------------------------------------------------------------- ReconnectPolicy


def test_reconnect_policy_segue_1_2_4_e_satura_no_ultimo() -> None:
    policy = ReconnectPolicy(backoff_schedule_s=[1.0, 2.0, 4.0])
    assert [policy.next_delay_s() for _ in range(5)] == [1.0, 2.0, 4.0, 4.0, 4.0]

    policy.reset()
    assert policy.next_delay_s() == 1.0


# ----------------------------------------------------------- UserDataStreamClient


class _FakeTransport:
    def __init__(self) -> None:
        self.connected_url: str | None = None
        self.messages: list[str] = []
        self.closed = False

    def connect(self, url: str) -> None:
        self.connected_url = url

    def recv(self, timeout: float | None = None) -> str | None:
        return self.messages.pop(0) if self.messages else None

    def send(self, data: str) -> None:  # pragma: no cover - não exercido nestes testes
        raise NotImplementedError

    def close(self) -> None:
        self.closed = True


class _FakeRestClient:
    def __init__(self) -> None:
        self._n = 0
        self.keepalive_calls: list[str] = []

    def create_listen_key(self) -> str:
        self._n += 1
        return f"lk-{self._n}"

    def keepalive_listen_key(self, listen_key: str) -> None:
        self.keepalive_calls.append(listen_key)


def test_user_data_stream_client_connect_e_poll() -> None:
    clock = _FakeClock()
    transport = _FakeTransport()
    rest = _FakeRestClient()

    client = UserDataStreamClient(  # type: ignore[arg-type]
        rest, transport, now_fn=clock, sleep_fn=lambda _s: None
    )
    client.connect()

    assert transport.connected_url == "wss://fstream.binance.com/ws/lk-1"
    assert client.lifecycle.listen_key == "lk-1"

    transport.messages.append('{"e":"ORDER_TRADE_UPDATE"}')
    msg = client.poll_once()
    assert msg == '{"e":"ORDER_TRADE_UPDATE"}'
    assert client.poll_once() is None  # fila de mensagens vazia agora


def test_user_data_stream_client_keepalive_no_intervalo_certo() -> None:
    clock = _FakeClock()
    transport = _FakeTransport()
    rest = _FakeRestClient()

    client = UserDataStreamClient(  # type: ignore[arg-type]
        rest, transport, now_fn=clock, sleep_fn=lambda _s: None
    )
    client.connect()

    client.maybe_keepalive()
    assert rest.keepalive_calls == []  # ainda não venceu o intervalo

    clock.advance(1800.0)
    client.maybe_keepalive()
    assert rest.keepalive_calls == ["lk-1"]


def test_user_data_stream_client_close() -> None:
    transport = _FakeTransport()
    client = UserDataStreamClient(_FakeRestClient(), transport)  # type: ignore[arg-type]
    client.close()
    assert transport.closed is True
