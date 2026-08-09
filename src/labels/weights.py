"""Pesos por unicidade (§3.5, AFML cap. 4) — concorrência pontual, unicidade
média por label, `sample_weight` normalizado para média 1.

**B24 — proibido estipular `N_eff` por fórmula fechada** (tamanho da
amostra dividido pelo horizonte, ou `1+s(2h-1)`). Este módulo MEDE a
concorrência ponto a ponto (varredura tipo AFML `numCoEvents`/
`avgUniqueness`) e soma `uniqueness` real — `N_eff = Σ uniqueness` é lido
do resultado, nunca calculado por atalho fechado.

**Concorrência/unicidade calculadas POR LADO** (`side=+1`/`side=-1`
separadamente), porque cada lado alimenta um modelo binário distinto
(M_long/M_short, B18) com seu próprio conjunto de treino/CPCV — overlap
entre uma aposta long e uma aposta short no mesmo `t0` não é a mesma
redundância estatística que overlap entre duas apostas do MESMO lado.
`sample_weight`, porém, é normalizado para média 1 sobre o dataset
COMBINADO (os dois lados juntos), porque a invariante §3.8
(`sample_weight.mean() ≈ 1`) é verificada sobre `labels.parquet` inteiro —
um arquivo só, não um por lado.

**Índice de concorrência = a própria série de `t0`, não um grid de tempo
físico.** Cada linha do lado (`side` fixo) tem exatamente um `t0` (uma
barra de 15m produz um label por lado); a posição de um label na série
ordenada por `t0` FAZ o papel do `closeIdx` do AFML — inclui gaps reais de
dado de graça (um gap não conta como "barras vazias" na concorrência,
porque simplesmente não existe posição pra ele no índice)."""

from __future__ import annotations

import numpy as np
import polars as pl
from numpy.typing import NDArray

IntArray = NDArray[np.int64]
FloatArray = NDArray[np.float64]


def compute_concurrency_and_uniqueness(t0: IntArray, t1: IntArray) -> tuple[IntArray, FloatArray]:
    """`t0`/`t1` (epoch ms, ou qualquer unidade inteira monotonicamente
    comparável) já ORDENADOS por `t0` ascendente, um label por posição —
    exatamente a ordem em que `triple_barrier.build_labels` emite as linhas
    de um mesmo lado.

    Para cada label `i` (posição `i` no array), o intervalo `[t0_i, t1_i]`
    "ocupa" as posições `[i, idx1_i]`, onde `idx1_i` é a última posição `j`
    tal que `t0_j <= t1_i` (busca binária — `np.searchsorted`). Isso é
    literalmente "quantos OUTROS labels começam antes de `t1_i` terminar",
    a definição de concorrência do AFML cap. 4, calculada sobre o índice
    real dos dados (não um grid físico reconstruído).

    Retorna `(concurrency, uniqueness)`, ambos alinhados posicionalmente a
    `t0`/`t1` de entrada: `concurrency[i]` = quantos labels cobrem a
    posição `i` (a própria `t0` do label `i`); `uniqueness[i]` = média de
    `1/concurrency` sobre todas as posições que o label `i` ocupa."""
    n = t0.shape[0]
    if n == 0:
        return np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.float64)

    idx0 = np.arange(n)
    idx1 = np.searchsorted(t0, t1, side="right") - 1
    idx1 = np.clip(idx1, 0, n - 1)
    idx1 = np.maximum(idx1, idx0)  # t1 > t0 (invariante §3.8) garante isso, clip só por segurança

    # Array de diferenças — soma 1 no início do intervalo ocupado, subtrai 1
    # logo após o fim. `cumsum` reconstrói a concorrência por posição em
    # O(n), sem materializar uma matriz indicadora n x n.
    diff = np.zeros(n + 1, dtype=np.int64)
    np.add.at(diff, idx0, 1)
    np.add.at(diff, idx1 + 1, -1)
    concurrency = np.cumsum(diff[:n]).astype(np.int64)

    reciprocal = 1.0 / concurrency.astype(np.float64)
    prefix = np.concatenate((np.zeros(1, dtype=np.float64), np.cumsum(reciprocal)))
    span = (idx1 - idx0 + 1).astype(np.float64)
    uniqueness = (prefix[idx1 + 1] - prefix[idx0]) / span
    # `uniqueness` é matematicamente uma média de 1/concorrência, sempre em
    # (0, 1] — o `clip` só absorve ruído de ponto flutuante da soma
    # acumulada (`cumsum`/subtração de prefixos), medido até ~1e-14 acima
    # de 1.0 em dado real, nunca um erro de lógica.
    uniqueness = np.clip(uniqueness, 0.0, 1.0)

    return concurrency, uniqueness


def apply_weights(labels: pl.DataFrame) -> pl.DataFrame:
    """Adiciona `concurrency`, `uniqueness` (por lado) e `sample_weight`
    (`uniqueness * |ret_net|`, normalizado para média 1 sobre o dataset
    COMBINADO — ver docstring do módulo) a `labels` (schema pré-pesos de
    `triple_barrier._PRE_WEIGHT_SCHEMA`, colunas `side`/`t0`/`t1`/`ret_net`
    obrigatórias). Levanta `ValueError` se a média de `uniqueness *
    |ret_net|` for zero/não-finita — dataset degenerado (ex.: todo
    `ret_net` == 0), não é possível normalizar para média 1 sem dividir por
    zero, e um `sample_weight` silenciosamente `NaN`/`inf` seria pior do
    que falhar alto."""
    if labels.is_empty():
        return labels.with_columns(
            pl.Series("concurrency", [], dtype=pl.Int16),
            pl.Series("uniqueness", [], dtype=pl.Float64),
            pl.Series("sample_weight", [], dtype=pl.Float64),
        )

    parts: list[pl.DataFrame] = []
    for side_value in sorted(labels["side"].unique().to_list()):
        subset = labels.filter(pl.col("side") == side_value).sort("t0")
        t0_ms = subset["t0"].dt.epoch(time_unit="ms").to_numpy().astype(np.int64)
        t1_ms = subset["t1"].dt.epoch(time_unit="ms").to_numpy().astype(np.int64)
        concurrency, uniqueness = compute_concurrency_and_uniqueness(t0_ms, t1_ms)
        subset = subset.with_columns(
            pl.Series("concurrency", concurrency).cast(pl.Int16),
            pl.Series("uniqueness", uniqueness).cast(pl.Float64),
        )
        parts.append(subset)

    out = pl.concat(parts, how="vertical")

    raw_weight = (out["uniqueness"] * out["ret_net"].abs()).to_numpy()
    mean_w = float(np.nanmean(raw_weight)) if raw_weight.size else 0.0
    if not np.isfinite(mean_w) or mean_w <= 0.0:
        raise ValueError(
            f"apply_weights: média de uniqueness*|ret_net| = {mean_w!r} — dataset "
            "degenerado (ex.: todo ret_net == 0), não é possível normalizar "
            "sample_weight para média 1 sem dividir por zero"
        )
    sample_weight = raw_weight / mean_w
    out = out.with_columns(pl.Series("sample_weight", sample_weight, dtype=pl.Float64))

    return out.sort(["side", "t0"])
