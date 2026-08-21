"""Testes de `src/analysis/gate_efficiency.py` -- AG-118 (Gate Efficiency),
`PLANO_MESTRE_PRINCE2.md` §15.12.4/§15.12.5. Núcleo puro (`_tail_and_
holding_stats`/`_pool_asymmetric_removal`/`_gate_efficiency_for_symbol_
window`) exercitado com fixtures sintéticas pequenas, valor conhecido à
mão -- sem tocar disco (exceto `_load_raw_labels_from_parquet`, que usa
`tmp_path`)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import polars as pl
import pytest

from src.analysis import gate_efficiency as ge
from src.analysis import m4_critical_windows as mcw
from src.analysis import m4_regime_comparison as m4

# ============================================================================
# _tail_and_holding_stats -- valor conhecido à mão + casos degenerados
# ============================================================================


def test_tail_and_holding_stats_vazio_da_nan() -> None:
    labels = pl.DataFrame(
        {"ret_net": [], "atr_at_t0": [], "n_bars_held": []},
        schema={"ret_net": pl.Float64, "atr_at_t0": pl.Float64, "n_bars_held": pl.Int32},
    )
    p05, median_h, p80_h = ge._tail_and_holding_stats(labels)
    assert np.isnan(p05)
    assert np.isnan(median_h)
    assert np.isnan(p80_h)


def test_tail_and_holding_stats_atr_nao_positivo_e_filtrado() -> None:
    """Linha com `atr_at_t0<=0` nunca entra na razão -- se TODAS forem
    inválidas, `NaN` explícito (nunca `0/0` silencioso, mesma disciplina
    de `unguarded-ratio`)."""
    labels = pl.DataFrame(
        {
            "ret_net": [0.01, 0.02],
            "atr_at_t0": [0.0, -0.01],
            "n_bars_held": [5, 10],
        }
    )
    p05, median_h, p80_h = ge._tail_and_holding_stats(labels)
    assert np.isnan(p05)
    assert np.isnan(median_h)
    assert np.isnan(p80_h)


def test_tail_and_holding_stats_valor_conhecido_a_mao() -> None:
    """10 linhas, `ret_net/atr_at_t0` = -1.0..8.0 (passo 1.0),
    `n_bars_held` = 1..10 -- `np.percentile` com interpolação linear
    (default do numpy) pra p05/p80 confirmado por cálculo direto."""
    ret_net = list(range(-1, 9))  # -1..8
    atr = [1.0] * 10
    n_bars_held = list(range(1, 11))  # 1..10
    labels = pl.DataFrame(
        {
            "ret_net": [float(x) for x in ret_net],
            "atr_at_t0": atr,
            "n_bars_held": n_bars_held,
        }
    )
    p05, median_h, p80_h = ge._tail_and_holding_stats(labels)

    expected_return_atr = np.array(ret_net, dtype=np.float64)
    expected_holding = np.array(n_bars_held, dtype=np.float64)
    assert p05 == pytest.approx(np.percentile(expected_return_atr, 5.0))
    assert median_h == pytest.approx(np.median(expected_holding))
    assert p80_h == pytest.approx(np.percentile(expected_holding, 80.0))


# ============================================================================
# _pool_asymmetric_removal -- valor conhecido à mão + casos degenerados
# ============================================================================


def _joined_df(barrier_hits: list[str], is_stress: list[bool]) -> pl.DataFrame:
    return pl.DataFrame({"barrier_hit": barrier_hits, "_is_stress": is_stress})


def test_pool_asymmetric_removal_lista_vazia_da_nan() -> None:
    result = ge._pool_asymmetric_removal("R1", "TESTUSDT", 1, [])
    assert np.isnan(result.bad_event_capture_rate)
    assert np.isnan(result.good_event_cost_rate)
    assert np.isnan(result.lift)
    assert result.n_sl_total == 0
    assert result.n_tp_total == 0


def test_pool_asymmetric_removal_good_event_cost_rate_zero_da_lift_nan() -> None:
    """4 SL (2 em stress), 0 TP -- `good_event_cost_rate` fica `NaN`
    (n_tp_total=0), `lift` precisa ficar `NaN`, nunca `inf`."""
    df = _joined_df(
        ["SL", "SL", "SL", "SL"],
        [True, True, False, False],
    )
    result = ge._pool_asymmetric_removal("R1", "TESTUSDT", 1, [df])
    assert result.n_sl_total == 4
    assert result.n_tp_total == 0
    assert result.bad_event_capture_rate == pytest.approx(0.5)
    assert np.isnan(result.good_event_cost_rate)
    assert np.isnan(result.lift)


def test_pool_asymmetric_removal_valor_conhecido_a_mao_lift_maior_que_1() -> None:
    """10 SL (8 em stress -> 0,8), 10 TP (2 em stress -> 0,2) --
    `lift = 0,8/0,2 = 4,0` (gate captura 4x mais eventos ruins do que
    bons, proporcionalmente) -- pooled através de 2 janelas (5+5 SL,
    5+5 TP), prova que o pooling soma contagem corretamente."""
    window_a = _joined_df(
        ["SL"] * 5 + ["TP"] * 5,
        [True, True, True, True, False, True, False, False, False, False],
    )
    window_b = _joined_df(
        ["SL"] * 5 + ["TP"] * 5,
        [True, True, True, True, False, True, False, False, False, False],
    )
    result = ge._pool_asymmetric_removal("R1", "TESTUSDT", 1, [window_a, window_b])
    assert result.n_sl_total == 10
    assert result.n_tp_total == 10
    assert result.n_sl_in_stress == 8
    assert result.n_tp_in_stress == 2
    assert result.bad_event_capture_rate == pytest.approx(0.8)
    assert result.good_event_cost_rate == pytest.approx(0.2)
    assert result.lift == pytest.approx(4.0)


# ============================================================================
# _load_raw_labels_from_parquet -- IO real (tmp_path), sem tocar
# experiments/ de verdade
# ============================================================================


def test_load_raw_labels_from_parquet_arquivo_ausente_devolve_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(mcw, "RAW_LABELS_OUTPUT_DIR", tmp_path)
    result = ge._load_raw_labels_from_parquet("R1", "RECENTE", "TESTUSDT", "hmm_gaussian_k4_v1")
    assert result is None


def test_load_raw_labels_from_parquet_le_de_volta_bit_a_bit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(mcw, "RAW_LABELS_OUTPUT_DIR", tmp_path)
    path = mcw._raw_labels_path("R1", "RECENTE", "TESTUSDT", "hmm_gaussian_k4_v1")
    path.parent.mkdir(parents=True, exist_ok=True)
    open_time_ms = np.array([1_000, 2_000, 3_000], dtype=np.int64)
    close_time_ms = np.array([1_999, 2_999, 3_999], dtype=np.int64)
    canonical_id = np.array([0, 1, 2], dtype=np.int64)
    pl.DataFrame(
        {
            "open_time_ms": open_time_ms,
            "close_time_ms": close_time_ms,
            "canonical_id": canonical_id,
        }
    ).write_parquet(path)

    result = ge._load_raw_labels_from_parquet("R1", "RECENTE", "TESTUSDT", "hmm_gaussian_k4_v1")
    assert result is not None
    np.testing.assert_array_equal(result.open_time_ms, open_time_ms)
    np.testing.assert_array_equal(result.close_time_ms, close_time_ms)
    np.testing.assert_array_equal(result.canonical_id, canonical_id)


# ============================================================================
# _gate_efficiency_for_symbol_window -- smoke test sintético, valor
# conhecido à mão pro bucket de stress
# ============================================================================


def _synthetic_window() -> mcw.CriticalWindow:
    return mcw.CriticalWindow(
        name="WIN_TEST",
        event="evento sintético de teste",
        start="2023-01-01",
        end="2023-04-01",
        symbols=("TESTUSDT",),
        note="janela sintética de teste",
    )


def test_gate_efficiency_for_symbol_window_identifica_bucket_de_stress_correto() -> None:
    """2 buckets (0=calmo, 1=stress) -- bucket 1 tem `realized_vol_short`
    médio maior por construção. Barras de regime cobrem todo janeiro-
    fevereiro/2023, labels caem dentro dessa janela -- confirma que
    `is_stress_bucket=True` só nas linhas do bucket 1."""
    day_ms = 86_400_000
    n = 40
    # fecha 1ms antes do próximo dia
    close_time_ms = (np.arange(n, dtype=np.int64) + 1) * day_ms - 1
    open_time_ms = np.arange(n, dtype=np.int64) * day_ms
    # metade dos bars em bucket 0 (calmo), metade em bucket 1 (stress)
    canonical_id = np.array([0] * 20 + [1] * 20, dtype=np.int64)
    regime_raw = m4.RawLabels(
        open_time_ms=open_time_ms, close_time_ms=close_time_ms, canonical_id=canonical_id
    )

    rng = np.random.default_rng(7)
    # realized_vol_short bem maior no bucket 1 -- identify_stress_state_by_volatility
    # deve escolher bucket 1 sem ambiguidade.
    realized_vol_short = np.concatenate(
        [rng.normal(0.01, 0.001, 20), rng.normal(0.05, 0.001, 20)]
    )
    forward_realized_vol = realized_vol_short.copy()  # não usado por este teste
    vol_history = mcw._SymbolForwardVolHistory(
        close_time_ms=close_time_ms,
        realized_vol_short=realized_vol_short,
        forward_realized_vol=forward_realized_vol,
    )

    # labels: 1 trade por dia, side=1, metade TP/metade SL, t0 alinhado
    # ao close_time_ms de cada barra (as-of backward casa exato).
    t0_ms = close_time_ms
    barrier_hit = (["TP", "SL"] * (n // 2))
    labels_full = pl.DataFrame(
        {
            "t0": pl.from_epoch(pl.Series(t0_ms), time_unit="ms").dt.replace_time_zone("UTC"),
            "side": [1] * n,
            "barrier_hit": barrier_hit,
            "ret_net": [0.01 if b == "TP" else -0.01 for b in barrier_hit],
            "atr_at_t0": [0.02] * n,
            "n_bars_held": [3] * n,
        }
    )

    rows, joined = ge._gate_efficiency_for_symbol_window(
        "R1",
        _synthetic_window(),
        "TESTUSDT",
        regime_raw,
        vol_history,
        labels_full,
        tp_atr_mult=1.5,
        sl_atr_mult=1.0,
        maker_fee=0.0002,
        taker_fee=0.0004,
    )

    assert joined is not None
    assert len(rows) == 2  # side=1 x 2 buckets (nenhum side=-1 nos dados sintéticos)
    by_bucket = {r.bucket: r for r in rows}
    assert by_bucket[0].is_stress_bucket is False
    assert by_bucket[1].is_stress_bucket is True
    assert by_bucket[0].n == 20
    assert by_bucket[1].n == 20
    # TP/SL alternam 50/50 em cada bucket (20 linhas, 10 TP/10 SL)
    assert by_bucket[0].p_target == pytest.approx(0.5)
    assert by_bucket[0].p_stop == pytest.approx(0.5)


def test_gate_efficiency_for_symbol_window_sem_overlap_devolve_vazio() -> None:
    """`regime_raw`/`vol_history` fora do período `[window.start,
    window.end)` -- `_asof_join_regime_onto_labels` não encontra match,
    `labels_full` vazio após o filtro de janela -- `((), None)`, nunca
    erro."""
    close_time_ms = np.array([1, 2, 3], dtype=np.int64)
    regime_raw = m4.RawLabels(
        open_time_ms=close_time_ms, close_time_ms=close_time_ms,
        canonical_id=np.array([0, 0, 1], dtype=np.int64),
    )
    vol_history = mcw._SymbolForwardVolHistory(
        close_time_ms=close_time_ms,
        realized_vol_short=np.array([0.01, 0.01, 0.02]),
        forward_realized_vol=np.array([0.01, 0.01, 0.02]),
    )
    labels_full = pl.DataFrame(
        {
            "t0": pl.Series([], dtype=pl.Datetime(time_unit="us", time_zone="UTC")),
            "side": pl.Series([], dtype=pl.Int8),
            "barrier_hit": pl.Series([], dtype=pl.Utf8),
            "ret_net": pl.Series([], dtype=pl.Float64),
            "atr_at_t0": pl.Series([], dtype=pl.Float64),
            "n_bars_held": pl.Series([], dtype=pl.Int32),
        }
    )
    rows, joined = ge._gate_efficiency_for_symbol_window(
        "R1",
        _synthetic_window(),
        "TESTUSDT",
        regime_raw,
        vol_history,
        labels_full,
        tp_atr_mult=1.5,
        sl_atr_mult=1.0,
        maker_fee=0.0002,
        taker_fee=0.0004,
    )
    assert rows == ()
    assert joined is None


# ============================================================================
# _raw_labels_provenance -- item 11 do parecer de auditoria externa
# (2026-08-20): hash de conteúdo dos parquets consumidos, nunca inventado
# quando o relatório de origem do AG-114 não existe.
# ============================================================================


def test_raw_labels_provenance_sem_arquivos_devolve_hash_vazio_e_metadados_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(mcw, "RAW_LABELS_OUTPUT_DIR", tmp_path / "raw_labels")
    monkeypatch.setattr(mcw, "EXPERIMENTS_DIR", tmp_path)
    result = ge._raw_labels_provenance("hmm_gaussian_k4_v1", (_synthetic_window(),))
    assert result["raw_labels_n_files_hashed"] == 0
    assert result["ag114_source_generated_at"] is None
    assert result["ag114_source_code_version"] is None
    # blake2b de string vazia -- determinístico, não depende de nenhum arquivo.
    import hashlib

    assert result["raw_labels_content_hash_blake2b"] == hashlib.blake2b(b"").hexdigest()


def test_raw_labels_provenance_le_generated_at_do_relatorio_ag114_real(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    raw_dir = tmp_path / "raw_labels"
    monkeypatch.setattr(mcw, "RAW_LABELS_OUTPUT_DIR", raw_dir)
    monkeypatch.setattr(mcw, "EXPERIMENTS_DIR", tmp_path)

    window = _synthetic_window()
    for resolution_id in mcw.RESOLUTIONS:
        p = mcw._raw_labels_path(resolution_id, window.name, "TESTUSDT", "hmm_gaussian_k4_v1")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"conteudo sintetico de teste")

    import orjson

    ag114_report_path = tmp_path / "m4_critical_windows_report.json"
    ag114_report_path.write_bytes(
        orjson.dumps({"generated_at": "2026-08-20T22:28:42Z", "code_version": "abc1234"})
    )

    result = ge._raw_labels_provenance(
        "hmm_gaussian_k4_v1", (mcw.CriticalWindow(
            name=window.name, event=window.event, start=window.start, end=window.end,
            symbols=("TESTUSDT",), note=window.note,
        ),)
    )
    assert result["raw_labels_n_files_hashed"] == len(mcw.RESOLUTIONS)
    assert result["ag114_source_generated_at"] == "2026-08-20T22:28:42Z"
    assert result["ag114_source_code_version"] == "abc1234"
