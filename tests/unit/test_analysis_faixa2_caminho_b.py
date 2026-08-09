"""Testes de `src/analysis/faixa2_caminho_b.py` — cobertura focada na
lógica pura mais recente (E1 synthesis, pré-E2 (1)/(3)): as peças que
processam dado real (D1-D4, F0.2, E1 sweep completo, pré-E2 (2)
permutation importance) já se auto-verificam via os checks embutidos nos
próprios relatórios (sanidade do centro da grade contra Sprint 6,
reprodução bit-idêntica contra `alpha_c1_v1`) e são caras demais para
rodar em `pytest` de rotina — este arquivo cobre o que É barato e
determinístico testar com fixture sintética."""

from __future__ import annotations

import polars as pl
import pytest

from src.analysis import faixa2_caminho_b as f2

# ============================================================================
# _edge_atr_closed_form_by_regime
# ============================================================================


def _mf_side_all(regime_counts: dict[str, int]) -> pl.DataFrame:
    rows: list[str] = []
    for regime, n in regime_counts.items():
        rows.extend([regime] * n)
    return pl.DataFrame({"regime": rows})


def _cell_trades(rows: list[tuple[str, str]]) -> pl.DataFrame:
    """`rows` = lista de `(regime, barrier_hit)`."""
    return pl.DataFrame(
        {"regime": [r[0] for r in rows], "barrier_hit": [r[1] for r in rows]}
    )


def test_edge_atr_closed_form_formula_basica() -> None:
    mf_side_all = _mf_side_all({"R1": 10})
    trades = _cell_trades([("R1", "TP")] * 4 + [("R1", "SL")] * 3 + [("R1", "TIME")] * 1)
    out = f2._edge_atr_closed_form_by_regime(trades, mf_side_all, tp=2.0, sl=1.5)
    r1 = out["R1"]
    assert r1["frac_tp"] == pytest.approx(0.4)
    assert r1["frac_sl"] == pytest.approx(0.3)
    assert r1["frac_time"] == pytest.approx(0.1)
    # edge = 0.4*2.0 - 0.3*1.5 = 0.8 - 0.45 = 0.35
    assert r1["edge_atr_closed_form"] == pytest.approx(0.35)


def test_edge_atr_closed_form_denominador_e_total_do_regime_nao_so_preenchidos() -> None:
    """`n_total_regime` inclui NOFILL (10 barras no regime, só 5
    preenchidas) -- frac_tp/frac_sl usam o denominador MAIOR, não o de
    trades preenchidos."""
    mf_side_all = _mf_side_all({"R2": 10})
    trades = _cell_trades([("R2", "TP")] * 5)  # só 5 das 10 barras do regime preenchidas
    out = f2._edge_atr_closed_form_by_regime(trades, mf_side_all, tp=2.0, sl=1.5)
    assert out["R2"]["frac_tp"] == pytest.approx(0.5)
    assert out["R2"]["edge_atr_closed_form"] == pytest.approx(1.0)  # 0.5*2.0 - 0*1.5


def test_edge_atr_closed_form_regime_sem_barra_da_nan() -> None:
    mf_side_all = _mf_side_all({"R1": 5})  # R2 ausente
    trades = _cell_trades([("R1", "TP")])
    out = f2._edge_atr_closed_form_by_regime(trades, mf_side_all, tp=2.0, sl=1.5)
    assert out["R2"]["n_total_regime"] == 0
    assert out["R2"]["frac_tp"] != out["R2"]["frac_tp"]  # NaN != NaN


# ============================================================================
# _edge_atr_synthesis
# ============================================================================


def _fake_cell(tp: float, sl: float, edge_by_regime: dict[str, float]) -> dict[str, object]:
    return {
        "tp_atr_mult": tp,
        "sl_atr_mult": sl,
        "edge_atr_closed_form_by_regime": {
            r: {"edge_atr_closed_form": e} for r, e in edge_by_regime.items()
        },
    }


def test_edge_atr_synthesis_escolhe_maior_edge_medio() -> None:
    cells = {
        "long_tp1.5_sl1.0": _fake_cell(
            1.5, 1.0, {"R1": 0.1, "R2": 0.1, "R3": 0.1, "R4": 0.1}
        ),
        "long_tp2.0_sl1.5": _fake_cell(
            2.0, 1.5, {"R1": 0.5, "R2": 0.5, "R3": 0.5, "R4": 0.5}
        ),
        "short_tp1.5_sl1.0": _fake_cell(
            1.5, 1.0, {"R1": 0.2, "R2": 0.2, "R3": 0.2, "R4": 0.2}
        ),
    }
    out = f2._edge_atr_synthesis(cells)
    assert out["best_by_side"]["long"]["cell"] == "long_tp2.0_sl1.5"
    assert out["best_by_side"]["long"]["toca_borda_inferior_tp"] is False


def test_edge_atr_synthesis_detecta_borda_inferior_e_propoe_extensao() -> None:
    cells = {
        "long_tp1.5_sl1.0": _fake_cell(
            f2._E1_TP_LOWER_BOUNDARY, 1.0, {"R1": 0.9, "R2": 0.9, "R3": 0.9, "R4": 0.9}
        ),
        "long_tp2.0_sl1.0": _fake_cell(
            2.0, 1.0, {"R1": 0.1, "R2": 0.1, "R3": 0.1, "R4": 0.1}
        ),
        "short_tp1.5_sl1.0": _fake_cell(
            f2._E1_TP_LOWER_BOUNDARY, 1.0, {"R1": 0.9, "R2": 0.9, "R3": 0.9, "R4": 0.9}
        ),
    }
    out = f2._edge_atr_synthesis(cells)
    assert out["best_by_side"]["long"]["toca_borda_inferior_tp"] is True
    assert out["proposta_extensao_grade"]["tp_atr_mult_proposto"] == [1.0, 1.25]


def test_edge_atr_synthesis_nao_propoe_extensao_quando_borda_nao_tocada() -> None:
    cells = {
        "long_tp2.0_sl1.0": _fake_cell(
            2.0, 1.0, {"R1": 0.9, "R2": 0.9, "R3": 0.9, "R4": 0.9}
        ),
        "long_tp1.5_sl1.0": _fake_cell(
            f2._E1_TP_LOWER_BOUNDARY, 1.0, {"R1": 0.1, "R2": 0.1, "R3": 0.1, "R4": 0.1}
        ),
        "short_tp2.0_sl1.0": _fake_cell(
            2.0, 1.0, {"R1": 0.9, "R2": 0.9, "R3": 0.9, "R4": 0.9}
        ),
        "short_tp1.5_sl1.0": _fake_cell(
            f2._E1_TP_LOWER_BOUNDARY, 1.0, {"R1": 0.1, "R2": 0.1, "R3": 0.1, "R4": 0.1}
        ),
    }
    out = f2._edge_atr_synthesis(cells)
    assert "tp_atr_mult_proposto" not in out["proposta_extensao_grade"]


# ============================================================================
# e2_prereq_configuracoes_viaveis_orcamento
# ============================================================================


def test_configuracoes_viaveis_orcamento_classifica_por_path() -> None:
    orcamento = {
        "implied_budget_trades_per_year": 100.0,
        "cenarios": {
            "cenario_a": {"trades_per_year_by_path": {"0": 80.0, "1": 120.0, "2": 100.0}},
        },
    }
    out = f2.e2_prereq_configuracoes_viaveis_orcamento(orcamento)
    cenario = out["cenarios"]["cenario_a"]
    assert cenario["paths_viaveis"] == ["0", "2"]
    assert cenario["paths_inviaveis"] == ["1"]
    assert cenario["cenario_totalmente_viavel"] is False
    assert cenario["detalhe_por_path"]["1"]["razao_vs_orcamento"] == pytest.approx(1.2)


def test_configuracoes_viaveis_orcamento_cenario_totalmente_viavel() -> None:
    orcamento = {
        "implied_budget_trades_per_year": 100.0,
        "cenarios": {"cenario_b": {"trades_per_year_by_path": {"0": 50.0, "1": 60.0}}},
    }
    out = f2.e2_prereq_configuracoes_viaveis_orcamento(orcamento)
    assert out["cenarios"]["cenario_b"]["cenario_totalmente_viavel"] is True
    assert out["cenarios"]["cenario_b"]["n_paths_viaveis"] == 2


def test_configuracoes_viaveis_orcamento_nao_finito_e_inviavel() -> None:
    orcamento = {
        "implied_budget_trades_per_year": 100.0,
        "cenarios": {"cenario_c": {"trades_per_year_by_path": {"0": float("nan")}}},
    }
    out = f2.e2_prereq_configuracoes_viaveis_orcamento(orcamento)
    assert out["cenarios"]["cenario_c"]["paths_inviaveis"] == ["0"]
