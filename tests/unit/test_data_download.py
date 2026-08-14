"""Testes de `src/data/download.py` — majoritariamente lógica pura (URL,
header detection, parsing, split por dia, seleção de partição). Nada de
rede real em nenhum teste.

`test_klines_partition_for_date_*` é o "teste obrigatório" que
PRD_V4_1.md §2.5 (F5) e §3.1 (T0.3) pedem e que não existia antes deste
módulo: falha se a seleção monthly/daily estiver errada.

`test_download_klines_1m_regime_*` (AG-014, `audit/architecture_gaps_log.
yaml`) são a exceção à regra "só lógica pura": `_download_with_retries`/
`_verify_checksum` são substituídas (`monkeypatch`) por stubs em memória —
ainda sem rede real, só o suficiente pra provar que o regime `"daily"`
agora faz 1 request POR DIA (não 1 por mês tentando cobrir `target_days`
inteiro com uma única URL diária, o bug original) e que o regime
`"monthly"` continua bit-exato (1 request só, cobrindo o mês inteiro).
`CAPACITY_DIR`/`_MANIFEST_PATH` também são substituídos por um `tmp_path`
isolado — nenhum dos dois testes toca `data/capacity/klines_1m/` real."""

from __future__ import annotations

import io
import zipfile
from datetime import date
from pathlib import Path

import polars as pl
import pytest
import requests

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


def test_mark_price_klines_url_monthly() -> None:
    url = dl._mark_price_klines_url("ETHUSDT", "monthly", date(2021, 12, 15))
    assert url == (
        "https://data.binance.vision/data/futures/um/monthly/markPriceKlines/"
        "ETHUSDT/1m/ETHUSDT-1m-2021-12.zip"
    )


def test_mark_price_klines_url_daily() -> None:
    url = dl._mark_price_klines_url("XRPUSDT", "daily", date(2026, 8, 1))
    assert url == (
        "https://data.binance.vision/data/futures/um/daily/markPriceKlines/"
        "XRPUSDT/1m/XRPUSDT-1m-2026-08-01.zip"
    )


def test_mark_price_klines_1m_registrado_em_source_downloaders() -> None:
    """`mark_price_klines_1m` (AG-014) precisa estar em `SOURCE_DOWNLOADERS`
    pra `--sources mark_price_klines_1m` funcionar na CLI, e opt-in (fora
    de `DEFAULT_SOURCES`, mesmo padrão de `agg_trades`/`book_ticker`) —
    ninguém deveria baixar isso sem pedir explicitamente."""
    assert dl.SOURCE_DOWNLOADERS["mark_price_klines_1m"] is dl.download_mark_price_klines_1m
    assert "mark_price_klines_1m" not in dl.DEFAULT_SOURCES


# ============================================================================
# AG-014 — download_klines_1m regime "daily" fazia 1 request pro mês
# inteiro (URL de um único dia tratada como se cobrisse target_days
# inteiro). Corrigido pra replicar o padrão de
# download_mark_price_klines_1m: 1 request POR DIA no regime "daily".
# ============================================================================


def _zip_with_single_csv(csv_text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("data.csv", csv_text)
    return buf.getvalue()


def _klines_row(open_time_ms: int) -> str:
    # 12 colunas de schemas.KLINES_1M, todas non_nullable preenchidas com
    # valor trivial -- só `open_time`/`close_time` variam entre linhas.
    return f"{open_time_ms},1,1,1,1,1.0,{open_time_ms + 59_999},1.0,1,1.0,1.0,0"


def test_download_klines_1m_regime_daily_faz_1_request_por_dia(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Antes da correção, o regime `"daily"` fazia `_klines_url(symbol,
    "daily", month_start)` — 1 request cobrindo só o dia 1º do mês — e
    tentava satisfazer `target_days` inteiro (~30 dias) com aquele payload
    de 1 dia só. Prova, sem rede real, que a versão corrigida faz 1
    request por dia, cada um contra a URL do dia certo (não `month_start`
    repetido), e escreve um parquet por dia."""
    monkeypatch.setattr(dl, "CAPACITY_DIR", tmp_path)
    monkeypatch.setattr(dl, "_MANIFEST_PATH", tmp_path / "_download_log" / "manifest.jsonl")

    requested_urls: list[str] = []

    def _fake_download(session: requests.Session, url: str) -> bytes:
        requested_urls.append(url)
        # Regime "daily" não passa pelo `_split_klines_by_day` -- o
        # `open_time` da linha não precisa bater com o dia `d` do request.
        return _zip_with_single_csv(_klines_row(1_685_577_600_000) + "\n")

    monkeypatch.setattr(dl, "_download_with_retries", _fake_download)
    monkeypatch.setattr(dl, "_verify_checksum", lambda *_a, **_k: None)

    start, end = date(2023, 6, 1), date(2023, 6, 3)  # regime "daily" (cutover = 2023-06-01)
    dl.download_klines_1m("ETHUSDT", start, end, session=requests.Session())

    assert requested_urls == [
        dl._klines_url("ETHUSDT", "daily", date(2023, 6, 1)),
        dl._klines_url("ETHUSDT", "daily", date(2023, 6, 2)),
        dl._klines_url("ETHUSDT", "daily", date(2023, 6, 3)),
    ]
    out_dir = tmp_path / "klines_1m" / "ETHUSDT"
    written = sorted(p.name for p in out_dir.glob("*.parquet"))
    assert written == ["2023-06-01.parquet", "2023-06-02.parquet", "2023-06-03.parquet"]


def test_download_klines_1m_regime_monthly_continua_1_request_por_mes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Regressão: o regime `"monthly"` (antes do cutover) precisa
    continuar fazendo exatamente 1 request cobrindo o mês inteiro — a
    correção do regime `"daily"` (AG-014) não pode mudar esse
    comportamento preexistente."""
    monkeypatch.setattr(dl, "CAPACITY_DIR", tmp_path)
    monkeypatch.setattr(dl, "_MANIFEST_PATH", tmp_path / "_download_log" / "manifest.jsonl")

    requested_urls: list[str] = []
    # 2021-12-30T00:00:00Z / 2021-12-31T00:00:00Z em epoch ms -- 1 barra por
    # dia é suficiente pro `_split_klines_by_day` separar os 2 dias-alvo.
    month_csv = "\n".join(
        _klines_row(open_time_ms) for open_time_ms in (1_640_822_400_000, 1_640_908_800_000)
    ) + "\n"

    def _fake_download(session: requests.Session, url: str) -> bytes:
        requested_urls.append(url)
        return _zip_with_single_csv(month_csv)

    monkeypatch.setattr(dl, "_download_with_retries", _fake_download)
    monkeypatch.setattr(dl, "_verify_checksum", lambda *_a, **_k: None)

    start, end = date(2021, 12, 30), date(2021, 12, 31)  # regime "monthly"
    dl.download_klines_1m("ETHUSDT", start, end, session=requests.Session())

    assert requested_urls == [dl._klines_url("ETHUSDT", "monthly", date(2021, 12, 1))]
    out_dir = tmp_path / "klines_1m" / "ETHUSDT"
    written = sorted(p.name for p in out_dir.glob("*.parquet"))
    assert written == ["2021-12-30.parquet", "2021-12-31.parquet"]


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
