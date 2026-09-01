"""Gate E0 (D-14) — esquema de permutação travado (P0, bloqueante) —
`docs/meta_model_design_doc_2026-08-22.md` §2.6, §15.1/§15.2.

**Módulo `analysis/`, medição pós-hoc, zero treino** — mesmo precedente de
`gate_efficiency.py`/`m4_critical_windows.py` (fora do `importlinter` de
propósito). `analysis` pode ler `models`/`labels`/`validation` livremente
(contrato real de `pyproject.toml`: só `exchange/data/features/regime/
risk/execution/live/monitoring` são proibidos de ler `labels`; `models não
importa analysis` é a única direção fechada — o inverso é livre).

**Escopo desta rodada: só P0.** `§15.2`:

```
P0  Esquema de permutação travado + VALIDAÇÃO DO NULO (§2.6)  [bloqueante]
P1  edges_ms sobre união temporal (D-16, AG-151)              [bloqueante, FECHADO]
P2  Diagnóstico de saturação isotônica                         [não iniciado]
P3  E0-piloto (provisório, single-symbol, grade legada)        [não iniciado]
```

Este módulo entrega a PRIMITIVA de permutação + a estatística agregada
(AUC ponderada por `uniqueness`) + a validação obrigatória do nulo. A
inventariação completa de FP/TP sobre `predictions.parquet` real
(universo `side_hat != 0 ∧ is_oof`, diagnósticos de §2.6) é P3/E0-piloto,
NÃO construída aqui — não é escopo de P0, é o próximo passo depois deste.

## Duas decisões de interpretação que o design doc não fecha por completo

O texto do §2.6 é **travado** ("ESQUEMA DE PERMUTAÇÃO — travado na v3"),
mas dois termos não têm definição operacional 100% inequívoca no texto —
seguindo a própria regra do `CLAUDE.md` ("toda regra de decisão travada a
priori precisa de definição operacional de cada termo"), a decisão é
tomada AQUI, explicitamente, não deixada para julgamento silencioso na
hora de programar:

1. **"Circular-shift por bloco... deslocamento sorteado uniforme sobre o
   comprimento da série... série tratada como circular."** Implementado
   como UMA ÚNICA rotação circular em TEMPO CONTÍNUO (`circular_shift_by_
   time`) da série inteira — não reordena nada internamente, então
   preserva QUALQUER estrutura de blocos contíguos por construção, sem
   precisar quantizar o deslocamento em múltiplos de largura de grupo.
   Motivo de não quantizar: `alpha_b1_n_seeds = 1000` (constante que o
   próprio §2.6 aponta para `n_seeds`) é ordens de grandeza maior que
   `n_groups` (6) — um esquema quantizado só teria 6 deslocamentos
   distintos possíveis, tornando 1000 sementes majoritariamente
   redundantes. "Comprimento de bloco... a largura de grupo do CPCV" é
   usado aqui como métrica REPORTADA (`n_effective_blocks`, diagnóstico),
   não como granularidade do sorteio.
2. **"Se ficar materialmente acima [de 5%], o nulo está mal calibrado."**
   "Materialmente acima" operacionalizado via intervalo de confiança
   binomial (Wilson, `scipy.stats.binomtest`) em vez de uma banda de
   tolerância inventada: `well_calibrated` é `True` sse 5% cai DENTRO do
   IC de 95% da taxa de PASS empírica observada em `n_trials` réplicas do
   procedimento inteiro.

**Se a leitura acima divergir da intenção original do design doc,
sinalizar ao Manager antes de tratar `AG-XXX`/P0 como fechado** — é
exatamente o tipo de gap que motivou `AG-114`/`AG-118`/`AG-122`.

## Por que a validação do nulo não é tautológica

Rodar o procedimento inteiro (estatística observada + nulo permutado +
p95 + PASS/FAIL) sobre uma feature SEM relação real com o alvo, mas usando
o MESMO mecanismo de rotação circular tanto para o "observado" quanto para
o "nulo", seria circular por construção — um valor amostrado da mesma
distribuição do seu próprio nulo excede o p95 dessa distribuição ~5% do
tempo quase por definição, independente de qualquer erro na implementação.
`validate_null_calibration` evita isso: o "observado" de cada trial usa um
deslocamento FIXO e independente (uma família diferente de amostragem do
que os `n_seeds_per_trial` deslocamentos do nulo interno daquele trial) —
o teste passa a medir de verdade se o esquema de nulo captura a
variabilidade que uma configuração "mesma estrutura de bloco, zero relação
real" exibiria, não uma tautologia estatística."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import numpy as np
import polars as pl
import structlog
from numpy.typing import NDArray
from scipy import stats
from sklearn.metrics import roc_auc_score

from src.labels.weights import compute_concurrency_and_uniqueness
from src.models._constants import load_constant

logger = structlog.get_logger(__name__)

IntArray = NDArray[np.int64]
FloatArray = NDArray[np.float64]

_MIN_STATES_FOR_AUC: Final[int] = 2
_MIN_CLASSES_FOR_AUC: Final[int] = 2


class MetaFpInventoryError(Exception):
    """Base para erros deste módulo."""


# ============================================================================
# Classes sobre barrier_hit (§2.6) — y_fp
# ============================================================================


def classify_fp_binary(labels: pl.DataFrame) -> pl.DataFrame:
    """Adiciona `y_fp` (Int8): `SL` -> 1 (FP duro); `TP` -> 0 (acerto);
    `TIME` -> `1 - 1[ret_net > 0]` (texto literal do §2.6: "TIME ->
    1[ret_net>0]" é a taxa de ACERTO, `y_fp` é o complemento); `NOFILL`
    -> `null` (classe N, fora do numerador/denominador — reportada em
    separado, nunca imputada). Requer `barrier_hit`/`ret_net` (schema de
    `LABEL_COLUMNS`, `src.labels.triple_barrier`)."""
    return labels.with_columns(
        y_fp=pl.when(pl.col("barrier_hit") == "NOFILL")
        .then(None)
        .when(pl.col("barrier_hit") == "SL")
        .then(1)
        .when(pl.col("barrier_hit") == "TP")
        .then(0)
        .when((pl.col("barrier_hit") == "TIME") & (pl.col("ret_net") > 0.0))
        .then(0)
        .when(pl.col("barrier_hit") == "TIME")
        .then(1)
        .otherwise(None)
        .cast(pl.Int8)
    )


# ============================================================================
# Estatística agregada — AUC ponderada de P̂(y_fp | estado) (§2.6, regra de
# agregação: "o estimador é reajustado dentro de cada permutação")
# ============================================================================


def weighted_state_positive_rate(
    y: FloatArray, state_ids: IntArray, weight: FloatArray, n_states: int
) -> FloatArray:
    """`P̂(y=1 | estado)`, empírica, ponderada por `weight` — recomputada a
    cada chamada (nunca cacheada entre permutações; é o "estimador
    reajustado dentro de cada permutação" do §2.6, sem isso o nulo não
    carrega o otimismo do ajuste). Estado sem massa de peso (`sum(weight)
    <= 0` no estado, incluindo estado nunca observado) vira `NaN`, não
    `0.0` — taxa indefinida é diferente de taxa zero."""
    rates = np.full(n_states, np.nan, dtype=np.float64)
    for state in range(n_states):
        mask = state_ids == state
        w = weight[mask]
        total_w = float(w.sum())
        if total_w <= 0.0:
            continue
        rates[state] = float(np.sum(w * y[mask]) / total_w)
    return rates


def score_from_state(state_ids: IntArray, state_rate: FloatArray) -> FloatArray:
    """Score por linha = taxa empírica do PRÓPRIO estado da linha —
    converte o preditor categórico (`regime`) num score contínuo válido
    para AUC, sem introduzir nenhum ajuste externo."""
    return state_rate[state_ids]


def weighted_state_auc(
    y: FloatArray, state_ids: IntArray, weight: FloatArray, n_states: int
) -> float:
    """AUC ponderada (§2.6, regra de agregação) entre `y_fp` e o score
    `P̂(y=1|estado)` do próprio estado de cada linha. Guarda dupla, `NaN`
    (não `0.0`/erro) se indefinida: (a) menos de `_MIN_STATES_FOR_AUC`
    estados com massa observada; (b) menos de `_MIN_CLASSES_FOR_AUC`
    classes distintas em `y` na subpopulação com score válido."""
    rate = weighted_state_positive_rate(y, state_ids, weight, n_states)
    n_observed_states = int(np.sum(~np.isnan(rate)))
    if n_observed_states < _MIN_STATES_FOR_AUC:
        return float("nan")

    score = score_from_state(state_ids, rate)
    valid = ~np.isnan(score)
    y_valid = y[valid]
    if np.unique(y_valid).shape[0] < _MIN_CLASSES_FOR_AUC:
        return float("nan")

    return float(roc_auc_score(y_valid, score[valid], sample_weight=weight[valid]))


# ============================================================================
# Circular-shift por bloco (§2.6, ESQUEMA DE PERMUTAÇÃO — travado na v3)
# ============================================================================


def draw_circular_shift_ms(t0_ms: IntArray, rng: np.random.Generator) -> int:
    """Deslocamento em ms, uniforme sobre `[0, duração_da_série)`. `+1` na
    duração espelha a convenção de `cpcv.assign_time_groups` (fronteira
    direita exclusiva cobrindo o próprio máximo)."""
    duration_ms = int(t0_ms.max() - t0_ms.min()) + 1
    return int(rng.integers(0, duration_ms))


def circular_shift_by_time(t0_ms: IntArray, values: IntArray, *, shift_ms: int) -> IntArray:
    """Rotação circular EM TEMPO CONTÍNUO de `values` (indexado por
    `t0_ms`) — a "série tratada como circular" do §2.6. Desloca a série
    INTEIRA sem reordenar nada internamente: por construção, preserva
    qualquer estrutura de blocos contíguos dos dois lados (nenhuma
    posição relativa muda, só o ponto de ancoragem). `values` é tratado
    como função em degrau de `t0` (regime muda só em fronteira de linha,
    nunca entre linhas) — o valor em qualquer instante `τ` é o da última
    linha original com `t0 <= τ`, via busca binária.

    Aceita `t0_ms` fora de ordem (ordena internamente); devolve `values`
    deslocado na MESMA ordem de entrada de `t0_ms`."""
    order = np.argsort(t0_ms, kind="stable")
    t0_sorted = t0_ms[order]
    values_sorted = values[order]

    t_min = int(t0_sorted[0])
    duration_ms = int(t0_sorted[-1] - t_min) + 1
    tau = (t0_sorted - t_min + shift_ms) % duration_ms + t_min

    idx = np.searchsorted(t0_sorted, tau, side="right") - 1
    idx = np.clip(idx, 0, t0_sorted.shape[0] - 1)
    shifted_sorted = values_sorted[idx]

    out = np.empty_like(shifted_sorted)
    out[order] = shifted_sorted
    return out


def effective_block_count(t0_ms: IntArray, block_width_ms: int) -> float:
    """`n_blocos efetivos = duração da série / largura de grupo do CPCV`
    — diagnóstico reportado (não usado para quantizar o sorteio, ver
    docstring do módulo), citado pelo §2.6 como a escala que governa a
    variância amostral do nulo real (não o número de linhas)."""
    if block_width_ms <= 0:
        raise MetaFpInventoryError(
            f"effective_block_count: block_width_ms precisa ser > 0, recebido {block_width_ms}"
        )
    duration_ms = int(t0_ms.max() - t0_ms.min()) + 1
    return duration_ms / block_width_ms


# ============================================================================
# Avaliação por path (§2.6, critério: PASS sse AUC observada > p95 do
# nulo permutado, em >= alpha_layer1_permanence_min_paths de 5 paths)
# ============================================================================


@dataclass(frozen=True, slots=True)
class PathNullResult:
    path_id: int
    n_rows: int
    n_states_observed: int
    n_effective_blocks: float
    auc_observed: float
    null_aucs: FloatArray
    p95_null: float
    n_seeds: int
    passed: bool


def evaluate_path_null(
    t0_ms: IntArray,
    state_ids: IntArray,
    y: FloatArray,
    weight: FloatArray,
    *,
    n_states: int,
    block_width_ms: int,
    n_seeds: int,
    rng: np.random.Generator,
    path_id: int = -1,
) -> PathNullResult:
    """Roda o procedimento completo de um path: AUC observada (`state_ids`
    reais) + `n_seeds` deslocamentos circulares independentes de
    `state_ids` (nulo, `y`/`weight` FIXOS) + p95 do nulo + PASS/FAIL.
    `PASS` sse `auc_observado > p95_nulo` (estritamente maior — critério
    do §2.6, não `>=`)."""
    auc_observed = weighted_state_auc(y, state_ids, weight, n_states)

    null_aucs = np.empty(n_seeds, dtype=np.float64)
    for i in range(n_seeds):
        shift_ms = draw_circular_shift_ms(t0_ms, rng)
        shifted_states = circular_shift_by_time(t0_ms, state_ids, shift_ms=shift_ms)
        null_aucs[i] = weighted_state_auc(y, shifted_states, weight, n_states)

    null_percentile = float(load_constant("meta_e0_null_percentile"))
    valid_null = null_aucs[~np.isnan(null_aucs)]
    p95_null = (
        float(np.quantile(valid_null, null_percentile)) if valid_null.shape[0] > 0 else float("nan")
    )
    passed = bool(
        not np.isnan(auc_observed) and not np.isnan(p95_null) and auc_observed > p95_null
    )

    rate = weighted_state_positive_rate(y, state_ids, weight, n_states)
    return PathNullResult(
        path_id=path_id,
        n_rows=int(t0_ms.shape[0]),
        n_states_observed=int(np.sum(~np.isnan(rate))),
        n_effective_blocks=effective_block_count(t0_ms, block_width_ms),
        auc_observed=auc_observed,
        null_aucs=null_aucs,
        p95_null=p95_null,
        n_seeds=n_seeds,
        passed=passed,
    )


# ============================================================================
# P0 — validação obrigatória e bloqueante do nulo (§2.6, §15.1/§15.2)
# ============================================================================


@dataclass(frozen=True, slots=True)
class NullCalibrationResult:
    n_trials: int
    n_seeds_per_trial: int
    n_pass: int
    pass_rate: float
    target: float
    confidence_level: float
    ci_low: float
    ci_high: float
    well_calibrated: bool


def validate_null_calibration(
    t0_ms: IntArray,
    proxy_state_ids: IntArray,
    y: FloatArray,
    weight: FloatArray,
    *,
    n_states: int,
    block_width_ms: int,
    n_trials: int,
    n_seeds_per_trial: int,
    rng: np.random.Generator,
    target: float | None = None,
    confidence_level: float | None = None,
) -> NullCalibrationResult:
    """VALIDAÇÃO OBRIGATÓRIA DO NULO — §2.6, P0, bloqueante: "se o nulo
    não rejeita ruído estruturado, E0 não roda."

    `proxy_state_ids` precisa ser uma feature SABIDAMENTE SEM SINAL real
    sobre `y`, mas com a MESMA estrutura de blocos de calendário (ex.
    `regime` de outro símbolo, alinhado por posição a este `t0_ms`/`y`) —
    a responsabilidade de garantir isso é do CALLER, não deste função.

    Roda o procedimento inteiro (`evaluate_path_null`) `n_trials` vezes.
    Cada trial usa um deslocamento circular FIXO e independente de
    `proxy_state_ids` como "observado" — família de amostragem DIFERENTE
    dos `n_seeds_per_trial` deslocamentos do nulo interno de cada trial
    (ver docstring do módulo, "por que a validação não é tautológica").

    `well_calibrated` é `True` sse `target` (5% nominal) cai dentro do
    intervalo de confiança binomial (`confidence_level`, Wilson via
    `scipy.stats.binomtest`) da taxa de PASS empírica — a
    operacionalização de "materialmente acima" do texto do design doc.

    `target`/`confidence_level` `None` (default) resolvem de
    `constants.yaml` (`meta_e0_null_calibration_target`,
    `meta_e0_null_calibration_confidence_level`) — passar explícito é só
    para teste/override, nunca a via de produção."""
    if n_trials <= 0:
        raise MetaFpInventoryError(
            f"validate_null_calibration: n_trials precisa ser > 0, recebido {n_trials}"
        )
    target = (
        target if target is not None else float(load_constant("meta_e0_null_calibration_target"))
    )
    confidence_level = (
        confidence_level
        if confidence_level is not None
        else float(load_constant("meta_e0_null_calibration_confidence_level"))
    )
    n_pass = 0
    for _ in range(n_trials):
        observed_shift_ms = draw_circular_shift_ms(t0_ms, rng)
        observed_proxy = circular_shift_by_time(t0_ms, proxy_state_ids, shift_ms=observed_shift_ms)
        result = evaluate_path_null(
            t0_ms,
            observed_proxy,
            y,
            weight,
            n_states=n_states,
            block_width_ms=block_width_ms,
            n_seeds=n_seeds_per_trial,
            rng=rng,
        )
        if result.passed:
            n_pass += 1

    pass_rate = n_pass / n_trials
    ci = stats.binomtest(n_pass, n_trials).proportion_ci(confidence_level=confidence_level)
    well_calibrated = bool(ci.low <= target <= ci.high)
    return NullCalibrationResult(
        n_trials=n_trials,
        n_seeds_per_trial=n_seeds_per_trial,
        n_pass=n_pass,
        pass_rate=pass_rate,
        target=target,
        confidence_level=confidence_level,
        ci_low=float(ci.low),
        ci_high=float(ci.high),
        well_calibrated=well_calibrated,
    )


# ============================================================================
# Unicidade (§2.6, `n_eff_subpop = Σ uniqueness`, B24) — grão (symbol, side)
# ============================================================================


def uniqueness_per_side(t0: pl.Series, t1: pl.Series, side: pl.Series) -> FloatArray:
    """`uniqueness` recalculada por lado (`side` ±1), mesma razão
    estrutural de `meta_dataset._uniqueness_subpop`: concorrência
    global misturando os dois lados contaria um long como concorrente de
    um short na mesma barra, subestimando `uniqueness` por ~2×. Devolve
    alinhado posicionalmente à ORDEM DE ENTRADA (não à ordem interna por
    `t0` usada no cálculo)."""
    frame = pl.DataFrame({"t0": t0, "t1": t1, "side": side}).with_row_index("_pos")
    partes: list[pl.DataFrame] = []
    for _side_val, grupo in frame.group_by("side", maintain_order=True):
        ordenado = grupo.sort("t0")
        t0_ms = ordenado["t0"].dt.epoch(time_unit="ms").to_numpy().astype(np.int64)
        t1_ms = ordenado["t1"].dt.epoch(time_unit="ms").to_numpy().astype(np.int64)
        _concurrency, unicidade = compute_concurrency_and_uniqueness(t0_ms, t1_ms)
        partes.append(ordenado.with_columns(uniqueness=pl.Series(unicidade)))
    out = pl.concat(partes, how="vertical").sort("_pos")
    return out["uniqueness"].to_numpy().astype(np.float64)
