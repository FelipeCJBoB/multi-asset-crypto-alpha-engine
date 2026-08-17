"""Testes de `src/monitoring/dollar_bar_drift.py` -- MECANISMO do alarme de
deriva de `threshold_usdt` (AG-042, Opção A′, item 2/3, `audit/
architecture_gaps_log.yaml`).

`evaluate_drift` é pura (sem IO) -- cobertura direta com números fixos,
inclusive os REAIS já medidos hoje (`experiments/dollar_threshold_drift.
json`, BTCUSDT `drift_ratio=18,18x` entre `2020_h1` e `etf`). `measure_new_
window_drift` tem IO mockado na fronteira (`src.data._chunked_scan.scan_
trades_totals`/`query_baseline`), mesmo padrão de `tests/unit/test_data_
build_dollar_bars.py`."""

from __future__ import annotations

import polars as pl
import pytest

from src.data import _chunked_scan
from src.data.build_dollar_bars import DollarBarCalibration
from src.monitoring import dollar_bar_drift
from src.monitoring._constants import load_constant as load_monitoring_constant

# Números REAIS medidos 2026-08-16 (experiments/dollar_threshold_drift.json,
# drift_summary, symbol=BTCUSDT) -- não arbitrários.
_BTCUSDT_REAL_MIN_DOLLAR_PER_DAY = 1_398_680_510.07  # janela 2020_h1
_BTCUSDT_REAL_MAX_DOLLAR_PER_DAY = 25_426_001_467.08  # janela etf
_BTCUSDT_REAL_DRIFT_RATIO = 18.1786  # drift_summary.drift_ratio, mesmo símbolo


def _baseline(
    *, symbol: str = "BTCUSDT", threshold_usdt: float = 1_000_000.0
) -> DollarBarCalibration:
    return DollarBarCalibration(
        symbol=symbol,
        resolution_id="R1",
        threshold_usdt=threshold_usdt,
        calibration_scope="validation",
        calibration_window_start="2024-01-01",
        calibration_window_end="2024-01-31",
        n_trades=1_000,
        calibrated_at="2024-01-01T00:00:00+00:00",
    )


# ============================================================================
# evaluate_drift -- função pura
# ============================================================================


def test_evaluate_drift_baixo_nao_dispara() -> None:
    baseline = _baseline(threshold_usdt=1_000_000.0)
    result = dollar_bar_drift.evaluate_drift(
        baseline,
        new_window_start="2026-01-01",
        new_window_end="2026-01-31",
        new_window_n_trades=500,
        new_window_total_dollar=1_050_000_000.0,
        new_window_threshold_usdt=1_050_000.0,  # 1,05x -- deriva pequena
        alarm_threshold_ratio=3.0,
    )
    assert result.drift_ratio == pytest.approx(1.05)
    assert result.alarm_triggered is False


def test_evaluate_drift_alto_dispara() -> None:
    baseline = _baseline(threshold_usdt=1_000_000.0)
    result = dollar_bar_drift.evaluate_drift(
        baseline,
        new_window_start="2026-01-01",
        new_window_end="2026-01-31",
        new_window_n_trades=500,
        new_window_total_dollar=5_000_000_000.0,
        new_window_threshold_usdt=5_000_000.0,  # 5x -- deriva grande
        alarm_threshold_ratio=3.0,
    )
    assert result.drift_ratio == pytest.approx(5.0)
    assert result.alarm_triggered is True


def test_evaluate_drift_borda_limiar_exato_nao_dispara() -> None:
    """Regra do módulo: dispara se drift_ratio > alarm_threshold_ratio --
    estritamente maior. No limiar EXATO, não dispara."""
    baseline = _baseline(threshold_usdt=1_000.0)
    result = dollar_bar_drift.evaluate_drift(
        baseline,
        new_window_start="2026-01-01",
        new_window_end="2026-01-31",
        new_window_n_trades=100,
        new_window_total_dollar=2_000_000.0,
        new_window_threshold_usdt=2_000.0,  # exatamente 2,0x
        alarm_threshold_ratio=2.0,
    )
    assert result.drift_ratio == pytest.approx(2.0)
    assert result.alarm_triggered is False


def test_evaluate_drift_logo_acima_do_limiar_dispara() -> None:
    """Complementa o teste de borda: um tiquinho acima do limiar exato já
    dispara -- prova que a fronteira é `>`, não um bug de folga."""
    baseline = _baseline(threshold_usdt=1_000.0)
    result = dollar_bar_drift.evaluate_drift(
        baseline,
        new_window_start="2026-01-01",
        new_window_end="2026-01-31",
        new_window_n_trades=100,
        new_window_total_dollar=2_000_001.0,
        new_window_threshold_usdt=2_000.001,  # 2,000001x -- logo acima de 2,0x
        alarm_threshold_ratio=2.0,
    )
    assert result.drift_ratio > 2.0
    assert result.alarm_triggered is True


def test_evaluate_drift_e_simetrico_por_direcao() -> None:
    """`drift_ratio` mede MAGNITUDE, não direção -- baseline maior que a
    janela nova produz o mesmo `drift_ratio` que o inverso."""
    baseline_alto = _baseline(threshold_usdt=5_000_000.0)
    resultado_queda = dollar_bar_drift.evaluate_drift(
        baseline_alto,
        new_window_start="2026-01-01",
        new_window_end="2026-01-31",
        new_window_n_trades=100,
        new_window_total_dollar=1_000_000.0,
        new_window_threshold_usdt=1_000_000.0,  # caiu 5x em relação ao baseline
        alarm_threshold_ratio=3.0,
    )
    baseline_baixo = _baseline(threshold_usdt=1_000_000.0)
    resultado_alta = dollar_bar_drift.evaluate_drift(
        baseline_baixo,
        new_window_start="2026-01-01",
        new_window_end="2026-01-31",
        new_window_n_trades=100,
        new_window_total_dollar=5_000_000.0,
        new_window_threshold_usdt=5_000_000.0,  # subiu 5x em relação ao baseline
        alarm_threshold_ratio=3.0,
    )
    assert resultado_queda.drift_ratio == pytest.approx(resultado_alta.drift_ratio)
    assert resultado_queda.alarm_triggered is True
    assert resultado_alta.alarm_triggered is True


def test_evaluate_drift_btcusdt_real_18_18x_dispara() -> None:
    """Números REAIS medidos 2026-08-16 (`experiments/dollar_threshold_
    drift.json`, `drift_summary`, BTCUSDT `2020_h1` vs `etf`,
    `drift_ratio=18,18x`) -- não um número arbitrário. `dollar_per_day` das
    duas janelas usado diretamente como proxy do threshold recalibrado
    (mesma justificativa de proporcionalidade documentada em `tools/
    diagnostics/measure_dollar_threshold_drift.py`: `target_n_bars` é
    ~fixo entre janelas de duração parecida, então a razão de densidade é
    a mesma razão que o threshold recalibrado teria). Usa o limiar REAL de
    `constants.yaml` (`dollar_bar_drift_alarm_ratio_max`, não um override
    de teste) -- prova que a magnitude real medida dispara o alarme com o
    valor de fato declarado em produção."""
    baseline = _baseline(threshold_usdt=_BTCUSDT_REAL_MIN_DOLLAR_PER_DAY)
    result = dollar_bar_drift.evaluate_drift(
        baseline,
        new_window_start="2024-03-01",
        new_window_end="2024-03-31",
        new_window_n_trades=66_512_993,  # n_ticks real da janela etf, BTCUSDT
        new_window_total_dollar=788_206_045_479.3694,  # total_dollar real da janela etf
        new_window_threshold_usdt=_BTCUSDT_REAL_MAX_DOLLAR_PER_DAY,
    )
    assert result.drift_ratio == pytest.approx(_BTCUSDT_REAL_DRIFT_RATIO, rel=1e-4)
    alarm_threshold_ratio = float(load_monitoring_constant("dollar_bar_drift_alarm_ratio_max"))
    assert result.alarm_threshold_ratio == pytest.approx(alarm_threshold_ratio)
    # sweep_range declarado em constants.yaml (1.5-10.0) fica bem abaixo de
    # 18,18x -- a asserção abaixo falharia de forma auditável (não
    # silenciosa) se o Manager um dia mudar o limiar para acima da deriva
    # real já medida, o que seria uma escolha que esvazia o alarme.
    assert result.drift_ratio > alarm_threshold_ratio
    assert result.alarm_triggered is True


def test_evaluate_drift_baseline_threshold_invalido_levanta() -> None:
    with pytest.raises(ValueError, match=r"baseline\.threshold_usdt"):
        dollar_bar_drift.evaluate_drift(
            _baseline(threshold_usdt=0.0),
            new_window_start="2026-01-01",
            new_window_end="2026-01-31",
            new_window_n_trades=1,
            new_window_total_dollar=1.0,
            new_window_threshold_usdt=1.0,
        )


def test_evaluate_drift_new_window_threshold_invalido_levanta() -> None:
    with pytest.raises(ValueError, match="new_window_threshold_usdt"):
        dollar_bar_drift.evaluate_drift(
            _baseline(),
            new_window_start="2026-01-01",
            new_window_end="2026-01-31",
            new_window_n_trades=1,
            new_window_total_dollar=0.0,
            new_window_threshold_usdt=-1.0,
        )


def test_evaluate_drift_alarm_threshold_ratio_invalido_levanta() -> None:
    with pytest.raises(ValueError, match="dollar_bar_drift_alarm_ratio_max"):
        dollar_bar_drift.evaluate_drift(
            _baseline(threshold_usdt=1_000.0),
            new_window_start="2026-01-01",
            new_window_end="2026-01-31",
            new_window_n_trades=1,
            new_window_total_dollar=1_000.0,
            new_window_threshold_usdt=1_000.0,
            alarm_threshold_ratio=1.0,  # <= 1.0 dispararia sempre -- rejeitado
        )


def test_evaluate_drift_le_limiar_de_constants_yaml_por_default() -> None:
    """Sem `alarm_threshold_ratio` explícito, o default vem de
    `constants.yaml` (`dollar_bar_drift_alarm_ratio_max`) -- não um
    literal escondido em código (Regra Zero)."""
    baseline = _baseline(threshold_usdt=1_000.0)
    result = dollar_bar_drift.evaluate_drift(
        baseline,
        new_window_start="2026-01-01",
        new_window_end="2026-01-31",
        new_window_n_trades=1,
        new_window_total_dollar=1_100.0,
        new_window_threshold_usdt=1_100.0,
    )
    expected = float(load_monitoring_constant("dollar_bar_drift_alarm_ratio_max"))
    assert result.alarm_threshold_ratio == pytest.approx(expected)


# ============================================================================
# measure_new_window_drift -- IO mockado na fronteira (_chunked_scan)
# ============================================================================


def test_measure_new_window_drift_reusa_chunked_scan(monkeypatch: pytest.MonkeyPatch) -> None:
    """`measure_new_window_drift` mede via `_chunked_scan.scan_trades_
    totals`/`query_baseline`/`target_n_bars` -- mesma fórmula de
    `src.data.build_dollar_bars.calibrate_dollar_threshold_for_validation`
    (`threshold = total_dollar/target_n_bars`). IO mockado na fronteira,
    mesmo padrão de `test_data_build_dollar_bars.py`."""
    fake_totals = _chunked_scan.TradesTotals(
        total_dollar=1_000_000.0, total_volume=10_000.0, n_ticks=500
    )
    monkeypatch.setattr(_chunked_scan, "scan_trades_totals", lambda *a, **k: fake_totals)
    monkeypatch.setattr(
        _chunked_scan,
        "query_baseline",
        lambda *a, **k: pl.DataFrame({"close": [1.0] * 10}),
    )

    baseline = _baseline(threshold_usdt=50_000.0)  # 1.000.000/20 no baseline original
    result = dollar_bar_drift.measure_new_window_drift(
        baseline, "2026-01-01", "2026-01-07", alarm_threshold_ratio=3.0
    )

    # target_n_bars = 10 (altura do baseline fake) -> threshold novo = 1_000_000/10 = 100_000
    assert result.new_window_threshold_usdt == pytest.approx(100_000.0)
    assert result.new_window_n_trades == 500
    assert result.new_window_total_dollar == pytest.approx(1_000_000.0)
    assert result.drift_ratio == pytest.approx(2.0)  # 100_000/50_000
    assert result.alarm_triggered is False  # 2.0 <= 3.0


def test_measure_new_window_drift_sem_trades_levanta_erro(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        _chunked_scan,
        "scan_trades_totals",
        lambda *a, **k: _chunked_scan.TradesTotals(),
    )
    with pytest.raises(ValueError, match="aggTrades vazio"):
        dollar_bar_drift.measure_new_window_drift(_baseline(), "2026-01-01", "2026-01-07")
