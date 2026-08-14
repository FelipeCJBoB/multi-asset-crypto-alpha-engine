"""Testes de `src/data/bars.py` -- PRD_V4_1.md §3.2 M2. Determinismo e
causalidade de `dollar_bars`/`volume_bars` (partição vetorizada, conferida
à mão) e `tick_imbalance_bars` (loop sequencial AFML, traçado à mão com
`expected_imbalance_window=1`/`num_prev_bars=1` -- ambos com alpha de EWMA
=1,0, ou seja EWMA vira substituição direta pelo valor mais recente, o
suficiente para reduzir o algoritmo adaptativo a aritmética verificável na
mão sem perder nenhuma etapa real do fechamento de barra)."""

from __future__ import annotations

import polars as pl
import pytest

from src.data.bars import TickImbalanceBarsConfig, dollar_bars, tick_imbalance_bars, volume_bars


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


@pytest.mark.parametrize(
    "kwargs",
    [
        {"num_prev_bars": 0, "expected_imbalance_window": 10, "exp_num_ticks_init": 5.0},
        {"num_prev_bars": 3, "expected_imbalance_window": 0, "exp_num_ticks_init": 5.0},
        {"num_prev_bars": 3, "expected_imbalance_window": 10, "exp_num_ticks_init": 0.0},
    ],
)
def test_tick_imbalance_bars_config_invalida_levanta_erro(kwargs: dict[str, int | float]) -> None:
    trades = _trades(price=[1.0], quantity=[1.0], is_buyer_maker=[False])
    config = TickImbalanceBarsConfig(
        num_prev_bars=int(kwargs["num_prev_bars"]),
        expected_imbalance_window=int(kwargs["expected_imbalance_window"]),
        exp_num_ticks_init=float(kwargs["exp_num_ticks_init"]),
        exp_num_ticks_min=1.0,
        exp_num_ticks_max=100.0,
    )
    with pytest.raises(ValueError):
        tick_imbalance_bars(trades, config)


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
