"""Testes do gate econômico (`src.analysis.economic_gate`).

Cobrem o NÚCLEO PURO — nenhum toca disco. A casca (`run_economic_gate_
report`) é exercida por um teste `integration` separado, com skip-if-ausente
sobre os relatórios S1 reais.

`evaluate_economic_gate`/`load_min_alpha_lift_by_combo` (e `GateRow`/
`EconomicGateError`, que este módulo agora reexporta de `src.models.
economic_gate`) migraram pra `tests/unit/test_models_economic_gate.py` no
split de 2026-08-27 (`/redesign_workflow`) -- mesma razão do split do
módulo em si: viraram insumo de treino, não ficam mais testados junto da
medição pós-hoc."""

from __future__ import annotations

import math
from typing import Any

import pytest

from src.analysis import economic_gate as eg

# ============================================================================
# required_lift
# ============================================================================


def test_required_lift_e_a_razao_breakeven_sobre_p_tp() -> None:
    assert eg.required_lift(0.5, 0.55) == pytest.approx(1.1)


def test_required_lift_igual_a_1_quando_p_tp_ja_cobre_o_custo() -> None:
    """Fronteira econômica: a célula já empata sem nenhum lift do modelo."""
    assert eg.required_lift(0.55, 0.55) == pytest.approx(1.0)


def test_required_lift_menor_que_1_quando_base_supera_o_breakeven() -> None:
    """Não é impossível por construção — significa que a célula é positiva
    sem modelo nenhum. O gate precisa reportar isso, não truncar em 1,0."""
    assert eg.required_lift(0.60, 0.55) < 1.0


@pytest.mark.parametrize("p_tp", [0.0, -0.1])
def test_required_lift_levanta_em_p_tp_nao_positivo(p_tp: float) -> None:
    """Célula sem toque de TP é INDETERMINADA, não 'muito difícil' —
    devolver `inf` a faria ordenar como pior célula em vez de ser rejeitada."""
    with pytest.raises(eg.EconomicGateError, match="não é positivo"):
        eg.required_lift(p_tp, 0.55)


# ============================================================================
# required_lift_stderr
# ============================================================================


def test_stderr_bate_com_a_formula_delta_fechada() -> None:
    p_tp, breakeven, n = 0.47, 0.55, 10_000
    esperado = (breakeven / p_tp) * math.sqrt((1.0 - p_tp) / (p_tp * n))
    assert eg.required_lift_stderr(p_tp, breakeven, n) == pytest.approx(esperado)


def test_stderr_cai_com_raiz_de_n() -> None:
    """Quadruplicar a amostra tem que reduzir o erro à metade."""
    s1 = eg.required_lift_stderr(0.47, 0.55, 10_000)
    s4 = eg.required_lift_stderr(0.47, 0.55, 40_000)
    assert s4 == pytest.approx(s1 / 2.0)


def test_stderr_e_positivo_para_amostra_real() -> None:
    assert eg.required_lift_stderr(0.4724, 0.5501, 215_790) > 0.0


@pytest.mark.parametrize("n_filled", [0, -5])
def test_stderr_levanta_em_amostra_nao_positiva(n_filled: int) -> None:
    with pytest.raises(eg.EconomicGateError, match="não é positivo"):
        eg.required_lift_stderr(0.47, 0.55, n_filled)


# ============================================================================
# is_distinguishable — o ponto do módulo (AG-246)
# ============================================================================


def _row(lift: float, stderr: float) -> eg.GateRow:
    """`GateRow` mínima para testar a comparação — só os dois campos que
    `is_distinguishable` lê importam."""
    return eg.GateRow(
        symbol="X",
        resolution_id="R1",
        side="long",
        cell_id="c",
        tp_atr_mult=1.5,
        sl_atr_mult=1.5,
        n_filled=1,
        atr_median_bps=30.0,
        p_tp=0.5,
        breakeven_wr=0.55,
        required_lift=lift,
        required_lift_stderr=stderr,
        required_lift_ci95_low=lift - stderr,
        required_lift_ci95_high=lift + stderr,
    )


def test_diferenca_grande_e_distinguivel() -> None:
    assert eg.is_distinguishable(_row(1.10, 0.001), _row(1.20, 0.001))


def test_diferenca_de_terceira_casa_com_erro_maior_nao_e_distinguivel() -> None:
    """O caso real que motivou o módulo: R2 vs R1 difere em ~0,003 com
    erro de ~0,004 em cada lado. Ordenar por `<` chamaria isso de vencedor."""
    assert not eg.is_distinguishable(_row(1.1187, 0.0035), _row(1.1216, 0.0025))


def test_is_distinguishable_e_simetrico() -> None:
    a, b = _row(1.10, 0.002), _row(1.13, 0.002)
    assert eg.is_distinguishable(a, b) == eg.is_distinguishable(b, a)


def test_celulas_identicas_nunca_sao_distinguiveis() -> None:
    assert not eg.is_distinguishable(_row(1.10, 0.002), _row(1.10, 0.002))


# ============================================================================
# build_gate_rows / rank_resolutions
# ============================================================================


def _report(p_tp: float, breakeven: float, *, n_filled: int = 100_000) -> dict[str, Any]:
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


def test_build_gate_rows_ordena_por_lift_crescente() -> None:
    rows = eg.build_gate_rows(
        {"R1": _report(0.40, 0.55), "R2": _report(0.50, 0.55), "R3": _report(0.45, 0.55)}
    )
    assert [r.resolution_id for r in rows] == ["R2", "R3", "R1"]


def test_build_gate_rows_converte_atr_para_bps() -> None:
    (row,) = eg.build_gate_rows({"R1": _report(0.50, 0.55)})
    assert row.atr_median_bps == pytest.approx(30.0)


def test_build_gate_rows_levanta_sem_bloco_by_symbol() -> None:
    with pytest.raises(eg.EconomicGateError, match="by_symbol"):
        eg.build_gate_rows({"R1": {"task": "s1"}})


def test_rank_resolutions_marca_vencedor_indistinguivel() -> None:
    """Duas grades com lift quase igual: o vencedor existe na ordenação,
    mas o campo tem que dizer que ele não é separável."""
    rows = eg.build_gate_rows(
        {"R1": _report(0.5000, 0.55), "R2": _report(0.5001, 0.55), "R3": _report(0.40, 0.55)}
    )
    (entrada,) = eg.rank_resolutions(rows)
    assert entrada["vencedor_distinguivel_do_2o"] is False


def test_rank_resolutions_marca_vencedor_distinguivel() -> None:
    rows = eg.build_gate_rows(
        {"R1": _report(0.40, 0.55), "R2": _report(0.52, 0.55), "R3": _report(0.41, 0.55)}
    )
    (entrada,) = eg.rank_resolutions(rows)
    assert entrada["vencedor"] == "R2"
    assert entrada["vencedor_distinguivel_do_2o"] is True


def test_best_per_combo_escolhe_o_menor_lift_da_celula() -> None:
    rows = eg.build_gate_rows({"R1": _report(0.40, 0.55), "R2": _report(0.50, 0.55)})
    best = eg.best_per_combo(rows)
    assert best[("BTCUSDT", "R2")].required_lift < best[("BTCUSDT", "R1")].required_lift


def test_load_s1_reports_levanta_com_caminho_real_se_faltar(tmp_path: Any) -> None:
    """Nunca cair no relatório sem sufixo (grade 15m legada, AG-042)."""
    with pytest.raises(eg.EconomicGateError, match="grade 15m legada"):
        eg.load_s1_reports(out_dir=tmp_path)


# ============================================================================
# find_incumbent_cell_id / recommend_geometry_per_combo
# ============================================================================


def _report_2_sides_2_cells(
    *, p_tp_incumbente: float, p_tp_alternativa: float, n_filled: int = 100_000
) -> dict[str, Any]:
    """Um símbolo, dois lados, duas geometrias — o mínimo para exercitar a
    média entre lados e a comparação contra o incumbente."""

    def _cells() -> dict[str, Any]:
        return {
            "INC": {
                "tp_atr_mult": 1.5,
                "sl_atr_mult": 1.5,
                "n_filled": n_filled,
                "frac_tp": p_tp_incumbente,
                "breakeven_wr_cost_adjusted": 0.55,
            },
            "ALT": {
                "tp_atr_mult": 2.25,
                "sl_atr_mult": 2.25,
                "n_filled": n_filled,
                "frac_tp": p_tp_alternativa,
                "breakeven_wr_cost_adjusted": 0.55,
            },
        }

    return {
        "by_symbol": {
            "BTCUSDT": {
                "by_side": {
                    "long": {"atr_median_side": 0.0030, "cells": _cells()},
                    "short": {"atr_median_side": 0.0030, "cells": _cells()},
                }
            }
        }
    }


def test_find_incumbent_casa_por_valor_nao_por_nome() -> None:
    rows = eg.build_gate_rows(
        {"R1": _report_2_sides_2_cells(p_tp_incumbente=0.47, p_tp_alternativa=0.50)}
    )
    assert eg.find_incumbent_cell_id(rows, tp=1.5, sl=1.5) == "INC"
    assert eg.find_incumbent_cell_id(rows, tp=2.25, sl=2.25) == "ALT"


def test_find_incumbent_levanta_se_producao_nao_esta_no_grid() -> None:
    """Sem baseline medido não há comparação honesta — inventar um seria
    afirmar ganho contra um número que ninguém mediu."""
    rows = eg.build_gate_rows(
        {"R1": _report_2_sides_2_cells(p_tp_incumbente=0.47, p_tp_alternativa=0.50)}
    )
    with pytest.raises(eg.EconomicGateError, match="não existe no grid"):
        eg.find_incumbent_cell_id(rows, tp=9.9, sl=9.9)


def test_recomendacao_aceita_alternativa_quando_ganho_e_grande() -> None:
    rows = eg.build_gate_rows(
        {"R1": _report_2_sides_2_cells(p_tp_incumbente=0.40, p_tp_alternativa=0.50)}
    )
    (rec,) = eg.recommend_geometry_per_combo(rows, incumbent_cell_id="INC")
    assert rec.cell_id == "ALT"
    assert rec.distinguivel_do_incumbente is True
    assert rec.ganho_vs_incumbente > 0.0


def test_recomendacao_marca_indistinguivel_quando_ganho_e_ruido() -> None:
    """O campo que impede trocar geometria (e disparar relabel, B15) por um
    ganho dentro do erro."""
    rows = eg.build_gate_rows(
        {"R1": _report_2_sides_2_cells(p_tp_incumbente=0.5000, p_tp_alternativa=0.5001)}
    )
    (rec,) = eg.recommend_geometry_per_combo(rows, incumbent_cell_id="INC")
    assert rec.distinguivel_do_incumbente is False


def test_recomendacao_usa_media_entre_lados_nao_o_melhor_lado() -> None:
    """Um lado ótimo e outro péssimo na alternativa: a média tem que puxar
    a decisão de volta, senão a geometria otimiza um lado às custas do
    outro (os dois são gerados sob a MESMA geometria)."""
    report = _report_2_sides_2_cells(p_tp_incumbente=0.47, p_tp_alternativa=0.47)
    report["by_symbol"]["BTCUSDT"]["by_side"]["long"]["cells"]["ALT"]["frac_tp"] = 0.60
    report["by_symbol"]["BTCUSDT"]["by_side"]["short"]["cells"]["ALT"]["frac_tp"] = 0.34
    rows = eg.build_gate_rows({"R1": report})
    (rec,) = eg.recommend_geometry_per_combo(rows, incumbent_cell_id="INC")
    # média de lift da ALT (0,55/0,60 e 0,55/0,34) supera a do incumbente
    # (0,55/0,47 nos dois lados) -> a alternativa NÃO deve ser escolhida.
    assert rec.cell_id == "INC"


def test_recomendacao_levanta_sem_o_incumbente_na_celula() -> None:
    rows = eg.build_gate_rows({"R1": _report(0.47, 0.55)})
    with pytest.raises(eg.EconomicGateError, match="incumbente"):
        eg.recommend_geometry_per_combo(rows, incumbent_cell_id="INEXISTENTE")
