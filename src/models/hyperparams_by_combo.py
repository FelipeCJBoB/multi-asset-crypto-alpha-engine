"""Loader de `config/alpha_hyperparams_by_combo.yaml` — hiperparâmetro
LightGBM calibrado por (symbol, resolution_id), `AG-207`/`ADR-003`
(2026-08-25). Completa D-11 (`docs/alpha_model_design_doc_2026-08-22.md`,
"conjunto único v1, ASSUMED até sweep").

Só as 10 combinações cobertas pela campanha têm entrada — as outras 5
retornam `None` (`load_hyperparams_by_combo`), caminho explícito pro
chamador cair no hiperparâmetro global de `constants.yaml`, nunca
inventado aqui.

Cache simples em memória, mesmo padrão de `_constants.py` deste pacote —
o arquivo não muda durante a vida do processo."""

from __future__ import annotations

import dataclasses
from typing import Any

import yaml

from ._paths import HYPERPARAMS_BY_COMBO_PATH
from .alpha import LGBMHyperparams

_cache: dict[str, Any] | None = None

_HYPER_FIELDS = (
    "max_depth", "num_leaves", "min_child_samples",
    "learning_rate", "subsample", "feature_fraction", "lambda_l2", "n_estimators",
    "min_sum_hessian_in_leaf",
)


def _load_all() -> dict[str, Any]:
    global _cache
    if _cache is None:
        with HYPERPARAMS_BY_COMBO_PATH.open(encoding="utf-8") as f:
            loaded: dict[str, Any] = yaml.safe_load(f) or {}
            _cache = loaded
    return _cache


def load_hyperparams_by_combo(
    symbol: str, resolution_id: str, *, base: LGBMHyperparams | None = None
) -> LGBMHyperparams | None:
    """`None` se a combinação não foi calibrada por esta campanha — o
    chamador decide o fallback (`LGBMHyperparams.from_constants()`), não
    decidido silenciosamente aqui.

    `base` (default `None` → `LGBMHyperparams.from_constants()`) fornece
    os campos que o YAML não declara (`subsample_freq`, `max_bin`) — o
    arquivo só lista os 9 campos que a campanha de fato variou."""
    payload = _load_all()
    key = f"{symbol}_{resolution_id}"
    combos = payload.get("combos", {})
    entry = combos.get(key)
    if entry is None:
        return None
    base_hyper = base if base is not None else LGBMHyperparams.from_constants()
    overrides = {f: entry[f] for f in _HYPER_FIELDS if f in entry}
    return dataclasses.replace(base_hyper, **overrides)
