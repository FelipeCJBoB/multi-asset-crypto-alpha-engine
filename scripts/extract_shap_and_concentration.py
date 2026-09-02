"""Extrai `shap_mean_abs_by_side` (TreeExplainer, já persistido por fold)
e concentração (`hhi`/`max_share`/`n_eff_factors_t1`, já persistidos nos
diagnostics) dos 5 candidatos -- leitura pura, sem retreino. Insumo pra
(a) validar o corte T1 do `AG-421` sob uma métrica de importância
independente de gain, (b) quantificar risco de concentração em poucas
features.

Uso:

    uv run python -m scripts.extract_shap_and_concentration
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from statistics import mean

import orjson
import structlog

from src.models._paths import EXPERIMENTS_DIR
from src.models.pipeline import MODELS_DIR
from src.monitoring.logging import configure_logging

logger = structlog.get_logger(__name__)

_CANDIDATOS: tuple[tuple[str, str], ...] = (
    ("BTCUSDT", "R2"),
    ("SOLUSDT", "R2"),
    ("SOLUSDT", "R3"),
    ("XRPUSDT", "R2"),
    ("XRPUSDT", "R3"),
)
_CAMADAS: tuple[str, ...] = ("camada1", "camada0")
_MODEL_ID_BY_CAMADA = {"camada1": "alpha_c1_v1", "camada0": "alpha_c0_baseline_v1"}


def _shap_por_combo() -> dict[str, dict[str, float]]:
    """`{combo/camada: {feature: shap_mean_abs medio entre folds e lados}}`."""
    out: dict[str, dict[str, float]] = {}
    for symbol, resolution_id in _CANDIDATOS:
        path = EXPERIMENTS_DIR / f"alpha_walk_forward_{symbol}_{resolution_id}.json"
        payload = orjson.loads(path.read_bytes())
        for camada in _CAMADAS:
            folds = payload[camada]["fold_results"]
            acc: dict[str, list[float]] = defaultdict(list)
            for fold in folds:
                shap = fold.get("shap_mean_abs_by_side")
                if not shap:
                    continue
                for side in ("long", "short"):
                    for feat, val in shap[side].items():
                        acc[feat].append(float(val))
            key = f"{symbol}/{resolution_id}/{camada}"
            out[key] = {feat: mean(vals) for feat, vals in acc.items() if vals}
            logger.info(
                "extract_shap.combo_ok", key=key, n_features=len(out[key]), n_folds=len(folds)
            )
    return out


def _concentracao_por_combo() -> dict[str, dict[str, float]]:
    """`{combo/camada: {hhi_mean, max_share_mean, n_eff_factors_t1_mean}}` --
    média simples entre todos os fold_*_{long,short}.json em disco."""
    out: dict[str, dict[str, float]] = {}
    for symbol, resolution_id in _CANDIDATOS:
        for camada in _CAMADAS:
            model_id = _MODEL_ID_BY_CAMADA[camada]
            diag_dir = MODELS_DIR / symbol / resolution_id / model_id / "diagnostics"
            files = sorted(diag_dir.glob("fold_*_*.json"))
            hhi_vals: list[float] = []
            max_share_vals: list[float] = []
            n_eff_vals: list[float] = []
            for f in files:
                payload = orjson.loads(f.read_bytes())
                hhi_vals.append(float(payload["hhi"]))
                max_share_vals.append(float(payload["max_share"]))
                n_eff_vals.append(float(payload["n_eff_factors_t1"]))
            key = f"{symbol}/{resolution_id}/{camada}"
            out[key] = {
                "hhi_mean": mean(hhi_vals) if hhi_vals else float("nan"),
                "max_share_mean": mean(max_share_vals) if max_share_vals else float("nan"),
                "n_eff_factors_t1_mean": mean(n_eff_vals) if n_eff_vals else float("nan"),
                "n_folds": len(files),
            }
    return out


def main() -> int:
    configure_logging(json_output=False)
    shap = _shap_por_combo()
    concentracao = _concentracao_por_combo()

    dest = Path("experiments/feature_shap_and_concentration_5_candidatos_20260901.json")
    dest.write_bytes(
        orjson.dumps({"shap": shap, "concentracao": concentracao}, option=orjson.OPT_INDENT_2)
    )
    logger.info("extract_shap.escrito", dest=str(dest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
