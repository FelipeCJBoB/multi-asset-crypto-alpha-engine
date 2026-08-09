"""Camada analysis — atribuição de importância de feature PÓS-HOC
(`attribution.py`: IC de Spearman por regime, gain do XGBoost por lado,
concordância entre os dois). Lê resultado REALIZADO (`ret_net`,
`barrier_hit`) e diagnóstico já persistido em disco — NUNCA insumo de
treino ou seleção de feature (ver docstring de `attribution.py`).

`src.models` e `src.features` não podem importar `src.analysis`
(`pyproject.toml [tool.importlinter]`, contratos "models não importa
analysis" / "features não importa analysis") — a separação é estrutural,
não só documentada."""

from __future__ import annotations

from .attribution import feature_agreement, gain_by_side, ic_by_regime

__all__ = ["feature_agreement", "gain_by_side", "ic_by_regime"]
