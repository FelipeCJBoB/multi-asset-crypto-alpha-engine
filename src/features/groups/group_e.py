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
from .._constants import load_constant
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
    primeiro, taker se o SL for tocado primeiro.

    **Corrigido 2026-08-24 (achado do usuário, AG-027 fechado de verdade).**
    Até esta correção, a probabilidade condicional de qual barreira toca
    primeiro era 50/50 hardcoded no corpo — apesar de `round_trip_cost_bps_
    maker_prob` já existir declarada em `constants.yaml` desde AG-027
    (2026-08-15), a função nunca a lia. Ruína do apostador
    (`tp_atr_mult=2,0`/`sl_atr_mult=1,5`, distâncias assimétricas) prevê
    P(TP primeiro)=1,5/3,5≈42,9% analítico; medição empírica real
    (`tools/diagnostics/measure_barrier_touch_probability.py`, 5 ativos,
    `labels.parquet`) confirma 42,06% pooled — usa o valor MEDIDO, não o
    analítico. Agora lido de `constants.yaml` via `load_constant`, não mais
    literal — os 7 call sites conhecidos (`group_e.py`, `cost_surface.py`,
    `volatility_operational_effect.py`, `feasibility.py`,
    `m3_timeframe_choice.py`, `risk/limits.py`, `s1_tp_sl_sensitivity.py`)
    herdam a correção automaticamente, nenhuma assinatura mudou."""
    maker_prob = float(load_constant("round_trip_cost_bps_maker_prob"))
    return (maker_fee + maker_prob * maker_fee + (1.0 - maker_prob) * taker_fee) * 10000  # noqa: magic-number -- conversão fração->bps, não constante de domínio


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


# ============================================================================
# Lote B da liberação de features (H5, 2026-08-24) — E03f, única do grupo
# E nesta leva (precisa de primitiva nova: soma por EVENTO de funding,
# não por barra -- ver docstring de e03f_funding_cum_3d).
# ============================================================================


def e03f_funding_cum_3d(
    funding_last_aligned: FloatArray,
    close_time_ms: FloatArray,
    funding_interval_hours: int,
    n_events: int,
) -> FloatArray:
    """Soma dos últimos `n_events` (=9, ~72h/8h) valores de funding
    CONHECIDOS até a barra `t` — §2.6 E03f. Soma por EVENTO, não por
    barra: uma soma ingênua sobre janela de barras (ex. `rolling_sum`
    de `funding_last_aligned` sobre N barras) contaria o MESMO valor
    repetido ~32× (todas as barras de 15m dentro de um período de 8h
    carregam o mesmo `funding_last_aligned`, por construção do
    asof-join backward que já o alinhou) — errado por construção, não é
    o que "soma dos últimos 9 eventos" significa.

    Fronteira de evento detectada por TIMESTAMP (`close_time_ms //
    (funding_interval_hours em ms)`, mesma técnica de `e05f_time_to_
    funding_h`), NÃO por mudança de VALOR — robusto ao caso raro mas
    real (ex. funding no cap/floor, `feature_e05f_funding_interval_
    hours` nota) de dois eventos consecutivos terem o MESMO valor
    numérico, o que uma detecção por "valor mudou" perderia
    silenciosamente (fundiria 2 eventos distintos em 1).

    Implementado com laço explícito de estado (mesma classe de
    `support.wilder_smooth`: acumulação causal com transição de
    fronteira, não vetorizável de forma direta em `polars.rolling_*`) —
    mantém só os últimos `n_events` valores conhecidos; `out[t]` só é
    definido quando já há `n_events` eventos vistos."""
    n = funding_last_aligned.shape[0]
    interval_ms = funding_interval_hours * 3_600_000  # noqa: magic-number -- ms/hora, conversão de unidade, mesma constante de e05f_time_to_funding_h
    epoch = close_time_ms.astype(np.int64) // interval_ms
    out = np.full(n, np.nan, dtype=np.float64)

    recent_values: list[float] = []
    last_epoch_seen: int | None = None
    for t in range(n):
        e = int(epoch[t])
        if last_epoch_seen is None or e != last_epoch_seen:
            v = funding_last_aligned[t]
            if not np.isnan(v):
                recent_values.append(float(v))
                if len(recent_values) > n_events:
                    recent_values.pop(0)
            last_epoch_seen = e
        if len(recent_values) == n_events:
            out[t] = sum(recent_values)
    return out


# ============================================================================
# Lote C da liberação de features (H5, 2026-08-24) — E08f, E14f-E18f.
# Todas T2 (§0.2 R4/§2.13, nenhuma promovida a T1). Zero primitiva nova
# (reusa support.expanding_zscore_strict, já usada por D03f/E02f) — só
# fonte já exposta por _sources.load_futures_positioning_aligned
# (mesmo arquivo `metrics` de E08f/E09f/E10f, colunas antes não lidas).
# ============================================================================


def e08f_oi_notional(oi_notional_aligned: FloatArray) -> FloatArray:
    """`sum_open_interest_value`, já alinhado ao grid causal — §2.6
    E08f. Passthrough puro, mesma convenção de `e01f_funding_last`/
    `e09f_oi_contracts`."""
    return oi_notional_aligned


def e14f_toptrader_ls_ratio(toptrader_ls_ratio_aligned: FloatArray) -> FloatArray:
    """`sum_toptrader_long_short_ratio` (variante baseada em SOMA de
    posições/notional, não `count_` baseada em número de contas —
    decisão do Manager, 2026-08-24, consistente com E09f/E18f), já
    alinhado ao grid causal — §2.6 E14f. Passthrough puro."""
    return toptrader_ls_ratio_aligned


def e15f_toptrader_ls_z(
    toptrader_ls_ratio_aligned: FloatArray, *, min_common_history_bars: int | None = None
) -> FloatArray:
    """Z-score EXPANSIVO estrito de `toptrader_ls_ratio` (E14f) — §2.6
    E15f. Mesma primitiva de D03f/E02f (`support.expanding_zscore_
    strict`, B02) e mesmo mecanismo de `min_common_history_bars`
    (AG-030) das 3 já ativas."""
    return support.expanding_zscore_strict(
        toptrader_ls_ratio_aligned, min_common_history_bars=min_common_history_bars
    )


def e16f_global_ls_ratio(global_ls_ratio_aligned: FloatArray) -> FloatArray:
    """`count_long_short_ratio` (razão de long/short do MERCADO geral,
    baseada em contagem de contas — diferente de `toptrader_ls_ratio`,
    que é dos top traders, baseada em soma de posições; PRD declara
    fontes distintas pras duas, `count_` aqui não é escolha — é a única
    coluna de long/short "geral" disponível no schema de `metrics`,
    `sum_toptrader_long_short_ratio`/`count_toptrader_long_short_ratio`
    são AMBAS específicas de top traders), já alinhado ao grid causal —
    §2.6 E16f. Passthrough puro."""
    return global_ls_ratio_aligned


def e17f_retail_vs_top_spread(
    global_ls_ratio_aligned: FloatArray,
    toptrader_ls_z: FloatArray,
    *,
    min_common_history_bars: int | None = None,
) -> FloatArray:
    """`global_ls_z - toptrader_ls_z` — §2.6 E17f, proxy de
    posicionamento contrário (retail vs. top traders). `global_ls_z`
    calculado INTERNAMENTE (mesma primitiva `expanding_zscore_strict`
    de E15f, aplicada a `global_ls_ratio_aligned`) — o PRD não cataloga
    "E16f_z" como feature própria, só usa "global_ls_z" dentro da
    fórmula de E17f. `toptrader_ls_z` é reaproveitado (já calculado
    como E15f pelo chamador), não recomputado aqui."""
    global_ls_z = support.expanding_zscore_strict(
        global_ls_ratio_aligned, min_common_history_bars=min_common_history_bars
    )
    out: FloatArray = global_ls_z - toptrader_ls_z
    return out


def e18f_taker_ls_vol_ratio(taker_ls_vol_ratio_aligned: FloatArray) -> FloatArray:
    """`sum_taker_long_short_vol_ratio`, já alinhado ao grid causal —
    §2.6 E18f. Passthrough puro."""
    return taker_ls_vol_ratio_aligned


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
