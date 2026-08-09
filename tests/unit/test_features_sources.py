"""Testes de `src/features/_sources.py`: asof-join causal (nunca usa
evento futuro) e a resolução determinística do duplicado real de
`create_time` medido em `metrics` (Sprint 3/4 — ver docstring de
`load_oi_series_deduped`), tudo com fixtures sintéticas em `tmp_path` (não
precisa do dado real do backfill para provar a lógica)."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from src.features import _paths as features_paths
from src.features import _sources


def _bars(open_times: list[int]) -> pl.DataFrame:
    step = 900_000  # 15m em ms
    return pl.DataFrame(
        {
            "open_time": open_times,
            "close_time": [t + step - 1 for t in open_times],
        }
    )


# ============================================================================
# asof_align_backward
# ============================================================================


def test_asof_align_backward_pega_ultimo_evento_anterior() -> None:
    bars = _bars([0, 900_000, 1_800_000, 2_700_000])
    aux = pl.DataFrame(
        {
            "ts": [500_000, 1_700_000, 2_600_000],
            "value": [10.0, 20.0, 30.0],
        }
    )
    out = _sources.asof_align_backward(bars, aux, "ts", "value")
    # barra 0 (close_time=899999): último evento <= 899999 é 500000 -> 10.0
    assert out[0] == pytest.approx(10.0)
    # barra 1 (close_time=1799999): último evento <= 1799999 é 1700000 -> 20.0
    assert out[1] == pytest.approx(20.0)
    # barra 2 (close_time=2699999): último evento <= 2699999 é 2600000 -> 30.0
    assert out[2] == pytest.approx(30.0)
    # barra 3 (close_time=3599999): último evento <= 3599999 ainda é 2600000 -> 30.0
    assert out[3] == pytest.approx(30.0)


def test_asof_align_backward_nunca_usa_evento_futuro() -> None:
    """Prova direta de causalidade: um evento POSTERIOR ao close_time de
    TODAS as barras nunca pode aparecer no valor alinhado de nenhuma
    delas."""
    bars = _bars([0, 900_000, 1_800_000])  # close_times: 899_999 / 1_799_999 / 2_699_999
    aux = pl.DataFrame({"ts": [3_000_000], "value": [999.0]})  # posterior a TODOS os close_time
    out = _sources.asof_align_backward(bars, aux, "ts", "value")
    assert out.null_count() == 3  # nenhuma barra tem evento <= seu close_time


def test_asof_align_backward_aux_vazio_retorna_null() -> None:
    bars = _bars([0, 900_000])
    aux = pl.DataFrame(schema={"ts": pl.Int64, "value": pl.Float64})
    out = _sources.asof_align_backward(bars, aux, "ts", "value")
    assert out.null_count() == 2


def test_asof_align_backward_preserva_ordem_de_bars_15m() -> None:
    # bars fora de ordem de close_time na entrada -- join_asof reordena
    # internamente por close_time, mas o retorno tem que bater com a ORDEM
    # ORIGINAL de bars_15m (open_time), não a ordem interna do join.
    bars = pl.DataFrame(
        {
            "open_time": [1_800_000, 0, 900_000],
            "close_time": [2_699_999, 899_999, 1_799_999],
        }
    )
    aux = pl.DataFrame({"ts": [100_000, 1_000_000], "value": [1.0, 2.0]})
    out = _sources.asof_align_backward(bars, aux, "ts", "value")
    # linha 0 = open_time 1_800_000 (close=2_699_999) -> último evento 1_000_000
    assert out[0] == pytest.approx(2.0)
    # linha 1 = open_time 0 (close=899_999) -> evento 100_000
    assert out[1] == pytest.approx(1.0)
    # linha 2 = open_time 900_000 (close=1_799_999) -> 1_000_000 já é <= close_time
    assert out[2] == pytest.approx(2.0)


# ============================================================================
# load_oi_series_deduped — dedup determinístico do achado do Sprint 3/4
# ============================================================================


@pytest.fixture()
def metrics_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    fake_capacity = tmp_path / "capacity"
    monkeypatch.setattr(features_paths, "CAPACITY_DIR", fake_capacity)
    d = fake_capacity / "metrics" / "BTCUSDT"
    d.mkdir(parents=True)
    return d


def test_load_oi_series_deduped_resolve_conflito_pelo_arquivo_nativo(metrics_dir: Path) -> None:
    """Reproduz exatamente o padrão medido em produção (2026-06-12/21): o
    arquivo do dia anterior "vaza" um ponto com o mesmo create_time do
    primeiro ponto do dia seguinte, com um valor DIFERENTE. A resolução
    determinística deve manter o valor do arquivo cujo nome bate com a
    data do create_time (aqui, `2024-01-02.parquet`, valor 111.0)."""
    df_day1 = pl.DataFrame(
        {
            "create_time": ["2024-01-01 23:55:00", "2024-01-02 00:00:00"],
            "sum_open_interest": [100.0, 999.0],  # 999.0 é o valor "vazado", errado
        }
    )
    df_day2 = pl.DataFrame(
        {
            "create_time": ["2024-01-02 00:00:00", "2024-01-02 00:05:00"],
            "sum_open_interest": [111.0, 112.0],  # 111.0 é o valor "nativo", correto
        }
    )
    df_day1.write_parquet(metrics_dir / "2024-01-01.parquet")
    df_day2.write_parquet(metrics_dir / "2024-01-02.parquet")

    out = _sources.load_oi_series_deduped("BTCUSDT", "2024-01-01", "2024-01-02")

    assert out.height == 3  # 3 create_time distintos, não 4
    row = out.filter(pl.col("create_time") == "2024-01-02 00:00:00")
    assert row.height == 1
    assert row["sum_open_interest"][0] == pytest.approx(111.0)  # o nativo venceu, não o vazado


def test_load_oi_series_deduped_sem_duplicata_preserva_tudo(metrics_dir: Path) -> None:
    df = pl.DataFrame(
        {
            "create_time": ["2024-01-01 00:00:00", "2024-01-01 00:05:00"],
            "sum_open_interest": [100.0, 101.0],
        }
    )
    df.write_parquet(metrics_dir / "2024-01-01.parquet")
    out = _sources.load_oi_series_deduped("BTCUSDT", "2024-01-01", "2024-01-01")
    assert out.height == 2


def test_load_oi_series_deduped_oi_nao_positivo_vira_null(metrics_dir: Path) -> None:
    """Achado adicional do Sprint 4 (fora dos 2 dias de duplicata
    conhecidos): pontos isolados de `sum_open_interest == 0.0` medidos em
    produção real (ex. BTCUSDT 2024-08-12 09:25:00). Tratados como null
    (leitura inválida), não como "OI caiu a zero" — ver docstring do
    código de produção."""
    df = pl.DataFrame(
        {
            "create_time": ["2024-01-01 00:00:00", "2024-01-01 00:05:00", "2024-01-01 00:10:00"],
            "sum_open_interest": [100.0, 0.0, 101.0],
        }
    )
    df.write_parquet(metrics_dir / "2024-01-01.parquet")
    out = _sources.load_oi_series_deduped("BTCUSDT", "2024-01-01", "2024-01-01")
    assert out.height == 3
    row = out.filter(pl.col("create_time") == "2024-01-01 00:05:00")
    assert row["sum_open_interest"][0] is None


def test_load_oi_series_deduped_sem_arquivos_retorna_vazio(metrics_dir: Path) -> None:
    out = _sources.load_oi_series_deduped("BTCUSDT", "2030-01-01", "2030-01-02")
    assert out.is_empty()
