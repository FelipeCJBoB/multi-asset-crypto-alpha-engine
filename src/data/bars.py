"""Barras alternativas a partir de `aggTrades` (PRD_V4_1.md §3.2 M2): dollar
bars, volume bars, tick imbalance bars — candidatas contra o baseline
`resample.resample_klines` (barra de tempo). Constrói bars trade-a-trade
real, não a partir de `klines_1m` (que já É uma agregação temporal — usar
klines pra medir "a barra de tempo é pior que outra coisa" seria circular).

**Streaming por construção, não um modo alternativo.** Achado de auditoria
(2026-08-15, medido antes de escrever qualquer linha): `aggTrades` de
BTCUSDT/ETHUSDT são 27GB/20GB *comprimidos* em disco — descompactado como
`DataFrame` tipado, isso não cabe na RAM de uma vez, em nenhuma
concorrência (nem 1 processo sozinho). Cada tipo de barra é implementado
como `<tipo>_bars_carry()` (estado inicial) + `<tipo>_bars_step(carry,
chunk)` (processa 1 chunk, muta `carry`) + `<tipo>_bars_finish(carry)`
(fecha o stream, devolve o `DataFrame` de barras — pequeno, ~dezenas de
milhares de linhas pro histórico inteiro, não os trades crus). As funções
`dollar_bars`/`volume_bars`/`tick_imbalance_bars` (assinatura antiga, 1
`DataFrame` só) viraram wrappers finos sobre `carry→step→finish` com um
único chunk — garante paridade streaming↔lote POR CONSTRUÇÃO (mesmo
caminho de código), não só por teste (ainda que testado, ver
`test_data_bars.py`).

**Causalidade.** Toda função aqui só usa informação de trades com
`transact_time <= t` da barra em construção — nenhuma olha para frente.
Para dollar/volume bars isso é por construção: `bar_id = floor(cumsum/
threshold)` é monotonicamente não-decrescente em `transact_time` (preço×
quantidade e quantidade são sempre >= 0), então o `bar_id` de um trade
nunca depende de trades futuros — e a soma acumulada CONTINUA de chunk pra
chunk via o "leftover" (trades do bar ainda aberto no fim do chunk
anterior), nunca reinicia do zero num ponto arbitrário. Para tick
imbalance bars, a EWMA do imbalance por tick e `exp_num_ticks` (atualizado
só quando uma barra FECHA, com o tamanho dessa própria barra já completa)
seguem a mesma disciplina, agora calculada trade-a-trade dentro do mesmo
loop que decide o fechamento (não mais um `pl.Series.ewm_mean` vetorizado
à parte — essa versão não tinha como retomar de um valor semente entre
chunks; a recorrência EWMA é matematicamente idêntica calculada assim,
achado ao resolver streaming, não uma segunda implementação divergente).

**Tick imbalance bars — fonte do sinal de direção.** `b_t` usa
`is_buyer_maker` DIRETO (mapeamento: `is_buyer_maker=True` → comprador é
maker → agressor vendeu → `b_t=-1`; `is_buyer_maker=False` → agressor
comprou → `b_t=+1`), não o "tick rule" clássico do AFML (comparar preço
consecutivo). Pesquisa web feita antes de implementar confirmou: quando o
rótulo real do agressor já vem no dado bruto (caso da Binance), ele é
estritamente superior ao tick rule, que foi desenhado como PROXY para
mercados sem esse campo (Ma & Zhai 2021 mediram ~77% de acurácia do tick
rule em Bitcoin, não ~90%).

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

**Performance.** `tick_imbalance_bars_step` é sequencial por construção (o
limiar de fechamento de cada barra depende do tamanho da barra anterior)
— não vetorizável como dollar/volume bars. `dollar_bars_step`/
`volume_bars_step` continuam vetorizados DENTRO de cada chunk (só o
"leftover" entre chunks é pequeno, nunca mais que os trades de 1 barra
ainda aberta). Ponto de entrada manual (M2), não código de produção em
tempo real."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final

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

#: Schema canônico de SAÍDA (barras agregadas) -- mesma convenção de coluna
#: de `resample.resample_klines`, sempre aplicado explicitamente (`.cast`)
#: pra que `_aggregate_bars` (vetorizado, via group_by) e
#: `tick_imbalance_bars_finish` (trade-a-trade, via dict) produzam dtypes
#: idênticos -- sem isso, um teste de paridade poderia falhar por dtype
#: (ex. Int64 vs UInt32 em `count`) mesmo com valores numericamente iguais.
_BAR_OUTPUT_SCHEMA: Final[pl.Schema] = pl.Schema(
    [
        ("open_time", pl.Int64()),
        ("close_time", pl.Int64()),
        ("open", pl.Float64()),
        ("high", pl.Float64()),
        ("low", pl.Float64()),
        ("close", pl.Float64()),
        ("volume", pl.Float64()),
        ("quote_volume", pl.Float64()),
        ("count", pl.UInt32()),
        ("taker_buy_volume", pl.Float64()),
        ("taker_buy_quote_volume", pl.Float64()),
    ]
)


def _require_trade_columns(trades: pl.DataFrame) -> None:
    missing = [c for c in _TRADE_REQUIRED_COLUMNS if c not in trades.columns]
    if missing:
        raise ValueError(f"trades sem coluna(s) obrigatória(s) {missing} (schema AGG_TRADES)")


def _empty_bars() -> pl.DataFrame:
    return pl.DataFrame(schema=_BAR_OUTPUT_SCHEMA)


def _aggregate_bars(trades: pl.DataFrame, bar_id: pl.Series | IntArray) -> pl.DataFrame:
    """Núcleo comum de agregação OHLCV, vetorizado via `group_by` --
    `is_buyer_maker=False` é trade agredido por comprador (mesma convenção
    de "taker buy" das klines da Binance). Sempre devolve `_BAR_OUTPUT_
    SCHEMA` exato (`.cast` explícito), não o que `group_by`/`agg` inferirem
    -- garante paridade de dtype com `tick_imbalance_bars_finish`
    (construído via dict, caminho diferente)."""
    if trades.is_empty():
        return _empty_bars()
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
    return agg.select(list(_BAR_OUTPUT_SCHEMA)).cast(_BAR_OUTPUT_SCHEMA)


# ---------------------------------------------------------------------------
# Dollar bars / volume bars -- vetorizado por chunk, leftover pequeno entre
# chunks (só os trades da barra ainda aberta -- nunca cresce além do que
# acumula até `threshold`, por construção).
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ThresholdBarsCarry:
    """Estado entre chunks pra dollar/volume bars. `value_expr` decide qual
    barra (`price*quantity` = dollar, `quantity` = volume) -- ver
    `dollar_bars_carry`/`volume_bars_carry`. `leftover` guarda só os trades
    do bar ainda aberto; `bar_frames` acumula barras JÁ fechadas
    (agregadas, pequenas -- não trades crus). `base_value` é o valor total
    (dólar ou volume) já consumido por todas as barras fechadas até agora --
    achado de bug (2026-08-15, teste de paridade `sizes=[1]*20` de
    `volume_bars` falhando com barra fantasma): uma barra só fecha quando um
    trade EXCEDE o threshold, não quando bate exatamente nele, então o
    "resto" acumulado ao fechar não é múltiplo do threshold em geral. Sem
    `base_value`, cada `step()` recalculava o cumsum do zero pra
    `leftover+chunk`, perdendo esse resto e fechando barras cedo demais
    sempre que o leftover sobrevivia a mais de 1 chunk -- não pegou no teste
    de `dollar_bars` só porque lá o valor por trade já excede o threshold
    (leftover nunca sobrevive), mascarando o bug por coincidência dos
    dados."""

    threshold: float
    value_expr: pl.Expr
    leftover: pl.DataFrame | None = None
    base_value: float = 0.0
    bar_frames: list[pl.DataFrame] = field(default_factory=list)


def dollar_bars_carry(*, threshold: float) -> ThresholdBarsCarry:
    if threshold <= 0:
        raise ValueError(f"threshold precisa ser > 0, recebido {threshold}")
    return ThresholdBarsCarry(threshold=threshold, value_expr=pl.col("price") * pl.col("quantity"))


def volume_bars_carry(*, threshold: float) -> ThresholdBarsCarry:
    if threshold <= 0:
        raise ValueError(f"threshold precisa ser > 0, recebido {threshold}")
    return ThresholdBarsCarry(threshold=threshold, value_expr=pl.col("quantity"))


def threshold_bars_step(carry: ThresholdBarsCarry, chunk: pl.DataFrame) -> None:
    """Processa 1 chunk de trades (ordenado por `transact_time`, mesma
    garantia de `lake.query_agg_trades`) -- muta `carry` in place. Chunk
    vazio (dia sem trade) é no-op seguro."""
    _require_trade_columns(chunk)
    if chunk.is_empty():
        return

    combined = (
        pl.concat([carry.leftover, chunk])
        if carry.leftover is not None and not carry.leftover.is_empty()
        else chunk
    )
    local_cum = combined.select(carry.value_expr.alias("_v")).to_series().cum_sum()
    # soma o valor ja consumido por barras fechadas (`base_value`) antes de
    # dividir pelo threshold -- sem isso, cada chunk recomeca o cumsum do
    # zero e perde o "resto" de barras que fecharam sem bater exatamente no
    # multiplo do threshold, fechando barra fantasma cedo demais (ver
    # docstring de `ThresholdBarsCarry`).
    cum_value = local_cum + carry.base_value
    # carry.threshold > 0 garantido por dollar_bars_carry/volume_bars_carry
    # (único jeito de construir ThresholdBarsCarry) antes de chegar aqui.
    bar_id = (cum_value // carry.threshold).cast(pl.Int64)  # noqa: unguarded-ratio
    # cum_value e' soma acumulada de valores >=0 (preco*quantidade ou
    # quantidade) -- monotonica nao-decrescente, entao bar_id tambem e';
    # o ultimo elemento e' sempre o maior, sem precisar de .max().
    max_bar_id = bar_id[-1]
    combined = combined.with_columns(pl.Series("_bar_id", bar_id))

    closed = combined.filter(pl.col("_bar_id") < max_bar_id)
    carry.leftover = combined.filter(pl.col("_bar_id") == max_bar_id).drop("_bar_id")
    if not closed.is_empty():
        closed_bar_id = closed["_bar_id"].to_numpy()
        carry.bar_frames.append(_aggregate_bars(closed.drop("_bar_id"), closed_bar_id))
        # bar_id e' monotonico nao-decrescente -> "closed" e' sempre um
        # prefixo de `combined`; cum_value[n_closed-1] e' o valor acumulado
        # exatamente ate o fim da ultima barra fechada, o novo `base_value`.
        carry.base_value = float(cum_value[closed.height - 1])


def threshold_bars_finish(carry: ThresholdBarsCarry) -> pl.DataFrame:
    """Fecha o stream -- inclui a última barra mesmo que parcial (nunca
    atingiu `threshold`; mesma convenção de `dollar_bars`/`volume_bars`
    não-streaming: toda trade pertence a alguma barra)."""
    if carry.leftover is not None and not carry.leftover.is_empty():
        leftover = carry.leftover
        leftover_bar_id = np.zeros(leftover.height, dtype=np.int64)
        carry.bar_frames.append(_aggregate_bars(leftover, leftover_bar_id))
        carry.leftover = None
    if not carry.bar_frames:
        return _empty_bars()
    return pl.concat(carry.bar_frames)


def dollar_bars(trades: pl.DataFrame, *, threshold: float) -> pl.DataFrame:
    """Conveniência pra um `DataFrame` só (testes, uso manual pequeno) --
    wrapper fino sobre `dollar_bars_carry`/`threshold_bars_step`/`finish`
    com um único chunk. Garante paridade com o caminho em streaming POR
    CONSTRUÇÃO (mesmo código), não uma segunda implementação."""
    _require_trade_columns(trades)
    carry = dollar_bars_carry(threshold=threshold)
    threshold_bars_step(carry, trades)
    return threshold_bars_finish(carry)


def volume_bars(trades: pl.DataFrame, *, threshold: float) -> pl.DataFrame:
    """Mesma lógica de `dollar_bars`, mas acumulando `quantity` (unidades
    do ativo), não valor em dólar."""
    _require_trade_columns(trades)
    carry = volume_bars_carry(threshold=threshold)
    threshold_bars_step(carry, trades)
    return threshold_bars_finish(carry)


# ---------------------------------------------------------------------------
# Tick imbalance bars -- sequencial por construção (AFML cap.2), acumulador
# OHLCV escalar no `carry` (não guarda trades crus entre chunks, ao
# contrário de dollar/volume bars -- não precisa, já é trade-a-trade).
# ---------------------------------------------------------------------------


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

    def __post_init__(self) -> None:
        if self.num_prev_bars <= 0:
            raise ValueError(f"num_prev_bars precisa ser > 0, recebido {self.num_prev_bars}")
        if self.expected_imbalance_window <= 0:
            raise ValueError(
                "expected_imbalance_window precisa ser > 0, recebido "
                f"{self.expected_imbalance_window}"
            )
        if self.exp_num_ticks_init <= 0:
            raise ValueError(
                f"exp_num_ticks_init precisa ser > 0, recebido {self.exp_num_ticks_init}"
            )


@dataclass(slots=True)
class TickImbalanceBarsCarry:
    """Estado entre chunks pra tick imbalance bars -- `theta`/`ewma_b`/
    `exp_num_ticks` são o estado do algoritmo AFML propriamente dito;
    `open`../`taker_buy_quote_volume` são o acumulador OHLCV da barra
    AINDA em construção (substitui guardar trades crus -- mais eficiente,
    e simplifica a lógica: `tick_imbalance_bars_step` nunca precisa
    reprocessar um trade já visto). `started` distingue "primeiro trade de
    todos" (EWMA nasce nele, sem recorrência) de "primeiro trade DE UM
    CHUNK, mas não da série" (EWMA continua a recorrência normal) -- sem
    isso, cada novo chunk reiniciaria a EWMA do zero, quebrando a
    causalidade "só olha pra trás" através de fronteiras de chunk."""

    config: TickImbalanceBarsConfig
    theta: float = 0.0
    ewma_b: float = 0.0
    exp_num_ticks: float = 0.0
    ticks_in_bar: int = 0
    started: bool = False
    open_time: int | None = None
    close_time: int | None = None
    open: float | None = None
    high: float = float("-inf")
    low: float = float("inf")
    close: float = 0.0
    volume: float = 0.0
    quote_volume: float = 0.0
    count: int = 0
    taker_buy_volume: float = 0.0
    taker_buy_quote_volume: float = 0.0
    bar_rows: list[dict[str, Any]] = field(default_factory=list)


def tick_imbalance_bars_carry(config: TickImbalanceBarsConfig) -> TickImbalanceBarsCarry:
    return TickImbalanceBarsCarry(config=config, exp_num_ticks=config.exp_num_ticks_init)


def tick_imbalance_bars_step(carry: TickImbalanceBarsCarry, chunk: pl.DataFrame) -> None:
    """Processa 1 chunk trade-a-trade -- muta `carry` in place, inclusive
    fechando barras que completam durante o chunk (acrescentadas a
    `carry.bar_rows`). Chunk vazio é no-op seguro."""
    _require_trade_columns(chunk)
    if chunk.is_empty():
        return

    price = chunk["price"].to_numpy()
    quantity = chunk["quantity"].to_numpy()
    transact_time = chunk["transact_time"].to_numpy()
    is_buyer_maker = chunk["is_buyer_maker"].to_numpy()

    cfg = carry.config
    alpha_imbalance = 2.0 / (cfg.expected_imbalance_window + 1.0)  # noqa: unguarded-ratio -- validado no __post_init__ de TickImbalanceBarsConfig
    alpha_bars = 2.0 / (cfg.num_prev_bars + 1.0)  # noqa: unguarded-ratio -- idem

    for i in range(chunk.height):
        b_i = -1.0 if is_buyer_maker[i] else 1.0
        if not carry.started:
            carry.ewma_b = b_i
            carry.started = True
        else:
            carry.ewma_b = alpha_imbalance * b_i + (1.0 - alpha_imbalance) * carry.ewma_b

        p = float(price[i])
        q = float(quantity[i])
        t = int(transact_time[i])
        value = p * q
        is_taker_buy = not bool(is_buyer_maker[i])

        if carry.ticks_in_bar == 0:
            carry.open_time = t
            carry.open = p
            carry.high = p
            carry.low = p
        else:
            carry.high = max(carry.high, p)
            carry.low = min(carry.low, p)
        carry.close = p
        carry.close_time = t
        carry.volume += q
        carry.quote_volume += value
        carry.count += 1
        if is_taker_buy:
            carry.taker_buy_volume += q
            carry.taker_buy_quote_volume += value

        carry.theta += b_i
        carry.ticks_in_bar += 1

        close_threshold = carry.exp_num_ticks * abs(carry.ewma_b)
        if close_threshold > 0.0 and abs(carry.theta) >= close_threshold:
            _close_tick_imbalance_bar(carry, alpha_bars)


def _close_tick_imbalance_bar(carry: TickImbalanceBarsCarry, alpha_bars: float) -> None:
    carry.bar_rows.append(
        {
            "open_time": carry.open_time,
            "close_time": carry.close_time,
            "open": carry.open,
            "high": carry.high,
            "low": carry.low,
            "close": carry.close,
            "volume": carry.volume,
            "quote_volume": carry.quote_volume,
            "count": carry.count,
            "taker_buy_volume": carry.taker_buy_volume,
            "taker_buy_quote_volume": carry.taker_buy_quote_volume,
        }
    )
    carry.exp_num_ticks = alpha_bars * carry.ticks_in_bar + (1.0 - alpha_bars) * carry.exp_num_ticks
    carry.exp_num_ticks = min(
        max(carry.exp_num_ticks, carry.config.exp_num_ticks_min), carry.config.exp_num_ticks_max
    )
    carry.ticks_in_bar = 0
    carry.theta = 0.0
    carry.volume = 0.0
    carry.quote_volume = 0.0
    carry.count = 0
    carry.taker_buy_volume = 0.0
    carry.taker_buy_quote_volume = 0.0
    carry.open = None
    carry.high = float("-inf")
    carry.low = float("inf")


def tick_imbalance_bars_finish(carry: TickImbalanceBarsCarry) -> pl.DataFrame:
    """Fecha o stream -- inclui a última barra mesmo que parcial (mesma
    convenção de `threshold_bars_finish`)."""
    if carry.ticks_in_bar > 0:
        carry.bar_rows.append(
            {
                "open_time": carry.open_time,
                "close_time": carry.close_time,
                "open": carry.open,
                "high": carry.high,
                "low": carry.low,
                "close": carry.close,
                "volume": carry.volume,
                "quote_volume": carry.quote_volume,
                "count": carry.count,
                "taker_buy_volume": carry.taker_buy_volume,
                "taker_buy_quote_volume": carry.taker_buy_quote_volume,
            }
        )
        carry.ticks_in_bar = 0
    if not carry.bar_rows:
        return _empty_bars()
    return pl.DataFrame(carry.bar_rows, schema=_BAR_OUTPUT_SCHEMA)


def tick_imbalance_bars(trades: pl.DataFrame, config: TickImbalanceBarsConfig) -> pl.DataFrame:
    """Conveniência pra um `DataFrame` só (testes, uso manual pequeno) --
    wrapper fino sobre `tick_imbalance_bars_carry`/`_step`/`_finish` com um
    único chunk. AFML cap.2: fecha uma barra quando `|theta_T| >= E_0[T] *
    |EWMA(b_t)|` -- ver docstring do módulo pra derivação completa."""
    _require_trade_columns(trades)
    carry = tick_imbalance_bars_carry(config)
    tick_imbalance_bars_step(carry, trades)
    return tick_imbalance_bars_finish(carry)
