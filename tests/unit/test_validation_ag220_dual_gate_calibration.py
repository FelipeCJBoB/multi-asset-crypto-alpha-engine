"""Testes de `src.validation.ag220_dual_gate_calibration` -- isola a
LÓGICA (contagem de n_better estrita, gate de edge, agregação de taxa de
falso-positivo) de treino real, mesmo padrão de mock de `alpha.run_all_
folds`/`backtest_lite.backtest_by_path` já usado em
`test_models_hyperparams_optuna.py`."""

from __future__ import annotations

from typing import Any

import pytest

from src.models import alpha, backtest_lite
from src.models import dataset as ds
from src.validation import ag220_dual_gate_calibration as mod

_FAKE_MF = ds.ModelingFrame(data=None, t1_feature_ids=(), regime_labels_present=())  # type: ignore[arg-type]


def _fake_path_result(
    path_id: int, *, sharpe: float, edge_bps: float, trades: int
) -> backtest_lite.PathBacktestResult:
    return backtest_lite.PathBacktestResult(
        path_id=path_id,
        n_signals=trades + 2,
        n_filled_trades=trades,
        fill_rate=0.9,
        sharpe_naive=sharpe,
        mean_trade_ret=edge_bps / mod._BPS_PER_UNIT,
        std_trade_ret=0.02,
        trades_per_year=100.0,
        win_rate=0.5,
    )


def _patch_plumbing(
    monkeypatch: pytest.MonkeyPatch,
    *,
    c1_by_seed: dict[int, dict[int, backtest_lite.PathBacktestResult]],
    c0_by_seed: dict[int, dict[int, backtest_lite.PathBacktestResult]],
) -> None:
    """`c1_by_seed`/`c0_by_seed`: `{repeat_index: {path_id: PathBacktestResult}}`
    -- indexa pela ORDEM de chamada (repeat 0, 1, 2...), não pela seed em si
    (a seed de permutação é derivada internamente, não controlável de fora)."""
    monkeypatch.setattr(
        mod, "_build_mf_and_splits", lambda *a, **k: (_FAKE_MF, ())
    )
    call_state = {"n": 0}

    def fake_run_all_folds(df: Any, splits: Any, *, variant: str, **kwargs: Any) -> Any:
        return {"variant": variant, "call_n": call_state["n"]}

    def fake_backtest_by_path(
        folds: Any, df_all: Any
    ) -> dict[int, backtest_lite.PathBacktestResult]:
        variant = folds["variant"]
        # call_n avança 2x por repeat (camada1 depois camada0) -- repeat = call_n // 2
        repeat = folds["call_n"] // 2
        result = c1_by_seed[repeat] if variant == alpha.VARIANT_CAMADA1 else c0_by_seed[repeat]
        call_state["n"] += 1
        return result

    monkeypatch.setattr(alpha, "run_all_folds", fake_run_all_folds)
    monkeypatch.setattr(backtest_lite, "backtest_by_path", fake_backtest_by_path)


def test_n_better_usa_comparacao_estrita_nao_conta_empate(monkeypatch: pytest.MonkeyPatch) -> None:
    """`>` (nunca `>=`) -- mesma convenção de `confirm_combo_paired`, não a
    de `backtest_lite.permanence_count` (que conta empate como Camada1
    melhor, AG-214) -- calibrar com a convenção errada mediria um gate que
    ninguém de fato aplica."""
    c1 = {
        0: {
            0: _fake_path_result(0, sharpe=1.0, edge_bps=1.0, trades=40),
            1: _fake_path_result(1, sharpe=1.0, edge_bps=1.0, trades=40),  # empate com C0
        }
    }
    c0 = {
        0: {
            0: _fake_path_result(0, sharpe=0.5, edge_bps=0.0, trades=40),  # C1 > C0 aqui
            1: _fake_path_result(1, sharpe=1.0, edge_bps=0.0, trades=40),  # empate -> NÃO conta
        }
    }
    _patch_plumbing(monkeypatch, c1_by_seed=c1, c0_by_seed=c0)

    result = mod.run_dual_gate_permutation_null(
        "BTCUSDT",
        "R3",
        camada1_hyper=alpha.LGBMHyperparams.from_constants(),
        camada0_hyper=alpha.LGBMHyperparams.from_constants(),
        n_repeats=1,
        device_type="cpu",
    )
    assert result["per_repeat"][0]["n_better"] == 1  # noqa: magic-number -- só o path 0, empate não conta


def test_edge_gate_e_dual_gate_calculados_corretamente(monkeypatch: pytest.MonkeyPatch) -> None:
    """2 repeats: 1 com edge positivo+cobertura suficiente (dual_gate_pass
    verdadeiro se Sharpe também bater), 1 com edge negativo (edge_gate_pass
    falso mesmo com Sharpe favorável)."""
    c1 = {
        0: {0: _fake_path_result(0, sharpe=2.0, edge_bps=5.0, trades=40)},
        1: {0: _fake_path_result(0, sharpe=2.0, edge_bps=-3.0, trades=40)},
    }
    c0 = {
        0: {0: _fake_path_result(0, sharpe=0.0, edge_bps=0.0, trades=40)},
        1: {0: _fake_path_result(0, sharpe=0.0, edge_bps=0.0, trades=40)},
    }
    _patch_plumbing(monkeypatch, c1_by_seed=c1, c0_by_seed=c0)

    result = mod.run_dual_gate_permutation_null(
        "BTCUSDT",
        "R3",
        camada1_hyper=alpha.LGBMHyperparams.from_constants(),
        camada0_hyper=alpha.LGBMHyperparams.from_constants(),
        n_repeats=2,
        device_type="cpu",
    )
    rep0, rep1 = result["per_repeat"]
    assert rep0["camada1_edge_bps"] == pytest.approx(5.0)
    assert rep0["edge_gate_pass"] is True
    assert rep1["camada1_edge_bps"] == pytest.approx(-3.0)
    assert rep1["edge_gate_pass"] is False
    # ambos passam permanence (n_better=1/1 caminho, >= piso real de produção
    # -- só 1 path simulado, então médio/mediana==1 sempre bate qualquer
    # piso <=1; o teste prova o CÁLCULO do edge gate, não o limiar real)
    assert result["false_positive_rate_edge_gate"] == pytest.approx(0.5)  # noqa: magic-number -- 1 de 2 repeats


def test_taxa_falso_positivo_agregada_sobre_todos_os_repeats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """3 repeats, cobertura insuficiente em 1 delas -- edge_gate_pass falha
    por cobertura mesmo com edge positivo (mesmo piso real, alpha_layer1_
    permanence_min_trades=30)."""
    c1 = {
        0: {0: _fake_path_result(0, sharpe=2.0, edge_bps=5.0, trades=40)},
        1: {0: _fake_path_result(0, sharpe=2.0, edge_bps=5.0, trades=5)},  # cobertura insuficiente
        2: {0: _fake_path_result(0, sharpe=2.0, edge_bps=5.0, trades=40)},
    }
    c0 = {i: {0: _fake_path_result(0, sharpe=0.0, edge_bps=0.0, trades=40)} for i in range(3)}
    _patch_plumbing(monkeypatch, c1_by_seed=c1, c0_by_seed=c0)

    result = mod.run_dual_gate_permutation_null(
        "BTCUSDT",
        "R3",
        camada1_hyper=alpha.LGBMHyperparams.from_constants(),
        camada0_hyper=alpha.LGBMHyperparams.from_constants(),
        n_repeats=3,
        device_type="cpu",
    )
    assert result["per_repeat"][1]["edge_gate_pass"] is False  # cobertura, não sinal
    assert result["false_positive_rate_edge_gate"] == pytest.approx(2.0 / 3.0)  # noqa: magic-number
