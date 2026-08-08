"""Cliente WebSocket — streams de mercado (público) e User Data Stream
(privado, §16.3, RF-026). Este módulo é a MECÂNICA de conexão/reconexão/
keepalive: ciclo de vida do `listenKey` (criar, renovar, backoff, watchdog) e
construção de URL de stream.

Parsing de mensagem por tipo (kline, aggTrade, ORDER_TRADE_UPDATE, ...) é
Sprint 3+, quando os consumidores existirem — este módulo não assume nenhum
shape de payload de mercado.

Testável sem rede real e sem sleep real: toda função de tempo (`now_fn`) e de
espera (`sleep_fn`) é injetável, e o transporte de socket é uma interface
(`WebSocketTransport`) injetada — os testes usam um fake, não um socket de
verdade. Nenhuma biblioteca de WebSocket está no `pyproject.toml` ainda; o
Sprint 2 não precisa de uma real — só a mecânica de ciclo de vida, isolada.
Quando o Sprint 3 escolher uma implementação de transporte (`websockets` é a
candidata óbvia), ela entra como adapter de `WebSocketTransport`, sem tocar
nesta lógica.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

import structlog

from ._constants import load_constant

if TYPE_CHECKING:
    from .rest import RestClient

logger = structlog.get_logger(__name__)

MARKET_STREAM_BASE_URL = "wss://fstream.binance.com"
USER_DATA_STREAM_BASE_URL = "wss://fstream.binance.com"


class WebSocketTransport(Protocol):
    """Interface mínima de transporte — implementação real é Sprint 3+. Testes
    injetam um fake que implementa este protocolo."""

    def connect(self, url: str) -> None: ...

    def recv(self, timeout: float | None = None) -> str | None: ...

    def send(self, data: str) -> None: ...

    def close(self) -> None: ...


def build_combined_stream_url(streams: list[str], *, base_url: str = MARKET_STREAM_BASE_URL) -> str:
    """`wss://fstream.binance.com/stream?streams=a/b/c` — múltiplos streams
    públicos de mercado num socket só."""
    if not streams:
        raise ValueError("build_combined_stream_url exige ao menos 1 stream")
    return f"{base_url}/stream?streams={'/'.join(streams)}"


def build_user_data_stream_url(
    listen_key: str, *, base_url: str = USER_DATA_STREAM_BASE_URL
) -> str:
    return f"{base_url}/ws/{listen_key}"


class ListenKeyLifecycle:
    """Máquina de estados pura do ciclo de vida do `listenKey` (§16.3, RF-026).

    `create_fn`/`keepalive_fn` são injetados (tipicamente
    `RestClient.create_listen_key` / `RestClient.keepalive_listen_key`) — esta
    classe não conhece HTTP. `now_fn`/`sleep_fn` são injetáveis para testes
    determinísticos, sem esperar 1800s nem 1s/2s/4s de verdade.
    """

    def __init__(
        self,
        *,
        create_fn: Callable[[], str],
        keepalive_fn: Callable[[str], None],
        now_fn: Callable[[], float] = time.monotonic,
        sleep_fn: Callable[[float], None] = time.sleep,
        keepalive_interval_s: float | None = None,
        backoff_schedule_s: list[float] | None = None,
        max_retries: int | None = None,
        recreate_deadline_s: float | None = None,
    ) -> None:
        self._create_fn = create_fn
        self._keepalive_fn = keepalive_fn
        self._now_fn = now_fn
        self._sleep_fn = sleep_fn

        self.keepalive_interval_s = (
            keepalive_interval_s
            if keepalive_interval_s is not None
            else load_constant("listen_key_keepalive_interval_s")
        )
        self.backoff_schedule_s = (
            list(backoff_schedule_s)
            if backoff_schedule_s is not None
            else list(load_constant("listen_key_keepalive_backoff_s"))
        )
        self.max_retries = (
            max_retries
            if max_retries is not None
            else load_constant("listen_key_keepalive_max_retries")
        )
        self.recreate_deadline_s = (
            recreate_deadline_s
            if recreate_deadline_s is not None
            else load_constant("listen_key_recreate_deadline_s")
        )

        self.listen_key: str | None = None
        self._last_keepalive_at: float | None = None
        self._invalid_since: float | None = None

    def start(self) -> str:
        self.listen_key = self._create_fn()
        self._last_keepalive_at = self._now_fn()
        self._invalid_since = None
        logger.info("listen_key.created")
        return self.listen_key

    def due_for_keepalive(self) -> bool:
        if self.listen_key is None or self._last_keepalive_at is None:
            return False
        return (self._now_fn() - self._last_keepalive_at) >= self.keepalive_interval_s

    def keepalive(self) -> bool:
        """Tenta renovar, com retry conforme `backoff_schedule_s` (§16.3: 3x,
        1s/2s/4s). Retorna `True` se renovou; `False` se esgotou as
        tentativas — o chamador deve então `recreate()` e forçar reconciliação
        completa (fora do escopo desta classe, que só sabe sobre o
        `listenKey`)."""
        if self.listen_key is None:
            raise RuntimeError("keepalive() chamado antes de start() — listenKey inexistente")

        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                self._keepalive_fn(self.listen_key)
                self._last_keepalive_at = self._now_fn()
                self._invalid_since = None
                logger.info("listen_key.keepalive_ok", attempt=attempt)
                return True
            except Exception as exc:  # qualquer falha de rede/API conta como tentativa consumida
                last_exc = exc
                logger.warning("listen_key.keepalive_failed", attempt=attempt, error=str(exc))
                if attempt < len(self.backoff_schedule_s):
                    self._sleep_fn(self.backoff_schedule_s[attempt])

        if self._invalid_since is None:
            self._invalid_since = self._now_fn()
        logger.error(
            "listen_key.keepalive_exhausted", retries=self.max_retries, error=str(last_exc)
        )
        return False

    def recreate(self) -> str:
        """Chamado após `keepalive()` esgotar tentativas."""
        self.listen_key = self._create_fn()
        self._last_keepalive_at = self._now_fn()
        self._invalid_since = None
        logger.warning("listen_key.recreated")
        return self.listen_key

    def seconds_since_invalid(self) -> float | None:
        if self._invalid_since is None:
            return None
        return self._now_fn() - self._invalid_since

    def recreate_deadline_breached(self) -> bool:
        """Kill switch gatilho 14 (§16.3): `listenKey` inválido e não
        recriado em `recreate_deadline_s` (120s)."""
        elapsed = self.seconds_since_invalid()
        return elapsed is not None and elapsed >= self.recreate_deadline_s


class EventWatchdog:
    """Watchdog de silêncio do stream (§16.3): sem evento por
    `no_event_timeout_s` (300s) dispara ping sintético; sem resposta ao ping
    por `no_response_timeout_s` (60s) dispara `TRADING_HALT`. Esta classe não
    sabe o que É um "ping sintético" de verdade (consulta de posição, por
    exemplo) — só marca quando é hora de o chamador disparar um."""

    def __init__(
        self,
        *,
        now_fn: Callable[[], float] = time.monotonic,
        no_event_timeout_s: float | None = None,
        no_response_timeout_s: float | None = None,
    ) -> None:
        self._now_fn = now_fn
        self.no_event_timeout_s = (
            no_event_timeout_s
            if no_event_timeout_s is not None
            else load_constant("ws_watchdog_no_event_timeout_s")
        )
        self.no_response_timeout_s = (
            no_response_timeout_s
            if no_response_timeout_s is not None
            else load_constant("ws_watchdog_no_response_timeout_s")
        )
        self._last_event_at: float | None = None
        self._ping_sent_at: float | None = None

    def record_event(self) -> None:
        """Chamado a cada mensagem recebida do stream — reseta o relógio de
        silêncio e limpa qualquer ping pendente (a chegada de QUALQUER evento
        prova que o socket está vivo)."""
        self._last_event_at = self._now_fn()
        self._ping_sent_at = None

    def needs_synthetic_ping(self) -> bool:
        if self._last_event_at is None or self._ping_sent_at is not None:
            return False
        return (self._now_fn() - self._last_event_at) >= self.no_event_timeout_s

    def record_ping_sent(self) -> None:
        self._ping_sent_at = self._now_fn()

    def needs_trading_halt(self) -> bool:
        if self._ping_sent_at is None:
            return False
        return (self._now_fn() - self._ping_sent_at) >= self.no_response_timeout_s


@dataclass
class ReconnectPolicy:
    """Backoff de reconexão de socket — mesma cadência declarada em §16.3
    para o keepalive (1s/2s/4s), reaproveitada para o transporte de baixo
    nível quando a conexão cai por outro motivo que não falha de keepalive."""

    backoff_schedule_s: list[float] = field(
        default_factory=lambda: list(load_constant("listen_key_keepalive_backoff_s"))
    )
    _attempt: int = field(default=0, init=False)

    def next_delay_s(self) -> float:
        idx = min(self._attempt, len(self.backoff_schedule_s) - 1)
        delay = self.backoff_schedule_s[idx]
        self._attempt += 1
        return delay

    def reset(self) -> None:
        self._attempt = 0


class UserDataStreamClient:
    """Orquestra o ciclo de vida completo do User Data Stream: cria/renova o
    `listenKey` via `RestClient`, mantém o watchdog de silêncio, e delega I/O
    de socket para um `WebSocketTransport` injetado. O laço de evento real
    (async ou thread) é Sprint 3+ — aqui os "passos" são métodos testáveis
    individualmente, não um `run_forever()` opaco."""

    def __init__(
        self,
        rest_client: RestClient,
        transport: WebSocketTransport,
        *,
        now_fn: Callable[[], float] = time.monotonic,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self._rest = rest_client
        self._transport = transport
        self.lifecycle = ListenKeyLifecycle(
            create_fn=rest_client.create_listen_key,
            keepalive_fn=rest_client.keepalive_listen_key,
            now_fn=now_fn,
            sleep_fn=sleep_fn,
        )
        self.watchdog = EventWatchdog(now_fn=now_fn)
        self.reconnect_policy = ReconnectPolicy()

    def connect(self) -> None:
        listen_key = self.lifecycle.start()
        self._transport.connect(build_user_data_stream_url(listen_key))
        self.reconnect_policy.reset()
        self.watchdog.record_event()  # conexão bem-sucedida conta como evento inicial

    def poll_once(self, *, timeout: float | None = None) -> str | None:
        """Um passo do laço de evento: lê uma mensagem (se houver) e atualiza
        o watchdog. Renovação de listenKey e verificação de watchdog ficam em
        métodos separados (`maybe_keepalive`), para que cada mecanismo seja
        testável isoladamente."""
        message = self._transport.recv(timeout=timeout)
        if message is not None:
            self.watchdog.record_event()
        return message

    def maybe_keepalive(self) -> None:
        if not self.lifecycle.due_for_keepalive():
            return
        if not self.lifecycle.keepalive():
            self.lifecycle.recreate()

    def close(self) -> None:
        self._transport.close()
