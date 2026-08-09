"""Testes de `src/data/lake.py`. A poda de arquivo por nome (`_list_day_files`
/ `_list_month_files`) é testada com arquivos vazios em `tmp_path` (só o
NOME importa para essa função); as funções `query_*` são testadas contra um
recorte real pequeno de `data/capacity/` (3 dias fixos, já confirmados
presentes no backfill) — sem isso, o teste de integração real da tarefa
("rode a validação real") não teria como existir."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from src.data import lake
from src.data._paths import CAPACITY_DIR

_FIXTURE_START = "2024-01-15"
_FIXTURE_END = "2024-01-17"  # 3 dias
_FIXTURE_MONTH = "2024-01"  # funding é mensal, não diário — ver schemas.FUNDING


def _skip_if_missing(*sources: str) -> None:
    for source in sources:
        d = CAPACITY_DIR / source / "BTCUSDT"
        stem = _FIXTURE_MONTH if source == "funding" else _FIXTURE_START
        filename = f"{stem}.parquet"
        if not (d / filename).exists():
            pytest.skip(f"fixture ausente no backfill local: {d / filename}")


# ============================================================================
# poda de arquivo por nome — não precisa de dado real
# ============================================================================


def test_list_day_files_filtra_por_intervalo(tmp_path: Path) -> None:
    for name in ("2024-01-01", "2024-01-02", "2024-01-03", "not-a-date"):
        (tmp_path / f"{name}.parquet").write_bytes(b"")
    files = lake._list_day_files(tmp_path, date(2024, 1, 2), date(2024, 1, 3))
    assert [f.stem for f in files] == ["2024-01-02", "2024-01-03"]


def test_list_day_files_sem_limites_pega_tudo(tmp_path: Path) -> None:
    for name in ("2024-01-01", "2024-01-02"):
        (tmp_path / f"{name}.parquet").write_bytes(b"")
    files = lake._list_day_files(tmp_path, None, None)
    assert len(files) == 2


def test_list_month_files_filtra_por_intervalo(tmp_path: Path) -> None:
    for name in ("2024-01", "2024-02", "2024-03"):
        (tmp_path / f"{name}.parquet").write_bytes(b"")
    files = lake._list_month_files(tmp_path, date(2024, 2, 15), date(2024, 3, 1))
    assert [f.stem for f in files] == ["2024-02", "2024-03"]


def test_day_bounds_ms_e_utc_independente_do_fuso_local() -> None:
    start_ms, end_ms = lake._day_bounds_ms("2024-01-15", "2024-01-15")
    assert start_ms == 1705276800000  # 2024-01-15T00:00:00Z, calculado independentemente
    assert end_ms == 1705276800000 + 86_400_000 - 1


# ============================================================================
# query_* contra dado real (fixture fixo, 3 dias)
# ============================================================================


@pytest.mark.integration
def test_query_bars_klines_1m() -> None:
    _skip_if_missing("klines_1m")
    df = lake.query_bars(
        "BTCUSDT", "1m", _FIXTURE_START, _FIXTURE_END, source="klines_1m", cast_prices=False
    )
    assert df.height == 3 * 1440
    assert df.schema["open"] == pl.Utf8
    assert df["open_time"].is_sorted()


@pytest.mark.integration
def test_query_bars_cast_prices() -> None:
    _skip_if_missing("klines_1m")
    df = lake.query_bars(
        "BTCUSDT", "1m", _FIXTURE_START, _FIXTURE_START, source="klines_1m", cast_prices=True
    )
    assert df.schema["open"] == pl.Float64


@pytest.mark.integration
def test_query_bars_resample_compoe_com_lake() -> None:
    _skip_if_missing("klines_1m")
    df_30m = lake.query_bars("BTCUSDT", "30m", _FIXTURE_START, _FIXTURE_END, source="klines_1m")
    assert df_30m.height == 3 * 48  # 3 dias * 48 barras de 30m


def test_query_bars_source_invalido_levanta_erro() -> None:
    with pytest.raises(ValueError):
        lake.query_bars("BTCUSDT", "1m", _FIXTURE_START, _FIXTURE_END, source="metrics")


@pytest.mark.integration
def test_query_agg_trades() -> None:
    _skip_if_missing("agg_trades")
    df = lake.query_agg_trades("BTCUSDT", _FIXTURE_START, _FIXTURE_START)
    assert df.height > 0
    assert df["transact_time"].is_sorted()


@pytest.mark.integration
def test_query_metrics() -> None:
    _skip_if_missing("metrics")
    df = lake.query_metrics("BTCUSDT", _FIXTURE_START, _FIXTURE_END)
    assert df.height == 3 * 288  # 288 pontos de 5m por dia


@pytest.mark.integration
def test_query_funding() -> None:
    _skip_if_missing("funding")
    df = lake.query_funding("BTCUSDT", _FIXTURE_START, _FIXTURE_END)
    assert df.height > 0
    assert df["calc_time"].is_sorted()


def test_query_bars_range_fora_de_cobertura_retorna_vazio() -> None:
    df = lake.query_bars("BTCUSDT", "1m", "1900-01-01", "1900-01-02", source="klines_1m")
    assert df.height == 0
