"""Primitivas causais compartilhadas por vários grupos de features (§2.0
princípios 2 e 4 — causalidade e normalização causal).

Tudo aqui opera sobre `numpy.ndarray` 1D (já extraído de uma coluna
polars pelo chamador) e devolve `numpy.ndarray` do mesmo comprimento, com
NaN onde o warmup individual daquela quantidade ainda não completou. O
warmup UNIFORME de `min_warmup_bars` (§2.15 invariante 5) é aplicado
depois, em `build.py`, sobre o vetor T1 inteiro — as funções aqui não
conhecem essa constante.

Duas famílias de janela, deliberadamente distintas (banned pattern B02):

* **Janela rolante fixa** (ATR, EMA, RSI, realized_vol, z-score rolante de
  D06f/E10f): a barra `t` pode entrar na sua própria janela — ela é
  informação disponível em `t`, não do futuro. `polars.rolling_*` já é
  causal por construção (janela sempre para trás, nunca centrada).
* **Janela expansiva estrita** (C07, D03f, E02f): o quantil/z-score em `t`
  usa só índices `< t`, nunca `t` — é a definição literal do banned
  pattern B02 e a razão de essas três funções existirem separadas das
  acima.

`expanding_zscore_strict`/`expanding_percentile_rank_strict` aceitam
`min_common_history_bars` opcional (AG-030, T0.5 — comparabilidade
cross-asset: BTC acumula ~231.552 barras de 15m desde `SYMBOL_START_DATE`,
os 4 alts só ~164.256 — o MESMO valor bruto produzia posto/z-score
estruturalmente diferente por ativo, dependendo só de quanto histórico
aquele ativo já tinha, não de vazamento temporal). Quando informado, os
primeiros `len(values) - min_common_history_bars` pontos da série são
excluídos da distribuição/estado de referência (saem como NaN) e o cálculo
expansivo recomeça no primeiro índice retido — Opção A do AG-030 (truncar o
INÍCIO da série pro mesmo nº de barras acumuladas), não Opção B (rolling de
tamanho fixo): a semântica continua "expansiva desde o início", só o
"início" de cada ativo passa a ser redefinido para o mesmo ponto relativo
de história acumulada. `None` (default) preserva bit-exato o comportamento
anterior a esta constante existir.
"""

from __future__ import annotations

import numpy as np
import polars as pl
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]


def true_range(high: FloatArray, low: FloatArray, close: FloatArray) -> FloatArray:
    """`TR_t = max(H_t-L_t, |H_t-C_{t-1}|, |L_t-C_{t-1}|)`. No primeiro
    índice não existe `C_{t-1}` — só `H-L` é definido ali (convenção comum
    de TR; o primeiro valor nunca sobrevive ao warmup de qualquer janela
    que o consuma, então a escolha não afeta nenhum resultado reportado)."""
    n = high.shape[0]
    tr = np.full(n, np.nan, dtype=np.float64)
    if n == 0:
        return tr
    tr[0] = high[0] - low[0]
    if n == 1:
        return tr
    prev_close = close[:-1]
    hi = high[1:]
    lo = low[1:]
    tr[1:] = np.maximum(hi - lo, np.maximum(np.abs(hi - prev_close), np.abs(lo - prev_close)))
    return tr


def _first_valid_index(values: FloatArray) -> int:
    n = values.shape[0]
    i = 0
    while i < n and np.isnan(values[i]):
        i += 1
    return i


def wilder_smooth(values: FloatArray, window: int) -> FloatArray:
    """Suavização de Wilder (usada por ATR e RSI): seed = média simples dos
    primeiros `window` valores válidos a partir do primeiro índice não-NaN
    de `values`; depois recursivo:

        out[t] = (out[t-1] * (window - 1) + values[t]) / window

    Índices antes do seed ficam NaN. Implementado com laço explícito em vez
    de `ewm_mean` porque o seed de Wilder é a MÉDIA SIMPLES da primeira
    janela, não o primeiro valor bruto — `ewm_mean(adjust=False)` seed do
    primeiro ponto é uma definição diferente (convergem assintoticamente,
    mas não são bit-idênticas, e a feature registrada como "ATR de Wilder"
    precisa ser a definição literal, não uma aproximação)."""
    n = values.shape[0]
    out = np.full(n, np.nan, dtype=np.float64)
    first_valid = _first_valid_index(values)
    seed_idx = first_valid + window - 1
    if seed_idx >= n:
        return out
    seed = float(np.mean(values[first_valid : first_valid + window]))
    out[seed_idx] = seed
    prev = seed
    for t in range(seed_idx + 1, n):
        v = values[t]
        if np.isnan(v):
            out[t] = np.nan
            continue
        prev = (prev * (window - 1) + v) / window
        out[t] = prev
    return out


def atr_wilder(high: FloatArray, low: FloatArray, close: FloatArray, window: int) -> FloatArray:
    """ATR de Wilder, absoluto (unidade de preço) — §2.4 C01."""
    tr = true_range(high, low, close)
    return wilder_smooth(tr, window)


def ema(values: FloatArray, span: int) -> FloatArray:
    """EMA padrão (`alpha = 2/(span+1)`, `adjust=False`), seed no primeiro
    valor da série. Não usa o seed-SMA de Wilder — EMA e ATR de Wilder são
    convenções distintas mesmo quando ambas "suavizações exponenciais"; a
    diferença de seed é irrelevante aqui porque `min_warmup_bars` (2000) é
    ordens de magnitude maior que qualquer `span` usado em T1 (48), e o
    peso do seed decai como `(1-alpha)^n` — já é desprezível muito antes
    da barra 2000."""
    s = pl.Series(values)
    alpha = 2.0 / (span + 1)
    out: FloatArray = s.ewm_mean(alpha=alpha, adjust=False, min_samples=span).to_numpy()
    return out


def rsi_wilder(close: FloatArray, window: int) -> FloatArray:
    """RSI de Wilder, escala nativa [0, 100] — §2.3 B01. Ganhos/perdas
    suavizados por `wilder_smooth`, não por média rolante simples (é
    exatamente a diferença entre "RSI de Wilder" e outras variantes de
    RSI que usam SMA)."""
    n = close.shape[0]
    delta = np.full(n, np.nan, dtype=np.float64)
    if n > 1:
        delta[1:] = np.diff(close)
    gain = np.where(np.isnan(delta), np.nan, np.where(delta > 0, delta, 0.0))
    loss = np.where(np.isnan(delta), np.nan, np.where(delta < 0, -delta, 0.0))

    avg_gain = wilder_smooth(gain, window)
    avg_loss = wilder_smooth(loss, window)

    with np.errstate(divide="ignore", invalid="ignore"):
        rs = avg_gain / avg_loss
        rsi = 100.0 - 100.0 / (1.0 + rs)  # escala fixa do RSI [noqa: magic-number]

    zero_loss_trending = (avg_loss == 0) & (avg_gain > 0)
    rsi[zero_loss_trending] = 100.0  # teto da escala do RSI [noqa: magic-number]
    flat = (avg_loss == 0) & (avg_gain == 0)
    rsi[flat] = 50.0  # ponto neutro da escala do RSI, sem movimento no período [noqa: magic-number]
    return rsi


def parkinson_vol(high: FloatArray, low: FloatArray, window: int) -> FloatArray:
    """Estimador de Parkinson (1980) — PRD_V4_1.md §3.2 M1, um dos 6
    candidatos de `VolatilityEstimator`. `sigma_P,t^2 = mean_window(ln(H/L)^2)
    / (4*ln2)`; retorna `sigma_P,t` (raiz), fração do preço, mesma escala
    de `atr_wilder(...)/close`. Janela rolante fixa — a barra `t` entra na
    própria janela (mesma família de `atr_wilder`/`realized_vol`, B02 não
    se aplica). `low <= 0` (dado corrompido, nunca visto em preço cripto
    real mas sem garantia estrutural) vira NaN silencioso via `errstate`
    em vez de `RuntimeWarning` não suprimido -- mesma disciplina aplicada
    a todo log-ratio de preço neste módulo (`yang_zhang_vol`/log_return
    de `E27f`/etc., achado F2 do audit_engineering, 2026-08-11)."""
    with np.errstate(divide="ignore", invalid="ignore"):
        log_hl_sq = np.log(high / low) ** 2  # noqa: unguarded-ratio -- preço real (low), sempre >0 por construção, ver docstring
    mean_sq = (
        pl.Series(log_hl_sq).rolling_mean(window_size=window, min_samples=window).to_numpy()
    )
    var = mean_sq / (4.0 * np.log(2.0))  # noqa: unguarded-ratio -- denominador é constante numérica (4*ln2), falso positivo do heurístico AST (não reconhece BinOp/Call como literal) # noqa: magic-number -- constante de fórmula fechada da literatura (Parkinson 1980), mesma classe de garman_klass_vol
    with np.errstate(invalid="ignore"):
        out: FloatArray = np.sqrt(var)
    return out


def garman_klass_vol(
    high: FloatArray, low: FloatArray, open_: FloatArray, close: FloatArray, window: int
) -> FloatArray:
    """Estimador de Garman-Klass (1980) — PRD_V4_1.md §3.2 M1. Por barra:
    `gk_i = 0.5*ln(H_i/L_i)^2 - (2*ln2-1)*ln(C_i/O_i)^2`;
    `sigma_GK,t^2 = mean_window(gk_i)`, retorna a raiz (fração do preço).
    Janela rolante fixa, mesma convenção de `parkinson_vol`. Média da
    janela negativa (ruído numérico possível em janela curta com poucos
    candles de range quase nulo) vira NaN em vez de `sqrt` de número
    complexo silencioso. `low <= 0` ou `open_ <= 0` viram NaN via
    `errstate`, mesma disciplina de `parkinson_vol` (achado F2 do
    audit_engineering, 2026-08-11)."""
    with np.errstate(divide="ignore", invalid="ignore"):
        log_hl_sq = np.log(high / low) ** 2  # noqa: unguarded-ratio -- preço real (low), sempre >0 por construção, ver docstring
        log_co_sq = np.log(close / open_) ** 2  # noqa: unguarded-ratio -- preço real (open_), sempre >0 por construção, ver docstring
    gk = 0.5 * log_hl_sq - (2.0 * np.log(2.0) - 1.0) * log_co_sq
    mean_gk = pl.Series(gk).rolling_mean(window_size=window, min_samples=window).to_numpy()
    with np.errstate(invalid="ignore"):
        out: FloatArray = np.sqrt(np.where(mean_gk >= 0, mean_gk, np.nan))
    return out


def rogers_satchell_vol(
    high: FloatArray, low: FloatArray, open_: FloatArray, close: FloatArray, window: int
) -> FloatArray:
    """Estimador de Rogers-Satchell (1991) -- PRD_V4_1.md §3.2 M1 só declara
    6 candidatos (ATRWilder/EGARCH/HAR-RV/Parkinson/GarmanKlass/RealizedVol);
    este é extensão PÓS-M1 (decisão do Manager, 2026-08-11), não texto do
    PRD -- avalia se a família "fórmula fechada, sem drift zero" supera o
    vencedor de M1 (Garman-Klass). Por barra:
    `rs_i = ln(H_i/C_i)*ln(H_i/O_i) + ln(L_i/C_i)*ln(L_i/O_i)`;
    `sigma_RS,t^2 = mean_window(rs_i)`, retorna a raiz (fração do preço).
    Sem constante de escala (diferente de Parkinson/GK) -- `rs_i` já é
    proxy de variância não-enviesado por construção mesmo com drift não
    nulo (a limitação que Parkinson/GK carregam e RS resolve, Rogers &
    Satchell 1991). Janela rolante fixa, mesma convenção de
    `parkinson_vol`/`garman_klass_vol` -- a barra `t` entra na própria
    janela. Média da janela negativa (ruído numérico possível em janela
    curta) vira NaN em vez de `sqrt` de número complexo silencioso, e
    `high/low/open/close <= 0` viram NaN via `errstate` -- mesma
    disciplina de `parkinson_vol`/`garman_klass_vol` (achado F2 do
    audit_engineering, 2026-08-11, aplicado aqui desde a origem)."""
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = np.log(high / close) * np.log(high / open_) + np.log(low / close) * np.log(  # noqa: unguarded-ratio -- preços reais (close/open_), sempre >0 por construção, ver docstring
            low / open_  # noqa: unguarded-ratio -- preço real (open_), sempre >0 por construção, ver docstring
        )
    mean_rs = pl.Series(rs).rolling_mean(window_size=window, min_samples=window).to_numpy()
    with np.errstate(invalid="ignore"):
        out: FloatArray = np.sqrt(np.where(mean_rs >= 0, mean_rs, np.nan))
    return out


def yang_zhang_vol(
    high: FloatArray, low: FloatArray, open_: FloatArray, close: FloatArray, window: int
) -> FloatArray:
    """Estimador de Yang-Zhang (2000) -- mesmo status de extensão PÓS-M1 de
    `rogers_satchell_vol` (ver docstring acima), candidato por adicionar o
    componente overnight/gap que Garman-Klass ignora:

        overnight_i = ln(O_i / C_{i-1})   -- i>=1, exige 1 barra extra antes da janela
        oc_i        = ln(C_i / O_i)
        V_o,t  = variância amostral (ddof=1) de `overnight` na janela
        V_c,t  = variância amostral (ddof=1) de `oc` na janela
        V_rs,t = mean_window(rs_i)         -- mesmo termo de `rogers_satchell_vol`, sem a raiz
        k = 0.34 / (1.34 + (window+1)/(window-1))   -- Yang & Zhang (2000);
            peso que minimiza a variância do estimador combinado, NÃO o
            "k=0.34 fixo" citado em fontes secundárias simplificadas --
            0.34 é só o numerador da fórmula original, o peso real
            depende de `window` e converge a ~0,145 quando window->infinito
            (nunca a 0,34). `0.34`/`1.34` são constantes de fórmula da
            literatura (mesma classe de `4*ln2` em `parkinson_vol`/
            `2*ln2-1` em `garman_klass_vol`), não hiperparâmetro do
            projeto -- não entram em `constants.yaml` pelo mesmo motivo
            que as outras duas não entram.
        sigma_YZ,t^2 = V_o,t + k*V_c,t + (1-k)*V_rs,t

    Retorna a raiz (fração do preço). `overnight_i` exige `close[i-1]` --
    em cripto 24/7 isso é o gap ENTRE BARRAS consecutivas de kline
    contínuo (não sessão de bolsa tradicional; mesma adaptação que o
    HAR-RV retirado deste repo fazia pro seu "dia" em barras, commit
    3ceb5b7), tipicamente pequeno mas não garantido zero -- é justamente o que este
    candidato testa (hipótese: erro do GK concentrado em candles de
    abertura). Warmup de `window + 1` barras (1 barra extra pro primeiro
    overnight da janela) -- mesmo tipo de +1 que `next_bar_realized_
    variance` precisa por depender de `close[t+1]`. Soma dos 3 termos pode
    ficar negativa (mesma razão de
    `garman_klass_vol`: `V_rs,t` isolado pode ser negativo numa janela
    ruidosa) -- vira NaN em vez de `sqrt` de número complexo, mesma
    disciplina das outras duas."""
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = np.log(high / close) * np.log(high / open_) + np.log(low / close) * np.log(
            low / open_
        )

    n = close.shape[0]
    overnight = np.full(n, np.nan, dtype=np.float64)
    if n > 1:
        with np.errstate(divide="ignore", invalid="ignore"):
            overnight[1:] = np.log(open_[1:] / close[:-1])
    with np.errstate(divide="ignore", invalid="ignore"):
        oc = np.log(close / open_)

    v_o = (
        pl.Series(overnight).rolling_std(window_size=window, min_samples=window, ddof=1).to_numpy()
        ** 2
    )
    v_c = (
        pl.Series(oc).rolling_std(window_size=window, min_samples=window, ddof=1).to_numpy() ** 2
    )
    v_rs = pl.Series(rs).rolling_mean(window_size=window, min_samples=window).to_numpy()

    k = 0.34 / (1.34 + (window + 1) / (window - 1))  # noqa: magic-number -- constante de fórmula fechada da literatura (Yang-Zhang 2000), mesma classe de garman_klass_vol; ver derivação completa na docstring acima
    sigma_sq = v_o + k * v_c + (1.0 - k) * v_rs
    with np.errstate(invalid="ignore"):
        out: FloatArray = np.sqrt(np.where(sigma_sq >= 0, sigma_sq, np.nan))
    return out


def realized_vol(log_return: FloatArray, window: int) -> FloatArray:
    """`σ(log_return) × √window` sobre janela rolante de `window` barras,
    incluindo a barra atual (§2.4 C03) — janela rolante fixa, não
    expansiva, então B02 não se aplica (a barra `t` pode estar na sua
    própria janela)."""
    s = pl.Series(log_return)
    std = s.rolling_std(window_size=window, min_samples=window, ddof=1).to_numpy()
    out: FloatArray = std * np.sqrt(window)
    return out


def downside_deviation(log_return: FloatArray, window: int) -> FloatArray:
    """Semi-desvio -- raiz da média dos quadrados dos retornos NEGATIVOS
    na janela (retorno positivo conta como 0, não é descartado da
    janela) -- mesma convenção de janela rolante fixa de `realized_vol`
    (inclui a barra atual, B02 não se aplica). AG-119 (`audit/
    architecture_gaps_log.yaml`) -- feature usada na literatura de Jump
    Model (Nystrup/Shu/Kolm/Mulvey) e ausente do espaço de observação
    estreito (`log_return_1`/`realized_vol_short`) que `AG-117` testou;
    reteste do candidato Jump Model consome esta função diretamente,
    fora do Feature Engine de produção (não wired em `build_t1_
    features` -- uso hoje é só diagnóstico/pesquisa).

    **Achado real (AG-119, 2026-08-20, achado ao rodar o reteste sobre
    XRPUSDT):** `mean_sq` é matematicamente uma média de quadrados --
    nunca pode ser negativa -- mas `rolling_mean` sobre `window` barras
    quase todas com retorno positivo (poucos/nenhum retorno negativo na
    janela, comum em séries reais de dollar-bar) produz valores como
    `-3,16e-20` por cancelamento de ponto flutuante, não por qualquer
    coisa real sobre o dado. `np.sqrt` de um negativo (mesmo artefato de
    ULP) devolve `NaN` SILENCIOSO, sem warning -- 30 barras afetadas em
    163.765 de XRPUSDT (R1), zero em BTCUSDT/ETHUSDT/SOLUSDT/BNBUSDT
    nesta mesma checagem. `np.maximum(mean_sq, 0.0)` antes do `sqrt`
    corrige a CAUSA (interpretação matematicamente correta de "média de
    quadrados não pode ser negativa"), não um filtro de sintoma por
    cima."""
    downside_sq = np.minimum(log_return, 0.0) ** 2
    s = pl.Series(downside_sq)
    mean_sq = s.rolling_mean(window_size=window, min_samples=window).to_numpy()
    out: FloatArray = np.sqrt(np.maximum(mean_sq, 0.0))
    return out


def rolling_zscore(values: FloatArray, window: int) -> FloatArray:
    """Z-score sobre janela rolante fixa de `window` barras, incluindo a
    barra atual (D06f, E10f — o PRD declara lookback fixo "48" para essas
    duas, não "expansiva"; ver banned pattern B02 na docstring do módulo
    para a distinção)."""
    s = pl.Series(values)
    mean = s.rolling_mean(window_size=window, min_samples=window).to_numpy()
    std = s.rolling_std(window_size=window, min_samples=window, ddof=1).to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        out: FloatArray = (values - mean) / std
    return out


def efficiency_ratio(close: FloatArray, window: int) -> FloatArray:
    """`|C_t - C_{t-window}| / Σ_{i=t-window+1}^{t} |C_i - C_{i-1}|` — §2.3
    B07. Janela rolante fixa (inclui a barra atual no numerador e no
    denominador)."""
    n = close.shape[0]
    abs_diff = np.full(n, np.nan, dtype=np.float64)
    if n > 1:
        abs_diff[1:] = np.abs(np.diff(close))
    rolling_sum = pl.Series(abs_diff).rolling_sum(window_size=window, min_samples=window).to_numpy()

    numerator = np.full(n, np.nan, dtype=np.float64)
    if n > window:
        numerator[window:] = np.abs(close[window:] - close[:-window])

    with np.errstate(divide="ignore", invalid="ignore"):
        out: FloatArray = numerator / rolling_sum
    return out


def expanding_zscore_strict(
    values: FloatArray, *, min_common_history_bars: int | None = None
) -> FloatArray:
    """Z-score em janela EXPANSIVA estrita: `z_t = (x_t - média_{<t}) /
    desvio_{<t}`, onde média/desvio usam só índices `< t` (banned pattern
    B02 — nunca `<= t`). Implementado com algoritmo online de Welford
    (O(n), um passe): calcula `z_t` a partir do estado acumulado ANTES de
    incorporar `x_t` ao estado, e só then atualiza o estado com `x_t`.

    Requer pelo menos 2 pontos prévios válidos para desvio amostral
    (`ddof=1`) definido — `out[0]` e `out[1]` são sempre NaN (contados a
    partir do início EFETIVO da série, ver `min_common_history_bars`
    abaixo).

    `min_common_history_bars` (AG-030, T0.5, Opção A — ver docstring do
    módulo): quando informado e `len(values) > min_common_history_bars`, os
    primeiros `len(values) - min_common_history_bars` índices ficam de fora
    do estado de Welford inteiramente (saem como NaN) e a acumulação
    recomeça (`count=0`) no primeiro índice retido — equivalente a chamar
    esta função só sobre `values[-min_common_history_bars:]` e colar o
    resultado de volta no comprimento original. Cada índice retido `t`
    continua usando exclusivamente índices retidos `< t` (subconjunto
    ESTRITO do `< t` original — nunca um superconjunto), então B02
    permanece satisfeito por construção; não é uma segunda forma de
    calcular o z-score, é a mesma primitiva com o ponto de partida
    deslocado. `None` (default) ou `len(values) <= min_common_history_bars`
    preservam bit-exato o comportamento sem o parâmetro (início em `t=0`)."""
    n = values.shape[0]
    offset = 0 if min_common_history_bars is None else max(0, n - min_common_history_bars)
    if offset == 0:
        return _expanding_zscore_strict_core(values)
    out = np.full(n, np.nan, dtype=np.float64)
    out[offset:] = _expanding_zscore_strict_core(values[offset:])
    return out


def _expanding_zscore_strict_core(values: FloatArray) -> FloatArray:
    """Corpo original (pré-AG-030) de `expanding_zscore_strict` — Welford
    O(n), expansivo desde o índice 0 de `values`. Extraído para função
    privada só para ser reaproveitado pelo wrapper de
    `min_common_history_bars` acima sem duplicar o algoritmo."""
    n = values.shape[0]
    out = np.full(n, np.nan, dtype=np.float64)
    count = 0
    mean = 0.0
    m2 = 0.0
    for t in range(n):
        x = values[t]
        if count >= 2:
            var = m2 / (count - 1)
            if var > 0:
                out[t] = (x - mean) / np.sqrt(var)
        if not np.isnan(x):
            count += 1
            delta = x - mean
            mean += delta / count
            delta2 = x - mean
            m2 += delta * delta2
    return out


def rolling_correlation(x: FloatArray, y: FloatArray, window: int) -> FloatArray:
    """Correlação de Pearson em janela ROLANTE fixa de `window` barras —
    D10f (§2.5). Janela rolante fixa, mesma família de `rolling_zscore`/
    `realized_vol` (a barra `t` entra na própria janela, B02 não se
    aplica). Fórmula fechada clássica via somas rolantes:
    `corr_t = (E[xy] - E[x]E[y]) / sqrt((E[x^2]-E[x]^2) * (E[y^2]-E[y]^2))`
    sobre `[t-window+1, t]` — mesma técnica de `polars.rolling_mean`
    encadeada já usada por `garman_klass_vol`/`rogers_satchell_vol` neste
    módulo, não um segundo algoritmo. `np.maximum(..., 0.0)` no produto de
    variâncias antes da raiz evita `NaN` de cancelamento de ponto
    flutuante levemente negativo (mesma disciplina de `downside_
    deviation`, achado AG-119) — correlação verdadeiramente indefinida
    (variância zero de fato) ainda produz `NaN` via `errstate`, só não por
    causa de ruído de ponto flutuante."""
    sx = pl.Series(x)
    sy = pl.Series(y)
    sxy = sx * sy
    sx2 = sx * sx
    sy2 = sy * sy
    mean_x = sx.rolling_mean(window_size=window, min_samples=window).to_numpy()
    mean_y = sy.rolling_mean(window_size=window, min_samples=window).to_numpy()
    mean_xy = sxy.rolling_mean(window_size=window, min_samples=window).to_numpy()
    mean_x2 = sx2.rolling_mean(window_size=window, min_samples=window).to_numpy()
    mean_y2 = sy2.rolling_mean(window_size=window, min_samples=window).to_numpy()

    cov = mean_xy - mean_x * mean_y
    var_x = mean_x2 - mean_x * mean_x
    var_y = mean_y2 - mean_y * mean_y
    denom = np.sqrt(np.maximum(var_x * var_y, 0.0))
    with np.errstate(divide="ignore", invalid="ignore"):
        out: FloatArray = cov / denom
    return out


def rolling_percentile_rank_strict(values: FloatArray, window: int) -> FloatArray:
    """Posto percentil em janela ROLANTE estrita de tamanho `window` — C08
    (§2.4, "idem [C07_vol_pctile_expanding], janela rolante de 1 ano"):
    `rank_t = #{i em [t-window, t-1] : x_i "<" x_t} / #{i em [t-window,
    t-1] não-NaN}` — mesma convenção de "nunca inclui `t`" de `expanding_
    percentile_rank_strict` (B02), só que a distribuição de referência é
    uma JANELA FINITA deslizante, não expansiva desde a origem do dataset.

    Implementado com a MESMA compressão de coordenadas + Fenwick tree de
    `expanding_percentile_rank_strict`, com uma diferença: elementos que
    saem da janela são REMOVIDOS da árvore (`_update(pos, -1)`), não só
    inseridos — Fenwick tree suporta delta negativo tão bem quanto
    positivo, não precisa de estrutura nova. A compressão de coordenadas
    (posto denso GLOBAL, calculado uma vez sobre a série inteira) é só um
    mapeamento ESTÁTICO valor->índice de árvore — não viola causalidade
    (B02): a consulta em `t` só enxerga o ESTADO da árvore naquele
    momento, que reflete exatamente `[t-window, t-1]`, nunca `t` nem além
    (prova por indução: a árvore só recebe `_update(+1)` do índice `t`
    IMEDIATAMENTE DEPOIS de `out[t]` já ter sido calculado, nunca antes)."""
    n = values.shape[0]
    out = np.full(n, np.nan, dtype=np.float64)
    finite_mask = ~np.isnan(values)
    idx_finite = np.flatnonzero(finite_mask)
    m = idx_finite.shape[0]
    if m == 0:
        return out

    vals_finite = values[idx_finite]
    order = np.argsort(vals_finite, kind="stable")
    dense_rank = np.empty(m, dtype=np.int64)
    dense_rank[order] = np.arange(m)
    dense_rank_by_idx = np.full(n, -1, dtype=np.int64)
    dense_rank_by_idx[idx_finite] = dense_rank

    tree = np.zeros(m + 1, dtype=np.int64)

    def _update(i: int, delta: int) -> None:
        i += 1
        while i <= m:
            tree[i] += delta
            i += i & (-i)

    def _query_prefix(i: int) -> int:
        s = 0
        while i > 0:
            s += int(tree[i])
            i -= i & (-i)
        return s

    count_in_window = 0
    for t in range(n):
        r_t = int(dense_rank_by_idx[t])
        if count_in_window > 0 and r_t >= 0:
            less = _query_prefix(r_t)
            out[t] = less / count_in_window
        if r_t >= 0:
            _update(r_t, 1)
            count_in_window += 1
        remove_idx = t - window
        if remove_idx >= 0:
            r_remove = int(dense_rank_by_idx[remove_idx])
            if r_remove >= 0:
                _update(r_remove, -1)
                count_in_window -= 1
    return out


def rolling_percentile_rank_strict_by_time(
    values: FloatArray, close_time_ms: FloatArray, window_ms: int
) -> FloatArray:
    """Posto percentil em janela ROLANTE de TEMPO fixo (`window_ms`), não
    de CONTAGEM de barras fixa — C08 (`AG-317`, correção 2026-08-27):
    `rank_t = #{i : close_time_ms[t] - close_time_ms[i] <= window_ms e
    close_time_ms[i] <= close_time_ms[t-1] : x_i "<" x_t} / #{...}`, mesma
    convenção de "nunca inclui `t`" de `rolling_percentile_rank_strict`
    (que esta função generaliza).

    **Por que existe, além de `rolling_percentile_rank_strict`:** sob
    `canonical_bar_type: dollar` (`AG-042`) a duração de barra é VARIÁVEL
    — uma janela de `N` barras fixas cobre um intervalo de calendário
    diferente conforme a grade (R1/R2/R3) e conforme o regime de volume
    (barra fecha mais rápido quando o volume sobe). `C08_vol_pctile_
    rolling_1y` promete no PRÓPRIO NOME "1 ano" — só uma janela ancorada
    em TEMPO cumpre essa promessa em qualquer grade; `outer_window` fixo
    em barras não cumpre (`AG-317`: 17.520 barras eram 114,7 dias em R1,
    500 dias em R3, nunca 365 em nenhuma).

    Mesma implementação de Fenwick tree + compressão de coordenadas de
    `rolling_percentile_rank_strict`, só a condição de REMOÇÃO da janela
    muda: em vez de `t - window` (offset fixo de barras), um ponteiro
    `left` avança enquanto `close_time_ms[t] - close_time_ms[left] >=
    window_ms` — a mesma prova de causalidade se aplica (a consulta em
    `t` só enxerga o estado da árvore refletindo `close_time_ms[i] >
    close_time_ms[t] - window_ms` e `i < t`, nunca `t` nem além, porque a
    remoção roda ANTES da consulta e a inserção de `t` roda DEPOIS)."""
    n = values.shape[0]
    out = np.full(n, np.nan, dtype=np.float64)
    finite_mask = ~np.isnan(values)
    idx_finite = np.flatnonzero(finite_mask)
    m = idx_finite.shape[0]
    if m == 0:
        return out

    vals_finite = values[idx_finite]
    order = np.argsort(vals_finite, kind="stable")
    dense_rank = np.empty(m, dtype=np.int64)
    dense_rank[order] = np.arange(m)
    dense_rank_by_idx = np.full(n, -1, dtype=np.int64)
    dense_rank_by_idx[idx_finite] = dense_rank

    tree = np.zeros(m + 1, dtype=np.int64)

    def _update(i: int, delta: int) -> None:
        i += 1
        while i <= m:
            tree[i] += delta
            i += i & (-i)

    def _query_prefix(i: int) -> int:
        s = 0
        while i > 0:
            s += int(tree[i])
            i -= i & (-i)
        return s

    close_time_int = close_time_ms.astype(np.int64)
    count_in_window = 0
    left = 0
    for t in range(n):
        while left < t and close_time_int[t] - close_time_int[left] > window_ms:
            r_remove = int(dense_rank_by_idx[left])
            if r_remove >= 0:
                _update(r_remove, -1)
                count_in_window -= 1
            left += 1
        r_t = int(dense_rank_by_idx[t])
        if count_in_window > 0 and r_t >= 0:
            less = _query_prefix(r_t)
            out[t] = less / count_in_window
        if r_t >= 0:
            _update(r_t, 1)
            count_in_window += 1
    return out


def expanding_percentile_rank_strict(
    values: FloatArray, *, min_common_history_bars: int | None = None
) -> FloatArray:
    """Posto percentil em janela EXPANSIVA estrita: `rank_t = #{i<t :
    x_i "<" x_t} / #{i<t : x_i não-NaN}` — só índices `< t` entram na
    distribuição de referência (B02), nunca `t` mesmo. `out[t]` é NaN se
    não houver nenhum ponto prévio não-NaN.

    Implementado com uma Fenwick tree (Binary Indexed Tree) sobre o posto
    denso GLOBAL dos valores não-NaN — O(n log n), necessário porque um
    laço O(n) por atualização (busca+inserção linear) degrada para O(n²) e
    fica proibitivo na série completa (~230 mil barras de 15m, §5.9).

    O `"<"` acima é entre aspas de propósito: empates (valores idênticos)
    são desfeitos por ordem de chegada via posto denso GLOBAL
    (`argsort(kind="stable")` sobre a série inteira de valores não-NaN,
    calculado uma vez no início) — entre dois valores idênticos, o que
    ocorre mais cedo na série recebe posto denso menor e por isso conta
    como "menor" quando comparado a uma ocorrência posterior do mesmo
    valor, mesmo sendo numericamente igual. Não é a convenção de "mid-rank"
    (contar empate como metade) usada em algumas bibliotecas de estatística
    — é mais simples e totalmente determinística, o que importa mais aqui
    (§2.0 princípio 1). Em dado de mercado real (float64 de retorno/
    volatilidade) empates exatos são raríssimos, então o efeito da escolha
    é desprezível; documentado aqui para não ficar implícito.

    `min_common_history_bars` (AG-030, T0.5, Opção A — ver docstring do
    módulo): quando informado e `len(values) > min_common_history_bars`, os
    primeiros `len(values) - min_common_history_bars` índices ficam de fora
    da árvore de Fenwick inteiramente (saem como NaN) e a distribuição de
    referência recomeça vazia no primeiro índice retido — equivalente a
    chamar esta função só sobre `values[-min_common_history_bars:]` e colar
    o resultado de volta no comprimento original (inclusive o posto denso
    GLOBAL do desempate é recalculado só sobre essa sub-série, não sobre a
    série inteira original). Cada índice retido `t` continua usando
    exclusivamente índices retidos `< t` (subconjunto ESTRITO do `< t`
    original — nunca um superconjunto), então B02 permanece satisfeito por
    construção. `None` (default) ou `len(values) <= min_common_history_bars`
    preservam bit-exato o comportamento sem o parâmetro (início em `t=0`)."""
    n = values.shape[0]
    offset = 0 if min_common_history_bars is None else max(0, n - min_common_history_bars)
    if offset == 0:
        return _expanding_percentile_rank_strict_core(values)
    out = np.full(n, np.nan, dtype=np.float64)
    out[offset:] = _expanding_percentile_rank_strict_core(values[offset:])
    return out


def _expanding_percentile_rank_strict_core(values: FloatArray) -> FloatArray:
    """Corpo original (pré-AG-030) de `expanding_percentile_rank_strict` —
    Fenwick tree O(n log n), expansivo desde o índice 0 de `values`.
    Extraído para função privada só para ser reaproveitado pelo wrapper de
    `min_common_history_bars` acima sem duplicar o algoritmo."""
    n = values.shape[0]
    out = np.full(n, np.nan, dtype=np.float64)
    finite_mask = ~np.isnan(values)
    idx_finite = np.flatnonzero(finite_mask)
    m = idx_finite.shape[0]
    if m == 0:
        return out

    vals_finite = values[idx_finite]
    order = np.argsort(vals_finite, kind="stable")
    dense_rank = np.empty(m, dtype=np.int64)
    dense_rank[order] = np.arange(m)

    tree = np.zeros(m + 1, dtype=np.int64)

    def _update(i: int) -> None:
        i += 1
        while i <= m:
            tree[i] += 1
            i += i & (-i)

    def _query_prefix(i: int) -> int:
        """Soma de posições com posto denso em `[0, i)` já inseridas."""
        s = 0
        while i > 0:
            s += int(tree[i])
            i -= i & (-i)
        return s

    for k in range(m):
        r = int(dense_rank[k])
        t = int(idx_finite[k])
        if k > 0:  # k == número de pontos já inseridos (0-indexado) -- nenhum contador redundante
            less = _query_prefix(r)
            out[t] = less / k
        _update(r)
    return out
