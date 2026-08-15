"""Testes de `src/data/bars.py` -- PRD_V4_1.md §3.2 M2. Determinismo e
causalidade de `dollar_bars`/`volume_bars` (partição vetorizada, conferida
à mão) e `tick_imbalance_bars` (loop sequencial AFML, traçado à mão com
`expected_imbalance_window=1`/`num_prev_bars=1` -- ambos com alpha de EWMA
=1,0, ou seja EWMA vira substituição direta pelo valor mais recente, o
suficiente para reduzir o algoritmo adaptativo a aritmética verificável na
mão sem perder nenhuma etapa real do fechamento de barra). Também prova a
propriedade mais importante do redesenho em streaming (achado de auditoria
2026-08-15, aggTrades não cabe em memória de uma vez): processar em N
chunks pequenos precisa produzir EXATAMENTE o mesmo resultado que processar
tudo de uma vez -- `test_..._streaming_bate_com_lote_*`."""

from __future__ import annotations

import polars as pl
import pytest

from src.data.bars import (
    TickImbalanceBarsConfig,
    dollar_bars,
    dollar_bars_carry,
    threshold_bars_finish,
    threshold_bars_step,
    tick_imbalance_bars,
    tick_imbalance_bars_carry,
    tick_imbalance_bars_finish,
    tick_imbalance_bars_step,
    volume_bars,
    volume_bars_carry,
)


def _trades(
    *, price: list[float], quantity: list[float], is_buyer_maker: list[bool]
) -> pl.DataFrame:
    n = len(price)
    assert len(quantity) == n and len(is_buyer_maker) == n
    # schema explícito -- sem isso, `is_buyer_maker=[]` infere dtype Null
    # (não Boolean), e `_aggregate_bars` quebra em `~pl.col("is_buyer_
    # maker")`. Dado real de `lake.query_agg_trades` sempre carrega o
    # schema AGG_TRADES fixo mesmo com 0 linhas (parquet preserva tipo);
    # este helper de teste precisa fazer o mesmo pra não fabricar um
    # cenário que não existe em produção.
    return pl.DataFrame(
        {
            "transact_time": list(range(n)),
            "price": price,
            "quantity": quantity,
            "is_buyer_maker": is_buyer_maker,
        },
        schema={
            "transact_time": pl.Int64,
            "price": pl.Float64,
            "quantity": pl.Float64,
            "is_buyer_maker": pl.Boolean,
        },
    )


def _chunk(trades: pl.DataFrame, sizes: list[int]) -> list[pl.DataFrame]:
    """Fatia `trades` em pedaços de tamanho `sizes` (soma == trades.height),
    simulando o que `m2_bar_comparison.py` recebe de `lake.query_agg_trades`
    dia a dia -- tamanhos DESIGUAIS de propósito (dia real não tem sempre o
    mesmo nº de trades), inclusive testando chunk vazio no meio."""
    assert sum(sizes) == trades.height, (sizes, trades.height)
    chunks = []
    offset = 0
    for size in sizes:
        chunks.append(trades.slice(offset, size))
        offset += size
    return chunks


def test_dollar_bars_particao_bate_com_calculo_manual() -> None:
    # value = price*quantity = 50 em cada trade; cumsum = [50,100,150,200];
    # threshold=100 -> bar_id = floor(cumsum/100) = [0,1,1,2]
    trades = _trades(price=[10.0] * 4, quantity=[5.0] * 4, is_buyer_maker=[False] * 4)
    bars = dollar_bars(trades, threshold=100.0)

    assert bars.height == 3
    assert bars["count"].to_list() == [1, 2, 1]
    assert bars["volume"].to_list() == pytest.approx([5.0, 10.0, 5.0])
    assert bars["open"].to_list() == pytest.approx([10.0, 10.0, 10.0])
    assert bars["close"].to_list() == pytest.approx([10.0, 10.0, 10.0])


def test_volume_bars_particao_bate_com_calculo_manual() -> None:
    # cumsum(quantity) = [3,6,9,12]; threshold=5 -> bar_id = [0,1,1,2]
    trades = _trades(price=[1.0, 2.0, 3.0, 4.0], quantity=[3.0] * 4, is_buyer_maker=[False] * 4)
    bars = volume_bars(trades, threshold=5.0)

    assert bars.height == 3
    assert bars["count"].to_list() == [1, 2, 1]
    assert bars["open"].to_list() == pytest.approx([1.0, 2.0, 4.0])
    assert bars["high"].to_list() == pytest.approx([1.0, 3.0, 4.0])
    assert bars["low"].to_list() == pytest.approx([1.0, 2.0, 4.0])
    assert bars["close"].to_list() == pytest.approx([1.0, 3.0, 4.0])


@pytest.mark.parametrize("fn", [dollar_bars, volume_bars])
def test_threshold_invalido_levanta_erro(fn) -> None:  # type: ignore[no-untyped-def]
    trades = _trades(price=[1.0], quantity=[1.0], is_buyer_maker=[False])
    with pytest.raises(ValueError, match="threshold"):
        fn(trades, threshold=0.0)


def test_dollar_bars_particao_preserva_todos_os_trades_sem_sobreposicao() -> None:
    """Causalidade/completude: cada trade pertence a exatamente 1 barra, e
    open_time/close_time das barras não se sobrepõem nem pulam trades --
    proxy direto de "bar_id não depende de trade futuro"."""
    trades = _trades(
        price=[10.0, 11.0, 9.0, 12.0, 8.0, 13.0],
        quantity=[1.0, 2.0, 3.0, 1.0, 2.0, 3.0],
        is_buyer_maker=[False, True, False, True, False, True],
    )
    bars = dollar_bars(trades, threshold=15.0)

    assert bars["count"].sum() == trades.height
    close_times = bars["close_time"].to_list()
    open_times = bars["open_time"].to_list()
    for i in range(1, len(bars)):
        assert open_times[i] > close_times[i - 1]


def test_tick_imbalance_bars_fecha_barra_no_limiar_esperado_tracado_a_mao() -> None:
    """expected_imbalance_window=1 -> EWMA(b_t) = b_t exato (alpha=1,0,
    sem memória); num_prev_bars=1 -> exp_num_ticks pós-fechamento também
    vira substituição direta pelo tamanho da barra que acabou de fechar
    (alpha=1,0). Com isso o algoritmo adaptativo colapsa em aritmética
    determinística, traçada à mão no docstring de
    `test_data_bars.py` (ver mensagem do commit/PR para o traço completo):

    b = [+1,+1,+1, -1,-1,+1,+1,+1,+1,+1] (10 trades)
    exp_num_ticks_init=3 -> barra 1 fecha em i=2 (theta chega a 3, 3 ticks)
    exp_num_ticks vira 3 (tamanho da barra 1) -> barra 2 precisa |theta|>=3
    de novo; só fecha em i=9 (theta oscila -2..3, chega a +3 na 7ª trade
    da barra), com 7 ticks. Fim da série sem barra 3."""
    price = [100.0, 101.0, 102.0, 99.0, 98.0, 97.0, 103.0, 104.0, 105.0, 106.0]
    is_buyer_maker = [False, False, False, True, True, False, False, False, False, False]
    trades = _trades(price=price, quantity=[1.0] * 10, is_buyer_maker=is_buyer_maker)

    config = TickImbalanceBarsConfig(
        num_prev_bars=1,
        expected_imbalance_window=1,
        exp_num_ticks_init=3.0,
        exp_num_ticks_min=1.0,
        exp_num_ticks_max=100.0,
    )
    bars = tick_imbalance_bars(trades, config)

    assert bars.height == 2
    assert bars["count"].to_list() == [3, 7]
    assert bars["open"].to_list() == pytest.approx([100.0, 99.0])
    assert bars["high"].to_list() == pytest.approx([102.0, 106.0])
    assert bars["low"].to_list() == pytest.approx([100.0, 97.0])
    assert bars["close"].to_list() == pytest.approx([102.0, 106.0])
    # bar 2 (indices 3..9): taker-buy (is_buyer_maker=False) em 5,6,7,8,9
    assert bars["taker_buy_volume"].to_list() == pytest.approx([3.0, 5.0])


def test_tick_imbalance_bars_fluxo_balanceado_ewma_pequeno_nao_trava() -> None:
    """Achado de auditoria (`project_assurance`, 2026-08-15): TODOS os
    testes de TIB até aqui usam `expected_imbalance_window=1`, que colapsa
    `alpha_imbalance` pra 1,0 -- `ewma_b` vira substituição direta por
    `b_t` (sempre exatamente +-1,0), nunca exercitando a suavização EWMA
    de verdade nem se aproximando de zero. `bars_tick_imbalance_ewma_floor`
    (piso numérico contra `ewma_b==0`, ver `constants.yaml`) não tinha
    NENHUM teste cobrindo a região onde ele poderia atuar.

    Este teste usa `expected_imbalance_window=99` (`alpha~=0,02`, EWMA de
    verdade) com fluxo de ordem quase perfeitamente alternado (regime que
    a literatura mlfinlab documenta como real em mercado balanceado, não
    hipotético) -- não força `ewma_b` a chegar literalmente em `1e-12`
    (isso exigiria uma sequência muito mais longa e uma amplitude de
    convergência específica, impraticável num teste sintético), mas
    exercita a suavização EWMA numa faixa ordens de magnitude menor que
    qualquer teste anterior. Prova: (1) sem exceção/hang; (2) barras
    fecham (`height>0`); (3) paridade streaming<->lote se mantém também
    NESTE regime, não só no traçado à mão com alpha=1,0."""
    n = 200
    price = [100.0 + 0.1 * ((i * 7) % 5) for i in range(n)]
    quantity = [1.0] * n
    is_buyer_maker = [i % 2 == 0 for i in range(n)]  # alterna b_i: -1,+1,-1,+1,...
    trades = _trades(price=price, quantity=quantity, is_buyer_maker=is_buyer_maker)

    config = TickImbalanceBarsConfig(
        num_prev_bars=3,
        expected_imbalance_window=99,
        exp_num_ticks_init=20.0,
        exp_num_ticks_min=1.0,
        exp_num_ticks_max=1000.0,
    )

    batch_bars = tick_imbalance_bars(trades, config)
    assert batch_bars.height > 0

    carry = tick_imbalance_bars_carry(config)
    for chunk in _chunk(trades, [50, 50, 50, 50]):
        tick_imbalance_bars_step(carry, chunk)
    streaming_bars = tick_imbalance_bars_finish(carry)

    _bars_equal(batch_bars, streaming_bars)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"num_prev_bars": 0, "expected_imbalance_window": 10, "exp_num_ticks_init": 5.0},
        {"num_prev_bars": 3, "expected_imbalance_window": 0, "exp_num_ticks_init": 5.0},
        {"num_prev_bars": 3, "expected_imbalance_window": 10, "exp_num_ticks_init": 0.0},
    ],
)
def test_tick_imbalance_bars_config_invalida_levanta_erro(kwargs: dict[str, int | float]) -> None:
    """Validação migrou pra `TickImbalanceBarsConfig.__post_init__` (fail
    fast na construção, não só quando `tick_imbalance_bars`/`_carry` é
    chamado -- protege os dois pontos de entrada agora que existem:
    wrapper de DataFrame único E o caminho em streaming) -- por isso a
    própria construção precisa estar dentro do `pytest.raises`."""
    with pytest.raises(ValueError):
        TickImbalanceBarsConfig(
            num_prev_bars=int(kwargs["num_prev_bars"]),
            expected_imbalance_window=int(kwargs["expected_imbalance_window"]),
            exp_num_ticks_init=float(kwargs["exp_num_ticks_init"]),
            exp_num_ticks_min=1.0,
            exp_num_ticks_max=100.0,
        )


@pytest.mark.parametrize(
    "exp_num_ticks_min,exp_num_ticks_max",
    [
        (0.0, 100.0),  # exp_num_ticks_min <= 0
        (-1.0, 100.0),  # exp_num_ticks_min < 0
        (50.0, 10.0),  # exp_num_ticks_max < exp_num_ticks_min
    ],
)
def test_tick_imbalance_bars_config_clip_bounds_invalidos_levanta_erro(
    exp_num_ticks_min: float, exp_num_ticks_max: float
) -> None:
    """Achado de auditoria (`project_assurance`, 2026-08-15): a guarda
    antiga em `_tick_imbalance_loop` (`close_threshold > 0.0`) blindava
    contra as DUAS causas possíveis de `close_threshold<=0` -- `ewma_b==0`
    (mercado, coberta pelo piso `bars_tick_imbalance_ewma_floor`) OU
    `exp_num_ticks<=0` (config malformada). O piso só cobre a 1ª causa --
    esta validação fecha a 2ª na CONSTRUÇÃO da config, antes mesmo do
    `__post_init__` deste teste ser adicionado ela não existia."""
    with pytest.raises(ValueError):
        TickImbalanceBarsConfig(
            num_prev_bars=3,
            expected_imbalance_window=10,
            exp_num_ticks_init=5.0,
            exp_num_ticks_min=exp_num_ticks_min,
            exp_num_ticks_max=exp_num_ticks_max,
        )


def test_dollar_bars_dataframe_vazio_devolve_vazio() -> None:
    trades = _trades(price=[], quantity=[], is_buyer_maker=[])
    bars = dollar_bars(trades, threshold=1.0)
    assert bars.height == 0


def test_tick_imbalance_bars_dataframe_vazio_devolve_vazio() -> None:
    trades = _trades(price=[], quantity=[], is_buyer_maker=[])
    config = TickImbalanceBarsConfig(
        num_prev_bars=3, expected_imbalance_window=10, exp_num_ticks_init=5.0,
        exp_num_ticks_min=1.0, exp_num_ticks_max=100.0,
    )
    bars = tick_imbalance_bars(trades, config)
    assert bars.height == 0


def test_dollar_bars_sem_coluna_obrigatoria_levanta_erro() -> None:
    trades = pl.DataFrame({"price": [1.0], "quantity": [1.0]})
    with pytest.raises(ValueError, match="coluna"):
        dollar_bars(trades, threshold=1.0)


# ============================================================================
# Paridade streaming <-> lote -- a propriedade central do redesenho
# (auditoria 2026-08-15: aggTrades de BTC/ETH não cabem em memória de uma
# vez, 27GB/20GB comprimidos em disco; processar em chunks pequenos PRECISA
# dar o mesmo resultado que processar tudo de uma vez, senão o streaming
# está silenciosamente mudando o que M2 mede).
# ============================================================================


def _bars_equal(a: pl.DataFrame, b: pl.DataFrame) -> None:
    assert a.height == b.height
    assert a.columns == b.columns
    assert a.schema == b.schema
    for col in a.columns:
        assert a[col].to_list() == pytest.approx(b[col].to_list()), col


@pytest.mark.parametrize("sizes", [[20], [1] * 20, [7, 5, 3, 5], [1, 19], [19, 1], [4, 0, 16]])
def test_dollar_bars_streaming_bate_com_lote_varios_tamanhos_de_chunk(
    sizes: list[int],
) -> None:
    """Mesmos 20 trades, particionados em chunks de tamanhos bem diferentes
    (incluindo 1 chunk vazio no meio, `[4, 0, 16]`) -- resultado tem que
    ser byte-a-byte igual ao processamento em 1 `DataFrame` só."""
    n = 20
    trades = _trades(
        price=[100.0 + 0.7 * ((i * 13) % 9) for i in range(n)],
        quantity=[1.0 + (i % 4) for i in range(n)],
        is_buyer_maker=[i % 3 == 0 for i in range(n)],
    )
    threshold = 30.0  # pequeno o suficiente pra fechar várias barras nos 20 trades

    batch_bars = dollar_bars(trades, threshold=threshold)

    carry = dollar_bars_carry(threshold=threshold)
    for chunk in _chunk(trades, sizes):
        threshold_bars_step(carry, chunk)
    streaming_bars = threshold_bars_finish(carry)

    _bars_equal(batch_bars, streaming_bars)


@pytest.mark.parametrize("sizes", [[20], [1] * 20, [7, 5, 3, 5], [1, 19], [4, 0, 16]])
def test_volume_bars_streaming_bate_com_lote_varios_tamanhos_de_chunk(
    sizes: list[int],
) -> None:
    n = 20
    trades = _trades(
        price=[50.0 + 0.3 * ((i * 11) % 7) for i in range(n)],
        quantity=[1.0 + (i % 5) for i in range(n)],
        is_buyer_maker=[i % 2 == 0 for i in range(n)],
    )
    threshold = 10.0

    batch_bars = volume_bars(trades, threshold=threshold)

    carry = volume_bars_carry(threshold=threshold)
    for chunk in _chunk(trades, sizes):
        threshold_bars_step(carry, chunk)
    streaming_bars = threshold_bars_finish(carry)

    _bars_equal(batch_bars, streaming_bars)


@pytest.mark.parametrize("sizes", [[10], [1] * 10, [3, 4, 3], [1, 9], [9, 1], [2, 0, 8]])
def test_tick_imbalance_bars_streaming_bate_com_lote_varios_tamanhos_de_chunk(
    sizes: list[int],
) -> None:
    """Mesma prova de paridade, agora sobre o traço já verificado à mão em
    `test_tick_imbalance_bars_fecha_barra_no_limiar_esperado_tracado_a_mao`
    -- se streaming bate com lote NESSE caso (2 barras, geometria não
    trivial), a EWMA/exp_num_ticks estão sendo carregados corretamente
    entre chunks, não reiniciando do zero a cada chunk."""
    price = [100.0, 101.0, 102.0, 99.0, 98.0, 97.0, 103.0, 104.0, 105.0, 106.0]
    is_buyer_maker = [False, False, False, True, True, False, False, False, False, False]
    trades = _trades(price=price, quantity=[1.0] * 10, is_buyer_maker=is_buyer_maker)
    config = TickImbalanceBarsConfig(
        num_prev_bars=1,
        expected_imbalance_window=1,
        exp_num_ticks_init=3.0,
        exp_num_ticks_min=1.0,
        exp_num_ticks_max=100.0,
    )

    batch_bars = tick_imbalance_bars(trades, config)

    carry = tick_imbalance_bars_carry(config)
    for chunk in _chunk(trades, sizes):
        tick_imbalance_bars_step(carry, chunk)
    streaming_bars = tick_imbalance_bars_finish(carry)

    _bars_equal(batch_bars, streaming_bars)


def test_threshold_bars_step_chunk_vazio_e_no_op() -> None:
    carry = dollar_bars_carry(threshold=10.0)
    empty = _trades(price=[], quantity=[], is_buyer_maker=[])
    threshold_bars_step(carry, empty)  # não deve levantar nem mudar estado
    assert carry.leftover is None
    assert carry.bar_frames == []


def test_tick_imbalance_bars_step_chunk_vazio_e_no_op() -> None:
    config = TickImbalanceBarsConfig(
        num_prev_bars=3, expected_imbalance_window=10, exp_num_ticks_init=5.0,
        exp_num_ticks_min=1.0, exp_num_ticks_max=100.0,
    )
    carry = tick_imbalance_bars_carry(config)
    empty = _trades(price=[], quantity=[], is_buyer_maker=[])
    tick_imbalance_bars_step(carry, empty)
    assert carry.started is False
    assert carry.bar_frames == []
