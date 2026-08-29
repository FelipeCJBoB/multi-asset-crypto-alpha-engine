"""Loader de `config/alpha_hyperparams_by_combo.yaml` — hiperparâmetro
LightGBM calibrado por (symbol, resolution_id), `AG-207`/`ADR-003`
(2026-08-25). Completa D-11 (`docs/alpha_model_design_doc_2026-08-22.md`,
"conjunto único v1, ASSUMED até sweep").

Só as 10 combinações cobertas pela campanha têm entrada — as outras 5
retornam `None` (`load_hyperparams_by_combo`), caminho explícito pro
chamador cair no hiperparâmetro global de `constants.yaml`, nunca
inventado aqui.

Cache simples em memória, mesmo padrão de `_constants.py` deste pacote —
o arquivo não muda durante a vida do processo.

**Trava de compatibilidade de vetor (AG-371, 2026-08-28).** A campanha
que gerou este arquivo (25/08) calibrou sob UM vetor de features
específico (`feature_ids_ref`/`feature_ids_hash` no header do YAML). O
hiperparâmetro resultante (`num_leaves` raso, `min_child_samples` alto)
é MEDIDO pra esse vetor — não generaliza automaticamente pra outro
(achado real: a campanha de 25/08 mediu sob `SUPPORT_FEATURE_IDS`, 62
features; `AG-362`, 27/08, reestruturou `T1_FEATURE_IDS` pra 22 sem
recalibrar este arquivo; o retreino canônico de 28/08 injetou o
hiperparâmetro stale sob o vetor novo sem checagem nenhuma). Por isso
`load_hyperparams_by_combo` exige `feature_ids_effective` — o vetor
REALMENTE resolvido que vai treinar (nunca `None`; ver
`src.features.build.resolve_feature_ids`) — e verifica por HASH de
conteúdo (`compute_feature_ids_hash`), não por nome de símbolo: a causa
raiz do AG-371 foi justamente `T1_FEATURE_IDS` mudar de CONTEÚDO (7->22)
mantendo o NOME, então uma checagem por string de nome não pegaria uma
repetição futura do mesmo defeito."""

from __future__ import annotations

import dataclasses
from typing import Any

import structlog
import yaml

from src.io.artifact import compute_config_hash

from ._paths import HYPERPARAMS_BY_COMBO_PATH
from .alpha import LGBMHyperparams

logger = structlog.get_logger(__name__)

_cache: dict[str, Any] | None = None

_HYPER_FIELDS = (
    "max_depth", "num_leaves", "min_child_samples",
    "learning_rate", "subsample", "feature_fraction", "lambda_l2", "n_estimators",
    "min_sum_hessian_in_leaf",
)

_FEATURE_IDS_HASH_SCHEMA_VERSION = "alpha_hyperparams_by_combo_feature_ids_v1"


class HyperparamFeatureMismatchError(Exception):
    """AG-371 — `feature_ids_effective` recebido não bate com o vetor sob
    o qual `alpha_hyperparams_by_combo.yaml` foi calibrado (hash de
    conteúdo, `feature_ids_hash` do header). Hiperparâmetro calibrado pra
    um vetor não generaliza pra outro sem medição nova — injetar mesmo
    assim reproduziria o AG-371 original. Mesmo padrão de
    `ConfigHashMismatchError` (`src.labels.triple_barrier`, B15): "teste
    que quebra o build, não item de checklist" — nunca um warning que se
    perde em log de 15 combinações."""


def compute_feature_ids_hash(feature_ids: tuple[str, ...]) -> str:
    """Fingerprint de CONTEÚDO do vetor de features, não do nome do
    símbolo Python que o carrega (`T1_FEATURE_IDS` pode mudar de conteúdo
    mantendo o nome — foi exatamente a causa raiz do AG-371). Ordena
    antes de serializar: hiperparâmetro é propriedade do CONJUNTO de
    features, não da ordem das colunas — reordenar `T1_FEATURE_IDS` sem
    mudar seu conteúdo não deveria acender falso-positivo. Mesmo
    mecanismo de `compute_config_hash` (`src.io.artifact`, usado por
    `config_hash`/`ConfigHashMismatchError`), não um hash novo inventado
    aqui."""
    return compute_config_hash(
        {"feature_ids": sorted(feature_ids)},
        schema_version=_FEATURE_IDS_HASH_SCHEMA_VERSION,
    )


def _load_all() -> dict[str, Any]:
    global _cache
    if _cache is None:
        with HYPERPARAMS_BY_COMBO_PATH.open(encoding="utf-8") as f:
            loaded: dict[str, Any] = yaml.safe_load(f) or {}
            _cache = loaded
    return _cache


def load_hyperparams_by_combo(
    symbol: str,
    resolution_id: str,
    *,
    feature_ids_effective: tuple[str, ...],
    base: LGBMHyperparams | None = None,
    allow_feature_mismatch: bool = False,
) -> tuple[LGBMHyperparams | None, bool]:
    """Retorna `(hyper, feature_mismatch)`. `hyper=None` se a combinação
    não foi calibrada por esta campanha — o chamador decide o fallback
    (`LGBMHyperparams.from_constants()`), não decidido silenciosamente
    aqui; nesse caso `feature_mismatch` é sempre `False` (não há
    hiperparâmetro calibrado pra validar contra nada).

    `feature_ids_effective` (AG-371, 2026-08-28) — vetor de features
    REALMENTE resolvido que vai treinar agora (nunca `None`; resolva com
    `src.features.build.resolve_feature_ids` antes de chamar). Comparado
    por hash de conteúdo contra `feature_ids_hash` do header do YAML.

    Mismatch (ou header sem `feature_ids_hash`, ex. arquivo pré-AG-371
    nunca migrado) -> `HyperparamFeatureMismatchError`, default. Fail-
    CLOSED de propósito: silenciar isso de volta pra warning é o que já
    causou o AG-371 (o warning de "combinação sem calibração" já existia
    e não impediu ninguém de confiar no retreino contaminado).
    `allow_feature_mismatch=True` rebaixa pra warning explícito e retorna
    `feature_mismatch=True` -- o chamador decide o que fazer com o flag
    (ex. marcar o report como contaminado); esta função não escreve em
    artefato. Só pra comparação exploratória deliberada (mesmo espírito
    de `scratch=True`, AG-368) -- nunca em retreino canônico.

    `base` (default `None` → `LGBMHyperparams.from_constants()`) fornece
    os campos que o YAML não declara (`subsample_freq`, `max_bin`) — o
    arquivo só lista os 9 campos que a campanha de fato variou."""
    payload = _load_all()
    key = f"{symbol}_{resolution_id}"
    combos = payload.get("combos", {})
    entry = combos.get(key)
    if entry is None:
        return None, False
    expected_hash = payload.get("feature_ids_hash")
    actual_hash = compute_feature_ids_hash(feature_ids_effective)
    feature_mismatch = expected_hash is None or expected_hash != actual_hash
    if feature_mismatch:
        message = (
            "hyperparams_by_combo: feature_ids_hash do YAML "
            f"({expected_hash!r}) != hash do vetor ativo ({actual_hash!r}) "
            f"para {key} -- hiperparâmetro calibrado (AG-207/ADR-003) pra "
            "outro vetor de features, nunca revalidado (AG-371). Recalibre "
            "config/alpha_hyperparams_by_combo.yaml sob o vetor atual antes "
            "de usar use_hyperparams_by_combo=True em produção."
        )
        if not allow_feature_mismatch:
            raise HyperparamFeatureMismatchError(message)
        logger.warning(
            "models.hyperparams_by_combo.feature_ids_mismatch_allowed",
            symbol=symbol,
            resolution_id=resolution_id,
            expected_hash=expected_hash,
            actual_hash=actual_hash,
        )
    base_hyper = base if base is not None else LGBMHyperparams.from_constants()
    overrides = {f: entry[f] for f in _HYPER_FIELDS if f in entry}
    return dataclasses.replace(base_hyper, **overrides), feature_mismatch
