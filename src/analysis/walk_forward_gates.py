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
limiares (`CLAUDE.md` §Proveniência). Sem decisão explícita, os 2
thresholds (`alpha_gate_data_min_folds_usados`/`alpha_gate_model_
significance_level`) entram `provenance: DERIVED`/`LITERATURE` +
`sweep_required: true` (`config/constants.yaml`, ver derivação completa
lá) — o gate Alpha reusa `alpha_layer1_permanence_min_edge_bps` (já
`DERIVED`), o mesmo conceito de "existe edge líquido" que
`edge_gate_pass` já testa sobre CPCV, aqui testado sobre walk-forward.

**Correção 2026-08-31 (pós-Fase 8, "investigar e medir os thresholds
corretamente" — Manager):** os 2 originais (`alpha_gate_data_min_frac_
folds_usados`=0,5, `alpha_gate_model_min_auc`=0,52) eram `ASSUMED`
explicitamente marcados "ARBITRÁRIO por ora" — nenhuma medição os
embasava. Medir contra o artefato real revelou que a FORMA do gate,
não só o número, estava errada em ambos os eixos:

- **Model**: um AUC agregado (`roc_auc.mean` sobre os folds usáveis) tem
  um erro-padrão POR FOLD dado pela fórmula de Hanley-McNeil (1982) sob
  H0 (AUC=0,5): `SE² = (n_pos+n_neg+1)/(12·n_pos·n_neg)`. Medido contra
  os 62 fold-lado reais da campanha 2026-08-31 (`n_trades` por
  fold-lado usado no AUC: mediana=20,5, p25=10): `SE(AUC|H0)` fica entre
  0,13 (mediana) e 0,19 (p25) — um piso fixo de 0,52 está a menos de 1
  desvio-padrão de amostragem de UM fold só, sem poder estatístico real
  pra distinguir sinal de ruído. Substituído por teste-t de uma amostra
  unicaudal (H0: AUC_médio≤0,5, H1: AUC_médio>0,5) sobre mean/std/n já
  computados por `stability_matrix` — mesmo padrão já estabelecido em
  `score_quality._ic_dispersion_stats` (`tstat = mean/(std/sqrt(n))`).
- **Data**: a forma FRAÇÃO (`n_usados/n_total`) penaliza de forma
  desigual combos com `n_folds_total` diferente (12 vs 19 nesta
  campanha) pro MESMO requisito real — um piso ABSOLUTO de observações
  independentes suficientes pro teste-t acima não ser dominado por
  ruído de amostra pequena. Substituído por contagem absoluta
  (`n_folds_usados >= min_folds`).

Consequência medida, honesta, não escondida: sob os novos thresholds,
NENHUM dos 10 combo×variant da campanha real atinge `n_folds_usados>=10`
(máximo real medido = 8) — o teto de folds do desenho walk-forward atual
(`initial_train_years=2` + passo trimestral, 12-19 folds totais) é
estruturalmente insuficiente pra este piso. Achado real, registrado em
`AG-391` — não um efeito colateral do número escolhido.

**Definições operacionais** (as 3 perguntas que cada gate responde —
propostas aqui na AUSÊNCIA de decisão explícita do Manager sobre O QUE
cada gate mede, não só o limiar; sujeitas a correção):

- **Data**: o número ABSOLUTO de folds walk-forward com trades
  suficientes (`n_folds_usados`, nível combo×variant — `degenerado` já
  é conceito por fold, não por lado, ver `walk_forward.py`) é grande o
  bastante pra confiar no resto da medição daquele combo? `>=`
  threshold (não `>`) — maior cobertura é sempre melhor, empate no piso
  passa (mesma convenção de `permanence_pass_criterion`).
- **Model**: o classificador discrimina fora da amostra melhor que uma
  moeda honesta, com significância estatística (teste-t unicaudal sobre
  o AUC médio pooled dos folds usáveis, nível combo×variant×lado)? Exige
  `n_folds>=2` (desvio-padrão amostral indefinido com 1 ponto) — `NaN`
  ou `n_folds<2` SEMPRE falha, ausência de dado nunca é aprovação por
  omissão.
- **Alpha**: existe edge econômico líquido positivo (edge_bps médio
  pooled sobre os folds usáveis, nível combo×variant, MESMO threshold
  que o edge gate de CPCV já usa — break-even)? Comparação ESTRITA
  (`>`, não `>=`) — mesma convenção documentada em `edge_gate_pass`
  (`hyperparams_optuna.py`/`ag220_dual_gate_calibration.py`), `NaN`
  sempre falha."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.stats import t as student_t

from src.analysis.stability_matrix import StabilityMatrixResult

_SIDES: tuple[str, ...] = ("long", "short")
_MIN_FOLDS_FOR_TTEST = 2  # noqa: magic-number -- desvio-padrão amostral (ddof=1) exige >=2 pontos, mesmo piso de score_quality._MIN_FOLDS_FOR_DISPERSION


def data_gate_passes(n_folds_usados: int, *, min_folds: int) -> bool:
    """Definição operacional: ver docstring do módulo, eixo "Data". Piso
    ABSOLUTO de folds usáveis (não fração — ver "Correção 2026-08-31" na
    docstring do módulo). `>=` (empate no piso passa)."""
    return n_folds_usados >= min_folds


def model_gate_passes(
    auc_mean: float, auc_std: float, n_folds: int, *, significance_level: float
) -> bool:
    """Definição operacional: ver docstring do módulo, eixo "Model" —
    teste-t de uma amostra unicaudal, H0: AUC_médio<=0,5 vs H1:
    AUC_médio>0,5, ao nível `significance_level`. `NaN`/`n_folds<2`
    sempre falha (sem desvio-padrão amostral não há teste possível, não
    é aprovação por omissão)."""
    if not math.isfinite(auc_mean) or not math.isfinite(auc_std):
        return False
    if n_folds < _MIN_FOLDS_FOR_TTEST:
        return False
    if auc_std == 0.0:
        return auc_mean > 0.5
    t_stat = (auc_mean - 0.5) / (auc_std / math.sqrt(n_folds))  # noqa: unguarded-ratio -- auc_std!=0.0 e n_folds>=2 ja garantidos pelos 2 early-return acima nesta funcao, sqrt(n_folds) nunca e 0
    t_crit = float(student_t.ppf(1.0 - significance_level, df=n_folds - 1))
    return t_stat > t_crit


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
    auc_std_by_side: dict[str, float]
    n_folds_auc_by_side: dict[str, int]
    model_gate_pass_by_side: dict[str, bool]


def evaluate_gates(
    walk_forward_payload: dict[str, Any],
    stability: StabilityMatrixResult,
    *,
    data_min_folds_usados: int,
    model_significance_level: float,
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
        n_folds_usados / n_folds_total  # noqa: unguarded-ratio -- guardado pelo ternario: so divide quando n_folds_total>0
        if n_folds_total > 0
        else float("nan")
    )
    edge_bps_mean = walk_forward_payload["aggregate"]["mean"]["edge_bps"]

    auc_mean_by_side: dict[str, float] = {}
    auc_std_by_side: dict[str, float] = {}
    n_folds_auc_by_side: dict[str, int] = {}
    model_gate_pass_by_side: dict[str, bool] = {}
    for side in _SIDES:
        disp = stability.dispersion_by_metric_and_side[side]["roc_auc"]
        auc_mean = disp["mean"]
        auc_std = disp["std"]
        n_folds_auc = int(disp["n"])
        auc_mean_by_side[side] = auc_mean
        auc_std_by_side[side] = auc_std
        n_folds_auc_by_side[side] = n_folds_auc
        model_gate_pass_by_side[side] = model_gate_passes(
            auc_mean, auc_std, n_folds_auc, significance_level=model_significance_level
        )

    return GateVerdict(
        combo=f"{stability.symbol}/{stability.resolution_id}",
        variant=stability.variant,
        n_folds_total=n_folds_total,
        n_folds_usados=n_folds_usados,
        frac_folds_usados=frac_folds_usados,
        data_gate_pass=data_gate_passes(n_folds_usados, min_folds=data_min_folds_usados),
        edge_bps_mean=edge_bps_mean,
        alpha_gate_pass=alpha_gate_passes(edge_bps_mean, min_edge_bps=alpha_min_edge_bps),
        auc_mean_by_side=auc_mean_by_side,
        auc_std_by_side=auc_std_by_side,
        n_folds_auc_by_side=n_folds_auc_by_side,
        model_gate_pass_by_side=model_gate_pass_by_side,
    )
