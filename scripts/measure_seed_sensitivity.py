"""Mede a sensibilidade a seed dos 5 candidatos — fecha o item 4 do
roadmap "Caso 0/20" ("rodar a Fase 4 com >=5 seeds; reportar mediana e
dispersão"). Consome os artefatos já gravados por `scripts.run_walk_
forward_campaign --seed N` (um por seed, sufixo `_seed{N}`) + o artefato
canônico (`seed=alpha_random_seed`, sem sufixo).

**Por que isto importa** (R11 da auditoria adversarial externa): o
veredito "0/20" da ADR-008 vem de UMA seed só. Sem uma segunda medição,
não há como distinguir "candidato sem edge" de "candidato cujo edge essa
seed específica não capturou". Este módulo aplica o MESMO núcleo de
teste-t já usado nos gates de produção (`alpha_gate_p_value`), agora
sobre a dispersão ENTRE seeds (não entre folds dentro de 1 seed) — eixo
complementar, não substitui o gate oficial.

Uso (assume que `scripts.run_walk_forward_campaign --seed N` já rodou
para os seeds informados):

    uv run python -m scripts.measure_seed_sensitivity --seeds 42,43,44,45,46
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

import structlog

from src.analysis.walk_forward_gates import alpha_gate_p_value
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


def _parse_seeds(raw: str) -> tuple[int, ...]:
    return tuple(int(s) for s in raw.split(","))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--seeds", type=_parse_seeds, required=True)
    parser.add_argument("--experiments-dir", type=Path, default=EXPERIMENTS_DIR)
    parser.add_argument(
        "--significance-level",
        type=float,
        default=None,
        help="Default: alpha_gate_model_significance_level de constants.yaml (mesmo "
        "nível já travado pro gate Model/Alpha oficial).",
    )
    args = parser.parse_args(argv)

    configure_logging(json_output=False)
    seed_default = int(load_constant("alpha_random_seed"))
    significance_level = (
        args.significance_level
        if args.significance_level is not None
        else float(load_constant("alpha_gate_model_significance_level"))
    )

    n_cells = 0
    n_significant = 0
    for symbol, res in _CANDIDATOS:
        for variant in _VARIANTS:
            edges: list[float] = []
            for seed in args.seeds:
                suffix = "" if seed == seed_default else f"_seed{seed}"
                path = args.experiments_dir / f"alpha_walk_forward_{symbol}_{res}{suffix}.json"
                if not path.exists():
                    logger.error(
                        "scripts.measure_seed_sensitivity.artefato_ausente",
                        path=str(path),
                        detail="rode scripts.run_walk_forward_campaign --seed "
                        f"{seed} primeiro",
                    )
                    return 1
                payload = json.loads(path.read_text(encoding="utf-8"))[variant]
                edge = payload["aggregate"]["mean"]["edge_bps"]
                if edge is not None:
                    edges.append(float(edge))

            n_cells += 1
            label = f"{symbol}/{res}/{variant}"
            if len(edges) < 2:  # noqa: magic-number -- desvio-padrao amostral exige >=2 pontos, mesmo piso do resto do projeto
                logger.info(
                    "scripts.measure_seed_sensitivity.celula",
                    label=label,
                    n_seeds_validos=len(edges),
                    detail="menos de 2 seeds com edge_bps computavel -- sem dispersao possivel",
                )
                continue

            mean = statistics.mean(edges)
            std = statistics.stdev(edges)
            median = statistics.median(edges)
            n = len(edges)
            p_value = alpha_gate_p_value(mean, std, n, min_edge_bps=0.0)
            significant = p_value < significance_level
            n_significant += int(significant)
            logger.info(
                "scripts.measure_seed_sensitivity.celula",
                label=label,
                n_seeds_validos=n,
                edge_bps_mediana=round(median, 2),
                edge_bps_media=round(mean, 2),
                edge_bps_std=round(std, 2),
                edge_bps_min=round(min(edges), 2),
                edge_bps_max=round(max(edges), 2),
                n_seeds_positivos=sum(1 for e in edges if e > 0),
                p_value=round(p_value, 4),
                significativo=significant,
            )

    logger.info(
        "scripts.measure_seed_sensitivity.concluido",
        n_celulas=n_cells,
        n_seeds=len(args.seeds),
        n_significativas_p_bruto=n_significant,
        significance_level=significance_level,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover -- execucao manual
    sys.exit(main())
