"""Mede o poder estatístico REAL dos gates Model/Alpha via injeção de
sinal sintético (Monte Carlo) — fecha o item 10 do roadmap "Caso 0/20"
(reusa o mesmo padrão de `src.analysis.eixo1_power_diagnostic`, aplicado
aos gates do walk-forward em vez do eixo 1 de features).

**Método.** Para cada célula real (combo × camada × lado) e cada valor
verdadeiro na grade (`_DEFAULT_AUC_GRID`/`_DEFAULT_EDGE_GRID`), simula
`n_mc_draws` sorteios: por fold, sorteia uma estimativa `Normal(valor_
verdadeiro, dispersão_entre_fold_JÁ_MEDIDA)` — a dispersão usada é a REAL
(`auc_std`/`edge_bps_std` já medidos nesta célula, não uma suposição nova
— mede "se o efeito verdadeiro fosse X, sob o MESMO ruído entre-fold que
já medimos, o gate detectaria?"). Roda os sorteios pelos MESMOS `model_
gate_p_value`/`alpha_gate_p_value` de produção. A taxa de detecção sobre
os `n_mc_draws` sorteios é o poder empírico.

Uso:

    uv run python -m scripts.measure_gate_power
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import structlog

from src.analysis.stability_matrix import build_stability_matrix
from src.analysis.walk_forward_gates import (
    alpha_gate_p_value,
    evaluate_gates,
    model_gate_p_value,
)
from src.models._constants import load_constant
from src.models._paths import EXPERIMENTS_DIR
from src.monitoring.logging import configure_logging

logger = structlog.get_logger(__name__)

_CANDIDATOS: tuple[tuple[str, str], ...] = (
    ("BTCUSDT", "R2"),
    ("SOLUSDT", "R2"),
    ("SOLUSDT", "R3"),
    ("XRPUSDT", "R2"),
    ("XRPUSDT", "R3"),
)
_VARIANTS: tuple[str, ...] = ("camada1", "camada0")
_SIDES: tuple[str, ...] = ("long", "short")
_DEFAULT_AUC_GRID: tuple[float, ...] = (0.50, 0.52, 0.55, 0.60, 0.70)  # noqa: magic-number -- grade de sensibilidade, nao constante de dominio
# bps -- grade de sensibilidade do eixo Alpha, nao constante de dominio
_DEFAULT_EDGE_GRID: tuple[float, ...] = (0.0, 5.0, 10.0, 20.0, 30.0)  # noqa: magic-number


def _simulated_detection_rate(
    true_value: float,
    dispersao_medida: float,
    n_folds: int,
    *,
    p_value_fn: object,
    rng: np.random.Generator,
    n_mc_draws: int,
    significance_level: float,
) -> float:
    """Núcleo compartilhado do Model e do Alpha gate -- só o `p_value_fn`
    (assinatura `(mean, std, n_folds) -> float`) muda entre os dois.
    `NaN` se a célula não tem dispersão válida medida (sem base pra
    simular ruído realista)."""
    if not math.isfinite(dispersao_medida) or dispersao_medida <= 0.0 or n_folds < 2:  # noqa: magic-number -- piso de graus de liberdade, mesmo de _MIN_FOLDS_FOR_TTEST
        return float("nan")
    detections = 0
    for _ in range(n_mc_draws):
        fold_draws = rng.normal(loc=true_value, scale=dispersao_medida, size=n_folds)
        sim_mean = float(fold_draws.mean())
        sim_std = float(fold_draws.std(ddof=1))
        p = p_value_fn(sim_mean, sim_std, n_folds)  # type: ignore[operator]
        if not math.isnan(p) and p < significance_level:
            detections += 1
    return detections / n_mc_draws  # noqa: unguarded-ratio -- n_mc_draws validado >0 pelo caller (CLI) antes de qualquer chamada desta funcao


def _model_power_curve(
    auc_std: float,
    n_folds: int,
    *,
    significance_level: float,
    rng: np.random.Generator,
    n_mc_draws: int,
) -> dict[float, float]:
    return {
        auc: _simulated_detection_rate(
            auc, auc_std, n_folds,
            p_value_fn=model_gate_p_value,
            rng=rng, n_mc_draws=n_mc_draws, significance_level=significance_level,
        )
        for auc in _DEFAULT_AUC_GRID
    }


def _alpha_power_curve(
    edge_std: float,
    n_folds: int,
    *,
    min_edge_bps: float,
    significance_level: float,
    rng: np.random.Generator,
    n_mc_draws: int,
) -> dict[float, float]:
    def _alpha_p(mean: float, std: float, n: int) -> float:
        return alpha_gate_p_value(mean, std, n, min_edge_bps=min_edge_bps)

    return {
        edge: _simulated_detection_rate(
            edge, edge_std, n_folds,
            p_value_fn=_alpha_p,
            rng=rng, n_mc_draws=n_mc_draws, significance_level=significance_level,
        )
        for edge in _DEFAULT_EDGE_GRID
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--suffix", default="")
    parser.add_argument("--experiments-dir", type=Path, default=EXPERIMENTS_DIR)
    parser.add_argument("--n-mc-draws", type=int, default=2000)  # noqa: magic-number
    parser.add_argument("--seed", type=int, default=42)  # noqa: magic-number
    args = parser.parse_args(argv)
    if args.n_mc_draws <= 0:
        raise ValueError(f"--n-mc-draws={args.n_mc_draws} precisa ser > 0")

    configure_logging(json_output=False)
    rng = np.random.default_rng(args.seed)

    significance_level = float(load_constant("alpha_gate_model_significance_level"))
    alpha_min_edge = float(load_constant("alpha_layer1_permanence_min_edge_bps"))
    data_min_folds = int(load_constant("alpha_gate_data_min_folds_usados"))

    n_cells = 0
    n_com_dispersao_valida = 0
    for symbol, res in _CANDIDATOS:
        suffix = f"_{args.suffix}" if args.suffix else ""
        path = args.experiments_dir / f"alpha_walk_forward_{symbol}_{res}{suffix}.json"
        payload_all = json.loads(path.read_text(encoding="utf-8"))
        for variant in _VARIANTS:
            payload = payload_all[variant]
            sm = build_stability_matrix(payload, symbol=symbol, resolution_id=res, variant=variant)
            gv = evaluate_gates(
                payload,
                sm,
                data_min_folds_usados=data_min_folds,
                significance_level=significance_level,
                alpha_min_edge_bps=alpha_min_edge,
            )
            label = f"{symbol}/{res}/{variant}"

            for side in _SIDES:
                n_cells += 1
                power = _model_power_curve(
                    gv.auc_std_by_side[side],
                    gv.n_folds_auc_by_side[side],
                    significance_level=significance_level,
                    rng=rng,
                    n_mc_draws=args.n_mc_draws,
                )
                if any(not math.isnan(p) for p in power.values()):
                    n_com_dispersao_valida += 1
                logger.info(
                    "scripts.measure_gate_power.model_gate",
                    label=f"{label}/{side}",
                    n_folds=gv.n_folds_auc_by_side[side],
                    auc_std_medido=round(gv.auc_std_by_side[side], 4)
                    if math.isfinite(gv.auc_std_by_side[side])
                    else None,
                    power_curve={k: round(v, 3) for k, v in power.items()},
                )

            n_cells += 1
            power_alpha = _alpha_power_curve(
                gv.edge_bps_std,
                gv.n_folds_usados,
                min_edge_bps=alpha_min_edge,
                significance_level=significance_level,
                rng=rng,
                n_mc_draws=args.n_mc_draws,
            )
            if any(not math.isnan(p) for p in power_alpha.values()):
                n_com_dispersao_valida += 1
            logger.info(
                "scripts.measure_gate_power.alpha_gate",
                label=label,
                n_folds=gv.n_folds_usados,
                edge_bps_std_medido=round(gv.edge_bps_std, 4)
                if math.isfinite(gv.edge_bps_std)
                else None,
                power_curve={k: round(v, 3) for k, v in power_alpha.items()},
            )

    logger.info(
        "scripts.measure_gate_power.concluido",
        n_celulas_gate_model_e_alpha=n_cells,
        n_com_dispersao_valida=n_com_dispersao_valida,
        n_mc_draws=args.n_mc_draws,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover -- execucao manual
    sys.exit(main())
