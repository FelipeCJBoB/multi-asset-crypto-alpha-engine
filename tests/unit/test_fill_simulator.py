"""Testes de `src/execution/fill_simulator.py` — simulador de fila (§9.5,
Sprint 9). Cobre o núcleo numérico puro (`_simulate_one_order`,
`_asof_index`, `_day_grid_ms`) com fixtures sintéticas pequenas primeiro
(sem IO — a janela real 2023-05-16..2024-03-30 NÃO é varrida aqui, isso é
feito por uma execução separada, fora da suíte de testes, que produz
`data/execution_runs/fill_simulator_runs.parquet`), depois `summarize`/escrita
atômica/log de experimentos com `tmp_path`, e por fim um teste de integração
leve (skip se o backfill local não existir) confirmando o schema real de
`data/raw/book_ticker/BTCUSDT/`."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from src.execution import fill_simulator as fs
from src.execution._paths import BOOK_TICKER_DIR

_SYMBOL = "BTCUSDT"


def _skip_if_missing_book_ticker(day: str) -> None:
    path = BOOK_TICKER_DIR / _SYMBOL / f"{day}.parquet"
    if not path.exists():
        pytest.skip(f"fixture ausente no backfill local: {path}")


def _book(
    times: list[int],
    bid_px: list[float],
    bid_qty: list[float],
    ask_px: list[float],
    ask_qty: list[float],
) -> fs._BookArrays:
    return fs._BookArrays(
        transaction_time=np.array(times, dtype=np.int64),
        best_bid_price=np.array(bid_px, dtype=np.float64),
        best_bid_qty=np.array(bid_qty, dtype=np.float64),
        best_ask_price=np.array(ask_px, dtype=np.float64),
        best_ask_qty=np.array(ask_qty, dtype=np.float64),
    )


def _trades(
    times: list[int], prices: list[float], qtys: list[float], is_buyer_maker: list[bool]
) -> fs._TradeArrays:
    return fs._TradeArrays(
        transact_time=np.array(times, dtype=np.int64),
        price=np.array(prices, dtype=np.float64),
        quantity=np.array(qtys, dtype=np.float64),
        is_buyer_maker=np.array(is_buyer_maker, dtype=np.bool_),
    )


# ============================================================================
# _asof_index
# ============================================================================


def test_asof_index_antes_do_primeiro_registro_e_menos_um() -> None:
    times = np.array([1_000, 2_000, 3_000], dtype=np.int64)
    assert fs._asof_index(times, 500) == -1


def test_asof_index_exato_e_entre_registros() -> None:
    times = np.array([1_000, 2_000, 3_000], dtype=np.int64)
    assert fs._asof_index(times, 2_000) == 1
    assert fs._asof_index(times, 2_500) == 1
    assert fs._asof_index(times, 3_500) == 2


# ============================================================================
# _simulate_one_order — sem estado de book conhecido
# ============================================================================


def test_sem_estado_de_book_devolve_none() -> None:
    book = _book([10_000], [100.0], [1.0], [100.1], [1.0])
    trades = _trades([], [], [], [])
    order = fs._simulate_one_order(
        book, trades, t_post_ms=5_000, side=1, fill_timeout_ms=900_000, tick_size=0.10
    )
    assert order is None


def test_side_invalido_levanta_erro() -> None:
    book = _book([0], [100.0], [1.0], [100.1], [1.0])
    trades = _trades([], [], [], [])
    with pytest.raises(ValueError):
        fs._simulate_one_order(
            book, trades, t_post_ms=0, side=0, fill_timeout_ms=900_000, tick_size=0.10
        )


# ============================================================================
# _simulate_one_order — fila vazia preenche imediatamente
# ============================================================================


def test_queue_ahead_zero_preenche_no_proprio_post() -> None:
    book = _book([0], [100.0], [0.0], [100.1], [1.0])
    trades = _trades([], [], [], [])
    order = fs._simulate_one_order(
        book, trades, t_post_ms=0, side=1, fill_timeout_ms=900_000, tick_size=0.10
    )
    assert order is not None
    assert order.filled is True
    assert order.t_entry_ms == 0
    assert order.fill_price == 100.0
    assert order.queue_ahead_initial == 0.0


# ============================================================================
# _simulate_one_order — compra no bid, preenchida por venda agressora
# ============================================================================


def test_compra_preenchida_por_venda_agressora_no_mesmo_nivel() -> None:
    book = _book([0], [100.0], [1.0], [100.1], [1.0])
    trades = _trades(
        times=[100, 200, 300],
        prices=[100.0, 100.0, 100.0],
        qtys=[0.3, 0.3, 0.5],  # cumsum: 0.3, 0.6, 1.1 -> cruza 1.0 no terceiro
        is_buyer_maker=[True, True, True],  # comprador=maker (nosso lado), vendedor=agressor
    )
    order = fs._simulate_one_order(
        book, trades, t_post_ms=0, side=1, fill_timeout_ms=900_000, tick_size=0.10
    )
    assert order is not None
    assert order.filled is True
    assert order.t_entry_ms == 300  # primeiro trade que CRUZA o total, não o último
    assert order.fill_price == 100.0


def test_compra_nao_preenche_por_trade_do_lado_errado() -> None:
    """`is_buyer_maker=False` (comprador é o agressor) não decrementa a fila
    de uma ordem de COMPRA repousando no bid — é o mesmo lado do book, não o
    agressor que bateria contra nós."""
    book = _book([0], [100.0], [1.0], [100.1], [1.0])
    trades = _trades(
        times=[100, 200],
        prices=[100.0, 100.0],
        qtys=[5.0, 5.0],
        is_buyer_maker=[False, False],
    )
    order = fs._simulate_one_order(
        book, trades, t_post_ms=0, side=1, fill_timeout_ms=900_000, tick_size=0.10
    )
    assert order is not None
    assert order.filled is False
    assert order.t_entry_ms is None
    assert order.fill_price is None


def test_compra_nao_preenche_por_trade_em_nivel_de_preco_diferente() -> None:
    book = _book([0], [100.0], [0.5], [100.1], [1.0])
    trades = _trades(
        times=[100],
        prices=[99.5],  # fora da tolerância tick_size/2 de 100.0
        qtys=[10.0],
        is_buyer_maker=[True],
    )
    order = fs._simulate_one_order(
        book, trades, t_post_ms=0, side=1, fill_timeout_ms=900_000, tick_size=0.10
    )
    assert order is not None
    assert order.filled is False


# ============================================================================
# _simulate_one_order — venda no ask, preenchida por compra agressora
# ============================================================================


def test_venda_preenchida_por_compra_agressora_no_mesmo_nivel() -> None:
    book = _book([0], [100.0], [1.0], [100.1], [0.4])
    trades = _trades(
        times=[100, 200],
        prices=[100.1, 100.1],
        qtys=[0.2, 0.3],  # cumsum 0.2, 0.5 -> cruza 0.4 no segundo
        is_buyer_maker=[False, False],  # vendedor=maker (nosso lado), comprador=agressor
    )
    order = fs._simulate_one_order(
        book, trades, t_post_ms=0, side=-1, fill_timeout_ms=900_000, tick_size=0.10
    )
    assert order is not None
    assert order.filled is True
    assert order.t_entry_ms == 200
    assert order.fill_price == 100.1


# ============================================================================
# _simulate_one_order — janela de timeout
# ============================================================================


def test_trade_fora_da_janela_de_timeout_nao_conta() -> None:
    book = _book([0], [100.0], [0.5], [100.1], [1.0])
    trades = _trades(
        times=[1_000_000],  # depois do horizonte de 900_000ms
        prices=[100.0],
        qtys=[10.0],
        is_buyer_maker=[True],
    )
    order = fs._simulate_one_order(
        book, trades, t_post_ms=0, side=1, fill_timeout_ms=900_000, tick_size=0.10
    )
    assert order is not None
    assert order.filled is False


def test_trade_exatamente_em_t_post_nao_conta() -> None:
    """Janela é `(t_post, horizon]`, estritamente posterior a `t_post` —
    mesma convenção de `src.labels.fill_model`."""
    book = _book([0], [100.0], [0.5], [100.1], [1.0])
    trades = _trades(times=[0], prices=[100.0], qtys=[10.0], is_buyer_maker=[True])
    order = fs._simulate_one_order(
        book, trades, t_post_ms=0, side=1, fill_timeout_ms=900_000, tick_size=0.10
    )
    assert order is not None
    assert order.filled is False


# ============================================================================
# _simulate_one_order — markout
# ============================================================================


def test_markout_calculado_no_horizonte_com_sinal_correto() -> None:
    # Preenche imediatamente (queue_ahead=0) em t_post=0, fill_price=100.0 (compra).
    book = _book(
        times=[0, 60_000, 300_000, 1_800_000],
        bid_px=[100.0, 101.0, 99.0, 102.0],
        bid_qty=[0.0, 1.0, 1.0, 1.0],
        ask_px=[100.2, 101.2, 99.2, 102.2],
        ask_qty=[1.0, 1.0, 1.0, 1.0],
    )
    trades = _trades([], [], [], [])
    order = fs._simulate_one_order(
        book, trades, t_post_ms=0, side=1, fill_timeout_ms=900_000, tick_size=0.10
    )
    assert order is not None
    assert order.filled is True
    assert order.t_entry_ms == 0
    # mid em 60_000 = (101.0+101.2)/2 = 101.1 -> markout = +1 * (101.1-100.0)/100.0 * 10000
    assert order.markout_1m_bps == pytest.approx((101.1 - 100.0) / 100.0 * 10_000)
    # mid em 300_000 = (99.0+99.2)/2 = 99.1 -> markout negativo (preço caiu, ruim pra compra)
    assert order.markout_5m_bps == pytest.approx((99.1 - 100.0) / 100.0 * 10_000)
    assert order.markout_5m_bps is not None
    assert order.markout_5m_bps < 0
    assert order.markout_30m_bps == pytest.approx((102.1 - 100.0) / 100.0 * 10_000)


def test_markout_sinal_invertido_para_venda() -> None:
    # Venda no ask preenche imediatamente; preço SOBE depois -> markout negativo (ruim pra venda).
    book = _book(
        times=[0, 60_000],
        bid_px=[100.0, 101.0],
        bid_qty=[1.0, 1.0],
        ask_px=[100.2, 101.2],
        ask_qty=[0.0, 1.0],
    )
    trades = _trades([], [], [], [])
    order = fs._simulate_one_order(
        book, trades, t_post_ms=0, side=-1, fill_timeout_ms=900_000, tick_size=0.10
    )
    assert order is not None
    assert order.fill_price == 100.2
    mid_60s = (101.0 + 101.2) / 2.0
    expected = -1 * (mid_60s - 100.2) / 100.2 * 10_000
    assert order.markout_1m_bps == pytest.approx(expected)
    assert order.markout_1m_bps is not None
    assert order.markout_1m_bps < 0  # preço subiu, ruim pra quem vendeu


def test_markout_none_quando_horizonte_alem_do_book_carregado() -> None:
    # Só há book até 60_000ms — horizonte de 30m (1_800_000ms) fica fora.
    book = _book([0, 60_000], [100.0, 100.0], [0.0, 1.0], [100.2, 100.2], [1.0, 1.0])
    trades = _trades([], [], [], [])
    order = fs._simulate_one_order(
        book, trades, t_post_ms=0, side=1, fill_timeout_ms=900_000, tick_size=0.10
    )
    assert order is not None
    assert order.filled is True
    assert order.markout_1m_bps is not None
    assert order.markout_30m_bps is None  # não um valor stale


def test_markout_none_quando_nofill() -> None:
    book = _book([0], [100.0], [5.0], [100.1], [1.0])
    trades = _trades([], [], [], [])
    order = fs._simulate_one_order(
        book, trades, t_post_ms=0, side=1, fill_timeout_ms=900_000, tick_size=0.10
    )
    assert order is not None
    assert order.filled is False
    assert order.markout_1m_bps is None
    assert order.markout_5m_bps is None
    assert order.markout_30m_bps is None


# ============================================================================
# _simulate_one_order_price_improved — variante de sensibilidade (item 4 da
# investigação pós-Sprint 9): posta 1 tick melhor que o topo do livro.
# ============================================================================


def test_price_improved_sem_estado_de_book_devolve_none() -> None:
    book = _book([10_000], [100.0], [1.0], [100.1], [1.0])
    trades = _trades([], [], [], [])
    order = fs._simulate_one_order_price_improved(
        book, trades, t_post_ms=5_000, side=1, fill_timeout_ms=900_000, tick_size=0.10
    )
    assert order is None


def test_price_improved_side_invalido_levanta_erro() -> None:
    book = _book([0], [100.0], [1.0], [100.1], [1.0])
    trades = _trades([], [], [], [])
    with pytest.raises(ValueError):
        fs._simulate_one_order_price_improved(
            book, trades, t_post_ms=0, side=0, fill_timeout_ms=900_000, tick_size=0.10
        )


def test_price_improved_compra_melhora_um_tick_acima_do_bid() -> None:
    # bid=100.0, ask=100.3 -> compra melhorada posta em 100.1 (1 tick acima
    # do bid), fila vazia por construção (queue_ahead_initial == 0.0).
    book = _book([0], [100.0], [1.0], [100.3], [1.0])
    trades = _trades(
        times=[100], prices=[100.1], qtys=[0.05], is_buyer_maker=[True]
    )
    order = fs._simulate_one_order_price_improved(
        book, trades, t_post_ms=0, side=1, fill_timeout_ms=900_000, tick_size=0.10
    )
    assert order is not None
    assert order.limit_price == pytest.approx(100.1)
    assert order.queue_ahead_initial == 0.0
    assert order.filled is True
    assert order.t_entry_ms == 100
    assert order.fill_price == pytest.approx(100.1)


def test_price_improved_venda_melhora_um_tick_abaixo_do_ask() -> None:
    book = _book([0], [100.0], [1.0], [100.3], [1.0])
    trades = _trades(
        times=[100], prices=[100.2], qtys=[0.05], is_buyer_maker=[False]
    )
    order = fs._simulate_one_order_price_improved(
        book, trades, t_post_ms=0, side=-1, fill_timeout_ms=900_000, tick_size=0.10
    )
    assert order is not None
    assert order.limit_price == pytest.approx(100.2)
    assert order.filled is True
    assert order.t_entry_ms == 100


def test_price_improved_primeiro_trade_casado_ja_preenche_sem_acumular() -> None:
    """Diferente de `_simulate_one_order`: aqui não há fila alheia para
    esvaziar — o primeiro trade casado (qualquer quantidade) já preenche,
    não precisa de cumsum cruzando um total."""
    book = _book([0], [100.0], [1.0], [100.3], [1.0])
    trades = _trades(
        times=[100, 200],
        prices=[100.1, 100.1],
        qtys=[0.001, 5.0],  # o primeiro trade, minúsculo, já basta
        is_buyer_maker=[True, True],
    )
    order = fs._simulate_one_order_price_improved(
        book, trades, t_post_ms=0, side=1, fill_timeout_ms=900_000, tick_size=0.10
    )
    assert order is not None
    assert order.filled is True
    assert order.t_entry_ms == 100  # primeiro trade casado, não o segundo


def test_price_improved_sem_trade_casado_nofill() -> None:
    book = _book([0], [100.0], [1.0], [100.3], [1.0])
    trades = _trades([], [], [], [])
    order = fs._simulate_one_order_price_improved(
        book, trades, t_post_ms=0, side=1, fill_timeout_ms=900_000, tick_size=0.10
    )
    assert order is not None
    assert order.filled is False
    assert order.t_entry_ms is None
    assert order.fill_price is None
    assert order.markout_1m_bps is None


def test_price_improved_spread_de_um_tick_cruzaria_e_nao_posta() -> None:
    # bid=100.0, ask=100.1 (spread == 1 tick) -> compra melhorada seria
    # 100.1 == ask -> cruzaria -> GTX rejeitaria -> sentinela -1.0.
    book = _book([0], [100.0], [1.0], [100.1], [1.0])
    trades = _trades([], [], [], [])
    order = fs._simulate_one_order_price_improved(
        book, trades, t_post_ms=0, side=1, fill_timeout_ms=900_000, tick_size=0.10
    )
    assert order is not None
    assert order.queue_ahead_initial == -1.0
    assert order.filled is False
    assert order.t_entry_ms is None


def test_price_improved_spread_menor_que_um_tick_tambem_cruzaria() -> None:
    # ask abaixo do que seria o novo bid melhorado -> cruza também.
    book = _book([0], [100.0], [1.0], [100.05], [1.0])
    trades = _trades([], [], [], [])
    order = fs._simulate_one_order_price_improved(
        book, trades, t_post_ms=0, side=-1, fill_timeout_ms=900_000, tick_size=0.10
    )
    assert order is not None
    assert order.queue_ahead_initial == -1.0


def test_price_improved_markout_usa_o_mesmo_nucleo_compartilhado() -> None:
    # Fill acontece em t_entry=100ms (primeiro trade casado, não em t_post=0)
    # -> horizonte de 1m cai em 100 + 60_000 = 60_100ms; book precisa cobrir
    # até lá (não só 60_000) para o markout não ficar None (item 6/docstring).
    book = _book(
        times=[0, 60_100],
        bid_px=[100.0, 101.0],
        bid_qty=[1.0, 1.0],
        ask_px=[100.3, 101.3],
        ask_qty=[1.0, 1.0],
    )
    trades = _trades(times=[100], prices=[100.1], qtys=[1.0], is_buyer_maker=[True])
    order = fs._simulate_one_order_price_improved(
        book, trades, t_post_ms=0, side=1, fill_timeout_ms=900_000, tick_size=0.10
    )
    assert order is not None
    assert order.filled is True
    assert order.t_entry_ms == 100
    # mid em 60_100 = (101.0+101.3)/2 = 101.15 -> markout = (101.15-100.1)/100.1*10000
    expected = (101.15 - 100.1) / 100.1 * 10_000
    assert order.markout_1m_bps == pytest.approx(expected)


def test_price_improved_trade_fora_da_janela_nao_conta() -> None:
    book = _book([0], [100.0], [1.0], [100.3], [1.0])
    trades = _trades(times=[1_000_000], prices=[100.1], qtys=[1.0], is_buyer_maker=[True])
    order = fs._simulate_one_order_price_improved(
        book, trades, t_post_ms=0, side=1, fill_timeout_ms=900_000, tick_size=0.10
    )
    assert order is not None
    assert order.filled is False


# ============================================================================
# simulate_window_price_improved — encaminha para simulate_window com o
# núcleo trocado, sem duplicar IO/laço de orquestração.
# ============================================================================


def test_simulate_window_price_improved_encaminha_nucleo_correto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def _fake_simulate_window(*args: object, **kwargs: object) -> fs.SimulationRunResult:
        captured.update(kwargs)
        captured["args"] = args
        return fs.SimulationRunResult(
            orders=fs._empty_orders_frame(), n_skipped_no_book_state=0, n_days_no_data=0
        )

    monkeypatch.setattr(fs, "simulate_window", _fake_simulate_window)
    fs.simulate_window_price_improved("BTCUSDT", date(2023, 6, 1), date(2023, 6, 2))

    assert captured["_order_simulator"] is fs._simulate_one_order_price_improved
    assert captured["args"] == ("BTCUSDT", date(2023, 6, 1), date(2023, 6, 2))


# ============================================================================
# _day_grid_ms
# ============================================================================


def test_day_grid_tem_96_pontos_de_15_minutos() -> None:
    grid = fs._day_grid_ms(date(2024, 1, 15), 900_000)
    assert grid.shape[0] == 96
    assert int(grid[0]) == 1705276800000  # 2024-01-15T00:00:00Z em epoch ms
    assert int(grid[1]) - int(grid[0]) == 900_000
    assert int(grid[-1]) - int(grid[0]) == 95 * 900_000


# ============================================================================
# _dollar_bar_grid_ms / _resolve_day_grid_and_timeout — achado real (mapa de
# dívida técnica multi-ativo, 2026-08-22): a grade era sempre step_ms("15m")
# fixo, mesmo sob resolução dollar-bar, onde não existe cadência de relógio
# pra sintetizar. Sob dollar-bar, usa close_time REAL de cada barra.
# ============================================================================

_DAY_START_MS = 1705276800000  # 2024-01-15T00:00:00Z


def test_dollar_bar_grid_ms_usa_close_time_real(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_bars = pl.DataFrame(
        {"close_time": [_DAY_START_MS + 1_000, _DAY_START_MS + 500_000]},
        schema={"close_time": pl.Int64},
    )

    def _fake_query_dollar_bars(
        symbol: str, start: object, end: object, *, resolution_id: str, **kwargs: object
    ) -> pl.DataFrame:
        assert symbol == "BTCUSDT"
        assert resolution_id == "R1"
        return fake_bars

    monkeypatch.setattr(fs.lake, "query_dollar_bars", _fake_query_dollar_bars)
    grid = fs._dollar_bar_grid_ms("BTCUSDT", date(2024, 1, 15), "R1")
    assert grid.tolist() == [_DAY_START_MS + 1_000, _DAY_START_MS + 500_000]


def test_dollar_bar_grid_ms_filtra_barras_fora_do_dia_pedido(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`query_dollar_bars(day, day+1)` pode devolver barras de fora do dia
    exato (poda por arquivo, não por timestamp) -- filtra explicitamente."""
    fake_bars = pl.DataFrame(
        {"close_time": [_DAY_START_MS - 1, _DAY_START_MS + 1_000, _DAY_START_MS + 86_400_000]},
        schema={"close_time": pl.Int64},
    )
    monkeypatch.setattr(fs.lake, "query_dollar_bars", lambda *a, **k: fake_bars)
    grid = fs._dollar_bar_grid_ms("BTCUSDT", date(2024, 1, 15), "R1")
    assert grid.tolist() == [_DAY_START_MS + 1_000]


def test_dollar_bar_grid_ms_vazio_quando_sem_barra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        fs.lake,
        "query_dollar_bars",
        lambda *a, **k: pl.DataFrame(schema={"close_time": pl.Int64}),
    )
    grid = fs._dollar_bar_grid_ms("BTCUSDT", date(2024, 1, 15), "R1")
    assert grid.shape[0] == 0


def test_dollar_bar_grid_ms_symbol_ausente_levanta_erro_claro(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Achado CRITICAL corrigido (revisão `audit_engineering`, 2026-08-22):
    `lake.query_dollar_bars` levanta `FileNotFoundError` cru (sem
    contexto) se o diretório do symbol não existir em
    `data/capacity/dollar_bars_r{N}/` -- hoje só BTCUSDT tem esse
    diretório pras 3 resoluções. Re-levanta com mensagem acionável."""

    def _raise(*args: object, **kwargs: object) -> pl.DataFrame:
        raise FileNotFoundError("dir ausente")

    monkeypatch.setattr(fs.lake, "query_dollar_bars", _raise)
    with pytest.raises(FileNotFoundError, match="Backfill"):
        fs._dollar_bar_grid_ms("ETHUSDT", date(2024, 1, 15), "R1")


# ============================================================================
# _resolve_tick_size_cached — achado CRITICAL corrigido (revisão
# audit_engineering, 2026-08-22): load_filters_asof levanta
# NoFiltersAvailableError pra QUALQUER data anterior ao único snapshot em
# disco -- a janela default inteira do módulo (2023-2024) é anterior ao
# snapshot (2026-08-08). Sem fallback, simulate_window() sem argumentos
# crashava no 1º dia, 100% da janela, sempre.
# ============================================================================


def test_resolve_tick_size_cached_sem_fallback_propaga_erro(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`historical_filters_fallback=False` (default) preserva B01 -- nunca
    substitui silenciosamente, propaga o erro."""

    def _raise(*args: object, **kwargs: object) -> object:
        raise fs.NoFiltersAvailableError("sem snapshot pra esta data")

    monkeypatch.setattr(fs, "load_filters_asof", _raise)
    with pytest.raises(fs.NoFiltersAvailableError):
        fs._resolve_tick_size_cached(
            date(2023, 6, 1), "BTCUSDT", {}, [False], historical_filters_fallback=False
        )


def test_resolve_tick_size_cached_com_fallback_usa_snapshot_mais_recente(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeFilters:
        def __init__(self, tick_size: float, snapshot_date: date) -> None:
            self.tick_size = tick_size
            self.snapshot_date = snapshot_date

    def _fake_load_filters_asof(t: object, *, symbol: str, **kwargs: object) -> _FakeFilters:
        # `datetime` é subtipo de `date` (isinstance(t, date) seria True
        # pros dois), mas comparar datetime < date levanta TypeError em
        # Python -- normaliza pra date antes de comparar. `t` chega como
        # `date` puro na 1ª tentativa (linha do teste abaixo) e como
        # `datetime.now(tz=UTC)` no caminho de fallback real
        # (`_resolve_tick_size_cached`, mesmo padrão de
        # `triple_barrier._earliest_available_filters`).
        t_date = t.date() if isinstance(t, datetime) else t
        if t_date < date(2025, 1, 1):
            raise fs.NoFiltersAvailableError("sem snapshot histórico")
        return _FakeFilters(tick_size=0.05, snapshot_date=date(2026, 8, 8))

    monkeypatch.setattr(fs, "load_filters_asof", _fake_load_filters_asof)
    tick_size = fs._resolve_tick_size_cached(
        date(2023, 6, 1), "BTCUSDT", {}, [False], historical_filters_fallback=True
    )
    assert tick_size == pytest.approx(0.05)


def test_resolve_tick_size_cached_usa_cache_por_dia(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[date] = []

    class _FakeFilters:
        tick_size = 0.10

    def _fake_load_filters_asof(t: date, *, symbol: str, **kwargs: object) -> _FakeFilters:
        calls.append(t)
        return _FakeFilters()

    monkeypatch.setattr(fs, "load_filters_asof", _fake_load_filters_asof)
    cache: dict[date, float] = {}
    warned = [False]
    fs._resolve_tick_size_cached(
        date(2024, 1, 15), "BTCUSDT", cache, warned, historical_filters_fallback=False
    )
    fs._resolve_tick_size_cached(
        date(2024, 1, 15), "BTCUSDT", cache, warned, historical_filters_fallback=False
    )
    assert len(calls) == 1  # 2ª chamada usa o cache, não reconsulta


def test_simulate_window_sem_fallback_propaga_erro_de_filtro_ausente(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ponta a ponta: `simulate_window` sem `historical_filters_fallback`
    propaga `NoFiltersAvailableError` em vez de crashar com traceback
    genérico ou (pior) produzir resultado silenciosamente errado."""

    def _fake_load_book_ticker_pair(symbol: str, day: date) -> pl.DataFrame:
        t0 = int(fs._day_grid_ms(day, 900_000)[0])
        return pl.DataFrame(
            {
                "transaction_time": [t0],
                "best_bid_price": [100.0],
                "best_bid_qty": [0.0],
                "best_ask_price": [100.1],
                "best_ask_qty": [0.0],
            }
        )

    def _raise(*args: object, **kwargs: object) -> object:
        raise fs.NoFiltersAvailableError("sem snapshot")

    monkeypatch.setattr(fs, "load_book_ticker_pair", _fake_load_book_ticker_pair)
    monkeypatch.setattr(fs, "load_filters_asof", _raise)
    monkeypatch.setattr(fs.lake, "query_agg_trades", lambda *a, **k: pl.DataFrame())

    with pytest.raises(fs.NoFiltersAvailableError):
        fs.simulate_window("BTCUSDT", date(2024, 1, 15), date(2024, 1, 15))


# ============================================================================
# n_days_no_dollar_bar_grid — achado HIGH corrigido (revisão
# audit_engineering, 2026-08-22): "zero medido" (dia sem barra, symbol/
# resolução existem) precisa ficar visível, não conflar com sucesso.
# ============================================================================


def test_simulate_window_conta_dias_sem_dollar_bar_grid(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeFilters:
        tick_size = 0.10

    def _fake_load_book_ticker_pair(symbol: str, day: date) -> pl.DataFrame:
        t0 = int(fs._day_grid_ms(day, 900_000)[0])
        return pl.DataFrame(
            {
                "transaction_time": [t0],
                "best_bid_price": [100.0],
                "best_bid_qty": [0.0],
                "best_ask_price": [100.1],
                "best_ask_qty": [0.0],
            }
        )

    monkeypatch.setattr(fs, "load_book_ticker_pair", _fake_load_book_ticker_pair)
    monkeypatch.setattr(fs, "load_filters_asof", lambda day, *, symbol, **k: _FakeFilters())
    monkeypatch.setattr(fs.lake, "query_agg_trades", lambda *a, **k: pl.DataFrame())
    monkeypatch.setattr(
        fs.lake,
        "query_dollar_bars",
        lambda *a, **k: pl.DataFrame(schema={"close_time": pl.Int64}),
    )

    result = fs.simulate_window(
        "BTCUSDT", date(2024, 1, 15), date(2024, 1, 15), resolution_id="R1"
    )
    assert result.n_days_no_dollar_bar_grid == 1
    assert result.orders.height == 0  # grade vazia -> nenhuma ordem simulada


def test_resolve_day_grid_and_timeout_grade_de_tempo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fs, "load_constant", lambda name: 1)
    grid, timeout_ms = fs._resolve_day_grid_and_timeout(
        "BTCUSDT", date(2024, 1, 15), tf="15m", resolution_id=None, fill_timeout_bars=None
    )
    assert grid.shape[0] == 96
    assert timeout_ms == 900_000


def test_resolve_day_grid_and_timeout_grade_dollar_bar(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_bars = pl.DataFrame({"close_time": [_DAY_START_MS + 42]}, schema={"close_time": pl.Int64})
    monkeypatch.setattr(fs.lake, "query_dollar_bars", lambda *a, **k: fake_bars)
    grid, timeout_ms = fs._resolve_day_grid_and_timeout(
        "BTCUSDT", date(2024, 1, 15), tf="15m", resolution_id="R1", fill_timeout_bars=2
    )
    assert grid.tolist() == [_DAY_START_MS + 42]
    # fill_timeout_ms fica ancorado em 15m-clock mesmo sob dollar-bar --
    # decisão explícita (ver docstring de _resolve_day_grid_and_timeout),
    # não escala com a grade de decisão.
    assert timeout_ms == 2 * 900_000


# ============================================================================
# summarize
# ============================================================================


def test_summarize_dataset_vazio() -> None:
    empty = fs._empty_orders_frame()
    summary = fs.summarize(empty, symbol="BTCUSDT", start="2024-01-01", end="2024-01-02")
    assert summary.n_orders == 0
    assert summary.n_filled == 0
    assert np.isnan(summary.p_fill)


def test_summarize_conta_p_fill_e_markout_corretamente() -> None:
    cols: dict[str, list[object]] = {c: [] for c in fs._ORDERS_SCHEMA}
    rows = [
        # side, filled, t_entry, fill_price, m1, m5, m30
        (1, True, 0, 100.0, 1.0, 2.0, 3.0),
        (1, False, None, None, None, None, None),
        (-1, True, 0, 100.0, -1.0, -2.0, None),
    ]
    for side, filled, t_entry, fill_price, m1, m5, m30 in rows:
        cols["symbol"].append("BTCUSDT")
        cols["t_post"].append(0)
        cols["side"].append(side)
        cols["limit_price"].append(100.0)
        cols["queue_ahead_initial"].append(0.0)
        cols["filled"].append(filled)
        cols["t_entry"].append(t_entry)
        cols["fill_price"].append(fill_price)
        cols["markout_1m_bps"].append(m1)
        cols["markout_5m_bps"].append(m5)
        cols["markout_30m_bps"].append(m30)
    df = fs._finalize_orders_frame(cols)

    summary = fs.summarize(df, symbol="BTCUSDT", start="2024-01-01", end="2024-01-02")
    assert summary.n_orders == 3
    assert summary.n_filled == 2
    assert summary.n_nofill == 1
    assert summary.p_fill == pytest.approx(2 / 3)
    assert summary.p_fill_by_side["buy"] == pytest.approx(1 / 2)
    assert summary.p_fill_by_side["sell"] == pytest.approx(1.0)
    assert summary.markout_n["1m"] == 2
    assert summary.markout_mean_bps["1m"] == pytest.approx((1.0 + -1.0) / 2)
    assert summary.markout_n["30m"] == 1  # um dos fills tem markout_30m None
    assert summary.markout_mean_bps["30m"] == pytest.approx(3.0)


# ============================================================================
# calibrate_against_real_fills — hook não implementado
# ============================================================================


def test_calibrate_against_real_fills_levanta_not_implemented() -> None:
    empty = fs._empty_orders_frame()
    with pytest.raises(NotImplementedError):
        fs.calibrate_against_real_fills(empty, empty)


# ============================================================================
# simulate_window — guard-rails (sem IO real — falha antes de tocar disco)
# ============================================================================


def test_simulate_window_recusa_janela_pos_quebra_rpi() -> None:
    with pytest.raises(ValueError, match="RPI"):
        fs.simulate_window("BTCUSDT", date(2025, 11, 1), date(2025, 12, 1))


def test_simulate_window_recusa_tf_e_resolution_id_simultaneos() -> None:
    """Mesma disciplina de `src.models.dataset.build_modeling_frame` — um
    parâmetro de grade só, dois que pudessem divergir reintroduziriam
    incoerência silenciosa."""
    with pytest.raises(ValueError, match="resolution_id"):
        fs.simulate_window(
            "BTCUSDT", date(2023, 6, 1), date(2023, 6, 2), tf="30m", resolution_id="R1"
        )


def test_simulate_window_resolve_tick_size_via_filters_nao_constante_global(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Achado real (mapa de dívida técnica multi-ativo, 2026-08-22):
    `tick_size` vinha de uma constante global calibrada em BTCUSDT
    (`exchangeInfo BTCUSDT`), usada pra QUALQUER símbolo — tick size varia
    até 1000x entre os 5 símbolos (BTC=0.10, XRP=0.0001). Confirma que
    agora resolve via `Filters` por symbol+dia (`load_filters_asof`, mesmo
    padrão de `src.risk.sizing`), nunca `load_constant("tick_size")`."""
    calls: list[tuple[object, str]] = []

    class _FakeFilters:
        tick_size = 0.01  # ETHUSDT real -- != 0.10 (constante global de BTC)

    def _fake_load_filters_asof(day: object, *, symbol: str, **kwargs: object) -> _FakeFilters:
        calls.append((day, symbol))
        return _FakeFilters()

    def _fake_load_book_ticker_pair(symbol: str, day: date) -> pl.DataFrame:
        t0 = int(fs._day_grid_ms(day, 900_000)[0])
        return pl.DataFrame(
            {
                "transaction_time": [t0],
                "best_bid_price": [100.0],
                "best_bid_qty": [0.0],  # queue_ahead=0 -> preenche no post, sem IO de trades
                "best_ask_price": [100.1],
                "best_ask_qty": [0.0],
            }
        )

    monkeypatch.setattr(fs, "load_filters_asof", _fake_load_filters_asof)
    monkeypatch.setattr(fs, "load_book_ticker_pair", _fake_load_book_ticker_pair)
    monkeypatch.setattr(fs.lake, "query_agg_trades", lambda *a, **k: pl.DataFrame())

    result = fs.simulate_window("ETHUSDT", date(2024, 1, 15), date(2024, 1, 15))

    assert calls == [(date(2024, 1, 15), "ETHUSDT")]
    assert result.orders.height > 0


# ============================================================================
# Escrita atômica + log de experimentos — tmp_path, nunca o arquivo real do repo
# ============================================================================


def _dummy_summary() -> fs.FillSimulationSummary:
    return fs.FillSimulationSummary(
        symbol="BTCUSDT",
        start="2024-01-01",
        end="2024-01-02",
        n_orders=10,
        n_filled=6,
        n_nofill=4,
        p_fill=0.6,
        n_skipped_no_book_state=0,
        n_days_no_data=0,
        p_fill_by_side={"buy": 0.6, "sell": 0.6},
        markout_mean_bps={"1m": 0.5, "5m": 1.0, "30m": 1.5},
        markout_median_bps={"1m": 0.4, "5m": 0.9, "30m": 1.4},
        markout_n={"1m": 6, "5m": 6, "30m": 5},
    )


def test_write_orders_atomic_e_write_summary_atomic(tmp_path: Path) -> None:
    df = fs._empty_orders_frame()
    orders_path = fs.write_orders_atomic(df, dest_dir=tmp_path)
    assert orders_path.exists()
    assert orders_path.name == "orders.parquet"

    summary = _dummy_summary()
    summary_path = fs.write_summary_atomic(summary, dest_dir=tmp_path)
    assert summary_path.exists()
    assert summary_path.name == "summary.json"
    import orjson

    payload = orjson.loads(summary_path.read_bytes())
    assert payload["p_fill"] == 0.6
    assert payload["markout_mean_bps"]["5m"] == 1.0


def test_record_experiment_cria_e_acrescenta(tmp_path: Path) -> None:
    log_path = tmp_path / "runs.parquet"
    summary = _dummy_summary()

    written = fs.record_experiment(
        summary, fill_timeout_bars_used=1, tick_size_used=0.10, path=log_path
    )
    assert written == log_path
    out = fs.load_experiment_log(log_path)
    assert out.height == 1
    assert out["run_id"][0] == 1
    assert out["p_fill"][0] == 0.6

    fs.record_experiment(
        summary, fill_timeout_bars_used=1, tick_size_used=0.10, path=log_path, notes="segunda run"
    )
    out2 = fs.load_experiment_log(log_path)
    assert out2.height == 2
    assert sorted(out2["run_id"].to_list()) == [1, 2]


# ============================================================================
# Integração leve — confirma o schema real de bookTicker (skip se ausente)
# ============================================================================

_SCHEMA_FIXTURE_DAY = "2023-06-01"


@pytest.mark.integration
def test_load_book_ticker_pair_schema_real() -> None:
    _skip_if_missing_book_ticker(_SCHEMA_FIXTURE_DAY)
    df = fs.load_book_ticker_pair(_SYMBOL, date.fromisoformat(_SCHEMA_FIXTURE_DAY))
    assert not df.is_empty()
    for col in fs._BOOK_TICKER_COLUMNS:
        assert col in df.columns
    # ordenado por transaction_time
    ts = df["transaction_time"].to_numpy()
    assert bool((ts[1:] >= ts[:-1]).all())
