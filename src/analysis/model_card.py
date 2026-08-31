"""ADR-008 Fase 8 — cartão final / model card: consolida as Fases 0-7
numa estrutura ÚNICA por (combo, variant, lado), cobrindo as 8
métricas-chave do consultor (Test AUC, Test Rank IC, IC IR, Q10-Q1, OOS
folds X/X, feature stability%, regime stability%, generalization gap%).
Mesmo padrão de `backtest_lite.permanence_pass_criterion` — o veredito
final é regra CODIFICADA (reusa `walk_forward_gates.GateVerdict` da
Fase 6), nunca julgamento manual na hora de montar o cartão.

**Por que vive em `src.analysis`, não `src.models`** — mesma fronteira
de `stability_matrix.py`/`walk_forward_gates.py` (auditoria pós-hoc
sobre artefato já escrito).

**2 das 8 métricas ficam `TBD` deliberadamente (B23, CLAUDE.md — nunca
inventar faixa esperada):**
- `regime_stability_pct` — a Fase 8 do plano original previa medir
  estabilidade ENTRE regimes de mercado (R0-R5), mas nenhuma fase
  anterior desta ADR computou isso para os candidatos do walk-forward
  (`calibration_diagnostics.stratified_by_regime` existe no repo, mas
  nunca foi aplicado às predições do walk-forward — exigiria nova
  integração, fora do escopo já coberto).
- `generalization_gap_pct` — `score_quality.compute_train_val_test_gap`
  (Fase 3) existe e está com fiação em `pipeline.run_layer1_sprint`
  (CPCV), mas o run canônico dos 5 candidatos (ADR-007) foi executado
  ANTES da Fase 3 existir — os artefatos CPCV atuais não têm esse campo,
  e o walk-forward (Fase 4) nunca chamou essa função. Medir isso exigiria
  outro retreino real (CPCV ou walk-forward), fora do orçamento já
  autorizado nesta rodada.

As outras 6 são REAIS, extraídas dos artefatos já escritos:
`test_auc`/`test_rank_ic`/`q10_minus_q1_bps` vêm de `stability_matrix.
StabilityMatrixResult.dispersion_by_metric_and_side` (Fase 5); `ic_ir`
é DERIVADO ali mesmo (`mean/std`, mesma fórmula de `score_quality.
_ic_dispersion_stats`, não uma sexta métrica nova calculada do zero);
`oos_folds_usados`/`oos_folds_total` vêm do artefato de walk-forward
(Fase 4); `feature_stability_pct` é a frequência do feature #1 por gain
nativo entre os folds usáveis (`top_feature_frequency_by_side`, Fase
5) — o valor MÁXIMO do dict, já ordenado decrescente."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from src.analysis.stability_matrix import StabilityMatrixResult
from src.analysis.walk_forward_gates import GateVerdict

_SIDES: tuple[str, ...] = ("long", "short")


@dataclass(frozen=True, slots=True)
class ModelCard:
    combo: str
    variant: str
    side: str
    test_auc: float
    test_rank_ic: float
    ic_ir: float
    q10_minus_q1_bps: float
    oos_folds_usados: int
    oos_folds_total: int
    feature_stability_pct: float
    # `None` = TBD (ver docstring do módulo) -- nunca `0.0`/`NaN`
    # inventado no lugar de "não medido".
    regime_stability_pct: float | None
    generalization_gap_pct: float | None
    gate_data_pass: bool
    gate_alpha_pass: bool
    gate_model_pass: bool
    gate_pass: bool  # AND dos 3 acima -- veredito final CODIFICADO


def _ic_ir(mean: float, std: float) -> float:
    """`mean/std` — mesma fórmula de `score_quality._ic_dispersion_
    stats`, `NaN` se `std` não-finito/zero (indefinido, não inventa
    infinito)."""
    if not math.isfinite(std) or std == 0.0:
        return float("nan")
    return mean / std


def build_model_card(
    walk_forward_payload: dict[str, Any],
    stability: StabilityMatrixResult,
    gate_verdict: GateVerdict,
    *,
    side: str,
) -> ModelCard:
    """`walk_forward_payload`/`stability`/`gate_verdict` — os 3 artefatos
    já construídos sobre o MESMO combo×variant (Fases 4/5/6), passados
    prontos em vez de reconstruídos aqui."""
    disp = stability.dispersion_by_metric_and_side[side]
    auc_mean = disp["roc_auc"]["mean"]
    ic_mean = disp["ic_spearman_pooled"]["mean"]
    ic_std = disp["ic_spearman_pooled"]["std"]
    q_mean = disp["q10_minus_q1_bps"]["mean"]

    gain_freq = stability.top_feature_frequency_by_side[side]
    feature_stability_pct = max(gain_freq.values()) if gain_freq else float("nan")

    gate_model_pass = gate_verdict.model_gate_pass_by_side[side]
    gate_pass = gate_verdict.data_gate_pass and gate_verdict.alpha_gate_pass and gate_model_pass

    return ModelCard(
        combo=gate_verdict.combo,
        variant=gate_verdict.variant,
        side=side,
        test_auc=auc_mean,
        test_rank_ic=ic_mean,
        ic_ir=_ic_ir(ic_mean, ic_std),
        q10_minus_q1_bps=q_mean,
        oos_folds_usados=walk_forward_payload["n_folds_usados"],
        oos_folds_total=walk_forward_payload["n_folds_total"],
        feature_stability_pct=feature_stability_pct,
        regime_stability_pct=None,
        generalization_gap_pct=None,
        gate_data_pass=gate_verdict.data_gate_pass,
        gate_alpha_pass=gate_verdict.alpha_gate_pass,
        gate_model_pass=gate_model_pass,
        gate_pass=gate_pass,
    )


def build_model_cards_for_combo(
    walk_forward_payload: dict[str, Any],
    stability: StabilityMatrixResult,
    gate_verdict: GateVerdict,
) -> tuple[ModelCard, ...]:
    """1 `ModelCard` por lado (`long`/`short`) — conveniência sobre
    `build_model_card` pros 2 lados de um combo×variant de uma vez."""
    return tuple(
        build_model_card(walk_forward_payload, stability, gate_verdict, side=side)
        for side in _SIDES
    )
