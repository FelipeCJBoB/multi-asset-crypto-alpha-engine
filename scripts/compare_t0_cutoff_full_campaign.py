"""Comparação DECISIVA do item 12 (roadmap "Caso 0/20", `AG-411`/`AG-416`)
— pega os hiperparâmetros vencedores da campanha COMPLETA
(`scripts/run_t0_cutoff_full_campaign.py`, 150 trials × 10 studies,
`experiments/t0_cutoff_full_campaign_results.json`) e roda um walk-forward
real com eles, comparando `edge_bps` agregado contra o artefato canônico
de produção.

**Nunca toca produção**: escreve em `experiments/alpha_walk_forward_
{symbol}_{resolution}_t0cutoff.json` (sufixo `_t0cutoff`, nunca o nome
canônico) — mesma seed/tau_policy/split de calibração que geraram os
artefatos canônicos, SÓ o hiperparâmetro muda (achado sob corte de data
em vez do hiperparâmetro de produção atual).

**`--control` (`AG-416`)**: mesma lógica, mas lendo `experiments/
t0_cutoff_control_campaign_results.json` (campanha SEM corte de data,
seed corrigido — `scripts/run_t0_cutoff_full_campaign.py --control`) e
escrevendo em `_control.json`. Reporta os 3 números lado a lado
(canônico/produção-atual, t0cutoff, control) — isola se a melhora de
8/10 já medida vem do corte de data ou só do seed corrigido (`AG-399`).

Uso:

    uv run python -m scripts.compare_t0_cutoff_full_campaign
    uv run python -m scripts.compare_t0_cutoff_full_campaign --control
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

import structlog

from src.models import alpha, dataset, pipeline
from src.models import walk_forward as wf
from src.models._constants import load_constant
from src.models._paths import EXPERIMENTS_DIR
from src.monitoring.logging import configure_logging

logger = structlog.get_logger(__name__)

_RESULTS_PATH = Path("experiments/t0_cutoff_full_campaign_results.json")
_CONTROL_RESULTS_PATH = Path("experiments/t0_cutoff_control_campaign_results.json")


def _edge_bps_from_artifact(path: Path, variant: str) -> float | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    edge_mean = payload[variant]["aggregate"]["mean"].get("edge_bps")
    return float(edge_mean) if edge_mean is not None else None


def _canonical_edge_bps(symbol: str, resolution_id: str, variant: str) -> float | None:
    path = EXPERIMENTS_DIR / f"alpha_walk_forward_{symbol}_{resolution_id}.json"
    return _edge_bps_from_artifact(path, variant)


def _t0cutoff_edge_bps(symbol: str, resolution_id: str, variant: str) -> float | None:
    path = EXPERIMENTS_DIR / f"alpha_walk_forward_{symbol}_{resolution_id}_t0cutoff.json"
    return _edge_bps_from_artifact(path, variant)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--control",
        action="store_true",
        help="AG-416 -- compara os hiperparametros da campanha de controle "
        "(sem t0_end, seed corrigido) em vez da campanha com t0_end.",
    )
    args = parser.parse_args(argv)

    configure_logging(json_output=False)

    results_path = _CONTROL_RESULTS_PATH if args.control else _RESULTS_PATH
    suffix = "_control" if args.control else "_t0cutoff"
    campaign_results: list[dict[str, Any]] = json.loads(results_path.read_text(encoding="utf-8"))
    seed = int(load_constant("alpha_random_seed"))
    vol_estimator_id = str(load_constant("canonical_volatility_estimator"))

    by_combo: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for entry in campaign_results:
        key = (str(entry["symbol"]), str(entry["resolution_id"]))
        by_combo.setdefault(key, []).append(entry)

    comparacoes: list[dict[str, Any]] = []
    for (symbol, resolution_id), entries in by_combo.items():
        mf = dataset.build_modeling_frame(
            symbol=symbol, resolution_id=resolution_id, vol_estimator_id=vol_estimator_id
        )
        payload: dict[str, Any] = {}
        for entry in entries:
            variant: str = entry["variant"]
            hyper = alpha.LGBMHyperparams(**entry["best_hyper"])
            logger.info(
                "scripts.compare_t0_cutoff_full_campaign.rodando_combo",
                symbol=symbol,
                resolution_id=resolution_id,
                variant=variant,
            )
            result = wf.run_walk_forward_for_combo(
                mf.data,
                symbol=symbol,
                resolution_id=resolution_id,
                variant=variant,
                hyper=hyper,
                seed=seed,
                device_type="cpu",
                tau_policy=alpha.TAU_POLICY_LEGACY_PER_SIDE,
            )
            payload[variant] = asdict(result)

            edge_novo = result.aggregate["mean"].get("edge_bps")
            edge_canonico = _canonical_edge_bps(symbol, resolution_id, variant)
            comparacao: dict[str, Any] = {
                "symbol": symbol,
                "resolution_id": resolution_id,
                "variant": variant,
                "edge_bps_canonico": edge_canonico,
                f"edge_bps{suffix}": edge_novo,
                "delta_vs_canonico": (
                    edge_novo - edge_canonico
                    if edge_canonico is not None and edge_novo is not None
                    else None
                ),
            }
            if args.control:
                edge_t0cutoff = _t0cutoff_edge_bps(symbol, resolution_id, variant)
                comparacao["edge_bps_t0cutoff"] = edge_t0cutoff
                comparacao["delta_control_vs_t0cutoff"] = (
                    edge_novo - edge_t0cutoff
                    if edge_t0cutoff is not None and edge_novo is not None
                    else None
                )
            comparacoes.append(comparacao)
            logger.info(
                "scripts.compare_t0_cutoff_full_campaign.comparacao_combo", **comparacao
            )

        payload["run_metadata"] = {
            "seed": seed,
            "tau_policy": alpha.TAU_POLICY_LEGACY_PER_SIDE,
            "device_type": "cpu",
            "symbol": symbol,
            "resolution_id": resolution_id,
            "producer_entrypoint": "scripts.compare_t0_cutoff_full_campaign",
            "hyperparam_source": f"{results_path.name} (AG-411/AG-416 item 12)",
        }
        out_path = EXPERIMENTS_DIR / f"alpha_walk_forward_{symbol}_{resolution_id}{suffix}.json"
        pipeline.write_report_atomic(payload, dest_path=out_path)
        logger.info(
            "scripts.compare_t0_cutoff_full_campaign.artefato_escrito", path=str(out_path)
        )

    n_melhora = sum(
        1 for c in comparacoes if c["delta_vs_canonico"] is not None and c["delta_vs_canonico"] > 0
    )
    logger.info(
        "scripts.compare_t0_cutoff_full_campaign.resumo_final",
        n_combos_variant=len(comparacoes),
        n_melhora=n_melhora,
        n_piora=len(comparacoes) - n_melhora,
        comparacoes=comparacoes,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover -- execucao manual
    sys.exit(main())
