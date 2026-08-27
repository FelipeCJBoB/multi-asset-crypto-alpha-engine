"""Instrumentação de progresso para `ProcessPoolExecutor` sem timeout/kill
automático (`AG-071`, `audit/architecture_gaps_log.yaml`) — nenhum
`future.result()` do repo tinha timeout, e a rodada real já travou 16h+ e
teve OOM 3x na sessão de M2. Decisão do usuário 2026-08-27: o mecanismo de
timeout/kill (qual valor? matar o processo do worker? abortar a rodada
inteira ou só a task travada?) segue em aberto — só instrumentar por ora,
sem matar nada. `iter_completed_with_heartbeat` substitui `concurrent.
futures.as_completed` nos call sites de `ProcessPoolExecutor`: mesmo
contrato de iteração (devolve cada future assim que completa), mas loga
periodicamente quais tasks ainda estão pendentes e há quanto tempo a
rodada está rodando — puramente observacional, não lê `constants.yaml`
por conta própria (`heartbeat_s` é responsabilidade de quem chama, cada
call site já importa seu próprio loader de `_constants`)."""

from __future__ import annotations

import time
from collections.abc import Hashable, Iterable, Iterator, Mapping
from concurrent.futures import FIRST_COMPLETED, Future, wait
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


def iter_completed_with_heartbeat(
    future_to_label: Mapping[Future[Any], Hashable],
    *,
    event_prefix: str,
    heartbeat_s: float,
    **log_context: Any,
) -> Iterator[Future[Any]]:
    """Substituto de `as_completed(future_to_label)` com log periódico
    (`heartbeat_s`, ex. `ag071_process_pool_heartbeat_s`) de progresso —
    `pending` no log lista os labels (ex. `(symbol, tf)`) ainda não
    concluídos. `log_context` (ex. `resolution_id=...`) é anexado a todo
    evento de heartbeat, mesmo padrão dos `logger.info`/`logger.error` já
    existentes nos call sites. Nunca levanta `TimeoutError`, nunca cancela
    future — só observa; quem chama continua responsável por
    `future.result()`/tratamento de exceção, sem mudança de contrato."""
    pending: Iterable[Future[Any]] = set(future_to_label)
    t0 = time.monotonic()
    n_total = len(future_to_label)
    while pending:
        done, pending = wait(pending, timeout=heartbeat_s, return_when=FIRST_COMPLETED)
        if not done:
            logger.info(
                f"{event_prefix}.heartbeat",
                elapsed_s=round(time.monotonic() - t0, 1),
                n_done=n_total - len(pending),
                n_total=n_total,
                pending=[future_to_label[f] for f in pending],
                **log_context,
            )
            continue
        yield from done
