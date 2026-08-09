"""Testes de `src/labels/experiment_log.py` — registro append-only de
variantes de barreira (§11.6, Sprint 6 explícito no roadmap). Todos usam
`tmp_path`/`path=` explícito — NUNCA escrevem no
`experiments/label_engine_runs.parquet` real do repo (esse arquivo é
populado pelo run de medição real do Sprint 6, não pela suíte de testes)."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from src.labels import experiment_log
from src.labels.triple_barrier import LabelConfig

_CFG = LabelConfig(
    tp_atr_mult=2.0, sl_atr_mult=1.5, time_stop_bars=32, fill_timeout_bars=1, atr_window=20,
    maker_fee=0.0002, taker_fee=0.0005,
)


def _labels_frame(
    barrier_hits: list[str], ret_net: list[float], uniqueness: list[float]
) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "barrier_hit": pl.Series(barrier_hits, dtype=pl.Categorical),
            "ret_net": pl.Series(ret_net, dtype=pl.Float64),
            "uniqueness": pl.Series(uniqueness, dtype=pl.Float64),
        }
    )


# ============================================================================
# load_experiment_log
# ============================================================================


def test_load_experiment_log_inexistente_devolve_vazio_com_schema(tmp_path: Path) -> None:
    out = experiment_log.load_experiment_log(tmp_path / "nao_existe.parquet")
    assert out.height == 0
    assert "experiment_id" in out.columns
    assert "config_hash" in out.columns


# ============================================================================
# summarize_labels
# ============================================================================


def test_summarize_labels_conta_certo() -> None:
    labels = _labels_frame(
        ["TP", "TP", "SL", "TIME", "NOFILL"],
        [0.01, 0.02, -0.015, 0.0, 0.0],
        [0.5, 0.4, 0.6, 0.3, 0.2],
    )
    stats = experiment_log.summarize_labels(labels)
    assert stats["n_labels"] == 5
    assert stats["n_tp"] == 2
    assert stats["n_sl"] == 1
    assert stats["n_time"] == 1
    assert stats["n_nofill"] == 1
    assert stats["pct_tp"] == 2 / 5
    assert stats["sum_uniqueness"] == pytest.approx(sum([0.5, 0.4, 0.6, 0.3, 0.2]))


def test_summarize_labels_dataset_vazio() -> None:
    empty = pl.DataFrame(
        schema={"barrier_hit": pl.Categorical, "ret_net": pl.Float64, "uniqueness": pl.Float64}
    )
    stats = experiment_log.summarize_labels(empty)
    assert stats["n_labels"] == 0
    assert stats["pct_tp"] == 0.0


# ============================================================================
# record_experiment — append-only, nunca sobrescreve linha existente
# ============================================================================


def test_record_experiment_cria_arquivo_com_id_1(tmp_path: Path) -> None:
    log_path = tmp_path / "runs.parquet"
    labels = _labels_frame(["TP", "SL"], [0.01, -0.01], [0.5, 0.5])

    written = experiment_log.record_experiment(
        labels,
        _CFG,
        symbol="BTCUSDT",
        period_start="2024-01-01",
        period_end="2024-01-02",
        path=log_path,
    )
    assert written == log_path
    assert log_path.exists()

    out = experiment_log.load_experiment_log(log_path)
    assert out.height == 1
    assert out["experiment_id"][0] == 1
    assert out["config_hash"][0] == _CFG.config_hash
    assert out["n_labels"][0] == 2


def test_record_experiment_acrescenta_sem_apagar_anterior(tmp_path: Path) -> None:
    log_path = tmp_path / "runs.parquet"
    labels_a = _labels_frame(["TP", "SL"], [0.01, -0.01], [0.5, 0.5])
    labels_b = _labels_frame(["TP", "TP", "TIME"], [0.01, 0.02, 0.0], [0.4, 0.4, 0.2])

    experiment_log.record_experiment(
        labels_a,
        _CFG,
        symbol="BTCUSDT",
        period_start="2024-01-01",
        period_end="2024-01-02",
        path=log_path,
    )
    cfg_b = LabelConfig(
        tp_atr_mult=2.5, sl_atr_mult=1.5, time_stop_bars=32, fill_timeout_bars=1, atr_window=20,
        maker_fee=0.0002, taker_fee=0.0005,
    )
    experiment_log.record_experiment(
        labels_b,
        cfg_b,
        symbol="BTCUSDT",
        period_start="2024-02-01",
        period_end="2024-02-02",
        path=log_path,
    )

    out = experiment_log.load_experiment_log(log_path)
    assert out.height == 2
    assert sorted(out["experiment_id"].to_list()) == [1, 2]
    # a primeira linha continua intacta -- "nunca edita nem remove"
    first = out.filter(pl.col("experiment_id") == 1)
    assert first["config_hash"][0] == _CFG.config_hash
    assert first["n_labels"][0] == 2
    second = out.filter(pl.col("experiment_id") == 2)
    assert second["config_hash"][0] == cfg_b.config_hash
    assert second["n_labels"][0] == 3


def test_record_experiment_notes_e_periodo_gravados(tmp_path: Path) -> None:
    log_path = tmp_path / "runs.parquet"
    labels = _labels_frame(["TIME"], [0.0], [1.0])
    experiment_log.record_experiment(
        labels,
        _CFG,
        symbol="BTCUSDT",
        period_start="2020-01-01",
        period_end="2026-08-06",
        notes="medicao de teste",
        path=log_path,
    )
    out = experiment_log.load_experiment_log(log_path)
    assert out["period_start"][0] == "2020-01-01"
    assert out["period_end"][0] == "2026-08-06"
    assert out["notes"][0] == "medicao de teste"
