"""Loader de `config/constants.yaml` — privado ao pacote `models` (Regra
Zero, §16.10). Duplicado de `src/validation/_constants.py` pelo mesmo
motivo declarado em `_paths.py` deste pacote.

Nenhum literal numérico do Alpha (hiperparâmetros XGBoost, limiar de
consistência da Camada 1, fração de calibração, seed) vive solto em código
desta camada; tudo entra em `constants.yaml` com proveniência declarada e
é lido daqui.

Cache simples em memória — `constants.yaml` não muda durante a vida do
processo; testes que precisam de outro valor passam override explícito em
vez de mexer no cache global."""

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


def load_constant_entry(name: str) -> dict[str, Any]:
    """Como `load_constant`, mas devolve a entrada INTEIRA (`class`,
    `sweep_required`, `sweep_range`, `provenance`...), não só `value`.
    Usado por `hyperparams_optuna.py::build_search_space` para decidir
    dinamicamente quais campos de `LGBMHyperparams` entram na busca (campo
    elegível <=> a constante `alpha_lgbm_{campo}` correspondente declara
    `class: B` + `sweep_range` — nunca uma lista Python paralela mantida à
    mão, mesma disciplina que fechou o `AG-371`)."""
    entry = _load_all().get(name)
    if not isinstance(entry, dict) or "value" not in entry:
        raise KeyError(
            f"constante '{name}' ausente ou malformada em {CONSTANTS_PATH} "
            "(toda constante precisa de 'value' + proveniência, §16.10)"
        )
    return entry
