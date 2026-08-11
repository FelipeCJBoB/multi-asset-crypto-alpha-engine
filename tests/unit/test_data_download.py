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
