"""GRUPO B — Momentum e reversão (§2.3). Escopo do Sprint 4: B01 (T1) e
B07 (T2, mas implementado agora — insumo do Regime Engine, §4.2, Sprint 5)."""

from __future__ import annotations

import numpy as np
import polars as pl

from .. import support
from ..support import FloatArray


def b01_rsi_14(close: FloatArray, window: int) -> FloatArray:
    """RSI de Wilder escalado para `[-1, 1]` via `(RSI-50)/50` — §2.3 B01."""
    rsi = support.rsi_wilder(close, window)
    out: FloatArray = (rsi - 50.0) / 50.0  # reescala fixa [0,100] do RSI [noqa: magic-number]
    return out


def b07_efficiency_ratio_48(close: FloatArray, window: int) -> FloatArray:
    """`|C_t − C_{t−48}| / Σ|C_i − C_{i−1}|` — §2.3 B07. T2 no vetor de
    treino do Alpha V1, mas eixo de partição do Regime Engine (§4.2) — por
    isso implementado no Sprint 4 junto com T1, não adiado para quando B07
    for promovido por ablação (§2.0.1)."""
    return support.efficiency_ratio(close, window)


# ============================================================================
# Lote A da liberação de features (H5, 2026-08-24) — B02-B06, B08, B09, B11.
# Todas T2 (nenhuma promovida a T1 por esta implementação, §0.2 R4/§2.13).
# ============================================================================


def b02_rsi_48(close: FloatArray, window: int) -> FloatArray:
    """RSI de Wilder, escalado para `[-1, 1]` — §2.3 B02 (mesma fórmula
    de B01, janela diferente)."""
    return b01_rsi_14(close, window)


def b03_roc_12(close: FloatArray, lookback_bars: int) -> FloatArray:
    """`(C_t - C_{t-lookback_bars}) / C_{t-lookback_bars}` — §2.3 B03."""
    n = close.shape[0]
    out = np.full(n, np.nan, dtype=np.float64)
    if n > lookback_bars:
        with np.errstate(divide="ignore", invalid="ignore"):
            out[lookback_bars:] = (close[lookback_bars:] - close[:-lookback_bars]) / close[
                :-lookback_bars
            ]
    return out


def _ema_skip_leading_nan(values: FloatArray, span: int) -> FloatArray:
    """`support.ema` (via `polars.ewm_mean`) nunca foi exercitada neste
    repo com uma entrada que já carrega NaN líder (todo caller existente
    passa `close`, preço bruto, sem NaN) — a semântica NaN-vs-null do
    `ewm_mean` do polars pra esse caso não está verificada aqui, e uma
    suposição errada poderia propagar NaN pra sempre (contaminação
    silenciosa do resto da série). Em vez de confiar nisso, aplica
    `support.ema` só na cauda válida (mesma técnica de `support.
    wilder_smooth`/`_first_valid_index`: acha o primeiro índice não-NaN,
    computa só a partir dali) e cola o prefixo NaN de volta —
    determinístico por construção, independente da semântica interna do
    polars."""
    n = values.shape[0]
    out = np.full(n, np.nan, dtype=np.float64)
    first_valid = 0
    while first_valid < n and np.isnan(values[first_valid]):
        first_valid += 1
    if first_valid >= n:
        return out
    out[first_valid:] = support.ema(values[first_valid:], span)
    return out


def b04_macd_hist_norm(
    close: FloatArray,
    atr_20_abs: FloatArray,
    fast_window: int,
    slow_window: int,
    signal_window: int,
) -> FloatArray:
    """`(MACD_{fast,slow} - sinal_signal) / ATR_20` (absoluto) — §2.3 B04.
    `MACD = EMA_fast - EMA_slow` (Gerald Appel, anos 1970 — validado via
    pesquisa web: EMA12/EMA26, sinal=EMA9 do MACD, convenção pública
    universal). Numerador é diferença de duas EMAs de preço (unidade de
    preço) → denominador ATR absoluto, mesma leitura dimensional de
    A13/A14. Sinal = EMA9 de `macd`, que já carrega o warmup NaN de
    `ema_slow` — via `_ema_skip_leading_nan` (não `support.ema` direto
    sobre a série com NaN líder, ver docstring dela)."""
    ema_fast = support.ema(close, fast_window)
    ema_slow = support.ema(close, slow_window)
    macd = ema_fast - ema_slow
    signal = _ema_skip_leading_nan(macd, signal_window)
    hist = macd - signal
    with np.errstate(divide="ignore", invalid="ignore"):
        out: FloatArray = hist / atr_20_abs
    return out


def b05_ema_slope_24(
    close: FloatArray, atr_20_abs: FloatArray, ema_window: int, slope_lag_bars: int
) -> FloatArray:
    """`(EMA_{ema_window,t} - EMA_{ema_window,t-slope_lag_bars}) / ATR_20`
    (absoluto) — §2.3 B05. Numerador é diferença de EMA de preço (unidade
    de preço) → denominador ATR absoluto, mesma leitura dimensional de
    A13/A14/B04."""
    ema_v = support.ema(close, ema_window)
    n = ema_v.shape[0]
    slope = np.full(n, np.nan, dtype=np.float64)
    if n > slope_lag_bars:
        slope[slope_lag_bars:] = ema_v[slope_lag_bars:] - ema_v[:-slope_lag_bars]
    with np.errstate(divide="ignore", invalid="ignore"):
        out: FloatArray = slope / atr_20_abs
    return out


def b06_momentum_accel(close: FloatArray, atr_20_pct: FloatArray, lookback_bars: int) -> FloatArray:
    """`ret_{lookback_bars,t} - ret_{lookback_bars,t-lookback_bars}`,
    normalizado por `atr_20_pct` — §2.3 B06. `ret_lookback_bars` é o
    log-retorno de `lookback_bars` (mesmo núcleo de A01-A04, inline aqui
    para não depender de símbolo privado de outro módulo); o lag do
    deslocamento é o PRÓPRIO `lookback_bars` (comparar o retorno de N
    barras agora contra o retorno de N barras N barras atrás, sem
    sobreposição) — não é um segundo parâmetro independente (PRD tabula
    lookback "8+20" = 4+4 barras de retorno + a janela de ATR, não dois
    lookbacks de retorno distintos). Numerador adimensional (diferença de
    log-retornos) → denominador `atr_20_pct`, mesma leitura de A05/A06."""
    n = close.shape[0]
    ret = np.full(n, np.nan, dtype=np.float64)
    if n > lookback_bars:
        with np.errstate(divide="ignore", invalid="ignore"):
            ret[lookback_bars:] = np.log(close[lookback_bars:] / close[:-lookback_bars])
    accel = np.full(n, np.nan, dtype=np.float64)
    if n > lookback_bars:
        accel[lookback_bars:] = ret[lookback_bars:] - ret[:-lookback_bars]
    with np.errstate(divide="ignore", invalid="ignore"):
        out: FloatArray = accel / atr_20_pct
    return out


def b08_efficiency_ratio_16(close: FloatArray, window: int) -> FloatArray:
    """`|C_t − C_{t−window}| / Σ|C_i − C_{i−1}|` — §2.3 B08 (mesma
    fórmula de B07, janela diferente)."""
    return support.efficiency_ratio(close, window)


def b09_zscore_close_48(close: FloatArray, window: int) -> FloatArray:
    """`(C_t - μ_window) / σ_window` — §2.3 B09."""
    return support.rolling_zscore(close, window)


def b11_bb_position_20(close: FloatArray, window: int, std_multiplier: float) -> FloatArray:
    """`(C - MA_window) / (std_multiplier × σ_window)` — §2.3 B11
    (posição estilo Bollinger %B). `std_multiplier=2.0` é a convenção
    padrão de Bollinger Bands (validado via pesquisa web: John Bollinger,
    2 desvios-padrão). `rolling_zscore(close, window)` já calcula
    `(C-MA)/σ` — esta função só reescala pelo `std_multiplier`, não
    duplica o cálculo de z-score."""
    z = support.rolling_zscore(close, window)
    out: FloatArray = z / std_multiplier
    return out


# ============================================================================
# Lote D da liberação de features (2026-08-28, `AG-372`/ADR-006) — B12-B15,
# família momentum/reversão reconstruída em torno do H real medido nesta
# sessão (n_bars_held mediana=1, p75=3, estável entre R1/R2/R3). Todas T1
# por decisão direta do Manager (autorização explícita 2026-08-28,
# `CLAUDE.md` "correção pedida pelo Manager é o default imediato").
# ============================================================================


def b12_close_location_h3(
    high: FloatArray, low: FloatArray, close: FloatArray, window: int
) -> FloatArray:
    """Posição do close dentro do range mínimo-máximo rolante de `window`
    barras (mesmo núcleo de B10), reescalado pra `[-1,1]` (mesma convenção
    de B01) — **[NOVO, 2026-08-28, `AG-372`/ADR-006]** consolida A10/B09/
    B10/B11 (4 features julgadas o MESMO conceito -- "posição do close na
    distribuição recente" -- sob 4 janelas (1/48/14/20) nunca calibradas
    contra H, veredito `SEM_MECANISMO`/`INCOERENTE_DIMENSIONAL` em
    `audit/feature_thesis/fichas_69_2026-08-25.yaml`) numa família única,
    na janela certa. `range_=0` (preço flat na janela inteira) produz `0`
    (ponto médio de `[-1,1]`), mesma convenção de A07-A10. Janela rolante
    fixa (a barra `t` entra na própria janela, B02 não se aplica)."""
    lowest_low = pl.Series(low).rolling_min(window_size=window, min_samples=window).to_numpy()
    highest_high = pl.Series(high).rolling_max(window_size=window, min_samples=window).to_numpy()
    range_ = highest_high - lowest_low
    with np.errstate(divide="ignore", invalid="ignore"):
        pct = np.where(range_ == 0.0, 0.5, (close - lowest_low) / range_)
        out: FloatArray = pct * 2.0 - 1.0
    return out


def b13_extension_h3(ret_h: FloatArray, realized_vol_h: FloatArray) -> FloatArray:
    """`|ret_h| / realized_vol_h` — magnitude do movimento recente
    relativo à volatilidade realizada típica, mesma janela `H`. **[NOVO,
    2026-08-28, `AG-372`/ADR-006]** Tese: quão "extremo" é o movimento —
    condição de entrada da hipótese de reversão (extensão grande é
    candidato a exaustão, não confirmação por si só — ver B14).

    **[CORRIGIDO 2026-08-28, achado de `/audit_engineering`]**
    `realized_vol_h` (`std` de 3 retornos, janela curta de propósito —
    ver ADR-006) pode ser exatamente `0` em barras consecutivas de preço
    idêntico — não hipotético: dollar bar fecha por volume, não por
    tempo, e um trade de tick repetido em ativo de menor liquidez (ex.
    XRP/BNB) pode gerar 3 barras de retorno zero. `check_unguarded_
    ratios.py` pegou a divisão sem guarda (denominador `realized_vol_h`
    variável, sem checagem de sinal). Guardado: `realized_vol_h<=0`
    produz `NaN`, nunca `inf` silencioso."""
    with np.errstate(divide="ignore", invalid="ignore"):
        out: FloatArray = np.where(realized_vol_h > 0.0, np.abs(ret_h) / realized_vol_h, np.nan)
    return out


def b14_rejection_after_extension(
    ret_h_prior: FloatArray, ret_1: FloatArray, atr_20_pct: FloatArray
) -> FloatArray:
    """`-sign(ret_h_prior) × ret_1_t / atr_20_pct_t` — **[NOVO,
    2026-08-28, `AG-372`/ADR-006]**, a feature de "exaustão"/falha de
    continuação. `ret_h_prior` é o retorno de `H` barras já ENCERRADO em
    `t-1` (a extensão que aconteceu ANTES da barra atual — não inclui a
    barra `t`); `ret_1` é o retorno de uma barra da barra atual. Extensão
    prévia de alta (`ret_h_prior>0`) seguida de barra atual que reverte
    (`ret_1<0`): produto `sign(ret_h_prior)×ret_1` negativo → com o `-` na
    frente, sinal POSITIVO = rejeição/falha de continuação detectada.
    Extensão confirmada (mesmo sinal): sinal negativo = continuação, não
    rejeição. Causal por construção: `ret_h_prior` usa só dado até `t-1`
    (deslocado em `build.py` antes de chegar aqui), `ret_1`/`atr_20_pct`
    usam só dado até `t` — nenhum índice >= `t+1` em nenhum dos dois."""
    with np.errstate(divide="ignore", invalid="ignore"):
        out: FloatArray = -np.sign(ret_h_prior) * ret_1 / atr_20_pct
    return out


def b15_efficiency_ratio_h3(close: FloatArray, window: int) -> FloatArray:
    """`|C_t - C_{t-window}| / Σ|C_i - C_{i-1}|` — mesmo núcleo de B07/B08
    (`support.efficiency_ratio`), janela medida (`H`). **[NOVO,
    2026-08-28, `AG-372`/ADR-006]** Kaufman's Efficiency Ratio na escala
    do holding period real: mede se o movimento que o trade de fato
    captura foi "reto" (tendência limpa, consistência direcional alta) ou
    "ruidoso" (zigue-zague), não um regime mais lento (B07=48, B08=16)."""
    return support.efficiency_ratio(close, window)


# ============================================================================
# Lote D2 (2026-08-28, `AG-372`/ADR-006, validação da especificação de Candle
# Features proposta pelo usuário) -- B16-B18: dinâmica de range/corpo entre
# barras consecutivas e "engolfo" normalizado por ATR. Todas T1 por decisão
# direta do Manager -- mesmo default imediato das anteriores.
# ============================================================================


def b16_log_range_ratio_1(high: FloatArray, low: FloatArray, lag_bars: int) -> FloatArray:
    """`ln(Range_t / Range_{t-lag_bars})`, `Range_t = H_t - L_t` — **[NOVO,
    2026-08-28, `AG-372`/ADR-006]** expansão/compressão de range em 1
    barra (lag=1, a mediana exata de `H`) — diferente de C06/C10/C11
    (suavizados 12/96 barras). `Range_t<=0` ou `Range_{t-lag_bars}<=0`
    (barra flat, achado de `/audit_engineering`: guardado desde a
    implementação, não descoberto depois) produz `NaN`."""
    range_ = high - low
    n = range_.shape[0]
    range_prev = np.full(n, np.nan, dtype=np.float64)
    if n > lag_bars:
        range_prev[lag_bars:] = range_[:-lag_bars]
    with np.errstate(divide="ignore", invalid="ignore"):
        out: FloatArray = np.where(
            (range_ > 0.0) & (range_prev > 0.0), np.log(range_ / range_prev), np.nan
        )
    return out


def b17_directional_pressure_h3(open_: FloatArray, close: FloatArray, window: int) -> FloatArray:
    """`Σbody_i / Σ|body_i|` sobre `window` barras, `body_i = C_i - O_i`
    — **[NOVO, 2026-08-28, `AG-372`/ADR-006]** pressão direcional via
    CORPO (open→close intra-barra), diferente de B15 (via close-a-close
    entre barras) — mesma janela=3 (H medido), ângulo de medição
    genuinamente distinto. `Σ|body_i|=0` só se as 3 barras tiverem corpo
    exatamente zero (doji triplo) — guardado, produz `NaN`."""
    body = close - open_
    body_abs = np.abs(body)
    num = pl.Series(body).rolling_sum(window_size=window, min_samples=window).to_numpy()
    denom = pl.Series(body_abs).rolling_sum(window_size=window, min_samples=window).to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        out: FloatArray = np.where(denom > 0.0, num / denom, np.nan)
    return out


def b18_engulfing_atr(open_: FloatArray, close: FloatArray, atr_20_abs: FloatArray) -> FloatArray:
    """`-sign(body_atr_{t-1}) × body_atr_t`, `body_atr = (C-O)/ATR_20`
    — **[NOVO, 2026-08-28, `AG-372`/ADR-006]** "engolfo" contínuo,
    normalizado por ATR (não pelo range da própria barra — comparável
    ENTRE barras, diferente de A07 que é intra-barra). Barra `t-1` de
    baixa seguida de `t` de alta com corpo maior (em unidades de ATR) →
    sinal positivo grande (reversão/engolfo real); mesma direção → sinal
    negativo (continuação). Sob dollar bar, comparar corpo entre barras
    consecutivas é comparar "agressão por unidade de turnover" — as duas
    barras têm ~o mesmo quantum de dólar negociado (`AG-321`), então a
    diferença de tamanho de corpo já é diferença pura de eficácia
    direcional, não confundida por volume desigual (o problema que essa
    comparação teria sob barra de relógio). Causal: `body_atr_{t-1}` usa
    só dado até `t-1`; `body_atr_t` usa só dado até `t`."""
    with np.errstate(divide="ignore", invalid="ignore"):
        body_atr: FloatArray = (close - open_) / atr_20_abs
    n = body_atr.shape[0]
    body_atr_prior = np.full(n, np.nan, dtype=np.float64)
    if n > 1:
        body_atr_prior[1:] = body_atr[:-1]
    out: FloatArray = -np.sign(body_atr_prior) * body_atr
    return out


# ============================================================================
# Lote B da liberação de features (H5, 2026-08-24) — B10, única do grupo B
# nesta leva (precisa de primitiva nova: mínimo/máximo rolante).
# ============================================================================


def b10_stoch_k_14(high: FloatArray, low: FloatArray, close: FloatArray, window: int) -> FloatArray:
    """`(C - min(L)_window) / (max(H)_window - min(L)_window) × 100` —
    §2.3 B10 (Stochastic %K padrão, George Lane, validado via pesquisa
    web). Janela rolante fixa (a barra `t` entra na própria janela —
    `min(L)`/`max(H)` incluem `L_t`/`H_t`, B02 não se aplica).
    `min`/`max` rolantes via `polars.rolling_min`/`rolling_max`
    diretamente — mesmo padrão de uso direto de primitiva polars já
    presente no módulo (`rolling_median` em D02f/D04f), não precisa de
    wrapper novo em `support.py`. `range_=0` (preço flat na janela
    inteira, caso degenerado raro) produz `NaN` via `errstate` — o PRD
    não declara uma convenção pra esse caso (diferente de A07-A10, que
    declaram "0 se H=L" explicitamente), então nenhuma é inventada
    aqui."""
    lowest_low = pl.Series(low).rolling_min(window_size=window, min_samples=window).to_numpy()
    highest_high = pl.Series(high).rolling_max(window_size=window, min_samples=window).to_numpy()
    pct_scale = 100.0  # noqa: magic-number -- escala percentual padrão do Stochastic %K, definicional (mesma classe do 50.0/100.0 de rsi_wilder), não hiperparâmetro
    with np.errstate(divide="ignore", invalid="ignore"):
        out: FloatArray = (close - lowest_low) / (highest_high - lowest_low) * pct_scale
    return out
