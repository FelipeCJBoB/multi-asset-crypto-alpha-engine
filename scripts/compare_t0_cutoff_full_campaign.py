"""Comparação DECISIVA do item 12 (roadmap "Caso 0/20", `AG-411`) — pega os
hiperparâmetros vencedores da campanha COMPLETA (`scripts/run_t0_cutoff_
full_campaign.py`, 150 trials × 10 studies, `experiments/t0_cutoff_full_
campaign_results.json`) e roda um walk-forward real com eles, comparando
`edge_bps` agregado contra o artefato canônico de produção.

**Nunca toca produção**: escreve em `experiments/alpha_walk_forward_
{symbol}_{resolution}_t0cutoff.json` (sufixo `_t0cutoff`, nunca o nome
canônico) — mesma seed/tau_policy/split de calibração que geraram os
artefatos canônicos, SÓ o hiperparâmetro muda (achado sob corte de data
em vez do hiperparâmetro de produção atual).

Uso:

    uv run python -m scripts.compare_t0_cutoff_full_campaign
"""

from __future__ import annotations

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


def _canonical_edge_bps(symbol: str, resolution_id: str, variant: str) -> float | None:
    path = EXPERIMENTS_DIR / f"alpha_walk_forward_{symbol}_{resolution_id}.json"
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    edge_mean = payload[variant]["aggregate"]["mean"].get("edge_bps")
    return float(edge_mean) if edge_mean is not None else None


def main() -> int:
    configure_logging(json_output=False)

    campaign_results: list[dict[str, Any]] = json.loads(_RESULTS_PATH.read_text(encoding="utf-8"))
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

            edge_t0cutoff = result.aggregate["mean"].get("edge_bps")
            edge_canonico = _canonical_edge_bps(symbol, resolution_id, variant)
            comparacoes.append(
                {
                    "symbol": symbol,
                    "resolution_id": resolution_id,
                    "variant": variant,
                    "edge_bps_canonico": edge_canonico,
                    "edge_bps_t0cutoff": edge_t0cutoff,
                    "delta_bps": (
                        edge_t0cutoff - edge_canonico
                        if edge_canonico is not None and edge_t0cutoff is not None
                        else None
                    ),
                }
            )
            logger.info(
                "scripts.compare_t0_cutoff_full_campaign.comparacao_combo",
                symbol=symbol,
                resolution_id=resolution_id,
                variant=variant,
                edge_bps_canonico=edge_canonico,
                edge_bps_t0cutoff=edge_t0cutoff,
            )

        payload["run_metadata"] = {
            "seed": seed,
            "tau_policy": alpha.TAU_POLICY_LEGACY_PER_SIDE,
            "device_type": "cpu",
            "symbol": symbol,
            "resolution_id": resolution_id,
            "producer_entrypoint": "scripts.compare_t0_cutoff_full_campaign",
            "hyperparam_source": "t0_cutoff_full_campaign_results.json (AG-411 item 12)",
        }
        out_path = (
            EXPERIMENTS_DIR / f"alpha_walk_forward_{symbol}_{resolution_id}_t0cutoff.json"
        )
        pipeline.write_report_atomic(payload, dest_path=out_path)
        logger.info(
            "scripts.compare_t0_cutoff_full_campaign.artefato_escrito", path=str(out_path)
        )

    n_melhora = sum(
        1 for c in comparacoes if c["delta_bps"] is not None and c["delta_bps"] > 0
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
