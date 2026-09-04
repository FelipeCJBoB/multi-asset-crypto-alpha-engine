"""Script chamador da campanha de walk-forward real (ADR-008 Fase 4) —
fecha `AG-396` (achado da auditoria adversarial externa,
`docs/prompts/REFUTACAO_CONSOLIDADA_0de20_20260831.md`: nenhuma
invocação real de `walk_forward.run_walk_forward_for_combo` estava
commitada fora de `tests/unit/test_models_walk_forward_driver.py` — os 5
artefatos em `experiments/alpha_walk_forward_*.json` que sustentam a
ADR-008/auditoria adversarial interna/externa/"Caso 0/20" não eram
reproduzíveis nem auditáveis por terceiros).

Uso — reproduzir a campanha original (mesma seed/política que gerou os
artefatos atuais, `--overwrite` necessário pois os arquivos já existem):

    uv run python scripts/run_walk_forward_campaign.py --overwrite

Testar `AG-395`/prova D2 (tau calculado sobre score in-sample) sob a
política já implementada em `AG-210` (nunca aplicada aos 5 candidatos
reais) — escreve em arquivo SEPARADO, nunca sobrescreve o canônico:

    uv run python scripts/run_walk_forward_campaign.py --tau-policy total_common_oof

Um combo só, pra teste rápido antes da campanha completa:

    uv run python scripts/run_walk_forward_campaign.py --combo BTCUSDT/R2 \
        --tau-policy total_common_oof
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

import structlog

from src.models import alpha, dataset, hyperparams_by_combo, pipeline
from src.models import walk_forward as wf
from src.models._constants import load_constant
from src.models._paths import EXPERIMENTS_DIR
from src.monitoring.logging import configure_logging

logger = structlog.get_logger(__name__)

# Os 5 candidatos promovidos (config/constants.yaml::alpha_production_
# hyperparam_override, decisão do Manager 2026-08-31) — mesma lista da
# Seção 1.4/2.2 da ADR-008 e do artefato "Caso 0/20". Não lida
# dinamicamente da constante porque a constante mapeia pra `run_stamp`
# (histórico de hiperparâmetro), não pra lista de combos — a lista de
# combos É a decisão de escopo do Manager, hardcoded aqui de propósito
# (mudar quais 5 candidatos são promovidos é decisão fora do escopo
# deste script).
_CANDIDATOS: tuple[tuple[str, str], ...] = (
    ("BTCUSDT", "R2"),
    ("SOLUSDT", "R2"),
    ("SOLUSDT", "R3"),
    ("XRPUSDT", "R2"),
    ("XRPUSDT", "R3"),
)
_VARIANTS: tuple[str, ...] = (alpha.VARIANT_CAMADA1, alpha.VARIANT_CAMADA0)


def _run_combo(
    symbol: str,
    resolution_id: str,
    *,
    seed: int,
    tau_policy: str,
    device_type: str,
) -> dict[str, Any]:
    """1 combo, as 2 camadas — `mf_data` construído 1 vez, reusado entre
    Camada1/Camada0 (mesmo padrão já documentado em
    `run_walk_forward_for_combo`: "reusado entre Camada1/Camada0 do
    mesmo combo")."""
    # `vol_estimator_id` -- `build_modeling_frame` exige explícito sob
    # `resolution_id` (dollar bar, sem `bar_ms` pra derivar default). Mesma
    # resolução que `pipeline.run_layer1_sprint` já faz pro caminho de
    # produção (`canonical_volatility_estimator`, promovido a default
    # 2026-08-27) -- não reinventada aqui.
    vol_estimator_id = str(load_constant("canonical_volatility_estimator"))
    mf = dataset.build_modeling_frame(
        symbol=symbol, resolution_id=resolution_id, vol_estimator_id=vol_estimator_id
    )
    payload: dict[str, Any] = {}
    for variant in _VARIANTS:
        hyper = hyperparams_by_combo.load_production_override(symbol, resolution_id, variant)
        if hyper is None:
            raise ValueError(
                f"_run_combo: {symbol}/{resolution_id}/{variant} sem entrada em "
                "alpha_production_hyperparam_override (constants.yaml) -- esperado "
                "presente pros 5 candidatos promovidos, ver ADR-008 Seção 1.4"
            )
        logger.info(
            "scripts.run_walk_forward_campaign.combo_iniciado",
            symbol=symbol,
            resolution_id=resolution_id,
            variant=variant,
            tau_policy=tau_policy,
            seed=seed,
        )
        result = wf.run_walk_forward_for_combo(
            mf.data,
            symbol=symbol,
            resolution_id=resolution_id,
            variant=variant,
            hyper=hyper,
            seed=seed,
            device_type=device_type,
            tau_policy=tau_policy,
        )
        payload[variant] = asdict(result)
        logger.info(
            "scripts.run_walk_forward_campaign.combo_concluido",
            symbol=symbol,
            resolution_id=resolution_id,
            variant=variant,
            n_folds_total=result.n_folds_total,
            n_folds_usados=result.n_folds_usados,
        )
    return payload


def _parse_combo_arg(raw: str) -> tuple[str, str]:
    if "/" not in raw:
        raise argparse.ArgumentTypeError(
            f"--combo {raw!r} -- formato esperado SYMBOL/RESOLUTION, ex. BTCUSDT/R2"
        )
    symbol, resolution_id = raw.split("/", 1)
    return symbol, resolution_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--tau-policy",
        default=alpha.TAU_POLICY_LEGACY_PER_SIDE,
        choices=[
            alpha.TAU_POLICY_LEGACY_PER_SIDE,
            alpha.TAU_POLICY_TOTAL_COMMON_OOF,
            alpha.TAU_POLICY_TOTAL_COMMON_OOF_NO_NOFILL,
        ],
        help="AG-210/AG-395 (audit/architecture_gaps_log.yaml) -- legacy_per_side "
        "reproduz o comportamento que gerou os artefatos atuais; total_common_oof "
        "testa a correção já implementada pra tau in-sample, nunca aplicada aos 5 "
        "candidatos reais; total_common_oof_no_nofill (AG-436) é a MESMA política "
        "sem as barras NOFILL na população out-of-fit -- par de comparação pra "
        "atribuir o overshoot de 2,3-3,0x medido no AG-428 a uma variável só.",
    )
    parser.add_argument("--device-type", default="cpu", choices=["cpu", "cuda"])
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Default: alpha_random_seed de constants.yaml (a mesma seed única de "
        "produção que gerou os artefatos atuais).",
    )
    parser.add_argument(
        "--combo",
        action="append",
        type=_parse_combo_arg,
        default=None,
        metavar="SYMBOL/RESOLUTION",
        help="Ex. --combo BTCUSDT/R2 (repetível). Default: os 5 candidatos promovidos.",
    )
    parser.add_argument("--out-dir", type=Path, default=EXPERIMENTS_DIR)
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Sem esta flag, recusa sobrescrever um artefato existente -- os JSONs "
        "atuais sustentam toda a auditoria '0/20' (ADR-008 + auditorias "
        "adversariais interna/externa), ver AG-396.",
    )
    args = parser.parse_args(argv)

    configure_logging(json_output=False)

    seed_default = int(load_constant("alpha_random_seed"))
    seed = args.seed if args.seed is not None else seed_default
    combos = tuple(args.combo) if args.combo else _CANDIDATOS

    # Sufixo no nome do arquivo quando a política E/OU a seed NÃO são as
    # canônicas -- nunca colide com o artefato canônico (tau_policy=
    # legacy_per_side + seed=alpha_random_seed é o que gerou os 5 JSONs
    # que sustentam a ADR-008/auditoria adversarial). AG-396: overwrite
    # acidental do artefato canônico destruiria a base de comparação de
    # toda a auditoria "0/20". Item 4 do roadmap "Caso 0/20" (>=5 seeds)
    # precisa de um sufixo POR SEED pra as 5 rodadas não colidirem entre
    # si nem com o canônico.
    suffix_policy = (
        "" if args.tau_policy == alpha.TAU_POLICY_LEGACY_PER_SIDE else f"_{args.tau_policy}"
    )
    suffix_seed = "" if seed == seed_default else f"_seed{seed}"
    suffix = suffix_policy + suffix_seed

    falhas: list[str] = []
    for symbol, resolution_id in combos:
        out_path = args.out_dir / f"alpha_walk_forward_{symbol}_{resolution_id}{suffix}.json"
        if out_path.exists() and not args.overwrite:
            logger.error(
                "scripts.run_walk_forward_campaign.artefato_ja_existe_sem_overwrite",
                path=str(out_path),
                detail="use --overwrite para sobrescrever deliberadamente",
            )
            falhas.append(f"{symbol}/{resolution_id}: {out_path} já existe")
            continue
        try:
            payload = _run_combo(
                symbol,
                resolution_id,
                seed=seed,
                tau_policy=args.tau_policy,
                device_type=args.device_type,
            )
        except Exception:
            logger.exception(
                "scripts.run_walk_forward_campaign.combo_falhou",
                symbol=symbol,
                resolution_id=resolution_id,
            )
            falhas.append(f"{symbol}/{resolution_id}: falhou, ver log acima")
            continue
        # AG-396 -- seed/política/entrypoint gravados no próprio artefato,
        # não só no nome do arquivo (o nome não sobrevive a um `cp`).
        payload["run_metadata"] = {
            "seed": seed,
            "tau_policy": args.tau_policy,
            "device_type": args.device_type,
            "symbol": symbol,
            "resolution_id": resolution_id,
            "producer_entrypoint": "scripts.run_walk_forward_campaign",
        }
        pipeline.write_report_atomic(payload, dest_path=out_path)
        logger.info("scripts.run_walk_forward_campaign.artefato_escrito", path=str(out_path))

    if falhas:
        logger.error(
            "scripts.run_walk_forward_campaign.campanha_com_falhas",
            n_falhas=len(falhas),
            falhas=falhas,
        )
        return 1

    logger.info(
        "scripts.run_walk_forward_campaign.campanha_concluida",
        n_combos=len(combos),
        tau_policy=args.tau_policy,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover -- execução manual
    sys.exit(main())
