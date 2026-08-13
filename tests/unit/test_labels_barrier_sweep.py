"""Testes de `src/labels/barrier_sweep.py` — vetorização via
`sliding_window_view` (§18.7.1, Faixa 2 E1).

Duas camadas: (1) fixtures sintéticas, reproduzindo byte-a-byte os mesmos
cenários já testados em `test_labels_triple_barrier.py` (TP/SL/TIME/
desempate) contra o resultado do motor ESCALAR (`triple_barrier.
build_labels`) — a garantia central deste arquivo: vetorizar não pode
mudar o resultado; (2) um recorte REAL (1 ano, 2024), comparando a
distribuição TP/SL/TIME da versão vetorizada contra `build_labels` sobre o
mesmo intervalo — sanidade "a grade reproduz o motor de produção" em
escala menor que os 6,5 anos completos (caro demais para rodar em todo
`pytest`)."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import polars as pl
import pytest

from src.data._paths import CAPACITY_DIR
from src.labels import barrier_sweep as bs
from src.labels import triple_barrier as tb

_BAR_MS = 900_000
_BASE_MS = int(datetime(2026, 8, 8, 0, 0, tzinfo=UTC).timestamp() * 1000)
_CLOSES = [100.0, 100.2, 99.9]
_CFG = tb.LabelConfig(
    tp_atr_mult=2.0,
    sl_atr_mult=1.5,
    time_stop_bars=4,
    fill_timeout_bars=1,
    atr_window=3,
    maker_fee=0.0002,
    taker_fee=0.0005,
    estimator_id="atr_wilder_w3",
)
_EMPTY_FUNDING = pl.DataFrame(schema={"calc_time": pl.Int64, "last_funding_rate": pl.Float64})

_Row = tuple[int, float, float, float, float]


def _synthetic_bars() -> pl.DataFrame:
    open_time = [_BASE_MS + i * _BAR_MS for i in range(len(_CLOSES))]
    close_time = [t + _BAR_MS - 1 for t in open_time]
    high = [c + 0.2 for c in _CLOSES]
    low = [c - 0.2 for c in _CLOSES]
    return pl.DataFrame(
        {
            "open_time": open_time,
            "close_time": close_time,
            "close": _CLOSES,
            "high": high,
            "low": low,
        }
    )


def _t0() -> int:
    return _synthetic_bars()["close_time"][-1]


def _mark(rows: list[_Row]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "open_time": [r[0] for r in rows],
            "open": [r[1] for r in rows],
            "high": [r[2] for r in rows],
            "low": [r[3] for r in rows],
            "close": [r[4] for r in rows],
        }
    )


def _with_horizon_coverage(rows: list[_Row]) -> list[_Row]:
    horizon = _t0() + _CFG.time_stop_bars * _BAR_MS
    last_px = rows[-1][4]
    return [*rows, (horizon, last_px, last_px, last_px, last_px)]


def _scalar_and_vectorized(
    mark: pl.DataFrame, *, side: int, funding: pl.DataFrame = _EMPTY_FUNDING
) -> tuple[dict[str, object], bs.ResolvedBarriers]:
    """Roda o motor escalar (fonte da verdade) e o vetorizado sobre o
    MESMO cenário, devolve `(linha_escalar, resultado_vetorizado)` prontos
    pra comparar campo a campo."""
    scalar_out = tb.build_labels(_synthetic_bars(), mark, funding, side=side, config=_CFG)
    filled = scalar_out.filter(pl.col("barrier_hit").cast(pl.Utf8) != "NOFILL")
    assert filled.height == 1, "cenário de teste tem que produzir exatamente 1 trade preenchido"
    vec_out = bs.resolve_barriers_vectorized(
        filled,
        mark,
        funding,
        side=side,
        tp_atr_mult=_CFG.tp_atr_mult,
        sl_atr_mult=_CFG.sl_atr_mult,
        time_stop_bars=_CFG.time_stop_bars,
        maker_fee=_CFG.maker_fee,
        taker_fee=_CFG.taker_fee,
    )
    return filled.row(0, named=True), vec_out


def _assert_reproduces(scalar_row: dict[str, object], vec: bs.ResolvedBarriers) -> None:
    assert vec.barrier_hit[0] == scalar_row["barrier_hit"]
    assert vec.exit_price[0] == pytest.approx(scalar_row["exit_price"], rel=1e-9)
    assert vec.ret_gross[0] == pytest.approx(scalar_row["ret_gross"], rel=1e-9)
    assert vec.ret_net[0] == pytest.approx(scalar_row["ret_net"], rel=1e-9)
    assert vec.cost_entry_bps[0] == pytest.approx(scalar_row["cost_entry_bps"], rel=1e-9)
    assert vec.cost_exit_bps[0] == pytest.approx(scalar_row["cost_exit_bps"], rel=1e-9)
    assert vec.funding_bps[0] == pytest.approx(scalar_row["funding_bps"], rel=1e-9)
    assert int(vec.n_bars_held[0]) == scalar_row["n_bars_held"]
    scalar_t1_ms = scalar_row["t1"].timestamp() * 1000  # type: ignore[union-attr]
    assert int(vec.t1_ms[0]) == pytest.approx(scalar_t1_ms, abs=1.0)


def test_reproduz_build_labels_tp_long() -> None:
    t0 = _t0()
    mark = _mark(
        _with_horizon_coverage(
            [
                (t0 + 1 * 60_000, 99.9, 100.0, 99.8, 99.9),
                (t0 + 5 * 60_000, 145.0, 150.0, 140.0, 148.0),
            ]
        )
    )
    scalar_row, vec = _scalar_and_vectorized(mark, side=1)
    assert scalar_row["barrier_hit"] == "TP"
    _assert_reproduces(scalar_row, vec)


def test_reproduz_build_labels_sl_long() -> None:
    t0 = _t0()
    mark = _mark(
        _with_horizon_coverage(
            [
                (t0 + 1 * 60_000, 99.9, 100.0, 99.8, 99.9),
                (t0 + 5 * 60_000, 60.0, 65.0, 50.0, 55.0),
            ]
        )
    )
    scalar_row, vec = _scalar_and_vectorized(mark, side=1)
    assert scalar_row["barrier_hit"] == "SL"
    _assert_reproduces(scalar_row, vec)


def test_reproduz_build_labels_tp_short() -> None:
    t0 = _t0()
    mark = _mark(
        _with_horizon_coverage(
            [
                (t0 + 1 * 60_000, 99.9, 100.0, 99.8, 99.9),
                (t0 + 5 * 60_000, 55.0, 60.0, 50.0, 52.0),
            ]
        )
    )
    scalar_row, vec = _scalar_and_vectorized(mark, side=-1)
    assert scalar_row["barrier_hit"] == "TP"
    _assert_reproduces(scalar_row, vec)


def test_reproduz_build_labels_time() -> None:
    t0 = _t0()
    rows: list[_Row] = [
        (t0 + 1 * 60_000, 99.9, 100.0, 99.8, 99.9),
        (t0 + 5 * 60_000, 100.3, 100.5, 100.2, 100.4),
        (t0 + 9 * 60_000, 100.1, 100.2, 99.8, 99.9),
    ]
    mark = _mark(_with_horizon_coverage(rows))
    scalar_row, vec = _scalar_and_vectorized(mark, side=1)
    assert scalar_row["barrier_hit"] == "TIME"
    _assert_reproduces(scalar_row, vec)


def test_reproduz_build_labels_tie_break_mesmo_candle() -> None:
    """TP e SL tocados no MESMO candle de 1m -- desempate por proximidade
    ao `open` (item 5 da docstring de `triple_barrier.py`). `tp_price`/
    `sl_price` da fixture ficam em ~100,77/~99,25 (ver debug prévio) — um
    candle com `low` abaixo de `sl_price` E `high` acima de `tp_price`
    força os dois toques no mesmo índice."""
    t0 = _t0()
    mark = _mark(
        _with_horizon_coverage(
            [
                (t0 + 1 * 60_000, 99.9, 100.0, 99.8, 99.9),
                (t0 + 5 * 60_000, 99.9, 101.0, 99.0, 100.0),
            ]
        )
    )
    scalar_row, vec = _scalar_and_vectorized(mark, side=1)
    assert scalar_row["barrier_hit"] in ("TP", "SL")
    assert bool(vec.tie_break_used[0])
    _assert_reproduces(scalar_row, vec)


def test_vetorizado_processa_multiplos_trades_de_uma_vez() -> None:
    """`resolve_barriers_vectorized` roda sobre um DataFrame de N trades —
    monta 3 trades sintéticos independentes (índices diferentes de
    `t_entry`/`fill_px`/`atr_at_t0`, um TP/um SL/um TIME) num único
    `filled` e confere que os 3 resultados batem com 3 chamadas escalares
    separadas -- pega bug de indexação entre linhas (`idx_range`,
    `np.where(tie_mask, tp_idx, 0)`) que um teste de n=1 não pegaria."""
    rows: list[dict[str, object]] = []
    for i, (fill_px, atr_pct, exit_hint) in enumerate(
        [(100.0, 0.004, "tp"), (100.0, 0.004, "sl"), (100.0, 0.004, "time")]
    ):
        t0_i = _BASE_MS + i * 10 * _BAR_MS
        rows.append(
            {
                "t0": t0_i,
                "t_entry": t0_i + 60_000,
                "entry_price_fill": fill_px,
                "atr_at_t0": atr_pct,
                "_exit_hint": exit_hint,
            }
        )
    filled = pl.DataFrame(rows).with_columns(
        pl.col("t0").cast(pl.Datetime("ms")).dt.replace_time_zone("UTC"),
        pl.col("t_entry").cast(pl.Datetime("ms")).dt.replace_time_zone("UTC"),
    )

    mark_rows: list[_Row] = []
    horizon_bars = _CFG.time_stop_bars * 15 + 5
    for i, exit_hint in enumerate(("tp", "sl", "time")):
        t0_i = _BASE_MS + i * 10 * _BAR_MS
        base_open = t0_i + 60_000
        if exit_hint == "tp":
            mark_rows.append((base_open, 100.0, 100.0, 99.9, 100.0))
            mark_rows.append((base_open + 60_000, 145.0, 150.0, 140.0, 148.0))
        elif exit_hint == "sl":
            mark_rows.append((base_open, 100.0, 100.0, 99.9, 100.0))
            mark_rows.append((base_open + 60_000, 60.0, 65.0, 50.0, 55.0))
        else:
            mark_rows.append((base_open, 100.0, 100.0, 99.9, 100.0))
        for m in range(2, horizon_bars):
            mark_rows.append((base_open + m * 60_000, 100.0, 100.1, 99.9, 100.0))
    mark = _mark(mark_rows).sort("open_time")

    vec = bs.resolve_barriers_vectorized(
        filled,
        mark,
        _EMPTY_FUNDING,
        side=1,
        tp_atr_mult=_CFG.tp_atr_mult,
        sl_atr_mult=_CFG.sl_atr_mult,
        time_stop_bars=_CFG.time_stop_bars,
        maker_fee=_CFG.maker_fee,
        taker_fee=_CFG.taker_fee,
    )
    assert vec.barrier_hit == ["TP", "SL", "TIME"]


# ============================================================================
# tf — AG-005 (audit/architecture_gaps_log.yaml)
# ============================================================================


def test_resolve_barriers_vectorized_tf_default_bate_bit_exato_com_explicito() -> None:
    """AG-005 — `tf` omitido (default `"15m"`) tem que produzir EXATAMENTE
    o mesmo resultado que `tf="15m"` explícito — preserva todo caller
    existente (`src.analysis.faixa2_caminho_b`, testes acima) bit-exato."""
    t0 = _t0()
    mark = _mark(
        _with_horizon_coverage(
            [
                (t0 + 1 * 60_000, 99.9, 100.0, 99.8, 99.9),
                (t0 + 5 * 60_000, 145.0, 150.0, 140.0, 148.0),
            ]
        )
    )
    scalar_out = tb.build_labels(_synthetic_bars(), mark, _EMPTY_FUNDING, side=1, config=_CFG)
    filled = scalar_out.filter(pl.col("barrier_hit").cast(pl.Utf8) != "NOFILL")
    out_default = bs.resolve_barriers_vectorized(
        filled,
        mark,
        _EMPTY_FUNDING,
        side=1,
        tp_atr_mult=_CFG.tp_atr_mult,
        sl_atr_mult=_CFG.sl_atr_mult,
        time_stop_bars=_CFG.time_stop_bars,
        maker_fee=_CFG.maker_fee,
        taker_fee=_CFG.taker_fee,
    )
    out_explicit = bs.resolve_barriers_vectorized(
        filled,
        mark,
        _EMPTY_FUNDING,
        side=1,
        tp_atr_mult=_CFG.tp_atr_mult,
        sl_atr_mult=_CFG.sl_atr_mult,
        time_stop_bars=_CFG.time_stop_bars,
        maker_fee=_CFG.maker_fee,
        taker_fee=_CFG.taker_fee,
        tf="15m",
    )
    assert out_default.barrier_hit == out_explicit.barrier_hit
    assert np.array_equal(out_default.t1_ms, out_explicit.t1_ms)
    assert np.array_equal(out_default.n_bars_held, out_explicit.n_bars_held)
    assert np.allclose(out_default.ret_net, out_explicit.ret_net)


def test_resolve_barriers_vectorized_tf_invalido_levanta_unsupportedtimeframeerror() -> None:
    """AG-005 — `step_ms(tf)` roda ANTES de qualquer acesso a `filled`/
    `mark_1m`/`funding` (primeira linha da função), então falha alto mesmo
    com DataFrames vazios/placeholder."""
    from src.data.resample import UnsupportedTimeframeError

    with pytest.raises(UnsupportedTimeframeError):
        bs.resolve_barriers_vectorized(
            pl.DataFrame(),
            pl.DataFrame(),
            pl.DataFrame(),
            side=1,
            tp_atr_mult=2.0,
            sl_atr_mult=1.5,
            time_stop_bars=4,
            maker_fee=0.0002,
            taker_fee=0.0005,
            tf="45m",
        )


def test_resolve_barriers_vectorized_horizon_escala_com_tf_diferente_de_15m() -> None:
    """AG-005 — `horizon_end`/`n_bars_held`/`t1_ms` têm que escalar com
    `tf`, não ficar presos ao antigo `_BAR_MS` fixo em 15m (a mesma
    constante existia aqui, CÓPIA independente da de `triple_barrier.py`).
    Cenário TIME (mark plano dentro de TP/SL, nunca toca), `filled`
    construído diretamente (não via `build_labels`) para isolar só a
    escala de `tf`. Diferença entre 15m/30m medida contra `step_ms`, não
    um fator "2x" presumido a priori (lição AG-004 — não travar proporção
    redonda sem medir)."""
    from src.data.resample import step_ms

    t0_i = _BASE_MS
    fill_px = 100.0
    atr_pct = 0.004  # tp=100.8/sl=99.4 (tp_atr_mult=2.0/sl_atr_mult=1.5) -- mark plano nunca toca
    filled = pl.DataFrame(
        {
            "t0": [t0_i],
            "t_entry": [t0_i + 60_000],
            "entry_price_fill": [fill_px],
            "atr_at_t0": [atr_pct],
        }
    ).with_columns(
        pl.col("t0").cast(pl.Datetime("ms")).dt.replace_time_zone("UTC"),
        pl.col("t_entry").cast(pl.Datetime("ms")).dt.replace_time_zone("UTC"),
    )

    def _flat_mark(tf: str, time_stop_bars: int) -> pl.DataFrame:
        horizon = t0_i + time_stop_bars * step_ms(tf)
        n_1m_bars = (horizon - (t0_i + 60_000)) // 60_000 + 1
        rows: list[_Row] = [
            (t0_i + 60_000 + m * 60_000, fill_px, fill_px + 0.05, fill_px - 0.05, fill_px)
            for m in range(int(n_1m_bars))
        ]
        return _mark(rows)

    time_stop_bars = 4
    vec_15m = bs.resolve_barriers_vectorized(
        filled,
        _flat_mark("15m", time_stop_bars),
        _EMPTY_FUNDING,
        side=1,
        tp_atr_mult=2.0,
        sl_atr_mult=1.5,
        time_stop_bars=time_stop_bars,
        maker_fee=0.0002,
        taker_fee=0.0005,
        tf="15m",
    )
    vec_30m = bs.resolve_barriers_vectorized(
        filled,
        _flat_mark("30m", time_stop_bars),
        _EMPTY_FUNDING,
        side=1,
        tp_atr_mult=2.0,
        sl_atr_mult=1.5,
        time_stop_bars=time_stop_bars,
        maker_fee=0.0002,
        taker_fee=0.0005,
        tf="30m",
    )
    assert vec_15m.barrier_hit == ["TIME"]
    assert vec_30m.barrier_hit == ["TIME"]
    assert int(vec_15m.n_bars_held[0]) == time_stop_bars
    assert int(vec_30m.n_bars_held[0]) == time_stop_bars

    expected_t1_15m = t0_i + time_stop_bars * step_ms("15m")
    expected_t1_30m = t0_i + time_stop_bars * step_ms("30m")
    assert int(vec_15m.t1_ms[0]) == expected_t1_15m
    assert int(vec_30m.t1_ms[0]) == expected_t1_30m
    measured_delta = int(vec_30m.t1_ms[0]) - int(vec_15m.t1_ms[0])
    expected_delta = time_stop_bars * (step_ms("30m") - step_ms("15m"))
    assert measured_delta == expected_delta


# ============================================================================
# Reprodução sobre dado real — 2024, um ano, side=1 (mais barato que os
# 6,5 anos completos do E1 de verdade).
# ============================================================================


@pytest.mark.integration
@pytest.mark.slow
def test_reproduz_distribuicao_real_2024_long() -> None:
    from datetime import timedelta

    from src.data import lake

    _skip_path = CAPACITY_DIR / "klines_1m" / "BTCUSDT" / "2024-06-01.parquet"
    if not _skip_path.exists():
        pytest.skip(f"fixture ausente no backfill local: {_skip_path}")

    cfg = tb.LabelConfig.from_constants()
    start, end = "2024-01-01", "2024-12-31"
    bars_15m = lake.query_bars("BTCUSDT", "15m", start, end, source="klines_1m", cast_prices=True)
    mark_end = (datetime.fromisoformat(end) + timedelta(days=1)).date().isoformat()
    mark_1m = lake.query_bars(
        "BTCUSDT", "1m", start, mark_end, source="mark_price_klines_1m", cast_prices=True
    )
    funding = lake.query_funding("BTCUSDT", start, mark_end)

    scalar_labels = tb.build_labels(
        bars_15m, mark_1m, funding, side=1, config=cfg, historical_filters_fallback=True
    )
    scalar_filled = scalar_labels.filter(pl.col("barrier_hit").cast(pl.Utf8) != "NOFILL")

    vec = bs.resolve_barriers_vectorized(
        scalar_filled,
        mark_1m,
        funding,
        side=1,
        tp_atr_mult=cfg.tp_atr_mult,
        sl_atr_mult=cfg.sl_atr_mult,
        time_stop_bars=cfg.time_stop_bars,
        maker_fee=cfg.maker_fee,
        taker_fee=cfg.taker_fee,
    )
    scalar_barrier = scalar_filled["barrier_hit"].cast(pl.Utf8).to_list()
    n_mismatch = sum(1 for a, b in zip(scalar_barrier, vec.barrier_hit, strict=True) if a != b)
    assert n_mismatch == 0, f"{n_mismatch}/{len(scalar_barrier)} trades divergem do motor escalar"

    ret_net_scalar = scalar_filled["ret_net"].to_numpy().astype(np.float64)
    max_abs_diff = float(np.max(np.abs(ret_net_scalar - vec.ret_net)))
    assert max_abs_diff < 1e-6
