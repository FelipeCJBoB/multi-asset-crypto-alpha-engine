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
    uv run python -m scripts.promote_control_campaign_to_production \
        --results-path experiments/t0_cutoff_control_campaign_results_post_ag421_ag422.json
"""

from __future__ import annotations

import argparse
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


def main(argv: list[str] | None = None) -> int:
    configure_logging(json_output=False)

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--results-path",
        type=Path,
        default=_CONTROL_RESULTS_PATH,
        help="AG-422 -- resultados de uma campanha --tag (ex. post_ag421_ag422), "
        "em vez do arquivo de controle original (AG-419/AG-420).",
    )
    args = parser.parse_args(argv)

    run_stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    campaign_results: list[dict[str, Any]] = json.loads(
        args.results_path.read_text(encoding="utf-8")
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

    # AG-427 (2026-09-03) -- texto passou a ser gerado a partir do nome do
    # arquivo de resultados (via --tag) em vez de hardcoded pra uma unica
    # rodada histórica (achado real: o texto anterior citava só AG-421/
    # AG-422, ficou enganoso assim que uma campanha nova/tag diferente
    # rodasse -- esta função é chamada de novo a cada promoção, não só
    # uma vez). `stem` do arquivo já carrega o `--tag` (AG-422), suficiente
    # pra rastrear qual campanha gerou o override sem reescrever este
    # script a cada correção futura.
    overrides_novos: dict[str, str] = {}
    source_campaign = (
        f"{args.results_path.stem} -- seed corrigido (AG-399), SEM corte de data, "
        "1 seed, 150 trials -- NAO e confirmacao multi-seed como o processo ADR-007 "
        "anterior. Ver o --tag no nome do arquivo (se houver) pro contexto exato "
        "desta campanha (vetor de features/mecanismo de tau/etc. vigentes no "
        "momento em que rodou -- consultar audit/architecture_gaps_log.yaml pela "
        "data)."
        if args.results_path != _CONTROL_RESULTS_PATH
        else "t0_cutoff_control_campaign (AG-419) -- seed corrigido (AG-399), SEM "
        "corte de data, 1 seed, 150 trials -- NAO e confirmacao multi-seed como o "
        "processo ADR-007 anterior"
    )
    for (symbol, resolution_id), variants in by_combo.items():
        payload: dict[str, Any] = {
            "symbol": symbol,
            "resolution_id": resolution_id,
            "source_campaign": source_campaign,
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
