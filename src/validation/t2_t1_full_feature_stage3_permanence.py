"""ADR-003 (`docs/ADR-003_hiperparametro_feature_set_completo_2026-08-25.md`)
Estágio 3 — gate de permanência real (Camada1 vs Camada0, sem
permutação) sobre o vencedor do Estágio 2 de cada combo, repetido 5
seeds — critério de promoção = mediana de `n_better` >=
`alpha_layer1_permanence_min_paths`, nunca uma única realização (mesma
disciplina do ADR-002 Estágio 3).

Diferente do ADR-002: aqui o resultado NÃO decide se a promoção T2->T1
acontece (`AG-207`, decisão de negócio já ratificada) — só informa a
calibração final de hiperparâmetro por combo."""

from __future__ import annotations

import dataclasses
import os
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import orjson
import structlog

from src.features import build as features_build
from src.models import alpha, backtest_lite
from src.models._constants import load_constant
from src.models._paths import EXPERIMENTS_DIR
from src.models.pipeline import MODEL_ID_CAMADA0, MODEL_ID_CAMADA1
from src.validation.noise_floor_diagnostics import _build_mf_and_splits

logger = structlog.get_logger(__name__)

_N_SEEDS_STAGE3 = 5  # noqa: magic-number -- mesma disciplina do ADR-002

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


def _load_winner(symbol: str, resolution_id: str) -> dict[str, Any]:
    path = EXPERIMENTS_DIR / f"t2_t1_stage2_confirm_full_{symbol}_{resolution_id}.json"
    payload: dict[str, Any] = orjson.loads(path.read_bytes())
    winner: dict[str, Any] = payload["winner"]
    return winner


def run_stage3_permanence_gate(
    symbol: str,
    resolution_id: str,
    *,
    n_seeds: int = _N_SEEDS_STAGE3,
    device_type: str = "cpu",
    vol_estimator_id: str | None = None,
) -> dict[str, Any]:
    winner = _load_winner(symbol, resolution_id)
    feature_ids = features_build.SUPPORT_FEATURE_IDS
    mf, splits = _build_mf_and_splits(symbol, resolution_id, vol_estimator_id, feature_ids)
    base_hyper = alpha.LGBMHyperparams.from_constants()
    hyper = _candidate_to_hyper(winner, base_hyper)
    base_seed = int(load_constant("alpha_random_seed"))
    permanence_min_paths = int(load_constant("alpha_layer1_permanence_min_paths"))

    n_better_list: list[int] = []
    per_seed: list[dict[str, Any]] = []
    for i in range(n_seeds):
        seed = alpha._derived_seed(base_seed, 777_001, i)  # noqa: magic-number -- separa espaço de seed do Estágio 3, arbitrário, mesmo padrão do ADR-002
        t0 = time.time()
        c1_folds = alpha.run_all_folds(
            mf.data, splits, variant=alpha.VARIANT_CAMADA1, model_id=MODEL_ID_CAMADA1,
            symbol=symbol, resolution_id=resolution_id, hyper=hyper, seed=seed,
            feature_ids=feature_ids, device_type=device_type,
        )
        c0_folds = alpha.run_all_folds(
            mf.data, splits, variant=alpha.VARIANT_CAMADA0, model_id=MODEL_ID_CAMADA0,
            symbol=symbol, resolution_id=resolution_id, hyper=hyper, seed=seed,
            feature_ids=feature_ids, device_type=device_type,
        )
        elapsed_s = time.time() - t0
        c1_by_path = backtest_lite.backtest_by_path(c1_folds, mf.data)
        c0_by_path = backtest_lite.backtest_by_path(c0_folds, mf.data)
        n_better, n_total = backtest_lite.permanence_count(c1_by_path, c0_by_path)
        n_better_list.append(n_better)
        per_seed.append(
            {"seed": seed, "n_better": n_better, "n_total": n_total, "elapsed_seconds": elapsed_s}
        )
        logger.info(
            "validation.t2_t1_full_feature_stage3.seed_done",
            symbol=symbol, resolution_id=resolution_id, seed_index=i,
            n_better=n_better, n_total=n_total, elapsed_seconds=elapsed_s,
        )

    median_n_better = float(np.median(np.asarray(n_better_list, dtype=np.float64)))
    permanence_pass = median_n_better >= permanence_min_paths
    logger.info(
        "validation.t2_t1_full_feature_stage3.run_done",
        symbol=symbol, resolution_id=resolution_id,
        n_seeds=n_seeds, n_better_list=n_better_list, median_n_better=median_n_better,
        permanence_min_paths=permanence_min_paths, permanence_pass=permanence_pass,
    )
    return {
        "symbol": symbol, "resolution_id": resolution_id,
        "candidate": {f: winner[f] for f in _HYPER_FIELDS},
        "n_seeds": n_seeds, "n_better_list": n_better_list, "median_n_better": median_n_better,
        "permanence_min_paths_threshold": permanence_min_paths, "permanence_pass": permanence_pass,
        "per_seed": per_seed,
    }


def write_report_atomic(payload: dict[str, Any], *, symbol: str, resolution_id: str) -> Path:
    """B29 — `.tmp` -> `fsync` -> `rename`."""
    EXPERIMENTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = EXPERIMENTS_DIR / f"t2_t1_stage3_permanence_full_{symbol}_{resolution_id}.json"
    tmp_path = out_path.with_name(out_path.name + ".tmp")
    blob = orjson.dumps(payload, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS)
    with tmp_path.open("wb") as fh:
        fh.write(blob)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, out_path)
    logger.info("validation.t2_t1_full_feature_stage3.report_written", path=str(out_path))
    return out_path


def _run_cli() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="ADR-003 Estágio 3 -- gate de permanência por combo (k=62 T2 completo)"
    )
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--resolution-id", default="R1")
    parser.add_argument("--vol-estimator-id", default="parkinson_w20")
    parser.add_argument("--device-type", default="cpu")
    args = parser.parse_args()

    result = run_stage3_permanence_gate(
        args.symbol, args.resolution_id,
        device_type=args.device_type, vol_estimator_id=args.vol_estimator_id,
    )
    out_path = write_report_atomic(result, symbol=args.symbol, resolution_id=args.resolution_id)
    logger.info(
        "validation.t2_t1_full_feature_stage3.cli_done",
        symbol=args.symbol, resolution_id=args.resolution_id,
        median_n_better=result["median_n_better"], permanence_pass=result["permanence_pass"],
        report_path=str(out_path),
    )
    return 0


if __name__ == "__main__":
    sys.exit(_run_cli())
