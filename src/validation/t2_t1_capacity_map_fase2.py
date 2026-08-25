"""Fase 2 -- extensão de fronteira sobre a região vencedora da Fase 1
(`docs/t2_t1_ablation_veredito_duas_analises_2026-08-24.md` §4), ETHUSDT/R1.

**Por que "refinar ao redor" não se aplica pela letra.** A melhor
combinação da Fase 1 (`k=24, max_depth=2, num_leaves=2`,
`experiments/t2_t1_capacity_map_ETHUSDT_R1.json::best_trial`) está na
FRONTEIRA da grade testada nos dois eixos relevantes -- `k=24` é o maior
`k` que a Fase 1 testou (39 sobrevivem ao filtro de ortogonalidade,
`t2_ranking_ortogonalidade_ETHUSDT_R1.json::n_survivors`, só 24 foram
usados); `max_depth=2, num_leaves=2` é a MENOR complexidade que a grade
testou (não existe "vizinhança abaixo" -- `num_leaves=2` já é o piso do
LightGBM). Amostrar em torno de um ponto de fronteira, na direção que a
grade já não cobre, não é "refinar uma vizinhança" -- é ESTENDER a grade
na direção que o padrão monotônico da Fase 1 aponta (mais `k`, menos
complexidade), mais os pontos INTERIORES que a Fase 1 nunca visitou
(ela sempre pulava do teto de `num_leaves` pro único ponto abaixo dele,
nunca um 3º ponto intermediário -- `num_leaves=3` sob `depth=2`,
`num_leaves=3` sob `depth=3`, nunca testados).

**Estágio A** (grid): `depth/leaves` ∈ {(2,2) já vencedor, (2,3) e (3,3)
interiores nunca testados} × `k` ∈ {24 (reusa Fase 1), 32, 39 (novos,
prefixos de `survivors_ortogonalidade`)}. **Estágio B**: sweep de
`min_child_samples` ∈ {100,200,350,500} nos 2 melhores combos do Estágio
A -- estende o único ponto (200) que a Fase 1 testou.

Reusa QUALQUER ponto já medido na Fase 1 em vez de retreinar (mesma
disciplina de não gastar `N_lifetime` em algo já medido, usada em toda a
campanha) -- `_load_fase1_cached_points` indexa `trials` +
`extra_trial_min_child_samples_high` por `(k, max_depth, num_leaves,
min_child_samples)`.

Só Camada1 é treinada (mesmo escopo da Fase 1 -- mapa de forma da
superfície de Sharpe, não comparação de permanência)."""

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

# k=24 reusa o ponto já medido na Fase 1 (cache); 32/39 são novos, prefixos
# de `survivors_ortogonalidade` (mesma construção de `build_k_feature_sets`
# em `src.analysis.t2_ranking_ortogonalidade`, sem reabrir o ranking --
# passe de 0 trials, é leitura de artefato já computado).
K_VALUES: tuple[int, ...] = (24, 32, 39)

# (2,2) = vencedor da Fase 1 (extensão de k só). (2,3)/(3,3) = pontos
# INTERIORES nunca testados pela Fase 1 -- ela só testava o teto de
# `num_leaves` e 1 ponto abaixo dele (ex. depth=2 -> {2,4}), nunca um 3º
# ponto entre os dois. `(1,2)` seria redundante com `(2,2)`: com
# `num_leaves=2` a árvore para no 1º split de qualquer forma (crescimento
# leaf-wise), `max_depth=1` ou `2` produzem o MESMO modelo -- não testado
# por isso, mesmo raciocínio já documentado em `t2_t1_capacity_map.py`
# sobre `num_leaves > 2^max_depth`.
DEPTH_LEAVES_GRID_STAGE_A: tuple[tuple[int, int], ...] = ((2, 2), (2, 3), (3, 3))

# Estende o único ponto (200) que a Fase 1 testou -- 20 é PROD (já coberto
# pelo Estágio A), 200 pode já estar em cache (Fase 1 extra_trial).
MIN_CHILD_SAMPLES_SWEEP: tuple[int, ...] = (100, 200, 350, 500)
_N_TOP_CONFIGS_STAGE_B = 2  # noqa: magic-number -- decisão de desenho desta fase (top-2, não top-1 isolado), não constante de domínio

TrialKey = tuple[int, int, int, int]


def _load_extended_k_feature_sets(
    symbol: str, resolution_id: str, k_values: tuple[int, ...]
) -> dict[int, tuple[str, ...]]:
    path = EXPERIMENTS_DIR / f"t2_ranking_ortogonalidade_{symbol}_{resolution_id}.json"
    payload = orjson.loads(path.read_bytes())
    survivors: list[str] = payload["survivors_ortogonalidade"]
    n_survivors = len(survivors)
    out: dict[int, tuple[str, ...]] = {}
    for k in k_values:
        if k > n_survivors:
            raise ValueError(
                f"_load_extended_k_feature_sets: k={k} > {n_survivors} sobreviventes "
                "do filtro de ortogonalidade"
            )
        out[k] = tuple(survivors[:k])
    return out


def _load_fase1_cached_points(symbol: str, resolution_id: str) -> dict[TrialKey, dict[str, Any]]:
    """Indexa todo trial já medido na Fase 1 por `(k, max_depth, num_leaves,
    min_child_samples)` -- reuso sem retreino quando o Estágio A/B desta
    fase pede exatamente um ponto que já existe."""
    path = EXPERIMENTS_DIR / f"t2_t1_capacity_map_{symbol}_{resolution_id}.json"
    payload = orjson.loads(path.read_bytes())
    cached: dict[TrialKey, dict[str, Any]] = {}
    for t in payload["trials"]:
        key = (t["k"], t["max_depth"], t["num_leaves"], t["min_child_samples"])
        cached[key] = {**t, "reused_from_fase1": True}
    extra = payload["extra_trial_min_child_samples_high"]
    key = (extra["k"], extra["max_depth"], extra["num_leaves"], extra["min_child_samples"])
    cached[key] = {**extra, "reused_from_fase1": True}
    return cached


def _load_noise_floor(symbol: str, resolution_id: str) -> dict[str, float]:
    path = EXPERIMENTS_DIR / f"noise_floor_diagnostics_{symbol}_{resolution_id}.json"
    payload = orjson.loads(path.read_bytes())
    result_0a = payload["0a_seed_repetition"]
    return {
        "pooled_sharpe_mean": result_0a["pooled_sharpe_mean"],
        "pooled_sharpe_std": result_0a["pooled_sharpe_std"],
    }


def _run_or_reuse_trial(
    *,
    mf_data: Any,
    splits: Any,
    symbol: str,
    resolution_id: str,
    base_hyper: alpha.LGBMHyperparams,
    k: int,
    depth: int,
    leaves: int,
    mcs: int,
    feature_ids: tuple[str, ...],
    device_type: str,
    cached: dict[TrialKey, dict[str, Any]],
    log_event: str,
) -> dict[str, Any]:
    key = (k, depth, leaves, mcs)
    if key in cached:
        trial = cached[key]
        logger.info(
            f"{log_event}_reused",
            k=k, max_depth=depth, num_leaves=leaves, min_child_samples=mcs,
            pooled_sharpe=trial["pooled_sharpe"],
        )
        return trial

    hyper = dataclasses.replace(
        base_hyper, max_depth=depth, num_leaves=leaves, min_child_samples=mcs
    )
    t0 = time.time()
    folds = alpha.run_all_folds(
        mf_data, splits,
        variant=alpha.VARIANT_CAMADA1,
        model_id=MODEL_ID_CAMADA1,
        symbol=symbol,
        resolution_id=resolution_id,
        hyper=hyper,
        seed=int(load_constant("alpha_random_seed")),
        feature_ids=feature_ids,
        device_type=device_type,
    )
    elapsed_s = time.time() - t0
    pooled, by_path = _pooled_sharpe(folds, mf_data)
    trial = {
        "k": k, "max_depth": depth, "num_leaves": leaves, "min_child_samples": mcs,
        "pooled_sharpe": pooled, "sharpe_by_path": by_path,
        "elapsed_seconds": elapsed_s, "reused_from_fase1": False,
    }
    logger.info(
        f"{log_event}_done",
        k=k, max_depth=depth, num_leaves=leaves, min_child_samples=mcs,
        pooled_sharpe=pooled, elapsed_seconds=elapsed_s,
    )
    return trial


def run_fase2(
    symbol: str,
    resolution_id: str,
    *,
    device_type: str = "cuda",
    vol_estimator_id: str | None = None,
) -> dict[str, Any]:
    k_feature_sets = _load_extended_k_feature_sets(symbol, resolution_id, K_VALUES)
    all_t2_needed = tuple(sorted(set().union(*k_feature_sets.values())))
    mf, splits = _build_mf_and_splits(symbol, resolution_id, vol_estimator_id, all_t2_needed)
    base_hyper = alpha.LGBMHyperparams.from_constants()
    cached = _load_fase1_cached_points(symbol, resolution_id)

    stage_a: list[dict[str, Any]] = []
    for depth, leaves in DEPTH_LEAVES_GRID_STAGE_A:
        for k in K_VALUES:
            trial = _run_or_reuse_trial(
                mf_data=mf.data, splits=splits, symbol=symbol, resolution_id=resolution_id,
                base_hyper=base_hyper, k=k, depth=depth, leaves=leaves,
                mcs=base_hyper.min_child_samples, feature_ids=k_feature_sets[k],
                device_type=device_type, cached=cached,
                log_event="validation.t2_t1_capacity_map_fase2.stage_a_trial",
            )
            stage_a.append(trial)

    top_configs = sorted(stage_a, key=lambda t: t["pooled_sharpe"], reverse=True)[
        :_N_TOP_CONFIGS_STAGE_B
    ]

    stage_b: list[dict[str, Any]] = []
    for cfg in top_configs:
        for mcs in MIN_CHILD_SAMPLES_SWEEP:
            if mcs == cfg["min_child_samples"]:
                continue  # já é o próprio ponto do Estágio A, não duplica
            trial = _run_or_reuse_trial(
                mf_data=mf.data, splits=splits, symbol=symbol, resolution_id=resolution_id,
                base_hyper=base_hyper, k=cfg["k"], depth=cfg["max_depth"], leaves=cfg["num_leaves"],
                mcs=mcs, feature_ids=k_feature_sets[cfg["k"]],
                device_type=device_type, cached=cached,
                log_event="validation.t2_t1_capacity_map_fase2.stage_b_trial",
            )
            stage_b.append(trial)

    all_trials = stage_a + stage_b
    best = max(all_trials, key=lambda t: t["pooled_sharpe"])
    n_new_trainings = sum(1 for t in all_trials if not t["reused_from_fase1"])

    try:
        noise_floor = _load_noise_floor(symbol, resolution_id)
        gap_vs_noise_floor = best["pooled_sharpe"] - noise_floor["pooled_sharpe_mean"]
        gap_in_std_units = (
            gap_vs_noise_floor / noise_floor["pooled_sharpe_std"]
            if noise_floor["pooled_sharpe_std"] > 0
            else float("nan")
        )
    except FileNotFoundError:
        noise_floor = None
        gap_vs_noise_floor = None
        gap_in_std_units = None

    logger.info(
        "validation.t2_t1_capacity_map_fase2.run_done",
        n_trials_stage_a=len(stage_a),
        n_trials_stage_b=len(stage_b),
        n_new_trainings=n_new_trainings,
        best_pooled_sharpe=best["pooled_sharpe"],
        gap_vs_noise_floor=gap_vs_noise_floor,
        gap_in_std_units=gap_in_std_units,
    )

    return {
        "symbol": symbol,
        "resolution_id": resolution_id,
        "k_values": list(K_VALUES),
        "depth_leaves_grid_stage_a": [list(pair) for pair in DEPTH_LEAVES_GRID_STAGE_A],
        "min_child_samples_sweep": list(MIN_CHILD_SAMPLES_SWEEP),
        "stage_a": stage_a,
        "top_configs_stage_a": top_configs,
        "stage_b": stage_b,
        "best_trial": best,
        "n_new_trainings": n_new_trainings,
        "noise_floor_0a": noise_floor,
        "gap_vs_noise_floor": gap_vs_noise_floor,
        "gap_in_std_units": gap_in_std_units,
    }


def write_report_atomic(payload: dict[str, Any], *, symbol: str, resolution_id: str) -> Path:
    """B29 — `.tmp` -> `fsync` -> `rename`."""
    EXPERIMENTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = EXPERIMENTS_DIR / f"t2_t1_capacity_map_fase2_{symbol}_{resolution_id}.json"
    tmp_path = out_path.with_name(out_path.name + ".tmp")
    blob = orjson.dumps(payload, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS)
    with tmp_path.open("wb") as fh:
        fh.write(blob)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, out_path)
    logger.info("validation.t2_t1_capacity_map_fase2.report_written", path=str(out_path))
    return out_path


def _run_cli() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Fase 2 -- extensão de fronteira do Alpha")
    parser.add_argument("--symbol", default="ETHUSDT")
    parser.add_argument("--resolution-id", default="R1")
    parser.add_argument("--vol-estimator-id", default="parkinson_w20")
    parser.add_argument("--device-type", default="cuda")
    args = parser.parse_args()

    result = run_fase2(
        args.symbol,
        args.resolution_id,
        device_type=args.device_type,
        vol_estimator_id=args.vol_estimator_id,
    )
    out_path = write_report_atomic(result, symbol=args.symbol, resolution_id=args.resolution_id)
    logger.info(
        "validation.t2_t1_capacity_map_fase2.cli_done",
        n_new_trainings=result["n_new_trainings"],
        best_trial={
            "k": result["best_trial"]["k"],
            "max_depth": result["best_trial"]["max_depth"],
            "num_leaves": result["best_trial"]["num_leaves"],
            "min_child_samples": result["best_trial"]["min_child_samples"],
            "pooled_sharpe": result["best_trial"]["pooled_sharpe"],
        },
        gap_vs_noise_floor=result["gap_vs_noise_floor"],
        gap_in_std_units=result["gap_in_std_units"],
        report_path=str(out_path),
    )
    return 0


if __name__ == "__main__":
    sys.exit(_run_cli())
