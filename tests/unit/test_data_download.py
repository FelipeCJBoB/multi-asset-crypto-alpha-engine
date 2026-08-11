"""Testes de `src/data/download.py` — só lógica pura (URL, header
detection, parsing, split por dia, seleção de partição). Nada de rede real
(`_download_with_retries`/`_verify_checksum` não são testados aqui —
exigiriam mock de `requests`, fora do escopo desta rodada).

`test_klines_partition_for_date_*` é o "teste obrigatório" que
PRD_V4_1.md §2.5 (F5) e §3.1 (T0.3) pedem e que não existia antes deste
módulo: falha se a seleção monthly/daily estiver errada."""

from __future__ import annotations

from datetime import date

import polars as pl

from src.data import download as dl
from src.data import schemas


def test_klines_partition_for_date_antes_do_cutover_e_monthly() -> None:
    assert dl.klines_partition_for_date(date(2021, 12, 1)) == "monthly"
    assert dl.klines_partition_for_date(date(2023, 5, 31)) == "monthly"


def test_klines_partition_for_date_no_cutover_e_apos_e_daily() -> None:
    assert dl.klines_partition_for_date(date(2023, 6, 1)) == "daily"
    assert dl.klines_partition_for_date(date(2026, 8, 1)) == "daily"


def test_klines_url_monthly() -> None:
    url = dl._klines_url("ETHUSDT", "monthly", date(2021, 12, 15))
    assert url == (
        "https://data.binance.vision/data/futures/um/monthly/klines/"
        "ETHUSDT/1m/ETHUSDT-1m-2021-12.zip"
    )


def test_klines_url_daily() -> None:
    url = dl._klines_url("ETHUSDT", "daily", date(2026, 1, 5))
    assert url == (
        "https://data.binance.vision/data/futures/um/daily/klines/"
        "ETHUSDT/1m/ETHUSDT-1m-2026-01-05.zip"
    )


def test_metrics_url() -> None:
    url = dl._metrics_url("SOLUSDT", date(2022, 3, 1))
    assert url == (
        "https://data.binance.vision/data/futures/um/daily/metrics/"
        "SOLUSDT/SOLUSDT-metrics-2022-03-01.zip"
    )


def test_funding_url() -> None:
    url = dl._funding_url("BNBUSDT", 2022, 7)
    assert url == (
        "https://data.binance.vision/data/futures/um/monthly/fundingRate/"
        "BNBUSDT/BNBUSDT-fundingRate-2022-07.zip"
    )


def test_has_header_true_quando_primeira_celula_bate_nome_da_coluna() -> None:
    assert dl._has_header("calc_time,funding_interval_hours,last_funding_rate", "calc_time")


def test_has_header_false_quando_primeira_celula_e_dado() -> None:
    assert not dl._has_header("1638316800000,8,0.00010000", "calc_time")


def test_parse_csv_funding_sem_header() -> None:
    csv_text = "1638316800000,8,0.00010000\n1638345600000,8,-0.00005000\n"
    df = dl._parse_csv(csv_text, schemas.FUNDING)
    assert df.columns == ["calc_time", "funding_interval_hours", "last_funding_rate"]
    assert df.schema["calc_time"] == pl.Int64
    assert df.schema["funding_interval_hours"] == pl.Int64
    assert df.schema["last_funding_rate"] == pl.Utf8
    assert df.height == 2
    assert df["calc_time"].to_list() == [1638316800000, 1638345600000]


def test_parse_csv_metrics_celula_vazia_em_coluna_nullable_vira_null() -> None:
    # Reproduz o que foi medido ao vivo em 2021-12-30 (ETH/SOL/BNB/XRP, sessão
    # 2026-08-11): Binance não populava count_long_short_ratio pros alts nos
    # primeiros dias do dataset de metrics — "" no CSV cru, não erro de rede.
    header = (
        "create_time,symbol,sum_open_interest,sum_open_interest_value,"
        "count_toptrader_long_short_ratio,sum_toptrader_long_short_ratio,"
        "count_long_short_ratio,sum_taker_long_short_vol_ratio\n"
    )
    row = '2021-12-30 00:00:00,ETHUSDT,123.4,567.8,1.1,2.2,"",4.4\n'
    df = dl._parse_csv(header + row, schemas.METRICS)
    assert df.height == 1
    assert df["count_long_short_ratio"].to_list() == [None]
    assert df["sum_open_interest"].to_list() == [123.4]
    assert df.schema["count_long_short_ratio"] == pl.Float64


def test_parse_csv_klines_celula_vazia_em_coluna_non_nullable_vira_null() -> None:
    # Medido: campo CSV vazio vira `null` no Polars (não ""), e null atravessa
    # cast mesmo com strict=True — strict só rejeita valor não-nulo ilegível,
    # não substitui a checagem de `non_nullable`. Enforcement de
    # `non_nullable` é responsabilidade de `src.data.validate` (check de
    # integridade downstream), não de `_parse_csv` — este teste documenta
    # esse limite em vez de presumir que o download.py barra aqui.
    row = ',"1","1","1","1",1.0,1638403080000,1.0,1,1.0,1.0,"0"\n'
    df = dl._parse_csv(row, schemas.KLINES_1M)
    assert df["open_time"].to_list() == [None]


def test_parse_csv_funding_com_header_e_pulado() -> None:
    csv_text = (
        "calc_time,funding_interval_hours,last_funding_rate\n"
        "1638316800000,8,0.00010000\n"
    )
    df = dl._parse_csv(csv_text, schemas.FUNDING)
    assert df.height == 1
    assert df["calc_time"].to_list() == [1638316800000]


def test_split_klines_by_day_separa_corretamente_na_virada() -> None:
    # duas barras no dia 1 (2021-12-01 23:58/23:59 UTC), uma no dia 2 (2021-12-02 00:00 UTC)
    open_times = [1638403080000, 1638403140000, 1638403200000]
    df = pl.DataFrame(
        {
            "open_time": open_times,
            "open": ["1", "2", "3"],
            "high": ["1", "2", "3"],
            "low": ["1", "2", "3"],
            "close": ["1", "2", "3"],
            "volume": [1.0, 2.0, 3.0],
            "close_time": [t + 59_999 for t in open_times],
            "quote_volume": [1.0, 2.0, 3.0],
            "count": [1, 1, 1],
            "taker_buy_volume": [1.0, 2.0, 3.0],
            "taker_buy_quote_volume": [1.0, 2.0, 3.0],
            "ignore": ["0", "0", "0"],
        },
        schema=dict(schemas.KLINES_1M.columns),
    )
    by_day = dl._split_klines_by_day(df)
    assert set(by_day.keys()) == {date(2021, 12, 1), date(2021, 12, 2)}
    assert by_day[date(2021, 12, 1)].height == 2
    assert by_day[date(2021, 12, 2)].height == 1


def test_month_range_cobre_virada_de_ano() -> None:
    months = list(dl._month_range(date(2022, 11, 15), date(2023, 2, 1)))
    assert months == [(2022, 11), (2022, 12), (2023, 1), (2023, 2)]


def test_date_range_e_inclusivo_nas_duas_pontas() -> None:
    days = list(dl._date_range(date(2022, 1, 30), date(2022, 2, 1)))
    assert days == [date(2022, 1, 30), date(2022, 1, 31), date(2022, 2, 1)]


def test_agg_trades_url() -> None:
    url = dl._agg_trades_url("ETHUSDT", date(2022, 3, 1))
    assert url == (
        "https://data.binance.vision/data/futures/um/daily/aggTrades/"
        "ETHUSDT/ETHUSDT-aggTrades-2022-03-01.zip"
    )


def test_book_ticker_url() -> None:
    url = dl._book_ticker_url("SOLUSDT", date(2023, 6, 1))
    assert url == (
        "https://data.binance.vision/data/futures/um/daily/bookTicker/"
        "SOLUSDT/SOLUSDT-bookTicker-2023-06-01.zip"
    )


def test_parse_csv_agg_trades_is_buyer_maker_string_vira_boolean() -> None:
    # Medido ao vivo em 2026-08-11 (amostra real ETHUSDT-aggTrades-2022-03-01):
    # CSV sem header, is_buyer_maker chega como "true"/"false" (string), não
    # 0/1 -- confirma que Polars faz esse cast Utf8 -> Boolean sem crashar
    # (não documentado no schema, então não presumido, testado).
    csv_text = (
        "766470841,2920.05,22.308,1474115524,1474115533,1646092800145,false\n"
        "766470842,2920.08,0.119,1474115534,1474115534,1646092800175,true\n"
    )
    df = dl._parse_csv(csv_text, schemas.AGG_TRADES)
    assert df["is_buyer_maker"].to_list() == [False, True]
    assert df.schema["is_buyer_maker"] == pl.Boolean
    assert df["agg_trade_id"].to_list() == [766470841, 766470842]


def test_parse_book_ticker_csv_com_header_descarta_update_id_e_event_time() -> None:
    # Header real medido em 2026-08-11 (amostra ETHUSDT-bookTicker-2023-06-01):
    # 7 colunas no CSV bruto, só 5 sobrevivem no parquet local (mesmo
    # contrato de data/raw/book_ticker/BTCUSDT/ já em disco).
    csv_text = (
        "update_id,best_bid_price,best_bid_qty,best_ask_price,best_ask_qty,"
        "transaction_time,event_time\n"
        "2899808024194,1872.84000000,55.72800000,1872.85000000,24.16400000,"
        "1685577600027,1685577600031\n"
    )
    df = dl._parse_book_ticker_csv(csv_text)
    assert df.columns == [
        "transaction_time",
        "best_bid_price",
        "best_bid_qty",
        "best_ask_price",
        "best_ask_qty",
    ]
    assert df["transaction_time"].to_list() == [1685577600027]
    assert df["best_bid_price"].to_list() == [1872.84]
    assert df.schema["best_bid_price"] == pl.Float64


def test_parse_book_ticker_csv_sem_header() -> None:
    csv_text = (
        "2899808024194,1872.84000000,55.72800000,1872.85000000,24.16400000,"
        "1685577600027,1685577600031\n"
    )
    df = dl._parse_book_ticker_csv(csv_text)
    assert df.height == 1
    assert df["best_ask_qty"].to_list() == [24.164]


def test_clip_to_book_ticker_window_pedido_maior_recorta_dos_dois_lados() -> None:
    clipped = dl._clip_to_book_ticker_window(date(2021, 12, 1), date(2026, 8, 7))
    assert clipped == (dl.BOOK_TICKER_WINDOW_START, dl.BOOK_TICKER_WINDOW_END)


def test_clip_to_book_ticker_window_pedido_dentro_da_janela_nao_recorta() -> None:
    start, end = date(2023, 6, 1), date(2023, 12, 1)
    assert dl._clip_to_book_ticker_window(start, end) == (start, end)


def test_clip_to_book_ticker_window_pedido_fora_da_janela_retorna_none() -> None:
    assert dl._clip_to_book_ticker_window(date(2020, 1, 1), date(2020, 12, 31)) is None
    assert dl._clip_to_book_ticker_window(date(2025, 1, 1), date(2025, 12, 31)) is None
