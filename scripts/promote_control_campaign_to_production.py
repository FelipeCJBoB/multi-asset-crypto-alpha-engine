"""Promove os hiperparâmetros da campanha de CONTROLE (seed corrigido,
`AG-399`, SEM corte de data) a `alpha_production_hyperparam_override` —
decisão de negócio explícita do Manager (2026-09-01): "aplica no código
real os fix que estão prontos, promovendo os itens achados no
diagnóstico pro run canônico".

**Por que a campanha de CONTROLE, não a de `t0_end`**: `AG-419` isolou
que a melhora medida vem do seed corrigido, não do corte de data — a
campanha de controle é a correção do bug ISOLADA (só o seed muda vs.
o processo que gerou os hiperparâmetros atuais), sem misturar uma
segunda mudança de metodologia ainda não validada.

**Schema honesto, não forjado**: os hiperparâmetros de produção
anteriores vinham de uma confirmação de 10 seeds (`ADR-007` Item 2/3) —
esta campanha é busca de 1 seed, 150 trials. O JSON de confirmação
escrito aqui NÃO replica os campos de confirmação multi-seed (seria
fabricar confiança que não existe) — só `winner.hyper` (o único campo
que `hyperparams_by_combo.load_production_override` lê) mais metadados
honestos da campanha real (`best_value`, `n_trials`, `source_campaign`).

Uso:

    uv run python -m scripts.promote_control_campaign_to_production
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from src.models._paths import EXPERIMENTS_DIR
from src.monitoring.logging import configure_logging

logger = structlog.get_logger(__name__)

_CONTROL_RESULTS_PATH = Path("experiments/t0_cutoff_control_campaign_results.json")


def main() -> int:
    configure_logging(json_output=False)

    run_stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    campaign_results: list[dict[str, Any]] = json.loads(
        _CONTROL_RESULTS_PATH.read_text(encoding="utf-8")
    )

    by_combo: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    for entry in campaign_results:
        key = (str(entry["symbol"]), str(entry["resolution_id"]))
        by_combo.setdefault(key, {})[entry["variant"]] = {
            "winner": {
                "hyper": entry["best_hyper"],
                "best_value": entry["best_value"],
            },
            "n_trials": entry["n_trials"],
            "study_name": entry["study_name"],
        }

    overrides_novos: dict[str, str] = {}
    for (symbol, resolution_id), variants in by_combo.items():
        payload: dict[str, Any] = {
            "symbol": symbol,
            "resolution_id": resolution_id,
            "source_campaign": "t0_cutoff_control_campaign (AG-419) -- seed corrigido "
            "(AG-399), SEM corte de data, 1 seed, 150 trials -- NAO e confirmacao "
            "multi-seed como o processo ADR-007 anterior",
            "run_stamp": run_stamp,
            **variants,
        }
        out_path = (
            EXPERIMENTS_DIR
            / f"alpha_optuna_confirmation_{symbol}_{resolution_id}_{run_stamp}.json"
        )
        out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        overrides_novos[f"{symbol}_{resolution_id}"] = run_stamp
        logger.info(
            "scripts.promote_control_campaign_to_production.confirmacao_escrita",
            symbol=symbol,
            resolution_id=resolution_id,
            path=str(out_path),
            variants=sorted(variants.keys()),
        )

    logger.info(
        "scripts.promote_control_campaign_to_production.run_stamp_para_constants_yaml",
        run_stamp=run_stamp,
        overrides=overrides_novos,
    )
    logger.info("scripts.promote_control_campaign_to_production.concluido")
    return 0


if __name__ == "__main__":  # pragma: no cover -- execucao manual
    sys.exit(main())
