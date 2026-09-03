"""Varredura de sensibilidade dos itens 2/3/6/7 do roadmap de correção do
mecanismo de tau (2026-09-03, decisão do Manager) — mede, sem tocar
`constants.yaml` nem os artefatos canônicos, qual combinação de
`tau_window_days` (item 3, janela recente de calibração de `tau`) e
`target_signal_rate` (item 2/6/7, taxa-alvo que define o quantil de
`tau`) reduz a taxa de fold degenerado / estabiliza `signal_rate_realized`
no walk-forward real dos 5 candidatos.

Desenho em 2 estágios, pra não confundir os dois efeitos:

    Estágio A — varre só `tau_window_days` (`target_signal_rate` fixo no
    valor de produção, 0.0189) — isola o efeito do MECANISMO (item 3).

    Estágio B — trava o melhor `tau_window_days` do Estágio A, varre
    `target_signal_rate` dentro do `sweep_range` já declarado em
    `constants.yaml` ([0.0095, 0.0284]) — isola o efeito do NÍVEL (item
    6/2/7), já sob o mecanismo corrigido.

Métrica de decisão: fração de fold degenerado (pooled, 5 combos x 2
camadas) e desvio-padrão de `signal_rate_realized` entre folds — NUNCA
edge/Sharpe/P&L (isso seria escolher o limiar de decisão pela métrica
que ele deveria produzir, exatamente o erro que B20/`alpha.py` linha 30
existe pra evitar). É calibração de INSTRUMENTAÇÃO (tamanho de amostra
válida), não de performance.

Nenhum artefato canônico é tocado — escreve só em
`experiments/tau_sweep_{stage}.json`.

Uso:

    uv run python -m scripts.sweep_tau_mechanism --stage A
    uv run python -m scripts.sweep_tau_mechanism --stage B --tau-window-days 180
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

# Eixo do experimento em si (pontos varridos), não constante de domínio --
# 90/270 são +-90d ao redor do candidato de 180d (item 3, "últimos 6
# meses"); None é o baseline sem janela (mecanismo legado).
_STAGE_A_TAU_WINDOW_DAYS: tuple[int | None, ...] = (None, 90, 180, 270)  # noqa: magic-number
# 5 pontos igualmente espaçados dentro do sweep_range JÁ declarado em
# constants.yaml::target_signal_rate ([0.0095, 0.0284]) -- eixo do
# experimento, não constante de domínio nova (a própria constante recebe
# o valor adotado ao fim do sweep, com proveniência completa).
_STAGE_B_TARGET_SIGNAL_RATE: tuple[float, ...] = (0.0095, 0.0142, 0.0189, 0.0236, 0.0284)  # noqa: magic-number


def _summarize_point(
    *,
    tau_window_days: int | None,
    target_signal_rate: float,
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
                    f"sweep_tau_mechanism: {symbol}/{resolution_id}/{variant} sem entrada em "
                    "alpha_production_hyperparam_override"
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
                "scripts.sweep_tau_mechanism.combo_concluido",
                symbol=symbol,
                resolution_id=resolution_id,
                variant=variant,
                tau_window_days=tau_window_days,
                target_signal_rate=target_signal_rate,
                n_folds_usados=result.n_folds_usados,
                n_folds_total=result.n_folds_total,
            )

    frac_usado = n_folds_usados_sum / n_folds_total_sum if n_folds_total_sum else float("nan")
    return {
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
    parser.add_argument("--stage", required=True, choices=["A", "B"])
    parser.add_argument(
        "--tau-window-days",
        type=int,
        default=None,
        help="Estágio B: melhor tau_window_days do Estágio A, travado enquanto varre "
        "target_signal_rate. Obrigatório pro Estágio B.",
    )
    parser.add_argument("--device-type", default="cpu", choices=["cpu", "cuda"])
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args(argv)

    if args.stage == "B" and args.tau_window_days is None:
        parser.error("--stage B exige --tau-window-days (resultado travado do Estágio A)")

    configure_logging(json_output=False)
    seed = args.seed if args.seed is not None else int(load_constant("alpha_random_seed"))
    baseline_rate = float(load_constant("target_signal_rate"))

    points: list[dict[str, Any]] = []
    if args.stage == "A":
        for tau_window_days in _STAGE_A_TAU_WINDOW_DAYS:
            logger.info(
                "scripts.sweep_tau_mechanism.ponto_iniciado",
                stage="A",
                tau_window_days=tau_window_days,
                target_signal_rate=baseline_rate,
            )
            points.append(
                _summarize_point(
                    tau_window_days=tau_window_days,
                    target_signal_rate=baseline_rate,
                    seed=seed,
                    device_type=args.device_type,
                )
            )
    else:
        for rate in _STAGE_B_TARGET_SIGNAL_RATE:
            logger.info(
                "scripts.sweep_tau_mechanism.ponto_iniciado",
                stage="B",
                tau_window_days=args.tau_window_days,
                target_signal_rate=rate,
            )
            points.append(
                _summarize_point(
                    tau_window_days=args.tau_window_days,
                    target_signal_rate=rate,
                    seed=seed,
                    device_type=args.device_type,
                )
            )

    out_path = EXPERIMENTS_DIR / f"tau_sweep_stage_{args.stage}.json"
    payload = {
        "stage": args.stage,
        "seed": seed,
        "baseline_target_signal_rate": baseline_rate,
        "tau_window_days_locked": args.tau_window_days,
        "points": points,
        "producer_entrypoint": "scripts.sweep_tau_mechanism",
    }
    write_report_atomic(payload, dest_path=out_path)
    logger.info("scripts.sweep_tau_mechanism.concluido", path=str(out_path), n_points=len(points))
    return 0


if __name__ == "__main__":  # pragma: no cover -- execução manual
    sys.exit(main())
