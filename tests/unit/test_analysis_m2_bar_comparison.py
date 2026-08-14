"""Testes de `src/analysis/m2_bar_comparison.py` -- núcleo puro
(`compute_bar_statistics`), sem IO real (`compute_bar_comparison_for_symbol`/
`run_and_save_bar_comparison_report` fazem IO real via `lake.query_bars`/
`lake.query_agg_trades`, não exercitados aqui — mesma convenção de M1/M3/M6
sobre funções orquestradoras com IO). JB/Ljung-Box/ADF vêm de scipy/
statsmodels (bibliotecas de terceiros testadas fora deste repo) — o que
vale testar aqui é a ORQUESTRAÇÃO: amostra pequena não crasha, tipos/faixas
saem sãos em amostra grande, e a reutilização de `compute_concurrency_and_
uniqueness` está corretamente calibrada (t0/t1), não uma reimplementação
das próprias fórmulas estatísticas."""

from __future__ import annotations

import math

import polars as pl
import pytest

from src.analysis.m2_bar_comparison import compute_bar_statistics


def _bars(*, close: list[float], close_time: list[int]) -> pl.DataFrame:
    n = len(close)
    assert len(close_time) == n
    return pl.DataFrame({"close": close, "close_time": close_time})


def test_amostra_pequena_devolve_nan_sem_levantar() -> None:
    bars = _bars(close=[100.0, 101.0, 99.0, 102.0, 98.0], close_time=list(range(5)))
    metrics = compute_bar_statistics(
        "BTCUSDT", "time", bars, time_stop_ms=1_000, ljung_box_lags=10
    )

    assert metrics.n_bars == 5
    assert metrics.n_returns == 4
    assert math.isnan(metrics.jarque_bera_pvalue)
    assert math.isnan(metrics.ljung_box_r_pvalue)
    assert math.isnan(metrics.adf_pvalue)
    assert math.isnan(metrics.avg_uniqueness)


def test_amostra_grande_produz_valores_finitos_e_em_faixa_valida() -> None:
    # sequencia pseudo-variavel determinística (sem RNG) -- só precisa de
    # variância real, não de aleatoriedade de verdade.
    close = [100.0 + 0.5 * ((i * 37) % 11) for i in range(101)]
    close_time = list(range(101))
    bars = _bars(close=close, close_time=close_time)

    metrics = compute_bar_statistics(
        "BTCUSDT", "dollar", bars, time_stop_ms=1_000, ljung_box_lags=10
    )

    assert metrics.n_bars == 101
    assert metrics.n_returns == 100
    assert not math.isnan(metrics.jarque_bera_pvalue)
    assert not math.isnan(metrics.kurtosis_excess)
    assert not math.isnan(metrics.ljung_box_r_pvalue)
    assert not math.isnan(metrics.ljung_box_r2_pvalue)
    assert not math.isnan(metrics.adf_pvalue)
    assert not math.isnan(metrics.avg_uniqueness)
    assert 0.0 <= metrics.jarque_bera_pvalue <= 1.0
    assert 0.0 <= metrics.ljung_box_r_pvalue <= 1.0
    assert 0.0 <= metrics.ljung_box_r2_pvalue <= 1.0
    assert 0.0 <= metrics.adf_pvalue <= 1.0
    assert 0.0 < metrics.avg_uniqueness <= 1.0


def test_avg_uniqueness_e_um_quando_janelas_de_time_stop_nao_se_sobrepoem() -> None:
    """close_time bem espaçados (1_000_000ms) contra um time_stop pequeno
    (100ms) -> nenhuma janela [close_time, close_time+time_stop) cobre a
    próxima barra -- concorrência 1 em toda posição, uniqueness exato 1.0
    (comportamento já garantido por `compute_concurrency_and_uniqueness`,
    aqui só confirmando que t0/t1 foram passados na conta certa)."""
    n = 50
    close = [100.0 + 0.5 * ((i * 37) % 11) for i in range(n)]
    close_time = [i * 1_000_000 for i in range(n)]
    bars = _bars(close=close, close_time=close_time)

    metrics = compute_bar_statistics(
        "BTCUSDT", "tick_imbalance", bars, time_stop_ms=100, ljung_box_lags=10
    )

    assert metrics.avg_uniqueness == pytest.approx(1.0)
