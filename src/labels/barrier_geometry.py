"""S1 — geometria de barreira reparametrizada (`reward_risk_ratio` ×
`sl_mult`), `docs/s1_design_doc_sweep_tp_sl_reward_risk_2026-08-22.md` §5/§7.
Núcleo funcional puro (`resolve_geometry`) + ponto de entrada com IO mínimo
(`filled_side_population`, seleciona colunas de `labels.parquet` já
carregado — não faz leitura de arquivo, isso é responsabilidade do
chamador, `src.analysis.s1_tp_sl_sensitivity`)."""

from __future__ import annotations

from fractions import Fraction
from typing import Final

import polars as pl

#: Grade declarada a priori (B20, `CLAUDE.md`) — verificação de robustez
#: AO REDOR do valor de produção já escolhido (célula central R=4/3,S=3/2
#: -> tp=2,0,sl=1,5), não busca de novo ótimo. Ver §5/§11 risco #1 do
#: design doc — critério de "sobrevive à faixa" fica TBD no relatório,
#: decisão do Manager, não travada aqui.
REWARD_RISK_GRID: Final[tuple[Fraction, ...]] = (
    Fraction(1, 1),
    Fraction(4, 3),
    Fraction(2, 1),
)  # noqa: magic-number -- grid declarado a priori, §16.10 regra 4, ver docs/s1_design_doc_sweep_tp_sl_reward_risk_2026-08-22.md
SL_MULT_GRID: Final[tuple[Fraction, ...]] = (
    Fraction(3, 4),
    Fraction(3, 2),
    Fraction(9, 4),
)  # noqa: magic-number


def resolve_geometry(reward_risk_ratio: Fraction, sl_mult: Fraction) -> tuple[float, float]:
    """`(R,S) -> (tp_atr_mult, sl_atr_mult)` via aritmética `Fraction`
    exata — nunca `R*S` em float (verificado: `(4/3)*1.5` em float64 !=
    `2.0` exato, ver §5 do design doc). `tp = R·S`, `sl = S`."""
    tp_atr_mult = reward_risk_ratio * sl_mult
    return float(tp_atr_mult), float(sl_mult)


def filled_side_population(labels: pl.DataFrame, *, side: int) -> pl.DataFrame:
    """Trades já preenchidos de UM lado, direto de `labels.parquet` bruto
    (`LABEL_COLUMNS`, `src.labels.triple_barrier`) — SEM coluna `regime`
    (S1 bypassa o Regime Engine de propósito, §4 do design doc). Função
    NOVA e mínima, não promoção de `_filled_side_population` de
    `src.analysis.faixa2_caminho_b` (aquela exige `mf_data`, saída de
    `build_modeling_frame`, que `labels.parquet` bruto não tem)."""
    if side not in (1, -1):
        raise ValueError(f"filled_side_population: side deve ser 1 ou -1, recebido {side}")
    return labels.filter(
        (pl.col("side") == side) & (pl.col("barrier_hit").cast(pl.Utf8) != "NOFILL")
    ).select("t0", "t_entry", "entry_price_fill", "atr_at_t0")
