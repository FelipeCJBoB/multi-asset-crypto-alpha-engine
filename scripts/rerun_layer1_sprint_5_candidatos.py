"""Re-roda `run_layer1_sprint` (produção — 1 seed, `run_layer1_sprint`,
não busca/confirmação multi-seed) pros 5 candidatos promovidos, sob o
hiperparâmetro NOVO (`AG-420` — campanha de controle, seed corrigido
`AG-399`). Regenera `experiments/alpha_layer1_report_{symbol}_
{resolution_id}.json` — a base real da aba "Run Canônico — 5
Candidatos" do artefato "ADR-007 — Painel de Execução".

`load_production_override` já é checado automaticamente dentro de
`pipeline.run_layer1_sprint_all_combinations` (independente de
`use_hyperparams_by_combo`) — só chamando com os 5 pares (symbol,
resolution_id) certos, sem hiperparâmetro explícito, já aplica o
override novo de `alpha_production_hyperparam_override`.

Uso:

    uv run python -m scripts.rerun_layer1_sprint_5_candidatos
"""

from __future__ import annotations

import sys

import structlog

from src.models import pipeline
from src.models._constants import load_constant
from src.monitoring.logging import configure_logging

logger = structlog.get_logger(__name__)

_CANDIDATOS: tuple[tuple[str, str], ...] = (
    ("BTCUSDT", "R2"),
    ("SOLUSDT", "R2"),
    ("SOLUSDT", "R3"),
    ("XRPUSDT", "R2"),
    ("XRPUSDT", "R3"),
)


def main() -> int:
    configure_logging(json_output=False)
    vol_estimator_id = str(load_constant("canonical_volatility_estimator"))

    for symbol, resolution_id in _CANDIDATOS:
        logger.info(
            "scripts.rerun_layer1_sprint_5_candidatos.iniciando",
            symbol=symbol,
            resolution_id=resolution_id,
        )
        pipeline.run_layer1_sprint_all_combinations(
            symbols=(symbol,),
            resolutions=(resolution_id,),
            vol_estimator_id=vol_estimator_id,
            device_type="cpu",
        )
        logger.info(
            "scripts.rerun_layer1_sprint_5_candidatos.concluido_combo",
            symbol=symbol,
            resolution_id=resolution_id,
        )

    logger.info("scripts.rerun_layer1_sprint_5_candidatos.concluido")
    return 0


if __name__ == "__main__":  # pragma: no cover -- execucao manual
    sys.exit(main())
