"""Campanha COMPLETA de busca Optuna com corte de data (item 12 do
roadmap "Caso 0/20", `AG-411`) — escala de produção (`alpha_optuna_
n_trials`, default 150), não a validação reduzida (20 trials) já rodada.
Autorização explícita do Manager pra gastar `n_lifetime` real nesta
escala (2026-09-01).

**Isolamento deliberado**: `storage_dir` e `scratch=True` sempre
isolados da produção (`artifacts/scratch/optuna_studies_t0_cutoff_full/`)
— `t0_end` não entra no hash de identidade content-addressed (`AG-411`),
então nunca pode tocar o `OPTUNA_STUDIES_DIR`/artefato canônico de
produção. Resultado desta campanha é um INSUMO pra decisão, não uma
promoção automática de hiperparâmetro — promover a produção é decisão
separada, não tomada por este script.

`t0_end` por combo = `test_start` real do walk-forward (medido nesta
sessão, `AG-393` item 1 / Seção 5.1 corrigida da ADR-008): `BTCUSDT/R2`
alcança 2022 (único dos 5), os outros 4 começam em 2023-10-01.

Uso:

    uv run python -m scripts.run_t0_cutoff_full_campaign
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

import structlog

from src.models import alpha
from src.models import hyperparams_optuna as hpo
from src.models._constants import load_constant
from src.monitoring.logging import configure_logging

logger = structlog.get_logger(__name__)

_COMBOS: tuple[tuple[str, str, str], ...] = (
    ("BTCUSDT", "R2", "2022-01-01"),
    ("SOLUSDT", "R2", "2023-10-01"),
    ("SOLUSDT", "R3", "2023-10-01"),
    ("XRPUSDT", "R2", "2023-10-01"),
    ("XRPUSDT", "R3", "2023-10-01"),
)
_VARIANTS: tuple[str, ...] = (alpha.VARIANT_CAMADA1, alpha.VARIANT_CAMADA0)
_STORAGE_DIR = Path("artifacts/scratch/optuna_studies_t0_cutoff_full")
_RESULTS_PATH = Path("experiments/t0_cutoff_full_campaign_results.json")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--n-trials",
        type=int,
        default=None,
        help="Default: alpha_optuna_n_trials de constants.yaml (150, orçamento de produção).",
    )
    parser.add_argument(
        "--combo",
        action="append",
        default=None,
        metavar="SYMBOL/RESOLUTION",
        help="Ex. --combo BTCUSDT/R2 (repetível). Default: os 5 candidatos.",
    )
    args = parser.parse_args(argv)

    configure_logging(json_output=False)
    n_trials = (
        args.n_trials if args.n_trials is not None else int(load_constant("alpha_optuna_n_trials"))
    )
    combos = _COMBOS
    if args.combo:
        wanted = set(args.combo)
        combos = tuple(c for c in _COMBOS if f"{c[0]}/{c[1]}" in wanted)

    results: list[dict[str, object]] = []
    if _RESULTS_PATH.exists():
        results = json.loads(_RESULTS_PATH.read_text(encoding="utf-8"))
        done = {(r["symbol"], r["resolution_id"], r["variant"]) for r in results}
    else:
        done = set()

    total = len(combos) * len(_VARIANTS)
    i = 0
    for symbol, resolution_id, t0_end in combos:
        for variant in _VARIANTS:
            i += 1
            if (symbol, resolution_id, variant) in done:
                logger.info(
                    "scripts.run_t0_cutoff_full_campaign.ja_feito_pulando",
                    symbol=symbol,
                    resolution_id=resolution_id,
                    variant=variant,
                    progresso=f"{i}/{total}",
                )
                continue
            logger.info(
                "scripts.run_t0_cutoff_full_campaign.iniciando",
                symbol=symbol,
                resolution_id=resolution_id,
                variant=variant,
                t0_end=t0_end,
                n_trials=n_trials,
                progresso=f"{i}/{total}",
            )
            result = hpo.run_search_for_combo(
                symbol=symbol,
                resolution_id=resolution_id,
                variant=variant,
                n_trials=n_trials,
                storage_dir=_STORAGE_DIR,
                t0_end=t0_end,
                scratch=True,
            )
            results.append(
                {
                    "symbol": symbol,
                    "resolution_id": resolution_id,
                    "variant": variant,
                    "t0_end": t0_end,
                    "n_trials": n_trials,
                    "best_value": result.best_value,
                    "best_hyper": dataclasses.asdict(result.best_hyper),
                    "study_name": result.study_name,
                }
            )
            _RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
            _RESULTS_PATH.write_text(
                json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            logger.info(
                "scripts.run_t0_cutoff_full_campaign.concluido_combo",
                symbol=symbol,
                resolution_id=resolution_id,
                variant=variant,
                best_value=result.best_value,
                progresso=f"{i}/{total}",
            )

    logger.info(
        "scripts.run_t0_cutoff_full_campaign.tudo_concluido",
        n_studies=len(results),
        results_path=str(_RESULTS_PATH),
    )
    return 0


if __name__ == "__main__":  # pragma: no cover -- execucao manual
    sys.exit(main())
