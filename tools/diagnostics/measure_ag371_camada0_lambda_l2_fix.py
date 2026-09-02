"""AG-371 item (D) -- 2ª hipótese testada depois de `feature_fraction`
falhar (`measure_ag371_camada0_feature_fraction_fix.py`, 0,7/0,5/0,3
todos com `n_signals=0`). Mecanismo diferente: `lambda_l2` (L2 sobre o
VALOR da folha, não sobre QUAL feature é escolhida) deveria encolher a
magnitude de cada contribuição de árvore, amortecendo o acúmulo de log-
odds mesmo se `E27f_cost_atr_ratio` continuar sendo a feature preferida
em toda split -- mecanismo ortogonal ao de `feature_fraction` (que tenta
impedir a feature de aparecer; `lambda_l2` aceita que ela apareça mas
força cada folha a "pedir licença" pra dar um valor extremo).

Produção/global hoje: `lambda_l2=5,0` (idêntico nos dois hiperparâmetros
já medidos, stale e global -- nunca variado). Testa 20/50/100 (4x/10x/20x
o valor atual) -- mesma célula/desenho de `measure_ag371_camada0_
feature_fraction_fix.py`, resultado comparável direto.

PENDENTE-DE-EXECUÇÃO-HUMANA -- Claude não executa `.py` (CLAUDE.md,
"Protocolo de execução"), exceto autorização explícita do Manager na
sessão (dada em 2026-08-28, "atacar C>D>E... com solução robusta"). Rodar
com:

    uv run python tools/diagnostics/measure_ag371_camada0_lambda_l2_fix.py
"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import structlog

from src.features import build as features_build
from src.models import alpha
from src.models import pipeline as pl

logger = structlog.get_logger(__name__)

_SYMBOL = "BNBUSDT"
_RESOLUTION_ID = "R1"
_LAMBDA_L2_TO_TEST: tuple[float, ...] = (20.0, 50.0, 100.0)  # noqa: magic-number


def main() -> None:
    base_hyper = alpha.LGBMHyperparams.from_constants()
    logger.info(
        "ag371d.baseline_ja_medido",
        lambda_l2=base_hyper.lambda_l2,
        detail="5,0 (global/stale, nunca variado) ja mostrou n_signals=0 "
        "(AG-371-ADDENDUM-4/5) -- nao re-roda aqui, so referencia",
    )

    for l2 in _LAMBDA_L2_TO_TEST:
        hyper = dataclasses.replace(base_hyper, lambda_l2=l2)
        report = pl.run_layer1_sprint(
            symbol=_SYMBOL,
            resolution_id=_RESOLUTION_ID,
            feature_ids=features_build.T1_FEATURE_IDS,
            hyper=hyper,
            scratch=True,
        )
        c0 = report["camada0_backtest_by_path"]
        n_signals_total = sum(int(v.get("n_signals", 0)) for v in c0.values())
        lv = report["layer1_vs_layer0"]
        logger.info(
            "ag371d.lambda_l2_result",
            lambda_l2=l2,
            n_signals_total_camada0=n_signals_total,
            camada0_sharpe_mean=lv.get("camada0_sharpe_mean"),
            permanence_pass=lv.get("permanence_pass"),
            n_paths_camada1_supera_camada0=lv.get("n_paths_camada1_supera_camada0"),
        )


if __name__ == "__main__":
    main()
