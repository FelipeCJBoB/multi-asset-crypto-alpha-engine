"""GRUPO E — Futuros: funding, open interest, custo (§2.6). Escopo T1 do
Sprint 4: E02f, E10f, E27f.

`funding_last_aligned` e `oi_contracts_aligned` chegam já alinhados barra a
barra ao grid de 15m (via `src.features._sources.asof_align_backward`,
asof-join causal backward) — o alinhamento acontece antes destas funções,
não dentro delas; aqui só a matemática da feature em si.
"""

from __future__ import annotations

import numpy as np

from .. import support
from ..support import FloatArray


def e02f_funding_z_expanding(funding_last_aligned: FloatArray) -> FloatArray:
    """Z-score expansivo estrito de `funding_last` — §2.6 E02f."""
    return support.expanding_zscore_strict(funding_last_aligned)


def e10f_oi_change_z_48(oi_contracts_aligned: FloatArray, window: int) -> FloatArray:
    """Z-score ROLANTE (janela fixa `window`) de `Δln(oi_contracts)` —
    §2.6 E10f. `oi_contracts_aligned` pode conter NaN (barra sem nenhum
    ponto de `metrics` anterior ainda, início da série de OI) — `np.log`
    de NaN é NaN por definição do numpy, sem exceção, e se propaga
    corretamente pelo resto do cálculo."""
    log_oi = np.log(oi_contracts_aligned)
    n = log_oi.shape[0]
    delta = np.full(n, np.nan, dtype=np.float64)
    if n > 1:
        delta[1:] = np.diff(log_oi)
    return support.rolling_zscore(delta, window)


def round_trip_cost_bps(maker_fee: float, taker_fee: float) -> float:
    """Custo de round-trip do caminho assimétrico `maker_in / maker_tp /
    taker_sl` (§9.1): entrada sempre maker; saída maker se o TP for tocado
    primeiro, taker se o SL for tocado primeiro. Sem estimativa melhor da
    probabilidade condicional de qual barreira toca primeiro nesta etapa,
    50/50 é a leitura mais simples e é exatamente a que reproduz o
    `c_médio(assimétrico) = 0,055%` citado textualmente em §0.2 R2 dado
    `maker_fee=0,0002`/`taker_fee=0,0005` (`constants.yaml`):
    `0,0002 + 0,5×0,0002 + 0,5×0,0005 = 0,00055`. Não é uma constante nova
    — é combinação fixa de duas que já existem em `constants.yaml`, e o
    peso 0,5 é literal (já na whitelist do lint de proveniência,
    `tools/lint/banned_patterns.py::_ALLOWED_NUMERIC_LITERALS`)."""
    # 0.5/0.5 = round_trip_cost_bps_maker_prob em config/constants.yaml (AG-027,
    # 2026-08-15) -- valor ASSUMED, medição real aponta 42,06%, não 50%; não
    # lido dinamicamente ainda (ver ressalva de escopo na entrada do yaml).
    return (maker_fee + 0.5 * maker_fee + 0.5 * taker_fee) * 10000  # noqa: magic-number -- ver comentário acima


def e27f_cost_atr_ratio(atr_20_pct: FloatArray, maker_fee: float, taker_fee: float) -> FloatArray:
    """`custo_round_trip_bps / (atr_20_pct × 10000)` — §2.6 E27f."""
    cost_bps = round_trip_cost_bps(maker_fee, taker_fee)
    with np.errstate(divide="ignore", invalid="ignore"):
        out: FloatArray = cost_bps / (atr_20_pct * 10000)
    return out
