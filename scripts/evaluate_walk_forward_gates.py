"""Consolida os 3 gates (Data/Model/Alpha, ADR-008 Fase 6) sobre um lote de
artefatos de walk-forward real, com correção de múltiplas comparações —
fecha `AG-400` (achado da auditoria adversarial externa: `apply_fdr_to_
model_gates` existe, testada, nunca chamada em produção; a própria
docstring do módulo instrui usá-la pra consolidar um lote, e o "0/20" da
ADR-008 foi consolidado célula a célula, contra essa instrução) e a parte
de `AG-396` sobre `rodar_gates_v2.py`/`montar_model_cards_v2.py` (citados
no commit `e812ab1`, nunca commitados).

Uso — os 5 artefatos canônicos (a base do "0/20" da ADR-008):

    uv run python -m scripts.evaluate_walk_forward_gates

Os 5 artefatos sob a política de tau corrigida (AG-210/AG-395/AG-403):

    uv run python -m scripts.evaluate_walk_forward_gates --suffix total_common_oof
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import structlog

from src.analysis.stability_matrix import build_stability_matrix
from src.analysis.walk_forward_gates import apply_fdr_to_model_gates, evaluate_gates
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--suffix",
        default="",
        help="Sufixo do nome do arquivo (ex. 'total_common_oof' lê "
        "alpha_walk_forward_{symbol}_{res}_total_common_oof.json). Vazio (default) "
        "lê os artefatos canônicos.",
    )
    parser.add_argument("--experiments-dir", type=Path, default=EXPERIMENTS_DIR)
    args = parser.parse_args(argv)

    configure_logging(json_output=False)

    data_min = int(load_constant("alpha_gate_data_min_folds_usados"))
    model_sig = float(load_constant("alpha_gate_model_significance_level"))
    alpha_min_edge = float(load_constant("alpha_layer1_permanence_min_edge_bps"))

    verdicts = []
    for symbol, res in _CANDIDATOS:
        suffix = f"_{args.suffix}" if args.suffix else ""
        path = args.experiments_dir / f"alpha_walk_forward_{symbol}_{res}{suffix}.json"
        if not path.exists():
            logger.error("scripts.evaluate_walk_forward_gates.artefato_ausente", path=str(path))
            return 1
        payload_all = json.loads(path.read_text(encoding="utf-8"))
        for variant in _VARIANTS:
            payload = payload_all[variant]
            sm = build_stability_matrix(payload, symbol=symbol, resolution_id=res, variant=variant)
            gv = evaluate_gates(
                payload,
                sm,
                data_min_folds_usados=data_min,
                significance_level=model_sig,
                alpha_min_edge_bps=alpha_min_edge,
            )
            verdicts.append(gv)

    fdr_by_label = apply_fdr_to_model_gates(verdicts)

    n_pass_raw = 0
    n_pass_bh = 0
    n_cells = 0
    for gv in verdicts:
        for side in _SIDES:
            n_cells += 1
            label = f"{gv.combo}/{gv.variant}/{side}"
            fdr = fdr_by_label.get(label)
            model_pass_raw = gv.model_gate_pass_by_side[side]
            p_raw = gv.auc_p_value_by_side[side]
            pass_raw = bool(gv.data_gate_pass and gv.alpha_gate_pass and model_pass_raw)
            pass_bh = bool(gv.data_gate_pass and gv.alpha_gate_pass and fdr and fdr.significant_bh)
            n_pass_raw += int(pass_raw)
            n_pass_bh += int(pass_bh)
            logger.info(
                "scripts.evaluate_walk_forward_gates.celula",
                label=label,
                data_gate_pass=gv.data_gate_pass,
                n_folds_usados=gv.n_folds_usados,
                alpha_gate_pass=gv.alpha_gate_pass,
                edge_bps_mean=gv.edge_bps_mean,
                model_gate_pass_raw=model_pass_raw,
                model_auc_p_value_raw=p_raw,
                model_significant_bh=fdr.significant_bh if fdr else None,
                model_significant_by=fdr.significant_by if fdr else None,
                passa_sob_p_bruto=pass_raw,
                passa_sob_fdr_bh=pass_bh,
            )

    logger.info(
        "scripts.evaluate_walk_forward_gates.concluido",
        suffix=args.suffix or "canonico",
        n_cells=n_cells,
        n_pass_raw=n_pass_raw,
        n_pass_bh=n_pass_bh,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover -- execucao manual
    sys.exit(main())
