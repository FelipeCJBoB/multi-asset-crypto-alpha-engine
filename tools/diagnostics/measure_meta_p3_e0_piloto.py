"""P3 — E0-piloto: FP inventory + Gate E0 REAL — `docs/meta_model_design_
doc_2026-08-22.md` §2.6, §15.1/§15.2.

Não é mais "piloto" no sentido do texto original do design doc (grade
15m legada, single-symbol) — decisão do Manager (2026-08-31): 15m/R1 não
são grade de treino do Alpha hoje. Roda direto contra os 5 combos de
PRODUÇÃO reais (`config/constants.yaml::alpha_production_hyperparam_
override`: `BTCUSDT/R2`, `SOLUSDT/R2`, `SOLUSDT/R3`, `XRPUSDT/R2`,
`XRPUSDT/R3`) — os únicos com hiperparâmetro confirmado pelo Manager.
`predictions.parquet` já existe em disco (`run_layer1_sprint`, sessão
anterior) — zero retreino, só leitura + inventário + a decisão real do
Gate E0 sobre Camada 1 (o sinal que o Meta-model filtra).

**Isto é uma MEDIÇÃO, não a decisão do Gate E0 em si** — o design doc é
explícito: "Consequência declarada antes de rodar: falha em ≥2 paths ⟹
registro em evidence_ledger + Meta sai do roadmap" é uma consequência
que o MANAGER aplica, não este script. O script produz os números;
`PLANO_MESTRE_PRINCE2.md`/`evidence_ledger.yaml` registram o resultado
e a decisão fica documentada separadamente.

Universo: `side_hat != 0 ∧ is_oof`, joinado a `labels` por `(t0,
side_hat) → (t0, side)` (§2.6). Regime: quantile_classifier_v1 (sem
artefato HMM persistido ainda — mesma ressalva do P0/P1). `n_seeds =
alpha_b1_n_seeds` (1000, orçamento de produção — P0 já validou a
calibração do esquema, esta rodada usa o orçamento REAL, não o
reduzido de autoteste)."""

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

import numpy as np
import polars as pl
import structlog

from src.analysis import meta_fp_inventory as fpi
from src.io import artifact as io_artifact
from src.models import alpha
from src.models import dataset as ds
from src.models import hyperparams_by_combo as hbc
from src.models._constants import load_constant
from src.models._paths import ARTIFACT_ROOT
from src.models.pipeline import MODEL_ID_CAMADA1
from src.regime.classifier import REGIME_LABELS
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
_SEED_BASE = 20260831

_OUT_PATH = _REPO_ROOT / "experiments" / "meta_p3_e0_real_2026-08-31.json"

_REGIME_MAP = {label: i for i, label in enumerate(REGIME_LABELS)}


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


def _run_combo(symbol: str, resolution_id: str, rng: np.random.Generator) -> dict[str, Any]:
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
    path_map = fpi.path_id_by_fold(result.splits)
    group_widths = np.diff(result.edges_ms)
    block_width_ms = int(np.median(group_widths))

    universe = fpi.join_predictions_to_universe(predictions, mf.data)
    universe = fpi.classify_fp_binary(universe)
    universe = universe.with_columns(
        path_id=pl.col("fold_id").replace(path_map).cast(pl.Int64),
        _state_id=pl.col("regime").cast(str).replace(_REGIME_MAP).cast(int),
    )
    weight = fpi.uniqueness_per_side(universe["t0"], universe["t1"], universe["side_hat"])
    universe = universe.with_columns(_weight=pl.Series(weight))

    # group_id do CPCV, recomputado sobre o t0 do universo com as MESMAS
    # fronteiras (edges_ms) ja calculadas -- nao um novo particionamento.
    t0_ms_universe = universe["t0"].dt.epoch(time_unit="ms").to_numpy().astype(np.int64)
    universe_group_id, _ = cpcv.assign_time_groups(
        t0_ms_universe, result.config.n_groups, edges_ms=result.edges_ms
    )

    y_valido = universe.filter(pl.col("y_fp").is_not_null())
    inventory = fpi.compute_fp_inventory(
        y_valido, weight[universe["y_fp"].is_not_null().to_numpy()]
    )

    state_ids_all = universe["_state_id"].to_numpy().astype(np.int64)
    cramers_v = fpi.cramers_v(state_ids_all, universe_group_id.astype(np.int64))

    atr = universe["atr_at_t0"].to_numpy().astype(np.float64)
    stability = fpi.state_characteristic_stability(
        state_ids_all, universe_group_id.astype(np.int64), atr, n_states=len(REGIME_LABELS)
    )

    n_seeds = int(load_constant("alpha_b1_n_seeds"))
    gate_result = fpi.evaluate_gate_e0(
        universe,
        symbol=symbol,
        resolution_id=resolution_id,
        n_states=len(REGIME_LABELS),
        block_width_ms=block_width_ms,
        rng=rng,
        n_seeds=n_seeds,
    )

    logger.info(
        "meta_p3_e0_real.combo_concluido",
        symbol=symbol,
        resolution_id=resolution_id,
        n_universe_rows=universe.height,
        n_fp=inventory.n_fp,
        n_tp=inventory.n_tp,
        n_nofill=inventory.n_nofill,
        fp_rate=round(inventory.fp_rate, 4) if not np.isnan(inventory.fp_rate) else None,
        pnl_fp_total=round(inventory.pnl_fp_total, 6),
        n_eff_subpop=round(inventory.n_eff_subpop, 2),
        cramers_v=round(cramers_v, 4) if not np.isnan(cramers_v) else None,
        n_paths_passed=gate_result.n_paths_passed,
        n_paths_total=gate_result.n_paths_total,
        min_paths_required=gate_result.min_paths_required,
        gate_passed=gate_result.gate_passed,
    )

    return {
        "symbol": symbol,
        "resolution_id": resolution_id,
        "n_universe_rows": universe.height,
        "fp_inventory": {
            "n_tp": inventory.n_tp,
            "n_fp": inventory.n_fp,
            "n_nofill": inventory.n_nofill,
            "fp_rate": inventory.fp_rate,
            "pnl_fp_total": inventory.pnl_fp_total,
            "n_eff_subpop": inventory.n_eff_subpop,
        },
        "cramers_v_regime_vs_group": cramers_v,
        "state_characteristic_stability_atr": stability.to_dicts(),
        "gate_e0": {
            "n_seeds": n_seeds,
            "n_paths_passed": gate_result.n_paths_passed,
            "n_paths_total": gate_result.n_paths_total,
            "min_paths_required": gate_result.min_paths_required,
            "gate_passed": gate_result.gate_passed,
            "path_results": [
                {
                    "path_id": r.path_id,
                    "n_rows": r.n_rows,
                    "n_states_observed": r.n_states_observed,
                    "n_effective_blocks": r.n_effective_blocks,
                    "auc_observed": r.auc_observed,
                    "p95_null": r.p95_null,
                    "passed": r.passed,
                }
                for r in gate_result.path_results
            ],
        },
    }


def main() -> int:
    t_start = time.time()
    results: list[dict[str, Any]] = []
    for symbol, resolution_id in _COMBOS:
        rng = np.random.default_rng(_SEED_BASE + hash((symbol, resolution_id)) % 10_000)
        results.append(_run_combo(symbol, resolution_id, rng))

    n_combos_passed = sum(1 for r in results if r["gate_e0"]["gate_passed"])
    total_elapsed_s = time.time() - t_start
    payload: dict[str, Any] = {
        "_schema": "meta_p3_e0_real/1.0.0",
        "_gerado_por": "tools/diagnostics/measure_meta_p3_e0_piloto.py",
        "_proposito": (
            "P3 do Gate E0 (docs/meta_model_design_doc_2026-08-22.md Sec2.6) -- "
            "FP inventory + decisao real do Gate E0 sobre Camada1, 5 combos de "
            "producao reais (R2/R3, 15m/R1 fora de escopo -- decisao do Manager "
            "2026-08-31)."
        ),
        "n_combos": len(results),
        "n_combos_gate_passed": n_combos_passed,
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
        "meta_p3_e0_real.concluido",
        n_combos=len(results),
        n_combos_gate_passed=n_combos_passed,
        out_path=str(_OUT_PATH),
        total_elapsed_s=round(total_elapsed_s, 1),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
