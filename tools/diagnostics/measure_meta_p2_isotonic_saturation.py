"""P2 — diagnóstico de saturação isotônica (§3.4, custo zero, zero
treino) — `docs/meta_model_design_doc_2026-08-22.md` §15.1/§15.2.

Lê `predictions.parquet` REAL dos 5 combos de produção (`config/
constants.yaml::alpha_production_hyperparam_override`: `BTCUSDT/R2`,
`SOLUSDT/R2`, `SOLUSDT/R3`, `XRPUSDT/R2`, `XRPUSDT/R3` — os únicos com
hiperparâmetro CONFIRMADO pelo Manager, não os 5 símbolos × 2 resoluções
inteiros) via `src.io.artifact.read_artifact` (content-addressed,
`config_hash` calculado localmente por `hyperparams_by_combo.load_
production_override`, sem retreinar nada — os artefatos já existem em
disco, escritos por `run_layer1_sprint` em sessão anterior).

Universo: `side_hat != 0 ∧ is_oof` (mesmo universo do §2.6), por lado
(`side_hat=1`→`p_long`/`score_long_raw`; `side_hat=-1`→`p_short`/`score_
short_raw`). Métrica: `n_distinct(p_alpha)` vs `n_distinct(score_raw)` —
razão baixa = o calibrador isotônico colapsou muitos scores brutos
distintos em poucos níveis de probabilidade, o que tornaria a escolha de
`tau_meta` por quantil (§8.3) pouco granular na prática."""

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

import polars as pl
import structlog

from src.io import artifact as io_artifact
from src.models import alpha
from src.models import hyperparams_by_combo as hbc
from src.models._paths import ARTIFACT_ROOT
from src.models.pipeline import MODEL_ID_CAMADA0, MODEL_ID_CAMADA1

logger = structlog.get_logger(__name__)

_COMBOS: tuple[tuple[str, str], ...] = (
    ("BTCUSDT", "R2"),
    ("SOLUSDT", "R2"),
    ("SOLUSDT", "R3"),
    ("XRPUSDT", "R2"),
    ("XRPUSDT", "R3"),
)

_OUT_PATH = _REPO_ROOT / "experiments" / "meta_p2_isotonic_saturation_2026-08-31.json"


def _config_hash_for(symbol: str, resolution_id: str, variant: str) -> str:
    from dataclasses import asdict

    hyper = hbc.load_production_override(symbol, resolution_id, variant)
    if hyper is None:
        raise ValueError(
            f"_config_hash_for: sem override de producao para {symbol}/{resolution_id}/{variant}"
        )
    alpha_train_config_common = {
        "tau_policy": alpha.TAU_POLICY_LEGACY_PER_SIDE,
        "calib_split_mode": alpha.CALIB_SPLIT_TEMPORAL_PURGED,
        "class_balance_basis": alpha.CLASS_BALANCE_WEIGHT,
        "calib_weight_basis": alpha.CALIB_WEIGHT_UNIQUENESS,
    }
    cfg: dict[str, Any] = {"variant": variant, **alpha_train_config_common, "hyper": asdict(hyper)}
    if variant == alpha.VARIANT_CAMADA0:
        cfg["camada0_constrained_features"] = sorted(alpha.CAMADA0_CONSTRAINED_FEATURES)
    model_id = MODEL_ID_CAMADA1 if variant == alpha.VARIANT_CAMADA1 else MODEL_ID_CAMADA0
    full_cfg = {"model_id": model_id, **cfg}
    return io_artifact.compute_config_hash(
        full_cfg, schema_version=alpha.PREDICTIONS_ARTIFACT_SCHEMA.schema_version
    )


def _load_predictions(symbol: str, resolution_id: str) -> pl.DataFrame:
    config_hash = _config_hash_for(symbol, resolution_id, alpha.VARIANT_CAMADA1)
    df, _manifest = io_artifact.read_artifact(
        root=ARTIFACT_ROOT,
        stage="predictions_alpha",
        config_hash=config_hash,
        symbol=symbol,
        resolution=resolution_id,
    )
    return df


def _saturation_for_side(sub: pl.DataFrame, *, p_col: str, raw_col: str) -> dict[str, Any]:
    n = sub.height
    n_distinct_p = sub[p_col].n_unique() if n > 0 else 0
    n_distinct_raw = sub[raw_col].n_unique() if n > 0 else 0
    var_p_raw = sub[p_col].var()
    var_raw_raw = sub[raw_col].var()
    var_p = float(var_p_raw) if n > 1 and isinstance(var_p_raw, int | float) else float("nan")
    var_raw = (
        float(var_raw_raw) if n > 1 and isinstance(var_raw_raw, int | float) else float("nan")
    )
    return {
        "n_rows": n,
        "n_distinct_p_alpha": n_distinct_p,
        "n_distinct_score_raw": n_distinct_raw,
        "saturation_ratio": (n_distinct_p / n_distinct_raw) if n_distinct_raw > 0 else float("nan"),
        "variance_p_alpha": var_p,
        "variance_score_raw": var_raw,
    }


def main() -> int:
    results: list[dict[str, Any]] = []
    t_start = time.time()
    for symbol, resolution_id in _COMBOS:
        df = _load_predictions(symbol, resolution_id)
        sub = df.filter((pl.col("side_hat") != 0) & pl.col("is_oof"))
        long_ = sub.filter(pl.col("side_hat") == 1)
        short_ = sub.filter(pl.col("side_hat") == -1)

        n_calibradores = df["calibrator_id"].n_unique()
        long_stats = _saturation_for_side(long_, p_col="p_long", raw_col="score_long_raw")
        short_stats = _saturation_for_side(short_, p_col="p_short", raw_col="score_short_raw")

        logger.info(
            "meta_p2_isotonic_saturation.combo",
            symbol=symbol,
            resolution_id=resolution_id,
            n_calibradores=n_calibradores,
            long_n_rows=long_stats["n_rows"],
            long_n_distinct_p=long_stats["n_distinct_p_alpha"],
            long_n_distinct_raw=long_stats["n_distinct_score_raw"],
            long_saturation_ratio=round(long_stats["saturation_ratio"], 4),
            short_n_rows=short_stats["n_rows"],
            short_n_distinct_p=short_stats["n_distinct_p_alpha"],
            short_n_distinct_raw=short_stats["n_distinct_score_raw"],
            short_saturation_ratio=round(short_stats["saturation_ratio"], 4),
        )
        results.append(
            {
                "symbol": symbol,
                "resolution_id": resolution_id,
                "n_calibradores": n_calibradores,
                "long": long_stats,
                "short": short_stats,
            }
        )

    payload = {
        "_schema": "meta_p2_isotonic_saturation/1.0.0",
        "_gerado_por": "tools/diagnostics/measure_meta_p2_isotonic_saturation.py",
        "_proposito": (
            "P2 do Gate E0 (docs/meta_model_design_doc_2026-08-22.md Sec3.4) -- "
            "n_distinct(p_alpha) vs n_distinct(score_raw) na subpopulacao "
            "side_hat!=0 ^ is_oof, sobre os 5 combos de producao reais "
            "(config/constants.yaml::alpha_production_hyperparam_override)."
        ),
        "n_combos": len(results),
        "total_elapsed_s": time.time() - t_start,
        "combos": results,
    }

    _OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = _OUT_PATH.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, _OUT_PATH)

    logger.info("meta_p2_isotonic_saturation.concluido", out_path=str(_OUT_PATH))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
