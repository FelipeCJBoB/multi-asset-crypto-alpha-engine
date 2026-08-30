"""Perfila 1 trial completo (`run_all_folds`, 15 splits do CPCV x 2 lados)
sob `device_type="cuda"` -- decide, com dado real (nao suposicao de
leitura de codigo), o que vale a pena mover pro device antes de tentar
qualquer otimizacao (achado do usuario via Gerenciador de Tarefas: GPU
em ~55% com mergulhos, nao 100% -- ver AG-379/comentario de 2026-08-29).

Uso (dentro do WSL2, venv CUDA):
    ~/.venvs/binance-futures-cuda/bin/python -m \\
        tools.diagnostics.profile_optuna_trial_cuda_cpu_split
"""

from __future__ import annotations

import cProfile
import pstats

from src.models import alpha
from src.models.hyperparams_optuna import build_search_frame

SYMBOL = "ETHUSDT"
RESOLUTION_ID = "R3"


def _run_one_trial(device_type: str) -> None:
    mf, splits, feature_ids_effective = build_search_frame(SYMBOL, RESOLUTION_ID)
    hyper = alpha.LGBMHyperparams.from_constants()
    alpha.run_all_folds(
        mf.data,
        splits,
        variant=alpha.VARIANT_CAMADA1,
        model_id="profile_trial",
        symbol=SYMBOL,
        resolution_id=RESOLUTION_ID,
        hyper=hyper,
        seed=1,
        feature_ids=feature_ids_effective,
        device_type=device_type,
        tau_policy=alpha.TAU_POLICY_LEGACY_PER_SIDE,
        calib_split_mode=alpha.CALIB_SPLIT_TEMPORAL_PURGED,
        class_balance_basis=alpha.CLASS_BALANCE_WEIGHT,
        calib_weight_basis=alpha.CALIB_WEIGHT_UNIQUENESS,
        enforce_r2=True,
    )


def main() -> None:
    profiler = cProfile.Profile()
    profiler.enable()
    _run_one_trial("cuda")
    profiler.disable()

    stats = pstats.Stats(profiler)
    stats.sort_stats("cumulative")
    print("\n=== TOP 30 por tempo CUMULATIVO ===")  # noqa: T201
    stats.print_stats(30)
    stats.sort_stats("tottime")
    print("\n=== TOP 30 por tempo PROPRIO (tottime, exclui chamadas filhas) ===")  # noqa: T201
    stats.print_stats(30)


if __name__ == "__main__":
    main()
