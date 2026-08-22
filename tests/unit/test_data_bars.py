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

import numpy as np
import polars as pl
import pytest

from src.data._constants import load_constant as load_data_constant
from src.data.bars import (
    LeftoverOverflowError,
    TickImbalanceBarsConfig,
    dollar_bars,
    dollar_bars_carry,
    threshold_bars_drain,
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


def test_threshold_bars_drain_preserva_leftover_e_produz_mesmo_resultado_que_lote() -> None:
    """AG-124/item 14 -- `threshold_bars_drain` (ao contrário de `finish`)
    NÃO fecha o stream: o leftover em aberto continua vivo pro próximo
    `step()`. Processar em 2 partes com um `drain()` no meio (em vez de
    processar tudo de 1 vez) precisa produzir EXATAMENTE o mesmo resultado
    -- mesma disciplina de equivalência já usada pra chunking dentro de
    `threshold_bars_step` (docstring do módulo), agora estendida através
    de uma fronteira de drain/período (ex. `build_dollar_bars_walkforward`
    recalibrando a cada `cadence_days`)."""
    trades = _trades(price=[10.0] * 4, quantity=[5.0] * 4, is_buyer_maker=[False] * 4)
    # value=50/trade; cumsum=[50,100,150,200]; threshold=100 -> bar_id=[0,1,1,2]
    # -> lote inteiro: 3 barras (tamanhos 1,2,1). Split após o 1º trade
    # (cumsum=50, nenhuma barra fechada ainda -- leftover=1 trade) prova
    # que o drain NÃO descarta esse trade em aberto.
    reference = dollar_bars(trades, threshold=100.0)

    carry = dollar_bars_carry(threshold=100.0)
    threshold_bars_step(carry, trades.slice(0, 1))
    drained = threshold_bars_drain(carry)
    assert drained.is_empty()  # nenhuma barra fechou ainda no 1º trade
    assert carry.leftover is not None and carry.leftover.n_trades == 1  # NÃO descartado
    assert carry.bar_frames == []  # drain limpou bar_frames, sem tocar leftover

    threshold_bars_step(carry, trades.slice(1, 3))
    finished = threshold_bars_finish(carry)

    combined = pl.concat([drained, finished]) if not drained.is_empty() else finished
    assert combined.height == reference.height == 3
    assert combined["count"].to_list() == reference["count"].to_list() == [1, 2, 1]
    assert combined["volume"].to_list() == pytest.approx(reference["volume"].to_list())


def test_threshold_bars_drain_sobrevive_a_troca_de_threshold_entre_periodos() -> None:
    """`build_dollar_bars_walkforward` muda `carry.threshold` a cada
    período (nova calibração) sem perder leftover/base_value -- nenhum
    trade é perdido nem duplicado quando o threshold muda entre um
    `drain()` e o próximo `step()`. `cum_value` é acumulação bruta de
    valor DESDE A ORIGEM do carry, nunca resetada -- então `bar_id =
    cum_value // threshold` reinterpreta TODO o histórico acumulado sob o
    threshold NOVO, não só o valor futuro. Consequência real, não-óbvia,
    documentada aqui em vez de escondida: um trade que estava "em
    progresso" rumo a um threshold ANTIGO maior pode fechar como sua
    própria barra, com volume MENOR que o threshold_quote atual, assim
    que o próximo trade cruza o múltiplo do threshold NOVO -- ver conta
    abaixo."""
    # 1º trade: value=50, não fecha nada sob threshold=100 (fica leftover,
    # base_value continua 0 -- só é atualizado quando uma barra FECHA)
    p1 = _trades(price=[10.0], quantity=[5.0], is_buyer_maker=[False])
    carry = dollar_bars_carry(threshold=100.0)
    threshold_bars_step(carry, p1)
    drained1 = threshold_bars_drain(carry)
    assert drained1.is_empty()

    # troca de threshold (nova calibração do período seguinte) -- baixa pra
    # 60: cum_value = [50 (leftover), 70 (leftover+p2 value=20)] // 60 =
    # [0, 1] -- bar_id SOBE entre os 2 elementos, então o algoritmo fecha
    # o elemento 0 (só o trade de p1, cum_value=50) como bar 0 -- mesmo
    # sendo MENOR que o threshold_quote=60 atual -- e deixa o elemento 1
    # (só o trade de p2, value=20) como novo leftover em aberto.
    carry.threshold = 60.0
    p2 = _trades(price=[10.0], quantity=[2.0], is_buyer_maker=[False])  # value=20
    threshold_bars_step(carry, p2)
    result = threshold_bars_finish(carry)

    # 2 barras (não 1) -- nenhum trade perdido/duplicado: volumes [5, 2],
    # soma 7 == 5(p1)+2(p2). A 1ª barra é o "resto" do threshold antigo
    # fechando cedo sob o threshold novo -- comportamento real, verificado
    # à mão, não um bug a esconder.
    assert result.height == 2
    assert result["volume"].to_list() == pytest.approx([5.0, 2.0])
    assert result["count"].to_list() == [1, 1]
    assert (result["threshold_quote"] == 60.0).all()  # threshold NOVO em ambas, não o antigo (100)
    assert sum(result["volume"].to_list()) == pytest.approx(7.0)  # conservação: nada perdido


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


# ============================================================================
# threshold_quote -- AG-124 (2026-08-21): cada barra carrega o threshold
# (unidade de carry.value_kind) que a fechou.
# ============================================================================


def test_dollar_bars_toda_barra_carrega_threshold_quote_igual_ao_threshold_passado() -> None:
    trades = _trades(price=[10.0] * 4, quantity=[5.0] * 4, is_buyer_maker=[False] * 4)
    bars = dollar_bars(trades, threshold=100.0)

    assert bars.height == 3
    assert bars["threshold_quote"].to_list() == pytest.approx([100.0, 100.0, 100.0])


def test_volume_bars_toda_barra_carrega_threshold_quote_igual_ao_threshold_passado() -> None:
    trades = _trades(price=[1.0, 2.0, 3.0, 4.0], quantity=[3.0] * 4, is_buyer_maker=[False] * 4)
    bars = volume_bars(trades, threshold=5.0)

    assert bars.height == 3
    assert bars["threshold_quote"].to_list() == pytest.approx([5.0, 5.0, 5.0])


def test_dollar_bars_streaming_threshold_quote_bate_com_lote() -> None:
    """`_aggregate_bars` recebe `threshold_quote=carry.threshold` em AMBOS
    os pontos de chamada (`threshold_bars_step`/`threshold_bars_finish`) --
    trava que o valor sobrevive à passagem por streaming, não só ao
    caminho de 1 chunk só (`dollar_bars`)."""
    n = 20
    trades = _trades(
        price=[100.0 + 0.7 * ((i * 13) % 9) for i in range(n)],
        quantity=[1.0 + (i % 4) for i in range(n)],
        is_buyer_maker=[i % 3 == 0 for i in range(n)],
    )
    carry = dollar_bars_carry(threshold=37.5)
    for chunk in _chunk(trades, [7, 5, 3, 5]):
        threshold_bars_step(carry, chunk)
    streamed = threshold_bars_finish(carry)

    assert streamed.height > 0
    assert streamed["threshold_quote"].drop_nulls().n_unique() == 1
    assert streamed["threshold_quote"][0] == pytest.approx(37.5)


def test_tick_imbalance_bars_threshold_quote_e_none_nunca_inventado() -> None:
    """TIB fecha por EWMA de imbalance/`exp_num_ticks`, não por um
    threshold escalar fixo -- `threshold_quote` fica `None` (honesto, B23),
    nunca um valor fabricado (ex. `close_threshold` do fechamento, que
    varia POR BARRA e não é o mesmo conceito de `threshold_usdt` de
    dollar/volume bar)."""
    trades = _trades(
        price=[100.0, 101.0, 102.0, 99.0, 98.0, 97.0, 103.0, 104.0, 105.0, 106.0],
        quantity=[1.0] * 10,
        is_buyer_maker=[False, False, False, True, True, False, False, False, False, False],
    )
    config = TickImbalanceBarsConfig(
        num_prev_bars=1,
        expected_imbalance_window=1,
        exp_num_ticks_init=3.0,
        exp_num_ticks_min=1.0,
        exp_num_ticks_max=100.0,
    )
    bars = tick_imbalance_bars(trades, config)

    assert bars.height == 2
    assert bars["threshold_quote"].is_null().all()


def test_tick_imbalance_bars_dataframe_vazio_ainda_tem_coluna_threshold_quote() -> None:
    trades = _trades(price=[], quantity=[], is_buyer_maker=[])
    config = TickImbalanceBarsConfig(
        num_prev_bars=3, expected_imbalance_window=10, exp_num_ticks_init=5.0,
        exp_num_ticks_min=1.0, exp_num_ticks_max=100.0,
    )
    bars = tick_imbalance_bars(trades, config)
    assert "threshold_quote" in bars.columns
    assert bars.schema["threshold_quote"] == pl.Float64


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


# ============================================================================
# Redesenho AG-034 addendum (2026-08-16) -- `ThresholdBarsCarry.leftover`
# virou arrays numpy (não mais `pl.DataFrame`) e o split fechado/leftover
# virou busca binária (`np.searchsorted`), não mais dois `.filter()`. Os
# testes abaixo provam especificamente essa mudança -- os testes de
# paridade streaming<->lote acima já continuam cobrindo o comportamento
# geral sem alteração de asserção nenhuma.
# ============================================================================


def test_dollar_bars_split_por_busca_binaria_bate_com_filtro_quando_varias_barras_fecham() -> None:
    """`threshold_bars_step` trocou os dois `.filter()` (`bar_id<max_bar_id`
    / `bar_id==max_bar_id`) por 1 busca binária (`np.searchsorted`) -- este
    teste prova que a nova partição bate com a partição que os dois
    filtros dariam, num caso com MAIS de 1 barra fechando no mesmo chunk
    (os testes de traço à mão já existentes só cobrem 0 ou 1 barra
    fechando por vez)."""
    # value = price*quantity = 25 por trade; cumsum = [25,50,75,...,200];
    # threshold=50 -> bar_id = floor(cumsum/50) = [0,1,1,2,2,3,3,4] --
    # 4 barras fecham (id 0..3), 1 trade fica aberto (id 4).
    n = 8
    trades = _trades(price=[5.0] * n, quantity=[5.0] * n, is_buyer_maker=[False] * n)
    threshold = 50.0

    # Oracle independente: reconstrói a partição via os dois filtros que
    # threshold_bars_step usava antes do redesenho -- polars puro, direto
    # no teste, sem reimportar nada do algoritmo em si.
    value = (trades["price"] * trades["quantity"]).to_numpy()
    cum_value = value.cumsum()
    bar_id = (cum_value // threshold).astype("int64")  # noqa: unguarded-ratio -- threshold=50.0 literal do teste, sempre >0
    assert bar_id.tolist() == [0, 1, 1, 2, 2, 3, 3, 4]
    max_bar_id = bar_id[-1]
    combined = trades.with_columns(pl.Series("_bar_id", bar_id))
    oracle_closed = combined.filter(pl.col("_bar_id") < max_bar_id)
    oracle_leftover = combined.filter(pl.col("_bar_id") == max_bar_id)

    carry = dollar_bars_carry(threshold=threshold)
    threshold_bars_step(carry, trades)

    assert len(carry.bar_frames) == 1  # 1 chunk passado -> 1 DataFrame de barras fechadas
    closed_result = carry.bar_frames[0]
    assert closed_result.height == 4  # bar_id 0,1,2,3
    assert closed_result["count"].to_list() == [1, 2, 2, 2]
    assert int(closed_result["count"].sum()) == oracle_closed.height
    assert carry.leftover is not None
    assert carry.leftover_trade_count == oracle_leftover.height == 1
    assert carry.leftover.price.tolist() == oracle_leftover["price"].to_list()
    assert carry.leftover.quantity.tolist() == oracle_leftover["quantity"].to_list()
    assert carry.leftover.transact_time.tolist() == oracle_leftover["transact_time"].to_list()


def test_dollar_bars_ultimo_trade_fecha_barra_exatamente_no_threshold() -> None:
    """Caso de borda: `cum_value[-1] % threshold == 0` -- o último trade do
    chunk cai EXATAMENTE no limiar (não só ultrapassa). Pela semântica já
    documentada em `ThresholdBarsCarry` ("uma barra só fecha quando um
    trade EXCEDE o threshold, não quando bate exatamente nele"), o
    `bar_id` desse trade pertence à barra que a fronteira exata ABRE, não
    à que fecha -- o leftover resultante tem exatamente 1 trade (o próprio
    trade da fronteira), nunca um leftover fantasma de 0 linhas."""
    trades = _trades(price=[1.0, 1.0], quantity=[30.0, 20.0], is_buyer_maker=[False, False])
    threshold = 50.0  # cumsum = [30, 50]; 50 % 50 == 0 -- fronteira exata

    carry = dollar_bars_carry(threshold=threshold)
    threshold_bars_step(carry, trades)

    assert carry.leftover is not None
    assert carry.leftover_trade_count == 1
    assert carry.leftover.quantity.tolist() == [20.0]
    assert len(carry.bar_frames) == 1
    assert carry.bar_frames[0].height == 1
    assert carry.bar_frames[0]["count"].to_list() == [1]
    assert carry.bar_frames[0]["volume"].to_list() == pytest.approx([30.0])

    bars = threshold_bars_finish(carry)
    assert carry.leftover is None
    assert bars.height == 2
    assert bars["count"].to_list() == [1, 1]
    assert bars["volume"].to_list() == pytest.approx([30.0, 20.0])


def test_threshold_bars_step_leftover_overflow_levanta_erro_com_contagem_certa() -> None:
    """Circuit breaker novo (achado MEDIUM de AG-034 addendum): threshold
    que nunca fecha barra nenhuma + `max_leftover_trades` pequeno ->
    `LeftoverOverflowError`, com o número certo de trades acumulados na
    mensagem."""
    n = 5
    trades = _trades(
        price=[1.0] * n, quantity=[1.0] * n, is_buyer_maker=[False] * n
    )
    carry = dollar_bars_carry(threshold=1_000_000.0, max_leftover_trades=3.0)

    with pytest.raises(LeftoverOverflowError, match=r"len\(new_leftover\)=5"):
        threshold_bars_step(carry, trades)


def test_threshold_bars_step_leftover_overflow_nao_muta_carry_quando_barras_tambem_fecham() -> None:
    """Achado de revisão pessoal (2026-08-16, antes de considerar o
    redesenho pronto): a ordem original checava o circuit breaker DEPOIS
    de já ter atualizado `bar_frames`/`base_value` -- se `split_idx > 0`
    (uma ou mais barras fecham) NO MESMO step em que o leftover também
    excede `max_leftover_trades`, `carry` ficava num estado inconsistente
    (barras novas já registradas, `leftover` não). O teste anterior
    (`..._levanta_erro_com_contagem_certa`) não pegava isso porque usa um
    threshold que nunca fecha bar nenhuma (`split_idx=0` sempre) -- este
    teste força as duas coisas a acontecerem no mesmo chunk: 3 barras
    fecham (7 trades com valor 25 cada, threshold=50) E o leftover final
    (7 trades com valor 1 cada, todos ficam na mesma barra aberta) excede
    o teto. Prova que `threshold_bars_step` é tudo-ou-nada: se levanta,
    `carry` sai exatamente como entrou."""
    closing = _trades(price=[5.0] * 7, quantity=[5.0] * 7, is_buyer_maker=[False] * 7)
    tail = _trades(price=[1.0] * 5, quantity=[1.0] * 5, is_buyer_maker=[False] * 5)
    trades = pl.concat([closing, tail])
    # cumsum = [25,50,75,100,125,150,175,176,177,178,179,180]; threshold=50
    # -> bar_id = [0,1,1,2,2,3,3,3,3,3,3,3] -- 3 barras fecham (id 0,1,2,
    # 5 trades), leftover final = 7 trades (id 3), todos com bar_id==3.
    threshold = 50.0

    carry = dollar_bars_carry(threshold=threshold, max_leftover_trades=5.0)
    assert carry.bar_frames == []
    assert carry.base_value == 0.0
    assert carry.leftover is None

    with pytest.raises(LeftoverOverflowError, match=r"len\(new_leftover\)=7"):
        threshold_bars_step(carry, trades)

    # carry precisa sair EXATAMENTE como entrou -- nada parcialmente
    # aplicado, mesmo com 3 barras tendo "fechado" antes do ponto de falha.
    assert carry.bar_frames == []
    assert carry.base_value == 0.0
    assert carry.leftover is None


def test_threshold_bars_step_circuit_breaker_cobre_pico_de_volume_14x_legitimo() -> None:
    """AG-124/item 16 (2026-08-21) -- a auditoria externa mediu picos de
    até ~14x o volume/dia calibrado (addendum diário de `AG-124`) e
    perguntou se `max_leftover_trades` ainda cobre isso. Resposta medida
    aqui: SIM, folgadamente, e por um motivo estrutural -- um pico de
    volume EM DÓLAR, sustentado por trades de tamanho médio SEMELHANTE ao
    da calibração (só mais trades, não trades menores), fecha barras MAIS
    RÁPIDO (mais barras/dia), não faz o leftover CRESCER -- `leftover` é
    contagem de trades no bar ainda ABERTO, que continua perto de `avg_
    trades_per_bar` a qualquer instante, nunca do dia inteiro. Usa o
    multiplicador REAL de produção (`bars_threshold_leftover_safety_
    multiplier`, `config/constants.yaml`), não um valor arbitrário de
    teste."""
    safety_mult = float(load_data_constant("bars_threshold_leftover_safety_multiplier"))
    avg_trades_per_bar_calibrated = 10
    trade_value = 100.0
    threshold = avg_trades_per_bar_calibrated * trade_value  # 1000.0
    max_leftover_trades = avg_trades_per_bar_calibrated * safety_mult

    # "pico de 14x": 14x mais trades que num dia normal (140 vs 10), MESMO
    # tamanho médio por trade -- simula volume em dólar 14x maior sustentado
    # por mais atividade, não por trades individualmente maiores.
    n_trades_spike_day = avg_trades_per_bar_calibrated * 14
    trades = _trades(
        price=[10.0] * n_trades_spike_day,
        quantity=[10.0] * n_trades_spike_day,  # value=100/trade, igual à calibração
        is_buyer_maker=[False] * n_trades_spike_day,
    )
    carry = dollar_bars_carry(threshold=threshold, max_leftover_trades=max_leftover_trades)

    threshold_bars_step(carry, trades)  # não deve levantar

    # ~14 barras fecharam (140 trades / 10 por barra, todas dentro do ÚNICO
    # DataFrame de bar_frames -- _aggregate_bars agrupa por bar_id numa
    # chamada só); leftover residual fica muito abaixo do teto (500 =
    # 10*50), nunca perto de estourar.
    assert len(carry.bar_frames) == 1
    assert carry.bar_frames[0].height >= 13
    assert carry.leftover_trade_count < max_leftover_trades / 10


def test_threshold_bars_step_circuit_breaker_dispara_sob_mudanca_real_de_forma_nao_so_volume() -> (
    None
):
    """Contraponto ao teste acima -- o que REALMENTE ameaça
    `max_leftover_trades` não é volume em dólar alto, é uma MUDANÇA DE
    FORMA da distribuição de trades (muitos trades pequenos em vez de
    poucos grandes, deslocando trades-por-barra pra além do multiplicador
    de segurança) -- categoria de risco DIFERENTE do "~14x" medido em
    dólar/dia, e o motivo de não tratar os dois como comparáveis (ver
    `docs/plano_acao_ag124_pos_auditoria_2026-08-21.md`, item 16)."""
    safety_mult = float(load_data_constant("bars_threshold_leftover_safety_multiplier"))
    avg_trades_per_bar_calibrated = 10
    threshold = avg_trades_per_bar_calibrated * 100.0  # 1000.0
    max_leftover_trades = avg_trades_per_bar_calibrated * safety_mult  # 500.0

    # mesmo VALOR total que fecharia 1 barra normalmente (1000.0), mas
    # fatiado em trades 60x menores -- precisaria de 600 trades pra fechar
    # 1 barra (60x avg_trades_per_bar_calibrated), acima do teto de 50x.
    n_tiny_trades = int(max_leftover_trades) + 1  # 501 -- já excede o teto sem fechar 1 barra
    tiny_value = 1000.0 / (avg_trades_per_bar_calibrated * 60)
    trades = _trades(
        price=[tiny_value] * n_tiny_trades,
        quantity=[1.0] * n_tiny_trades,
        is_buyer_maker=[False] * n_tiny_trades,
    )
    carry = dollar_bars_carry(threshold=threshold, max_leftover_trades=max_leftover_trades)

    with pytest.raises(LeftoverOverflowError):
        threshold_bars_step(carry, trades)


def test_np_cumsum_bate_bit_a_bit_com_polars_cum_sum() -> None:
    """Achado MEDIUM de revisão independente (project_assurance, 2026-08-16):
    a prova de paridade bit-a-bit `np.cumsum` vs `pl.Series.cum_sum()`
    (docstring de `threshold_bars_step`) é uma leitura de código-fonte do
    Polars numa versão pinada -- sem NENHUM teste executável, um bump
    futuro de `uv.lock` poderia mudar o algoritmo interno de `cum_sum` sem
    nada no repo notar. Este teste é o canário: compara os dois caminhos
    direto, sobre valores com a MESMA característica de ponto flutuante
    de `price*quantity` real (não inteiros exatos, que mascarariam erro
    de soma) -- se algum dia divergir, é sinal de que a alegação do
    docstring não vale mais pra versão instalada, não é teste de
    `threshold_bars_step` em si (que já não chama `pl.Series.cum_sum()`
    em lugar nenhum pós-redesenho -- ver achado)."""
    rng = np.random.default_rng(2026_08_16)
    price = rng.uniform(20_000.0, 70_000.0, size=5_000)
    quantity = rng.uniform(0.0001, 5.0, size=5_000)
    value = price * quantity

    numpy_cumsum = np.cumsum(value)
    polars_cumsum = pl.Series("v", value).cum_sum().to_numpy()

    assert np.array_equal(numpy_cumsum, polars_cumsum)


def test_threshold_bars_step_leftover_no_limite_exato_nao_levanta() -> None:
    """Caso de borda não testado (achado LOW de revisão independente,
    2026-08-16): `max_leftover_trades` é checado com `>` (estrito) --
    `new_leftover_size == max_leftover_trades` NÃO deve levantar. Mesmos
    5 trades de `..._levanta_erro_com_contagem_certa`, mas com o teto
    exatamente igual à contagem real."""
    n = 5
    trades = _trades(price=[1.0] * n, quantity=[1.0] * n, is_buyer_maker=[False] * n)
    carry = dollar_bars_carry(threshold=1_000_000.0, max_leftover_trades=5.0)

    threshold_bars_step(carry, trades)  # não deve levantar -- limite exato, não excedido

    assert carry.leftover_trade_count == 5


def test_threshold_bars_step_sem_max_leftover_trades_nunca_levanta() -> None:
    """`max_leftover_trades=None` (default de `dollar_bars_carry`/
    `volume_bars_carry`) preserva o comportamento de antes do circuit
    breaker existir -- nunca levanta, não importa quantos trades ficam
    acumulados no leftover."""
    n = 500
    trades = _trades(
        price=[1.0] * n, quantity=[1.0] * n, is_buyer_maker=[False] * n
    )
    carry = dollar_bars_carry(threshold=1_000_000.0)  # max_leftover_trades default None

    threshold_bars_step(carry, trades)  # não deve levantar

    assert carry.leftover_trade_count == n
