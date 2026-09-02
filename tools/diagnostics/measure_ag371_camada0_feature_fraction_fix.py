"""AG-371 item (D) -- testa a hipótese líder do item (C)
(`AG-371-ADDENDUM-6`): Camada0 não tem NENHUM freio contra uma feature
contínua de alta correlação (`E27f_cost_atr_ratio`) dominar TODA árvore
via busca gulosa de split -- `feature_fraction=1,0` (produção, global E
por-combo) deixa `E27f` disponível em 100% das splits de 100% das 300
árvores. `feature_fraction<1,0` (colsample por árvore, regularização
padrão de literatura, nunca testada aqui) deveria quebrar essa dominância
por desenho -- cada árvore só vê um subconjunto aleatório de features,
então parte das 300 árvores não pode usar `E27f` nenhuma vez.

Testa 3 valores (0,7 / 0,5 / 0,3) contra o baseline (1,0, já medido) em
UMA célula (BNBUSDT/R1, já tem baseline completo desta investigação) --
mede `hhi`/`n_eff_factors_t1`/share de `E27f` no gain (fold 0 long, tudo
já persistido de graça) E o efeito final em `n_signals`/`tau`
(`camada0_backtest_by_path`, precisa retreinar as 15 folds pra medir
isso corretamente -- CPCV real, não só fold 0).

Não decide sozinho se isso vira default de produção -- mede, reporta,
Manager decide com o número na mão (B23: nunca presumir faixa esperada).

PENDENTE-DE-EXECUÇÃO-HUMANA -- Claude não executa `.py` (CLAUDE.md,
"Protocolo de execução"), exceto autorização explícita do Manager na
sessão (dada em 2026-08-28, "atacar C>D>E... com solução robusta"). Rodar
com:

    uv run python tools/diagnostics/measure_ag371_camada0_feature_fraction_fix.py
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
_FEATURE_FRACTIONS_TO_TEST: tuple[float, ...] = (0.7, 0.5, 0.3)  # noqa: magic-number


def main() -> None:
    base_hyper = alpha.LGBMHyperparams.from_constants()
    logger.info(
        "ag371d.baseline_ja_medido",
        feature_fraction=base_hyper.feature_fraction,
        detail="1,0 (global) ja mostrou 52% de raw score>0,9 e n_signals=0 "
        "(AG-371-ADDENDUM-4/5) -- nao re-roda aqui, so referencia",
    )

    for ff in _FEATURE_FRACTIONS_TO_TEST:
        hyper = dataclasses.replace(base_hyper, feature_fraction=ff)
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
            "ag371d.feature_fraction_result",
            feature_fraction=ff,
            n_signals_total_camada0=n_signals_total,
            camada0_sharpe_mean=lv.get("camada0_sharpe_mean"),
            permanence_pass=lv.get("permanence_pass"),
            n_paths_camada1_supera_camada0=lv.get("n_paths_camada1_supera_camada0"),
        )


if __name__ == "__main__":
    main()
