"""Testes de `src/labels/experiment_log.py` — registro append-only de
variantes de barreira (§11.6, Sprint 6 explícito no roadmap). Todos usam
`tmp_path`/`path=` explícito — NUNCA escrevem no
`experiments/label_engine_runs.parquet` real do repo (esse arquivo é
populado pelo run de medição real do Sprint 6, não pela suíte de testes)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from src.labels import experiment_log
from src.labels.triple_barrier import LabelBuildStats, LabelConfig

_CFG = LabelConfig(
    tp_atr_mult=2.0, sl_atr_mult=1.5, time_stop_ms=32 * 900_000, fill_timeout_ms=900_000,
    atr_window_ms=20 * 900_000, maker_fee=0.0002, taker_fee=0.0005,
    estimator_id="atr_wilder_w20",
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
        tp_atr_mult=2.5, sl_atr_mult=1.5, time_stop_ms=32 * 900_000, fill_timeout_ms=900_000,
        atr_window_ms=20 * 900_000, maker_fee=0.0002, taker_fee=0.0005,
        estimator_id="atr_wilder_w20",
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


def _legacy_schema_row(log_path: Path) -> None:
    """Simula o arquivo REAL em disco (`experiments/label_engine_runs.
    parquet`, existe desde 2026-08-09) escrito sob o `_SCHEMA` de ANTES do
    AG-031/B1 -- sem a coluna `time_stop_ms`, `time_stop_bars` como fonte
    única (Int32, populado). Bypassa `record_experiment` de propósito: o
    objetivo é criar em disco exatamente o schema antigo, não o schema
    atual com um valor antigo dentro."""
    legacy_schema: dict[str, Any] = {
        "experiment_id": pl.Int64,
        "logged_at_utc": pl.Datetime("ms", "UTC"),
        "sprint": pl.Int32,
        "stage": pl.Utf8,
        "symbol": pl.Utf8,
        "period_start": pl.Utf8,
        "period_end": pl.Utf8,
        "config_hash": pl.Utf8,
        "tp_atr_mult": pl.Float64,
        "sl_atr_mult": pl.Float64,
        "time_stop_bars": pl.Int32,
        "fill_timeout_bars": pl.Int32,
        "atr_window": pl.Int32,
        "maker_fee": pl.Float64,
        "taker_fee": pl.Float64,
        "n_labels": pl.Int64,
        "n_tp": pl.Int64,
        "n_sl": pl.Int64,
        "n_time": pl.Int64,
        "n_nofill": pl.Int64,
        "pct_tp": pl.Float64,
        "pct_sl": pl.Float64,
        "pct_time": pl.Float64,
        "pct_nofill": pl.Float64,
        "mean_ret_net": pl.Float64,
        "std_ret_net": pl.Float64,
        "sum_uniqueness": pl.Float64,
        "notes": pl.Utf8,
    }
    legacy_row = {
        "experiment_id": 1,
        "logged_at_utc": datetime(2026, 8, 9, tzinfo=UTC),
        "sprint": 6,
        "stage": "labels_build",
        "symbol": "BTCUSDT",
        "period_start": "2020-01-01",
        "period_end": "2026-08-08",
        "config_hash": "legado0000000000",
        "tp_atr_mult": 2.0,
        "sl_atr_mult": 1.5,
        "time_stop_bars": 32,
        "fill_timeout_bars": 1,
        "atr_window": 20,
        "maker_fee": 0.0002,
        "taker_fee": 0.0005,
        "n_labels": 1000,
        "n_tp": 300,
        "n_sl": 300,
        "n_time": 300,
        "n_nofill": 100,
        "pct_tp": 0.3,
        "pct_sl": 0.3,
        "pct_time": 0.3,
        "pct_nofill": 0.1,
        "mean_ret_net": 0.001,
        "std_ret_net": 0.01,
        "sum_uniqueness": 500.0,
        "notes": "run pré-AG-031",
    }
    pl.DataFrame([legacy_row], schema=legacy_schema).write_parquet(log_path)


def test_record_experiment_tolera_arquivo_real_com_schema_antigo_sem_time_stop_ms_nem_atr_window_ms(
    tmp_path: Path,
) -> None:
    """AG-044 (achado de `project_assurance`) -- o `how="diagonal"` em
    `record_experiment` existe especificamente pra tolerar o schema do
    arquivo REAL (`experiments/label_engine_runs.parquet`, sem
    `time_stop_ms` nem `atr_window_ms`), mas nenhum teste exercitava esse
    caminho contra um frame de schema DIFERENTE -- só contra dois frames já
    no schema atual. Este teste escreve o schema antigo de verdade em disco
    (bypassando `record_experiment`, ver `_legacy_schema_row`) e confirma
    que uma chamada real de `record_experiment` não levanta e produz as
    duas linhas corretamente alinhadas por nome de coluna."""
    log_path = tmp_path / "runs_legado.parquet"
    _legacy_schema_row(log_path)

    labels = _labels_frame(["TP", "SL"], [0.01, -0.01], [0.5, 0.5])
    experiment_log.record_experiment(
        labels,
        _CFG,
        symbol="BTCUSDT",
        period_start="2024-01-01",
        period_end="2024-01-02",
        path=log_path,
    )

    out = experiment_log.load_experiment_log(log_path)
    assert out.height == 2
    assert sorted(out["experiment_id"].to_list()) == [1, 2]

    legacy_row = out.filter(pl.col("experiment_id") == 1)
    assert legacy_row["time_stop_bars"][0] == 32
    assert legacy_row["time_stop_ms"][0] is None
    assert legacy_row["atr_window"][0] == 20
    assert legacy_row["atr_window_ms"][0] is None

    new_row = out.filter(pl.col("experiment_id") == 2)
    assert new_row["time_stop_ms"][0] == _CFG.time_stop_ms
    assert new_row["time_stop_bars"][0] is None
    assert new_row["atr_window_ms"][0] == _CFG.atr_window_ms
    assert new_row["atr_window"][0] is None
    assert new_row["config_hash"][0] == _CFG.config_hash


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


# ============================================================================
# build_stats (AG-128, F2) — n_warmup_dropped/n_incomplete_tail/n_tie_break
# ============================================================================


def test_record_experiment_build_stats_gravado_nas_3_colunas_novas(tmp_path: Path) -> None:
    """F2 -- os 3 contadores de `triple_barrier.LabelBuildStats` (antes só
    emitidos via `logger.info`, nunca persistidos) chegam nas colunas
    novas do schema quando `build_stats` é passado."""
    log_path = tmp_path / "runs.parquet"
    labels = _labels_frame(["TP", "SL"], [0.01, -0.01], [0.5, 0.5])
    stats = LabelBuildStats(n_warmup_dropped=7, n_incomplete_tail=2, n_tie_break=1)

    experiment_log.record_experiment(
        labels,
        _CFG,
        symbol="BTCUSDT",
        period_start="2024-01-01",
        period_end="2024-01-02",
        build_stats=stats,
        path=log_path,
    )
    out = experiment_log.load_experiment_log(log_path)
    assert out["n_warmup_dropped"][0] == 7
    assert out["n_incomplete_tail"][0] == 2
    assert out["n_tie_break"][0] == 1


def test_record_experiment_build_stats_ausente_grava_null(tmp_path: Path) -> None:
    """`build_stats=None` (default) -- todo caller existente que só tem
    `labels`/`config` em mãos (ex. os testes acima deste arquivo) continua
    funcionando sem passar `build_stats`; as 3 colunas novas ficam `null`,
    não um valor inventado."""
    log_path = tmp_path / "runs.parquet"
    labels = _labels_frame(["TP", "SL"], [0.01, -0.01], [0.5, 0.5])

    experiment_log.record_experiment(
        labels,
        _CFG,
        symbol="BTCUSDT",
        period_start="2024-01-01",
        period_end="2024-01-02",
        path=log_path,
    )
    out = experiment_log.load_experiment_log(log_path)
    assert out["n_warmup_dropped"][0] is None
    assert out["n_incomplete_tail"][0] is None
    assert out["n_tie_break"][0] is None
