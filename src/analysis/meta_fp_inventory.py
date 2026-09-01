"""Gate E0 (D-14) — esquema de permutação travado (P0, bloqueante) —
`docs/meta_model_design_doc_2026-08-22.md` §2.6, §15.1/§15.2.

**Módulo `analysis/`, medição pós-hoc, zero treino** — mesmo precedente de
`gate_efficiency.py`/`m4_critical_windows.py` (fora do `importlinter` de
propósito). `analysis` pode ler `models`/`labels`/`validation` livremente
(contrato real de `pyproject.toml`: só `exchange/data/features/regime/
risk/execution/live/monitoring` são proibidos de ler `labels`; `models não
importa analysis` é a única direção fechada — o inverso é livre).

**Escopo**: `§15.2`:

```
P0  Esquema de permutação travado + VALIDAÇÃO DO NULO (§2.6)  [bloqueante, FECHADO]
P1  edges_ms sobre união temporal (D-16, AG-151)              [bloqueante, FECHADO]
P2  Diagnóstico de saturação isotônica                         [tools/diagnostics/, separado]
P3  E0-piloto (FP inventory + Gate E0 real)                    [FECHADO -- ver abaixo]
```

Este módulo entrega: a PRIMITIVA de permutação + a estatística agregada
(AUC ponderada por `uniqueness`) + a validação obrigatória do nulo (P0);
e a inventariação completa de FP/TP sobre `predictions.parquet` REAL —
`join_predictions_to_universe`, `compute_fp_inventory`, `cramers_v`,
`state_characteristic_stability` (P3). **P3 rodou 2026-08-31 contra os 5
combos de produção reais (não mais "piloto"/legado 15m — decisão do
Manager, R2/R3, `predictions.parquet` real via `run_layer1_sprint`) — ver
`PLANO_MESTRE_PRINCE2.md §15.37` pro resultado e a decisão do Gate E0
propriamente dita (fora deste módulo, é decisão do Manager, não
código).**

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
    `0.0` — taxa indefinida é diferente de taxa zero.

    Precondição validada (achado real, 2026-08-31): `state_ids` fora de
    `[0, n_states)` — ex. sentinela de `NaN`/nulo convertido pra
    `int64` por um mapeamento upstream descuidado (`regime` pode ter
    linhas nulas de verdade, `models.dataset.build_modeling_frame`
    mede e loga `n_missing_regime` > 0 às vezes) — indexava
    `state_rate[state_ids]` fora dos limites em `score_from_state` com
    `IndexError` sem contexto nenhum. Falha aqui, alto e cedo, com
    mensagem acionável: quem constrói `state_ids` precisa FILTRAR
    linhas de regime nulo antes de chamar, não é responsabilidade
    deste módulo adivinhar o que fazer com elas."""
    if state_ids.shape[0] > 0 and not bool(
        np.all((state_ids >= 0) & (state_ids < n_states))
    ):
        bad = state_ids[(state_ids < 0) | (state_ids >= n_states)]
        raise MetaFpInventoryError(
            f"weighted_state_positive_rate: state_ids fora de [0, {n_states}) -- "
            f"{bad.shape[0]} linha(s), exemplo {bad[0]!r}. Provável causa: regime nulo "
            "mapeado sem filtro upstream (ver n_missing_regime no log de "
            "build_modeling_frame) -- filtre antes de chamar, não corrija aqui."
        )
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


# ============================================================================
# P3 — E0-piloto: universo real (§2.6, join (t0, side_hat) -> (t0, side))
# ============================================================================


def join_predictions_to_universe(predictions: pl.DataFrame, dense: pl.DataFrame) -> pl.DataFrame:
    """Universo do Gate E0 (§2.6): `side_hat != 0 ∧ is_oof`, joinado a
    `labels` por `(t0, side_hat) → (t0, side)` — texto literal: "`symbol`
    NÃO é coluna de `labels` — é chave de caminho (`cpcv.py:760-780`);
    entra como parâmetro do pipeline, não como chave de join." `dense` é
    o `ModelingFrame.data` (`src.models.dataset.build_modeling_frame`) do
    MESMO `(symbol, resolution_id)` das `predictions` — carrega
    `barrier_hit`/`ret_net`/`t1`/`atr_at_t0`/`regime` já causal e
    corretamente unidos, sem reimplementar esse join aqui.

    Uma linha de `predictions` pode aparecer em até 5 `fold_id` (`t0`
    revisitado por múltiplos splits do CPCV) — o join é 1:1 em `dense`
    (`t0` único por lado), então a saída tem uma linha por (`t0`,
    `side_hat`, `fold_id`) de `predictions`, cada uma carregando os
    mesmos campos de `dense` (correto: cada `fold_id` é uma AVALIAÇÃO
    independente do mesmo evento real)."""
    sinalizado = predictions.filter((pl.col("side_hat") != 0) & pl.col("is_oof"))
    return sinalizado.join(
        dense, left_on=["t0", "side_hat"], right_on=["t0", "side"], how="inner"
    )


def path_id_by_fold(splits: object) -> dict[int, int]:
    """`{fold_id: path_id}` a partir de `CPCVResult.splits` — `fold_id`
    em `predictions.parquet` é `split.split_id` (`src.models.alpha`,
    `"fold_id": pl.Series([split.split_id] * n_rows)`), e `path_id` vem
    de `split.path_id` (1-fatoração de `src.validation.cpcv`)."""
    return {s.split_id: s.path_id for s in splits}  # type: ignore[attr-defined]


# ============================================================================
# P3 — Inventário de FP/TP (§2.6, "Métricas por path")
# ============================================================================


@dataclass(frozen=True, slots=True)
class FpInventory:
    n_tp: int
    n_fp: int
    n_nofill: int
    fp_rate: float
    pnl_fp_total: float
    n_eff_subpop: float


def compute_fp_inventory(table: pl.DataFrame, weight: FloatArray) -> FpInventory:
    """§2.6, "Métricas por path": `n_fp`, `n_tp`, `n_nofill`, `fp_rate =
    n_fp/(n_fp+n_tp)`, `pnl_fp_total = Σ ret_net | FP` (teto teórico de
    um filtro perfeito é `-pnl_fp_total`), `n_eff_subpop = Σ uniqueness`
    (B24). `table` precisa ter `barrier_hit`/`ret_net`; `weight`
    alinhado posicionalmente a `table` (tipicamente `uniqueness_per_
    side`). `fp_rate` é `NaN` (não `0.0`) quando `n_fp+n_tp == 0`."""
    barrier_hit = table["barrier_hit"].cast(pl.Utf8)
    ret_net = table["ret_net"].to_numpy().astype(np.float64)

    is_nofill = (barrier_hit == "NOFILL").to_numpy()
    is_sl = (barrier_hit == "SL").to_numpy()
    is_tp = (barrier_hit == "TP").to_numpy()
    is_time = (barrier_hit == "TIME").to_numpy()
    is_time_loss = is_time & (ret_net <= 0.0)
    is_time_win = is_time & (ret_net > 0.0)

    fp_mask = is_sl | is_time_loss
    tp_mask = is_tp | is_time_win

    n_fp = int(fp_mask.sum())
    n_tp = int(tp_mask.sum())
    n_nofill = int(is_nofill.sum())
    denom = n_fp + n_tp
    fp_rate = (n_fp / denom) if denom > 0 else float("nan")  # noqa: unguarded-ratio — guarda inline no ternário (denom>0), heurística não reconhece ternário na mesma linha
    pnl_fp_total = float(ret_net[fp_mask].sum())
    n_eff_subpop = float(weight[~is_nofill].sum())

    return FpInventory(
        n_tp=n_tp,
        n_fp=n_fp,
        n_nofill=n_nofill,
        fp_rate=fp_rate,
        pnl_fp_total=pnl_fp_total,
        n_eff_subpop=n_eff_subpop,
    )


# ============================================================================
# P3 — Diagnósticos (§2.6, "custo zero, mudam decisões a jusante")
# ============================================================================


def cramers_v(state_ids: IntArray, group_id: IntArray) -> float:
    """V de Cramér entre `regime` e `group_id` do CPCV (§2.4) — mede se
    `regime` é, na prática, um carimbo de data disfarçado (associação
    forte com o grupo cronológico) em vez de um estado econômico real.
    `NaN` se a tabela de contingência degenerar (< 2 categorias
    OBSERVADAS em algum eixo).

    A tabela é construída só sobre valores de `state_ids`/`group_id`
    REALMENTE observados (`np.unique`, reindexado compacto) — não sobre
    `[0, max]` inteiro. Achado real (2026-08-31, subpopulação pequena de
    `side_hat != 0`, ~2-3 mil linhas): um estado de regime intermediário
    pode ter ZERO ocorrências nessa subpopulação mesmo com outro estado
    de índice maior presente — `[0, max]` cru produzia uma linha inteira
    de zeros no meio da tabela, e `scipy.stats.contingency.association`
    levanta `ValueError` (frequência esperada zero) nesse caso, não
    devolve `NaN` sozinho — o guard precisa evitar CONSTRUIR essa linha,
    não só contar categorias depois."""
    from scipy.stats.contingency import association

    if state_ids.shape[0] == 0:
        return float("nan")
    _states_unicos, state_idx = np.unique(state_ids, return_inverse=True)
    _groups_unicos, group_idx = np.unique(group_id, return_inverse=True)
    n_states_obs = _states_unicos.shape[0]
    n_groups_obs = _groups_unicos.shape[0]
    if n_states_obs < 2 or n_groups_obs < 2:
        return float("nan")
    table = np.zeros((n_states_obs, n_groups_obs), dtype=np.int64)
    for s, g in zip(state_idx.tolist(), group_idx.tolist(), strict=True):
        table[s, g] += 1
    return float(association(table, method="cramer"))


def state_characteristic_stability(
    state_ids: IntArray, group_id: IntArray, characteristic: FloatArray, *, n_states: int
) -> pl.DataFrame:
    """Estabilidade do mapeamento estado↔característica ENTRE grupos
    cronológicos do CPCV (§6.2) — operacionalização: para cada estado,
    a média de `characteristic` (ex. `atr_at_t0`) DENTRO de cada grupo, e
    o coeficiente de variação (`std/mean`) dessas médias ENTRE grupos.
    CV baixo = a característica do estado é estável ao longo do tempo
    (o estado "significa a mesma coisa" em qualquer grupo); CV alto =
    o mapeamento estado→característica deriva entre janelas -- sinal de
    que `regime` pode não ser um candidato estável o bastante pro Meta
    consumir como feature. Estado observado em < 2 grupos -> `NaN`
    (instabilidade indefinida, não `0.0`)."""
    frame = pl.DataFrame(
        {"state": state_ids, "group": group_id, "characteristic": characteristic}
    )
    por_grupo = (
        frame.group_by(["state", "group"], maintain_order=True)
        .agg(pl.col("characteristic").mean().alias("mean_characteristic"))
    )
    linhas: list[dict[str, object]] = []
    for state in range(n_states):
        sub = por_grupo.filter(pl.col("state") == state)
        means = sub["mean_characteristic"].to_numpy().astype(np.float64)
        n_groups_observed = int(means.shape[0])
        if n_groups_observed < 2:
            cv = float("nan")
        else:
            mean_of_means = float(np.mean(means))
            cv = (
                float(np.std(means, ddof=1) / mean_of_means)  # noqa: unguarded-ratio — guarda inline no ternário (!=0.0), heurística não reconhece ternário na mesma linha
                if mean_of_means != 0.0
                else float("nan")
            )
        linhas.append(
            {"state": state, "n_groups_observed": n_groups_observed, "coefficient_of_variation": cv}
        )
    return pl.DataFrame(linhas)


# ============================================================================
# P3 — Gate E0 real (§2.6, critério: PASS sse AUC observada > p95 do nulo
# em >= alpha_layer1_permanence_min_paths de 5 paths)
# ============================================================================


@dataclass(frozen=True, slots=True)
class GateE0Result:
    symbol: str
    resolution_id: str
    path_results: tuple[PathNullResult, ...]
    n_paths_passed: int
    n_paths_total: int
    min_paths_required: int
    gate_passed: bool


def evaluate_gate_e0(
    table: pl.DataFrame,
    *,
    symbol: str,
    resolution_id: str,
    n_states: int,
    block_width_ms: int,
    rng: np.random.Generator,
    n_seeds: int | None = None,
    min_paths_required: int | None = None,
) -> GateE0Result:
    """Decisão real do Gate E0 (§2.6) sobre `table` — precisa já ter
    `y_fp` (via `classify_fp_binary`), `state_ids` (coluna `_state_id`,
    int, mapeado de `regime`), `path_id`, `t0`, e `weight` (coluna
    `_weight`). Roda `evaluate_path_null` por `path_id`, agrega pelo
    critério travado. `n_seeds`/`min_paths_required` `None` (default)
    resolvem de `constants.yaml` (`alpha_b1_n_seeds`, `alpha_layer1_
    permanence_min_paths`) -- os MESMOS orçamentos que o resto do Alpha
    já usa pra permutação/permanência, não números novos."""
    n_seeds = n_seeds if n_seeds is not None else int(load_constant("alpha_b1_n_seeds"))
    min_paths_required = (
        min_paths_required
        if min_paths_required is not None
        else int(load_constant("alpha_layer1_permanence_min_paths"))
    )

    path_results: list[PathNullResult] = []
    for path_id in sorted(table["path_id"].unique().to_list()):
        sub = table.filter(pl.col("path_id") == path_id).filter(pl.col("y_fp").is_not_null())
        t0_ms = sub["t0"].dt.epoch(time_unit="ms").to_numpy().astype(np.int64)
        y = sub["y_fp"].to_numpy().astype(np.float64)
        state_ids = sub["_state_id"].to_numpy().astype(np.int64)
        weight = sub["_weight"].to_numpy().astype(np.float64)
        result = evaluate_path_null(
            t0_ms,
            state_ids,
            y,
            weight,
            n_states=n_states,
            block_width_ms=block_width_ms,
            n_seeds=n_seeds,
            rng=rng,
            path_id=int(path_id),
        )
        path_results.append(result)

    n_paths_passed = sum(1 for r in path_results if r.passed)
    return GateE0Result(
        symbol=symbol,
        resolution_id=resolution_id,
        path_results=tuple(path_results),
        n_paths_passed=n_paths_passed,
        n_paths_total=len(path_results),
        min_paths_required=min_paths_required,
        gate_passed=bool(n_paths_passed >= min_paths_required),
    )
