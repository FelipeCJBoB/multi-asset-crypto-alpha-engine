"""Primitivos de métrica de utilidade de regime — M4 (`PRD_V4_1.md` §3.2).
Núcleo puro (sem IO), análogo a `volatility_walkforward.py` (M1) mas para
as 4 métricas do M4: separação de retorno condicional (ANOVA F/ω²),
persistência (duração mediana, taxa de troca), estabilidade entre folds
(Rand ajustado) e ortogonalidade contra volatilidade — esta última reusa
`anova_by_group` com a resposta trocada (`vol_pctile` em vez de retorno
futuro), não é uma métrica própria.

**NaN em `response`**: filtrado antes do cálculo (não escondido — contado
e reportado em `ANOVAResult.n`, que é o `n` PÓS-filtro). A última barra de
uma série sempre tem `log_return_1=NaN` (não existe `close[t+1]`) — é
esperado, não um erro de dado."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy import stats
from sklearn.metrics import adjusted_rand_score

IntArray = NDArray[np.int64]
FloatArray = NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class ANOVAResult:
    """`omega_squared` clipado em `[0, 1]` — a fórmula clássica (Fritz,
    Morris & Richler 2012) pode dar levemente negativo quando o efeito
    real é ~0 e o ruído amostral domina; convenção padrão da literatura é
    reportar 0 nesse caso, não um valor sem sentido físico."""

    f_stat: float
    omega_squared: float
    p_value: float
    k_groups: int
    n: int


def anova_by_group(group_labels: IntArray, response: FloatArray) -> ANOVAResult:
    """ANOVA de 1 fator: `response` explicada por `group_labels` (grupo =
    regime/estado canônico). `F`/`p_value` via `scipy.stats.f_oneway`
    (referência, não reimplementada); `omega_squared` calculado à mão a
    partir de SSB/SSW porque `scipy` não expõe isso diretamente.

    Usada tanto para "separação de retorno condicional" (resposta = log-
    retorno futuro, ω² ALTO é o sinal BOM) quanto para "ortogonalidade
    contra volatilidade" (resposta = `vol_pctile` do baseline, ω² ALTO é
    o sinal RUIM — candidato só reencontrou C07). A função não sabe qual
    interpretação se aplica — é responsabilidade do chamador.

    Levanta `ValueError` se sobrarem menos de 2 grupos ou `n <= k_groups`
    após filtrar NaN de `response` (graus de liberdade dentro do grupo
    ficariam <= 0 — resultado sem sentido, não um NaN silencioso)."""
    if group_labels.shape != response.shape:
        raise ValueError(
            "anova_by_group: group_labels/response precisam do mesmo shape "
            f"(group_labels={group_labels.shape}, response={response.shape})"
        )
    finite_mask = np.isfinite(response)
    group_labels = group_labels[finite_mask]
    response = response[finite_mask]

    unique_groups = np.unique(group_labels)
    k = int(unique_groups.size)
    n = int(group_labels.shape[0])
    if k < 2:
        raise ValueError(f"anova_by_group: precisa de >=2 grupos com dado finito, achou {k}")
    if n <= k:
        raise ValueError(f"anova_by_group: n={n} <= k_groups={k}, graus de liberdade insuficientes")

    groups = [response[group_labels == g] for g in unique_groups]
    f_stat, p_value = stats.f_oneway(*groups)

    grand_mean = float(np.mean(response))
    ssb = float(sum(g.size * (float(np.mean(g)) - grand_mean) ** 2 for g in groups))
    ssw = float(sum(float(np.sum((g - np.mean(g)) ** 2)) for g in groups))
    df_between = k - 1
    df_within = n - k
    msw = ssw / df_within  # noqa: unguarded-ratio -- df_within=n-k>0 checado acima (n<=k levanta ValueError)
    denom = ssb + ssw + msw
    omega_squared = (ssb - df_between * msw) / denom if denom != 0 else 0.0  # noqa: unguarded-ratio -- guarda inline no ternário
    omega_squared = float(np.clip(omega_squared, 0.0, 1.0))

    return ANOVAResult(
        f_stat=float(f_stat),
        omega_squared=omega_squared,
        p_value=float(p_value),
        k_groups=k,
        n=n,
    )


@dataclass(frozen=True, slots=True)
class PersistenceMetrics:
    median_duration_bars: float
    switch_rate: float
    n_segments: int


def regime_persistence(group_labels: IntArray) -> PersistenceMetrics:
    """Run-length do array `group_labels` — segmento = sequência máxima de
    barras consecutivas com o mesmo rótulo. `switch_rate` = fração de
    barras (excluindo a primeira) em que o rótulo muda em relação à barra
    anterior — `1/median_duration_bars` na aproximação de segmentos
    geométricos, mas calculado direto do dado real, não derivado da
    mediana (série real não é geométrica)."""
    n = group_labels.shape[0]
    if n == 0:
        raise ValueError("regime_persistence: group_labels vazio")

    change_mask = group_labels[1:] != group_labels[:-1]
    switch_rate = float(np.mean(change_mask)) if n > 1 else 0.0

    boundaries = np.flatnonzero(change_mask) + 1
    segment_starts = np.concatenate(([0], boundaries))
    segment_ends = np.concatenate((boundaries, [n]))
    durations = (segment_ends - segment_starts).astype(np.float64)

    return PersistenceMetrics(
        median_duration_bars=float(np.median(durations)),
        switch_rate=switch_rate,
        n_segments=int(durations.shape[0]),
    )


def adjusted_rand(labels_a: IntArray, labels_b: IntArray) -> float:
    """Wrapper fino sobre `sklearn.metrics.adjusted_rand_score` — guarda
    comprimento desalinhado com `ValueError` explícito em vez de deixar o
    sklearn levantar uma exceção de mensagem genérica. `1.0` = partições
    idênticas; `~0.0` = tão parecido quanto atribuição aleatória; negativo
    é possível (pior que aleatório), preservado sem clip (é informação
    real, não ruído numérico a esconder)."""
    if labels_a.shape != labels_b.shape:
        raise ValueError(
            "adjusted_rand: labels_a/labels_b precisam do mesmo shape "
            f"(labels_a={labels_a.shape}, labels_b={labels_b.shape})"
        )
    return float(adjusted_rand_score(labels_a, labels_b))


__all__ = [
    "ANOVAResult",
    "PersistenceMetrics",
    "adjusted_rand",
    "anova_by_group",
    "regime_persistence",
]
