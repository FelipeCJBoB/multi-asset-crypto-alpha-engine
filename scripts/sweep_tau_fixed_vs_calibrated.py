"""Medição: tau FIXO (proposta do Manager, 2026-09-03, "fixar em 0,51 pra
todos") contra o tau CALIBRADO dinamicamente por fold (mecanismo de
produção corrigido no AG-427 — janela rolante de 180d + quantil de
target_signal_rate=0.0284).

Mesma disciplina B20/AG-427: métrica de decisão é fração de fold
walk-forward usável (>=10 trades, `alpha.MIN_OCCURRENCES_ABOVE_TAU`) e
desvio-padrão de `signal_rate_realized` entre folds — NUNCA edge/Sharpe/
P&L (isso escolheria o limiar pela métrica que ele deveria produzir).

Baseline (calibrado, já medido no AG-427, não re-executado aqui):
`tau_calibration_window_days=180`, `target_signal_rate=0,0284` ->
52,24% folds usáveis (70/134), signal_rate_std_pooled=0,0293
(`experiments/tau_sweep_stage_B.json`, último ponto).

Ponto novo medido aqui: `tau_fixed=0.51` (mesmo valor pros 2 lados,
todos os 10 combo×variant, todos os 12-19 folds) — usa o mecanismo novo
de `alpha.fit_side_model`/`run_fold`/`run_walk_forward_for_combo`
(`tau_fixed`, bypassa por completo o quantil calibrado).

Nenhum artefato canônico é tocado — escreve só em
`experiments/tau_sweep_fixed_vs_calibrated.json`.

Uso:

    uv run python -m scripts.sweep_tau_fixed_vs_calibrated --tau-fixed 0.51
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

import numpy as np
import structlog

from src.models import alpha, dataset, hyperparams_by_combo
from src.models import walk_forward as wf
from src.models._constants import load_constant
from src.models._paths import EXPERIMENTS_DIR
from src.models.pipeline import write_report_atomic
from src.monitoring.logging import configure_logging

logger = structlog.get_logger(__name__)

_CANDIDATOS: tuple[tuple[str, str], ...] = (
    ("BTCUSDT", "R2"),
    ("SOLUSDT", "R2"),
    ("SOLUSDT", "R3"),
    ("XRPUSDT", "R2"),
    ("XRPUSDT", "R3"),
)
_VARIANTS: tuple[str, ...] = (alpha.VARIANT_CAMADA1, alpha.VARIANT_CAMADA0)

# Referência do baseline calibrado (AG-427, já medido em
# experiments/tau_sweep_stage_B.json, último ponto) -- só pra comparação
# lado a lado neste relatório, não re-medido aqui.
_BASELINE_CALIBRADO_FRAC_FOLDS_USADOS_POOLED = 0.5224  # noqa: magic-number
_BASELINE_CALIBRADO_SIGNAL_RATE_STD_POOLED = 0.0293  # noqa: magic-number


def _summarize_point(
    *,
    tau_fixed: float | None,
    tau_window_days: int | None,
    target_signal_rate: float | None,
    seed: int,
    device_type: str,
) -> dict[str, Any]:
    vol_estimator_id = str(load_constant("canonical_volatility_estimator"))
    per_combo: list[dict[str, Any]] = []
    all_signal_rates: list[float] = []
    n_folds_total_sum = 0
    n_folds_usados_sum = 0

    for symbol, resolution_id in _CANDIDATOS:
        mf = dataset.build_modeling_frame(
            symbol=symbol, resolution_id=resolution_id, vol_estimator_id=vol_estimator_id
        )
        for variant in _VARIANTS:
            hyper = hyperparams_by_combo.load_production_override(symbol, resolution_id, variant)
            if hyper is None:
                raise ValueError(
                    f"sweep_tau_fixed_vs_calibrated: {symbol}/{resolution_id}/{variant} sem "
                    "entrada em alpha_production_hyperparam_override"
                )
            result = wf.run_walk_forward_for_combo(
                mf.data,
                symbol=symbol,
                resolution_id=resolution_id,
                variant=variant,
                hyper=hyper,
                seed=seed,
                device_type=device_type,
                tau_policy=alpha.TAU_POLICY_LEGACY_PER_SIDE,
                target_signal_rate=target_signal_rate,
                tau_window_days=tau_window_days,
                tau_fixed=tau_fixed,
            )
            rates = [
                fm.signal_rate_realized
                for fm in result.fold_results
                if not np.isnan(fm.signal_rate_realized)
            ]
            all_signal_rates.extend(rates)
            n_folds_total_sum += result.n_folds_total
            n_folds_usados_sum += result.n_folds_usados
            per_combo.append(
                {
                    "symbol": symbol,
                    "resolution_id": resolution_id,
                    "variant": variant,
                    "n_folds_total": result.n_folds_total,
                    "n_folds_usados": result.n_folds_usados,
                    "n_folds_degenerados": result.n_folds_degenerados,
                    "signal_rate_mean": float(np.mean(rates)) if rates else float("nan"),
                    "signal_rate_std": float(np.std(rates)) if len(rates) > 1 else float("nan"),
                }
            )
            logger.info(
                "scripts.sweep_tau_fixed_vs_calibrated.combo_concluido",
                symbol=symbol,
                resolution_id=resolution_id,
                variant=variant,
                tau_fixed=tau_fixed,
                n_folds_usados=result.n_folds_usados,
                n_folds_total=result.n_folds_total,
            )

    frac_usado = n_folds_usados_sum / n_folds_total_sum if n_folds_total_sum else float("nan")
    return {
        "tau_fixed": tau_fixed,
        "tau_window_days": tau_window_days,
        "target_signal_rate": target_signal_rate,
        "n_folds_total_pooled": n_folds_total_sum,
        "n_folds_usados_pooled": n_folds_usados_sum,
        "frac_folds_usados_pooled": frac_usado,
        "signal_rate_std_pooled": (
            float(np.std(all_signal_rates)) if len(all_signal_rates) > 1 else float("nan")
        ),
        "signal_rate_mean_pooled": (
            float(np.mean(all_signal_rates)) if all_signal_rates else float("nan")
        ),
        "n_signal_rate_obs_pooled": len(all_signal_rates),
        "per_combo": per_combo,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tau-fixed", type=float, required=True)
    parser.add_argument("--device-type", default="cpu", choices=["cpu", "cuda"])
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args(argv)

    configure_logging(json_output=False)
    seed = args.seed if args.seed is not None else int(load_constant("alpha_random_seed"))

    logger.info(
        "scripts.sweep_tau_fixed_vs_calibrated.ponto_iniciado", tau_fixed=args.tau_fixed
    )
    ponto_fixo = _summarize_point(
        tau_fixed=args.tau_fixed,
        tau_window_days=None,
        target_signal_rate=None,
        seed=seed,
        device_type=args.device_type,
    )

    out_path = EXPERIMENTS_DIR / "tau_sweep_fixed_vs_calibrated.json"
    payload = {
        "seed": seed,
        "ponto_tau_fixo": ponto_fixo,
        "baseline_calibrado_ref": (
            "experiments/tau_sweep_stage_B.json, ultimo ponto "
            "(tau_calibration_window_days=180, target_signal_rate=0.0284) -- "
            "nao re-executado aqui, ja medido no AG-427"
        ),
        "baseline_calibrado_frac_folds_usados_pooled": (
            _BASELINE_CALIBRADO_FRAC_FOLDS_USADOS_POOLED
        ),
        "baseline_calibrado_signal_rate_std_pooled": _BASELINE_CALIBRADO_SIGNAL_RATE_STD_POOLED,
        "producer_entrypoint": "scripts.sweep_tau_fixed_vs_calibrated",
    }
    write_report_atomic(payload, dest_path=out_path)
    logger.info(
        "scripts.sweep_tau_fixed_vs_calibrated.concluido",
        path=str(out_path),
        frac_folds_usados_pooled=ponto_fixo["frac_folds_usados_pooled"],
        signal_rate_std_pooled=ponto_fixo["signal_rate_std_pooled"],
    )
    return 0


if __name__ == "__main__":  # pragma: no cover -- execução manual
    sys.exit(main())
