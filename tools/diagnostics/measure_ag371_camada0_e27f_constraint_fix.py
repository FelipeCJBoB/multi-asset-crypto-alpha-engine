"""AG-371 item (D) -- HISTÓRICO, achado já PROMOVIDO a produção
(2026-08-28, "totalmente aprovado, pode transformar em produção
canônico ponta a ponta"). Mediu o impacto de restringir SÓ `E27f_cost_
atr_ratio` dentro de Camada0 via um parâmetro EXPERIMENTAL (`camada0_
forced_constraints`, valor `-1` fixo, não recalculado por IC) que EXISTIU
só neste script -- já foi REMOVIDO de `alpha.fit_side_model`/`run_fold`/
`run_all_folds`/`pipeline.run_layer1_sprint` depois de promovido, porque
o mecanismo definitivo (`alpha.CAMADA0_CONSTRAINED_FEATURES`, direção
lida de `ic_results` por fold/lado, não hardcoded) agora é DEFAULT
incondicional de produção pra toda Camada0 -- `main()` abaixo foi
ATUALIZADO pra chamar `run_layer1_sprint` puro (sem o parâmetro
removido), servindo agora de REGRESSÃO -- confirma que o comportamento
de produção já reproduz o resultado medido no experimento original.

Resultado que motivou a promoção (BNBUSDT/R1, CPCV completo):
`n_signals` 0->2407, `camada0_sharpe_mean` NaN->-4,54, `hhi` 0,87->0,069,
`E27f` sai do top-6 de gain -- não torna Camada0 lucrativo (baseline
fraco por desenho), torna o gate de permanência mensurável.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import structlog

from src.features import build as features_build
from src.models import pipeline as pl

logger = structlog.get_logger(__name__)

_SYMBOL = "BNBUSDT"
_RESOLUTION_ID = "R1"


def main() -> None:
    logger.info(
        "ag371d_e27f.baseline_pre_promocao",
        detail="sem constraint nenhum mostrava n_signals=0/gain E27f=93% "
        "(AG-371-ADDENDUM-4/6) -- CAMADA0_CONSTRAINED_FEATURES agora e "
        "default incondicional (AG-371-ADDENDUM-8), este run confirma "
        "que o comportamento de producao ja reproduz o resultado medido",
    )

    report = pl.run_layer1_sprint(
        symbol=_SYMBOL,
        resolution_id=_RESOLUTION_ID,
        feature_ids=features_build.T1_FEATURE_IDS,
        scratch=True,
    )
    c0 = report["camada0_backtest_by_path"]
    n_signals_total = sum(int(v.get("n_signals", 0)) for v in c0.values())
    lv = report["layer1_vs_layer0"]
    logger.info(
        "ag371d_e27f.resultado_cpcv_completo",
        n_signals_total_camada0=n_signals_total,
        camada0_sharpe_mean=lv.get("camada0_sharpe_mean"),
        camada1_sharpe_mean=lv.get("camada1_sharpe_mean"),
        permanence_pass=lv.get("permanence_pass"),
        n_paths_camada1_supera_camada0=lv.get("n_paths_camada1_supera_camada0"),
        n_paths_total=lv.get("n_paths_total"),
        economic_gate=report.get("economic_gate"),
    )


if __name__ == "__main__":
    main()
