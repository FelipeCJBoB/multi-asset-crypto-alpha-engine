"""Testes de `src/features/_sources.py`: asof-join causal (nunca usa
evento futuro), a resolução determinística do duplicado real de
`create_time` medido em `metrics` (Sprint 3/4 — ver docstring de
`load_oi_series_deduped`), e o dispatcher de `bar_source` de `load_bars`
(R2/R3 wireados 2026-08-18, extensão do M4) — tudo com fixtures
sintéticas/monkeypatch em `tmp_path` (não precisa do dado real do
backfill pra provar a lógica)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from src.data import lake
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


# ============================================================================
# load_metrics_series_deduped / load_futures_positioning_aligned — Lote C
# da liberação de features (H5, 2026-08-24). Generalização de
# load_oi_series_deduped pra outras colunas de schemas.METRICS -- reusa a
# MESMA resolução de create_time duplicado (_load_and_dedupe_metrics_
# rows), prova aqui é que a generalização não quebrou nem o dedup nem o
# alinhamento causal pras colunas NOVAS.
# ============================================================================


def test_load_metrics_series_deduped_le_multiplas_colunas(metrics_dir: Path) -> None:
    df = pl.DataFrame(
        {
            "create_time": ["2024-01-01 00:00:00", "2024-01-01 00:05:00"],
            "sum_open_interest": [100.0, 101.0],
            "sum_open_interest_value": [5_000_000.0, 5_010_000.0],
            "sum_toptrader_long_short_ratio": [1.2, 1.3],
            "count_long_short_ratio": [0.9, 0.95],
            "sum_taker_long_short_vol_ratio": [1.1, 1.05],
        }
    )
    df.write_parquet(metrics_dir / "2024-01-01.parquet")

    out = _sources.load_metrics_series_deduped(
        "BTCUSDT",
        "2024-01-01",
        "2024-01-01",
        value_cols=(
            "sum_open_interest_value",
            "sum_toptrader_long_short_ratio",
            "count_long_short_ratio",
            "sum_taker_long_short_vol_ratio",
        ),
    )
    assert out.height == 2
    assert out["sum_open_interest_value"].to_list() == [5_000_000.0, 5_010_000.0]
    assert out["sum_toptrader_long_short_ratio"].to_list() == pytest.approx([1.2, 1.3])
    assert "_ts_ms" in out.columns


def test_load_metrics_series_deduped_resolve_conflito_pelo_arquivo_nativo(
    metrics_dir: Path,
) -> None:
    """Mesma prova de `test_load_oi_series_deduped_resolve_conflito_pelo_
    arquivo_nativo`, mas exercitando a generalização (`value_cols`
    diferente de `sum_open_interest`) -- confirma que
    `_load_and_dedupe_metrics_rows` continua resolvendo o duplicado
    corretamente pra colunas que `load_oi_series_deduped` nunca lê."""
    df_day1 = pl.DataFrame(
        {
            "create_time": ["2024-01-01 23:55:00", "2024-01-02 00:00:00"],
            "sum_open_interest_value": [100.0, 999.0],
        }
    )
    df_day2 = pl.DataFrame(
        {
            "create_time": ["2024-01-02 00:00:00", "2024-01-02 00:05:00"],
            "sum_open_interest_value": [111.0, 112.0],
        }
    )
    df_day1.write_parquet(metrics_dir / "2024-01-01.parquet")
    df_day2.write_parquet(metrics_dir / "2024-01-02.parquet")

    out = _sources.load_metrics_series_deduped(
        "BTCUSDT", "2024-01-01", "2024-01-02", value_cols=("sum_open_interest_value",)
    )
    assert out.height == 3
    row = out.filter(pl.col("create_time") == "2024-01-02 00:00:00")
    assert row["sum_open_interest_value"][0] == pytest.approx(111.0)


def test_load_metrics_series_deduped_sem_arquivos_retorna_vazio_com_schema(
    metrics_dir: Path,
) -> None:
    out = _sources.load_metrics_series_deduped(
        "BTCUSDT", "2030-01-01", "2030-01-02", value_cols=("sum_open_interest_value",)
    )
    assert out.is_empty()
    assert "sum_open_interest_value" in out.columns
    assert "_ts_ms" in out.columns


def test_load_futures_positioning_aligned_alinha_as_4_colunas(metrics_dir: Path) -> None:
    df = pl.DataFrame(
        {
            "create_time": ["2024-01-01 00:00:00"],
            "sum_open_interest_value": [5_000_000.0],
            "sum_toptrader_long_short_ratio": [1.25],
            "count_long_short_ratio": [0.9],
            "sum_taker_long_short_vol_ratio": [1.1],
        }
    )
    df.write_parquet(metrics_dir / "2024-01-01.parquet")

    # `_bars()` usa timestamps relativos à época Unix (1970) -- não bate
    # com o `create_time` real ("2024-01-01") do fixture acima. Aqui as
    # barras precisam de close_time REAL de 2024-01-01 pro asof-join
    # achar o evento (mesma base de tempo, não coincidência de nome).
    day_start_ms = int(
        datetime(2024, 1, 1, tzinfo=UTC).timestamp() * 1000
    )  # início real do dia, epoch ms
    step = 900_000  # 15m em ms
    bars = pl.DataFrame(
        {
            "open_time": [day_start_ms, day_start_ms + step],
            "close_time": [day_start_ms + step - 1, day_start_ms + 2 * step - 1],
        }
    )
    out = _sources.load_futures_positioning_aligned(bars, "BTCUSDT", "2024-01-01", "2024-01-01")

    assert set(out.keys()) == {
        "oi_notional",
        "toptrader_ls_ratio",
        "global_ls_ratio",
        "taker_ls_vol_ratio",
    }
    assert out["oi_notional"][0] == pytest.approx(5_000_000.0)
    assert out["toptrader_ls_ratio"][0] == pytest.approx(1.25)
    assert out["global_ls_ratio"][0] == pytest.approx(0.9)
    assert out["taker_ls_vol_ratio"][0] == pytest.approx(1.1)


def test_load_futures_positioning_aligned_sem_arquivos_retorna_null(metrics_dir: Path) -> None:
    bars = _bars([0, 900_000])
    out = _sources.load_futures_positioning_aligned(bars, "BTCUSDT", "2030-01-01", "2030-01-02")
    for series in out.values():
        assert series.null_count() == 2


# ============================================================================
# load_bars — dispatcher de bar_source (R1/R2/R3 wireados 2026-08-18)
# ============================================================================


@pytest.mark.parametrize(
    ("bar_source", "expected_resolution_id"),
    [("dollar_r1", "R1"), ("dollar_r2", "R2"), ("dollar_r3", "R3")],
)
def test_load_bars_dollar_resolutions_chamam_query_dollar_bars_com_resolution_id_certo(
    monkeypatch: pytest.MonkeyPatch, bar_source: str, expected_resolution_id: str
) -> None:
    calls: list[dict[str, Any]] = []

    def _fake_query_dollar_bars(
        symbol: str, start: object, end: object, *, resolution_id: str = "R1", **kwargs: object
    ) -> pl.DataFrame:
        calls.append({"symbol": symbol, "start": start, "end": end, "resolution_id": resolution_id})
        return pl.DataFrame(schema={"open_time": pl.Int64, "close_time": pl.Int64})

    monkeypatch.setattr(lake, "query_dollar_bars", _fake_query_dollar_bars)
    _sources.load_bars("BTCUSDT", "2022-01-01", "2022-02-01", bar_source=bar_source)

    assert len(calls) == 1
    assert calls[0]["resolution_id"] == expected_resolution_id
    assert calls[0]["symbol"] == "BTCUSDT"


def test_load_bars_time_15m_nao_chama_query_dollar_bars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regressão: wireup de R2/R3 não pode mudar o caminho `time_15m`
    (default, bit-exato pra todo caller existente que não passa
    `bar_source`) -- confirma que `query_dollar_bars` nunca é chamada
    nesse branch."""
    called = False

    def _fail_if_called(*args: object, **kwargs: object) -> pl.DataFrame:
        nonlocal called
        called = True
        raise AssertionError("query_dollar_bars não deveria ser chamada sob bar_source=time_15m")

    monkeypatch.setattr(lake, "query_dollar_bars", _fail_if_called)
    monkeypatch.setattr(
        _sources, "load_bars_15m", lambda symbol, start, end: pl.DataFrame({"open_time": [0]})
    )
    _sources.load_bars("BTCUSDT", "2022-01-01", "2022-02-01", bar_source="time_15m")
    assert called is False


def test_load_bars_bar_source_desconhecido_levanta_value_error_lista_4_opcoes() -> None:
    with pytest.raises(ValueError, match=r"dollar_r1.*dollar_r2.*dollar_r3"):
        _sources.load_bars("BTCUSDT", "2022-01-01", "2022-02-01", bar_source="dollar_r4")
