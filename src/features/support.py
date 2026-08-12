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
        log_hl_sq = np.log(high / low) ** 2
    mean_sq = (
        pl.Series(log_hl_sq).rolling_mean(window_size=window, min_samples=window).to_numpy()
    )
    var = mean_sq / (4.0 * np.log(2.0))
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
        log_hl_sq = np.log(high / low) ** 2
        log_co_sq = np.log(close / open_) ** 2
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
        rs = np.log(high / close) * np.log(high / open_) + np.log(low / close) * np.log(
            low / open_
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
    variance` precisa por depender de `close[t+1]`. Soma dos 3 termos pode ficar negativa (mesma razão de
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

    k = 0.34 / (1.34 + (window + 1) / (window - 1))
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


def expanding_zscore_strict(values: FloatArray) -> FloatArray:
    """Z-score em janela EXPANSIVA estrita: `z_t = (x_t - média_{<t}) /
    desvio_{<t}`, onde média/desvio usam só índices `< t` (banned pattern
    B02 — nunca `<= t`). Implementado com algoritmo online de Welford
    (O(n), um passe): calcula `z_t` a partir do estado acumulado ANTES de
    incorporar `x_t` ao estado, e só then atualiza o estado com `x_t`.

    Requer pelo menos 2 pontos prévios válidos para desvio amostral
    (`ddof=1`) definido — `out[0]` e `out[1]` são sempre NaN."""
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


def expanding_percentile_rank_strict(values: FloatArray) -> FloatArray:
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
    é desprezível; documentado aqui para não ficar implícito."""
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
