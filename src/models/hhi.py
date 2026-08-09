"""Diagnóstico de concentração — §5.8. `HHI = Σ share²` da importância por
ganho total (`total_gain`), mais o maior share individual e a contagem de
features com share > 1%. Núcleo puro (sem IO, sem XGBoost) — recebe o
dicionário já extraído de `booster.get_score(importance_type="total_gain")`
mapeado para nomes de coluna reais, não `"f0".."fN"`."""

from __future__ import annotations

from dataclasses import dataclass

_SHARE_PCT_THRESHOLD = 0.01  # 1% — literal do próprio §5.8 do PRD  # noqa: magic-number


@dataclass(frozen=True, slots=True)
class ConcentrationDiagnostics:
    hhi: float
    max_share: float
    n_features_over_1pct: int
    shares: dict[str, float]


def compute_concentration(
    gain_by_column: dict[str, float], all_columns: tuple[str, ...]
) -> ConcentrationDiagnostics:
    """`gain_by_column` só precisa conter as colunas que o booster de fato
    usou em alguma divisão (gain > 0) — colunas de `all_columns` ausentes
    do dicionário recebem `share = 0.0` explicitamente, não são omitidas do
    denominador do HHI."""
    total_gain = sum(max(g, 0.0) for g in gain_by_column.values())
    if total_gain <= 0.0:
        shares = dict.fromkeys(all_columns, 0.0)
        return ConcentrationDiagnostics(
            hhi=0.0, max_share=0.0, n_features_over_1pct=0, shares=shares
        )

    shares = {col: max(gain_by_column.get(col, 0.0), 0.0) / total_gain for col in all_columns}
    hhi = sum(s * s for s in shares.values())
    max_share = max(shares.values())
    n_over_1pct = sum(1 for s in shares.values() if s > _SHARE_PCT_THRESHOLD)
    return ConcentrationDiagnostics(
        hhi=float(hhi), max_share=float(max_share), n_features_over_1pct=n_over_1pct, shares=shares
    )
