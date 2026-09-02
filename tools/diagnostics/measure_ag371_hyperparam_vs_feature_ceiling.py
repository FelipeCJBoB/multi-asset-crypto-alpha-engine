"""AG-371 item (b) -- teste DIFERENCIAL, não "controle limpo" (o global
também é `ASSUMED`/nunca medido, `constants.yaml::alpha_lgbm_num_leaves`/
`min_child_samples`; ver `audit/architecture_gaps_log.yaml::AG-371`
status). Rerroda as 4 células cujo Camada0 zerou (`n_signals=0` nas 5
paths) sob o hiperparâmetro por-combo STALE (calibrado ADR-003 sob 62
features, `AG-371`) -- desta vez sob `use_hyperparams_by_combo=False`
(hiperparâmetro global limpo, `num_leaves=8`, `min_child_samples=20`) --
pra separar 2 hipóteses concorrentes:

  (H1) "teto de capacidade real do vetor de 22 features" -- zeramento
       persiste mesmo sob hiperparâmetro global (mais raso e menos
       restritivo que o por-combo);
  (H2) "artefato do hiperparâmetro stale" -- zeramento desaparece sob
       hiperparâmetro global.

ETHUSDT/R1 (5ª célula zerada, AG-371) já é o controle de graça: usa
hiperparâmetro GLOBAL desde sempre (não está nas 10 combinações
calibradas) e já zera as 5 paths (`experiments/alpha_layer1_report_
ETHUSDT_R1.json`, `camada0_backtest_by_path.*.n_signals == 0` nas 5,
confirmado nesta investigação) -- evidência POR SI SÓ a favor de H1 pra
essa célula específica (zerou SEM hiperparâmetro stale). Este script
gera o mesmo dado pras outras 4, pra comparar.

`scratch=True` (AG-368) -- exploratório, não retreino canônico, não
sobrescreve `artifacts/predictions_alpha/` imutável. `feature_ids=
T1_FEATURE_IDS` explícito (AG-366) -- evita `config_hash` colidir com
`feature_ids=None`. Custo: ~700-960s POR CÉLULA (medido no retreino
canônico de 28/08, SPRINT_LOG) -- 4 células, ~50-65min total, sequencial.

N_lifetime: NÃO registrado aqui -- mesmo raciocínio já documentado em
`run_layer1_sprint_all_combinations` (D-14): reavaliar um desenho já
fixado sob um hiperparâmetro que já é o default de `constants.yaml` (não
uma busca nova) não é, por definição do ledger, trial novo. Decisão do
Manager se isso precisa mudar, não decidida aqui (B23).

PENDENTE-DE-EXECUÇÃO-HUMANA -- Claude não executa `.py` (CLAUDE.md,
"Protocolo de execução"), exceto autorização explícita do Manager na
sessão (dada em 2026-08-28 pra este item). Rodar com:

    uv run python tools/diagnostics/measure_ag371_hyperparam_vs_feature_ceiling.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import json
from typing import Any

import structlog

from src.features import build as features_build
from src.models import pipeline
from src.models._paths import EXPERIMENTS_DIR

logger = structlog.get_logger(__name__)

#: as 4 células com Camada0 zerada (n_signals=0 nas 5 paths) que passam
#: por `alpha_hyperparams_by_combo.yaml` (AG-371). BNBUSDT_R1/R2,
#: BTCUSDT_R1, XRPUSDT_R1 -- a 5ª (ETHUSDT_R1) já é hiperparâmetro
#: global, não entra aqui (é o controle, já medido).
_CELLS: tuple[tuple[str, str], ...] = (
    ("BNBUSDT", "R1"),
    ("BNBUSDT", "R2"),
    ("BTCUSDT", "R1"),
    ("XRPUSDT", "R1"),
)


def _n_signals_by_path(report: dict[str, Any], key: str) -> dict[str, int | None]:
    by_path = report.get(key, {})
    return {path: entry.get("n_signals") for path, entry in by_path.items()}


def _original_n_signals(symbol: str, resolution_id: str) -> dict[str, int | None] | None:
    path = EXPERIMENTS_DIR / f"alpha_layer1_report_{symbol}_{resolution_id}.json"
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as f:
        original = json.load(f)
    return _n_signals_by_path(original, "camada0_backtest_by_path")


def main() -> None:
    results: list[dict[str, Any]] = []
    for symbol, resolution_id in _CELLS:
        original_n_signals = _original_n_signals(symbol, resolution_id)
        logger.info(
            "ag371b.rerun_start",
            symbol=symbol,
            resolution_id=resolution_id,
            n_signals_original_stale_hyper=original_n_signals,
        )
        reports = pipeline.run_layer1_sprint_all_combinations(
            symbols=(symbol,),
            resolutions=(resolution_id,),
            feature_ids=features_build.T1_FEATURE_IDS,
            use_hyperparams_by_combo=False,
            scratch=True,
        )
        report = reports[(symbol, resolution_id)]
        n_signals_global = _n_signals_by_path(report, "camada0_backtest_by_path")
        camada0_sharpe_mean = report.get("layer1_vs_layer0", {}).get("camada0_sharpe_mean")
        zerou_com_global = all(v == 0 for v in n_signals_global.values())

        row = {
            "symbol": symbol,
            "resolution_id": resolution_id,
            "n_signals_original_stale_hyper": original_n_signals,
            "n_signals_global_hyper": n_signals_global,
            "camada0_sharpe_mean_global_hyper": camada0_sharpe_mean,
            "zerou_com_global_tambem": zerou_com_global,
            "veredito": (
                "H1 (teto de capacidade -- zerou mesmo com hiper global limpo, "
                "mesma assinatura de ETHUSDT_R1)"
                if zerou_com_global
                else "H2 (artefato do hiperparametro stale -- zeramento some sob global)"
            ),
        }
        results.append(row)
        logger.info("ag371b.rerun_done", **row)

    n_h1 = sum(1 for r in results if r["zerou_com_global_tambem"])
    logger.info(
        "ag371b.resumo_final",
        n_celulas=len(results),
        n_confirmam_h1_teto_capacidade=n_h1,
        n_confirmam_h2_artefato_hyper=len(results) - n_h1,
        leitura=(
            "H1 em TODAS as 4 + ETHUSDT_R1 ja H1 -- teto de capacidade e a "
            "explicacao dominante, hiperparametro stale nao e causa suficiente "
            "sozinha (decisao do Manager sobre proximo passo, nao este script)"
            if n_h1 == len(results)
            else "misto ou H2 predominante -- hiperparametro stale contribui "
            "de fato, recalibracao (AG-371 item c) deve resolver total ou "
            "parcialmente (decisao do Manager)"
        ),
    )


if __name__ == "__main__":
    main()
