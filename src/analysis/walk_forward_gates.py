"""ADR-008 Fase 6 — gates codificados (Data/Model/Alpha) sobre o
artefato de walk-forward real (Fase 4,
`experiments/alpha_walk_forward_{symbol}_{resolution_id}.json`) e a
stability matrix (Fase 5, `src.analysis.stability_matrix`). O PADRÃO já
existia no repo — núcleo puro `_passes` + threshold em `constants.yaml`
+ campo no report, mesma forma de `backtest_lite.permanence_pass_
criterion`/`hhi.gate3_4_passes` (não a de `edge_gate_pass`, que é lógica
inline duplicada em 2 call sites — a ADR-008 cita os 3 como padrão-alvo,
mas só os 2 primeiros seguem a forma núcleo/casca completa).

O trabalho real desta fase não é código — é decisão do Manager sobre os
limiares (`CLAUDE.md` §Proveniência). Sem decisão explícita, os 2 novos
thresholds (`alpha_gate_data_min_frac_folds_usados`/`alpha_gate_model_
min_auc`) entram `provenance: ASSUMED` + `sweep_required: true`
(`config/constants.yaml`) — o gate Alpha reusa `alpha_layer1_permanence_
min_edge_bps` (já `DERIVED`), o mesmo conceito de "existe edge líquido"
que `edge_gate_pass` já testa sobre CPCV, aqui testado sobre
walk-forward.

**Definições operacionais** (as 3 perguntas que cada gate responde —
propostas aqui na AUSÊNCIA de decisão explícita do Manager sobre O QUE
cada gate mede, não só o limiar; sujeitas a correção):

- **Data**: a fração de folds walk-forward com trades suficientes
  (`n_folds_usados / n_folds_total`, nível combo×variant — `degenerado`
  já é conceito por fold, não por lado, ver `walk_forward.py`) é grande
  o bastante pra confiar no resto da medição daquele combo? `>=`
  threshold (não `>`) — maior cobertura é sempre melhor, empate no piso
  passa (mesma convenção de `permanence_pass_criterion`).
- **Model**: o classificador discrimina fora da amostra melhor que uma
  moeda honesta COM MARGEM (AUC médio pooled sobre os folds usáveis,
  nível combo×variant×lado)? `>=` threshold, `NaN` (nenhum fold com
  amostra suficiente pro AUC ser computável) SEMPRE falha — ausência de
  dado nunca é aprovação por omissão.
- **Alpha**: existe edge econômico líquido positivo (edge_bps médio
  pooled sobre os folds usáveis, nível combo×variant, MESMO threshold
  que o edge gate de CPCV já usa — break-even)? Comparação ESTRITA
  (`>`, não `>=`) — mesma convenção documentada em `edge_gate_pass`
  (`hyperparams_optuna.py`/`ag220_dual_gate_calibration.py`), `NaN`
  sempre falha."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from src.analysis.stability_matrix import StabilityMatrixResult

_SIDES: tuple[str, ...] = ("long", "short")


def data_gate_passes(frac_folds_usados: float, *, threshold: float) -> bool:
    """Definição operacional: ver docstring do módulo, eixo "Data".
    `NaN`/não-finito sempre falha (nunca `True` por omissão)."""
    if not np.isfinite(frac_folds_usados):
        return False
    return frac_folds_usados >= threshold


def model_gate_passes(auc_mean: float, *, min_auc: float) -> bool:
    """Definição operacional: ver docstring do módulo, eixo "Model"."""
    if not np.isfinite(auc_mean):
        return False
    return auc_mean >= min_auc


def alpha_gate_passes(edge_bps_mean: float, *, min_edge_bps: float) -> bool:
    """Definição operacional: ver docstring do módulo, eixo "Alpha"."""
    if not np.isfinite(edge_bps_mean):
        return False
    return edge_bps_mean > min_edge_bps


@dataclass(frozen=True, slots=True)
class GateVerdict:
    combo: str
    variant: str
    n_folds_total: int
    n_folds_usados: int
    frac_folds_usados: float
    data_gate_pass: bool
    edge_bps_mean: float
    alpha_gate_pass: bool
    auc_mean_by_side: dict[str, float]
    model_gate_pass_by_side: dict[str, bool]


def evaluate_gates(
    walk_forward_payload: dict[str, Any],
    stability: StabilityMatrixResult,
    *,
    data_min_frac_folds_usados: float,
    model_min_auc: float,
    alpha_min_edge_bps: float,
) -> GateVerdict:
    """`walk_forward_payload` — um `variant` dentro do JSON da Fase 4
    (mesmo payload que `stability_matrix.build_stability_matrix`
    consome). `stability` — o resultado já construído sobre o MESMO
    payload (`build_stability_matrix(walk_forward_payload, ...)`) —
    passado já pronto em vez de reconstruído aqui, pra não pagar o
    custo duas vezes quando o chamador já tem os dois."""
    n_folds_total = walk_forward_payload["n_folds_total"]
    n_folds_usados = walk_forward_payload["n_folds_usados"]
    frac_folds_usados = (
        n_folds_usados / n_folds_total if n_folds_total > 0 else float("nan")
    )
    edge_bps_mean = walk_forward_payload["aggregate"]["mean"]["edge_bps"]

    auc_mean_by_side: dict[str, float] = {}
    model_gate_pass_by_side: dict[str, bool] = {}
    for side in _SIDES:
        auc_mean = stability.dispersion_by_metric_and_side[side]["roc_auc"]["mean"]
        auc_mean_by_side[side] = auc_mean
        model_gate_pass_by_side[side] = model_gate_passes(auc_mean, min_auc=model_min_auc)

    return GateVerdict(
        combo=f"{stability.symbol}/{stability.resolution_id}",
        variant=stability.variant,
        n_folds_total=n_folds_total,
        n_folds_usados=n_folds_usados,
        frac_folds_usados=frac_folds_usados,
        data_gate_pass=data_gate_passes(frac_folds_usados, threshold=data_min_frac_folds_usados),
        edge_bps_mean=edge_bps_mean,
        alpha_gate_pass=alpha_gate_passes(edge_bps_mean, min_edge_bps=alpha_min_edge_bps),
        auc_mean_by_side=auc_mean_by_side,
        model_gate_pass_by_side=model_gate_pass_by_side,
    )
