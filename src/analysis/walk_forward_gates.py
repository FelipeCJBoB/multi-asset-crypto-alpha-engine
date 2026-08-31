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

**Correção 2026-08-31, rodada 2 (achado real de `audit_engineering`
sobre este próprio módulo — auditoria adversarial confirmou 2 achados
P1, ver `audit/architecture_gaps_log.yaml::AG-391` adendo):**

1. **Múltiplas comparações sem correção, p-valor nem exposto.**
   `model_gate_passes` decidia `pass`/`fail` por combo×variant×lado a
   `significance_level=0,05` fixo, célula a célula, sem nunca calcular
   nem devolver o p-valor — inviabilizando a correção de FDR que
   `src.validation.fdr_correction` (BH+BY) já implementa e que o
   `ADR-007` Item 4 aplicou um dia antes, na MESMA sessão, pro mesmo
   tipo de problema ("cuidado com falsos positivos", pedido do
   Manager). Sob 20 células testadas (5 combos × 2 camadas × 2 lados),
   o número esperado de "passes" por puro acaso sob H0 universal, sem
   correção, é ≈20×0,05=1 — e foi exatamente 1 antes desta correção.
   `model_gate_p_value` agora expõe o p-valor bruto; `GateVerdict.
   auc_p_value_by_side` carrega-o; `apply_fdr_to_model_gates` (novo,
   abaixo) aplica BH+BY sobre um LOTE de `GateVerdict`s via a mesma
   `apply_fdr_correction` já testada — `evaluate_gates` continua
   operando célula a célula (é uma auditoria pós-hoc, sem caller de
   produção ainda, `AG-391`), mas quem for consolidar um lote real deve
   usar `apply_fdr_to_model_gates`, não o veredito bruto por célula.
2. **`auc_std==0,0` decidia só pela média — divergia da convenção do
   módulo-irmão citado como espelho.** `score_quality._ic_dispersion_
   stats` retorna `NaN` (falha) no mesmo caso degenerado (dispersão
   zero); este módulo decidia `auc_mean > 0.5` (aprovação automática).
   Risco assimétrico real: com `n_trades` mediano de 20,5 por fold
   (docstring acima), AUC idêntico em múltiplos folds por coincidência
   de amostra pequena é alcançável, e o lado errado pra "decidir
   sozinho" num gate de capital real é o permissivo. Corrigido — `std
   ==0,0` agora sempre falha (mesma convenção "NaN/ausência de teste
   válido nunca é aprovação por omissão" já aplicada ao resto do
   módulo), nunca mais decide pela média.

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
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.stats import t as student_t

from src.analysis.stability_matrix import StabilityMatrixResult
from src.validation.fdr_correction import FdrResult, apply_fdr_correction

_SIDES: tuple[str, ...] = ("long", "short")
_MIN_FOLDS_FOR_TTEST = 2  # noqa: magic-number -- desvio-padrão amostral (ddof=1) exige >=2 pontos, mesmo piso de score_quality._MIN_FOLDS_FOR_DISPERSION


def data_gate_passes(n_folds_usados: int, *, min_folds: int) -> bool:
    """Definição operacional: ver docstring do módulo, eixo "Data". Piso
    ABSOLUTO de folds usáveis (não fração — ver "Correção 2026-08-31" na
    docstring do módulo). `>=` (empate no piso passa)."""
    return n_folds_usados >= min_folds


def model_gate_p_value(auc_mean: float, auc_std: float, n_folds: int) -> float:
    """P-valor UNICAUDAL do teste-t de uma amostra (H0: AUC_médio<=0,5,
    H1: AUC_médio>0,5) — `NaN` se não computável (`auc_mean`/`auc_std`
    não-finito, ou `n_folds<2`, sem desvio-padrão amostral não há teste
    possível). `std==0,0` com `n_folds>=2` (correção 2026-08-31, rodada
    2 — ver docstring do módulo) também devolve `NaN`, nunca decide pela
    média sozinho — mesma convenção de `score_quality._ic_dispersion_
    stats` no mesmo caso degenerado. Núcleo compartilhado de
    `model_gate_passes` (decisão por célula) e `apply_fdr_to_model_
    gates` (correção de múltiplas comparações sobre um lote)."""
    if not math.isfinite(auc_mean) or not math.isfinite(auc_std):
        return float("nan")
    if n_folds < _MIN_FOLDS_FOR_TTEST:
        return float("nan")
    if auc_std == 0.0:
        return float("nan")
    t_stat = (auc_mean - 0.5) / (auc_std / math.sqrt(n_folds))  # noqa: unguarded-ratio -- auc_std!=0.0 e n_folds>=2 ja garantidos pelos early-return acima nesta funcao, sqrt(n_folds) nunca e 0
    return float(student_t.sf(t_stat, df=n_folds - 1))


def model_gate_passes(
    auc_mean: float, auc_std: float, n_folds: int, *, significance_level: float
) -> bool:
    """Definição operacional: ver docstring do módulo, eixo "Model" —
    teste-t de uma amostra unicaudal, H0: AUC_médio<=0,5 vs H1:
    AUC_médio>0,5, ao nível `significance_level`, célula a célula (sem
    correção de múltiplas comparações — ver `apply_fdr_to_model_gates`
    pra consolidar um LOTE de células com FDR). `NaN` (inclui `n_folds<2`
    e `std==0,0`) sempre falha — ausência de teste válido nunca é
    aprovação por omissão."""
    p_value = model_gate_p_value(auc_mean, auc_std, n_folds)
    if math.isnan(p_value):
        return False
    return p_value < significance_level


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
    # P-valor bruto (unicaudal), NÃO ajustado por múltiplas comparações
    # -- ver `apply_fdr_to_model_gates` pra consolidar um LOTE de
    # GateVerdict com BH+BY (correção 2026-08-31, rodada 2).
    auc_p_value_by_side: dict[str, float]
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
    auc_p_value_by_side: dict[str, float] = {}
    model_gate_pass_by_side: dict[str, bool] = {}
    for side in _SIDES:
        disp = stability.dispersion_by_metric_and_side[side]["roc_auc"]
        auc_mean = disp["mean"]
        auc_std = disp["std"]
        n_folds_auc = int(disp["n"])
        p_value = model_gate_p_value(auc_mean, auc_std, n_folds_auc)
        auc_mean_by_side[side] = auc_mean
        auc_std_by_side[side] = auc_std
        n_folds_auc_by_side[side] = n_folds_auc
        auc_p_value_by_side[side] = p_value
        model_gate_pass_by_side[side] = (
            not math.isnan(p_value) and p_value < model_significance_level
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
        auc_p_value_by_side=auc_p_value_by_side,
        model_gate_pass_by_side=model_gate_pass_by_side,
    )


def apply_fdr_to_model_gates(
    verdicts: Sequence[GateVerdict], *, significance_level: float | None = None
) -> dict[str, FdrResult]:
    """Correção 2026-08-31, rodada 2 (achado real de `audit_engineering`
    sobre este módulo) — consolida o gate Model de um LOTE de
    `GateVerdict` (ex. os 5 combos × 2 camadas × 2 lados = 20 células da
    campanha real) via `src.validation.fdr_correction.apply_fdr_
    correction` (BH+BY, já testado, já usado no `ADR-007` Item 4 pro
    mesmo problema) — em vez do veredito bruto por célula (`GateVerdict.
    model_gate_pass_by_side`, sem correção de múltiplas comparações,
    anti-conservador sob 20 testes simultâneos a `alpha=0,05` cada).

    `p_value` de cada célula é UNICAUDAL (H1: AUC>0,5); `apply_fdr_
    correction` espera p-valor BILATERAL já convertido pelo chamador
    (ver docstring dela) — `p_bilateral = min(2*p_unicaudal, 1.0)`,
    identidade padrão pra distribuições simétricas (t de Student é
    simétrica em torno de 0). Células com `p_value=NaN` (sem teste
    válido — `n_folds<2`/`std==0,0`) são EXCLUÍDAS da família testada
    (nunca entram como p=1,0 nem como p=0,0 — não fazem parte do
    conjunto de hipóteses simultâneas, já que nenhum teste foi de fato
    realizado ali).

    Retorna `{f"{combo}/{variant}/{side}": FdrResult}` — chame com o
    resultado `.significant_bh`/`.significant_by` no lugar de
    `GateVerdict.model_gate_pass_by_side` bruto pra qualquer
    consolidação real de mais de 1 célula."""
    p_values: dict[str, float] = {}
    for verdict in verdicts:
        for side in _SIDES:
            p_one_sided = verdict.auc_p_value_by_side[side]
            if math.isnan(p_one_sided):
                continue
            label = f"{verdict.combo}/{verdict.variant}/{side}"
            p_values[label] = min(2.0 * p_one_sided, 1.0)
    results = apply_fdr_correction(p_values, significance_level=significance_level)
    return {r.label: r for r in results}
