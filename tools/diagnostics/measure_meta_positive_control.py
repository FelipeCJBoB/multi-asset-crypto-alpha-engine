"""Controle positivo sintetico (Sec4.3) -- pre-condicao BLOQUEANTE de F6
(Sec9, `meta_ablation.py` linhas 8-14: "nao e reverificado aqui -- e
responsabilidade do chamador confirmar que ja rodou").

**Achado real, nao hipotetico**: a medicao real de F6 (AG-409,
2026-09-01, `measure_meta_f6_ablation.py`) rodou SEM este controle ter
sido executado uma unica vez antes -- lacuna encontrada revisando o
design doc antes de iniciar F6b. O design doc e explicito: "rodar F6 sem
essa garantia nao e erro de codigo, e decisao do Manager de pular uma
trava, e nao deveria acontecer em silencio" -- isso aconteceu em
silencio. Este script fecha a lacuna AGORA (depois do fato): confirma ou
refuta se o resultado de AG-409 e interpretavel. Nao decide se F6 "pode"
rodar -- ja rodou, por decisao explicita do Manager de continuar mesmo
com Gate E0/F6 reprovando.

Injeta `p_alpha' = (1-lambda).p_alpha + lambda.y_meta` numa grade a
priori (`meta_leakage_control_lambda_grid`), reajusta o Meta do zero
(`meta.run_all_meta_folds`) sobre cada tabela contaminada, mede o Sharpe
agregado do braco A1 (`meta_ablation.compute_branch_panel` sobre
`side_final`). Gate: a metrica precisa ser ESTRITAMENTE crescente em
lambda (`meta_dataset.run_leakage_positive_control`).

**Previsao estrutural, declarada ANTES de rodar (nao pos-hoc)**: combos
onde o Meta nunca ajusta modelo de verdade (SOLUSDT/R3, XRPUSDT/R3 --
100% pass-through, AG-409) nao podem detectar o controle por construcao
-- pass-through ignora `p_alpha` inteiramente (`side_final = side_hat`
sempre), entao a metrica fica IDENTICA em todo lambda (nao crescente,
`detected=False`) independente de o mecanismo de ajuste funcionar. Isto
NAO e uma falha do harness -- e um corolario direto do achado de amostra
insuficiente ja registrado em `AG-409`, nao um achado novo."""

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

import polars as pl
import structlog

from src.io import artifact as io_artifact
from src.models import alpha
from src.models import dataset as ds
from src.models import hyperparams_by_combo as hbc
from src.models import meta as meta_mod
from src.models import meta_ablation as ab
from src.models import meta_dataset as mds
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
_SEED_BASE = 20260901

_OUT_PATH = _REPO_ROOT / "experiments" / "meta_positive_control_2026-09-01.json"


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
    cpcv_result = cpcv.generate_splits(
        mf.data, config=cpcv.CPCVConfig.from_constants(grade_id=resolution_id), symbol=symbol
    )

    # Mesma fonte de regime da medicao real de F6 (AG-409,
    # `measure_meta_f6_ablation.py`) -- `hmm_gaussian_k4_v1` foi decidido
    # pelo Manager (2026-08-30) mas o artefato nunca foi persistido, F6
    # rodou sob `quantile_classifier_v1` (PLANO_MESTRE_PRINCE2.md
    # Sec15.38). O controle positivo precisa testar a MESMA configuracao
    # que produziu AG-409, nao uma diferente.
    regime_source = "quantile_classifier_v1"
    regime_levels = mds.regime_levels_for_source(regime_source)
    table = mds.build_meta_signal_table(
        dense=mf.data,
        predictions=predictions,
        cpcv_result=cpcv_result,
        symbol=symbol,
        resolution_id=resolution_id,
        variant="camada1",
        donor_rule=mds.DONOR_RULE_PATH_MATCHED,
        regime_source=regime_source,
        origem=f"measure_meta_positive_control({symbol}/{resolution_id})",
    )
    random_state = _SEED_BASE + hash((symbol, resolution_id)) % 10_000

    def evaluate(contaminated: pl.DataFrame) -> float:
        fold_results = meta_mod.run_all_meta_folds(
            contaminated,
            regime_levels=regime_levels,
            random_state=random_state,
            alpha_model_id="alpha_c1_v1",
            variant="camada1",
            resolution_id=resolution_id,
        )
        test_predictions = pl.concat([r.test_predictions for r in fold_results], how="vertical")
        panel = ab.compute_branch_panel(test_predictions, accept_col="side_final")
        return panel.sharpe_naive

    pc_result = mds.run_leakage_positive_control(table, evaluate)

    logger.info(
        "meta_positive_control.combo_concluido",
        symbol=symbol,
        resolution_id=resolution_id,
        lambda_grid=pc_result.lambda_grid,
        metric_by_lambda=pc_result.metric_by_lambda,
        detected=pc_result.detected,
        reason=pc_result.reason,
    )

    return {
        "symbol": symbol,
        "resolution_id": resolution_id,
        "lambda_grid": list(pc_result.lambda_grid),
        "metric_by_lambda": list(pc_result.metric_by_lambda),
        "detected": pc_result.detected,
        "reason": pc_result.reason,
    }


def main() -> int:
    t_start = time.time()
    results: list[dict[str, Any]] = []
    for symbol, resolution_id in _COMBOS:
        results.append(_run_combo(symbol, resolution_id))

    n_detected = sum(1 for r in results if r["detected"])
    total_elapsed_s = time.time() - t_start
    payload: dict[str, Any] = {
        "_schema": "meta_positive_control/1.0.0",
        "_gerado_por": "tools/diagnostics/measure_meta_positive_control.py",
        "_proposito": (
            "Controle positivo sintetico (Sec4.3), pre-condicao BLOQUEANTE de F6 "
            "(Sec9) nunca executada antes da medicao real de AG-409 -- fecha a "
            "lacuna agora. Combos onde o Meta nunca ajusta modelo (100% "
            "pass-through, AG-409) nao podem detectar por construcao -- previsto "
            "a priori, nao e achado novo."
        ),
        "n_combos": len(results),
        "n_detected": n_detected,
        "n_total": len(results),
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
        "meta_positive_control.concluido",
        n_combos=len(results),
        n_detected=n_detected,
        out_path=str(_OUT_PATH),
        total_elapsed_s=round(total_elapsed_s, 1),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
