"""Camada validation — CPCV com purge por t1 (§11.4), 14 testes de leakage
(§11.5), DSR/PSR/PBO (§11.6), walk-forward (§11.4.1).

DSR/PSR/PBO (§11.6) e walk-forward (§11.4.1) ainda não implementados neste
Sprint (escopo desta rodada: `cpcv.py` + `leakage.py`) — ver relatório do
Sprint para o que ficou de fora e por quê."""

from __future__ import annotations

from .cpcv import (
    CPCVConfig,
    CPCVError,
    CPCVResult,
    CPCVSplit,
    assert_embargo_respected,
    assert_no_train_t1_leaks_into_test,
    assign_time_groups,
    generate_splits,
    load_labels_v1,
    summarize_splits,
)
from .leakage import (
    LeakageStatus,
    LeakageTestResult,
    run_all_leakage_tests,
    write_leakage_report_atomic,
)

__all__ = [
    "CPCVConfig",
    "CPCVError",
    "CPCVResult",
    "CPCVSplit",
    "LeakageStatus",
    "LeakageTestResult",
    "assert_embargo_respected",
    "assert_no_train_t1_leaks_into_test",
    "assign_time_groups",
    "generate_splits",
    "load_labels_v1",
    "run_all_leakage_tests",
    "summarize_splits",
    "write_leakage_report_atomic",
]
