"""Configuração central de logging estruturado (§13.1, B28, B31).

Uso: chamar `configure_logging()` UMA VEZ no ponto de entrada de cada
executável (scripts/, src/live/runner.py, testnet, paper). Todo o resto do
código, em qualquer camada, só precisa de:

    import structlog
    logger = structlog.get_logger(__name__)

Isso mantém a hierarquia de import do §14.2 intacta — `exchange/` não precisa
importar `monitoring/` para logar; importa `structlog` diretamente, e a
configuração já foi feita a montante pelo processo.

Nunca usar `print()` (B28) — vira violação automatizada em
`tools/lint/banned_patterns.py`.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import orjson
import structlog

_MASKED_KEYS = re.compile(r"(?i)(api[_-]?key|secret|signature|password|token)")
_MASK = "***REDACTED***"


def _mask_secrets(_logger: object, _method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """B31 — mascaramento de api_key/signature em TODA saída estruturada, sem exceção."""
    for key in list(event_dict.keys()):
        if _MASKED_KEYS.search(key):
            event_dict[key] = _MASK
    return event_dict


def _orjson_dumps(obj: Any, **_kwargs: Any) -> str:
    return orjson.dumps(obj).decode("utf-8")


def configure_logging(level: int = logging.INFO, *, json_output: bool = True) -> None:
    """Configura structlog globalmente. Idempotente — pode ser chamada mais de uma vez."""
    logging.basicConfig(format="%(message)s", level=level)

    processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        _mask_secrets,
    ]
    processors.append(
        structlog.processors.JSONRenderer(serializer=_orjson_dumps) if json_output else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
