"""Rate Limit / Weight Budget Manager (§9.4).

Peso de IP e contagem de ordens são orçamentos **independentes** — a Binance
pune os dois separadamente (regra 2). Ambos reservam `rate_limit_reserve_pct`
do teto exclusivamente para chamadas de execução (P0/P1); pesquisa/backfill
(P2/P3) nunca consome a reserva, mesmo sobrando orçamento bruto.

A fonte de verdade do peso usado é sempre o header devolvido pela Binance
(`update_from_headers`, chamado por `rest.py` em CADA resposta) — nunca a
contagem própria (regra 1). `Budget.reserve()` faz uma reserva otimista local
só para decidir ordem de fila entre um header e o próximo; ela é sempre
sobrescrita pelo próximo valor real.
"""

from __future__ import annotations

import itertools
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import IntEnum

import structlog

from ._constants import load_constant

logger = structlog.get_logger(__name__)

_HEADER_IP_WEIGHT_1M = "X-MBX-USED-WEIGHT-1M"
_HEADER_ORDER_COUNT_10S = "X-MBX-ORDER-COUNT-10S"
_HEADER_ORDER_COUNT_1M = "X-MBX-ORDER-COUNT-1M"


class Priority(IntEnum):
    """Ordem de prioridade da fila (§9.4) — valor menor = mais prioritário."""

    P0 = 0  # cancel_order, reconcile, close_position
    P1 = 1  # create_order, query_order
    P2 = 2  # account_info, position_risk
    P3 = 3  # backfill, research


CALL_TYPE_PRIORITY: dict[str, Priority] = {
    "cancel_order": Priority.P0,
    "reconcile": Priority.P0,
    "close_position": Priority.P0,
    "create_order": Priority.P1,
    "query_order": Priority.P1,
    "account_info": Priority.P2,
    "position_risk": Priority.P2,
    "backfill": Priority.P3,
    "research": Priority.P3,
}

# Chamadas que também contam contra o orçamento de ORDER COUNT (10s e 1m),
# além do peso de IP — só ações que criam/cancelam ordem na Binance de fato.
# `close_position` é implementada, na Binance, como uma create_order reduce-only.
ORDER_COUNTING_CALL_TYPES: frozenset[str] = frozenset(
    {"create_order", "cancel_order", "close_position"}
)

_EXECUTION_PRIORITIES: frozenset[Priority] = frozenset({Priority.P0, Priority.P1})


def priority_of(call_type: str) -> Priority:
    """P3 (research) é o piso — uma chamada de tipo desconhecido nunca furta
    prioridade de execução por engano."""
    return CALL_TYPE_PRIORITY.get(call_type, Priority.P3)


@dataclass
class Budget:
    """Um orçamento de peso com reserva fracionária para prioridades de
    execução (P0/P1)."""

    limit: int
    reserve_pct: float
    used: int = 0

    def cap_for(self, priority: Priority) -> int:
        if priority in _EXECUTION_PRIORITIES:
            return self.limit
        return int(self.limit * (1 - self.reserve_pct))

    def remaining_for(self, priority: Priority) -> int:
        return max(self.cap_for(priority) - self.used, 0)

    def can_admit(self, priority: Priority, weight: int) -> bool:
        return self.used + weight <= self.cap_for(priority)

    def reserve(self, weight: int) -> None:
        """Reserva otimista local — corrigida no próximo `update_from_header`
        (regra 1, §9.4: a contagem própria nunca é a fonte de verdade)."""
        self.used += weight

    def update_from_header(self, used: int) -> None:
        self.used = used


@dataclass(order=True)
class _QueuedCall:
    sort_key: tuple[int, int]
    call_type: str = field(compare=False)
    weight: int = field(compare=False)
    priority: Priority = field(compare=False)


class RateLimitManager:
    """Orçamento de peso de IP + contagem de ordens (10s/1m), com fila de
    prioridade P0 > P1 > P2 > P3 (FIFO dentro da mesma prioridade)."""

    def __init__(
        self,
        *,
        ip_weight_limit: int | None = None,
        order_count_limit_10s: int | None = None,
        order_count_limit_1m: int | None = None,
        reserve_pct: float | None = None,
    ) -> None:
        reserve = (
            reserve_pct if reserve_pct is not None else load_constant("rate_limit_reserve_pct")
        )
        ip_limit = (
            ip_weight_limit if ip_weight_limit is not None else load_constant("ip_weight_limit_1m")
        )
        oc10_limit = (
            order_count_limit_10s
            if order_count_limit_10s is not None
            else load_constant("order_count_limit_10s")
        )
        oc1m_limit = (
            order_count_limit_1m
            if order_count_limit_1m is not None
            else load_constant("order_count_limit_1m")
        )

        self.ip_weight = Budget(ip_limit, reserve)
        self.order_count_10s = Budget(oc10_limit, reserve)
        self.order_count_1m = Budget(oc1m_limit, reserve)

        self._queue: list[_QueuedCall] = []
        self._seq = itertools.count()

    def update_from_headers(self, headers: Mapping[str, str]) -> None:
        """Chamado por `rest.py` em CADA resposta — a Binance é a fonte de
        verdade, nunca a contagem própria (§9.4 regra 1)."""
        for key, value in headers.items():
            upper = key.upper()
            if upper == _HEADER_IP_WEIGHT_1M:
                self.ip_weight.update_from_header(int(value))
            elif upper == _HEADER_ORDER_COUNT_10S:
                self.order_count_10s.update_from_header(int(value))
            elif upper == _HEADER_ORDER_COUNT_1M:
                self.order_count_1m.update_from_header(int(value))

    def enqueue(self, call_type: str, *, weight: int = 1) -> None:
        priority = priority_of(call_type)
        item = _QueuedCall((int(priority), next(self._seq)), call_type, weight, priority)
        self._queue.append(item)

    def _budgets_for(self, call_type: str) -> tuple[Budget, ...]:
        if call_type in ORDER_COUNTING_CALL_TYPES:
            return (self.ip_weight, self.order_count_10s, self.order_count_1m)
        return (self.ip_weight,)

    def process_queue(self) -> tuple[list[str], list[str]]:
        """Drena a fila em ordem de prioridade (P0 > P1 > P2 > P3; FIFO dentro
        da mesma prioridade). Cada chamada admitida reserva otimisticamente em
        TODOS os orçamentos que consome (regra 2: IP weight e order-count são
        independentes — uma chamada pode ser bloqueada por qualquer um dos
        dois). Retorna `(admitidas, adiadas)`; as adiadas permanecem na fila
        para a próxima rodada, preservando a ordem relativa."""
        pending = sorted(self._queue)
        admitted: list[str] = []
        deferred: list[_QueuedCall] = []

        for item in pending:
            budgets = self._budgets_for(item.call_type)
            if all(b.can_admit(item.priority, item.weight) for b in budgets):
                for b in budgets:
                    b.reserve(item.weight)
                admitted.append(item.call_type)
                logger.debug(
                    "rate_limit.admitted", call_type=item.call_type, priority=item.priority.name
                )
            else:
                deferred.append(item)
                logger.debug(
                    "rate_limit.deferred", call_type=item.call_type, priority=item.priority.name
                )

        self._queue = deferred
        return admitted, [d.call_type for d in deferred]

    def pending(self) -> list[str]:
        return [c.call_type for c in sorted(self._queue)]
