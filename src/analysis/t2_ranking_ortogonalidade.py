"""Pré-requisito da Fase 1 (`docs/t2_t1_ablation_veredito_duas_analises_
2026-08-24.md` §4) — ranking dos 62 candidatos T2 (`SUPPORT_FEATURE_IDS`)
por estabilidade + filtro de ortogonalidade, precedente direto dos passes
E2/E3 (`audit/n_lifetime.yaml` ids 11/13, mesma metodologia, candidatas
diferentes). **Medição de pesquisa, não seleção final** — nenhuma
promoção a `T1_FEATURE_IDS`/`registry.yaml` acontece aqui (§0.2 R4,
CLAUDE.md); alimenta os conjuntos k=6,9,12,16,24 que a Fase 1 testa.

Dois passos, escopos DIFERENTES de propósito, não confundir:

1. **Estabilidade** (`src.models.stability.stability_screen`) — IN-FOLD,
   agregada sobre as 15 splits × 2 lados REAIS do CPCV (30 células por
   feature, mesmo precedente do E3/id 13) — média das células com dado
   suficiente (`n_envs_with_data > 0`), não trata ausência de dado como
   zero.
2. **Ortogonalidade** (|Spearman| ≤ 0,70, filtro guloso por ordem de
   estabilidade) — sobre `mf.data` inteiro, mesmo escopo do precedente E2
   (id 11): correlação entre features é propriedade da SÉRIE, não do
   fold de treino — não é o mesmo tipo de vazamento que estabilidade
   (que precisa nunca olhar o teste) previne.

Custo: 1 trial (passe de ranking/triagem, nenhum modelo retreinado —
mesmo critério de contagem dos ids 11/13: "medição pra a triagem
in-fold decidir", não um trial por feature)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import numpy as np
import orjson
import structlog
from scipy.stats import spearmanr

from src.features import build as features_build
from src.features.build import SUPPORT_FEATURE_IDS
from src.models import dataset as ds
from src.models import stability
from src.models._constants import load_constant
from src.models._paths import EXPERIMENTS_DIR
from src.validation.noise_floor_diagnostics import _build_mf_and_splits

logger = structlog.get_logger(__name__)

_MIN_PAIRWISE_OBS = 30  # noqa: magic-number -- piso de robustez de Spearman em par de feature, mesma ordem de grandeza de _MIN_OBS_PER_LEG (stability.py), não constante de dominio


def _orthogonality_threshold() -> float:
    return float(load_constant("alpha_t2_orthogonality_spearman_max"))


def rank_by_stability(
    mf_data: Any, splits: tuple[Any, ...]
) -> dict[str, float]:
    """Núcleo -- estabilidade média por feature, agregada sobre as 15
    splits × 2 lados. `df_train_side` (não o teste, não o dataset
    inteiro) em cada célula, mesma disciplina de `stability_screen`."""
    scores_by_feature: dict[str, list[float]] = {f: [] for f in SUPPORT_FEATURE_IDS}
    for split in splits:
        train_bars = mf_data[split.train_idx]
        for side in (1, -1):
            train_side_df = ds.side_subset(
                train_bars, side=side, feature_ids=features_build.T1_FEATURE_IDS
            )
            results = stability.stability_screen(train_side_df, SUPPORT_FEATURE_IDS)
            for f, r in results.items():
                if r.n_envs_with_data > 0:
                    scores_by_feature[f].append(r.estabilidade)
    return {
        f: (float(np.mean(v)) if v else 0.0)
        for f, v in scores_by_feature.items()
    }


def orthogonality_filter(
    ranked_features: list[str], mf_data: Any, *, threshold: float
) -> list[str]:
    """Núcleo -- filtro guloso: percorre por ordem de estabilidade (maior
    primeiro), inclui a feature SE `|Spearman| <= threshold` com TODAS as
    já selecionadas. Correlação computada uma vez por par candidato,
    numpy puro (sem pandas, B26). `threshold` obrigatório (sem default)
    -- núcleo puro não esconde `load_constant` (IO) atrás de um default;
    quem chama resolve `_orthogonality_threshold()` explicitamente."""
    selected: list[str] = []
    arrays = {f: mf_data[f].to_numpy().astype(np.float64) for f in ranked_features}
    for f in ranked_features:
        x = arrays[f]
        ok = True
        for g in selected:
            y = arrays[g]
            mask = np.isfinite(x) & np.isfinite(y)
            if int(mask.sum()) < _MIN_PAIRWISE_OBS:
                continue
            if np.std(x[mask]) == 0.0 or np.std(y[mask]) == 0.0:
                continue
            rho, _p = spearmanr(x[mask], y[mask])
            if np.isfinite(rho) and abs(float(rho)) > threshold:
                ok = False
                break
        if ok:
            selected.append(f)
    return selected


def build_k_feature_sets(
    ordered_features: list[str], k_values: tuple[int, ...] = (6, 9, 12, 16, 24)
) -> dict[int, tuple[str, ...]]:
    """`k` = top-k da lista já filtrada por ortogonalidade, na ordem de
    estabilidade. Levanta se `k > len(ordered_features)` — falha alto,
    não trunca silenciosamente (B23-adjacent: não inventa feature)."""
    out: dict[int, tuple[str, ...]] = {}
    for k in k_values:
        if k > len(ordered_features):
            raise ValueError(
                f"build_k_feature_sets: k={k} > {len(ordered_features)} features "
                "sobreviventes ao filtro de ortogonalidade -- grade de k precisa ser "
                "revisada, não dá pra truncar silenciosamente"
            )
        out[k] = tuple(ordered_features[:k])
    return out


def write_report_atomic(payload: dict[str, Any], *, symbol: str, resolution_id: str) -> Path:
    """B29 — `.tmp` -> `fsync` -> `rename`."""
    EXPERIMENTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = EXPERIMENTS_DIR / f"t2_ranking_ortogonalidade_{symbol}_{resolution_id}.json"
    tmp_path = out_path.with_name(out_path.name + ".tmp")
    blob = orjson.dumps(payload, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS)
    with tmp_path.open("wb") as fh:
        fh.write(blob)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, out_path)
    logger.info("analysis.t2_ranking.report_written", path=str(out_path))
    return out_path


def _run_cli() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Pré-requisito Fase 1 -- ranking + ortogonalidade dos 62 candidatos T2"
    )
    parser.add_argument("--symbol", default="ETHUSDT")
    parser.add_argument("--resolution-id", default="R1")
    parser.add_argument("--vol-estimator-id", default="parkinson_w20")
    args = parser.parse_args()

    mf, splits = _build_mf_and_splits(
        args.symbol, args.resolution_id, args.vol_estimator_id, SUPPORT_FEATURE_IDS
    )
    threshold = _orthogonality_threshold()
    scores = rank_by_stability(mf.data, splits)
    ranked = sorted(scores, key=lambda f: scores[f], reverse=True)
    survivors = orthogonality_filter(ranked, mf.data, threshold=threshold)
    k_sets = build_k_feature_sets(survivors)

    payload = {
        "symbol": args.symbol,
        "resolution_id": args.resolution_id,
        "n_candidates": len(SUPPORT_FEATURE_IDS),
        "estabilidade_by_feature": scores,
        "ranked_all": ranked,
        "survivors_ortogonalidade": survivors,
        "n_survivors": len(survivors),
        "orthogonality_threshold": threshold,
        "k_feature_sets": {str(k): list(v) for k, v in k_sets.items()},
    }
    out_path = write_report_atomic(payload, symbol=args.symbol, resolution_id=args.resolution_id)
    logger.info(
        "analysis.t2_ranking.cli_done",
        n_survivors=len(survivors),
        k_feature_sets=dict(payload["k_feature_sets"]),
        report_path=str(out_path),
    )
    return 0


if __name__ == "__main__":
    sys.exit(_run_cli())
