"""Camada validation — CPCV com purge por t1 (§11.4), 14 testes de leakage
(§11.5), DSR/PSR (§11.6), walk-forward (§11.4.1).

DSR/PSR (§11.6, `dsr.py`) implementados na Faixa 2/pré-FASE 3
(2026-08-09) — escopo mínimo pedido pelo Manager para avaliar UMA
configuração já medida contra o `N_lifetime` auditado, não o módulo
formal completo do Sprint 11. PBO (§11.6) e walk-forward (§11.4.1)
continuam não implementados — ver `docs/SPRINT_LOG.md` para o que ficou
de fora e por quê."""

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
from .dsr import (
    DSRResult,
    compute_dsr,
    dsr_passes_conventional_threshold,
    expected_max_sharpe_under_n_trials,
    probabilistic_sharpe_ratio,
    sharpe_difference_block_bootstrap,
    sharpe_ratio_standard_error,
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
    "DSRResult",
    "LeakageStatus",
    "LeakageTestResult",
    "assert_embargo_respected",
    "assert_no_train_t1_leaks_into_test",
    "assign_time_groups",
    "compute_dsr",
    "dsr_passes_conventional_threshold",
    "expected_max_sharpe_under_n_trials",
    "generate_splits",
    "load_labels_v1",
    "probabilistic_sharpe_ratio",
    "run_all_leakage_tests",
    "sharpe_difference_block_bootstrap",
    "sharpe_ratio_standard_error",
    "summarize_splits",
    "write_leakage_report_atomic",
]
