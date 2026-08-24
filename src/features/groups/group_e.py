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


def e02f_funding_z_expanding(
    funding_last_aligned: FloatArray, *, min_common_history_bars: int | None = None
) -> FloatArray:
    """Z-score expansivo estrito de `funding_last` — §2.6 E02f.

    `min_common_history_bars` (AG-030, T0.5): repassado direto a
    `support.expanding_zscore_strict` — cap no histórico comum entre os 5
    ativos (ver docstring da primitiva). `None` (default) preserva o
    comportamento expansivo desde a origem do ativo."""
    return support.expanding_zscore_strict(
        funding_last_aligned, min_common_history_bars=min_common_history_bars
    )


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


# ============================================================================
# Lote A da liberação de features (H5, 2026-08-24) — E01f, E05f, E09f,
# E11f, E12f. Todas T2 (nenhuma promovida a T1 por esta implementação,
# §0.2 R4/§2.13). Nenhuma fonte nova — `funding_last_aligned`/`oi_
# contracts_aligned` já chegam alinhados (mesmo contrato de E02f/E10f);
# E05f é matemática pura de timestamp (`close_time`, já em `bars_15m`).
# ============================================================================


def e01f_funding_last(funding_last_aligned: FloatArray) -> FloatArray:
    """Último funding liquidado, já alinhado ao grid causal (asof-join
    backward, `_sources.asof_align_backward`) — §2.6 E01f. Passthrough
    puro: a causalidade/alinhamento já acontece ANTES desta função,
    mesma convenção de E02f/E10f (ver docstring do módulo)."""
    return funding_last_aligned


def e05f_time_to_funding_h(close_time_ms: FloatArray, funding_interval_hours: int) -> FloatArray:
    """Horas até o próximo settlement de funding — §2.6 E05f. Binance
    USDⓈ-M liquida funding a cada `funding_interval_hours` (=8, `feature_
    e05f_funding_interval_hours`) em horários fixos de relógio UTC
    (00:00/08:00/16:00 — confirmado via pesquisa web nesta sessão),
    alinhados à época Unix (1970-01-01T00:00:00Z já é fronteira de 8h) —
    matemática pura de timestamp, sem IO, sem fonte de dado adicional
    além de `close_time` (já em `bars_15m`). `close_time_ms` convertido
    pra int64 (epoch ms) evita erro de ponto flutuante no módulo;
    conversão pra horas (float) só no resultado final."""
    ms_per_hour = 3_600_000  # noqa: magic-number -- ms/hora, conversão de unidade, não hiperparâmetro de negócio
    interval_ms = funding_interval_hours * ms_per_hour
    close_time_int = close_time_ms.astype(np.int64)
    ms_since_boundary = close_time_int % interval_ms
    ms_to_next = (interval_ms - ms_since_boundary) % interval_ms
    out: FloatArray = ms_to_next.astype(np.float64) / float(ms_per_hour)
    return out


def e09f_oi_contracts(oi_contracts_aligned: FloatArray) -> FloatArray:
    """`sum_open_interest`, já alinhado ao grid causal — §2.6 E09f.
    Passthrough puro, mesma convenção de `e01f_funding_last`."""
    return oi_contracts_aligned


def e11f_oi_change_1d(oi_contracts_aligned: FloatArray, lag_bars: int) -> FloatArray:
    """`Δln(oi_contracts)` sobre `lag_bars` barras — §2.6 E11f. Nome
    "1d" herdado do PRD original a 30m (48 barras × 30m = 24h); mantido
    em CONTAGEM DE BARRAS (48) sob a migração pra 15m, mesma convenção
    documentada em `registry.yaml` (NOTA DE TF) pras 10 features T1 —
    não recalibrado pra 96 barras (24h reais a 15m). Diferente de E10f
    (z-score ROLANTE do delta de 1 barra): aqui é o delta bruto de
    `lag_bars` barras, sem z-score, mesmo padrão de A04 (`log_return_12`)
    aplicado a OI em vez de close."""
    log_oi = np.log(oi_contracts_aligned)
    n = log_oi.shape[0]
    out = np.full(n, np.nan, dtype=np.float64)
    if n > lag_bars:
        with np.errstate(invalid="ignore"):
            out[lag_bars:] = log_oi[lag_bars:] - log_oi[:-lag_bars]
    return out


def e12f_price_oi_divergence(
    ret_lag: FloatArray, oi_contracts_aligned: FloatArray, oi_lag_bars: int
) -> FloatArray:
    """`sign(ret_lag) × sign(Δln(oi))` ∈ {-1,0,1} — §2.6 E12f. `ret_lag`
    é o log-retorno de referência (A04, `log_return_12` — mesmo lookback
    12 do PRD "ret_12"), passado já calculado pelo chamador; `Δln(oi)`
    sobre `oi_lag_bars` (12, dedicado — não reaproveita `lag_bars` de
    E11f, que é 48). `np.sign(0.0) == 0.0` por definição do numpy,
    reproduzindo o "0" do range declarado sem tratamento especial."""
    log_oi = np.log(oi_contracts_aligned)
    n = log_oi.shape[0]
    oi_change = np.full(n, np.nan, dtype=np.float64)
    if n > oi_lag_bars:
        with np.errstate(invalid="ignore"):
            oi_change[oi_lag_bars:] = log_oi[oi_lag_bars:] - log_oi[:-oi_lag_bars]
    with np.errstate(invalid="ignore"):
        out: FloatArray = np.sign(ret_lag) * np.sign(oi_change)
    return out
