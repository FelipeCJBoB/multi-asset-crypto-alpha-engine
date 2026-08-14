"""Barras alternativas a partir de `aggTrades` (PRD_V4_1.md §3.2 M2): dollar
bars, volume bars, tick imbalance bars — candidatas contra o baseline
`resample.resample_klines` (barra de tempo). Constrói bars trade-a-trade
real, não a partir de `klines_1m` (que já É uma agregação temporal — usar
klines pra medir "a barra de tempo é pior que outra coisa" seria circular).

**Causalidade.** Toda função aqui só usa informação de trades com
`transact_time <= t` da barra em construção — nenhuma olha para frente.
Para dollar/volume bars isso é por construção: `bar_id = floor(cumsum/
threshold)` é monotonicamente não-decrescente em `transact_time` (preço×
quantidade e quantidade são sempre >= 0), então o `bar_id` de um trade
nunca depende de trades futuros. Para tick imbalance bars, a EWMA do
imbalance por tick (`ewm_mean`, polars, causal por definição — pondera só
o passado) e o `exp_num_ticks` (atualizado só quando uma barra FECHA, com
o tamanho dessa própria barra já completa) seguem a mesma disciplina.

**Tick imbalance bars — fonte do sinal de direção.** `b_t` usa
`is_buyer_maker` DIRETO (mapeamento: `is_buyer_maker=True` → comprador é
maker → agressor vendeu → `b_t=-1`; `is_buyer_maker=False` → agressor
comprou → `b_t=+1`), não o "tick rule" clássico do AFML (comparar preço
consecutivo). Pesquisa web feita antes de implementar (commit da mesma
rodada) confirmou: quando o rótulo real do agressor já vem no dado bruto
(caso da Binance), ele é estritamente superior ao tick rule, que foi
desenhado como PROXY para mercados sem esse campo — usar o proxy quando
o rótulo real existe introduziria erro sistemático desnecessário (Ma &
Zhai 2021 mediram ~77% de acurácia do tick rule em Bitcoin, não ~90%).

**Warm-up.** `exp_num_ticks` começa em `config.exp_num_ticks_init`
(calibrado pelo chamador — ver `m2_bar_comparison.py` — para a mesma
frequência média do baseline, não um número universal fabricado) —
`theta` parte de zero e precisa acumular até esse patamar antes da
primeira barra fechar, o que já implementa o "warm-up" descrito na
literatura sem precisar de um estado especial de bootstrap.

**Instabilidade conhecida, mitigada por construção.** A literatura de
referência (mlfinlab) documenta que `E_0[T]` pode "explodir" sem limite
via EWMA sem clipping — `config.exp_num_ticks_min/max` (derivados de
`bars_tick_imbalance_clip_multiplier` em `constants.yaml`) implementam a
correção padrão de facto, não uma correção nova.

**Performance.** `tick_imbalance_bars` é sequencial por construção (o
limiar de fechamento de cada barra depende do tamanho da barra anterior)
— não vetorizável como dollar/volume bars. Para a história completa de um
ativo (dezenas de milhões de trades), um loop Python é o gargalo esperado
da literatura de referência (mesma característica do `mlfinlab`), não algo
que este módulo tenta resolver com uma dependência nova (`numba` etc.).
Ponto de entrada manual (M2), não código de produção em tempo real."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import polars as pl
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]

_TRADE_REQUIRED_COLUMNS: tuple[str, ...] = (
    "transact_time",
    "price",
    "quantity",
    "is_buyer_maker",
)


def _require_trade_columns(trades: pl.DataFrame) -> None:
    missing = [c for c in _TRADE_REQUIRED_COLUMNS if c not in trades.columns]
    if missing:
        raise ValueError(f"trades sem coluna(s) obrigatória(s) {missing} (schema AGG_TRADES)")


def _aggregate_bars(trades: pl.DataFrame, bar_id: pl.Series | IntArray) -> pl.DataFrame:
    """Núcleo comum de agregação OHLCV -- mesma convenção de coluna de
    `resample.resample_klines` (`open_time/open/high/low/close/volume/
    close_time/quote_volume/count/taker_buy_volume/taker_buy_quote_volume`),
    pra que o baseline e as barras alternativas fiquem comparáveis sem
    remapear nomes de coluna em `m2_bar_comparison.py`. `is_buyer_maker=False`
    é trade agredido por comprador -- mesma convenção de "taker buy" das
    klines da Binance."""
    df = trades.with_columns(
        pl.Series("_bar_id", bar_id, dtype=pl.Int64),
        (pl.col("price") * pl.col("quantity")).alias("_value"),
    )
    taker_buy_mask = ~pl.col("is_buyer_maker")
    agg = (
        df.group_by("_bar_id", maintain_order=True)
        .agg(
            open_time=pl.col("transact_time").first(),
            close_time=pl.col("transact_time").last(),
            open=pl.col("price").first(),
            high=pl.col("price").max(),
            low=pl.col("price").min(),
            close=pl.col("price").last(),
            volume=pl.col("quantity").sum(),
            quote_volume=pl.col("_value").sum(),
            count=pl.len(),
            taker_buy_volume=pl.col("quantity").filter(taker_buy_mask).sum(),
            taker_buy_quote_volume=pl.col("_value").filter(taker_buy_mask).sum(),
        )
        .drop("_bar_id")
    )
    return agg


def dollar_bars(trades: pl.DataFrame, *, threshold: float) -> pl.DataFrame:
    """Fecha uma barra a cada `threshold` de volume em dólar (`price ×
    quantity`) acumulado desde a última barra. `threshold` é calibrado pelo
    chamador (`m2_bar_comparison.py`) para a mesma frequência média do
    baseline -- não fabricado aqui."""
    _require_trade_columns(trades)
    if threshold <= 0:
        raise ValueError(f"threshold precisa ser > 0, recebido {threshold}")
    if trades.is_empty():
        return _aggregate_bars(trades, np.empty(0, dtype=np.int64))

    value = (trades["price"] * trades["quantity"]).cum_sum()
    bar_id = (value // threshold).cast(pl.Int64)
    return _aggregate_bars(trades, bar_id)


def volume_bars(trades: pl.DataFrame, *, threshold: float) -> pl.DataFrame:
    """Mesma lógica de `dollar_bars`, mas acumulando `quantity` (unidades do
    ativo), não valor em dólar."""
    _require_trade_columns(trades)
    if threshold <= 0:
        raise ValueError(f"threshold precisa ser > 0, recebido {threshold}")
    if trades.is_empty():
        return _aggregate_bars(trades, np.empty(0, dtype=np.int64))

    cum_volume = trades["quantity"].cum_sum()
    bar_id = (cum_volume // threshold).cast(pl.Int64)
    return _aggregate_bars(trades, bar_id)


@dataclass(frozen=True, slots=True)
class TickImbalanceBarsConfig:
    """Hiperparâmetros de TIB (AFML cap.2, PRD_V4_1.md §3.2 M2) -- ver
    docstring do módulo e `constants.yaml::bars_tick_imbalance_*` pra
    proveniência. `exp_num_ticks_init`/`exp_num_ticks_min`/
    `exp_num_ticks_max` são específicos do ativo (calibrados pelo
    chamador), não constantes globais."""

    num_prev_bars: int
    expected_imbalance_window: int
    exp_num_ticks_init: float
    exp_num_ticks_min: float
    exp_num_ticks_max: float


def tick_imbalance_bars(trades: pl.DataFrame, config: TickImbalanceBarsConfig) -> pl.DataFrame:
    """AFML cap.2: fecha uma barra quando `|theta_T| >= E_0[T] * |EWMA(b_t)|`,
    `theta_T = soma acumulada de b_t` desde a última barra, `b_t` derivado de
    `is_buyer_maker` (ver docstring do módulo). `E_0[T]` (`exp_num_ticks`) é
    atualizado por EWMA (`span=num_prev_bars`) só quando uma barra fecha, com
    o tamanho dessa própria barra -- nunca olha pra dentro da barra em
    construção (causal). Sequencial por construção -- ver "Performance" na
    docstring do módulo."""
    _require_trade_columns(trades)
    if config.num_prev_bars <= 0:
        raise ValueError(f"num_prev_bars precisa ser > 0, recebido {config.num_prev_bars}")
    if config.expected_imbalance_window <= 0:
        raise ValueError(
            "expected_imbalance_window precisa ser > 0, recebido "
            f"{config.expected_imbalance_window}"
        )
    if config.exp_num_ticks_init <= 0:
        raise ValueError(
            f"exp_num_ticks_init precisa ser > 0, recebido {config.exp_num_ticks_init}"
        )
    n = trades.height
    if n == 0:
        return _aggregate_bars(trades, np.empty(0, dtype=np.int64))

    is_buyer_maker = trades["is_buyer_maker"].to_numpy()
    b: FloatArray = np.where(is_buyer_maker, -1.0, 1.0)

    ewma_b: FloatArray = (
        pl.Series("_b", b)
        .ewm_mean(span=config.expected_imbalance_window, adjust=False)
        .to_numpy()
    )

    bar_id: IntArray = np.empty(n, dtype=np.int64)
    # num_prev_bars > 0 garantido pelo raise acima -- denominador sempre >= 2.
    alpha = 2.0 / (config.num_prev_bars + 1.0)  # noqa: unguarded-ratio
    exp_num_ticks = float(config.exp_num_ticks_init)
    theta = 0.0
    ticks_in_bar = 0
    current_bar = 0

    for i in range(n):
        theta += float(b[i])
        ticks_in_bar += 1
        bar_id[i] = current_bar

        threshold = exp_num_ticks * abs(float(ewma_b[i]))
        if threshold > 0.0 and abs(theta) >= threshold:
            exp_num_ticks = alpha * ticks_in_bar + (1.0 - alpha) * exp_num_ticks
            exp_num_ticks = min(
                max(exp_num_ticks, config.exp_num_ticks_min), config.exp_num_ticks_max
            )
            current_bar += 1
            ticks_in_bar = 0
            theta = 0.0

    return _aggregate_bars(trades, bar_id)
