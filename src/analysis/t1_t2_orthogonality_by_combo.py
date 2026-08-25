"""Ortogonalidade combinada T1+T2 (69×69), por combinação símbolo×
resolução — `AG-207`/`AG-234` (2026-08-25). `t2_ranking_ortogonalidade.py`
(id=21, `audit/n_lifetime.yaml`) só mediu T2-vs-T2, e só para ETHUSDT/R1 —
gap real apontado pelo Manager ao revisar a aplicação de T1+T2 (69,
aditivo) em produção: (1) nenhuma das 10 combinações reais tem essa
medição própria (correlação é propriedade da série, pode variar por
mercado); (2) T1 nunca entrou na matriz de correlação, então um par
T1↔T2 redundante nunca foi detectável.

T1 (`T1_FEATURE_IDS`, 7) é o núcleo — sempre mantido, nunca candidato a
exclusão (é o próprio pedido do Manager: "promover T2 a T1" é aditivo,
T1 não some). O filtro guloso roda só sobre T2 (ranqueado por
estabilidade, `t2_ranking_ortogonalidade.rank_by_stability`, reusado sem
mudança), verificando cada candidato contra T1 (fixo) MAIS os T2 já
aceitos — mesma lógica de `orthogonality_filter`, só que com T1
pré-populado em `selected` e nunca sujeito a rejeição.

Núcleo puro (`filter_t2_given_t1`) separado da casca (`run_for_combo`,
que resolve símbolo/resolução/IO) — mesmo padrão de
`t2_ranking_ortogonalidade.py`."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import numpy as np
import orjson
import structlog
from scipy.stats import spearmanr

from src.features.build import SUPPORT_FEATURE_IDS, T1_FEATURE_IDS
from src.models._paths import EXPERIMENTS_DIR
from src.validation.noise_floor_diagnostics import _build_mf_and_splits

from .t2_ranking_ortogonalidade import (
    _MIN_PAIRWISE_OBS,
    _orthogonality_threshold,
    rank_by_stability,
)

logger = structlog.get_logger(__name__)


def _pairwise_spearman(x: np.ndarray, y: np.ndarray) -> float | None:
    mask = np.isfinite(x) & np.isfinite(y)
    if int(mask.sum()) < _MIN_PAIRWISE_OBS:
        return None
    if np.std(x[mask]) == 0.0 or np.std(y[mask]) == 0.0:
        return None
    rho, _p = spearmanr(x[mask], y[mask])
    return float(rho) if np.isfinite(rho) else None


def filter_t2_given_t1(
    t1_ids: tuple[str, ...],
    ranked_t2: list[str],
    mf_data: Any,
    *,
    threshold: float,
) -> tuple[list[str], list[str], dict[str, tuple[str, float]]]:
    """Núcleo -- T1 SEMPRE em `selected`, nunca removido. T2 percorrido
    por ordem de estabilidade (maior primeiro), aceito SE `|Spearman| <=
    threshold` contra TODOS os já selecionados (T1 + T2 já aceitos).
    Retorna `(t2_survivors, t2_excluded, motivo_exclusao)` -- motivo =
    (feature_correlacionada, rho), a PRIMEIRA que rejeitou (não todas)."""
    all_ids = tuple(t1_ids) + tuple(ranked_t2)
    arrays = {f: mf_data[f].to_numpy().astype(np.float64) for f in all_ids}
    selected: list[str] = list(t1_ids)
    t2_survivors: list[str] = []
    t2_excluded: list[str] = []
    excluded_reason: dict[str, tuple[str, float]] = {}
    for f in ranked_t2:
        x = arrays[f]
        rejected_by: tuple[str, float] | None = None
        for g in selected:
            rho = _pairwise_spearman(x, arrays[g])
            if rho is not None and abs(rho) > threshold:
                rejected_by = (g, rho)
                break
        if rejected_by is None:
            selected.append(f)
            t2_survivors.append(f)
        else:
            t2_excluded.append(f)
            excluded_reason[f] = rejected_by
    return t2_survivors, t2_excluded, excluded_reason


def _t1_internal_correlations(mf_data: Any, t1_ids: tuple[str, ...]) -> dict[str, float]:
    """Diagnóstico -- pares T1×T1 com |Spearman| alto, só informativo (T1
    nunca é excluído por isso). Chave `"A×B"`, valor = rho."""
    arrays = {f: mf_data[f].to_numpy().astype(np.float64) for f in t1_ids}
    out: dict[str, float] = {}
    for i, f in enumerate(t1_ids):
        for g in t1_ids[i + 1 :]:
            rho = _pairwise_spearman(arrays[f], arrays[g])
            if rho is not None:
                out[f"{f}x{g}"] = rho
    return out


def run_for_combo(
    symbol: str, resolution_id: str, *, vol_estimator_id: str | None = None
) -> dict[str, Any]:
    mf, splits = _build_mf_and_splits(symbol, resolution_id, vol_estimator_id, SUPPORT_FEATURE_IDS)
    threshold = _orthogonality_threshold()
    scores = rank_by_stability(mf.data, splits)
    ranked_t2 = sorted(scores, key=lambda f: scores[f], reverse=True)
    t2_survivors, t2_excluded, excluded_reason = filter_t2_given_t1(
        T1_FEATURE_IDS, ranked_t2, mf.data, threshold=threshold
    )
    t1_internal = _t1_internal_correlations(mf.data, T1_FEATURE_IDS)
    t1_internal_high_corr = {k: v for k, v in t1_internal.items() if abs(v) > threshold}
    final_feature_set_n = len(T1_FEATURE_IDS) + len(t2_survivors)
    result = {
        "symbol": symbol,
        "resolution_id": resolution_id,
        "n_t1": len(T1_FEATURE_IDS),
        "n_t2_candidates": len(SUPPORT_FEATURE_IDS),
        "orthogonality_threshold": threshold,
        "t2_survivors_given_t1": t2_survivors,
        "n_t2_survivors_given_t1": len(t2_survivors),
        "t2_excluded_given_t1": t2_excluded,
        "t2_excluded_reason": {
            f: {"correlated_with": g, "spearman": rho}
            for f, (g, rho) in excluded_reason.items()
        },
        "t1_internal_correlations": t1_internal,
        "t1_internal_high_corr": t1_internal_high_corr,
        "final_feature_set_n": final_feature_set_n,
    }
    logger.info(
        "analysis.t1_t2_orthogonality.combo_done",
        symbol=symbol,
        resolution_id=resolution_id,
        n_t2_survivors_given_t1=len(t2_survivors),
        n_t2_excluded_given_t1=len(t2_excluded),
        n_t1_internal_high_corr=len(t1_internal_high_corr),
        final_feature_set_n=final_feature_set_n,
    )
    return result


def write_report_atomic(payload: dict[str, Any], *, symbol: str, resolution_id: str) -> Path:
    """B29 — `.tmp` -> `fsync` -> `rename`."""
    EXPERIMENTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = EXPERIMENTS_DIR / f"t1_t2_orthogonality_{symbol}_{resolution_id}.json"
    tmp_path = out_path.with_name(out_path.name + ".tmp")
    blob = orjson.dumps(payload, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS)
    with tmp_path.open("wb") as fh:
        fh.write(blob)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, out_path)
    logger.info("analysis.t1_t2_orthogonality.report_written", path=str(out_path))
    return out_path


def _run_cli() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Ortogonalidade combinada T1+T2 (69x69) por combinação"
    )
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--resolution-id", default="R1")
    parser.add_argument("--vol-estimator-id", default="parkinson_w20")
    args = parser.parse_args()

    result = run_for_combo(args.symbol, args.resolution_id, vol_estimator_id=args.vol_estimator_id)
    out_path = write_report_atomic(result, symbol=args.symbol, resolution_id=args.resolution_id)
    logger.info(
        "analysis.t1_t2_orthogonality.cli_done",
        symbol=args.symbol,
        resolution_id=args.resolution_id,
        report_path=str(out_path),
    )
    return 0


if __name__ == "__main__":
    sys.exit(_run_cli())
