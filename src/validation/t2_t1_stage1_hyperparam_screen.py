"""ADR-002 (`docs/ADR-002_busca_hiperparametro_robusta_a_ruido_2026-08-24.md`)
Estágio 1b — coordenada-descendente sobre os 5 hiperparâmetros do LightGBM
nunca tocados por Fase 1/Fase 2 (`learning_rate`, `subsample`,
`feature_fraction`, `lambda_l2`, `n_estimators`). 1 seed só (screening
barato, viés de seleção esperado e não corrigido aqui de propósito -- a
correção é o Estágio 2, `t2_t1_fase2_confirmation.py`).

**Ancoragem, não re-busca de `(k, depth, leaves, mcs)`**: o grid de Fase
1+2 (149 trials) já existe e é reusado como está -- este módulo fixa a
região vencedora nominal dela (`k=32, max_depth=2, num_leaves=3,
min_child_samples=500`, `experiments/t2_t1_capacity_map_fase2_ETHUSDT_
R1.json::best_trial`) e varia CADA um dos 5 hiperparâmetros novos
isoladamente ao redor do valor de produção, mantendo os outros 4 (dos 5
novos) travados em PROD a cada passe -- não é grid cheio (5 dimensões ×
mesmo nº de pontos cada seria combinatorialmente proibitivo).

**Saída consumida pelo Estágio 2, não uma decisão em si**: todo trial
aqui é rotulado `stage="1b_hyperparam_coord_descent"` e carrega o
hyperparameter-set COMPLETO (9 campos de `LGBMHyperparams` + `k`), pra
`load_combined_candidate_pool` conseguir juntar isto com os candidatos de
Fase 1+2 (que só variam 4 dos 9 campos, os outros 5 implicitamente em
PROD) numa única lista rankeável."""

from __future__ import annotations

import dataclasses
import os
import sys
import time
from pathlib import Path
from typing import Any

import orjson
import structlog

from src.models import alpha
from src.models._constants import load_constant
from src.models._paths import EXPERIMENTS_DIR
from src.models.pipeline import MODEL_ID_CAMADA1
from src.validation.noise_floor_diagnostics import _build_mf_and_splits, _pooled_sharpe

logger = structlog.get_logger(__name__)

# Âncora -- vencedor nominal de Fase 2 (1 seed, NÃO confirmado -- é só o
# ponto de partida do screening deste estágio, mesmo tratamento que
# t2_t1_capacity_map_fase2.py já dava ao vencedor de Fase 1).
_ANCHOR_K = 32
_ANCHOR_MAX_DEPTH = 2
_ANCHOR_NUM_LEAVES = 3
_ANCHOR_MIN_CHILD_SAMPLES = 500

# Cada dimensão varia isolada, 1 de cada vez, ao redor do valor de PROD --
# coordenada-descendente, não cross-product. O valor PROD de cada
# dimensão já está coberto pelo trial-âncora (cache, 0 custo) -- só os
# pontos NOVOS (fora de PROD) precisam rodar de verdade.
_LEARNING_RATE_GRID: tuple[float, ...] = (0.01, 0.05, 0.08)  # noqa: magic-number -- grade de busca declarada a priori (ADR-002), não constante de domínio; PROD=0.03 já cacheado
_SUBSAMPLE_GRID: tuple[float, ...] = (0.6, 0.9, 1.0)  # noqa: magic-number -- idem; PROD=0.8 já cacheado
_FEATURE_FRACTION_GRID: tuple[float, ...] = (0.6, 0.8)  # noqa: magic-number -- idem; PROD=1.0 (teto) já cacheado
_LAMBDA_L2_GRID: tuple[float, ...] = (1.0, 10.0, 20.0)  # noqa: magic-number -- idem; PROD=5.0 já cacheado
_N_ESTIMATORS_GRID: tuple[int, ...] = (150, 500)  # noqa: magic-number -- idem; PROD=300 já cacheado


def _load_anchor_feature_set(symbol: str, resolution_id: str, k: int) -> tuple[str, ...]:
    path = EXPERIMENTS_DIR / f"t2_ranking_ortogonalidade_{symbol}_{resolution_id}.json"
    payload = orjson.loads(path.read_bytes())
    survivors: list[str] = payload["survivors_ortogonalidade"]
    return tuple(survivors[:k])


def _load_fase2_cached_anchor(symbol: str, resolution_id: str) -> dict[str, Any]:
    """O trial-âncora (`k=32/depth=2/leaves=3/mcs=500`, resto PROD) já foi
    medido em `t2_t1_capacity_map_fase2.py::run_fase2` (Estágio B, mcs=500)
    -- reusado aqui como o ponto PROD de referência pras 5 dimensões
    novas, sem retreino."""
    path = EXPERIMENTS_DIR / f"t2_t1_capacity_map_fase2_{symbol}_{resolution_id}.json"
    payload = orjson.loads(path.read_bytes())
    best_trial: dict[str, Any] = payload["best_trial"]
    return best_trial


def run_stage1b_coord_descent(
    symbol: str,
    resolution_id: str,
    *,
    device_type: str = "cpu",
    vol_estimator_id: str | None = None,
) -> dict[str, Any]:
    feature_ids = _load_anchor_feature_set(symbol, resolution_id, _ANCHOR_K)
    mf, splits = _build_mf_and_splits(symbol, resolution_id, vol_estimator_id, feature_ids)
    base_hyper = alpha.LGBMHyperparams.from_constants()
    anchor_hyper = dataclasses.replace(
        base_hyper,
        max_depth=_ANCHOR_MAX_DEPTH,
        num_leaves=_ANCHOR_NUM_LEAVES,
        min_child_samples=_ANCHOR_MIN_CHILD_SAMPLES,
    )
    seed = int(load_constant("alpha_random_seed"))

    anchor_cached = _load_fase2_cached_anchor(symbol, resolution_id)
    anchor_trial = {
        "k": _ANCHOR_K, "max_depth": _ANCHOR_MAX_DEPTH, "num_leaves": _ANCHOR_NUM_LEAVES,
        "min_child_samples": _ANCHOR_MIN_CHILD_SAMPLES,
        "learning_rate": anchor_hyper.learning_rate, "subsample": anchor_hyper.subsample,
        "feature_fraction": anchor_hyper.feature_fraction, "lambda_l2": anchor_hyper.lambda_l2,
        "n_estimators": anchor_hyper.n_estimators,
        "pooled_sharpe": anchor_cached["pooled_sharpe"],
        "sharpe_by_path": anchor_cached["sharpe_by_path"],
        "reused_from_fase2": True, "stage": "1b_hyperparam_coord_descent",
    }

    dims: tuple[tuple[str, tuple[Any, ...]], ...] = (
        ("learning_rate", _LEARNING_RATE_GRID),
        ("subsample", _SUBSAMPLE_GRID),
        ("feature_fraction", _FEATURE_FRACTION_GRID),
        ("lambda_l2", _LAMBDA_L2_GRID),
        ("n_estimators", _N_ESTIMATORS_GRID),
    )

    trials: list[dict[str, Any]] = [anchor_trial]
    for field_name, grid in dims:
        for value in grid:
            hyper = dataclasses.replace(anchor_hyper, **{field_name: value})
            t0 = time.time()
            folds = alpha.run_all_folds(
                mf.data, splits,
                variant=alpha.VARIANT_CAMADA1,
                model_id=MODEL_ID_CAMADA1,
                symbol=symbol,
                resolution_id=resolution_id,
                hyper=hyper,
                seed=seed,
                feature_ids=feature_ids,
                device_type=device_type,
            )
            elapsed_s = time.time() - t0
            pooled, by_path = _pooled_sharpe(folds, mf.data)
            trial = {
                "k": _ANCHOR_K, "max_depth": hyper.max_depth, "num_leaves": hyper.num_leaves,
                "min_child_samples": hyper.min_child_samples,
                "learning_rate": hyper.learning_rate, "subsample": hyper.subsample,
                "feature_fraction": hyper.feature_fraction, "lambda_l2": hyper.lambda_l2,
                "n_estimators": hyper.n_estimators,
                "pooled_sharpe": pooled, "sharpe_by_path": by_path,
                "elapsed_seconds": elapsed_s, "reused_from_fase2": False,
                "stage": "1b_hyperparam_coord_descent", "varied_dimension": field_name,
            }
            trials.append(trial)
            logger.info(
                "validation.t2_t1_stage1b.trial_done",
                varied_dimension=field_name, value=value, pooled_sharpe=pooled,
                elapsed_seconds=elapsed_s,
            )

    best = max(trials, key=lambda t: t["pooled_sharpe"])
    n_new = sum(1 for t in trials if not t.get("reused_from_fase2", False))
    logger.info(
        "validation.t2_t1_stage1b.run_done",
        n_trials=len(trials), n_new_trainings=n_new,
        best_pooled_sharpe=best["pooled_sharpe"],
        best_varied_dimension=best.get("varied_dimension", "anchor"),
    )
    return {
        "symbol": symbol, "resolution_id": resolution_id,
        "anchor": anchor_trial, "trials": trials, "best_trial": best,
        "n_new_trainings": n_new,
    }


def write_report_atomic(payload: dict[str, Any], *, symbol: str, resolution_id: str) -> Path:
    """B29 — `.tmp` -> `fsync` -> `rename`."""
    EXPERIMENTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = EXPERIMENTS_DIR / f"t2_t1_stage1b_hyperparam_{symbol}_{resolution_id}.json"
    tmp_path = out_path.with_name(out_path.name + ".tmp")
    blob = orjson.dumps(payload, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS)
    with tmp_path.open("wb") as fh:
        fh.write(blob)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, out_path)
    logger.info("validation.t2_t1_stage1b.report_written", path=str(out_path))
    return out_path


def _run_cli() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="ADR-002 Estágio 1b -- coordenada-descendente")
    parser.add_argument("--symbol", default="ETHUSDT")
    parser.add_argument("--resolution-id", default="R1")
    parser.add_argument("--vol-estimator-id", default="parkinson_w20")
    parser.add_argument("--device-type", default="cpu")
    args = parser.parse_args()

    result = run_stage1b_coord_descent(
        args.symbol, args.resolution_id,
        device_type=args.device_type, vol_estimator_id=args.vol_estimator_id,
    )
    out_path = write_report_atomic(result, symbol=args.symbol, resolution_id=args.resolution_id)
    logger.info(
        "validation.t2_t1_stage1b.cli_done",
        n_new_trainings=result["n_new_trainings"],
        best_trial={
            "varied_dimension": result["best_trial"].get("varied_dimension", "anchor"),
            "pooled_sharpe": result["best_trial"]["pooled_sharpe"],
        },
        report_path=str(out_path),
    )
    return 0


if __name__ == "__main__":
    sys.exit(_run_cli())
