"""ADR-002 (`docs/ADR-002_busca_hiperparametro_robusta_a_ruido_2026-08-24.md`)
Estágios 2 e 3 — a correção do erro real encontrado hoje: Fase 1+2
selecionaram um "vencedor" por `max()` sobre score de 1 seed só (viés de
seleção/winner's-curse), e a confirmação original repetiu seed só no
TOP-1 já selecionado, não nos top-K -- não dava pra saber se um candidato
vizinho (não o argmax de 1 seed) seria mais robusto.

**Estágio 2** — junta TODOS os candidatos já medidos (Fase 1: 65+1, Fase
2: 16, Estágio 1b: ~14) numa lista só, pega os **top-5 por score de 1
seed** (não top-1), reavalia cada um com **5 seeds** (a primeira reusa o
seed=42 original já medido -- 0 custo extra -- as 4 seguintes são novas),
seleciona o vencedor pela **mediana** dos 5, não a média (mais robusta a
1 seed outlier) nem o score de 1 seed (viesado por construção).

**Estágio 3** — só o vencedor do Estágio 2 passa pelo gate de
permanência real (Camada1 vs Camada0, sem permutação) repetido N vezes
(default 5), critério de promoção = mediana de `n_better` >=
`alpha_layer1_permanence_min_paths` -- nunca uma única realização, mesma
disciplina que a Fase 0b já aplica ao NULO, agora aplicada ao candidato
REAL."""

from __future__ import annotations

import dataclasses
import os
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import orjson
import structlog

from src.models import alpha, backtest_lite
from src.models._constants import load_constant
from src.models._paths import EXPERIMENTS_DIR
from src.models.pipeline import MODEL_ID_CAMADA0, MODEL_ID_CAMADA1
from src.validation.noise_floor_diagnostics import _build_mf_and_splits, _pooled_sharpe

logger = structlog.get_logger(__name__)

_TOP_K_FOR_CONFIRMATION = 5  # noqa: magic-number -- decisão de desenho da ADR-002 ("mediana top-5"), não constante de domínio
_N_SEEDS_STAGE2 = 5  # noqa: magic-number -- idem
_N_SEEDS_STAGE3 = 5  # noqa: magic-number -- idem

_HYPER_FIELDS = (
    "max_depth", "num_leaves", "min_child_samples",
    "learning_rate", "subsample", "feature_fraction", "lambda_l2", "n_estimators",
)


def _candidate_to_hyper(
    candidate: dict[str, Any], base: alpha.LGBMHyperparams
) -> alpha.LGBMHyperparams:
    overrides = {f: candidate[f] for f in _HYPER_FIELDS if f in candidate}
    return dataclasses.replace(base, **overrides)


def _normalize_candidate(raw: dict[str, Any], base_hyper: alpha.LGBMHyperparams) -> dict[str, Any]:
    """Preenche os 5 campos que Fase 1/2 nunca variaram com o valor PROD --
    todo candidato do pool combinado precisa do hyperparameter-set
    COMPLETO (9 campos) pra Estágio 2/3 rodarem, mesmo os que vieram de um
    trial que só variou `k`/`max_depth`/`num_leaves`/`min_child_samples`."""
    out = dict(raw)
    for f in ("learning_rate", "subsample", "feature_fraction", "lambda_l2", "n_estimators"):
        out.setdefault(f, getattr(base_hyper, f))
    return out


def load_combined_candidate_pool(symbol: str, resolution_id: str) -> list[dict[str, Any]]:
    """Junta Fase 1 (65+1) + Fase 2 (16) + Estágio 1b (~14) numa lista só
    de candidatos normalizados (9 campos de hiperparâmetro + `k` + score
    de 1 seed) -- fonte única pro Estágio 2 escolher o top-5."""
    base_hyper = alpha.LGBMHyperparams.from_constants()
    pool: list[dict[str, Any]] = []

    fase1_path = EXPERIMENTS_DIR / f"t2_t1_capacity_map_{symbol}_{resolution_id}.json"
    if fase1_path.exists():
        fase1 = orjson.loads(fase1_path.read_bytes())
        for t in fase1["trials"]:
            pool.append(_normalize_candidate(t, base_hyper))
        pool.append(_normalize_candidate(fase1["extra_trial_min_child_samples_high"], base_hyper))

    fase2_path = EXPERIMENTS_DIR / f"t2_t1_capacity_map_fase2_{symbol}_{resolution_id}.json"
    if fase2_path.exists():
        fase2 = orjson.loads(fase2_path.read_bytes())
        for t in fase2["stage_a"]:
            pool.append(_normalize_candidate(t, base_hyper))
        for t in fase2["stage_b"]:
            pool.append(_normalize_candidate(t, base_hyper))

    stage1b_path = EXPERIMENTS_DIR / f"t2_t1_stage1b_hyperparam_{symbol}_{resolution_id}.json"
    if stage1b_path.exists():
        stage1b = orjson.loads(stage1b_path.read_bytes())
        for t in stage1b["trials"]:
            pool.append(_normalize_candidate(t, base_hyper))

    # Dedup por assinatura completa de candidato (k + 8 campos de hyper) --
    # o mesmo ponto aparece em mais de um artefato (ex. o vencedor de Fase
    # 2 é reusado como âncora do Estágio 1b) e não deve contar 2x no
    # ranking nem ser reconfirmado 2x no Estágio 2.
    seen: set[tuple[Any, ...]] = set()
    deduped: list[dict[str, Any]] = []
    for c in pool:
        key = (c["k"], *(c[f] for f in _HYPER_FIELDS))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(c)
    return deduped


def _load_feature_set(symbol: str, resolution_id: str, k: int) -> tuple[str, ...]:
    path = EXPERIMENTS_DIR / f"t2_ranking_ortogonalidade_{symbol}_{resolution_id}.json"
    payload = orjson.loads(path.read_bytes())
    survivors: list[str] = payload["survivors_ortogonalidade"]
    return tuple(survivors[:k])


def run_stage2_confirm(
    symbol: str,
    resolution_id: str,
    *,
    device_type: str = "cpu",
    vol_estimator_id: str | None = None,
) -> dict[str, Any]:
    pool = load_combined_candidate_pool(symbol, resolution_id)
    top_k = sorted(pool, key=lambda c: c["pooled_sharpe"], reverse=True)[:_TOP_K_FOR_CONFIRMATION]

    base_hyper = alpha.LGBMHyperparams.from_constants()
    base_seed = int(load_constant("alpha_random_seed"))
    # Seed 0 = o seed=42 RAW já usado por Fase1/Fase2 (reuso, 0 custo) --
    # seeds 1..N-1 = derivados, novos.
    seeds = [base_seed] + [alpha._derived_seed(base_seed, i) for i in range(_N_SEEDS_STAGE2 - 1)]

    confirmed: list[dict[str, Any]] = []
    for candidate in top_k:
        k = candidate["k"]
        feature_ids = _load_feature_set(symbol, resolution_id, k)
        mf, splits = _build_mf_and_splits(symbol, resolution_id, vol_estimator_id, feature_ids)
        hyper = _candidate_to_hyper(candidate, base_hyper)

        seed_scores: list[float] = []
        per_seed: list[dict[str, Any]] = []
        for i, seed in enumerate(seeds):
            if i == 0:
                # seed=42 original -- já medido no screening, mesmo score.
                seed_scores.append(candidate["pooled_sharpe"])
                per_seed.append(
                    {"seed": seed, "pooled_sharpe": candidate["pooled_sharpe"], "reused": True}
                )
                continue
            t0 = time.time()
            folds = alpha.run_all_folds(
                mf.data, splits,
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
            pooled, _by_path = _pooled_sharpe(folds, mf.data)
            seed_scores.append(pooled)
            per_seed.append(
                {
                    "seed": seed, "pooled_sharpe": pooled, "reused": False,
                    "elapsed_seconds": elapsed_s,
                }
            )
            logger.info(
                "validation.t2_t1_stage2.seed_done",
                k=k, seed_index=i, pooled_sharpe=pooled, elapsed_seconds=elapsed_s,
            )

        median_sharpe = float(np.median(np.asarray(seed_scores, dtype=np.float64)))
        confirmed.append(
            {
                **{f: candidate[f] for f in ("k", *_HYPER_FIELDS)},
                "screening_pooled_sharpe": candidate["pooled_sharpe"],
                "median_pooled_sharpe": median_sharpe,
                "seed_scores": seed_scores,
                "per_seed": per_seed,
                "selection_bias_estimate": candidate["pooled_sharpe"] - median_sharpe,
            }
        )
        logger.info(
            "validation.t2_t1_stage2.candidate_confirmed",
            k=k, screening_pooled_sharpe=candidate["pooled_sharpe"],
            median_pooled_sharpe=median_sharpe,
            selection_bias_estimate=candidate["pooled_sharpe"] - median_sharpe,
        )

    winner = max(confirmed, key=lambda c: c["median_pooled_sharpe"])
    n_new_trainings = len(top_k) * (_N_SEEDS_STAGE2 - 1)
    logger.info(
        "validation.t2_t1_stage2.run_done",
        n_candidates_confirmed=len(confirmed), n_new_trainings=n_new_trainings,
        winner_k=winner["k"], winner_median_pooled_sharpe=winner["median_pooled_sharpe"],
        winner_selection_bias_estimate=winner["selection_bias_estimate"],
    )
    return {
        "symbol": symbol, "resolution_id": resolution_id,
        "pool_size": len(pool), "top_k": top_k, "confirmed": confirmed, "winner": winner,
        "n_new_trainings": n_new_trainings,
    }


def run_stage3_permanence_gate(
    symbol: str,
    resolution_id: str,
    winner: dict[str, Any],
    *,
    n_seeds: int = _N_SEEDS_STAGE3,
    device_type: str = "cpu",
    vol_estimator_id: str | None = None,
) -> dict[str, Any]:
    k = winner["k"]
    feature_ids = _load_feature_set(symbol, resolution_id, k)
    mf, splits = _build_mf_and_splits(symbol, resolution_id, vol_estimator_id, feature_ids)
    base_hyper = alpha.LGBMHyperparams.from_constants()
    hyper = _candidate_to_hyper(winner, base_hyper)
    base_seed = int(load_constant("alpha_random_seed"))
    permanence_min_paths = int(load_constant("alpha_layer1_permanence_min_paths"))

    n_better_list: list[int] = []
    per_seed: list[dict[str, Any]] = []
    for i in range(n_seeds):
        seed = alpha._derived_seed(base_seed, 777_001, i)  # noqa: magic-number -- separa espaço de seed do Estágio 3 do Estágio 2/screening, arbitrário
        t0 = time.time()
        c1_folds = alpha.run_all_folds(
            mf.data, splits, variant=alpha.VARIANT_CAMADA1, model_id=MODEL_ID_CAMADA1,
            symbol=symbol, resolution_id=resolution_id, hyper=hyper, seed=seed,
            feature_ids=feature_ids, device_type=device_type,
        )
        c0_folds = alpha.run_all_folds(
            mf.data, splits, variant=alpha.VARIANT_CAMADA0, model_id=MODEL_ID_CAMADA0,
            symbol=symbol, resolution_id=resolution_id, hyper=hyper, seed=seed,
            feature_ids=feature_ids, device_type=device_type,
        )
        elapsed_s = time.time() - t0
        c1_by_path = backtest_lite.backtest_by_path(c1_folds, mf.data)
        c0_by_path = backtest_lite.backtest_by_path(c0_folds, mf.data)
        n_better, n_total = backtest_lite.permanence_count(c1_by_path, c0_by_path)
        n_better_list.append(n_better)
        per_seed.append(
            {"seed": seed, "n_better": n_better, "n_total": n_total, "elapsed_seconds": elapsed_s}
        )
        logger.info(
            "validation.t2_t1_stage3.seed_done",
            seed_index=i, n_better=n_better, n_total=n_total, elapsed_seconds=elapsed_s,
        )

    median_n_better = float(np.median(np.asarray(n_better_list, dtype=np.float64)))
    permanence_pass = median_n_better >= permanence_min_paths
    logger.info(
        "validation.t2_t1_stage3.run_done",
        n_seeds=n_seeds, n_better_list=n_better_list, median_n_better=median_n_better,
        permanence_min_paths=permanence_min_paths, permanence_pass=permanence_pass,
    )
    return {
        "symbol": symbol, "resolution_id": resolution_id,
        "candidate": {f: winner[f] for f in ("k", *_HYPER_FIELDS)},
        "n_seeds": n_seeds, "n_better_list": n_better_list, "median_n_better": median_n_better,
        "permanence_min_paths_threshold": permanence_min_paths, "permanence_pass": permanence_pass,
        "per_seed": per_seed,
    }


def write_report_atomic(
    payload: dict[str, Any], *, symbol: str, resolution_id: str, name: str
) -> Path:
    """B29 — `.tmp` -> `fsync` -> `rename`."""
    EXPERIMENTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = EXPERIMENTS_DIR / f"{name}_{symbol}_{resolution_id}.json"
    tmp_path = out_path.with_name(out_path.name + ".tmp")
    blob = orjson.dumps(payload, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS)
    with tmp_path.open("wb") as fh:
        fh.write(blob)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, out_path)
    logger.info("validation.t2_t1_stage2_3.report_written", path=str(out_path))
    return out_path


def _run_cli() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="ADR-002 Estágios 2+3 -- confirmação robusta")
    parser.add_argument("--symbol", default="ETHUSDT")
    parser.add_argument("--resolution-id", default="R1")
    parser.add_argument("--vol-estimator-id", default="parkinson_w20")
    parser.add_argument("--device-type", default="cpu")
    args = parser.parse_args()

    stage2 = run_stage2_confirm(
        args.symbol, args.resolution_id,
        device_type=args.device_type, vol_estimator_id=args.vol_estimator_id,
    )
    write_report_atomic(
        stage2, symbol=args.symbol, resolution_id=args.resolution_id, name="t2_t1_stage2_confirm"
    )
    stage3 = run_stage3_permanence_gate(
        args.symbol, args.resolution_id, stage2["winner"],
        device_type=args.device_type, vol_estimator_id=args.vol_estimator_id,
    )
    out_path = write_report_atomic(
        stage3, symbol=args.symbol, resolution_id=args.resolution_id, name="t2_t1_stage3_permanence"
    )
    logger.info(
        "validation.t2_t1_stage2_3.cli_done",
        winner_k=stage2["winner"]["k"],
        winner_median_pooled_sharpe=stage2["winner"]["median_pooled_sharpe"],
        stage3_median_n_better=stage3["median_n_better"],
        stage3_permanence_pass=stage3["permanence_pass"],
        report_path=str(out_path),
    )
    return 0


if __name__ == "__main__":
    sys.exit(_run_cli())
