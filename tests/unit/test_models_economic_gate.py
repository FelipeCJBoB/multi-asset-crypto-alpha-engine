"""Testes do núcleo de decisão do gate econômico (`src.models.economic_gate`).

Cobre o que passou a viver em `models/` no split de 2026-08-27
(`/redesign_workflow`, AG-260 ponto (b)): `evaluate_economic_gate`/
`load_min_alpha_lift_by_combo` (movidos de `src.analysis.economic_gate`,
mesmo comportamento -- moveram porque estavam prestes a virar insumo real
de treino, e `analysis/` nunca pode ser isso, `CLAUDE.md` Layer hierarchy)
e os dois pontos novos do orquestrador de trial soft-flag,
`lookup_pre_trial_gate`/`suggested_n_lifetime_delta`.

A derivação da tabela a partir do sweep S1 (`build_gate_rows`/`_gate_yaml`/
`best_per_combo`) continua em `src.analysis.economic_gate` e testada em
`tests/unit/test_economic_gate.py` -- só é usada aqui pro round-trip real
do YAML (`analysis` pode importar `models`, nunca o contrário)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.analysis import economic_gate as analysis_eg
from src.models import economic_gate as eg

# ============================================================================
# evaluate_economic_gate / load_min_alpha_lift_by_combo
# ============================================================================


def _threshold(
    breakeven_wr: float, *, side: str = "long", symbol: str = "X", resolution_id: str = "R1"
) -> eg.GateRow:
    return eg.GateRow(
        symbol=symbol,
        resolution_id=resolution_id,
        side=side,
        cell_id="c",
        tp_atr_mult=1.5,
        sl_atr_mult=1.5,
        n_filled=1,
        atr_median_bps=30.0,
        p_tp=0.47,
        breakeven_wr=breakeven_wr,
        required_lift=breakeven_wr / 0.47,
        required_lift_stderr=0.001,
        required_lift_ci95_low=0.0,
        required_lift_ci95_high=1.0,
    )


def test_evaluate_economic_gate_passa_e_e_distinguivel_com_margem_grande() -> None:
    verdict = eg.evaluate_economic_gate(0.65, 50_000, _threshold(0.55), side="long")
    assert verdict.passes is True
    assert verdict.distinguishable is True
    assert verdict.margin == pytest.approx(0.10)
    assert verdict.side_matches_threshold is True


def test_evaluate_economic_gate_passa_mas_nao_e_distinguivel_com_margem_pequena_e_n_baixo() -> None:
    """`passes` (naive) e `distinguishable` podem DIVERGIR -- é exatamente
    o ponto do módulo (`AG-246`): margem positiva mas pequena, com amostra
    pequena, não é evidência suficiente pra um gate binding."""
    verdict = eg.evaluate_economic_gate(0.551, 50, _threshold(0.55), side="long")
    assert verdict.passes is True
    assert verdict.distinguishable is False


def test_evaluate_economic_gate_nao_passa_quando_abaixo_do_breakeven() -> None:
    verdict = eg.evaluate_economic_gate(0.50, 50_000, _threshold(0.55), side="long")
    assert verdict.passes is False
    assert verdict.distinguishable is False
    assert verdict.margin < 0.0


def test_evaluate_economic_gate_sinaliza_lado_trocado() -> None:
    verdict = eg.evaluate_economic_gate(
        0.65, 50_000, _threshold(0.55, side="short"), side="long"
    )
    assert verdict.side_matches_threshold is False
    # breakeven_wr continua o numero certo -- so o lado gravado diverge
    assert verdict.breakeven_wr == pytest.approx(0.55)


@pytest.mark.parametrize("p_tp", [0.0, -0.1])
def test_evaluate_economic_gate_levanta_com_candidate_p_tp_nao_positivo(p_tp: float) -> None:
    with pytest.raises(eg.EconomicGateError, match="não é positivo"):
        eg.evaluate_economic_gate(p_tp, 100, _threshold(0.55), side="long")


@pytest.mark.parametrize("n", [0, -5])
def test_evaluate_economic_gate_levanta_com_n_candidate_nao_positivo(n: int) -> None:
    with pytest.raises(eg.EconomicGateError, match="não é positivo"):
        eg.evaluate_economic_gate(0.6, n, _threshold(0.55), side="long")


def _write_min_alpha_lift_yaml(path: Path) -> None:
    path.write_text(
        "min_alpha_lift_ptp:\n"
        "  BTCUSDT_R1:\n"
        "    value: 1.1216\n"
        "    stderr: 0.0025\n"
        "    ci95: [1.1166, 1.1266]\n"
        "    geometria_otima: R1_S9/4\n"
        "    side: short\n"
        "    tp_atr_mult: 2.25\n"
        "    sl_atr_mult: 2.25\n"
        "    p_tp_base: 0.4890\n"
        "    breakeven_wr: 0.5484\n"
        "    atr_median_bps: 24.46\n"
        "    n_filled: 161707\n",
        encoding="utf-8",
    )


def test_load_min_alpha_lift_by_combo_reconstroi_gaterow(tmp_path: Path) -> None:
    path = tmp_path / "min_alpha_lift_by_combo.yaml"
    _write_min_alpha_lift_yaml(path)
    table = eg.load_min_alpha_lift_by_combo(path)
    row = table[("BTCUSDT", "R1")]
    assert row.side == "short"
    assert row.breakeven_wr == pytest.approx(0.5484)
    assert row.required_lift == pytest.approx(1.1216)
    assert row.n_filled == 161707


def test_load_min_alpha_lift_by_combo_arquivo_ausente_levanta(tmp_path: Path) -> None:
    with pytest.raises(eg.EconomicGateError, match="não encontrado"):
        eg.load_min_alpha_lift_by_combo(tmp_path / "nao_existe.yaml")


def test_load_min_alpha_lift_by_combo_entrada_malformada_levanta(tmp_path: Path) -> None:
    path = tmp_path / "min_alpha_lift_by_combo.yaml"
    path.write_text(
        "min_alpha_lift_ptp:\n  BTCUSDT_R1:\n    value: 1.1\n",  # faltam campos
        encoding="utf-8",
    )
    with pytest.raises(eg.EconomicGateError, match="malformada"):
        eg.load_min_alpha_lift_by_combo(path)


def _s1_report(p_tp: float, breakeven: float, *, n_filled: int = 100_000) -> dict[str, Any]:
    return {
        "by_symbol": {
            "BTCUSDT": {
                "by_side": {
                    "long": {
                        "atr_median_side": 0.0030,
                        "cells": {
                            "R1_S3/2": {
                                "tp_atr_mult": 1.5,
                                "sl_atr_mult": 1.5,
                                "n_filled": n_filled,
                                "frac_tp": p_tp,
                                "breakeven_wr_cost_adjusted": breakeven,
                            }
                        },
                    }
                }
            }
        }
    }


def test_load_min_alpha_lift_by_combo_gate_yaml_real_e_reconstruido_bit_exato(
    tmp_path: Path,
) -> None:
    """Round-trip real: `analysis_eg._gate_yaml` escreve (usa `GateRow`
    reexportado de `models.economic_gate`), `eg.load_min_alpha_lift_by_combo`
    lê de volta -- os dois lados do write-only viram um par testado."""
    report = _s1_report(0.4724, 0.5501)
    rows = analysis_eg.build_gate_rows({"R1": report})
    yaml_text = analysis_eg._gate_yaml(rows, source_version="teste")
    path = tmp_path / "min_alpha_lift_by_combo.yaml"
    path.write_text(yaml_text, encoding="utf-8")
    table = eg.load_min_alpha_lift_by_combo(path)
    best = analysis_eg.best_per_combo(rows)
    assert set(table.keys()) == set(best.keys())
    for key, expected in best.items():
        got = table[key]
        assert got.required_lift == pytest.approx(expected.required_lift)
        assert got.breakeven_wr == pytest.approx(expected.breakeven_wr)
        assert got.side == expected.side


# ============================================================================
# lookup_pre_trial_gate -- ponto de injeção zero-IO (Idioma A, §Núcleo
# funcional do CLAUDE.md). `None` nunca é inventado -- nem no miss, nem no
# retorno.
# ============================================================================


def test_lookup_pre_trial_gate_acha_por_symbol_resolution() -> None:
    row = _threshold(0.55, symbol="BTCUSDT", resolution_id="R1")
    table = {("BTCUSDT", "R1"): row}
    assert eg.lookup_pre_trial_gate("BTCUSDT", "R1", table=table) is row


def test_lookup_pre_trial_gate_devolve_none_em_miss_sem_inventar() -> None:
    table = {("BTCUSDT", "R1"): _threshold(0.55)}
    assert eg.lookup_pre_trial_gate("ETHUSDT", "R2", table=table) is None


def test_lookup_pre_trial_gate_tabela_vazia_e_miss() -> None:
    assert eg.lookup_pre_trial_gate("BTCUSDT", "R1", table={}) is None


# ============================================================================
# suggested_n_lifetime_delta -- só sugere um número pra campo de relatório;
# nunca escreve em audit/n_lifetime.yaml (ledger é mantido à mão).
# ============================================================================


def test_suggested_n_lifetime_delta_1_quando_treinou() -> None:
    assert eg.suggested_n_lifetime_delta(trained=True) == 1


def test_suggested_n_lifetime_delta_0_quando_nao_treinou() -> None:
    assert eg.suggested_n_lifetime_delta(trained=False) == 0
