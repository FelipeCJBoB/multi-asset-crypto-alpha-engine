"""Camada labels — triple barrier em mark_1m (§3.4), fill_model, pesos por
unicidade (§3.5), experiment tracking (§11.6, Sprint 6). Lido apenas por
models/, validation/, backtest/ (§3.7, import-linter em pyproject.toml)."""

from __future__ import annotations

from .experiment_log import load_experiment_log, record_experiment, summarize_labels
from .fill_model import FillResult, simulate_fill, simulate_fill_arrays
from .triple_barrier import (
    LABEL_COLUMNS,
    ConfigHashMismatchError,
    LabelBuildStats,
    LabelConfig,
    assert_label_invariants,
    build_labels,
    build_labels_both_sides,
    build_labels_both_sides_with_stats,
    build_labels_for_symbol,
    build_labels_for_symbol_with_stats,
    build_labels_with_stats,
    round_to_tick,
    verify_config_hash,
    write_labels_atomic,
)
from .weights import apply_weights, compute_concurrency_and_uniqueness

__all__ = [
    "LABEL_COLUMNS",
    "ConfigHashMismatchError",
    "FillResult",
    "LabelBuildStats",
    "LabelConfig",
    "apply_weights",
    "assert_label_invariants",
    "build_labels",
    "build_labels_both_sides",
    "build_labels_both_sides_with_stats",
    "build_labels_for_symbol",
    "build_labels_for_symbol_with_stats",
    "build_labels_with_stats",
    "compute_concurrency_and_uniqueness",
    "load_experiment_log",
    "record_experiment",
    "round_to_tick",
    "simulate_fill",
    "simulate_fill_arrays",
    "summarize_labels",
    "verify_config_hash",
    "write_labels_atomic",
]
