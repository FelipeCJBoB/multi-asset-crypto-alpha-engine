"""ADR-003 (`docs/ADR-003_hiperparametro_feature_set_completo_2026-08-25.md`)
Estágio 0 — sondagem de estrutura pro rollout obrigatório de T2 (todos os
62 `SUPPORT_FEATURE_IDS`, `feature_ids` SUBSTITUI os 7 `T1_FEATURE_IDS` no
vetor de treino — mesma convenção já usada em toda a campanha Fase 1/Fase
2/ADR-002, `build_design_matrix`/`run_all_folds::feature_ids`, "em vez do
T1 fixo", não adição).

Pergunta que este módulo responde, barato, ANTES de comprometer o
orçamento inteiro do Estágio 1 (10 combinações): o padrão "árvore rasa +
`min_child_samples` alto vence" medido até `k=39` (Fase 1/Fase 2) ainda
vale em `k=62` (~1,6x maior que qualquer coisa já testada), ou uma
dimensionalidade tão maior muda a estrutura? Roda um grid pequeno
(`max_depth`×`num_leaves`×`min_child_samples`) sobre 2 combinações
símbolo×resolução representativas (a pior e uma do meio das "10 piores"
por `ret_net`, `ADR-003` §Context) — se concordarem na direção, o
Estágio 1 usa grid estreito nas outras 8; se divergirem, usa grid cheio
em todas as 10 (mais caro, mas honesto sobre a incerteza medida aqui).

1 seed só (`alpha_random_seed`) — é screening, mesmo tratamento de viés
de seleção explícito do ADR-002 (não decide nada sozinho, só reduz o
espaço de busca do próximo estágio)."""

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

# (max_depth, num_leaves) -- mesma regiao que Fase 2 ja estabeleceu como a
# mais promissora ate k=39 (t2_t1_capacity_map_fase2.py::depth_leaves_grid_stage_a),
# reusada aqui como ponto de partida, nao presumida automaticamente valida em k=62.
_DEPTH_LEAVES_GRID: tuple[tuple[int, int], ...] = ((2, 2), (2, 3), (3, 3))  # noqa: magic-number -- grade de busca declarada a priori (ADR-003), não constante de domínio

# min_child_samples: PROD (sanidade) + os 3 pontos medidos ate k=32/k=39
# (500 foi o melhor la) + 2 pontos NOVOS mais altos, dado k=62 quase 2x maior
# -- nao presume que 500 continua o teto certo, so estende a sondagem.
_MIN_CHILD_SAMPLES_GRID: tuple[int, ...] = (20, 500, 1000, 2000)  # noqa: magic-number -- idem


def run_stage0_probe(
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

    trials: list[dict[str, Any]] = []
    for max_depth, num_leaves in _DEPTH_LEAVES_GRID:
        for min_child_samples in _MIN_CHILD_SAMPLES_GRID:
            hyper = dataclasses.replace(
                base_hyper,
                max_depth=max_depth,
                num_leaves=num_leaves,
                min_child_samples=min_child_samples,
            )
            t0 = time.time()
            folds = alpha.run_all_folds(
                mf.data,
                splits,
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
            trial = {
                "k": len(feature_ids),
                "max_depth": max_depth,
                "num_leaves": num_leaves,
                "min_child_samples": min_child_samples,
                "pooled_sharpe": pooled,
                "sharpe_by_path": by_path,
                "elapsed_seconds": elapsed_s,
            }
            trials.append(trial)
            logger.info(
                "validation.t2_t1_stage0_probe.trial_done",
                symbol=symbol,
                resolution_id=resolution_id,
                max_depth=max_depth,
                num_leaves=num_leaves,
                min_child_samples=min_child_samples,
                pooled_sharpe=pooled,
                elapsed_seconds=elapsed_s,
            )

    best = max(trials, key=lambda t: t["pooled_sharpe"])
    logger.info(
        "validation.t2_t1_stage0_probe.run_done",
        symbol=symbol,
        resolution_id=resolution_id,
        n_trials=len(trials),
        n_features=len(feature_ids),
        best_max_depth=best["max_depth"],
        best_num_leaves=best["num_leaves"],
        best_min_child_samples=best["min_child_samples"],
        best_pooled_sharpe=best["pooled_sharpe"],
    )
    return {
        "symbol": symbol,
        "resolution_id": resolution_id,
        "n_features": len(feature_ids),
        "trials": trials,
        "best_trial": best,
    }


def write_report_atomic(payload: dict[str, Any], *, symbol: str, resolution_id: str) -> Path:
    """B29 — `.tmp` -> `fsync` -> `rename`."""
    EXPERIMENTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = EXPERIMENTS_DIR / f"t2_t1_stage0_probe_{symbol}_{resolution_id}.json"
    tmp_path = out_path.with_name(out_path.name + ".tmp")
    blob = orjson.dumps(payload, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS)
    with tmp_path.open("wb") as fh:
        fh.write(blob)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, out_path)
    logger.info("validation.t2_t1_stage0_probe.report_written", path=str(out_path))
    return out_path


def _run_cli() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="ADR-003 Estágio 0 -- sondagem de estrutura (k=62 T2 completo)"
    )
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--resolution-id", default="R1")
    parser.add_argument("--vol-estimator-id", default="parkinson_w20")
    parser.add_argument("--device-type", default="cpu")
    args = parser.parse_args()

    result = run_stage0_probe(
        args.symbol,
        args.resolution_id,
        device_type=args.device_type,
        vol_estimator_id=args.vol_estimator_id,
    )
    out_path = write_report_atomic(result, symbol=args.symbol, resolution_id=args.resolution_id)
    logger.info(
        "validation.t2_t1_stage0_probe.cli_done",
        symbol=args.symbol,
        resolution_id=args.resolution_id,
        best_trial={
            "max_depth": result["best_trial"]["max_depth"],
            "num_leaves": result["best_trial"]["num_leaves"],
            "min_child_samples": result["best_trial"]["min_child_samples"],
            "pooled_sharpe": result["best_trial"]["pooled_sharpe"],
        },
        report_path=str(out_path),
    )
    return 0


if __name__ == "__main__":
    sys.exit(_run_cli())
