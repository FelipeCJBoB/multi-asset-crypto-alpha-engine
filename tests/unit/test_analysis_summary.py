"""Testes de `src/analysis/summary.py` — `build_summary_markdown` (função
pura) e `write_latest_summary_atomic` (IO, B29)."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import orjson
import pytest

from src.analysis import summary as smy
from src.analysis.summary import DEFAULT_REPORT_PATH
from src.core.metric import Metric, Unit


def _metric_json(value: float | None, *, unit: str, n: int = 100, valid: bool = True) -> dict:
    return {
        "value": value,
        "unit": unit,
        "n": n,
        "n_semantics": "trades",
        "source": "test",
        "valid": valid,
        "invalid_reason": None if valid else "denominador <= 0",
    }


def _fake_report() -> dict[str, Any]:
    return {
        "sprint": 8,
        "symbol": "BTCUSDT",
        "schema_version": 1,
        "n_cpcv_splits": 15,
        "decomposition_pnl": {
            "pooled_all_15_splits": {
                "pnl_total": _metric_json(-10.30, unit="fraction_of_notional", n=1000),
                "pnl_direcional": _metric_json(7.89, unit="fraction_of_notional", n=1000),
                "pnl_carry": _metric_json(2.86, unit="fraction_of_notional", n=1000),
                "pnl_execucao": _metric_json(-21.06, unit="fraction_of_notional", n=1000),
                "total_sharpe": _metric_json(-1.138, unit="sharpe_annualized", n=1000),
                "directional_sharpe": _metric_json(0.879, unit="sharpe_annualized", n=1000),
                "carry_share": _metric_json(None, unit="ratio", n=1000, valid=False),
            }
        },
        "hhi": {
            "mean_hhi": 0.1096,
            "mean_hhi_effective": 0.1911,
            "mean_max_share": 0.1679,
            "gate3_4_hhi_lt_025": True,
            "gate3_4_max_share_lt_030": True,
        },
        "baselines": {
            "b1_random_entry": {
                "percentile_of_alpha": 100.0,
                "n_seeds": 1000,
                "sample_size": 7308,
            }
        },
        "layer1_vs_layer0": {
            "n_paths_camada1_supera_camada0": 5,
            "n_paths_total": 5,
            "min_paths_required": 4,
            "permanence_pass": True,
        },
    }


# ============================================================================
# _metric_from_json / _fmt_metric
# ============================================================================


def test_metric_from_json_reconstroi_valido() -> None:
    original = Metric(
        value=0.05, unit=Unit.RATIO, n=10, n_semantics="trades", source="s", valid=True
    )
    d = original.to_json()
    rebuilt = smy._metric_from_json(d)
    assert rebuilt == original


def test_metric_from_json_value_none_vira_nan() -> None:
    d = _metric_json(None, unit="ratio", valid=False)
    m = smy._metric_from_json(d)
    assert math.isnan(m.value)
    assert m.valid is False


def test_fmt_metric_bps_per_trade() -> None:
    d = _metric_json(-10.0, unit="fraction_of_notional", n=1000)
    assert smy._fmt_metric(d, as_bps_per_trade=True) == "-100.00 bps/trade"


def test_fmt_metric_nao_computavel_mostra_motivo() -> None:
    d = _metric_json(None, unit="ratio", valid=False)
    out = smy._fmt_metric(d, as_bps_per_trade=False)
    assert out.startswith("não computável (")
    assert "denominador <= 0" in out


# ============================================================================
# build_summary_markdown — função pura
# ============================================================================


def test_build_summary_markdown_contem_numeros_manchete_em_bps() -> None:
    md = smy.build_summary_markdown(_fake_report())
    assert "Sprint 8, BTCUSDT" in md
    assert "1000 trades, 15 splits" in md
    # -10.30 (fração somada crua) convertido pra -103.00 bps/trade, não
    # exibido cru -- é exatamente a conversão manual que motivou per_unit().
    assert "-103.00 bps/trade" in md
    assert "-10.30" not in md


def test_build_summary_markdown_carry_share_invalido_mostra_nao_computavel() -> None:
    md = smy.build_summary_markdown(_fake_report())
    assert "não computável" in md


def test_build_summary_markdown_permanence_pass_aparece_como_passa() -> None:
    md = smy.build_summary_markdown(_fake_report())
    assert "5 de 5 caminhos" in md
    assert "PASSA" in md


def test_build_summary_markdown_gate_hhi_abaixo_do_teto_mostra_ok() -> None:
    md = smy.build_summary_markdown(_fake_report())
    assert "0,25 OK" in md
    assert "0,30 OK" in md


def test_build_summary_markdown_tem_generated_at_e_code_version() -> None:
    md = smy.build_summary_markdown(_fake_report())
    assert "Gerado em" in md
    assert "commit `" in md


# ============================================================================
# write_latest_summary_atomic — IO, B29
# ============================================================================


def test_write_latest_summary_atomic_tmp_nao_sobrevive(tmp_path: Path) -> None:
    dest = tmp_path / "latest_summary.md"
    result = smy.write_latest_summary_atomic(_fake_report(), dest_path=dest)
    assert result == dest
    assert dest.exists()
    assert not dest.with_name(dest.name + ".tmp").exists()
    assert "PASSA" in dest.read_text(encoding="utf-8")


def test_write_latest_summary_atomic_le_relatorio_do_disco_quando_nao_passado(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "alpha_layer1_report.json"
    report_path.write_bytes(orjson.dumps(_fake_report()))
    dest = tmp_path / "latest_summary.md"

    result = smy.write_latest_summary_atomic(report_path=report_path, dest_path=dest)

    assert result == dest
    assert "Sprint 8, BTCUSDT" in dest.read_text(encoding="utf-8")


@pytest.mark.integration
def test_write_latest_summary_atomic_contra_relatorio_real(tmp_path: Path) -> None:
    if not DEFAULT_REPORT_PATH.exists():
        pytest.skip("experiments/alpha_layer1_report.json ausente")
    dest = tmp_path / "latest_summary.md"
    result = smy.write_latest_summary_atomic(dest_path=dest)
    text = result.read_text(encoding="utf-8")
    assert "bps/trade" in text
    assert "Gerado em" in text
