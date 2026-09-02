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

**`--control` (`AG-416`)**: a campanha original (150 trials × 10 studies,
commits `1af8782`/`70c22ce`) mostrou 8/10 células melhorando contra
produção, mas CONFUNDIDO com a correção do bug de seed compartilhado
(`AG-399`) aplicada na mesma rodada — produção foi achada sob seed=42
GLOBAL, esta campanha usa `_derived_sampler_seed` por combo desde o
início. `--control` roda a MESMA campanha (mesmo seed corrigido) mas
com `t0_end=None` (sem corte) — isola se a melhora vem do corte de data
ou só do seed corrigido. Storage/resultados em arquivo SEPARADO, nunca
mistura com a campanha `t0_end` original.

**`--tag` (`AG-422`)**: sufixa `storage_dir`/`results_path` com
`_{tag}` — necessário sempre que a IDENTIDADE da busca muda por um
jeito que `results.json` não rastreia (`feature_ids`/`search_space`,
via `config_hash`) mas o `done`-tracking deste script rastreia só
`(symbol, resolution_id, variant)`. Sem `--tag`, reusar `--control`
depois de `AG-421` (vetor T1 36->30) ou `AG-422` (filtro
anti-degeneração no objective) leria o `results.json` ANTIGO e pularia
os 10 combos como "já feitos" — nenhum trial novo rodaria, silenciosamente,
mesmo a busca subjacente sendo outra (`study_name` novo, `config_hash`
diferente). `--tag` força um `results.json`/`storage_dir` novos, campanha
genuinamente do zero.

Uso:

    uv run python -m scripts.run_t0_cutoff_full_campaign
    uv run python -m scripts.run_t0_cutoff_full_campaign --control
    uv run python -m scripts.run_t0_cutoff_full_campaign --control --tag post_ag421_ag422
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

_COMBOS: tuple[tuple[str, str, str | None], ...] = (
    ("BTCUSDT", "R2", "2022-01-01"),
    ("SOLUSDT", "R2", "2023-10-01"),
    ("SOLUSDT", "R3", "2023-10-01"),
    ("XRPUSDT", "R2", "2023-10-01"),
    ("XRPUSDT", "R3", "2023-10-01"),
)
_VARIANTS: tuple[str, ...] = (alpha.VARIANT_CAMADA1, alpha.VARIANT_CAMADA0)
_STORAGE_DIR = Path("artifacts/scratch/optuna_studies_t0_cutoff_full")
_RESULTS_PATH = Path("experiments/t0_cutoff_full_campaign_results.json")
_CONTROL_STORAGE_DIR = Path("artifacts/scratch/optuna_studies_t0_cutoff_control")
_CONTROL_RESULTS_PATH = Path("experiments/t0_cutoff_control_campaign_results.json")


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
    parser.add_argument(
        "--control",
        action="store_true",
        help="AG-416 -- roda sem t0_end (t0_end=None), isolando o efeito do seed "
        "corrigido (AG-399) do efeito do corte de data. Storage/resultados separados.",
    )
    parser.add_argument(
        "--tag",
        type=str,
        default=None,
        help="AG-422 -- sufixa storage_dir/results_path com _{tag}. Use sempre que "
        "feature_ids/search_space mudou desde a última campanha (o done-tracking "
        "deste script não rastreia config_hash, só symbol/resolution_id/variant).",
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
    if args.control:
        combos = tuple((symbol, resolution_id, None) for symbol, resolution_id, _ in combos)

    storage_dir = _CONTROL_STORAGE_DIR if args.control else _STORAGE_DIR
    results_path = _CONTROL_RESULTS_PATH if args.control else _RESULTS_PATH
    if args.tag:
        storage_dir = storage_dir.parent / f"{storage_dir.name}_{args.tag}"
        results_path = results_path.with_name(
            f"{results_path.stem}_{args.tag}{results_path.suffix}"
        )

    results: list[dict[str, object]] = []
    if results_path.exists():
        results = json.loads(results_path.read_text(encoding="utf-8"))
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
                storage_dir=storage_dir,
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
            results_path.parent.mkdir(parents=True, exist_ok=True)
            results_path.write_text(
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
        results_path=str(results_path),
    )
    return 0


if __name__ == "__main__":  # pragma: no cover -- execucao manual
    sys.exit(main())
