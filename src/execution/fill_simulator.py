"""Simulador de fila (§9.5, Sprint 9) — "o artefato de maior retorno do
projeto" (texto literal do PRD). Reconstrói posição de fila a partir de
`bookTicker` (topo do livro, tick-level) + `aggTrades` (execuções com lado
do agressor) para simular preenchimento de ordem limite honestamente, em vez
de assumir "limite tocado = preenchido" (a simplificação otimista do
Sprint 6, `src/labels/fill_model.py` — ver comparação de vieses abaixo).

**Fontes e janela — §9.5 v3.3, bloco `fill_model.sources_pre_2025_11_20`.**
Este módulo implementa EXATAMENTE esse bloco: `[bookTicker_tick, aggTrades]`,
válido só até 2025-11-19. `BOOK_TICKER_WINDOW_START`/`_END` abaixo são a
cobertura REAL medida de `data/raw/book_ticker/BTCUSDT/` (2023-05-16 a
2024-03-30 — 320 arquivos, ver `known_gaps.
d05_d08_d09_upstream_availability_shorter_than_prd_claims` em
`constants.yaml`), inteiramente ANTES da quebra RPI de 2025-11-20 — logo
esta janela específica é simulável honestamente, sem o problema de liquidez
oculta que o parágrafo seguinte documenta.

**Por que este simulador NÃO serve para depois de 2025-11-20 (aviso
explícito do §9.5 v3.3, repetido aqui em código, não só em prosa).** Desde
essa data existem ordens RPI (Retail Price Improvement) que casam apenas com
takers não-algorítmicos e NÃO aparecem em `bookTicker` nem em
`/fapi/v1/depth` — o par de fontes usado aqui descreve um book
sistematicamente incompleto a partir dali (fonte adicional exigida:
`rpiDepth_stream`, sem dump histórico, só coleta forward — ver F06 e
`known_gaps.microstructure_definition_break_2025_11_20`). `simulate_window`
levanta `ValueError` se `end >= RPI_BREAK_DATE`. Não é um limite
conservador escolhido por este módulo — é uma verificação de definição:
sem `rpiDepth`, "queue_ahead" simplesmente não é mais o que este código
calcula.

**Limitações do modelo simplificado — declaradas aqui, não escondidas:**

1. **Só topo do livro.** `bookTicker` só tem melhor bid/ask, não profundidade
   completa. `queue_ahead` é o volume observado NAQUELE nível no instante do
   post — não a posição real da nossa ordem dentro dele (assume-se o pior
   caso, fim da fila, FIFO estrito).
2. **Cancelamento NÃO modelado — decisão estrutural, não uma taxa
   calibrada.** Não há dado de cancelamento real disponível (não temos
   profundidade completa do livro, só o topo, §9.5 logic item 3 pede
   explicitamente para documentar isso). Em vez de inventar uma "taxa
   calibrada" que não foi calibrada (proibido pela task que gerou este
   módulo e pelo espírito da Regra Zero, CLAUDE.md), a fila só é decrementada
   por volume TAKER observado em `aggTrades` — nunca por cancelamento
   estimado. Efeito direto, documentado explicitamlente: `queue_ahead`
   esvazia mais devagar do que na realidade (parte da fila real cancela em
   vez de ser executada), então **o `p_fill` medido aqui é um LIMITE
   INFERIOR pessimista**. O Sprint 6 (`fill_model.py`) já documenta o
   oposto: "toque do intervalo [low, high] = preenchimento" é um LIMITE
   SUPERIOR otimista. Os dois módulos juntos formam um INTERVALO, não um
   ponto — o `p_fill` real (com cancelamento real, quando medido ao vivo em
   Testnet/Paper, §9.5.1) fica entre os dois.
3. **Sem melhora de preço.** Todo fill acontece exatamente em `limit_price`
   (o melhor bid/ask no instante do post) — nunca melhor, nunca pior.
4. **"Mesmo nível de preço"** é comparado com tolerância `tick_size/2` (não
   um novo parâmetro de negócio — `tick_size` é reusado de `constants.yaml`,
   já existente desde o Sprint 1) para absorver ruído de ponto flutuante na
   conversão Binance -> Parquet, não para modelar nenhuma folga de mercado.
5. **`calibration` do §9.5 NÃO está implementada** — ver
   `calibrate_against_real_fills` abaixo: assinatura e docstring já
   compatíveis com `method`/`metric`/`threshold` do §9.5, corpo levanta
   `NotImplementedError` explícito. Fills reais de Testnet/Paper só existem
   nos Sprints 15-16 (§14.3); fabricar um substituto aqui violaria a Regra
   Zero.

**Ambiguidades do PRD resolvidas neste módulo, documentadas em vez de
deixadas implícitas (mesma prática de `src/labels/triple_barrier.py`):**

1. **Ordem postada exatamente no melhor bid/ask observado em `t_post`** —
   sem o deslocamento de 1 tick que `triple_barrier.round_to_tick` aplica
   para garantir passividade (GTX). A task que gerou este módulo pediu
   literalmente "postar no melhor bid / melhor ask"; `queue_ahead` é o
   volume JÁ existente naquele nível exato no instante do post.
2. **Os dois lados (compra no bid, venda no ask) são simulados em TODO
   ponto de grade**, não condicionados a nenhum sinal do Alpha (que não
   existe ainda — Sprint 8 é depois deste, §14.3). Isso dá a caracterização
   de microestrutura mais geral e simétrica possível, e é o que o placeholder
   `adverse_selection_bps` (um único número, sem lado) também assume.
3. **`markout` = variação do MID-PRICE `(bid+ask)/2`, ponto no tempo
   `t_fill + horizonte` (asof, não uma média sobre a janela inteira).** O
   §9.5 pede "preço médio no horizonte menos preço do fill" — "preço médio"
   é lido aqui como o ponto médio do book (mid-price), a definição padrão de
   markout na literatura de microestrutura (inclusive Albers, Cucuringu,
   Howison e Shestopaloff, citados no próprio §9.5) e a única leitura
   possível dado que só temos topo do livro, não um preço de referência
   único por instante.
4. **O `adverse_selection_bps` singular do bloco `outputs` do §9.5 não
   desambigua a qual dos 3 horizontes (1m/5m/30m) ele corresponde.** Este
   módulo reporta os 3 explicitamente (`FillSimulationSummary.markout_mean_bps`,
   um dict por horizonte) em vez de escolher um silenciosamente. **Este
   módulo NÃO escreve de volta em `constants.yaml:adverse_selection_bps.value`**
   — isso é reservado para a calibração real do §9.5 (Testnet/Paper), método
   explicitamente diferente deste simulador offline sobre dado histórico.
5. **Pontos de grade sem estado de book conhecido em `t_post`** (ex.:
   madrugada de 2023-05-16 — o primeiro arquivo de bookTicker só começa às
   11:49:47 UTC, medido, não presumido) são EXCLUÍDOS da amostra (nem
   viram uma linha de output) — são ausência de DADO, não o desfecho
   `NOFILL` (que exige saber que uma ordem foi de fato postada com um
   `queue_ahead` conhecido). Contados separadamente em
   `n_skipped_no_book_state`.
6. **Spillover de meia-noite.** Cada dia carrega o par `(dia, dia+1)` de
   bookTicker (a única fonte com janela real curta; `aggTrades` cobre bem
   além dos dois lados). No último dia da janela real (2024-03-30) não
   existe arquivo seguinte — qualquer markout que precisaria de dado além do
   último registro de bookTicker carregado retorna `None` (não um valor
   `stale` silenciosamente reusado).

**Reuso, não reimplementação:** `aggTrades` é consultado via
`src.data.lake.query_agg_trades` (mesma função usada pelo resto do pipeline)
— só `bookTicker` precisa de um loader próprio aqui, porque vive em
`data/raw/` (layout provisório do Sprint 1), não em `data/capacity/` com
`DatasetSchema` registrado em `src/data/schemas.py`.
"""

from __future__ import annotations

import argparse
import io
import os
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Final, NoReturn

import numpy as np
import orjson
import polars as pl
import structlog
from numpy.typing import NDArray

from src.data import lake
from src.data.resample import step_ms

from ._constants import load_constant
from ._paths import EXPERIMENTS_DIR, FILL_SIMULATOR_OUTPUT_DIR, book_ticker_symbol_dir

logger = structlog.get_logger(__name__)

IntArray = NDArray[np.int64]
FloatArray = NDArray[np.float64]
BoolArray = NDArray[np.bool_]

# Cobertura REAL medida de data/raw/book_ticker/BTCUSDT/ — 320 arquivos,
# 2023-05-16..2024-03-30 (known_gaps.
# d05_d08_d09_upstream_availability_shorter_than_prd_claims, constants.yaml).
# Upstream aparentemente descontinuado após esta data — não é falha de
# coleta local.
BOOK_TICKER_WINDOW_START: Final[date] = date(2023, 5, 16)
BOOK_TICKER_WINDOW_END: Final[date] = date(2024, 3, 30)

# Quebra RPI — §9.5 v3.3. A partir desta data bookTicker+aggTrades não
# descrevem mais o book inteiro; este simulador não é válido depois dela.
RPI_BREAK_DATE: Final[date] = date(2025, 11, 20)

# Fator de conversão fração -> pontos-base — definição matemática (mesma
# categoria de `src.labels.triple_barrier._BPS_PER_UNIT`), não constante de
# domínio; não entra em constants.yaml pelo mesmo motivo daquele módulo.
_BPS_PER_UNIT: Final[int] = 10_000

_MS_PER_DAY: Final[int] = 86_400_000

# §9.5 logic: "registra markout de 1m, 5m e 30m pós-fill" — citado
# literalmente do PRD, não uma escolha nova deste módulo.
_MARKOUT_HORIZONS_MS: Final[dict[str, int]] = {"1m": 60_000, "5m": 300_000, "30m": 1_800_000}

_BOOK_TICKER_COLUMNS: Final[tuple[str, ...]] = (
    "transaction_time",
    "best_bid_price",
    "best_bid_qty",
    "best_ask_price",
    "best_ask_qty",
)


# ============================================================================
# Arrays — núcleo numérico (sem IO), mesmo estilo de src/labels/fill_model.py
# ============================================================================


@dataclass(frozen=True, slots=True)
class _BookArrays:
    """`bookTicker` de UM dia + o dia seguinte concatenados (spillover de
    timeout/markout cruzando meia-noite — ver docstring do módulo, item 6),
    já ordenados por `transaction_time`."""

    transaction_time: IntArray
    best_bid_price: FloatArray
    best_bid_qty: FloatArray
    best_ask_price: FloatArray
    best_ask_qty: FloatArray


@dataclass(frozen=True, slots=True)
class _TradeArrays:
    """`aggTrades` do mesmo par de dias, ordenados por `transact_time`."""

    transact_time: IntArray
    price: FloatArray
    quantity: FloatArray
    is_buyer_maker: BoolArray


def _empty_trade_arrays() -> _TradeArrays:
    return _TradeArrays(
        transact_time=np.array([], dtype=np.int64),
        price=np.array([], dtype=np.float64),
        quantity=np.array([], dtype=np.float64),
        is_buyer_maker=np.array([], dtype=np.bool_),
    )


def _asof_index(times: IntArray, t_ms: int) -> int:
    """Índice do ÚLTIMO registro com `times[idx] <= t_ms` — o estado do book
    conhecido no instante `t_ms`. `-1` se `t_ms` é anterior a qualquer
    registro carregado (sem estado de book conhecido ainda)."""
    return int(np.searchsorted(times, t_ms, side="right")) - 1


# ============================================================================
# Resultado por ordem simulada
# ============================================================================


@dataclass(frozen=True, slots=True)
class SimulatedOrder:
    """Uma ordem limite simulada em um ponto de grade. `t_entry_ms`/
    `fill_price`/`markout_*_bps` são `None` quando `filled=False` (NOFILL —
    §3.2 label=-2) — `markout_*_bps` individualmente pode ser `None` mesmo
    com `filled=True` quando o horizonte cai além do bookTicker carregado
    (ver docstring do módulo, item 6)."""

    t_post_ms: int
    side: int  # +1 compra no bid, -1 venda no ask
    limit_price: float
    queue_ahead_initial: float
    filled: bool
    t_entry_ms: int | None
    fill_price: float | None
    markout_1m_bps: float | None
    markout_5m_bps: float | None
    markout_30m_bps: float | None


def _simulate_one_order(
    book: _BookArrays,
    trades: _TradeArrays,
    *,
    t_post_ms: int,
    side: int,
    fill_timeout_ms: int,
    tick_size: float,
) -> SimulatedOrder | None:
    """Núcleo puro (sem IO) — §9.5 `logic`. Retorna `None` (não uma
    `SimulatedOrder`) quando não há estado de book conhecido em `t_post_ms`
    — ver docstring do módulo, item 5 (ausência de dado, não `NOFILL`)."""
    if side not in (1, -1):
        raise ValueError(f"side deve ser 1 (compra) ou -1 (venda), recebido {side}")

    post_idx = _asof_index(book.transaction_time, t_post_ms)
    if post_idx < 0:
        return None

    if side == 1:
        limit_price = float(book.best_bid_price[post_idx])
        queue_ahead = float(book.best_bid_qty[post_idx])
    else:
        limit_price = float(book.best_ask_price[post_idx])
        queue_ahead = float(book.best_ask_qty[post_idx])

    horizon_ms = t_post_ms + fill_timeout_ms

    t_entry_ms: int | None
    fill_price: float | None

    if queue_ahead <= 0.0:
        # §9.5 logic: "preenche quando queue_ahead <= 0" — fila já vazia no
        # instante do post, preenche imediatamente.
        t_entry_ms, fill_price = t_post_ms, limit_price
    else:
        lo = int(np.searchsorted(trades.transact_time, t_post_ms, side="right"))
        hi = int(np.searchsorted(trades.transact_time, horizon_ms, side="right"))

        window_time = trades.transact_time[lo:hi]
        window_price = trades.price[lo:hi]
        window_qty = trades.quantity[lo:hi]
        window_is_buyer_maker = trades.is_buyer_maker[lo:hi]

        # Compra repousa no bid: preenchida por VENDA agressora (taker
        # vendeu contra o bid) -> is_buyer_maker=True (o lado comprador,
        # passivo, foi o maker). Venda repousa no ask: preenchida por COMPRA
        # agressora -> is_buyer_maker=False. (§9.5 logic: "decrementa por
        # volume TAKER executado naquele nível... is_buyer_maker indica o
        # lado do agressor".)
        direction_match = window_is_buyer_maker if side == 1 else ~window_is_buyer_maker
        price_match = np.abs(window_price - limit_price) < (tick_size / 2.0)
        matching = direction_match & price_match

        cum_qty = np.cumsum(np.where(matching, window_qty, 0.0))
        crossed = cum_qty >= queue_ahead

        if bool(crossed.any()):
            first_idx = int(np.argmax(crossed))
            t_entry_ms = int(window_time[first_idx])
            fill_price = limit_price
        else:
            t_entry_ms, fill_price = None, None

    markouts: dict[str, float | None] = {}
    if t_entry_ms is not None and fill_price is not None:
        last_book_time = int(book.transaction_time[-1])
        for label, h_ms in _MARKOUT_HORIZONS_MS.items():
            target_ms = t_entry_ms + h_ms
            if target_ms > last_book_time:
                # Horizonte além do bookTicker carregado (fim real da
                # janela, item 6 da docstring) — null, não um valor stale.
                markouts[label] = None
                continue
            target_idx = _asof_index(book.transaction_time, target_ms)
            mid = (book.best_bid_price[target_idx] + book.best_ask_price[target_idx]) / 2.0
            markouts[label] = side * (mid - fill_price) / fill_price * _BPS_PER_UNIT
    else:
        markouts = dict.fromkeys(_MARKOUT_HORIZONS_MS)

    return SimulatedOrder(
        t_post_ms=t_post_ms,
        side=side,
        limit_price=limit_price,
        queue_ahead_initial=queue_ahead,
        filled=t_entry_ms is not None,
        t_entry_ms=t_entry_ms,
        fill_price=fill_price,
        markout_1m_bps=markouts["1m"],
        markout_5m_bps=markouts["5m"],
        markout_30m_bps=markouts["30m"],
    )


# ============================================================================
# Grade de decisão a 15m (mesma grade da decisão real do sistema, §0.1)
# ============================================================================


def _day_grid_ms(day: date, bar_ms: int) -> IntArray:
    """Pontos de grade `[00:00, 24:00)` UTC do dia, a cada `bar_ms`."""
    start_ms = int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp() * 1000)
    n_bars = _MS_PER_DAY // bar_ms
    return (start_ms + np.arange(n_bars, dtype=np.int64) * bar_ms).astype(np.int64)


# ============================================================================
# IO — bookTicker (loader próprio, não está em src/data/schemas.py) +
# aggTrades (reusa src.data.lake, não reimplementado)
# ============================================================================


def _list_book_ticker_files(symbol: str, start: date, end: date) -> list[Path]:
    symbol_dir = book_ticker_symbol_dir(symbol)
    files = []
    for p in sorted(symbol_dir.glob("*.parquet")):
        try:
            file_date = date.fromisoformat(p.stem)
        except ValueError:
            continue  # arquivo fora do padrão yyyy-mm-dd.parquet
        if start <= file_date <= end:
            files.append(p)
    return files


def load_book_ticker_pair(symbol: str, day: date) -> pl.DataFrame:
    """Carrega `day` + `day + 1` (se existir) concatenados e ordenados por
    `transaction_time` — o dia seguinte cobre o spillover de
    `fill_timeout_ms`/markout que cruza meia-noite (nunca mais que
    `fill_timeout_bars` barras + 30 minutos de spillover). Retorna
    DataFrame vazio (schema correto, sem ler nada) se nenhum arquivo do par
    existir — chamador decide o que fazer (ver `simulate_window`)."""
    files = _list_book_ticker_files(symbol, day, day + timedelta(days=1))
    if not files:
        schema = {
            c: (pl.Int64 if c == "transaction_time" else pl.Float64) for c in _BOOK_TICKER_COLUMNS
        }
        return pl.DataFrame(schema=schema)
    frames = [pl.read_parquet(f, columns=list(_BOOK_TICKER_COLUMNS)) for f in files]
    return pl.concat(frames).sort("transaction_time")


def _book_arrays(df: pl.DataFrame) -> _BookArrays:
    return _BookArrays(
        transaction_time=df["transaction_time"].cast(pl.Int64).to_numpy().astype(np.int64),
        best_bid_price=df["best_bid_price"].cast(pl.Float64).to_numpy(),
        best_bid_qty=df["best_bid_qty"].cast(pl.Float64).to_numpy(),
        best_ask_price=df["best_ask_price"].cast(pl.Float64).to_numpy(),
        best_ask_qty=df["best_ask_qty"].cast(pl.Float64).to_numpy(),
    )


def _trade_arrays(df: pl.DataFrame) -> _TradeArrays:
    return _TradeArrays(
        transact_time=df["transact_time"].cast(pl.Int64).to_numpy().astype(np.int64),
        price=df["price"].cast(pl.Float64).to_numpy(),
        quantity=df["quantity"].cast(pl.Float64).to_numpy(),
        is_buyer_maker=df["is_buyer_maker"].cast(pl.Boolean).to_numpy().astype(np.bool_),
    )


# ============================================================================
# Orquestração — simulate_window
# ============================================================================

_ORDERS_SCHEMA: Final[dict[str, Any]] = {
    "symbol": pl.Utf8,
    "t_post": pl.Int64,
    "side": pl.Int8,
    "limit_price": pl.Float64,
    "queue_ahead_initial": pl.Float64,
    "filled": pl.Boolean,
    "t_entry": pl.Int64,
    "fill_price": pl.Float64,
    "markout_1m_bps": pl.Float64,
    "markout_5m_bps": pl.Float64,
    "markout_30m_bps": pl.Float64,
}

ORDER_COLUMNS: Final[tuple[str, ...]] = tuple(_ORDERS_SCHEMA)


def _ms_epoch_to_utc(expr: pl.Expr) -> pl.Expr:
    return expr.cast(pl.Datetime("ms")).dt.replace_time_zone("UTC")


def _empty_orders_frame() -> pl.DataFrame:
    return pl.DataFrame(schema=_ORDERS_SCHEMA)


def _finalize_orders_frame(cols: dict[str, list[Any]]) -> pl.DataFrame:
    df = pl.DataFrame(cols, schema=_ORDERS_SCHEMA)
    return df.with_columns([_ms_epoch_to_utc(pl.col(c)) for c in ("t_post", "t_entry")])


def _append_order(cols: dict[str, list[Any]], order: SimulatedOrder, *, symbol: str) -> None:
    cols["symbol"].append(symbol)
    cols["t_post"].append(order.t_post_ms)
    cols["side"].append(order.side)
    cols["limit_price"].append(order.limit_price)
    cols["queue_ahead_initial"].append(order.queue_ahead_initial)
    cols["filled"].append(order.filled)
    cols["t_entry"].append(order.t_entry_ms)
    cols["fill_price"].append(order.fill_price)
    cols["markout_1m_bps"].append(order.markout_1m_bps)
    cols["markout_5m_bps"].append(order.markout_5m_bps)
    cols["markout_30m_bps"].append(order.markout_30m_bps)


@dataclass(frozen=True, slots=True)
class SimulationRunResult:
    orders: pl.DataFrame
    n_skipped_no_book_state: int
    n_days_no_data: int


def simulate_window(
    symbol: str = "BTCUSDT",
    start: date = BOOK_TICKER_WINDOW_START,
    end: date = BOOK_TICKER_WINDOW_END,
    *,
    sides: tuple[int, ...] = (1, -1),
    fill_timeout_bars: int | None = None,
) -> SimulationRunResult:
    """Percorre `[start, end]` dia a dia, dia útil de calendário (não
    apenas dias com dado — dias sem arquivo de bookTicker são contados em
    `n_days_no_data` e pulados). Para cada dia carrega o par
    `(dia, dia+1)` de bookTicker + `aggTrades` (via `src.data.lake`), gera a
    grade de 15m do dia e simula UMA ordem por lado por ponto de grade
    (ambos os lados por padrão — ver docstring do módulo, item 2)."""
    if end >= RPI_BREAK_DATE:
        raise ValueError(
            f"end={end.isoformat()} >= {RPI_BREAK_DATE.isoformat()} (quebra RPI, §9.5 v3.3) — "
            "este simulador não é válido depois desta data (ver docstring do módulo)"
        )
    if start < BOOK_TICKER_WINDOW_START or end > BOOK_TICKER_WINDOW_END:
        logger.warning(
            "fill_simulator.window_outside_measured_coverage",
            requested_start=start.isoformat(),
            requested_end=end.isoformat(),
            coverage_start=BOOK_TICKER_WINDOW_START.isoformat(),
            coverage_end=BOOK_TICKER_WINDOW_END.isoformat(),
        )

    bar_ms = step_ms("15m")
    if fill_timeout_bars is not None:
        timeout_bars = fill_timeout_bars
    else:
        timeout_bars = int(load_constant("fill_timeout_bars"))
    fill_timeout_ms = timeout_bars * bar_ms
    tick_size = float(load_constant("tick_size"))

    cols: dict[str, list[Any]] = {c: [] for c in _ORDERS_SCHEMA}
    n_skipped_no_book_state = 0
    n_days_no_data = 0

    day = start
    while day <= end:
        book_df = load_book_ticker_pair(symbol, day)
        if book_df.is_empty():
            n_days_no_data += 1
            logger.warning("fill_simulator.day_no_book_data", day=day.isoformat())
            day += timedelta(days=1)
            continue

        trades_df = lake.query_agg_trades(symbol, day, day + timedelta(days=1))
        book_arr = _book_arrays(book_df)
        trade_arr = _trade_arrays(trades_df) if not trades_df.is_empty() else _empty_trade_arrays()

        grid = _day_grid_ms(day, bar_ms).tolist()
        n_before = len(cols["t_post"])
        for side in sides:
            for t_post_ms in grid:
                order = _simulate_one_order(
                    book_arr,
                    trade_arr,
                    t_post_ms=t_post_ms,
                    side=side,
                    fill_timeout_ms=fill_timeout_ms,
                    tick_size=tick_size,
                )
                if order is None:
                    n_skipped_no_book_state += 1
                    continue
                _append_order(cols, order, symbol=symbol)

        logger.debug(
            "fill_simulator.day_done",
            day=day.isoformat(),
            n_orders_emitted=len(cols["t_post"]) - n_before,
        )
        day += timedelta(days=1)

    df = _finalize_orders_frame(cols) if cols["t_post"] else _empty_orders_frame()
    logger.info(
        "fill_simulator.simulate_window_done",
        symbol=symbol,
        start=start.isoformat(),
        end=end.isoformat(),
        n_orders=df.height,
        n_skipped_no_book_state=n_skipped_no_book_state,
        n_days_no_data=n_days_no_data,
    )
    return SimulationRunResult(
        orders=df,
        n_skipped_no_book_state=n_skipped_no_book_state,
        n_days_no_data=n_days_no_data,
    )


# ============================================================================
# Agregação — p_fill, adverse_selection (markout) por horizonte
# ============================================================================


@dataclass(frozen=True, slots=True)
class FillSimulationSummary:
    symbol: str
    start: str
    end: str
    n_orders: int
    n_filled: int
    n_nofill: int
    p_fill: float
    n_skipped_no_book_state: int
    n_days_no_data: int
    p_fill_by_side: dict[str, float]
    markout_mean_bps: dict[str, float]
    markout_median_bps: dict[str, float]
    markout_n: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "start": self.start,
            "end": self.end,
            "n_orders": self.n_orders,
            "n_filled": self.n_filled,
            "n_nofill": self.n_nofill,
            "p_fill": self.p_fill,
            "n_skipped_no_book_state": self.n_skipped_no_book_state,
            "n_days_no_data": self.n_days_no_data,
            "p_fill_by_side": self.p_fill_by_side,
            "markout_mean_bps": self.markout_mean_bps,
            "markout_median_bps": self.markout_median_bps,
            "markout_n": self.markout_n,
        }


def summarize(
    df: pl.DataFrame,
    *,
    symbol: str,
    start: str,
    end: str,
    n_skipped_no_book_state: int = 0,
    n_days_no_data: int = 0,
) -> FillSimulationSummary:
    """`p_fill` agregado (fração preenchida) e `markout` médio/mediano por
    horizonte (1m/5m/30m) — ver docstring do módulo, item 4, sobre por que
    os 3 horizontes são reportados separadamente em vez de um único
    `adverse_selection_bps`."""
    n = df.height
    if n == 0:
        empty_h = dict.fromkeys(_MARKOUT_HORIZONS_MS, float("nan"))
        empty_n = dict.fromkeys(_MARKOUT_HORIZONS_MS, 0)
        return FillSimulationSummary(
            symbol=symbol,
            start=start,
            end=end,
            n_orders=0,
            n_filled=0,
            n_nofill=0,
            p_fill=float("nan"),
            n_skipped_no_book_state=n_skipped_no_book_state,
            n_days_no_data=n_days_no_data,
            p_fill_by_side={},
            markout_mean_bps=empty_h,
            markout_median_bps=empty_h,
            markout_n=empty_n,
        )

    filled_arr = df["filled"].to_numpy().astype(np.bool_)
    n_filled = int(filled_arr.sum())
    n_nofill = n - n_filled
    p_fill = n_filled / n

    p_fill_by_side: dict[str, float] = {}
    for side_val, side_name in ((1, "buy"), (-1, "sell")):
        side_df = df.filter(pl.col("side") == side_val)
        if side_df.height:
            side_filled = side_df["filled"].to_numpy().astype(np.bool_)
            p_fill_by_side[side_name] = float(side_filled.sum()) / side_df.height
        else:
            p_fill_by_side[side_name] = float("nan")

    markout_mean: dict[str, float] = {}
    markout_median: dict[str, float] = {}
    markout_n: dict[str, int] = {}
    for h in _MARKOUT_HORIZONS_MS:
        arr = df[f"markout_{h}_bps"].drop_nulls().to_numpy().astype(np.float64)
        markout_n[h] = int(arr.shape[0])
        if arr.size:
            markout_mean[h] = float(np.mean(arr))
            markout_median[h] = float(np.median(arr))
        else:
            markout_mean[h] = float("nan")
            markout_median[h] = float("nan")

    return FillSimulationSummary(
        symbol=symbol,
        start=start,
        end=end,
        n_orders=n,
        n_filled=n_filled,
        n_nofill=n_nofill,
        p_fill=p_fill,
        n_skipped_no_book_state=n_skipped_no_book_state,
        n_days_no_data=n_days_no_data,
        p_fill_by_side=p_fill_by_side,
        markout_mean_bps=markout_mean,
        markout_median_bps=markout_median,
        markout_n=markout_n,
    )


# ============================================================================
# Calibração (§9.5 `calibration`) — HOOK, NÃO IMPLEMENTADO (ver docstring)
# ============================================================================


def calibrate_against_real_fills(simulated: pl.DataFrame, real_fills: pl.DataFrame) -> NoReturn:
    """§9.5 `calibration`: `method: comparar contra fills reais de Testnet e
    Paper`, `metric: erro absoluto mediano de p_fill`, `threshold: 0.10`.

    **NÃO IMPLEMENTADO NESTE SPRINT.** Testnet/Paper só existem nos
    Sprints 15-16 (roadmap §14.3) — não há `real_fills` real para comparar
    hoje, e fabricar um substituto violaria a Regra Zero (CLAUDE.md: "não
    invente faixas esperadas — escreva TBD"). Esta função é o HOOK que os
    Sprints 15-16 preenchem: assinatura já compatível com `simulated`
    (output de `simulate_window(...).orders`) e `real_fills` (schema real
    ainda TBD — definido quando Testnet/Paper existirem), corpo levanta erro
    explícito em vez de fingir uma calibração que não aconteceu."""
    raise NotImplementedError(
        "calibração contra fills reais é Sprint 15-16 (§9.5 calibration, Testnet/Paper) — "
        "não implementada por design neste Sprint 9; ver docstring desta função e do módulo"
    )


# ============================================================================
# Escrita atômica — B29, mesmo padrão de src/labels/triple_barrier.py
# ============================================================================


def write_orders_atomic(
    df: pl.DataFrame, *, version: str = "v1", dest_dir: Path | None = None
) -> Path:
    out_dir = dest_dir if dest_dir is not None else (FILL_SIMULATOR_OUTPUT_DIR / version)
    out_dir.mkdir(parents=True, exist_ok=True)
    dest_path = out_dir / "orders.parquet"
    tmp_path = dest_path.with_name(dest_path.name + ".tmp")

    buffer = io.BytesIO()
    df.write_parquet(buffer)
    with tmp_path.open("wb") as fh:
        fh.write(buffer.getvalue())
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, dest_path)
    logger.info("fill_simulator.orders_written", path=str(dest_path), n_rows=df.height)
    return dest_path


def write_summary_atomic(
    summary: FillSimulationSummary, *, version: str = "v1", dest_dir: Path | None = None
) -> Path:
    out_dir = dest_dir if dest_dir is not None else (FILL_SIMULATOR_OUTPUT_DIR / version)
    out_dir.mkdir(parents=True, exist_ok=True)
    dest_path = out_dir / "summary.json"
    tmp_path = dest_path.with_name(dest_path.name + ".tmp")

    payload = orjson.dumps(summary.to_dict(), option=orjson.OPT_INDENT_2)
    with tmp_path.open("wb") as fh:
        fh.write(payload)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, dest_path)
    logger.info("fill_simulator.summary_written", path=str(dest_path))
    return dest_path


# ============================================================================
# Registro append-only PEQUENO (§11.6, mesmo padrão de
# src/labels/experiment_log.py) — experiments/fill_simulator_runs.parquet
# ============================================================================

EXPERIMENT_LOG_PATH: Path = EXPERIMENTS_DIR / "fill_simulator_runs.parquet"

_EXPERIMENT_SCHEMA: dict[str, Any] = {
    "run_id": pl.Int64,
    "logged_at_utc": pl.Datetime("ms", "UTC"),
    "sprint": pl.Int32,
    "symbol": pl.Utf8,
    "period_start": pl.Utf8,
    "period_end": pl.Utf8,
    "fill_timeout_bars": pl.Int32,
    "tick_size": pl.Float64,
    "n_orders": pl.Int64,
    "n_filled": pl.Int64,
    "n_nofill": pl.Int64,
    "p_fill": pl.Float64,
    "n_skipped_no_book_state": pl.Int64,
    "n_days_no_data": pl.Int64,
    "p_fill_buy": pl.Float64,
    "p_fill_sell": pl.Float64,
    "markout_mean_1m_bps": pl.Float64,
    "markout_mean_5m_bps": pl.Float64,
    "markout_mean_30m_bps": pl.Float64,
    "markout_n_1m": pl.Int64,
    "markout_n_5m": pl.Int64,
    "markout_n_30m": pl.Int64,
    # valor de constants.yaml no MOMENTO do run — placeholder que este run
    # está comparando, não o número medido (esse são as colunas markout_* acima).
    "adverse_selection_bps_placeholder": pl.Float64,
    "notes": pl.Utf8,
}


def load_experiment_log(path: Path | None = None) -> pl.DataFrame:
    log_path = path if path is not None else EXPERIMENT_LOG_PATH
    if not log_path.exists():
        return pl.DataFrame(schema=_EXPERIMENT_SCHEMA)
    return pl.read_parquet(log_path)


def _next_run_id(existing: pl.DataFrame) -> int:
    if existing.is_empty():
        return 1
    ids = existing["run_id"].to_numpy().astype(np.int64)
    return int(ids.max()) + 1


def record_experiment(
    summary: FillSimulationSummary,
    *,
    fill_timeout_bars_used: int,
    tick_size_used: float,
    sprint: int = 9,
    notes: str = "",
    path: Path | None = None,
) -> Path:
    """Acrescenta uma linha ao log de experimentos do simulador de fila —
    nunca edita nem remove linhas existentes (mesma regra de
    `src.labels.experiment_log.record_experiment`)."""
    log_path = path if path is not None else EXPERIMENT_LOG_PATH
    existing = load_experiment_log(log_path)

    row = {
        "run_id": _next_run_id(existing),
        "logged_at_utc": datetime.now(UTC),
        "sprint": sprint,
        "symbol": summary.symbol,
        "period_start": summary.start,
        "period_end": summary.end,
        "fill_timeout_bars": fill_timeout_bars_used,
        "tick_size": tick_size_used,
        "n_orders": summary.n_orders,
        "n_filled": summary.n_filled,
        "n_nofill": summary.n_nofill,
        "p_fill": summary.p_fill,
        "n_skipped_no_book_state": summary.n_skipped_no_book_state,
        "n_days_no_data": summary.n_days_no_data,
        "p_fill_buy": summary.p_fill_by_side.get("buy", float("nan")),
        "p_fill_sell": summary.p_fill_by_side.get("sell", float("nan")),
        "markout_mean_1m_bps": summary.markout_mean_bps.get("1m", float("nan")),
        "markout_mean_5m_bps": summary.markout_mean_bps.get("5m", float("nan")),
        "markout_mean_30m_bps": summary.markout_mean_bps.get("30m", float("nan")),
        "markout_n_1m": summary.markout_n.get("1m", 0),
        "markout_n_5m": summary.markout_n.get("5m", 0),
        "markout_n_30m": summary.markout_n.get("30m", 0),
        "adverse_selection_bps_placeholder": float(load_constant("adverse_selection_bps")),
        "notes": notes,
    }
    new_row = pl.DataFrame([row], schema=_EXPERIMENT_SCHEMA)
    combined = (
        new_row if existing.is_empty() else pl.concat([existing, new_row], how="vertical")
    )

    log_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = log_path.with_name(log_path.name + ".tmp")
    buffer = io.BytesIO()
    combined.write_parquet(buffer)
    with tmp_path.open("wb") as fh:
        fh.write(buffer.getvalue())
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, log_path)

    logger.info(
        "fill_simulator.experiment_recorded",
        run_id=row["run_id"],
        path=str(log_path),
        p_fill=summary.p_fill,
    )
    return log_path


# ============================================================================
# CLI — execução manual (`python -m src.execution.fill_simulator ...`).
# Mesmo padrão de src/data/validate.py: configuração de logging fica para um
# entry point real (scripts/), não é chamada aqui (§14.2 comment naquele
# módulo).
# ============================================================================


def _run_cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--start", default=BOOK_TICKER_WINDOW_START.isoformat(), help="yyyy-mm-dd")
    parser.add_argument("--end", default=BOOK_TICKER_WINDOW_END.isoformat(), help="yyyy-mm-dd")
    parser.add_argument("--version", default="v1")
    parser.add_argument("--notes", default="")
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)

    result = simulate_window(args.symbol, start, end)
    summary = summarize(
        result.orders,
        symbol=args.symbol,
        start=start.isoformat(),
        end=end.isoformat(),
        n_skipped_no_book_state=result.n_skipped_no_book_state,
        n_days_no_data=result.n_days_no_data,
    )

    write_orders_atomic(result.orders, version=args.version)
    write_summary_atomic(summary, version=args.version)
    record_experiment(
        summary,
        fill_timeout_bars_used=int(load_constant("fill_timeout_bars")),
        tick_size_used=float(load_constant("tick_size")),
        notes=args.notes,
    )

    logger.info("fill_simulator.cli_done", **summary.to_dict())
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(_run_cli())
