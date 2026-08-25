"""Confirmação da Fase 2 (`docs/t2_t1_ablation_veredito_duas_analises_
2026-08-24.md` §4) sobre o vencedor `k=32, max_depth=2, num_leaves=3,
min_child_samples=500` (`experiments/t2_t1_capacity_map_fase2_ETHUSDT_R1.
json::best_trial`) -- 2 testes que a Fase 2 deixou pendentes, ambos
obrigatórios antes de qualquer decisão de promoção ou generalização pra
outras combinações símbolo×resolução:

- **Repetição de seed** (mesmo desenho de `noise_floor_diagnostics.py::
  run_seed_repetition`, mas travado no config vencedor da Fase 2, não em
  `k=7`/PROD) -- confirma se `pooled_sharpe=-1,5945` é ponto real ou sorte
  de 1 seed. Sem isso, o "-0,75 desvio-padrão do piso de ruído" reportado
  na Fase 2 é uma leitura de 1 amostra só.
- **Gate de permanência REAL** (Camada1 vs Camada0, dado REAL, SEM
  permutação -- diferente da Fase 0b, que testava o nulo por permutação) --
  responde se essa configuração de fato bateria o critério de produção
  (`alpha_layer1_permanence_min_paths`), a pergunta que nem a Fase 1 nem a
  Fase 2 tentaram responder (as duas só mediram a FORMA da superfície de
  Sharpe da Camada1 isolada)."""

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

from src.models import alpha, backtest_lite
from src.models._constants import load_constant
from src.models._paths import EXPERIMENTS_DIR
from src.models.pipeline import MODEL_ID_CAMADA0, MODEL_ID_CAMADA1
from src.validation.noise_floor_diagnostics import (
    _build_mf_and_splits,
    _mean_finite,
    _pooled_sharpe,
)

logger = structlog.get_logger(__name__)

# Vencedor da Fase 2 -- experiments/t2_t1_capacity_map_fase2_ETHUSDT_R1.json::best_trial
_WINNER_K = 32
_WINNER_MAX_DEPTH = 2
_WINNER_NUM_LEAVES = 3
_WINNER_MIN_CHILD_SAMPLES = 500


def _load_winner_feature_set(symbol: str, resolution_id: str) -> tuple[str, ...]:
    path = EXPERIMENTS_DIR / f"t2_ranking_ortogonalidade_{symbol}_{resolution_id}.json"
    payload = orjson.loads(path.read_bytes())
    survivors: list[str] = payload["survivors_ortogonalidade"]
    return tuple(survivors[:_WINNER_K])


def _winner_hyper() -> alpha.LGBMHyperparams:
    base = alpha.LGBMHyperparams.from_constants()
    return dataclasses.replace(
        base,
        max_depth=_WINNER_MAX_DEPTH,
        num_leaves=_WINNER_NUM_LEAVES,
        min_child_samples=_WINNER_MIN_CHILD_SAMPLES,
    )


def run_seed_repetition_fase2(
    symbol: str,
    resolution_id: str,
    *,
    n_repeats: int = 10,
    device_type: str = "cpu",
    vol_estimator_id: str | None = None,
) -> dict[str, Any]:
    feature_ids = _load_winner_feature_set(symbol, resolution_id)
    mf, splits = _build_mf_and_splits(symbol, resolution_id, vol_estimator_id, feature_ids)
    hyper = _winner_hyper()

    pooled_sharpes: list[float] = []
    per_repeat: list[dict[str, Any]] = []
    for i in range(n_repeats):
        seed = alpha._derived_seed(int(load_constant("alpha_random_seed")), i)
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
        pooled_sharpes.append(pooled)
        per_repeat.append(
            {"repeat": i, "seed": seed, "pooled_sharpe": pooled, "sharpe_by_path": by_path,
             "elapsed_seconds": elapsed_s}
        )
        logger.info(
            "validation.t2_t1_fase2_confirmation.seed_repetition_done",
            repeat=i, pooled_sharpe=pooled, elapsed_seconds=elapsed_s,
        )

    std = (
        float(np.std(np.asarray(pooled_sharpes, dtype=np.float64), ddof=1))
        if len(pooled_sharpes) >= 2
        else float("nan")
    )
    return {
        "experiment": "fase2_confirmation_seed_repetition",
        "symbol": symbol, "resolution_id": resolution_id,
        "k": _WINNER_K, "max_depth": _WINNER_MAX_DEPTH,
        "num_leaves": _WINNER_NUM_LEAVES, "min_child_samples": _WINNER_MIN_CHILD_SAMPLES,
        "n_repeats": n_repeats,
        "pooled_sharpe_mean": _mean_finite(pooled_sharpes),
        "pooled_sharpe_std": std,
        "per_repeat": per_repeat,
    }


def run_permanence_check_fase2(
    symbol: str,
    resolution_id: str,
    *,
    device_type: str = "cpu",
    vol_estimator_id: str | None = None,
) -> dict[str, Any]:
    feature_ids = _load_winner_feature_set(symbol, resolution_id)
    mf, splits = _build_mf_and_splits(symbol, resolution_id, vol_estimator_id, feature_ids)
    hyper = _winner_hyper()
    model_seed = int(load_constant("alpha_random_seed"))

    t0 = time.time()
    c1_folds = alpha.run_all_folds(
        mf.data, splits,
        variant=alpha.VARIANT_CAMADA1,
        model_id=MODEL_ID_CAMADA1,
        symbol=symbol,
        resolution_id=resolution_id,
        hyper=hyper,
        seed=model_seed,
        feature_ids=feature_ids,
        device_type=device_type,
    )
    c0_folds = alpha.run_all_folds(
        mf.data, splits,
        variant=alpha.VARIANT_CAMADA0,
        model_id=MODEL_ID_CAMADA0,
        symbol=symbol,
        resolution_id=resolution_id,
        hyper=hyper,
        seed=model_seed,
        feature_ids=feature_ids,
        device_type=device_type,
    )
    elapsed_s = time.time() - t0

    c1_by_path = backtest_lite.backtest_by_path(c1_folds, mf.data)
    c0_by_path = backtest_lite.backtest_by_path(c0_folds, mf.data)
    n_better, n_total = backtest_lite.permanence_count(c1_by_path, c0_by_path)
    permanence_min_paths = int(load_constant("alpha_layer1_permanence_min_paths"))

    result = {
        "experiment": "fase2_confirmation_permanence_real",
        "symbol": symbol, "resolution_id": resolution_id,
        "k": _WINNER_K, "max_depth": _WINNER_MAX_DEPTH,
        "num_leaves": _WINNER_NUM_LEAVES, "min_child_samples": _WINNER_MIN_CHILD_SAMPLES,
        "n_better": n_better, "n_total": n_total,
        "permanence_min_paths_threshold": permanence_min_paths,
        "permanence_pass": n_better >= permanence_min_paths,
        "camada1_sharpe_by_path": {str(pid): r.sharpe_naive for pid, r in c1_by_path.items()},
        "camada0_sharpe_by_path": {str(pid): r.sharpe_naive for pid, r in c0_by_path.items()},
        "elapsed_seconds": elapsed_s,
    }
    logger.info(
        "validation.t2_t1_fase2_confirmation.permanence_done",
        n_better=n_better, n_total=n_total,
        permanence_pass=result["permanence_pass"], elapsed_seconds=elapsed_s,
    )
    return result


def write_report_atomic(payload: dict[str, Any], *, symbol: str, resolution_id: str) -> Path:
    """B29 — `.tmp` -> `fsync` -> `rename`."""
    EXPERIMENTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = EXPERIMENTS_DIR / f"t2_t1_fase2_confirmation_{symbol}_{resolution_id}.json"
    tmp_path = out_path.with_name(out_path.name + ".tmp")
    blob = orjson.dumps(payload, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS)
    with tmp_path.open("wb") as fh:
        fh.write(blob)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, out_path)
    logger.info("validation.t2_t1_fase2_confirmation.report_written", path=str(out_path))
    return out_path


def _run_cli() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Confirmação da Fase 2 -- ablação T2->T1 do Alpha")
    parser.add_argument("--symbol", default="ETHUSDT")
    parser.add_argument("--resolution-id", default="R1")
    parser.add_argument("--vol-estimator-id", default="parkinson_w20")
    parser.add_argument("--device-type", default="cpu")
    parser.add_argument("--n-repeats", type=int, default=10)
    args = parser.parse_args()

    t_start = time.time()
    seed_repetition = run_seed_repetition_fase2(
        args.symbol, args.resolution_id,
        n_repeats=args.n_repeats, device_type=args.device_type,
        vol_estimator_id=args.vol_estimator_id,
    )
    permanence_real = run_permanence_check_fase2(
        args.symbol, args.resolution_id,
        device_type=args.device_type, vol_estimator_id=args.vol_estimator_id,
    )
    payload = {
        "symbol": args.symbol, "resolution_id": args.resolution_id,
        "total_elapsed_seconds": time.time() - t_start,
        "seed_repetition": seed_repetition,
        "permanence_real": permanence_real,
    }
    out_path = write_report_atomic(payload, symbol=args.symbol, resolution_id=args.resolution_id)
    logger.info(
        "validation.t2_t1_fase2_confirmation.cli_done",
        pooled_sharpe_mean=seed_repetition["pooled_sharpe_mean"],
        pooled_sharpe_std=seed_repetition["pooled_sharpe_std"],
        n_better=permanence_real["n_better"],
        n_total=permanence_real["n_total"],
        permanence_pass=permanence_real["permanence_pass"],
        report_path=str(out_path),
    )
    return 0


if __name__ == "__main__":
    sys.exit(_run_cli())
