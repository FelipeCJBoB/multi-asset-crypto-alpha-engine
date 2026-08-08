"""Teste de paridade de `resample.py` (§1.3 check 16) contra um recorte real
de `klines_1m` — 3 dias fixos já confirmados presentes no backfill.

Se existir um kline NATIVO de 30m em algum lugar do disco, compara dentro de
`resample_cross_source_parity_tolerance` (1e-8, `config/constants.yaml`). Se
não existir — o caso real deste repo, medido em 2026-08-08 (ver
`known_gaps` em `constants.yaml`) — o teste documenta isso via `pytest.skip`
em vez de fingir uma comparação que não pode ser feita, e continua
verificando tudo que É possível verificar sem um nativo: causalidade,
coerência OHLC e conservação de volume."""

from __future__ import annotations

import polars as pl
import pytest

from src.data import checks, lake, resample
from src.data._paths import CAPACITY_DIR
from src.data._util import cast_price_columns

_FIXTURE_START = "2024-01-15"
_FIXTURE_END = "2024-01-17"  # 3 dias


def _skip_if_missing() -> None:
    path = CAPACITY_DIR / "klines_1m" / "BTCUSDT" / f"{_FIXTURE_START}.parquet"
    if not path.exists():
        pytest.skip(f"fixture ausente no backfill local: {path}")


@pytest.fixture()
def df_1m() -> pl.DataFrame:
    _skip_if_missing()
    return lake.query_bars(
        "BTCUSDT", "1m", _FIXTURE_START, _FIXTURE_END, source="klines_1m", cast_prices=True
    )


def test_resample_30m_causalidade_em_dado_real(df_1m: pl.DataFrame) -> None:
    df_30m = resample.resample_klines(df_1m, "30m")
    assert df_30m.height == 3 * 48
    resample.assert_no_lookahead(df_1m, df_30m, "30m")  # não deve levantar


def test_resample_30m_coerencia_ohlc_em_dado_real(df_1m: pl.DataFrame) -> None:
    df_30m = resample.resample_klines(df_1m, "30m")
    result = checks.check_ohlc_coherence(df_30m)
    assert result.violation_count == 0


def test_resample_30m_conserva_volume_total(df_1m: pl.DataFrame) -> None:
    df_30m = resample.resample_klines(df_1m, "30m")
    total_1m = df_1m["volume"].sum()
    total_30m = df_30m["volume"].sum()
    assert total_30m == pytest.approx(total_1m, rel=1e-9)


@pytest.mark.parametrize("timeframe", ["5m", "15m", "1h", "2h", "1d"])
def test_resample_multiplos_timeframes_sem_lookahead(df_1m: pl.DataFrame, timeframe: str) -> None:
    df_out = resample.resample_klines(df_1m, timeframe)
    resample.assert_no_lookahead(df_1m, df_out, timeframe)


def test_check16_cross_source_parity_ou_pending_documentado(df_1m: pl.DataFrame) -> None:
    """Implementação literal do check 16 do §1.3. Roda a comparação real
    SE (e só se) existir um klines_30m nativo no disco; caso contrário,
    documenta a pendência via skip em vez de inventar o comparador — a
    instrução explícita do Sprint 2 para este teste."""
    df_30m = resample.resample_klines(df_1m, "30m")
    native_dir = resample.find_native_klines("BTCUSDT", "30m")
    if native_dir is None:
        pytest.skip(
            "check 16 (§1.3) PENDING: nenhum klines_30m nativo encontrado em data/capacity/ "
            "nem data/raw/ (medido em 2026-08-08 — ver known_gaps em config/constants.yaml). "
            "resample.compare_resample_to_native já está implementado e testado com fixtures "
            "sintéticas em tests/unit/test_data_resample.py; falta só o dado nativo real."
        )
    result = resample.compare_resample_to_native(df_30m, native_dir)
    assert result.compared
    assert result.passed, (
        f"desvio máximo {result.max_abs_deviation} >= tolerância {result.tolerance}"
    )


def test_ensure_float_ohlc_idempotente(df_1m: pl.DataFrame) -> None:
    # cast_price_columns já foi aplicado pela fixture (cast_prices=True) —
    # reaplicar não deve quebrar nem mudar o schema.
    twice = cast_price_columns(df_1m, ("open", "high", "low", "close"))
    assert twice.schema == df_1m.schema
