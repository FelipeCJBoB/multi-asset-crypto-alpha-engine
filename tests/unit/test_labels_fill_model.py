"""Testes de `src/labels/fill_model.py` — modelo de preenchimento
simplificado (Sprint 6, `simulate_fill_arrays`/`simulate_fill`). Cobre a
lógica pura primeiro (arrays sintéticos, sem IO) e depois confirma contra
um recorte real de `mark_1m` que o schema é klines-like (`open`/`high`/
`low`/`close`), a premissa que o módulo documenta ter verificado — não
presumido — antes de decidir usar `high`/`low` em vez de comparar só
contra um valor único por minuto."""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from src.data import lake
from src.data._paths import CAPACITY_DIR
from src.labels import fill_model


def _skip_if_missing(day: str) -> None:
    path = CAPACITY_DIR / "mark_price_klines_1m" / "BTCUSDT" / f"{day}.parquet"
    if not path.exists():
        pytest.skip(f"fixture ausente no backfill local: {path}")


# ============================================================================
# simulate_fill_arrays — núcleo numérico
# ============================================================================


def test_fill_long_toca_limite_primeiro_candle() -> None:
    open_time = np.array([0, 60_000, 120_000], dtype=np.int64)
    low = np.array([100.5, 99.5, 98.0], dtype=np.float64)
    high = np.array([101.0, 100.5, 99.0], dtype=np.float64)
    result = fill_model.simulate_fill_arrays(
        open_time, low, high, t_post_ms=0, horizon_ms=180_000, limit_price=100.0, side=1
    )
    assert result.t_entry_ms == 60_000
    assert result.fill_price == 100.0


def test_fill_short_toca_limite_por_cima() -> None:
    open_time = np.array([0, 60_000, 120_000], dtype=np.int64)
    low = np.array([98.0, 99.0, 99.5], dtype=np.float64)
    high = np.array([99.5, 100.5, 101.0], dtype=np.float64)
    result = fill_model.simulate_fill_arrays(
        open_time, low, high, t_post_ms=0, horizon_ms=180_000, limit_price=100.0, side=-1
    )
    assert result.t_entry_ms == 60_000
    assert result.fill_price == 100.0


def test_fill_nunca_toca_e_nofill() -> None:
    open_time = np.array([0, 60_000, 120_000], dtype=np.int64)
    low = np.array([100.5, 100.6, 100.7], dtype=np.float64)
    high = np.array([101.0, 101.1, 101.2], dtype=np.float64)
    result = fill_model.simulate_fill_arrays(
        open_time, low, high, t_post_ms=0, horizon_ms=180_000, limit_price=100.0, side=1
    )
    assert result.t_entry_ms is None
    assert result.fill_price is None


def test_fill_pega_o_primeiro_toque_nao_o_ultimo() -> None:
    """Vários candles tocam o limite dentro da janela — tem que devolver o
    PRIMEIRO em ordem cronológica, não qualquer um."""
    open_time = np.array([0, 60_000, 120_000, 180_000], dtype=np.int64)
    low = np.array([100.5, 99.9, 99.8, 99.7], dtype=np.float64)
    high = np.array([101.0, 100.5, 100.4, 100.3], dtype=np.float64)
    result = fill_model.simulate_fill_arrays(
        open_time, low, high, t_post_ms=0, horizon_ms=240_000, limit_price=100.0, side=1
    )
    assert result.t_entry_ms == 60_000  # não 120_000 nem 180_000


def test_fill_janela_estritamente_apos_t_post() -> None:
    """Candle EXATAMENTE em t_post não conta — a janela é `(t_post,
    horizon_ms]`, estritamente posterior a `t_post` (a ordem foi postada
    NAQUELE instante; o toque relevante é depois)."""
    open_time = np.array([0, 60_000], dtype=np.int64)
    low = np.array([50.0, 100.5], dtype=np.float64)  # candle em t_post=0 tocaria, mas é excluído
    high = np.array([100.5, 101.0], dtype=np.float64)
    result = fill_model.simulate_fill_arrays(
        open_time, low, high, t_post_ms=0, horizon_ms=120_000, limit_price=100.0, side=1
    )
    assert result.t_entry_ms is None


def test_fill_janela_inclui_horizon_ms() -> None:
    open_time = np.array([60_000], dtype=np.int64)
    low = np.array([99.0], dtype=np.float64)
    high = np.array([100.5], dtype=np.float64)
    result = fill_model.simulate_fill_arrays(
        open_time, low, high, t_post_ms=0, horizon_ms=60_000, limit_price=100.0, side=1
    )
    assert result.t_entry_ms == 60_000


def test_fill_side_invalido_levanta_erro() -> None:
    open_time = np.array([0], dtype=np.int64)
    low = np.array([100.0], dtype=np.float64)
    high = np.array([100.0], dtype=np.float64)
    with pytest.raises(ValueError):
        fill_model.simulate_fill_arrays(
            open_time, low, high, t_post_ms=0, horizon_ms=60_000, limit_price=100.0, side=0
        )


def test_fill_horizon_antes_de_t_post_levanta_erro() -> None:
    open_time = np.array([0], dtype=np.int64)
    low = np.array([100.0], dtype=np.float64)
    high = np.array([100.0], dtype=np.float64)
    with pytest.raises(ValueError):
        fill_model.simulate_fill_arrays(
            open_time, low, high, t_post_ms=60_000, horizon_ms=0, limit_price=100.0, side=1
        )


# ============================================================================
# simulate_fill — wrapper polars, deve concordar com a versão numpy
# ============================================================================


def test_wrapper_polars_concorda_com_versao_numpy() -> None:
    mark = pl.DataFrame(
        {
            "open_time": [0, 60_000, 120_000],
            "low": [100.5, 99.5, 98.0],
            "high": [101.0, 100.5, 99.0],
        }
    )
    open_time = mark["open_time"].to_numpy().astype(np.int64)
    low = mark["low"].to_numpy()
    high = mark["high"].to_numpy()

    via_arrays = fill_model.simulate_fill_arrays(
        open_time, low, high, t_post_ms=0, horizon_ms=180_000, limit_price=100.0, side=1
    )
    via_wrapper = fill_model.simulate_fill(
        mark, t_post_ms=0, horizon_ms=180_000, limit_price=100.0, side=1
    )
    assert via_arrays == via_wrapper


def test_wrapper_polars_janela_vazia_e_nofill() -> None:
    mark = pl.DataFrame({"open_time": [0], "low": [100.0], "high": [100.0]})
    result = fill_model.simulate_fill(
        mark, t_post_ms=1_000_000, horizon_ms=2_000_000, limit_price=100.0, side=1
    )
    assert result.t_entry_ms is None
    assert result.fill_price is None


# ============================================================================
# Confirmação de schema real — a premissa que o módulo documenta ter
# verificado (mark_1m é klines-like, não um único valor por minuto).
# ============================================================================

_SCHEMA_FIXTURE_DAY = "2024-01-15"


def test_mark_1m_e_klines_like_nao_valor_unico_por_minuto() -> None:
    _skip_if_missing(_SCHEMA_FIXTURE_DAY)
    df = lake.query_bars(
        "BTCUSDT", "1m", _SCHEMA_FIXTURE_DAY, _SCHEMA_FIXTURE_DAY, source="mark_price_klines_1m"
    )
    assert not df.is_empty()
    for col in ("open_time", "open", "high", "low", "close"):
        assert col in df.columns
    # high >= low em toda linha — só faz sentido se for de fato um candle
    # OHLC, não um valor escalar repetido em 4 colunas por acidente.
    assert bool((df["high"] >= df["low"]).all())
    # pelo menos uma barra com high > low de verdade (variação real intra-minuto)
    assert bool((df["high"] > df["low"]).any())
