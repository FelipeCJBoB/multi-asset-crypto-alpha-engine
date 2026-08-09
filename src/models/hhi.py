"""Diagnóstico de concentração — §5.8. `HHI = Σ share²` da importância por
ganho total (`total_gain`), mais o maior share individual e a contagem de
features com share > 1%. Núcleo puro (sem IO, sem XGBoost) — recebe o
dicionário já extraído de `booster.get_score(importance_type="total_gain")`
mapeado para nomes de coluna reais, não `"f0".."fN"`."""

from __future__ import annotations

from dataclasses import dataclass

from src.core.metric import Metric, Unit

_SHARE_PCT_THRESHOLD = 0.01  # 1% — literal do próprio §5.8 do PRD  # noqa: magic-number

# `Metric.source` default — `compute_concentration()` é pura (não sabe se
# `gain_by_column` veio do fold 3 lado long ou do fold 7 lado short; essa
# distinção é de quem chama, `src.models.alpha.fit_side_model`). Kwarg com
# default para não quebrar a chamada posicional existente
# (`compute_concentration(gain_by_column, DESIGN_COLUMNS)` em
# `src.models.alpha`) — quem tiver contexto melhor pode sobrescrever.
_DEFAULT_SOURCE = "models.hhi.compute_concentration"
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
