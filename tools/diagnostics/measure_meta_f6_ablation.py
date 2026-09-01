"""F6 — Ablação real (§9) contra os 5 combos de produção — `docs/
meta_model_design_doc_2026-08-22.md`.

Roda `meta.run_meta_sprint` + `meta_ablation.run_ablation_for_combo` pros
5 combos com hiperparâmetro de produção confirmado (`config/constants.
yaml::alpha_production_hyperparam_override`). `predictions.parquet` já
existe em disco (mesmo achado do P2/P3 — zero retreino).

**Critério primário do §9 (não o secundário de paths)**: "os 5 paths não
são replicações independentes... o primário é permanência sobre os 5
SÍMBOLOS". Este script reporta os dois — o `n_paths_passed` por combo
(secundário) E a contagem de quantos dos 5 SÍMBOLOS têm `gate_passed ==
True` (primário)."""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Final

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import structlog

from src.io import artifact as io_artifact
from src.models import alpha
from src.models import dataset as ds
from src.models import hyperparams_by_combo as hbc
from src.models import meta as meta_mod
from src.models import meta_ablation as ab
from src.models._paths import ARTIFACT_ROOT
from src.models.pipeline import MODEL_ID_CAMADA1
from src.validation import cpcv

logger = structlog.get_logger(__name__)

_COMBOS: tuple[tuple[str, str], ...] = (
    ("BTCUSDT", "R2"),
    ("SOLUSDT", "R2"),
    ("SOLUSDT", "R3"),
    ("XRPUSDT", "R2"),
    ("XRPUSDT", "R3"),
)
_VOL_ESTIMATOR_ID = "parkinson_w20"
_N_SEEDS = 200
_SEED_BASE = 20260901

_OUT_PATH = _REPO_ROOT / "experiments" / "meta_f6_ablation_2026-09-01.json"


def _config_hash_camada1(symbol: str, resolution_id: str) -> str:
    hyper = hbc.load_production_override(symbol, resolution_id, alpha.VARIANT_CAMADA1)
    if hyper is None:
        raise ValueError(f"sem override de producao para {symbol}/{resolution_id}/camada1")
    cfg: dict[str, Any] = {
        "variant": alpha.VARIANT_CAMADA1,
        "tau_policy": alpha.TAU_POLICY_LEGACY_PER_SIDE,
        "calib_split_mode": alpha.CALIB_SPLIT_TEMPORAL_PURGED,
        "class_balance_basis": alpha.CLASS_BALANCE_WEIGHT,
        "calib_weight_basis": alpha.CALIB_WEIGHT_UNIQUENESS,
        "hyper": asdict(hyper),
    }
    full_cfg = {"model_id": MODEL_ID_CAMADA1, **cfg}
    return io_artifact.compute_config_hash(
        full_cfg, schema_version=alpha.PREDICTIONS_ARTIFACT_SCHEMA.schema_version
    )


def _run_combo(symbol: str, resolution_id: str) -> dict[str, Any]:
    config_hash = _config_hash_camada1(symbol, resolution_id)
    predictions, _manifest = io_artifact.read_artifact(
        root=ARTIFACT_ROOT,
        stage="predictions_alpha",
        config_hash=config_hash,
        symbol=symbol,
        resolution=resolution_id,
    )
    mf = ds.build_modeling_frame(
        symbol=symbol, resolution_id=resolution_id, vol_estimator_id=_VOL_ESTIMATOR_ID
    )
    result = cpcv.generate_splits(
        mf.data, config=cpcv.CPCVConfig.from_constants(grade_id=resolution_id), symbol=symbol
    )

    sprint = meta_mod.run_meta_sprint(
        symbol=symbol,
        resolution_id=resolution_id,
        variant="camada1",
        predictions=predictions,
        dense=mf.data,
        cpcv_result=result,
        alpha_model_id="alpha_c1_v1",
        regime_source="quantile_classifier_v1",
    )

    random_state = _SEED_BASE + hash((symbol, resolution_id)) % 10_000
    ablation = ab.run_ablation_for_combo(
        sprint["fold_results"],
        sprint["meta_training_set"],
        symbol=symbol,
        resolution_id=resolution_id,
        variant="camada1",
        n_seeds=_N_SEEDS,
        random_state=random_state,
    )

    logger.info(
        "meta_f6_ablation.combo_concluido",
        symbol=symbol,
        resolution_id=resolution_id,
        n_folds_ok=sprint["n_folds_ok"],
        n_folds=sprint["n_folds"],
        n_paths_passed=ablation.n_paths_passed,
        n_paths_total=ablation.n_paths_total,
        exposure_reduction_suspected=ablation.exposure_reduction_suspected,
        gate_passed=ablation.gate_passed,
    )

    return {
        "symbol": symbol,
        "resolution_id": resolution_id,
        "n_folds": sprint["n_folds"],
        "n_folds_ok": sprint["n_folds_ok"],
        "n_folds_insufficient_sample": sprint["n_folds_insufficient_sample"],
        "n_paths_passed": ablation.n_paths_passed,
        "n_paths_total": ablation.n_paths_total,
        "min_paths_required": ablation.min_paths_required,
        "exposure_reduction_suspected": ablation.exposure_reduction_suspected,
        "gate_passed": ablation.gate_passed,
        "path_results": [
            {
                "path_id": pr.path_id,
                "n_folds": pr.n_folds,
                "n_folds_ok": pr.n_folds_ok,
                "sharpe_a0": pr.panel_a0.sharpe_naive,
                "sharpe_a1": pr.panel_a1.sharpe_naive,
                "sharpe_a3": pr.panel_a3.sharpe_naive,
                "p95_null_a2": pr.p95_null_a2,
                "n_null_seeds": int(pr.null_sharpes_a2.shape[0]),
                "jaccard_a1_a3": pr.jaccard_a1_a3,
                "pass_rate_a1": pr.panel_a1.pass_rate,
                "pass_rate_a0": pr.panel_a0.pass_rate,
                "accuracy_unweighted_a1": pr.panel_a1.accuracy_unweighted,
                "base_rate_unweighted": pr.panel_a1.base_rate_unweighted,
                "passed": pr.passed,
            }
            for pr in ablation.path_results
        ],
    }


def main() -> int:
    t_start = time.time()
    results: list[dict[str, Any]] = []
    for symbol, resolution_id in _COMBOS:
        results.append(_run_combo(symbol, resolution_id))

    n_symbols_gate_passed = sum(1 for r in results if r["gate_passed"])
    total_elapsed_s = time.time() - t_start
    payload: dict[str, Any] = {
        "_schema": "meta_f6_ablation/1.0.0",
        "_gerado_por": "tools/diagnostics/measure_meta_f6_ablation.py",
        "_proposito": (
            "F6 do Meta-model (docs/meta_model_design_doc_2026-08-22.md Sec9) -- "
            "ablacao real (A0/A1/A2-nulo/A3-gate) sobre os 5 combos de producao "
            "reais. Criterio PRIMARIO (Sec9, correcao 'aplicando Sec4.6'): "
            "permanencia sobre os 5 SIMBOLOS, nao sobre os paths (secundario)."
        ),
        "_n_seeds": _N_SEEDS,
        "_seed_base": _SEED_BASE,
        "n_combos": len(results),
        "n_symbols_gate_passed_primario": n_symbols_gate_passed,
        "n_symbols_total": len(results),
        "total_elapsed_s": total_elapsed_s,
        "combos": results,
    }

    _OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = _OUT_PATH.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, _OUT_PATH)

    logger.info(
        "meta_f6_ablation.concluido",
        n_combos=len(results),
        n_symbols_gate_passed_primario=n_symbols_gate_passed,
        out_path=str(_OUT_PATH),
        total_elapsed_s=round(total_elapsed_s, 1),
    )
    return 0 if n_symbols_gate_passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
