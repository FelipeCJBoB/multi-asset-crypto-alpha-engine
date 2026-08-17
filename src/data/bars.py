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
tempo real.

**Achado de magnitude (2026-08-15) — o loop sequencial precisou de JIT.**
Rodando o M2 real pela 1ª vez sem OOM, o histórico completo de BTCUSDT
mostrou ser da ordem de bilhões de trades. Correção de proveniência
(2026-08-15, achado de auditoria externa): a extrapolação original citava
`data/quality_reports/quality_report_agg_trades_v1.json` (68,2 milhões de
trades / 53 dias) como se fosse BTCUSDT sem o arquivo declarar `symbol` —
estimativa, não medição, mesmo que o número tenha se confirmado certo.
**Medido de verdade** via `tools/diagnostics/measure_btcusdt_trade_rate.py`
direto dos 2.412 arquivos de `data/capacity/agg_trades/BTCUSDT/`
(2019-12-31 a 2026-08-07): **3.385.807.729 trades no total** (confirma "da
ordem de bilhões"), taxa média de 1.403.735 trades/dia no histórico
completo — só 1,09x a taxa da janela de 53 dias do quality_report
(1.286.169/dia, que por sua vez bateu EXATO com o quality_report,
confirmando que aquele arquivo já media BTCUSDT mesmo, só não declarava).
Um loop Python puro trade-a-trade, por mais que já evitasse iterar
`DataFrame` linha a linha (já convertia pra array numpy antes do loop),
levaria dezenas de minutos a mais de 1h só pra esse símbolo, puramente por
overhead de interpretador. `_tick_imbalance_loop` (Numba `@njit(cache=True)`,
SEM `fastmath`) resolve isso
compilando o mesmo algoritmo pra código de máquina — `fastmath=False`
(default) preserva ordem estrita de operação IEEE 754, então o resultado
é bit-a-bit idêntico ao loop Python original (confirmado por pesquisa web
antes de aplicar, não presumido) — mesmos testes de paridade, sem
afrouxar tolerância nenhuma. Estado do carry passado por escalares (não
a dataclass inteira -- `nopython` do Numba não suporta objeto Python
arbitrário), barras fechadas escritas em arrays pré-alocados no tamanho
do chunk (pior caso: toda trade fecha sua própria barra)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final, Literal

import numba
import numpy as np
import polars as pl
from numpy.typing import NDArray

from src.data._constants import load_constant as load_data_constant

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
# Dollar bars / volume bars -- vetorizado por chunk, leftover normalmente
# pequeno entre chunks (só os trades da barra ainda aberta). "Normalmente":
# sob liquidez estável isso é verdade por construção (fecha assim que
# acumula `threshold`), mas um threshold único calibrado pra MÉDIA de uma
# janela de 6+ anos não-estacionária não garante isso num sub-período de
# liquidez muito mais baixa -- achado MEDIUM de AG-034 addendum
# (2026-08-16, `audit/architecture_gaps_log.yaml`). `max_leftover_trades`/
# `LeftoverOverflowError` (abaixo) são o circuit breaker pra esse caso.
# ---------------------------------------------------------------------------


class LeftoverOverflowError(RuntimeError):
    """`ThresholdBarsCarry.leftover` cresceu além de `max_leftover_trades`
    (quando declarado) -- circuit breaker contra o achado MEDIUM da
    auditoria AG-034 (`audit/architecture_gaps_log.yaml`, addendum
    2026-08-16): threshold único global sob volume não-estacionário de 6+
    anos de histórico pode, num sub-período de liquidez muito mais baixa
    que a média calibrada, levar muitos chunks pra fechar 1 barra só --
    sem teto, `leftover` (trades brutos, não agregados) cresceria sem
    limite, o mesmo mecanismo que amplificava memória por chunk agora
    amplificado pela DURAÇÃO em vez do TAMANHO de 1 chunk só. Levantada
    dentro de `threshold_bars_step` -- quem chama decide se quer capturar
    e degradar (`NaN`, mesmo padrão de `duckdb.OutOfMemoryException` em
    `m2_worker.py`) ou deixar propagar. `max_leftover_trades=None`
    (default de `ThresholdBarsCarry`/`dollar_bars_carry`/`volume_bars_
    carry`) preserva bit-a-bit o comportamento de antes deste circuit
    breaker existir -- nenhum caller/teste existente antes desta mudança
    passava esse argumento."""


@dataclass(slots=True)
class _TradeArrays:
    """As 4 colunas necessárias de trades (`_TRADE_REQUIRED_COLUMNS`) como
    arrays numpy -- substitui o `pl.DataFrame` de 7 colunas que
    `ThresholdBarsCarry.leftover` guardava antes do redesenho de
    2026-08-16 (AG-034 addendum, achado HIGH+MEDIUM): eliminava tanto a
    materialização de um `pl.DataFrame` Polars completo por chunk quanto
    o carregamento das 3 colunas nunca usadas (`agg_trade_id`/
    `first_trade_id`/`last_trade_id`) por toda a vida do `leftover`."""

    price: FloatArray
    quantity: FloatArray
    transact_time: IntArray
    is_buyer_maker: NDArray[np.bool_]

    @property
    def n_trades(self) -> int:
        return int(self.price.shape[0])

    def to_frame(self) -> pl.DataFrame:
        """Reconstrói o `pl.DataFrame` mínimo (só as 4 colunas) que
        `_aggregate_bars` precisa -- chamado só sobre a fatia FECHADA
        (pequena) em `threshold_bars_step`, ou sobre o leftover final em
        `threshold_bars_finish`; nunca sobre o leftover inteiro entre
        chunks (que fica em numpy o tempo todo, ver docstring do módulo)."""
        return pl.DataFrame(
            {
                "transact_time": self.transact_time,
                "price": self.price,
                "quantity": self.quantity,
                "is_buyer_maker": self.is_buyer_maker,
            },
            schema={
                "transact_time": pl.Int64,
                "price": pl.Float64,
                "quantity": pl.Float64,
                "is_buyer_maker": pl.Boolean,
            },
        )


def _threshold_value(
    value_kind: Literal["dollar", "volume"], price: FloatArray, quantity: FloatArray
) -> FloatArray:
    """`"dollar"` -> `price*quantity` (valor em dólar por trade), `"volume"`
    -> `quantity` (unidades do ativo) -- mesmo papel do antigo
    `ThresholdBarsCarry.value_expr: pl.Expr` (removido no redesenho de
    2026-08-16, AG-034 addendum: `pl.Expr` só faz sentido aplicado a um
    `pl.DataFrame`/`Series` Polars; o núcleo do algoritmo agora opera em
    arrays numpy, então "qual valor" vira uma string enum simples).
    Multiplicação elementwise é comutativa e não tem redução/ordem de
    soma -- não carrega o risco de paridade bit-a-bit que `cum_sum` tem
    (ver docstring de `threshold_bars_step`)."""
    if value_kind == "dollar":
        return price * quantity
    return quantity


@dataclass(slots=True)
class ThresholdBarsCarry:
    """Estado entre chunks pra dollar/volume bars. `value_kind` decide qual
    barra (`"dollar"` ou `"volume"`, ver `_threshold_value`) -- ver
    `dollar_bars_carry`/`volume_bars_carry`. `leftover` guarda só os trades
    do bar ainda aberto, como `_TradeArrays` (arrays numpy, não mais um
    `pl.DataFrame` de 7 colunas -- ver docstring de `_TradeArrays` e do
    módulo, achado HIGH+MEDIUM de AG-034 addendum 2026-08-16); `bar_frames`
    acumula barras JÁ fechadas (agregadas, pequenas -- não trades crus).
    `base_value` é o valor total (dólar ou volume) já consumido por todas
    as barras fechadas até agora -- achado de bug (2026-08-15, teste de
    paridade `sizes=[1]*20` de `volume_bars` falhando com barra fantasma):
    uma barra só fecha quando um trade EXCEDE o threshold, não quando bate
    exatamente nele, então o "resto" acumulado ao fechar não é múltiplo do
    threshold em geral. Sem `base_value`, cada `step()` recalculava o
    cumsum do zero pra `leftover+chunk`, perdendo esse resto e fechando
    barras cedo demais sempre que o leftover sobrevivia a mais de 1 chunk
    -- não pegou no teste de `dollar_bars` só porque lá o valor por trade
    já excede o threshold (leftover nunca sobrevive), mascarando o bug por
    coincidência dos dados. `max_leftover_trades` (`None` = sem teto,
    default -- preserva bit-a-bit todo caller/teste existente antes deste
    circuit breaker) é o teto do achado MEDIUM de AG-034 addendum -- ver
    `LeftoverOverflowError`."""

    threshold: float
    value_kind: Literal["dollar", "volume"]
    leftover: _TradeArrays | None = None
    base_value: float = 0.0
    bar_frames: list[pl.DataFrame] = field(default_factory=list)
    max_leftover_trades: float | None = None

    @property
    def leftover_trade_count(self) -> int:
        """Diagnóstico exposto pro chamador (`m2_worker.py`) logar por
        chunk -- achado MEDIUM de AG-034 addendum: "nenhum sinal
        diagnóstico pro crescimento de `leftover`, nenhuma blindagem fora
        do DuckDB". `bars.py` continua sem `structlog` (módulo de
        computação pura, ver docstring do módulo) -- só expõe o número;
        quem loga é quem chama."""
        return 0 if self.leftover is None else self.leftover.n_trades


def dollar_bars_carry(
    *, threshold: float, max_leftover_trades: float | None = None
) -> ThresholdBarsCarry:
    if threshold <= 0:
        raise ValueError(f"threshold precisa ser > 0, recebido {threshold}")
    return ThresholdBarsCarry(
        threshold=threshold, value_kind="dollar", max_leftover_trades=max_leftover_trades
    )


def volume_bars_carry(
    *, threshold: float, max_leftover_trades: float | None = None
) -> ThresholdBarsCarry:
    if threshold <= 0:
        raise ValueError(f"threshold precisa ser > 0, recebido {threshold}")
    return ThresholdBarsCarry(
        threshold=threshold, value_kind="volume", max_leftover_trades=max_leftover_trades
    )


def threshold_bars_step(carry: ThresholdBarsCarry, chunk: pl.DataFrame) -> None:
    """Processa 1 chunk de trades (ordenado por `transact_time`, mesma
    garantia de `lake.query_agg_trades`) -- muta `carry` in place. Chunk
    vazio (dia sem trade) é no-op seguro.

    **Redesenho AG-034 addendum (2026-08-16) -- numpy, não mais Polars, no
    núcleo do algoritmo.** Achado HIGH de auditoria: a versão anterior
    fazia `pl.concat([leftover, chunk])` + `cum_sum()` + `with_columns` +
    DOIS `.filter()` -- mantinha 3-4 cópias do CHUNK inteiro (não do
    estado acumulado) vivas ao mesmo tempo, ~2-3GB por cópia num chunk de
    30 dias de BTCUSDT (~42M linhas), sob até 12 processos concorrentes.
    Aqui: (1) as 4 colunas necessárias saem do `chunk` Polars como array
    numpy imediatamente, soltando a referência ao `chunk` cedo; (2)
    concatenação com o leftover é `np.concatenate`, não `pl.concat`; (3)
    `cum_sum` vira `np.cumsum` (paridade bit-a-bit verificada, ver nota
    abaixo); (4) o split entre "fechado"/"novo leftover" é 1 busca binária
    (`np.searchsorted`) + 2 slices (view, não cópia) -- não mais dois
    `.filter()` (busca linear O(n) cada, aloca máscara booleana). Só a
    fatia FECHADA (pequena) vira `pl.DataFrame` pra `_aggregate_bars`
    (reaproveitado, já vetorizado via `group_by`) -- o leftover nunca mais
    materializa como `pl.DataFrame` entre chunks.

    **Paridade bit-a-bit `np.cumsum` vs `pl.Series.cum_sum()` (verificado
    por leitura de código-fonte, não presumido):** ambos são acumulação
    sequencial estrita esquerda-pra-direita sobre float64, sem SIMD/
    paralelismo/redução em árvore. Confirmado lendo o source Rust real de
    polars na tag `py-1.43.2` (a versão travada em `uv.lock`),
    `crates/polars-ops/src/series/ops/cum_agg.rs`: `cum_sum_numeric` ->
    `cum_scan_numeric` -> `ca.iter().map(|v| { *state += v; state
    }).collect_trusted()` -- um único acumulador mutável (`det_sum`), sem
    `rayon`/`par_iter`, sem chunking paralelo. `np.cumsum` (via `np.add.
    accumulate`) é sequencial pela própria definição matemática de cumsum
    -- precisa devolver TODA soma parcial, não só o total, ao contrário de
    `np.sum`/`np.add.reduce` (que usa soma pairwise/em árvore, correta só
    pro TOTAL final). Mesma sequência de valores (mesma ordem de linha --
    `to_numpy()` preserva ordem de linha; `price*quantity` é multiplicação
    elementwise, comutativa, sem risco de reordenação) processada pelo
    mesmo algoritmo de acumulação nos dois lados -> resultado bit-a-bit
    idêntico. O teste de paridade streaming<->lote (`test_data_bars.py`)
    cobre isso empiricamente também, além desta verificação de código-
    fonte.

    **Busca binária -- prova de equivalência com o filtro duplo antigo:**
    `bar_id` é monotonicamente não-decrescente (`cum_value` é soma
    acumulada de valores >=0, ver docstring do módulo) e `max_bar_id =
    bar_id[-1]` é, por definição, o MAIOR valor da série inteira (não só o
    último elemento por coincidência -- é o máximo porque a série é não-
    decrescente e termina nele). `np.searchsorted(bar_id, max_bar_id,
    side="left")` acha o índice mais à esquerda onde `bar_id >=
    max_bar_id`; como não existe valor MAIOR que o máximo, esse é o índice
    mais à esquerda onde `bar_id == max_bar_id`. Tudo ANTES desse índice
    tem `bar_id < max_bar_id` (definição de "mais à esquerda"), tudo DELE
    EM DIANTE tem `bar_id == max_bar_id` (não pode haver valor maior) --
    exatamente a partição que `filter(_bar_id < max_bar_id)` /
    `filter(_bar_id == max_bar_id)` produzia, só que com 1 busca binária
    O(log n) + 2 slices O(1) em vez de 2 buscas lineares O(n) + 2 máscaras
    booleanas alocadas (ver `test_data_bars.py` pro teste que prova essa
    equivalência num caso com várias barras fechando no mesmo chunk)."""
    _require_trade_columns(chunk)
    if chunk.is_empty():
        return

    # As 4 colunas necessárias saem do `chunk` Polars como array numpy já
    # aqui -- solta a referência ao DataFrame original o quanto antes
    # (mesmo padrão de `tick_imbalance_bars_step`, linhas acima). `.to_
    # numpy()` sobre coluna Float64/Int64/Boolean sem nulls é zero-copy
    # (ou, na pior hipótese, uma cópia byte-a-byte dos mesmos bits IEEE
    # 754/inteiros) -- de qualquer forma os VALORES são idênticos ao
    # `pl.Series` original, só a materialização Polars completa (7
    # colunas, várias cópias) que este redesenho elimina.
    price_chunk = chunk["price"].to_numpy()
    quantity_chunk = chunk["quantity"].to_numpy()
    transact_time_chunk = chunk["transact_time"].to_numpy().astype(np.int64)
    is_buyer_maker_chunk = chunk["is_buyer_maker"].to_numpy()

    if carry.leftover is not None and carry.leftover.n_trades > 0:
        price = np.concatenate([carry.leftover.price, price_chunk])
        quantity = np.concatenate([carry.leftover.quantity, quantity_chunk])
        transact_time = np.concatenate([carry.leftover.transact_time, transact_time_chunk])
        is_buyer_maker = np.concatenate([carry.leftover.is_buyer_maker, is_buyer_maker_chunk])
    else:
        price, quantity, transact_time, is_buyer_maker = (
            price_chunk,
            quantity_chunk,
            transact_time_chunk,
            is_buyer_maker_chunk,
        )

    value = _threshold_value(carry.value_kind, price, quantity)
    local_cum = np.cumsum(value)
    # soma o valor ja consumido por barras fechadas (`base_value`) antes de
    # dividir pelo threshold -- sem isso, cada chunk recomeca o cumsum do
    # zero e perde o "resto" de barras que fecharam sem bater exatamente no
    # multiplo do threshold, fechando barra fantasma cedo demais (ver
    # docstring de `ThresholdBarsCarry`).
    cum_value = local_cum + carry.base_value
    # carry.threshold > 0 garantido por dollar_bars_carry/volume_bars_carry
    # (único jeito de construir ThresholdBarsCarry) antes de chegar aqui.
    bar_id_float = cum_value // carry.threshold  # noqa: unguarded-ratio
    # Achado MEDIUM de revisão independente (project_assurance, 2026-08-16):
    # `.astype(np.int64)` sobre float64 fora do range de int64 é
    # comportamento indefinido/dependente de plataforma em numpy (não
    # levanta exceção -- a versão anterior usava `pl.Series.cast(pl.Int64)`,
    # que falha alto em overflow por padrão, `strict=True`). Inalcançável
    # pelo único caller de produção hoje (`m2_worker.py` deriva `threshold`
    # de `totals/target_n_bars`, mantendo `bar_id` na ordem de
    # `target_n_bars`, muito abaixo do teto int64), mas `threshold_bars_
    # step` é primitiva pública -- `cum_value[-1]` é sempre o maior valor
    # da série (monotonicidade, ver abaixo), então checar só esse elemento
    # basta pra garantir a série inteira.
    if bar_id_float[-1] > np.iinfo(np.int64).max:
        raise OverflowError(
            f"bar_id excederia o teto de int64 (cum_value={cum_value[-1]!r}, "
            f"threshold={carry.threshold!r}) -- risco de truncamento silencioso "
            "sob np.astype; verifique threshold/base_value antes de prosseguir"
        )
    bar_id = bar_id_float.astype(np.int64)
    # cum_value e' soma acumulada de valores >=0 (preco*quantidade ou
    # quantidade) -- monotonica nao-decrescente, entao bar_id tambem e';
    # max_bar_id e' sempre o maior valor da serie inteira (nao so o
    # ultimo elemento por coincidencia -- ver docstring desta funcao).
    max_bar_id = bar_id[-1]
    split_idx = int(np.searchsorted(bar_id, max_bar_id, side="left"))

    # Checagem do circuit breaker ANTES de qualquer mutação de `carry` --
    # achado de revisão pessoal (2026-08-16, antes desta função ser
    # considerada pronta): a ordem original (checar depois de já ter
    # atualizado `bar_frames`/`base_value`) deixava `carry` num estado
    # inconsistente sempre que `LeftoverOverflowError` disparava no mesmo
    # step em que uma ou mais barras também fechavam -- `bar_frames`/
    # `base_value` já refletiam as barras novas, mas `leftover` continuava
    # o valor de ANTES deste step, dessincronizado dos outros dois campos.
    # Inofensivo hoje (o único chamador, `m2_worker.py`, descarta `carry`
    # inteiro ao capturar a exceção, mesmo padrão de
    # `duckdb.OutOfMemoryException`), mas `threshold_bars_step` é uma
    # primitiva -- deveria ser tudo-ou-nada por conta própria, não por
    # sorte do único caller de hoje nunca tentar reusar `carry` após
    # capturar. Calcular o tamanho do novo leftover não exige construir
    # `_TradeArrays` primeiro (é só `len(price) - split_idx`), então dá pra
    # checar e falhar ANTES de tocar `carry` -- sem custo extra.
    new_leftover_size = price.shape[0] - split_idx
    if carry.max_leftover_trades is not None and new_leftover_size > carry.max_leftover_trades:
        raise LeftoverOverflowError(
            "ThresholdBarsCarry.leftover excederia max_leftover_trades -- "
            f"threshold={carry.threshold}, len(new_leftover)={new_leftover_size}, "
            f"max_leftover_trades={carry.max_leftover_trades} (carry não modificado)"
        )

    if split_idx > 0:
        closed_arrays = _TradeArrays(
            price=price[:split_idx],
            quantity=quantity[:split_idx],
            transact_time=transact_time[:split_idx],
            is_buyer_maker=is_buyer_maker[:split_idx],
        )
        carry.bar_frames.append(_aggregate_bars(closed_arrays.to_frame(), bar_id[:split_idx]))
        # bar_id e' monotonico nao-decrescente -> a fatia [:split_idx] e'
        # sempre um prefixo; cum_value[split_idx-1] e' o valor acumulado
        # exatamente ate o fim da ultima barra fechada, o novo base_value
        # (equivalente a cum_value[closed.height-1] da versao com filter,
        # onde closed.height == split_idx aqui).
        carry.base_value = float(cum_value[split_idx - 1])

    carry.leftover = _TradeArrays(
        price=price[split_idx:],
        quantity=quantity[split_idx:],
        transact_time=transact_time[split_idx:],
        is_buyer_maker=is_buyer_maker[split_idx:],
    )


def threshold_bars_finish(carry: ThresholdBarsCarry) -> pl.DataFrame:
    """Fecha o stream -- inclui a última barra mesmo que parcial (nunca
    atingiu `threshold`; mesma convenção de `dollar_bars`/`volume_bars`
    não-streaming: toda trade pertence a alguma barra). Lê `carry.leftover`
    como `_TradeArrays` (arrays numpy), não mais `pl.DataFrame`."""
    if carry.leftover is not None and carry.leftover.n_trades > 0:
        leftover = carry.leftover
        leftover_bar_id = np.zeros(leftover.n_trades, dtype=np.int64)
        carry.bar_frames.append(_aggregate_bars(leftover.to_frame(), leftover_bar_id))
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
        # Achado de auditoria (2026-08-15, project_assurance): a guarda antiga
        # em _tick_imbalance_loop ("close_threshold > 0.0") blindava contra
        # DUAS causas possíveis de close_threshold<=0 -- ewma_b==0 (mercado,
        # ver bars_tick_imbalance_ewma_floor abaixo) OU exp_num_ticks<=0
        # (config malformada). O piso numérico de ewma_b só cobre a 1ª causa
        # -- esta validação fecha a 2ª na CONSTRUÇÃO da config, não
        # silenciosamente dentro do loop JIT. Hoje o único chamador real
        # (m2_worker._build_tick_imbalance_config) já garante isso por fora
        # (exp_num_ticks_min/max derivados de exp_num_ticks_init/clip_mult,
        # ambos >0) -- esta checagem existe pra qualquer chamador futuro não
        # herdar essa garantia por acidente.
        if self.exp_num_ticks_min <= 0:
            raise ValueError(
                f"exp_num_ticks_min precisa ser > 0, recebido {self.exp_num_ticks_min}"
            )
        if self.exp_num_ticks_max < self.exp_num_ticks_min:
            raise ValueError(
                f"exp_num_ticks_max ({self.exp_num_ticks_max}) precisa ser >= "
                f"exp_num_ticks_min ({self.exp_num_ticks_min})"
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
    causalidade "só olha pra trás" através de fronteiras de chunk.
    `open_time`/`close_time`/`open` são `int`/`float` concretos, não
    `Optional` -- o valor antes do 1º trade nunca é lido (`ticks_in_bar
    ==0` sempre reseta os três no próximo trade processado), e o núcleo
    Numba (`_tick_imbalance_loop`) não representa `Optional` em escalar
    passado por argumento. `bar_frames` guarda barras JÁ fechadas como
    `DataFrame`s pequenos por chunk (mesmo padrão de `ThresholdBarsCarry.
    bar_frames`), não mais uma lista de dicts."""

    config: TickImbalanceBarsConfig
    theta: float = 0.0
    ewma_b: float = 0.0
    exp_num_ticks: float = 0.0
    ticks_in_bar: int = 0
    started: bool = False
    open_time: int = 0
    close_time: int = 0
    open: float = 0.0
    high: float = float("-inf")
    low: float = float("inf")
    close: float = 0.0
    volume: float = 0.0
    quote_volume: float = 0.0
    count: int = 0
    taker_buy_volume: float = 0.0
    taker_buy_quote_volume: float = 0.0
    bar_frames: list[pl.DataFrame] = field(default_factory=list)


def tick_imbalance_bars_carry(config: TickImbalanceBarsConfig) -> TickImbalanceBarsCarry:
    return TickImbalanceBarsCarry(config=config, exp_num_ticks=config.exp_num_ticks_init)


_TickImbalanceLoopResult = tuple[
    float,
    float,
    float,
    int,
    bool,
    int,
    int,
    float,
    float,
    float,
    float,
    float,
    float,
    int,
    float,
    float,
    int,
]


@numba.njit(cache=True)
def _tick_imbalance_loop(
    price: FloatArray,
    quantity: FloatArray,
    transact_time: IntArray,
    is_buyer_maker: NDArray[np.bool_],
    alpha_imbalance: float,
    alpha_bars: float,
    exp_num_ticks_min: float,
    exp_num_ticks_max: float,
    ewma_floor: float,
    theta: float,
    ewma_b: float,
    exp_num_ticks: float,
    ticks_in_bar: int,
    started: bool,
    open_time: int,
    close_time: int,
    open_: float,
    high: float,
    low: float,
    close: float,
    volume: float,
    quote_volume: float,
    count: int,
    taker_buy_volume: float,
    taker_buy_quote_volume: float,
    out_open_time: IntArray,
    out_close_time: IntArray,
    out_open: FloatArray,
    out_high: FloatArray,
    out_low: FloatArray,
    out_close: FloatArray,
    out_volume: FloatArray,
    out_quote_volume: FloatArray,
    out_count: IntArray,
    out_taker_buy_volume: FloatArray,
    out_taker_buy_quote_volume: FloatArray,
) -> _TickImbalanceLoopResult:
    """Núcleo JIT (Numba, achado de auditoria 2026-08-15 -- ver docstring
    do módulo) do loop trade-a-trade que era `tick_imbalance_bars_step`.
    `nopython` não suporta a dataclass `TickImbalanceBarsCarry` nem
    `Optional` -- estado passado por escalares, devolvido em tupla na
    MESMA ordem dos parâmetros de entrada (+ `n_closed` no fim). Barras
    fechadas escritas nos arrays `out_*` (pré-alocados pelo chamador,
    tamanho = nº de trades do chunk -- pior caso: toda trade fecha sua
    própria barra); `n_closed` diz quantas posições são válidas. SEM
    `fastmath` (default `False`) -- ordem estrita de operação IEEE 754,
    mesmo resultado bit-a-bit do loop Python que este núcleo substitui
    (confirmado por pesquisa web antes de aplicar, não presumido)."""
    n = price.shape[0]
    n_closed = 0
    for i in range(n):
        buyer_maker = is_buyer_maker[i]
        b_i = -1.0 if buyer_maker else 1.0
        if not started:
            ewma_b = b_i
            started = True
        else:
            ewma_b = alpha_imbalance * b_i + (1.0 - alpha_imbalance) * ewma_b

        p = price[i]
        q = quantity[i]
        t = transact_time[i]
        value = p * q
        is_taker_buy = not buyer_maker

        if ticks_in_bar == 0:
            open_time = t
            open_ = p
            high = p
            low = p
        else:
            if p > high:
                high = p
            if p < low:
                low = p
        close = p
        close_time = t
        volume += q
        quote_volume += value
        count += 1
        if is_taker_buy:
            taker_buy_volume += q
            taker_buy_quote_volume += value

        theta += b_i
        ticks_in_bar += 1

        # Piso de segurança numérica -- se ewma_b caísse em exatamente 0.0
        # (bit a bit), close_threshold seria 0 e a guarda `> 0.0` original
        # bloquearia o fechamento da barra pra sempre dali em diante.
        # `ewma_floor` vem de `constants.yaml::bars_tick_imbalance_ewma_
        # floor` (calculado 1x por chunk em `tick_imbalance_bars_step`,
        # passado por valor -- nopython não lê YAML). Cobre só a causa
        # "ewma_b->0" de close_threshold<=0; a causa "exp_num_ticks<=0" é
        # coberta na CONSTRUÇÃO da config (`TickImbalanceBarsConfig.
        # __post_init__`), não aqui -- as duas causas são independentes,
        # ver achado de auditoria 2026-08-15 (project_assurance).
        close_threshold = exp_num_ticks * max(abs(ewma_b), ewma_floor)
        if abs(theta) >= close_threshold:
            out_open_time[n_closed] = open_time
            out_close_time[n_closed] = close_time
            out_open[n_closed] = open_
            out_high[n_closed] = high
            out_low[n_closed] = low
            out_close[n_closed] = close
            out_volume[n_closed] = volume
            out_quote_volume[n_closed] = quote_volume
            out_count[n_closed] = count
            out_taker_buy_volume[n_closed] = taker_buy_volume
            out_taker_buy_quote_volume[n_closed] = taker_buy_quote_volume
            n_closed += 1

            exp_num_ticks = alpha_bars * ticks_in_bar + (1.0 - alpha_bars) * exp_num_ticks
            exp_num_ticks = min(max(exp_num_ticks, exp_num_ticks_min), exp_num_ticks_max)
            ticks_in_bar = 0
            theta = 0.0
            volume = 0.0
            quote_volume = 0.0
            count = 0
            taker_buy_volume = 0.0
            taker_buy_quote_volume = 0.0
            high = -np.inf
            low = np.inf

    return (
        theta,
        ewma_b,
        exp_num_ticks,
        ticks_in_bar,
        started,
        open_time,
        close_time,
        open_,
        high,
        low,
        close,
        volume,
        quote_volume,
        count,
        taker_buy_volume,
        taker_buy_quote_volume,
        n_closed,
    )


def tick_imbalance_bars_step(carry: TickImbalanceBarsCarry, chunk: pl.DataFrame) -> None:
    """Processa 1 chunk trade-a-trade via `_tick_imbalance_loop` (Numba
    JIT, ver docstring do módulo) -- muta `carry` in place, inclusive
    fechando barras que completam durante o chunk (acrescentadas a
    `carry.bar_frames`). Chunk vazio é no-op seguro."""
    _require_trade_columns(chunk)
    if chunk.is_empty():
        return

    price = chunk["price"].to_numpy()
    quantity = chunk["quantity"].to_numpy()
    transact_time = chunk["transact_time"].to_numpy().astype(np.int64)
    is_buyer_maker = chunk["is_buyer_maker"].to_numpy()

    cfg = carry.config
    alpha_imbalance = 2.0 / (cfg.expected_imbalance_window + 1.0)  # noqa: unguarded-ratio -- validado no __post_init__ de TickImbalanceBarsConfig
    alpha_bars = 2.0 / (cfg.num_prev_bars + 1.0)  # noqa: unguarded-ratio -- idem
    # constants.yaml, cache em memória via _constants._load_all() -- barato
    # o suficiente pra recalcular por chunk (mesmo padrão de alpha_* acima).
    ewma_floor = float(load_data_constant("bars_tick_imbalance_ewma_floor"))

    n = chunk.height
    out_open_time = np.empty(n, dtype=np.int64)
    out_close_time = np.empty(n, dtype=np.int64)
    out_open = np.empty(n, dtype=np.float64)
    out_high = np.empty(n, dtype=np.float64)
    out_low = np.empty(n, dtype=np.float64)
    out_close = np.empty(n, dtype=np.float64)
    out_volume = np.empty(n, dtype=np.float64)
    out_quote_volume = np.empty(n, dtype=np.float64)
    out_count = np.empty(n, dtype=np.int64)
    out_taker_buy_volume = np.empty(n, dtype=np.float64)
    out_taker_buy_quote_volume = np.empty(n, dtype=np.float64)

    (
        carry.theta,
        carry.ewma_b,
        carry.exp_num_ticks,
        carry.ticks_in_bar,
        carry.started,
        carry.open_time,
        carry.close_time,
        carry.open,
        carry.high,
        carry.low,
        carry.close,
        carry.volume,
        carry.quote_volume,
        carry.count,
        carry.taker_buy_volume,
        carry.taker_buy_quote_volume,
        n_closed,
    ) = _tick_imbalance_loop(
        price,
        quantity,
        transact_time,
        is_buyer_maker,
        alpha_imbalance,
        alpha_bars,
        cfg.exp_num_ticks_min,
        cfg.exp_num_ticks_max,
        ewma_floor,
        carry.theta,
        carry.ewma_b,
        carry.exp_num_ticks,
        carry.ticks_in_bar,
        carry.started,
        carry.open_time,
        carry.close_time,
        carry.open,
        carry.high,
        carry.low,
        carry.close,
        carry.volume,
        carry.quote_volume,
        carry.count,
        carry.taker_buy_volume,
        carry.taker_buy_quote_volume,
        out_open_time,
        out_close_time,
        out_open,
        out_high,
        out_low,
        out_close,
        out_volume,
        out_quote_volume,
        out_count,
        out_taker_buy_volume,
        out_taker_buy_quote_volume,
    )

    if n_closed > 0:
        carry.bar_frames.append(
            pl.DataFrame(
                {
                    "open_time": out_open_time[:n_closed],
                    "close_time": out_close_time[:n_closed],
                    "open": out_open[:n_closed],
                    "high": out_high[:n_closed],
                    "low": out_low[:n_closed],
                    "close": out_close[:n_closed],
                    "volume": out_volume[:n_closed],
                    "quote_volume": out_quote_volume[:n_closed],
                    "count": out_count[:n_closed],
                    "taker_buy_volume": out_taker_buy_volume[:n_closed],
                    "taker_buy_quote_volume": out_taker_buy_quote_volume[:n_closed],
                }
            ).cast(_BAR_OUTPUT_SCHEMA)
        )


def tick_imbalance_bars_finish(carry: TickImbalanceBarsCarry) -> pl.DataFrame:
    """Fecha o stream -- inclui a última barra mesmo que parcial (mesma
    convenção de `threshold_bars_finish`)."""
    if carry.ticks_in_bar > 0:
        carry.bar_frames.append(
            pl.DataFrame(
                {
                    "open_time": [carry.open_time],
                    "close_time": [carry.close_time],
                    "open": [carry.open],
                    "high": [carry.high],
                    "low": [carry.low],
                    "close": [carry.close],
                    "volume": [carry.volume],
                    "quote_volume": [carry.quote_volume],
                    "count": [carry.count],
                    "taker_buy_volume": [carry.taker_buy_volume],
                    "taker_buy_quote_volume": [carry.taker_buy_quote_volume],
                }
            ).cast(_BAR_OUTPUT_SCHEMA)
        )
        carry.ticks_in_bar = 0
    if not carry.bar_frames:
        return _empty_bars()
    return pl.concat(carry.bar_frames)


def tick_imbalance_bars(trades: pl.DataFrame, config: TickImbalanceBarsConfig) -> pl.DataFrame:
    """Conveniência pra um `DataFrame` só (testes, uso manual pequeno) --
    wrapper fino sobre `tick_imbalance_bars_carry`/`_step`/`_finish` com um
    único chunk. AFML cap.2: fecha uma barra quando `|theta_T| >= E_0[T] *
    |EWMA(b_t)|` -- ver docstring do módulo pra derivação completa."""
    _require_trade_columns(trades)
    carry = tick_imbalance_bars_carry(config)
    tick_imbalance_bars_step(carry, trades)
    return tick_imbalance_bars_finish(carry)
