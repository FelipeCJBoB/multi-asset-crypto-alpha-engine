"""Loader de `config/constants.yaml` — privado ao pacote `execution` (Regra
Zero, §16.10). Duplicado de `src/labels/_constants.py` / `src/data/_constants.py`
pelo mesmo motivo documentado em `_paths.py` deste pacote.

`fill_simulator.py` REUSA `tick_size` e `fill_timeout_bars`, ambos já
existentes em `constants.yaml` (§0.1 e Sprint 6 respectivamente) — nenhuma
constante numérica nova de barreira/execução é declarada por este Sprint 9
(ver docstring de `fill_simulator.py`, item "cancelamento não modelado" —
decisão estrutural, não um valor calibrado, portanto não vive aqui).

Cache simples em memória — `constants.yaml` não muda durante a vida do
processo; testes que precisam de outro valor passam override explícito em
vez de mexer no cache global.
"""

from __future__ import annotations

from typing import Any

import yaml

from ._paths import CONSTANTS_PATH

_cache: dict[str, Any] | None = None


def _load_all() -> dict[str, Any]:
    global _cache
    if _cache is None:
        with CONSTANTS_PATH.open(encoding="utf-8") as f:
            loaded: dict[str, Any] = yaml.safe_load(f) or {}
            _cache = loaded
    return _cache


def load_constant(name: str) -> Any:
    """Lê `value` da entrada `name` em `constants.yaml`. Levanta `KeyError`
    com mensagem acionável se a entrada não existir ou estiver malformada —
    nunca retorna um default silencioso inventado no código (Regra Zero)."""
    entry = _load_all().get(name)
    if not isinstance(entry, dict) or "value" not in entry:
        raise KeyError(
            f"constante '{name}' ausente ou malformada em {CONSTANTS_PATH} "
            "(toda constante precisa de 'value' + proveniência, §16.10)"
        )
    return entry["value"]
