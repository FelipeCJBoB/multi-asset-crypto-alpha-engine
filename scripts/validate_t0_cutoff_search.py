"""Validação em ESCALA REDUZIDA do item 12 (roadmap "Caso 0/20") — testa
a DIREÇÃO do achado E1 (HPO viu o período que o walk-forward trata como
fora-da-amostra) antes de comprometer o orçamento de uma campanha
completa (150 trials × 10 studies, ~2h30 medido em ADR-007 Item 1).

**Escopo deliberadamente pequeno**: poucos trials, poucos combos, storage
isolado (nunca toca os studies de produção — `run_search_for_combo`
exige isso via guard, ver `AG-411`). Objetivo é medir se cortar por data
muda o hiperparâmetro vencedor de forma MATERIAL — não produzir um
hiperparâmetro pronto pra promover.

Uso:

    uv run python -m scripts.validate_t0_cutoff_search
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
from pathlib import Path

import structlog

from src.models import alpha
from src.models import hyperparams_optuna as hpo
from src.monitoring.logging import configure_logging

logger = structlog.get_logger(__name__)

# (symbol, resolution_id, t0_end) -- t0_end = test_start real do walk-forward
# desse combo, medido nesta sessão (fold_id=0 dos artefatos canônicos):
# BTCUSDT/R2 alcança 2022 (único dos 5, ver Seção 5.1 corrigida da
# ADR-008); os outros 4 começam em 2023-10-01.
_VALIDATION_COMBOS: tuple[tuple[str, str, str], ...] = (
    ("BTCUSDT", "R2", "2022-01-01"),
    ("XRPUSDT", "R3", "2023-10-01"),
)
_VALIDATION_STORAGE_DIR = Path("artifacts/scratch/optuna_studies_t0_cutoff_validation")
_VALIDATION_N_TRIALS = 20  # noqa: magic-number -- escala de validacao, nao o orcamento de producao (150, alpha_optuna_n_trials)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n-trials", type=int, default=_VALIDATION_N_TRIALS)
    args = parser.parse_args(argv)

    configure_logging(json_output=False)

    for symbol, resolution_id, t0_end in _VALIDATION_COMBOS:
        for variant in (alpha.VARIANT_CAMADA1,):
            logger.info(
                "scripts.validate_t0_cutoff_search.iniciando",
                symbol=symbol,
                resolution_id=resolution_id,
                variant=variant,
                t0_end=t0_end,
                n_trials=args.n_trials,
            )
            result = hpo.run_search_for_combo(
                symbol=symbol,
                resolution_id=resolution_id,
                variant=variant,
                n_trials=args.n_trials,
                storage_dir=_VALIDATION_STORAGE_DIR,
                t0_end=t0_end,
                scratch=True,
            )
            logger.info(
                "scripts.validate_t0_cutoff_search.concluido_combo",
                symbol=symbol,
                resolution_id=resolution_id,
                variant=variant,
                t0_end=t0_end,
                best_value=result.best_value,
                best_hyper=dataclasses.asdict(result.best_hyper),
            )

    logger.info("scripts.validate_t0_cutoff_search.tudo_concluido")
    return 0


if __name__ == "__main__":  # pragma: no cover -- execucao manual
    sys.exit(main())
