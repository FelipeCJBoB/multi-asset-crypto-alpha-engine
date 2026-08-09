"""Camada features — feature engine, registry (§2.14), grupos A-K, teste de
paridade lote/streaming. Importa data/. NÃO pode importar labels/
(hierarquia §14.2).

Sprint 4 implementa o vetor T1 (§2.13) + B07 (T2, insumo do Regime Engine,
§4.2) a `decision_tf = 15m` — ver `config.constants.yaml` / registry.yaml
para a discussão da inconsistência 15m vs 30m nas tabelas §2.2-2.6 do PRD.
"""

from __future__ import annotations

from .build import (
    SUPPORT_FEATURE_IDS,
    T1_FEATURE_IDS,
    FeatureWindows,
    build_t1_features,
    compute_t1_features,
)

__all__ = [
    "SUPPORT_FEATURE_IDS",
    "T1_FEATURE_IDS",
    "FeatureWindows",
    "build_t1_features",
    "compute_t1_features",
]
