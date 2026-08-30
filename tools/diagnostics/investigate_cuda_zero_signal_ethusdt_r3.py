"""Diagnostico do achado colateral de AG-378: sob `device_type="cuda"`,
6/6 trials reais do Optuna (ETHUSDT/R3, camada1, `optuna_studies/ETHUSDT_
R3_camada1_cuda.db`) com `max_bin<=256` (fora da zona insegura ja
corrigida pelo guard `CudaMaxBinUnsupportedError`) treinaram o modelo
inteiro (~19-20s, mesma ordem de grandeza do CPU) mas voltaram com
`n_signals_total=0` em TODOS os 5 caminhos do CPCV -- Sharpe indefinido
(NaN). Sob CPU, os MESMOS hiperparametros (trial 7 do study CUDA, testado
aqui sob `device_type="cpu"`) produziram modelo saudavel (56 arvores, 36/36
features com gain, sinal real) -- prova de que NAO e o hiperparametro em
si, e device-specifico.

Ja DESCARTADO (`_diagnose_no_monotone`/`_diagnose_no_deterministic`,
rodados manualmente antes deste arquivo assumir a forma de bissecao):
`monotone_constraints` (zerar as 2 constraints -1 nao mudou nada) e
`deterministic=True`/`force_row_wise=True` (remover as duas flags
hardcoded em `fit_side_model` tambem nao mudou nada) -- os dois
produziram o MESMO colapso (1 arvore, gain zero, predict_proba
constante). Este arquivo faz a bissecao campo a campo real: parte de
`TRIAL_7_PARAMS` (colapsa sob CUDA) e troca UM campo de cada vez pelo
valor de `CPU_TRIAL_1_PARAMS` (funcionou sob CPU, 56 arvores) -- mesma
disciplina ja usada pra achar `max_bin>256` em AG-378.

Uso (dentro do WSL2, venv CUDA -- NUNCA `uv run`, ver AG-376):
    ~/.venvs/binance-futures-cuda/bin/python -m \\
        tools.diagnostics.investigate_cuda_zero_signal_ethusdt_r3
"""

from __future__ import annotations

import dataclasses
from typing import Any

import numpy as np
import polars as pl
import structlog

from src.models import alpha
from src.models import dataset as ds
from src.models._constants import load_constant
from src.models.hyperparams_optuna import build_search_frame

logger = structlog.get_logger(__name__)

SYMBOL = "ETHUSDT"
RESOLUTION_ID = "R3"

# Trial 7 REAL do study `optuna_studies/ETHUSDT_R3_camada1_cuda.db`
# (`trial_params`, copiado via `sqlite3` direto do arquivo -- nao
# reconstituido de cabeca). max_bin=249 <= 256, fora da zona que o guard
# de AG-378 rejeita -- este trial RODOU o treino inteiro e voltou com
# n_signals_total=0 nos 5 paths.
TRIAL_7_PARAMS: dict[str, Any] = {
    "max_bin": 249,
    "ess_regularization_fator_conservador": 0.831175281860513,
    "ess_regularization_n_obs_independentes_alvo": 35.1654295876226,
    "feature_fraction": 0.395813283158216,
    "lambda_l2": 0.845658053309257,
    "learning_rate": 0.0200143827568667,
    "min_child_samples": 39,
    "min_sum_hessian_in_leaf": 0.00409434765258584,
    "n_estimators": 316,
    "num_leaves": 8,
    "subsample": 0.870923600341733,
    "subsample_freq": 5,
}

# Trial 1 REAL do study `optuna_studies/ETHUSDT_R3_camada1_cpu.db` --
# funcionou sob CPU (56 arvores), usado como referencia pra bissecao
# campo a campo contra o TRIAL_7_PARAMS (que colapsa sob CUDA).
CPU_TRIAL_1_PARAMS: dict[str, Any] = {
    "max_bin": 239,
    "ess_regularization_fator_conservador": 0.796787280538031,
    "ess_regularization_n_obs_independentes_alvo": 30.4430107267891,
    "feature_fraction": 0.803628278849894,
    "lambda_l2": 1.38660143244717,
    "learning_rate": 0.0117827282653197,
    "min_child_samples": 99,
    "min_sum_hessian_in_leaf": 0.0601108235010031,
    "n_estimators": 588,
    "num_leaves": 26,
    "subsample": 0.613425726782101,
    "subsample_freq": 6,
}


def _setup() -> tuple[pl.DataFrame, tuple[str, ...], float, int]:
    """Monta `train_long`/`feature_ids_effective` UMA VEZ -- reusado por
    todas as rodadas da bissecao (o build do modeling frame domina o
    custo, ~2min; o fit em si e ~15-20s)."""
    mf, splits, feature_ids_effective = build_search_frame(SYMBOL, RESOLUTION_ID)
    split = splits[0]
    train_bars = mf.data[split.train_idx]
    train_long = ds.side_subset(
        train_bars, side=1, feature_ids=feature_ids_effective, enforce_r2=True
    )
    target_signal_rate = float(load_constant("target_signal_rate"))
    seed = int(load_constant("alpha_random_seed"))
    return train_long, feature_ids_effective, target_signal_rate, seed


def _fit_and_report(
    train_long: pl.DataFrame,
    feature_ids_effective: tuple[str, ...],
    target_signal_rate: float,
    seed: int,
    device_type: str,
    params: dict[str, Any],
    label: str,
) -> None:
    base_hyper = alpha.LGBMHyperparams.from_constants()
    hyper = dataclasses.replace(base_hyper, **params)

    result = alpha.fit_side_model(
        train_long,
        side=1,
        variant=alpha.VARIANT_CAMADA1,
        hyper=hyper,
        seed=seed,
        target_signal_rate=target_signal_rate,
        feature_ids=feature_ids_effective,
        device_type=device_type,
        calib_split_mode=alpha.CALIB_SPLIT_TEMPORAL_PURGED,
        class_balance_basis=alpha.CLASS_BALANCE_WEIGHT,
        calib_weight_basis=alpha.CALIB_WEIGHT_UNIQUENESS,
        regularization_basis=hyper.regularization_basis,
        ic_magnitude_floor_k=hyper.ic_magnitude_floor_k,
        early_stopping_mode=hyper.early_stopping_mode,
    )

    X_all = alpha.build_design_matrix(train_long, feature_ids=feature_ids_effective)
    raw = np.asarray(result.model.predict_proba(X_all))[:, 1]
    calibrated = result.calibrator.predict(raw)
    booster = result.model.booster_

    gains_nonzero = sum(1 for v in result.gain_by_column_raw.values() if v > 0.0)
    print(  # noqa: T201
        f"[{label}] device={device_type} n_trees={booster.num_trees()} "
        f"gain_nonzero={gains_nonzero}/{len(feature_ids_effective)} "
        f"raw_std={raw.std():.8f} n_above_tau={int((calibrated > result.tau).sum())}"
    )


def _bisect(device_type: str) -> None:
    """Referencia completa (`CPU_TRIAL_1_PARAMS` sob `device_type`) +
    1 campo por vez trocado de `TRIAL_7_PARAMS` pelo valor de
    `CPU_TRIAL_1_PARAMS` -- qual swap tira o colapso (1 arvore/gain zero)
    aponta o campo responsavel."""
    train_long, feature_ids_effective, target_signal_rate, seed = _setup()
    _fit_and_report(
        train_long,
        feature_ids_effective,
        target_signal_rate,
        seed,
        device_type,
        CPU_TRIAL_1_PARAMS,
        label="referencia-completa(trial1)",
    )
    for field_name in TRIAL_7_PARAMS:
        swapped = dict(TRIAL_7_PARAMS)
        swapped[field_name] = CPU_TRIAL_1_PARAMS[field_name]
        _fit_and_report(
            train_long,
            feature_ids_effective,
            target_signal_rate,
            seed,
            device_type,
            swapped,
            label=f"trial7+{field_name}<-trial1",
        )


if __name__ == "__main__":
    _bisect("cuda")
