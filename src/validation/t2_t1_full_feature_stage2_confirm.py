"""ADR-003 (`docs/ADR-003_hiperparametro_feature_set_completo_2026-08-25.md`)
Estágio 2 — confirmação por combinação símbolo×resolução, `k=62`
(`SUPPORT_FEATURE_IDS` completo). Mesma disciplina de mediana top-K do
ADR-002 (Estágio 2), adaptada pra 10 combos independentes em vez de 1
pool global: top-3 candidatos (não top-5 — orçamento controlado dado o
multiplicador ×10, `ADR-003 §Estágio 2`) do Estágio 1 de CADA combo, cada
um confirmado com 5 seeds (1 reusa o screening, 4 novas), vencedor por
combo = maior MEDIANA — nunca argmax de 1 seed."""

from __future__ import annotations

import dataclasses
import os
import sys
import time
from pathlib import Path
from typing import Any

import orjson
import structlog

from src.features import build as features_build
from src.models import alpha
from src.models._constants import load_constant
from src.models._paths import EXPERIMENTS_DIR
from src.models.pipeline import MODEL_ID_CAMADA1
from src.validation.noise_floor_diagnostics import _build_mf_and_splits, _pooled_sharpe

logger = structlog.get_logger(__name__)

_TOP_K_FOR_CONFIRMATION = 3  # noqa: magic-number -- decisão de desenho da ADR-003 (orçamento x10 combos), não constante de domínio
_N_SEEDS_STAGE2 = 5  # noqa: magic-number -- idem, mesma disciplina do ADR-002

_HYPER_FIELDS = (
    "max_depth", "num_leaves", "min_child_samples",
    "learning_rate", "subsample", "feature_fraction", "lambda_l2", "n_estimators",
    "min_sum_hessian_in_leaf",
)


def _candidate_to_hyper(
    candidate: dict[str, Any], base: alpha.LGBMHyperparams
) -> alpha.LGBMHyperparams:
    overrides = {f: candidate[f] for f in _HYPER_FIELDS if f in candidate}
    return dataclasses.replace(base, **overrides)


def _load_top_k(symbol: str, resolution_id: str) -> list[dict[str, Any]]:
    path = EXPERIMENTS_DIR / f"t2_t1_stage1_screen_{symbol}_{resolution_id}.json"
    payload: dict[str, Any] = orjson.loads(path.read_bytes())
    trials: list[dict[str, Any]] = payload["hyperparam_trials"]
    return sorted(trials, key=lambda t: t["pooled_sharpe"], reverse=True)[:_TOP_K_FOR_CONFIRMATION]


def run_stage2_confirm(
    symbol: str,
    resolution_id: str,
    *,
    device_type: str = "cpu",
    vol_estimator_id: str | None = None,
) -> dict[str, Any]:
    feature_ids = features_build.SUPPORT_FEATURE_IDS
    mf, splits = _build_mf_and_splits(symbol, resolution_id, vol_estimator_id, feature_ids)
    base_hyper = alpha.LGBMHyperparams.from_constants()
    base_seed = int(load_constant("alpha_random_seed"))
    seeds = [base_seed] + [alpha._derived_seed(base_seed, i) for i in range(_N_SEEDS_STAGE2 - 1)]

    top_k = _load_top_k(symbol, resolution_id)
    confirmed: list[dict[str, Any]] = []
    for candidate in top_k:
        hyper = _candidate_to_hyper(candidate, base_hyper)
        seed_scores: list[float] = []
        per_seed: list[dict[str, Any]] = []
        for i, seed in enumerate(seeds):
            if i == 0:
                pooled = candidate["pooled_sharpe"]
                per_seed.append({"seed": seed, "pooled_sharpe": pooled, "reused": True})
            else:
                t0 = time.time()
                folds = alpha.run_all_folds(
                    mf.data, splits, variant=alpha.VARIANT_CAMADA1, model_id=MODEL_ID_CAMADA1,
                    symbol=symbol, resolution_id=resolution_id, hyper=hyper, seed=seed,
                    feature_ids=feature_ids, device_type=device_type,
                )
                elapsed_s = time.time() - t0
                pooled, _ = _pooled_sharpe(folds, mf.data)
                per_seed.append({
                    "seed": seed, "pooled_sharpe": pooled, "reused": False,
                    "elapsed_seconds": elapsed_s,
                })
            seed_scores.append(pooled)
            logger.info(
                "validation.t2_t1_full_feature_stage2.seed_done",
                symbol=symbol, resolution_id=resolution_id, seed_index=i, pooled_sharpe=pooled,
            )

        median_sharpe = float(sorted(seed_scores)[len(seed_scores) // 2])
        screening_sharpe = candidate["pooled_sharpe"]
        result = {
            **{f: getattr(hyper, f) for f in _HYPER_FIELDS},
            "screening_pooled_sharpe": screening_sharpe,
            "median_pooled_sharpe": median_sharpe,
            "selection_bias_estimate": screening_sharpe - median_sharpe,
            "seed_scores": seed_scores,
            "per_seed": per_seed,
        }
        confirmed.append(result)
        logger.info(
            "validation.t2_t1_full_feature_stage2.candidate_confirmed",
            symbol=symbol, resolution_id=resolution_id,
            median_pooled_sharpe=median_sharpe, screening_pooled_sharpe=screening_sharpe,
            selection_bias_estimate=result["selection_bias_estimate"],
        )

    winner = max(confirmed, key=lambda c: c["median_pooled_sharpe"])
    n_new_trainings = len(top_k) * (_N_SEEDS_STAGE2 - 1)
    logger.info(
        "validation.t2_t1_full_feature_stage2.run_done",
        symbol=symbol, resolution_id=resolution_id,
        n_new_trainings=n_new_trainings, winner_median_pooled_sharpe=winner["median_pooled_sharpe"],
        winner_selection_bias_estimate=winner["selection_bias_estimate"],
    )
    return {
        "symbol": symbol, "resolution_id": resolution_id,
        "top_k": top_k, "confirmed": confirmed, "winner": winner,
        "n_new_trainings": n_new_trainings,
    }


def write_report_atomic(payload: dict[str, Any], *, symbol: str, resolution_id: str) -> Path:
    """B29 — `.tmp` -> `fsync` -> `rename`."""
    EXPERIMENTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = EXPERIMENTS_DIR / f"t2_t1_stage2_confirm_full_{symbol}_{resolution_id}.json"
    tmp_path = out_path.with_name(out_path.name + ".tmp")
    blob = orjson.dumps(payload, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS)
    with tmp_path.open("wb") as fh:
        fh.write(blob)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, out_path)
    logger.info("validation.t2_t1_full_feature_stage2.report_written", path=str(out_path))
    return out_path


def _run_cli() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="ADR-003 Estágio 2 -- confirmação top-3 por combo (k=62 T2 completo)"
    )
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--resolution-id", default="R1")
    parser.add_argument("--vol-estimator-id", default="parkinson_w20")
    parser.add_argument("--device-type", default="cpu")
    args = parser.parse_args()

    result = run_stage2_confirm(
        args.symbol, args.resolution_id,
        device_type=args.device_type, vol_estimator_id=args.vol_estimator_id,
    )
    out_path = write_report_atomic(result, symbol=args.symbol, resolution_id=args.resolution_id)
    logger.info(
        "validation.t2_t1_full_feature_stage2.cli_done",
        symbol=args.symbol, resolution_id=args.resolution_id,
        n_new_trainings=result["n_new_trainings"],
        winner_median_pooled_sharpe=result["winner"]["median_pooled_sharpe"],
        report_path=str(out_path),
    )
    return 0


if __name__ == "__main__":
    sys.exit(_run_cli())
