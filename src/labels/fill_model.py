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


class TradeWindowCursor:
    """Buffer DESLIZANTE de trades — núcleo puro (`AG-227`), zero IO.

    **Problema que resolve.** `simulate_fill_from_trades` precisa dos
    trades da janela `[t_post, t_post + fill_timeout_ms]` de cada barra.
    Passar o histórico inteiro em memória não escala: BTCUSDT tem 2,19
    bilhões de trades (medido: 909.425/dia x 2.412 dias) = **35 GB** como
    numpy, e são 5 símbolos. Pré-filtrar não ajuda — com
    `fill_timeout_ms = 900_000` (15 min), a união das janelas de 223.111
    barras cobre 96,4% do dataset.

    **Por que um cursor funciona.** `build_labels_with_stats` percorre as
    barras em ordem cronológica CRESCENTE de `t_post`, e cada barra só olha
    para frente. Logo o acesso é estritamente monotônico: trades anteriores
    ao `t_post` corrente nunca mais serão consultados e podem ser
    descartados. A memória vira `O(janela)` em vez de `O(dataset)` —
    ~9.500 trades (~150 KB) para 900 s, ou ~29 MB mantendo dois dias
    inteiros de folga.

    **Contrato de uso (a casca é quem faz IO):**

        cursor = TradeWindowCursor()
        for barra in barras:                  # t_post crescente
            while cursor.needs_more(horizonte):
                cursor.feed(*carrega_proximo_dia())   # <- IO, na casca
            cursor.advance_to(t_post)          # descarta o passado
            t, p = cursor.window(t_post, horizonte)

    `feed` aceita chunks já em memória; a classe NUNCA lê disco. É a mesma
    separação de `src/data/bars.py` (Idioma B do `CLAUDE.md`): estado
    acumulativo num objeto puro, IO na borda.

    **Ordenação é precondição, não é verificada por linha.** `feed` exige
    chunks já ordenados por tempo e em ordem cronológica entre si (garantia
    de `agg_trades`, que a casca confere uma vez ao carregar). Checar por
    chamada custaria `O(n)` no caminho quente — mesma decisão de
    `simulate_fill_from_trades`."""

    __slots__ = ("_price", "_time")

    def __init__(self) -> None:
        self._time: IntArray = np.zeros(0, dtype=np.int64)
        self._price: FloatArray = np.zeros(0, dtype=np.float64)

    @property
    def n_buffered(self) -> int:
        return int(self._time.shape[0])

    @property
    def last_time_ms(self) -> int | None:
        """Maior `transact_time` no buffer, ou `None` se vazio — é o que
        `needs_more` compara contra o horizonte pedido."""
        return int(self._time[-1]) if self._time.shape[0] else None

    def feed(self, time_ms: IntArray, price: FloatArray) -> None:
        """Anexa um chunk ao fim do buffer. Chunk vazio é no-op."""
        if time_ms.shape[0] != price.shape[0]:
            raise ValueError(
                f"TradeWindowCursor.feed: time_ms tem {time_ms.shape[0]} entradas e "
                f"price tem {price.shape[0]} -- precisam ser paralelos"
            )
        if time_ms.shape[0] == 0:
            return
        self._time = np.concatenate((self._time, time_ms.astype(np.int64)))
        self._price = np.concatenate((self._price, price.astype(np.float64)))

    def needs_more(self, horizon_ms: int) -> bool:
        """`True` se o buffer ainda não cobre `horizon_ms` — sinal para a
        casca alimentar mais um chunk. Buffer vazio sempre precisa de mais."""
        last = self.last_time_ms
        return last is None or last < horizon_ms

    def advance_to(self, t_from_ms: int) -> None:
        """Descarta trades com `transact_time <= t_from_ms` — eles nunca
        mais serão consultados, porque `t_post` só cresce.

        `<=` e não `<`: a janela de fill é ESTRITAMENTE posterior a
        `t_post` (mesma convenção de `simulate_fill_arrays` e
        `simulate_fill_from_trades`), então um trade exatamente em
        `t_post` já é inelegível e pode sair."""
        if self._time.shape[0] == 0:
            return
        keep_from = int(np.searchsorted(self._time, t_from_ms, side="right"))
        if keep_from > 0:
            self._time = self._time[keep_from:]
            self._price = self._price[keep_from:]

    def window(self, t_from_ms: int, t_to_ms: int) -> tuple[IntArray, FloatArray]:
        """Fatia `(t_from_ms, t_to_ms]` do buffer, pronta para
        `simulate_fill_from_trades`. Devolve VIEWS do buffer (sem cópia) —
        o consumidor não deve mutá-las."""
        lo = int(np.searchsorted(self._time, t_from_ms, side="right"))
        hi = int(np.searchsorted(self._time, t_to_ms, side="right"))
        return self._time[lo:hi], self._price[lo:hi]


def simulate_fill_from_trades(
    trade_time_ms: IntArray,
    trade_price: FloatArray,
    *,
    t_post_ms: int,
    horizon_ms: int,
    limit_price: float,
    side: int,
) -> FillResult:
    """Núcleo puro (Idioma A) — MESMA pergunta de `simulate_fill_arrays`,
    resolvida sobre `agg_trades` (granularidade de TRADE) em vez de
    `mark_1m` (granularidade de MINUTO). `AG-221`.

    **Por que existe (achado medido, 2026-08-25).** `t_post` é o
    `close_time` da dollar bar — instante ARBITRÁRIO, não alinhado ao
    relógio. `simulate_fill_arrays` só oferece oportunidade de fill em
    candles de `mark_1m` com `open_time` ESTRITAMENTE posterior a
    `t_post`, então existe uma espera FORÇADA entre a decisão e a primeira
    janela observável, uniformemente distribuída em `[0, 60s]`. Essa
    espera é pura fase de relógio e **não existe em produção**, onde a
    ordem é postada imediatamente.

    O efeito foi medido em BTCUSDT/R1 e é de primeira ordem — `ret_gross`
    é função monotônica dessa espera:

    | espera   | P(TP)  | ret_gross |
    |----------|--------|-----------|
    | 0-10s    | 0,4687 | -2,64 bps |
    | 50-60s   | 0,4242 | -6,94 bps |

    Gradiente de -4,30 bps em 60 segundos. Três verificações descartaram
    explicações alternativas: (1) o ATR mediano é constante entre as
    faixas (0,002494-0,002525), então não é regime de volatilidade;
    (2) o gradiente sobrevive DENTRO dos 5 quintis de volatilidade,
    monotônico em todos; (3) o gradiente ESCALA com a volatilidade
    (-1,82 bps no quintil mais calmo, -5,74 no mais volátil) — predição
    do mecanismo (o preço se desloca proporcionalmente a sigma durante a
    janela não-observada), confirmada fora do argumento original.

    **Diferença de contrato para `simulate_fill_arrays`:** aqui o toque é
    contra o PREÇO EXECUTADO de um trade real, não contra o intervalo
    `[low, high]` de um candle agregado. Isso remove a espera sintética na
    origem e é estritamente mais próximo da execução real — mas mantém
    deliberadamente as MESMAS simplificações do modelo atual, para que a
    única variável que muda seja a granularidade: sem modelo de fila, sem
    profundidade de book, `fill_price == limit_price` sempre. Modelar fila
    continua sendo Sprint 9.

    Janela: trades com `transact_time` estritamente posterior a
    `t_post_ms` e até `horizon_ms` inclusive — MESMA convenção de
    `simulate_fill_arrays`, para que a comparação entre os dois seja
    limpa (só a fonte muda).

    `side=1` (compra/long): preenche no primeiro trade com `price <=
    limit_price`. `side=-1` (venda/short): primeiro com `price >=
    limit_price`.

    `trade_time_ms`/`trade_price` precisam estar ordenados por tempo
    ascendente (garantia de `agg_trades`, verificada pelo chamador) —
    `argmax` sobre booleano devolve o primeiro `True`, que só é "primeiro
    cronológico" se a ordem valer."""
    if side not in (1, -1):
        raise ValueError(f"side deve ser 1 (compra) ou -1 (venda), recebido {side}")
    if horizon_ms <= t_post_ms:
        raise ValueError(
            f"horizon_ms ({horizon_ms}) deve ser posterior a t_post_ms ({t_post_ms})"
        )

    lo = int(np.searchsorted(trade_time_ms, t_post_ms, side="right"))
    hi = int(np.searchsorted(trade_time_ms, horizon_ms, side="right"))
    if hi <= lo:
        return FillResult(None, None)

    window_price = trade_price[lo:hi]
    touch = window_price <= limit_price if side == 1 else window_price >= limit_price
    if not bool(touch.any()):
        return FillResult(None, None)

    idx = int(np.argmax(touch))
    return FillResult(int(trade_time_ms[lo + idx]), float(limit_price))


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
