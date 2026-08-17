"""Testes de `src/backtest/fill_reconciliation.py` — reconciliação gate
OTIMISTA (Label Engine, Sprint 6) vs gate REALISTA (fill simulator, Sprint
9). Dado 100% sintético e pequeno (nenhum destes testes toca
`labels/v1/labels.parquet`, `predictions/.../predictions.parquet` ou
`execution/fill_simulator/v1/orders.parquet` reais — DoD explícito da
task: "não precisa rodar sobre o parquet de 462k linhas no teste").

Cobre especificamente os dois achados empíricos documentados na docstring
do módulo: (1) a chave de junção real é `t_entry`, não `t0`; (2) linhas
`barrier_hit == "NOFILL"` têm `t_entry` nulo por construção e devem entrar
na amostra-base com `filled = False`, não ser descartadas como lacuna de
dado."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import numpy as np
import polars as pl
import pytest

from src.backtest import fill_reconciliation as fr
from src.core.metric import Unit
from src.execution.fill_simulator import RPI_BREAK_DATE

_BAR_MS = 900_000  # 15m, mesma constante de tests/unit/test_validation_cpcv.py


def _dt(iso: str) -> datetime:
    return datetime.fromisoformat(iso).replace(tzinfo=UTC)


def _ts_col(values: list[datetime | None]) -> pl.Series:
    return pl.Series(values).cast(pl.Datetime("ms", "UTC"))


# ============================================================================
# build_reconciliation_base — junção + tratamento de NOFILL/lacuna de dado
# ============================================================================


def _predictions_fixture() -> pl.DataFrame:
    """5 sinais válidos (A..E) dentro da janela de teste [2024-01-01,
    2024-01-02], mais 3 linhas que devem ser filtradas antes de qualquer
    junção: side_hat==0 (sem sinal), is_oof==False, e t0 fora da janela."""
    rows = [
        # (t0, side_hat, is_oof, fold_id)
        (_dt("2024-01-01T00:00:00"), 1, True, 0),  # A -> TP, filled=True
        (_dt("2024-01-01T00:15:00"), -1, True, 0),  # B -> SL, filled=False
        (_dt("2024-01-01T00:30:00"), 1, True, 1),  # C -> TIME, sem order (lacuna)
        (_dt("2024-01-01T00:45:00"), -1, True, 1),  # D -> NOFILL, t_entry nulo
        (_dt("2024-01-01T01:00:00"), 1, True, 2),  # E -> TP, filled=True
        (_dt("2024-01-01T01:15:00"), 0, True, 2),  # sem sinal — filtrado
        (_dt("2024-01-01T01:30:00"), 1, False, 2),  # in-sample — filtrado (B07)
        (_dt("2024-01-05T00:00:00"), 1, True, 2),  # fora da janela — filtrado
    ]
    return pl.DataFrame(
        {
            "t0": _ts_col([r[0] for r in rows]),
            "side_hat": pl.Series([r[1] for r in rows], dtype=pl.Int8),
            "is_oof": pl.Series([r[2] for r in rows], dtype=pl.Boolean),
            "fold_id": pl.Series([r[3] for r in rows], dtype=pl.Int16),
        }
    )


def _labels_fixture() -> pl.DataFrame:
    """Uma linha de label por (t0, side) sinalizado em `_predictions_fixture`
    (A..E), `t_entry = t0 + 1 bar` exceto D (NOFILL -> t_entry nulo, mesma
    convenção medida em labels/v1/labels.parquet real)."""
    t0_vals: list[datetime | None] = [
        _dt("2024-01-01T00:00:00"),  # A
        _dt("2024-01-01T00:15:00"),  # B
        _dt("2024-01-01T00:30:00"),  # C
        _dt("2024-01-01T00:45:00"),  # D
        _dt("2024-01-01T01:00:00"),  # E
    ]
    t_entry_vals: list[datetime | None] = [
        _dt("2024-01-01T00:15:00"),  # A
        _dt("2024-01-01T00:30:00"),  # B
        _dt("2024-01-01T00:45:00"),  # C
        None,  # D — NOFILL, t_entry nulo por construção
        _dt("2024-01-01T01:15:00"),  # E
    ]
    side_vals = [1, -1, 1, -1, 1]
    barrier_vals = ["TP", "SL", "TIME", "NOFILL", "TP"]
    ret_net_vals = [0.01, -0.02, 0.0, 0.0, 0.02]  # noqa: magic-number — retornos sintéticos de teste
    n = len(t0_vals)

    return pl.DataFrame(
        {
            "t0": _ts_col(t0_vals),
            "side": pl.Series(side_vals, dtype=pl.Int8),
            "t_entry": _ts_col(t_entry_vals),
            "barrier_hit": pl.Series(barrier_vals, dtype=pl.Categorical),
            "ret_net": pl.Series(ret_net_vals, dtype=pl.Float64),
            "sample_weight": pl.Series([1.0] * n, dtype=pl.Float64),
            "ret_gross": pl.Series(ret_net_vals, dtype=pl.Float64),
            "cost_entry_bps": pl.Series([0.0] * n, dtype=pl.Float64),
            "cost_exit_bps": pl.Series([0.0] * n, dtype=pl.Float64),
            "funding_bps": pl.Series([0.0] * n, dtype=pl.Float64),
        }
    )


def _orders_fixture() -> pl.DataFrame:
    """Só A, B e E têm ordem correspondente — C fica sem par de propósito
    (lacuna genuína de bookTicker); D nunca teria par possível (t_entry
    nulo)."""
    t_post_vals: list[datetime | None] = [
        _dt("2024-01-01T00:15:00"),  # A
        _dt("2024-01-01T00:30:00"),  # B
        _dt("2024-01-01T01:15:00"),  # E
    ]
    return pl.DataFrame(
        {
            "t_post": _ts_col(t_post_vals),
            "side": pl.Series([1, -1, 1], dtype=pl.Int8),
            "filled": pl.Series([True, False, True], dtype=pl.Boolean),
        }
    )


def test_build_reconciliation_base_filtra_sinais_fora_do_escopo() -> None:
    _base, diag = fr.build_reconciliation_base(
        _predictions_fixture(),
        _labels_fixture(),
        _orders_fixture(),
        window_start=date(2024, 1, 1),
        window_end=date(2024, 1, 2),
    )
    # side_hat==0, is_oof==False e t0 fora da janela nunca entram na conta.
    assert diag.n_signals_window == 5


def test_build_reconciliation_base_trata_nofill_por_construcao() -> None:
    base, diag = fr.build_reconciliation_base(
        _predictions_fixture(),
        _labels_fixture(),
        _orders_fixture(),
        window_start=date(2024, 1, 1),
        window_end=date(2024, 1, 2),
    )
    assert diag.n_signals_nofill_by_construction == 1  # D
    nofill_row = base.filter(pl.col("barrier_hit") == "NOFILL")
    assert nofill_row.height == 1
    assert nofill_row["filled"].to_list() == [False]


def test_build_reconciliation_base_exclui_lacuna_genuina_de_dado() -> None:
    base, diag = fr.build_reconciliation_base(
        _predictions_fixture(),
        _labels_fixture(),
        _orders_fixture(),
        window_start=date(2024, 1, 1),
        window_end=date(2024, 1, 2),
    )
    # C (TIME, sem order correspondente) é uma lacuna genuína — excluído.
    assert diag.n_signals_missing_order_data_gap == 1
    assert base.filter(pl.col("barrier_hit") == "TIME").height == 0
    # base final = A, B, D, E (C excluído)
    assert diag.n_signals_common_base == 4
    assert base.height == 4


def test_build_reconciliation_base_levanta_erro_se_sinal_sem_label() -> None:
    predictions = _predictions_fixture()
    labels_sem_par = _labels_fixture().filter(pl.col("barrier_hit") != "TP")  # remove A e E
    with pytest.raises(AssertionError):
        fr.build_reconciliation_base(
            predictions,
            labels_sem_par,
            _orders_fixture(),
            window_start=date(2024, 1, 1),
            window_end=date(2024, 1, 2),
        )


# ============================================================================
# _evaluate_gate — otimista vs realista sobre a MESMA amostra-base
# ============================================================================


def test_evaluate_gate_otimista_vs_realista_mesma_base() -> None:
    base, _ = fr.build_reconciliation_base(
        _predictions_fixture(),
        _labels_fixture(),
        _orders_fixture(),
        window_start=date(2024, 1, 1),
        window_end=date(2024, 1, 2),
    )
    optimistic = fr._evaluate_gate(
        base,
        gate_expr=pl.col("barrier_hit") != "NOFILL",
        gate=fr._GATE_OPTIMISTA,
        gate_description=fr._GATE_OPTIMISTA_DESC,
    )
    realistic = fr._evaluate_gate(
        base,
        gate_expr=pl.col("filled"),
        gate=fr._GATE_REALISTA,
        gate_description=fr._GATE_REALISTA_DESC,
    )
    # base = {A(TP,filled=T), B(SL,filled=F), D(NOFILL,filled=F por construção), E(TP,filled=T)}
    assert optimistic.n_base_signals == 4
    assert optimistic.n_filled == 3  # A, B, E (só D é NOFILL)
    assert optimistic.fill_rate.value == pytest.approx(3 / 4)
    assert optimistic.fill_rate.unit == Unit.PROBABILITY
    assert optimistic.fill_rate.valid is True

    assert realistic.n_base_signals == 4
    assert realistic.n_filled == 2  # só A e E têm filled=True
    assert realistic.fill_rate.value == pytest.approx(2 / 4)

    # realista é sempre <= otimista na mesma amostra-base (limite inferior
    # vs superior, ver docstring do módulo).
    assert realistic.n_filled <= optimistic.n_filled


def test_evaluate_gate_vazio_nao_quebra() -> None:
    empty = pl.DataFrame(
        schema={
            "t0": pl.Datetime("ms", "UTC"),
            "side_hat": pl.Int8,
            "barrier_hit": pl.Utf8,
            "filled": pl.Boolean,
            "ret_net": pl.Float64,
            "ret_gross": pl.Float64,
            "funding_bps": pl.Float64,
            "cost_entry_bps": pl.Float64,
            "cost_exit_bps": pl.Float64,
        }
    )
    result = fr._evaluate_gate(
        empty,
        gate_expr=pl.col("filled"),
        gate=fr._GATE_REALISTA,
        gate_description=fr._GATE_REALISTA_DESC,
    )
    assert result.n_base_signals == 0
    assert result.n_filled == 0
    assert np.isnan(result.fill_rate.value)
    assert np.isnan(result.sharpe_naive.value)


# ============================================================================
# reconstruct_fold_to_path_id — puramente combinatório (1-fatoração de K6)
# ============================================================================


def _synthetic_labels_for_cpcv(n: int = 600) -> pl.DataFrame:
    t0_ms = [i * _BAR_MS for i in range(n)]
    t1_ms = [t + 4 * _BAR_MS for t in t0_ms]
    return pl.DataFrame(
        {
            "t0": pl.Series(t0_ms).cast(pl.Datetime("ms")).dt.replace_time_zone("UTC"),
            "t1": pl.Series(t1_ms).cast(pl.Datetime("ms")).dt.replace_time_zone("UTC"),
        }
    )


def test_reconstruct_fold_to_path_id_mapeia_15_splits_para_5_caminhos() -> None:
    # cpcv_n_groups=6/cpcv_n_test_groups=2 (constants.yaml real) -> C(6,2)=15
    # splits, C(5,1)=5 caminhos — mesma aritmética de tests/unit/test_validation_cpcv.py.
    known_fold_ids = set(range(15))
    mapping = fr.reconstruct_fold_to_path_id(
        _synthetic_labels_for_cpcv(), known_fold_ids=known_fold_ids
    )
    assert set(mapping) == known_fold_ids
    assert set(mapping.values()) == set(range(5))
    # cada caminho recebe exatamente 3 splits (15 / 5).
    counts = {p: list(mapping.values()).count(p) for p in range(5)}
    assert all(c == 3 for c in counts.values())


def test_reconstruct_fold_to_path_id_levanta_erro_se_fold_desconhecido() -> None:
    with pytest.raises(fr.PathReconstructionError):
        fr.reconstruct_fold_to_path_id(_synthetic_labels_for_cpcv(), known_fold_ids={999})


def test_reconstruct_fold_to_path_id_repassa_config_e_symbol_a_generate_splits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fase 4 (2026-08-17): antes desta correção, `generate_splits` era
    chamado sem `config`/`symbol` -- achado da varredura final própria,
    item 17b do plano. Spy sobre a função real prova que os dois chegam."""
    from src.validation import cpcv

    real_generate_splits = cpcv.generate_splits
    captured: dict[str, object] = {}

    def _spy(labels_arg, config=None, *, symbol=None):
        captured.update(config=config, symbol=symbol)
        return real_generate_splits(labels_arg, config=config, symbol=symbol)

    monkeypatch.setattr(cpcv, "generate_splits", _spy)
    custom_config = cpcv.CPCVConfig.from_constants(tf="15m")
    known_fold_ids = set(range(15))
    fr.reconstruct_fold_to_path_id(
        _synthetic_labels_for_cpcv(),
        known_fold_ids=known_fold_ids,
        config=custom_config,
        symbol="ETHUSDT",
    )
    assert captured["config"] is custom_config
    assert captured["symbol"] == "ETHUSDT"


# ============================================================================
# compute_fill_selectivity — P(TP|filled) vs P(TP|not filled), Módulo B
# ============================================================================


def _selectivity_labels_fixture() -> pl.DataFrame:
    t0_vals = [_dt("2024-01-01T00:00:00") + timedelta(minutes=15 * i) for i in range(4)]
    t_entry_vals = [t + timedelta(minutes=15) for t in t0_vals]
    barrier = ["TP", "SL", "TP", "SL"]
    ret_net = [0.02, -0.01, 0.03, -0.02]  # noqa: magic-number — retornos sintéticos de teste
    return pl.DataFrame(
        {
            "t0": _ts_col(list(t0_vals)),
            "side": pl.Series([1, 1, -1, -1], dtype=pl.Int8),
            "t_entry": _ts_col(list(t_entry_vals)),
            "barrier_hit": pl.Series(barrier, dtype=pl.Categorical),
            "ret_net": pl.Series(ret_net, dtype=pl.Float64),
        }
    )


def test_compute_fill_selectivity_p_tp_condicional() -> None:
    labels = _selectivity_labels_fixture()
    t_entry_vals = labels["t_entry"].to_list()
    orders = pl.DataFrame(
        {
            "t_post": _ts_col(list(t_entry_vals)),
            "side": labels["side"],
            "filled": pl.Series([True, False, True, False], dtype=pl.Boolean),
        }
    )
    result = fr.compute_fill_selectivity(
        labels, orders, window_start=date(2024, 1, 1), window_end=date(2024, 1, 2)
    )
    assert result.n_orders_matched == 4
    assert result.n_filled == 2
    assert result.n_notfilled == 2
    # filled: TP,TP -> P(TP|filled)=1.0 ; notfilled: SL,SL -> P(TP|notfilled)=0.0
    assert result.p_tp_given_filled.value == pytest.approx(1.0)
    assert result.p_tp_given_filled.unit == Unit.PROBABILITY
    assert result.p_tp_given_notfilled.value == pytest.approx(0.0)
    assert result.gap_pp.value == pytest.approx(100.0)  # noqa: magic-number
    assert result.gap_pp.unit == Unit.PERCENTAGE_POINTS
    assert result.mean_ret_net_bps_given_filled.value == pytest.approx(
        (0.02 + 0.03) / 2 * 10_000  # noqa: magic-number — mesmos retornos sintéticos acima
    )
    assert result.mean_ret_net_bps_given_filled.unit == Unit.BPS_PER_TRADE


def test_compute_fill_selectivity_amostra_vazia_nao_quebra() -> None:
    labels = _selectivity_labels_fixture()
    orders = pl.DataFrame(
        schema={"t_post": pl.Datetime("ms", "UTC"), "side": pl.Int8, "filled": pl.Boolean}
    )
    result = fr.compute_fill_selectivity(
        labels, orders, window_start=date(2024, 1, 1), window_end=date(2024, 1, 2)
    )
    assert result.n_orders_matched == 0
    assert np.isnan(result.p_tp_given_filled.value)
    assert np.isnan(result.selectivity_cost_bps.value)


# ============================================================================
# Guard-rail de janela — nunca extrapola além de RPI_BREAK_DATE (§9.5 v3.3)
# ============================================================================


def test_assert_window_recusa_janela_alem_da_quebra_rpi() -> None:
    with pytest.raises(ValueError, match="RPI"):
        fr._assert_window_within_measured_coverage(date(2023, 5, 16), RPI_BREAK_DATE)
