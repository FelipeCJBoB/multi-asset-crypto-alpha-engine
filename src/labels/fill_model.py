"""Modelo de preenchimento SIMPLIFICADO da ordem limite de entrada (§3.3
`fill_model`, Sprint 6).

**Escopo explícito — o que isto NÃO é.** O simulador de fila completo
(bookTicker + aggTrades, calibrado contra fills reais observados em
Testnet/Paper) é **Sprint 9**, fora de escopo aqui. Este módulo não modela
fila (posição relativa das outras ordens no mesmo nível de preço), não
modela profundidade do book, não distingue um único trade de 0,001 BTC de
um movimento substancial de mercado no mesmo nível.

**O que isto É:** dado que uma ordem limite foi postada em `t_post` a
`limit_price`, percorre `mark_1m` de `t_post` (exclusive) até `horizon_ms`
(inclusive) — janela em relógio fixo, TF-agnóstica, definida pelo chamador
(hoje `LabelConfig.fill_timeout_ms`, ver `triple_barrier.py`, AG-042; a
prosa antiga desta docstring falava em "barras de 15m"/`fill_timeout_bars`,
terminologia de antes da migração — o campo não existe mais em
`LabelConfig`, o código abaixo sempre foi ms-agnóstico) — e considera a
ordem preenchida se o INTERVALO `[low, high]` de algum candle de 1m tocou
`limit_price` — não compara só contra `close`.

**ISTO SUPERESTIMA O FILL RATE REAL** — é um LIMITE SUPERIOR otimista, não
uma estimativa não-enviesada. Qualquer toque do intervalo `[low, high]` de
um candle de 1 minuto é tratado como preenchimento total e imediato ao
preço do limite (sem melhora nem piora de preço — `fill_price ==
limit_price` sempre que preenchido). É exatamente por isso que o Sprint 9
existe: calibrar `p_fill` real contra book/trades. A fração de `NOFILL`
medida com este modelo é um piso, não o número real (o real é maior).

**Schema de `mark_1m` — achado do Sprint 6, não presumido.** A task que
gerou este módulo levantou como hipótese a testar que `mark_1m` "provavelmente
só tem um valor por minuto, não OHLC" — FALSO, medido contra
`src/data/schemas.py::MARK_PRICE_KLINES_1M` e um parquet real
(`data/capacity/mark_price_klines_1m/BTCUSDT/2024-01-15.parquet`): é
klines-like completo (`open/high/low/close` como string decimal, casta para
`Float64` — mesmo schema de `klines_1m`; `open_time`/`close_time` epoch ms).
Isso permite usar `high`/`low` mesmo a 1 minuto de granularidade, mantendo
B11 satisfeito (nunca a barra de 15m) e aproveitando a granularidade real
disponível — não é preciso degradar para "toque contra `close` apenas".
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import polars as pl
from numpy.typing import NDArray

IntArray = NDArray[np.int64]
FloatArray = NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class FillResult:
    """`t_entry_ms` é `None` se a ordem nunca foi tocada dentro da janela de
    timeout — o desfecho `NOFILL` (§3.2, `label=-2`). `fill_price`, quando
    preenchido, é sempre igual a `limit_price` (nenhuma melhora de preço
    modelada — ver docstring do módulo)."""

    t_entry_ms: int | None
    fill_price: float | None


def simulate_fill_arrays(
    mark_open_time_ms: IntArray,
    mark_low: FloatArray,
    mark_high: FloatArray,
    *,
    t_post_ms: int,
    horizon_ms: int,
    limit_price: float,
    side: int,
) -> FillResult:
    """Núcleo numérico (sem IO, sem polars) — opera sobre arrays de
    `mark_1m` JÁ ORDENADOS por `open_time` (ordem cronológica real, B11).
    Usado diretamente pelo laço quente de `triple_barrier.build_labels`
    (que converte `mark_1m` para numpy UMA VEZ fora do laço, não por linha)
    e também pela versão de conveniência `simulate_fill` abaixo.

    Janela de busca: candles de 1m com `open_time` estritamente posterior a
    `t_post_ms` e até `horizon_ms` inclusive — ex.: `horizon_ms - t_post_ms
    = 900_000` (15 min) produz até 15 candles de 1m nessa janela.

    `side=1` (compra/long): preenche se `low <= limit_price` em algum
    candle da janela — o mark tocou ou cruzou o limite por baixo.
    `side=-1` (venda/short): preenche se `high >= limit_price` — o mark
    tocou ou cruzou o limite por cima.

    Retorna o PRIMEIRO candle (cronologicamente) que tocou o limite —
    `argmax` sobre um array booleano devolve o índice do primeiro `True`,
    que é exatamente "primeiro toque em ordem cronológica real"."""
    if side not in (1, -1):
        raise ValueError(f"side deve ser 1 (compra) ou -1 (venda), recebido {side}")
    if horizon_ms <= t_post_ms:
        raise ValueError(
            f"horizon_ms ({horizon_ms}) deve ser posterior a t_post_ms ({t_post_ms})"
        )

    lo = int(np.searchsorted(mark_open_time_ms, t_post_ms, side="right"))
    hi = int(np.searchsorted(mark_open_time_ms, horizon_ms, side="right"))
    if hi <= lo:
        return FillResult(None, None)

    window_low = mark_low[lo:hi]
    window_high = mark_high[lo:hi]

    touched = window_low <= limit_price if side == 1 else window_high >= limit_price
    if not bool(touched.any()):
        return FillResult(None, None)

    first_idx = lo + int(np.argmax(touched))
    return FillResult(t_entry_ms=int(mark_open_time_ms[first_idx]), fill_price=float(limit_price))


def simulate_fill(
    mark_1m: pl.DataFrame,
    *,
    t_post_ms: int,
    horizon_ms: int,
    limit_price: float,
    side: int,
) -> FillResult:
    """Wrapper de conveniência sobre polars — filtra `mark_1m` (colunas
    `open_time`/`low`/`high`, schema `MARK_PRICE_KLINES_1M`) para a janela
    de interesse e delega a `simulate_fill_arrays`.

    Uso recomendado: chamadas isoladas/testes. `triple_barrier.build_labels`
    NÃO chama esta versão por linha — mantém os arrays de `mark_1m`
    convertidos uma única vez fora do laço principal, porque uma conversão
    polars->numpy por trade seria proibitivamente cara sobre ~230 mil barras
    de 15m × 2 lados (§5.9)."""
    window = (
        mark_1m.filter((pl.col("open_time") > t_post_ms) & (pl.col("open_time") <= horizon_ms))
        .sort("open_time")
    )
    if window.is_empty():
        return FillResult(None, None)

    open_time = window["open_time"].cast(pl.Int64).to_numpy().astype(np.int64)
    low = window["low"].cast(pl.Float64).to_numpy()
    high = window["high"].cast(pl.Float64).to_numpy()
    return simulate_fill_arrays(
        open_time,
        low,
        high,
        t_post_ms=t_post_ms,
        horizon_ms=horizon_ms,
        limit_price=limit_price,
        side=side,
    )
