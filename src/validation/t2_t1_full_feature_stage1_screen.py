"""ADR-003 (`docs/ADR-003_hiperparametro_feature_set_completo_2026-08-25.md`)
Estágio 1 — screening por combinação símbolo×resolução, `k=62`
(`SUPPORT_FEATURE_IDS` completo, SUBSTITUINDO os 7 `T1_FEATURE_IDS` no
vetor de treino, mesma convenção de Fase 1/Fase 2/ADR-002).

Grid estrutural (`max_depth`×`num_leaves`×`min_child_samples`, mesmos 12
pontos do Estágio 0) — Estágio 0 já rodou 2 combos (BTCUSDT/R3,
XRPUSDT/R1) e DIVERGIU na direção (BTCUSDT/R3 prefere `num_leaves=2`;
XRPUSDT/R1 prefere `num_leaves=3`, com `min_child_samples` melhor em
valores mais altos, mas a extensão de fronteira de `min_child_samples`
até 6000 mostrou variação da ordem do ruído de 1 seed (-2,83/-2,98/-2,54
em mcs=3000/4000/6000, spread ~0,43, mesma ordem de grandeza do σ≈0,3
medido na Fase 0a) — teto de `min_child_samples` mantido em 2000 por
decisão MEDIDA, não presumida (B23): estender mais estaria perseguindo
ruído de 1 seed, não sinal estrutural real.

Por isso: grid CHEIO (12 pontos, não estreito) em TODOS os 10 combos —
regra de decisão do ADR-003 Estágio 0 (divergência → grid cheio).
Reusa o resultado já persistido de `t2_t1_stage0_probe_{symbol}_
{resolution_id}.json` quando existir (BTCUSDT/R3, XRPUSDT/R1) — 0 custo
de retreino pra esses 2.

Depois do grid, coordenada-descendente sobre os 5 hiperparâmetros do
ADR-002 (`learning_rate`/`subsample`/`feature_fraction`/`lambda_l2`/
`n_estimators`), ancorado no melhor ponto do grid PRÓPRIO de cada combo
(não reusa a âncora k=32 de ETHUSDT/R1 — k mudou pra 62, âncora antiga
não se aplica). 1 seed só — screening, mesmo tratamento de viés de
seleção do ADR-002 (Estágio 2 confirma por mediana, não decide aqui)."""

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

# Mesmos 12 pontos do Estágio 0 -- teto de min_child_samples=2000 MEDIDO
# (não presumido, ver docstring do módulo) como o ponto onde a sondagem de
# fronteira passa a ser dominada por ruído de 1 seed, não sinal real.
_DEPTH_LEAVES_GRID: tuple[tuple[int, int], ...] = ((2, 2), (2, 3), (3, 3))  # noqa: magic-number -- grade de busca declarada a priori (ADR-003), não constante de domínio
_MIN_CHILD_SAMPLES_GRID: tuple[int, ...] = (20, 500, 1000, 2000)  # noqa: magic-number -- idem

_LEARNING_RATE_GRID: tuple[float, ...] = (0.01, 0.05, 0.08)  # noqa: magic-number -- idem, PROD=0.03 cacheado no âncora
_SUBSAMPLE_GRID: tuple[float, ...] = (0.6, 0.9, 1.0)  # noqa: magic-number -- idem, PROD=0.8 cacheado
# feature_fraction -- estendido pra baixo de (0.6,0.8) pra (0.3,0.5,0.8), AG-217
# (2026-08-25): com k=62 (~9x o k=7 que justificava feature_fraction=1.0 fixo,
# B19), colunas por árvore em 0,3 ainda são ~19 -- amostragem de coluna genuína
# em vez de decorrelação só por linha (subsample). Não decide a interação com
# B19/Camada 3 (fora de escopo desta rodada), só mede.
_FEATURE_FRACTION_GRID: tuple[float, ...] = (0.3, 0.5, 0.8)  # noqa: magic-number -- idem, PROD=1.0 (teto) cacheado
_LAMBDA_L2_GRID: tuple[float, ...] = (1.0, 10.0, 20.0)  # noqa: magic-number -- idem, PROD=5.0 cacheado
_N_ESTIMATORS_GRID: tuple[int, ...] = (150, 500)  # noqa: magic-number -- idem, PROD=300 cacheado
# min_sum_hessian_in_leaf -- AG-217/AG-208 (2026-08-25): nunca variado antes,
# PROD=0,001 (default de biblioteca) é inerte sob sample_weight de cauda longa
# (hessiana por amostra <= 0,25*w). sweep_range já declarado em constants.yaml
# ([0.001, 5.0]) -- 3 pontos dentro dele, não um range novo inventado (B23).
_MIN_SUM_HESSIAN_GRID: tuple[float, ...] = (0.1, 1.0, 5.0)  # noqa: magic-number -- idem, PROD=0.001 cacheado


def _load_cached_stage0(symbol: str, resolution_id: str) -> dict[str, Any] | None:
    path = EXPERIMENTS_DIR / f"t2_t1_stage0_probe_{symbol}_{resolution_id}.json"
    if not path.exists():
        return None
    payload: dict[str, Any] = orjson.loads(path.read_bytes())
    return payload


def _run_structural_grid(
    symbol: str,
    resolution_id: str,
    mf: Any,
    splits: Any,
    feature_ids: tuple[str, ...],
    base_hyper: Any,
    seed: int,
    device_type: str,
) -> list[dict[str, Any]]:
    cached = _load_cached_stage0(symbol, resolution_id)
    if cached is not None:
        logger.info(
            "validation.t2_t1_stage1.structural_grid_reused",
            symbol=symbol, resolution_id=resolution_id, n_trials=len(cached["trials"]),
        )
        return [dict(t, reused_from_stage0=True) for t in cached["trials"]]

    trials: list[dict[str, Any]] = []
    for max_depth, num_leaves in _DEPTH_LEAVES_GRID:
        for min_child_samples in _MIN_CHILD_SAMPLES_GRID:
            hyper = dataclasses.replace(
                base_hyper, max_depth=max_depth, num_leaves=num_leaves,
                min_child_samples=min_child_samples,
            )
            t0 = time.time()
            folds = alpha.run_all_folds(
                mf.data, splits, variant=alpha.VARIANT_CAMADA1, model_id=MODEL_ID_CAMADA1,
                symbol=symbol, resolution_id=resolution_id, hyper=hyper, seed=seed,
                feature_ids=feature_ids, device_type=device_type,
            )
            elapsed_s = time.time() - t0
            pooled, by_path = _pooled_sharpe(folds, mf.data)
            trial = {
                "max_depth": max_depth, "num_leaves": num_leaves,
                "min_child_samples": min_child_samples, "pooled_sharpe": pooled,
                "sharpe_by_path": by_path, "elapsed_seconds": elapsed_s,
                "reused_from_stage0": False,
            }
            trials.append(trial)
            logger.info(
                "validation.t2_t1_stage1.structural_trial_done",
                symbol=symbol, resolution_id=resolution_id, max_depth=max_depth,
                num_leaves=num_leaves, min_child_samples=min_child_samples,
                pooled_sharpe=pooled, elapsed_seconds=elapsed_s,
            )
    return trials


def run_stage1_screen(
    symbol: str,
    resolution_id: str,
    *,
    device_type: str = "cpu",
    vol_estimator_id: str | None = None,
) -> dict[str, Any]:
    feature_ids = features_build.SUPPORT_FEATURE_IDS
    mf, splits = _build_mf_and_splits(symbol, resolution_id, vol_estimator_id, feature_ids)
    base_hyper = alpha.LGBMHyperparams.from_constants()
    seed = int(load_constant("alpha_random_seed"))

    structural_trials = _run_structural_grid(
        symbol, resolution_id, mf, splits, feature_ids, base_hyper, seed, device_type,
    )
    grid_best = max(structural_trials, key=lambda t: t["pooled_sharpe"])
    anchor_hyper = dataclasses.replace(
        base_hyper,
        max_depth=grid_best["max_depth"],
        num_leaves=grid_best["num_leaves"],
        min_child_samples=grid_best["min_child_samples"],
    )

    dims: tuple[tuple[str, tuple[Any, ...]], ...] = (
        ("learning_rate", _LEARNING_RATE_GRID),
        ("subsample", _SUBSAMPLE_GRID),
        ("feature_fraction", _FEATURE_FRACTION_GRID),
        ("lambda_l2", _LAMBDA_L2_GRID),
        ("n_estimators", _N_ESTIMATORS_GRID),
        ("min_sum_hessian_in_leaf", _MIN_SUM_HESSIAN_GRID),
    )

    anchor_trial = {
        "max_depth": anchor_hyper.max_depth, "num_leaves": anchor_hyper.num_leaves,
        "min_child_samples": anchor_hyper.min_child_samples,
        "learning_rate": anchor_hyper.learning_rate, "subsample": anchor_hyper.subsample,
        "feature_fraction": anchor_hyper.feature_fraction, "lambda_l2": anchor_hyper.lambda_l2,
        "n_estimators": anchor_hyper.n_estimators,
        "min_sum_hessian_in_leaf": anchor_hyper.min_sum_hessian_in_leaf,
        "pooled_sharpe": grid_best["pooled_sharpe"], "sharpe_by_path": grid_best["sharpe_by_path"],
        "reused_from_structural_grid": True,
    }
    hyper_trials: list[dict[str, Any]] = [anchor_trial]
    for field_name, grid in dims:
        for value in grid:
            hyper = dataclasses.replace(anchor_hyper, **{field_name: value})
            t0 = time.time()
            folds = alpha.run_all_folds(
                mf.data, splits, variant=alpha.VARIANT_CAMADA1, model_id=MODEL_ID_CAMADA1,
                symbol=symbol, resolution_id=resolution_id, hyper=hyper, seed=seed,
                feature_ids=feature_ids, device_type=device_type,
            )
            elapsed_s = time.time() - t0
            pooled, by_path = _pooled_sharpe(folds, mf.data)
            trial = {
                "max_depth": hyper.max_depth, "num_leaves": hyper.num_leaves,
                "min_child_samples": hyper.min_child_samples,
                "learning_rate": hyper.learning_rate, "subsample": hyper.subsample,
                "feature_fraction": hyper.feature_fraction, "lambda_l2": hyper.lambda_l2,
                "n_estimators": hyper.n_estimators,
                "min_sum_hessian_in_leaf": hyper.min_sum_hessian_in_leaf,
                "pooled_sharpe": pooled, "sharpe_by_path": by_path,
                "elapsed_seconds": elapsed_s, "reused_from_structural_grid": False,
                "varied_dimension": field_name,
            }
            hyper_trials.append(trial)
            logger.info(
                "validation.t2_t1_stage1.hyperparam_trial_done",
                symbol=symbol, resolution_id=resolution_id, varied_dimension=field_name,
                value=value, pooled_sharpe=pooled, elapsed_seconds=elapsed_s,
            )

    best = max(hyper_trials, key=lambda t: t["pooled_sharpe"])
    n_new = sum(1 for t in structural_trials if not t.get("reused_from_stage0", False)) + sum(
        1 for t in hyper_trials if not t.get("reused_from_structural_grid", False)
    )
    logger.info(
        "validation.t2_t1_stage1.run_done",
        symbol=symbol, resolution_id=resolution_id,
        n_structural_trials=len(structural_trials), n_hyperparam_trials=len(hyper_trials),
        n_new_trainings=n_new, best_pooled_sharpe=best["pooled_sharpe"],
    )
    return {
        "symbol": symbol, "resolution_id": resolution_id, "n_features": len(feature_ids),
        "structural_trials": structural_trials, "hyperparam_trials": hyper_trials,
        "grid_best": grid_best, "best_trial": best, "n_new_trainings": n_new,
    }


def write_report_atomic(payload: dict[str, Any], *, symbol: str, resolution_id: str) -> Path:
    """B29 — `.tmp` -> `fsync` -> `rename`."""
    EXPERIMENTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = EXPERIMENTS_DIR / f"t2_t1_stage1_screen_{symbol}_{resolution_id}.json"
    tmp_path = out_path.with_name(out_path.name + ".tmp")
    blob = orjson.dumps(payload, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS)
    with tmp_path.open("wb") as fh:
        fh.write(blob)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, out_path)
    logger.info("validation.t2_t1_stage1.report_written", path=str(out_path))
    return out_path


def _run_cli() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="ADR-003 Estágio 1 -- screening por combo (k=62 T2 completo)"
    )
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--resolution-id", default="R1")
    parser.add_argument("--vol-estimator-id", default="parkinson_w20")
    parser.add_argument("--device-type", default="cpu")
    args = parser.parse_args()

    result = run_stage1_screen(
        args.symbol, args.resolution_id,
        device_type=args.device_type, vol_estimator_id=args.vol_estimator_id,
    )
    out_path = write_report_atomic(result, symbol=args.symbol, resolution_id=args.resolution_id)
    logger.info(
        "validation.t2_t1_stage1.cli_done",
        symbol=args.symbol, resolution_id=args.resolution_id,
        n_new_trainings=result["n_new_trainings"],
        best_trial={
            "max_depth": result["best_trial"]["max_depth"],
            "num_leaves": result["best_trial"]["num_leaves"],
            "min_child_samples": result["best_trial"]["min_child_samples"],
            "learning_rate": result["best_trial"]["learning_rate"],
            "n_estimators": result["best_trial"]["n_estimators"],
            "pooled_sharpe": result["best_trial"]["pooled_sharpe"],
        },
        report_path=str(out_path),
    )
    return 0


if __name__ == "__main__":
    sys.exit(_run_cli())
