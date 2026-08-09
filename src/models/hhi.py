"""Diagnóstico de concentração — §5.8. `HHI = Σ share²` da importância por
ganho total (`total_gain`), mais o maior share individual e a contagem de
features com share > 1%. Núcleo puro (sem IO, sem XGBoost) — recebe o
dicionário já extraído de `booster.get_score(importance_type="total_gain")`
mapeado para nomes de coluna reais, não `"f0".."fN"`.

**HHI efetivo (`compute_effective_concentration`, achado do Sprint 4/task D
do CLAUDE.md).** O HHI nominal acima trata cada feature como um grau de
liberdade de risco INDEPENDENTE — mas duas features do top-4 por gain têm
ρ=-0,913 entre si (`E27f_cost_atr_ratio` × `C07_vol_pctile_expanding`), e
outro par tem ρ=0,947 (`A13_dist_ema48_atr` × `B01_rsi_14`). Dois "slots" de
importância que carregam quase a mesma informação não são dois graus de
liberdade — o HHI nominal SUBESTIMA a concentração real nesse caso.
`compute_effective_concentration` corrige isso via "número efetivo de
fatores" (participation ratio dos autovalores da matriz de correlação
ponderada por gain) — ver a docstring da função para a derivação completa,
incluindo a prova de que ela se reduz exatamente ao HHI nominal quando as
features não são correlacionadas (o caso degenerado em que os dois números
DEVEM coincidir)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from src.core.metric import Metric, Unit

FloatArray = NDArray[np.float64]

_SHARE_PCT_THRESHOLD = 0.01  # 1% — literal do próprio §5.8 do PRD  # noqa: magic-number

# `Metric.source` default — `compute_concentration()` é pura (não sabe se
# `gain_by_column` veio do fold 3 lado long ou do fold 7 lado short; essa
# distinção é de quem chama, `src.models.alpha.fit_side_model`). Kwarg com
# default para não quebrar a chamada posicional existente
# (`compute_concentration(gain_by_column, DESIGN_COLUMNS)` em
# `src.models.alpha`) — quem tiver contexto melhor pode sobrescrever.
_DEFAULT_SOURCE = "models.hhi.compute_concentration"
_DEFAULT_SOURCE_EFFECTIVE = "models.hhi.compute_effective_concentration"
_N_SEMANTICS_FEATURES = "features"


@dataclass(frozen=True, slots=True)
class ConcentrationDiagnostics:
    hhi: Metric
    max_share: Metric
    n_features_over_1pct: int
    # `dict[str, float]` mantido (não `dict[str, Metric]`) — decisão
    # pragmática, mesma categoria da tomada em
    # `src.backtest.fill_reconciliation.SelectivityResult.
    # barrier_hit_distribution_given_filled`: os valores já são uma
    # distribuição normalizada somando 1.0 (shares de importância por
    # coluna), com unidade única e não-ambígua (RATIO/fração do total) — um
    # `Metric` por entrada repetiria a mesma unidade/`n`/`source` para cada
    # uma das ~10-14 colunas do design matrix sem ganho real de
    # interpretação sobre o que o dict já deixa claro (chave = nome da
    # feature, valor = fração do ganho total). Quem precisa da unidade
    # explícita usa `hhi`/`max_share` (os dois agregados que de fato entram
    # em gate, §5.8) já como `Metric`.
    shares: dict[str, float]


def compute_concentration(
    gain_by_column: dict[str, float],
    all_columns: tuple[str, ...],
    *,
    source: str = _DEFAULT_SOURCE,
) -> ConcentrationDiagnostics:
    """`gain_by_column` só precisa conter as colunas que o booster de fato
    usou em alguma divisão (gain > 0) — colunas de `all_columns` ausentes
    do dicionário recebem `share = 0.0` explicitamente, não são omitidas do
    denominador do HHI.

    `source` identifica a origem do `Metric` resultante (ex.
    `"alpha_c1_v1::fold3::long"`) — por padrão aponta para esta própria
    função, já que `compute_concentration()` não tem como saber de qual
    fold/lado veio `gain_by_column` (isso é de quem chama)."""
    n_features = len(all_columns)
    if n_features == 0:
        empty_reason = "all_columns vazio — nenhuma feature para medir concentração"
        return ConcentrationDiagnostics(
            hhi=Metric(
                value=float("nan"),
                unit=Unit.RATIO,
                n=0,
                n_semantics=_N_SEMANTICS_FEATURES,
                source=source,
                valid=False,
                invalid_reason=empty_reason,
            ),
            max_share=Metric(
                value=float("nan"),
                unit=Unit.RATIO,
                n=0,
                n_semantics=_N_SEMANTICS_FEATURES,
                source=source,
                valid=False,
                invalid_reason=empty_reason,
            ),
            n_features_over_1pct=0,
            shares={},
        )

    total_gain = sum(max(g, 0.0) for g in gain_by_column.values())
    if total_gain <= 0.0:
        shares = dict.fromkeys(all_columns, 0.0)
        return ConcentrationDiagnostics(
            hhi=Metric(
                value=0.0,
                unit=Unit.RATIO,
                n=n_features,
                n_semantics=_N_SEMANTICS_FEATURES,
                source=source,
            ),
            max_share=Metric(
                value=0.0,
                unit=Unit.RATIO,
                n=n_features,
                n_semantics=_N_SEMANTICS_FEATURES,
                source=source,
            ),
            n_features_over_1pct=0,
            shares=shares,
        )

    shares = {col: max(gain_by_column.get(col, 0.0), 0.0) / total_gain for col in all_columns}
    hhi_value = sum(s * s for s in shares.values())
    max_share_value = max(shares.values())
    n_over_1pct = sum(1 for s in shares.values() if s > _SHARE_PCT_THRESHOLD)
    return ConcentrationDiagnostics(
        hhi=Metric(
            value=float(hhi_value),
            unit=Unit.RATIO,
            n=n_features,
            n_semantics=_N_SEMANTICS_FEATURES,
            source=source,
        ),
        max_share=Metric(
            value=float(max_share_value),
            unit=Unit.RATIO,
            n=n_features,
            n_semantics=_N_SEMANTICS_FEATURES,
            source=source,
        ),
        n_features_over_1pct=n_over_1pct,
        shares=shares,
    )


@dataclass(frozen=True, slots=True)
class EffectiveConcentrationDiagnostics:
    """Irmão de `ConcentrationDiagnostics` — NUNCA a substitui, sempre
    reportado ao lado (D2 da task, CLAUDE.md). `hhi_effective`/
    `n_eff_factors` medem concentração no espaço de FATORES DE INFORMAÇÃO
    (após remover a redundância de features correlacionadas), não no
    espaço de features cru — ver `compute_effective_concentration`."""

    hhi_effective: Metric
    # `n_eff_factors` é contínuo (ex. 1,8), não um inteiro — "número efetivo
    # de fatores" no sentido de participation ratio (physics/finanças
    # quantitativas), não uma contagem literal. `Unit.COUNT` é o membro
    # existente mais próximo (não há `Unit` dedicado para "contagem
    # efetiva/fracionária de fatores"); `src/core/metric.py` está fora do
    # escopo desta task (não pode ganhar um membro novo aqui) — se um Unit
    # dedicado fizer sentido no futuro, este é o candidato.
    n_eff_factors: Metric
    # Pesos usados na ponderação (gain_share RENORMALIZADO dentro do
    # subconjunto `all_columns` recebido — soma 1.0 sobre esse subconjunto,
    # não sobre o design matrix inteiro; ver docstring de
    # `compute_effective_concentration` para a prova de que essa escolha de
    # normalização não muda `n_eff_factors`/`hhi_effective`, só a leitura
    # do dict em si). Plano (`dict[str, float]`), mesma decisão pragmática
    # de `ConcentrationDiagnostics.shares`.
    weights: dict[str, float]
    # Autovalores da matriz de correlação PONDERADA (`D @ C @ D`, ver
    # docstring da função), ordem DESCENDENTE — não é o dado bruto de
    # `correlation_matrix`, é o resultado já ponderado por gain_share.
    # Guardado para auditoria (mesma cultura de "meça antes de afirmar" do
    # CLAUDE.md) — permite reconstruir `n_eff_factors` sem retreinar.
    eigenvalues: tuple[float, ...]


def compute_effective_concentration(
    correlation_matrix: FloatArray,
    gain_by_column: dict[str, float],
    all_columns: tuple[str, ...],
    *,
    source: str = _DEFAULT_SOURCE_EFFECTIVE,
) -> EffectiveConcentrationDiagnostics:
    r"""Número efetivo de fatores de informação e HHI efetivo — D1 da task
    (CLAUDE.md, achado do Sprint 4: `E27f_cost_atr_ratio` ×
    `C07_vol_pctile_expanding` com ρ=-0,913; `A13_dist_ema48_atr` ×
    `B01_rsi_14` com ρ=0,947).

    **`correlation_matrix`** é a matriz de correlação de Pearson das
    features em `all_columns` (mesma ordem posicional — linha/coluna `i`
    corresponde a `all_columns[i]`), calculada pelo CHAMADOR sobre o MESMO
    subconjunto de treino do fold (`train_side_df` em
    `src.models.alpha.fit_side_model`) — nunca sobre o dataset inteiro,
    mesma disciplina B02/B04/B06 de `src.models.monotonic`/
    `src.models.environments`. Por padrão exclui as 4 dummies de regime
    (categóricas one-hot — correlação entre indicadores one-hot mede
    exclusividade categórica por construção, não redundância de
    INFORMAÇÃO; incluir os dummies aqui inflaria a matriz com correlações
    negativas estruturais que não têm a mesma leitura das correlações entre
    features contínuas T1). Só inclua os dummies se houver argumento
    econômico específico para tratá-los como fatores de risco correlacionados
    — não é o caso desta rodada.

    **Derivação exata (participation ratio ponderado por gain_share):**

    1. `w_i` = `gain_share` de cada feature `i` em `all_columns`,
       RENORMALIZADO dentro desse subconjunto (`Σ w_i = 1`) — pondera por
       quanto peso do MODELO está em cada feature (`gain_by_column`), não
       por variância bruta, conforme a task exige. Se `total_gain` do
       subconjunto for `<= 0` (nenhuma feature do subconjunto recebeu gain
       — caso degenerado), cai para peso uniforme `w_i = 1/p` (mesma leitura
       de "sem informação de importância disponível, assume-se
       equiponderado", análogo ao branch `total_gain <= 0` de
       `compute_concentration` acima, que também produz um valor definido
       em vez de `NaN`).
    2. `D = diag(√w_1, ..., √w_p)`.
    3. `M = D @ C @ D` — matriz de correlação PONDERADA por gain. `M` é PSD
       (transformação de congruência de uma matriz PSD por uma matriz
       diagonal real preserva PSD) e `trace(M) = Σ w_i C_ii = Σ w_i = 1`
       (`C_ii = 1` por ser matriz de correlação).
    4. `λ_1, ..., λ_p ≥ 0` = autovalores de `M` (somam 1, pelo passo 3).
    5. `N_eff = (Σλ)² / Σλ² = 1 / Σλ²` — participation ratio do espectro de
       `M` ("número efetivo de fatores": 1 = toda a massa de gain
       concentrada num único eixo perfeitamente correlacionado; `p` = toda
       a massa espalhada em `p` eixos mutuamente não-correlacionados).
    6. `hhi_effective = 1 / N_eff = Σλ²` — na MESMA escala `[1/p, 1]` do HHI
       nominal (`Σ share²`), diretamente comparável a ele.

    **Por que isto generaliza o HHI nominal corretamente (prova, não
    afirmação — verificada em teste unitário):**
    `Σλ² = trace(M²) = Σ_{i,j} w_i w_j C_{ij}²` (identidade de traço de
    matriz simétrica: `trace(M²) = Σ_{i,j} M_{ij}²`). Separando a diagonal
    (`i=j`, `C_ii=1`) do resto: `hhi_effective = Σ_i w_i² + Σ_{i≠j} w_i w_j
    ρ_{ij}²`. O primeiro termo é EXATAMENTE o HHI nominal (`Σ w_i²`) sobre
    os mesmos pesos; o segundo termo é `Σ_{i≠j} w_i w_j ρ_{ij}² ≥ 0` sempre
    (soma de quadrados). Logo **`hhi_effective ≥ hhi_nominal` sempre**, com
    igualdade se e somente se todas as correlações fora da diagonal forem
    zero — exatamente a leitura pretendida pela task ("dois slots que
    carregam quase a mesma informação não são dois graus de liberdade": o
    HHI nominal subestima, nunca superestima, a concentração real).

    **Sanitização defensiva de `correlation_matrix`:** entradas não-finitas
    (`NaN`/`inf`, produzidas por `np.corrcoef` quando uma feature é
    constante no fold — variância zero) viram `0.0` fora da diagonal e a
    diagonal é forçada para `1.0`; a matriz é simetrizada
    (`(M + M.T) / 2`) contra ruído de ponto flutuante antes do
    autovalor. Autovalores negativos residuais (ruído numérico — `M` é PSD
    por construção matemática, mas `eigvalsh` pode devolver `-1e-16` em vez
    de `0.0`) são truncados em `0.0` antes de somar."""
    n_features = len(all_columns)
    if n_features == 0:
        empty_reason = (
            "all_columns vazio — nenhuma feature para medir concentração efetiva"
        )
        invalid_hhi = Metric(
            value=float("nan"),
            unit=Unit.RATIO,
            n=0,
            n_semantics=_N_SEMANTICS_FEATURES,
            source=source,
            valid=False,
            invalid_reason=empty_reason,
        )
        invalid_n_eff = Metric(
            value=float("nan"),
            unit=Unit.COUNT,
            n=0,
            n_semantics=_N_SEMANTICS_FEATURES,
            source=source,
            valid=False,
            invalid_reason=empty_reason,
        )
        return EffectiveConcentrationDiagnostics(
            hhi_effective=invalid_hhi,
            n_eff_factors=invalid_n_eff,
            weights={},
            eigenvalues=(),
        )

    corr_input = np.asarray(correlation_matrix, dtype=np.float64)
    if corr_input.shape != (n_features, n_features):
        raise ValueError(
            "compute_effective_concentration: correlation_matrix.shape="
            f"{corr_input.shape} incompatível com len(all_columns)={n_features}"
        )

    total_gain = sum(max(gain_by_column.get(col, 0.0), 0.0) for col in all_columns)
    if total_gain > 0.0:
        weight_values = [
            max(gain_by_column.get(col, 0.0), 0.0) / total_gain for col in all_columns
        ]
    else:
        weight_values = [1.0 / n_features] * n_features
    weights = dict(zip(all_columns, weight_values, strict=True))
    w = np.asarray(weight_values, dtype=np.float64)

    # sanitização (ver docstring): NaN/inf -> 0.0 fora da diagonal, 1.0 na
    # diagonal, simetriza contra ruído de ponto flutuante.
    corr_clean = np.where(np.isfinite(corr_input), corr_input, 0.0)
    np.fill_diagonal(corr_clean, 1.0)
    corr_clean = (corr_clean + corr_clean.T) / 2.0

    d_sqrt = np.sqrt(w)
    weighted_corr = np.outer(d_sqrt, d_sqrt) * corr_clean
    eigenvalues_raw = np.linalg.eigvalsh(weighted_corr)
    eigenvalues_clipped = np.clip(eigenvalues_raw, 0.0, None)

    sum_eig = float(eigenvalues_clipped.sum())
    sum_eig_sq = float(np.sum(eigenvalues_clipped**2))
    if sum_eig > 0.0 and sum_eig_sq > 0.0:
        n_eff_value = (sum_eig**2) / sum_eig_sq
        hhi_eff_value = sum_eig_sq / (sum_eig**2)
    else:
        # degenerado (pesos todos zero — não deveria acontecer, w soma 1.0
        # por construção nos dois branches acima, mas o guard evita
        # divisão por zero se algum dia isso deixar de valer): equiponderado.
        n_eff_value = float(n_features)
        hhi_eff_value = 1.0 / n_features

    eigenvalues_sorted = tuple(
        sorted((float(v) for v in eigenvalues_clipped), reverse=True)
    )

    return EffectiveConcentrationDiagnostics(
        hhi_effective=Metric(
            value=hhi_eff_value,
            unit=Unit.RATIO,
            n=n_features,
            n_semantics=_N_SEMANTICS_FEATURES,
            source=source,
        ),
        n_eff_factors=Metric(
            value=n_eff_value,
            unit=Unit.COUNT,
            n=n_features,
            n_semantics=_N_SEMANTICS_FEATURES,
            source=source,
        ),
        weights=weights,
        eigenvalues=eigenvalues_sorted,
    )
