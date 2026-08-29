"""AG-371 Passo 3, item 2 (2026-08-29) — Estágio 1 (screening), sob os 36
`T1_FEATURE_IDS` atuais, 15 células × 2 camadas independentes
(`AG-371-ADDENDUM-12` item b: Camada0 nunca foi triada antes — Falha 3 do
AG-371 original, a campanha ADR-003 só otimizou Camada1) = 30 buscas.

**Reusa o MESMO grid, não inventa espaço de busca novo.** Grid estrutural
(`max_depth`×`num_leaves`×`min_child_samples`, 12 pontos) + coordenada-
descendente (6 dimensões, 17 trials) importados DIRETO de
`t2_t1_full_feature_stage1_screen` (fonte única — MEASURED/vetted pela
ADR-003, ver docstring de lá pro porquê de cada faixa, ex. teto de
`min_child_samples=2000`). Única mudança real: `T1_FEATURE_IDS` (36) em
vez de `SUPPORT_FEATURE_IDS` (62, extinto desde `AG-362`), e o loop cobre
Camada0 além de Camada1.

`hyperparam_search.run_one_trial`/`append_trial_result_jsonl`
(`AG-371-ADDENDUM-17`) substituem a lógica ad-hoc do script original —
cada trial grava Sharpe/n_signals/n_filled/fill_rate/trades_per_year POR
PATH, incremental (sobrevive crash tardio, precedente real `AG-365`), o
que fecha o gap de PBO que a ADR-003 nunca fechou.

1 seed por trial aqui (screening puro, viés de seleção NÃO corrigido
ainda) — Estágio 2 (próximo item) confirma top-K por mediana de ≥5 seeds
antes de qualquer promoção real; DSR/PBO entram depois disso
(`AG-371-ADDENDUM-12` c/d). Nenhum número deste estágio deve ser lido
como "achamos hiperparâmetro melhor" — é só a fase de descarte grosseiro.

**Granularidade de retomada = célula-camada inteira**, não trial
individual: se o log JSONL de uma célula-camada já tem qualquer conteúdo,
a célula-camada inteira é pulada (assume completa). Simplificação
deliberada — o risco real (crash entre uma célula-camada e outra, como em
`AG-365`) fica coberto; crash NO MEIO de uma célula-camada específica
exige apagar o log parcial dela antes de re-rodar."""

from __future__ import annotations

import concurrent.futures
import dataclasses
import math
import sys
from pathlib import Path
from typing import Any

import structlog

from src.features import build as features_build
from src.models import alpha
from src.models._constants import load_constant
from src.models._paths import EXPERIMENTS_DIR
from src.validation import hyperparam_search as hs
from src.validation.t2_t1_full_feature_stage1_screen import (
    _DEPTH_LEAVES_GRID,
    _FEATURE_FRACTION_GRID,
    _LAMBDA_L2_GRID,
    _LEARNING_RATE_GRID,
    _MIN_CHILD_SAMPLES_GRID,
    _MIN_SUM_HESSIAN_GRID,
    _N_ESTIMATORS_GRID,
    _SUBSAMPLE_GRID,
)

logger = structlog.get_logger(__name__)

ALL_SYMBOLS: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")
ALL_RESOLUTIONS: tuple[str, ...] = ("R1", "R2", "R3")
ALL_VARIANTS: tuple[str, ...] = (alpha.VARIANT_CAMADA1, alpha.VARIANT_CAMADA0)

_COORD_DESCENT_DIMS: tuple[tuple[str, tuple[Any, ...]], ...] = (
    ("learning_rate", _LEARNING_RATE_GRID),
    ("subsample", _SUBSAMPLE_GRID),
    ("feature_fraction", _FEATURE_FRACTION_GRID),
    ("lambda_l2", _LAMBDA_L2_GRID),
    ("n_estimators", _N_ESTIMATORS_GRID),
    ("min_sum_hessian_in_leaf", _MIN_SUM_HESSIAN_GRID),
)

_STAGE1_DIR = EXPERIMENTS_DIR / "ag371_stage1_screen"


def trial_log_path(symbol: str, resolution_id: str, variant: str) -> Path:
    return _STAGE1_DIR / f"{symbol}_{resolution_id}_{variant}.jsonl"


def _best_finite(trials: list[hs.TrialResult]) -> hs.TrialResult:
    finite = [t for t in trials if math.isfinite(t.pooled_sharpe)]
    pool = finite if finite else trials
    return max(
        pool, key=lambda t: t.pooled_sharpe if math.isfinite(t.pooled_sharpe) else float("-inf")
    )


def run_stage1_screen_one_cell_layer(
    symbol: str,
    resolution_id: str,
    variant: str,
    *,
    device_type: str = "cpu",
    vol_estimator_id: str | None = "parkinson_w20",
) -> list[hs.TrialResult]:
    """1 célula-camada = 29 trials (12 grid estrutural + 17 coordenada-
    descendente), 1 seed. Retoma (pula inteira) se o log já existe com
    conteúdo — ver docstring do módulo pra granularidade de retomada."""
    log_path = trial_log_path(symbol, resolution_id, variant)
    already = hs.read_trial_results_jsonl(log_path)
    if already:
        logger.info(
            "ag371_stage1.celula_camada_ja_feita_pulando",
            symbol=symbol, resolution_id=resolution_id, variant=variant, n_trials=len(already),
        )
        return [hs.TrialResult(**row) for row in already]

    feature_ids = features_build.T1_FEATURE_IDS
    mf, splits = hs.build_mf_and_splits(symbol, resolution_id, vol_estimator_id)
    base_hyper = alpha.LGBMHyperparams.from_constants()
    seed = int(load_constant("alpha_random_seed"))

    trials: list[hs.TrialResult] = []

    for i, (max_depth, num_leaves) in enumerate(_DEPTH_LEAVES_GRID):
        for j, min_child_samples in enumerate(_MIN_CHILD_SAMPLES_GRID):
            hyper = dataclasses.replace(
                base_hyper, max_depth=max_depth, num_leaves=num_leaves,
                min_child_samples=min_child_samples,
            )
            result = hs.run_one_trial(
                mf, splits, symbol=symbol, resolution_id=resolution_id, variant=variant,
                hyper=hyper, feature_ids=feature_ids, seed=seed,
                trial_id=f"struct_{i}_{j}", device_type=device_type,
            )
            hs.append_trial_result_jsonl(result, log_path)
            trials.append(result)
            logger.info(
                "ag371_stage1.structural_trial_done",
                symbol=symbol, resolution_id=resolution_id, variant=variant,
                max_depth=max_depth, num_leaves=num_leaves, min_child_samples=min_child_samples,
                pooled_sharpe=result.pooled_sharpe, elapsed_seconds=result.elapsed_seconds,
            )

    grid_best = _best_finite(trials)
    anchor = dataclasses.replace(
        base_hyper,
        max_depth=int(grid_best.hyper["max_depth"]),
        num_leaves=int(grid_best.hyper["num_leaves"]),
        min_child_samples=int(grid_best.hyper["min_child_samples"]),
    )

    for field_name, grid in _COORD_DESCENT_DIMS:
        for value in grid:
            hyper = dataclasses.replace(anchor, **{field_name: value})
            result = hs.run_one_trial(
                mf, splits, symbol=symbol, resolution_id=resolution_id, variant=variant,
                hyper=hyper, feature_ids=feature_ids, seed=seed,
                trial_id=f"coord_{field_name}_{value}", device_type=device_type,
            )
            hs.append_trial_result_jsonl(result, log_path)
            trials.append(result)
            logger.info(
                "ag371_stage1.coord_trial_done",
                symbol=symbol, resolution_id=resolution_id, variant=variant,
                varied_dimension=field_name, value=value,
                pooled_sharpe=result.pooled_sharpe, elapsed_seconds=result.elapsed_seconds,
            )

    best = _best_finite(trials)
    logger.info(
        "ag371_stage1.celula_camada_done",
        symbol=symbol, resolution_id=resolution_id, variant=variant,
        n_trials=len(trials), best_pooled_sharpe=best.pooled_sharpe, best_hyper=best.hyper,
    )
    return trials


def all_cell_layers() -> list[tuple[str, str, str]]:
    return [
        (symbol, resolution_id, variant)
        for symbol in ALL_SYMBOLS
        for resolution_id in ALL_RESOLUTIONS
        for variant in ALL_VARIANTS
    ]


def run_stage1_screen_all(*, device_type: str = "cpu") -> None:
    """Sequencial, 1 processo -- default, preserva o comportamento de
    sempre. Ver `run_stage1_screen_all_parallel` pra paralelismo real."""
    combos = all_cell_layers()
    logger.info("ag371_stage1.all_start", n_cell_layers=len(combos))
    for symbol, resolution_id, variant in combos:
        run_stage1_screen_one_cell_layer(symbol, resolution_id, variant, device_type=device_type)
    logger.info("ag371_stage1.all_done", n_cell_layers=len(combos))


def _screen_one_cell_layer_worker(args: tuple[str, str, str, str]) -> str:
    """Alvo picklable pra `ProcessPoolExecutor` -- roda em processo
    separado do SO, cada um com seu próprio `n_jobs=-1` do LightGBM. NÃO
    retorna `list[TrialResult]` (evita serializar de volta um payload
    grande via pipe entre processos, sem necessidade -- os trials já
    ficam persistidos em disco por `append_trial_result_jsonl` dentro do
    próprio worker); só confirma qual célula-camada terminou."""
    symbol, resolution_id, variant, device_type = args
    run_stage1_screen_one_cell_layer(symbol, resolution_id, variant, device_type=device_type)
    return f"{symbol}_{resolution_id}_{variant}"


def run_stage1_screen_all_parallel(*, max_workers: int = 2, device_type: str = "cpu") -> None:
    """Paralelismo em nível de PROCESSO do SO (`ProcessPoolExecutor`), não
    threads -- `alpha.py` já chama LightGBM com `n_jobs=-1` (usa todos os
    núcleos disponíveis POR trial), então paralelizar trials/células-
    camada é sobre núcleos OCIOSOS entre um fold e outro do CPCV (medido
    real, 2026-08-29: 1 trial sozinho consome ~61% de 12 núcleos — o CPCV
    roda os 15 folds em série dentro de `run_all_folds`, não em paralelo
    — sobra ~27-39% ocioso). `max_workers=2` é o default, não "o máximo
    possível" — 2 processos concorrentes já se aproxima de saturar os 12
    núcleos (2×~61%≈full); mais que isso arrisca disputa de núcleo
    (context-switch/cache thrashing) reduzindo o throughput total em vez
    de aumentar, não medido além disso nesta sessão."""
    combos = all_cell_layers()
    pending = [c for c in combos if not read_trial_results_jsonl_bool(*c)]
    logger.info(
        "ag371_stage1.all_parallel_start",
        n_cell_layers=len(combos), n_pending=len(pending), max_workers=max_workers,
    )
    if not pending:
        logger.info("ag371_stage1.all_parallel_nada_pendente")
        return

    tasks = [
        (symbol, resolution_id, variant, device_type)
        for symbol, resolution_id, variant in pending
    ]
    with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as pool:
        for done in pool.map(_screen_one_cell_layer_worker, tasks):
            logger.info("ag371_stage1.all_parallel_cell_layer_done", cell_layer=done)
    logger.info("ag371_stage1.all_parallel_done", n_cell_layers=len(combos))


def read_trial_results_jsonl_bool(symbol: str, resolution_id: str, variant: str) -> bool:
    """`True` se a célula-camada já tem log (qualquer conteúdo) -- mesma
    granularidade de retomada de `run_stage1_screen_one_cell_layer`, só
    pra filtrar o pool de trabalho ANTES de submeter ao
    `ProcessPoolExecutor` (não vale a pena gastar um worker só pra ele
    checar e devolver na hora)."""
    return bool(hs.read_trial_results_jsonl(trial_log_path(symbol, resolution_id, variant)))


def _run_cli() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "AG-371 Passo 3 Estagio 1 -- screening 15 celulas x 2 camadas "
            "sob 36 T1_FEATURE_IDS. Sem --symbol/--resolution-id/--variant: "
            "roda as 30 combinacoes. Com os 3: roda so 1 celula-camada."
        )
    )
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--resolution-id", default=None)
    parser.add_argument("--variant", default=None, choices=list(ALL_VARIANTS))
    parser.add_argument("--device-type", default="cpu")
    parser.add_argument(
        "--max-parallel",
        type=int,
        default=1,
        help=(
            "2026-08-29 -- so com --all (sem --symbol/--resolution-id/--variant). "
            "1 (default) roda sequencial, 1 processo -- bit-exato ao comportamento "
            "de sempre. >1 usa ProcessPoolExecutor -- ver docstring de "
            "run_stage1_screen_all_parallel pro porque de 2 ser o default recomendado "
            "(medido real: n_jobs=-1 do LightGBM ja usa ~61%% dos 12 nucleos POR "
            "trial sozinho -- 2 processos concorrentes se aproxima de saturar, mais "
            "que isso arrisca disputa de nucleo)"
        ),
    )
    args = parser.parse_args()

    if args.symbol and args.resolution_id and args.variant:
        run_stage1_screen_one_cell_layer(
            args.symbol, args.resolution_id, args.variant, device_type=args.device_type
        )
    elif args.max_parallel > 1:
        run_stage1_screen_all_parallel(max_workers=args.max_parallel, device_type=args.device_type)
    else:
        run_stage1_screen_all(device_type=args.device_type)
    return 0


if __name__ == "__main__":
    sys.exit(_run_cli())
