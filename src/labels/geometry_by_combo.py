"""Loader de `config/barrier_geometry_by_combo.yaml` — geometria de barreira
(`tp_atr_mult`/`sl_atr_mult`) calibrada por `(symbol, resolution_id)`.

**Por que existe.** `tp_atr_mult`/`sl_atr_mult` são constantes classe A
GLOBAIS: um valor para as 15 células `(symbol, resolution_id)`. Mas o Alpha
treina 15 modelos INDEPENDENTES, um por célula — a assimetria registrada em
`AG-249` ("o modelo é por célula, o alvo e os guardrails são globais"). O
gate econômico (`src/analysis/economic_gate.py`) mediu que a geometria de
menor `required_lift` NÃO é a mesma nas três grades: sob R1 a barreira ótima
medida é mais larga que a global, sob R2/R3 a global já é a certa.

**O que este módulo NÃO faz.** Não inventa geometria para combo ausente.
`load_barrier_geometry` devolve `None` quando a combinação não está no
arquivo, e o chamador cai no global de `constants.yaml` — caminho explícito,
nunca um valor interpolado. Só entram no arquivo os combos cujo ganho é
DISTINGUÍVEL do incumbente a 95%: trocar geometria muda `config_hash`
(B15) e obriga relabel, e pagar isso por um ganho dentro do erro seria
comprar ruído com custo real.

Cache simples em memória, mesmo padrão de `_constants.py` deste pacote — o
arquivo não muda durante a vida do processo."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

import yaml

from ._paths import BARRIER_GEOMETRY_BY_COMBO_PATH

_cache: dict[str, Any] | None = None

_ROOT_KEY: Final[str] = "barrier_geometry"


@dataclass(frozen=True, slots=True)
class BarrierGeometry:
    """Geometria de barreira de UMA célula. Os dois campos têm exatamente o
    mesmo significado das constantes globais homônimas — são um override,
    não uma grandeza nova."""

    tp_atr_mult: float
    sl_atr_mult: float


def _load_all() -> dict[str, Any]:
    global _cache
    if _cache is None:
        if not BARRIER_GEOMETRY_BY_COMBO_PATH.exists():
            _cache = {}
            return _cache
        with BARRIER_GEOMETRY_BY_COMBO_PATH.open(encoding="utf-8") as fh:
            loaded: dict[str, Any] = yaml.safe_load(fh) or {}
        raw = loaded.get(_ROOT_KEY) or {}
        _cache = raw if isinstance(raw, dict) else {}
    return _cache


def load_barrier_geometry(symbol: str, resolution_id: str | None) -> BarrierGeometry | None:
    """Geometria calibrada de `(symbol, resolution_id)`, ou `None` se a
    combinação não estiver coberta.

    `resolution_id=None` (grade de relógio legada) devolve `None` sempre: a
    calibração foi medida sobre as grades dollar-bar R1/R2/R3 e não é
    transportável para a grade de 15m (`AG-042` — são grades com ~47% de
    diferença de duração)."""
    if resolution_id is None:
        return None
    entry = _load_all().get(f"{symbol}_{resolution_id}")
    if entry is None:
        return None
    return BarrierGeometry(
        tp_atr_mult=float(entry["tp_atr_mult"]),
        sl_atr_mult=float(entry["sl_atr_mult"]),
    )


def covered_combos() -> tuple[str, ...]:
    """Combos com geometria calibrada — para o chamador registrar em log o
    que de fato está sob override, em vez de deixar isso implícito."""
    return tuple(sorted(_load_all()))
