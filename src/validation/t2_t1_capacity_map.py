"""Fase 1 — mapa de capacidade (`docs/t2_t1_ablation_veredito_duas_
analises_2026-08-24.md` §4), só roda se a Fase 0 não matar a hipótese.
Grid ENUMERADO, não Optuna — na escala orçada (66 trials), TPE não tem
vantagem sobre um grid pequeno e auditável (`TPESampler.n_startup_
trials=10` consumiria a maior parte do orçamento em sorteio aleatório
puro, ver `docs/t2_t1_promotion_ablation_design_doc_2026-08-24.md` §9.1).

`max_depth`/`num_leaves` SEMPRE condicionados (nunca eixos livres) —
achado da varredura crítica: `num_leaves > 2^max_depth` sob leaf-wise
growth produz o MESMO modelo que o teto, gastando trial sem explorar
nada novo. `k` (tamanho do vetor de features) vem do ranking já rodado
(`src.analysis.t2_ranking_ortogonalidade`, artefato `experiments/
t2_ranking_ortogonalidade_{symbol}_{resolution_id}.json`) — este módulo
NUNCA decide quais features compõem cada `k`, só consome.

Objetivo: existe relação CONSISTENTE entre `k` e capacidade de árvore
(`max_depth`/`num_leaves`)? Não é achar "o melhor modelo" — é mapear a
superfície. Só Camada1 (com `monotone_constraints`) é treinada aqui, não
Camada0 — o mapa de capacidade é sobre a FORMA da superfície de Sharpe
de Camada1 em função de `(k, depth, leaves)`, não uma comparação de
permanência (isso é papel da Fase 0b, já rodada)."""

from __future__ import annotations

import dataclasses
import os
import sys
import time
from pathlib import Path
from typing import Any

import orjson
import structlog

from src.models import alpha
from src.models._constants import load_constant
from src.models._paths import EXPERIMENTS_DIR
from src.models.pipeline import MODEL_ID_CAMADA1
from src.validation.noise_floor_diagnostics import _build_mf_and_splits, _pooled_sharpe

logger = structlog.get_logger(__name__)

# (max_depth, num_leaves candidatos) -- nunca `num_leaves > 2^max_depth`,
# e nunca no TETO sozinho (achado da pesquisa: doc oficial do LightGBM
# cita num_leaves=2^max_depth como exemplo de overfitting, não como
# ponto seguro) -- cada depth testa o teto E um ponto abaixo dele.
DEPTH_LEAVES_GRID: tuple[tuple[int, tuple[int, ...]], ...] = (
    (2, (2, 4)),
    (3, (4, 8)),
    (4, (4, 8, 16)),
    (5, (8, 16, 32)),
    (6, (8, 16, 32)),
)
K_VALUES: tuple[int, ...] = (6, 9, 12, 16, 24)
_MIN_CHILD_SAMPLES_HIGH = 200  # noqa: magic-number -- candidato de §2.5 do veredito, testado só na melhor combinação, não constante de domínio


def _load_k_feature_sets(symbol: str, resolution_id: str) -> dict[int, tuple[str, ...]]:
    path = EXPERIMENTS_DIR / f"t2_ranking_ortogonalidade_{symbol}_{resolution_id}.json"
    payload = orjson.loads(path.read_bytes())
    return {int(k): tuple(v) for k, v in payload["k_feature_sets"].items()}


def run_capacity_map(
    symbol: str,
    resolution_id: str,
    *,
    device_type: str = "cuda",
    vol_estimator_id: str | None = None,
) -> dict[str, Any]:
    k_feature_sets = _load_k_feature_sets(symbol, resolution_id)
    missing = [k for k in K_VALUES if k not in k_feature_sets]
    if missing:
        raise ValueError(
            f"run_capacity_map: k={missing} sem conjunto de features no ranking -- "
            "rode src.analysis.t2_ranking_ortogonalidade primeiro"
        )

    mf, splits = _build_mf_and_splits(symbol, resolution_id, vol_estimator_id)
    base_hyper = alpha.LGBMHyperparams.from_constants()

    trials: list[dict[str, Any]] = []
    for depth, leaves_options in DEPTH_LEAVES_GRID:
        for leaves in leaves_options:
            hyper = dataclasses.replace(base_hyper, max_depth=depth, num_leaves=leaves)
            for k in K_VALUES:
                t0 = time.time()
                folds = alpha.run_all_folds(
                    mf.data,
                    splits,
                    variant=alpha.VARIANT_CAMADA1,
                    model_id=MODEL_ID_CAMADA1,
                    symbol=symbol,
                    resolution_id=resolution_id,
                    hyper=hyper,
                    seed=int(load_constant("alpha_random_seed")),
                    feature_ids=k_feature_sets[k],
                    device_type=device_type,
                )
                elapsed_s = time.time() - t0
                pooled, by_path = _pooled_sharpe(folds, mf.data)
                trial = {
                    "k": k,
                    "max_depth": depth,
                    "num_leaves": leaves,
                    "min_child_samples": hyper.min_child_samples,
                    "pooled_sharpe": pooled,
                    "sharpe_by_path": by_path,
                    "elapsed_seconds": elapsed_s,
                }
                trials.append(trial)
                logger.info(
                    "validation.t2_t1_capacity_map.trial_done",
                    k=k,
                    max_depth=depth,
                    num_leaves=leaves,
                    pooled_sharpe=pooled,
                    elapsed_seconds=elapsed_s,
                    n_trial=len(trials),
                )

    best = max(trials, key=lambda t: t["pooled_sharpe"])

    # Trial extra (§2.5 do veredito): min_child_samples alto SÓ na melhor
    # combinação do grid acima -- não multiplica a grade inteira por 2.
    hyper_high_mcs = dataclasses.replace(
        base_hyper,
        max_depth=best["max_depth"],
        num_leaves=best["num_leaves"],
        min_child_samples=_MIN_CHILD_SAMPLES_HIGH,
    )
    t0 = time.time()
    folds_extra = alpha.run_all_folds(
        mf.data,
        splits,
        variant=alpha.VARIANT_CAMADA1,
        model_id=MODEL_ID_CAMADA1,
        symbol=symbol,
        resolution_id=resolution_id,
        hyper=hyper_high_mcs,
        seed=int(load_constant("alpha_random_seed")),
        feature_ids=k_feature_sets[best["k"]],
        device_type=device_type,
    )
    elapsed_extra = time.time() - t0
    pooled_extra, by_path_extra = _pooled_sharpe(folds_extra, mf.data)
    extra_trial = {
        "k": best["k"],
        "max_depth": best["max_depth"],
        "num_leaves": best["num_leaves"],
        "min_child_samples": _MIN_CHILD_SAMPLES_HIGH,
        "pooled_sharpe": pooled_extra,
        "sharpe_by_path": by_path_extra,
        "elapsed_seconds": elapsed_extra,
        "nota": "trial extra -- min_child_samples alto na melhor combinacao do grid",
    }
    logger.info(
        "validation.t2_t1_capacity_map.extra_trial_done",
        pooled_sharpe=pooled_extra,
        baseline_pooled_sharpe=best["pooled_sharpe"],
        delta=pooled_extra - best["pooled_sharpe"],
    )

    return {
        "symbol": symbol,
        "resolution_id": resolution_id,
        "n_trials_grid": len(trials),
        "trials": trials,
        "best_trial": best,
        "extra_trial_min_child_samples_high": extra_trial,
    }


def write_report_atomic(payload: dict[str, Any], *, symbol: str, resolution_id: str) -> Path:
    """B29 — `.tmp` -> `fsync` -> `rename`."""
    EXPERIMENTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = EXPERIMENTS_DIR / f"t2_t1_capacity_map_{symbol}_{resolution_id}.json"
    tmp_path = out_path.with_name(out_path.name + ".tmp")
    blob = orjson.dumps(payload, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS)
    with tmp_path.open("wb") as fh:
        fh.write(blob)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, out_path)
    logger.info("validation.t2_t1_capacity_map.report_written", path=str(out_path))
    return out_path


def _run_cli() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Fase 1 -- mapa de capacidade do Alpha")
    parser.add_argument("--symbol", default="ETHUSDT")
    parser.add_argument("--resolution-id", default="R1")
    parser.add_argument("--vol-estimator-id", default="parkinson_w20")
    parser.add_argument("--device-type", default="cuda")
    args = parser.parse_args()

    result = run_capacity_map(
        args.symbol,
        args.resolution_id,
        device_type=args.device_type,
        vol_estimator_id=args.vol_estimator_id,
    )
    out_path = write_report_atomic(result, symbol=args.symbol, resolution_id=args.resolution_id)
    logger.info(
        "validation.t2_t1_capacity_map.cli_done",
        n_trials_grid=result["n_trials_grid"],
        best_trial={
            "k": result["best_trial"]["k"],
            "max_depth": result["best_trial"]["max_depth"],
            "num_leaves": result["best_trial"]["num_leaves"],
            "pooled_sharpe": result["best_trial"]["pooled_sharpe"],
        },
        report_path=str(out_path),
    )
    return 0


if __name__ == "__main__":
    sys.exit(_run_cli())
