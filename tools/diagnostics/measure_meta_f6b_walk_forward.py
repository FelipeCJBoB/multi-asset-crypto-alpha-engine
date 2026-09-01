"""F6b — ablação real do Meta replicada sobre walk-forward ancorado
(§4.4) contra os 5 combos de produção — `docs/meta_model_design_
doc_2026-08-22.md`.

Gate declarado no §4.4: "Se A1 > p95(A2) sob CPCV mas não sob WF, o
resultado CPCV é artefato." F6 (`AG-409`) já reprovou sob CPCV (0/5
símbolos) -- este script confirma (ou refuta) a MESMA reprovação sob a
estrutura de erro causal real de produção. Split ÚNICO por combo
(decisão do Manager, 2026-09-01) -- ver `src/models/meta_walk_
forward.py` para a justificativa completa."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Final

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import structlog

from src.models import alpha
from src.models import dataset as ds
from src.models import hyperparams_by_combo as hbc
from src.models import meta_walk_forward as mwf
from src.models._constants import load_constant

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

_OUT_PATH = _REPO_ROOT / "experiments" / "meta_f6b_walk_forward_2026-09-01.json"


def _run_combo(symbol: str, resolution_id: str) -> dict[str, Any]:
    hyper = hbc.load_production_override(symbol, resolution_id, alpha.VARIANT_CAMADA1)
    if hyper is None:
        raise ValueError(f"sem override de producao para {symbol}/{resolution_id}/camada1")

    mf = ds.build_modeling_frame(
        symbol=symbol, resolution_id=resolution_id, vol_estimator_id=_VOL_ESTIMATOR_ID
    )
    # Mesma seed base de producao (`alpha_random_seed`), nao um valor
    # inventado -- `LGBMHyperparams` nao carrega seed (e parametro
    # separado de `run_fold`/`run_walk_forward_for_combo`).
    seed = int(load_constant("alpha_random_seed"))
    random_state = _SEED_BASE + hash((symbol, resolution_id)) % 10_000

    resultado = mwf.run_meta_walk_forward_ablation_for_combo(
        mf.data,
        symbol=symbol,
        resolution_id=resolution_id,
        variant="camada1",
        hyper=hyper,
        alpha_model_id="alpha_c1_v1",
        seed=seed,
        n_seeds=_N_SEEDS,
        random_state=random_state,
    )
    ablation = resultado["ablation"]
    fold_result = resultado["meta_fold_result"]
    wf_result = resultado["wf_result"]

    logger.info(
        "meta_f6b.combo_concluido",
        symbol=symbol,
        resolution_id=resolution_id,
        meta_fold_status=fold_result.fold_status,
        gate_passed=ablation.gate_passed,
    )

    path_result = ablation.path_results[0] if ablation.path_results else None
    return {
        "symbol": symbol,
        "resolution_id": resolution_id,
        "n_wf_folds_alpha_usados": wf_result.n_folds_usados,
        "n_wf_folds_alpha_total": wf_result.n_folds_total,
        "n_train_meta": resultado["meta_table"].filter(
            resultado["meta_table"]["role"] == "train"
        ).height,
        "n_test_meta": resultado["meta_table"].filter(
            resultado["meta_table"]["role"] == "test"
        ).height,
        "meta_fold_status": fold_result.fold_status,
        "gate_passed": ablation.gate_passed,
        "exposure_reduction_suspected": ablation.exposure_reduction_suspected,
        "path_result": (
            {
                "sharpe_a0": path_result.panel_a0.sharpe_naive,
                "sharpe_a1": path_result.panel_a1.sharpe_naive,
                "sharpe_a3": path_result.panel_a3.sharpe_naive,
                "p95_null_a2": path_result.p95_null_a2,
                "n_null_seeds": int(path_result.null_sharpes_a2.shape[0]),
                "jaccard_a1_a3": path_result.jaccard_a1_a3,
                "pass_rate_a1": path_result.panel_a1.pass_rate,
                "pass_rate_a0": path_result.panel_a0.pass_rate,
                "accuracy_unweighted_a1": path_result.panel_a1.accuracy_unweighted,
                "base_rate_unweighted": path_result.panel_a1.base_rate_unweighted,
                "passed": path_result.passed,
            }
            if path_result is not None
            else None
        ),
    }


def main() -> int:
    t_start = time.time()
    results: list[dict[str, Any]] = []
    for symbol, resolution_id in _COMBOS:
        results.append(_run_combo(symbol, resolution_id))

    n_gate_passed = sum(1 for r in results if r["gate_passed"])
    total_elapsed_s = time.time() - t_start
    payload: dict[str, Any] = {
        "_schema": "meta_f6b_walk_forward/1.0.0",
        "_gerado_por": "tools/diagnostics/measure_meta_f6b_walk_forward.py",
        "_proposito": (
            "F6b do Meta-model (docs/meta_model_design_doc_2026-08-22.md Sec4.4) -- "
            "ablacao replicada sobre a timeline OOS causal do Alpha (walk-forward "
            "ancorado), split UNICO por combo (decisao do Manager 2026-09-01). "
            "Gate declarado: se A1 > p95(A2) sob CPCV mas nao sob WF, o resultado "
            "CPCV e artefato -- F6 (AG-409) ja reprovou sob CPCV, este script "
            "confirma/refuta a mesma reprovacao sob a estrutura causal real."
        ),
        "_n_seeds": _N_SEEDS,
        "_seed_base": _SEED_BASE,
        "n_combos": len(results),
        "n_gate_passed": n_gate_passed,
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
        "meta_f6b.concluido",
        n_combos=len(results),
        n_gate_passed=n_gate_passed,
        out_path=str(_OUT_PATH),
        total_elapsed_s=round(total_elapsed_s, 1),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
