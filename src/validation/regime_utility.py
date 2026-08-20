"""Primitivos de métrica de utilidade de regime — M4 (`PRD_V4_1.md` §3.2).
Núcleo puro (sem IO), análogo a `volatility_walkforward.py` (M1) mas para
as 4 métricas do M4: separação de retorno condicional (ANOVA F de
Welch/ω²), persistência (duração mediana, taxa de troca), estabilidade
entre folds (Rand ajustado) e ortogonalidade contra volatilidade — esta
última reusa `anova_by_group` com a resposta trocada (`vol_pctile` em vez
de retorno futuro), não é uma métrica própria.

**ANOVA F de Welch, não a F clássica — decisão do Manager, 2026-08-18
(auditoria `audit_engineering`).** `anova_by_group` usava
`scipy.stats.f_oneway` (ANOVA F clássica), que assume homocedasticidade
(variância igual entre grupos). Essa suposição é violada POR CONSTRUÇÃO
no M4: regimes de volatilidade diferem em variância por definição, e a
métrica de "ortogonalidade contra volatilidade" testa exatamente se a
variância difere entre grupos de regime — usar um teste que assume
variância igual pra medir se a variância é diferente é uma contradição
interna do desenho. Trocado para Welch's ANOVA F (Welch 1951, "On the
comparison of several mean values: an alternative approach", Biometrika
38(3/4)), robusta a variância desigual entre grupos e com poder
equivalente à F clássica quando a homocedasticidade de fato vale — ver
docstring de `anova_by_group` pra implementação/fonte exata."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from sklearn.metrics import adjusted_rand_score
from statsmodels.stats.oneway import anova_oneway

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
    """ANOVA de 1 fator, variante de Welch: `response` explicada por
    `group_labels` (grupo = regime/estado canônico). `F`/`p_value` via
    `statsmodels.stats.oneway.anova_oneway(groups, use_var="unequal",
    welch_correction=True)` — implementação madura/testada da fórmula de
    Welch 1951 (peso `w_i = n_i/s_i²` por grupo, graus de liberdade do
    denominador fracionários pela aproximação de Satterthwaite), preferida
    a reimplementar a fórmula à mão (decisão do Manager, 2026-08-18: risco
    de bug de implementação própria > risco de uma lib madura já testada,
    ver docstring do módulo pro motivo da troca). Assinatura/uso
    confirmados lendo `statsmodels/stats/oneway.py` instalado (`anova_
    generic`/`anova_oneway`, `.venv`), não só a doc.

    **`omega_squared` — fórmula ajustada "AnL" (Albers & Lakens 2018),
    não mais SSB/SSW.** ω² tradicionalmente vem de somas de quadrados
    (SSB/SSW/SST) da ANOVA clássica — mas existe uma variante específica
    pra F de Welch na literatura: Albers, C., & Lakens, D. (2018), "When
    power analyses based on pilot data are biased", J. Experimental Social
    Psychology 74, popularizada/confirmada em Kroes & Finley (2023),
    "Demystifying omega squared", Psychological Methods — 3 métodos
    existem (Kirk, Carroll-Nordholm, Albers-Lakens/"AnL"), e a literatura
    recomenda AnL por ser o único que incorpora os graus de liberdade
    CORRIGIDOS (Satterthwaite) de Welch, não só as médias ponderadas.
    Fórmula (confirmada contra o pacote R `WAnova`, `R/wAnova.R`,
    `welch_anova.test`, licença BSD-3, código fonte lido antes de portar):

        ω²_AnL = (F − 1) / ((df_within + 1) / df_between + F)

    onde `df_between`/`df_within` são os graus de liberdade DE WELCH (o
    segundo, fracionário). **Prova de consistência (medida nesta sessão,
    não presumida):** aplicar essa MESMA fórmula com o F/df CLÁSSICOS
    (não os de Welch) reproduz exatamente `(ssb - df_between*msw)/(ssb+
    ssw+msw)` — a fórmula antiga baseada em SSB/SSW — até erro de ponto
    flutuante; ω²_AnL não é uma fórmula nova e sim a MESMA relação
    F→ω² clássica (Fritz, Morris & Richler 2012), agora alimentada com o
    F/df de Welch em vez do F/df clássico. Clipado em `[0, 1]` pelo mesmo
    motivo já documentado em `ANOVAResult` (pode dar levemente negativo
    quando o efeito real é ~0).

    Usada tanto para "separação de retorno condicional" (resposta = log-
    retorno futuro, ω² ALTO é o sinal BOM) quanto para "ortogonalidade
    contra volatilidade" (resposta = `vol_pctile` do baseline, ω² ALTO é
    o sinal RUIM — candidato só reencontrou C07). A função não sabe qual
    interpretação se aplica — é responsabilidade do chamador.

    Levanta `ValueError` se sobrarem menos de 2 grupos ou `n <= k_groups`
    após filtrar NaN de `response` (graus de liberdade dentro do grupo
    ficariam <= 0 — resultado sem sentido, não um NaN silencioso), OU se
    algum grupo sobrar com < 2 observações, OU se algum grupo tiver
    variância amostral exatamente 0 — os 2 achados reais desta sessão
    (medidos rodando a suíte de teste existente, não hipotéticos):

    1. **`n_i < 2` por grupo.** Diferente da F clássica (que só precisa da
       variância PARTILHADA/pooled, `n_total - k` graus de liberdade),
       Welch's F precisa da variância de CADA grupo individualmente
       (`ddof=1`, exige `n_i>=2`); com `n_i=1`, `statsmodels` não levanta
       erro, devolve `NaN` silencioso com `RuntimeWarning` interno
       (confirmado rodando `anova_oneway` com um grupo de tamanho 1).
    2. **Variância de grupo == 0 (todas as observações idênticas).**
       Welch pondera cada grupo por `w_i = n_i/var_i` — `var_i=0` é
       divisão por zero literal. Achado real: o teste pré-existente
       `test_anova_filtra_nan_da_response_antes_de_calcular` (dado
       `[1.0, 1.0]`/`[5.0, 5.0]` pós-filtro de NaN) SEMPRE foi um caso de
       variância 0 nos 2 grupos, inofensivo pra F clássica (SSW pooled
       ainda finito, contribuição de um grupo com variância 0 é só 0 na
       soma) mas silenciosamente produzia `f_stat=nan`/`omega_squared=nan`
       sob Welch (confirmado rodando a suíte após a troca, 2
       `RuntimeWarning: divide by zero`/`invalid value` do `statsmodels`)
       — o teste original só afirmava `result.n == 4`, nunca reparava.
       Corrigido no teste (dado com variância > 0 nos 2 grupos) E guardado
       aqui explicitamente — este projeto não silencia `RuntimeWarning`
       sem achar a causa raiz (CLAUDE.md), e `NaN` sem `ValueError` aqui
       seria exatamente isso: a causa raiz achada, mas não corrigida."""
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
    group_sizes = [g.size for g in groups]
    undersized = {
        int(g_id): size
        for g_id, size in zip(unique_groups.tolist(), group_sizes, strict=True)
        if size < 2
    }
    if undersized:
        raise ValueError(
            "anova_by_group: Welch's F precisa de >=2 observações por grupo (variância "
            f"amostral por grupo, ddof=1) -- grupo(s) com < 2: {undersized}"
        )
    zero_variance = {
        int(g_id): float(np.var(g, ddof=1))
        for g_id, g in zip(unique_groups.tolist(), groups, strict=True)
        if np.var(g, ddof=1) == 0.0
    }
    if zero_variance:
        raise ValueError(
            "anova_by_group: Welch's F pondera cada grupo por n_i/var_i -- var_i=0 "
            "(todas as observações do grupo idênticas) é divisão por zero, não um "
            f"resultado degenerado silencioso -- grupo(s) com variância 0: {list(zero_variance)}"
        )

    welch_result = anova_oneway(groups, use_var="unequal", welch_correction=True)
    f_stat = float(welch_result.statistic)
    p_value = float(welch_result.pvalue)
    df_between = float(welch_result.df_num)  # k - 1
    df_within = float(welch_result.df_denom)  # Satterthwaite-Welch, fracionário

    # ω²_AnL -- ver docstring acima pra fórmula/fonte/prova de equivalência
    # com SSB/SSW no caso clássico. `df_between=k-1>=1` sempre (k<2 já
    # levantou ValueError acima); `df_within` (Satterthwaite) é sempre
    # finito e positivo dado >=2 obs/grupo (checado acima).
    omega_denom = (df_within + 1.0) / df_between + f_stat  # noqa: unguarded-ratio -- df_between=k-1>=1, k<2 levanta ValueError acima
    omega_squared = (f_stat - 1.0) / omega_denom if omega_denom != 0 else 0.0  # noqa: unguarded-ratio -- guarda inline no ternário
    omega_squared = float(np.clip(omega_squared, 0.0, 1.0))

    return ANOVAResult(
        f_stat=f_stat,
        omega_squared=omega_squared,
        p_value=p_value,
        k_groups=k,
        n=n,
    )


@dataclass(frozen=True, slots=True)
class PersistenceMetrics:
    median_duration_bars: float
    switch_rate: float
    n_segments: int


def segment_boundaries(group_labels: IntArray) -> tuple[IntArray, IntArray]:
    """Fronteira de segmento (run-length) de `group_labels` — segmento =
    sequência máxima de posições consecutivas com o mesmo rótulo, na
    ordem em que o array já vem (nunca reordenado aqui). Extraído de
    `regime_persistence` (2026-08-19, AG-092) pra ser reusado por
    qualquer consumidor que precise dos ÍNDICES de fronteira, não só das
    métricas agregadas -- ex. permutação em bloco por episódio
    (`m6_common_factor_hypothesis.permutation_heterogeneity_test`), que
    precisa saber onde cada episódio começa/termina pra nunca quebrar um
    no meio ao permutar. Devolve `(segment_starts, segment_ends)`, índices
    posicionais tais que `group_labels[start:end]` é um segmento inteiro
    (mesmo contrato de fatiamento que `regime_persistence` já usava
    internamente, agora exposto)."""
    n = group_labels.shape[0]
    if n == 0:
        raise ValueError("segment_boundaries: group_labels vazio")
    change_mask = group_labels[1:] != group_labels[:-1]
    boundaries = np.flatnonzero(change_mask) + 1
    segment_starts = np.concatenate(([0], boundaries))
    segment_ends = np.concatenate((boundaries, [n]))
    return segment_starts, segment_ends


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

    segment_starts, segment_ends = segment_boundaries(group_labels)
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
    "segment_boundaries",
]
