"""Recuperação pontual (2026-09-02): 4 parquets de trajetória de trial
(`alpha_optuna_trials_{combo}.parquet`) foram apagados por um `git clean
-fd experiments/` rodado por engano enquanto a campanha
`run_t0_cutoff_full_campaign --tag post_ag421_ag422` ainda escrevia
arquivos novos nessa pasta. As studies SQLite (fonte real, em
`artifacts/scratch/optuna_studies_t0_cutoff_control_post_ag421_ag422/`)
nunca foram tocadas -- este script só reabre cada study e rechama
`export_trial_trajectory`, sem retreinar nada, custo ~0.

Uso:

    uv run python -m scripts.recover_missing_trial_trajectories
"""

from __future__ import annotations

from pathlib import Path

import optuna
import structlog

from src.models import hyperparams_optuna as hpo
from src.monitoring.logging import configure_logging

logger = structlog.get_logger(__name__)

_STORAGE_DIR = Path("artifacts/scratch/optuna_studies_t0_cutoff_control_post_ag421_ag422")
_MISSING: tuple[tuple[str, str, str], ...] = (
    ("BTCUSDT", "R2", "camada1"),
    ("BTCUSDT", "R2", "camada0"),
    ("SOLUSDT", "R2", "camada1"),
    ("SOLUSDT", "R2", "camada0"),
)


def main() -> int:
    configure_logging(json_output=False)
    for symbol, resolution_id, variant in _MISSING:
        db_path = _STORAGE_DIR / f"{symbol}_{resolution_id}_{variant}_cpu.db"
        studies = optuna.study.get_all_study_summaries(storage=f"sqlite:///{db_path.resolve()}")
        if len(studies) != 1:
            raise ValueError(f"{db_path}: esperado 1 study, achei {len(studies)}")
        study = optuna.load_study(
            study_name=studies[0].study_name, storage=f"sqlite:///{db_path.resolve()}"
        )
        out_path = hpo.export_trial_trajectory(
            study, symbol=symbol, resolution_id=resolution_id, variant=variant
        )
        logger.info(
            "recover_missing_trial_trajectories.recuperado",
            symbol=symbol,
            resolution_id=resolution_id,
            variant=variant,
            path=str(out_path),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
