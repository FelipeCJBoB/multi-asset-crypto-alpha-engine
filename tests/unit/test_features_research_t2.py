"""Testes de `research/research_t2.py` — cobertura focada em bugs
reais já encontrados (K03 is_weekend, regressão travada) e nas primitivas
genéricas novas (`log_return_n`/`rolling_corr`) que `support.py` não
tinha. Não é cobertura exaustiva das ~70 candidatas (research-pass, ver
docstring do módulo) — os grupos inteiros já foram verificados manualmente
contra dado real (2024, `n_finite` plausível em todas as colunas)."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import polars as pl
import pytest

from research import research_t2 as r2


def test_log_return_n_causal_e_correto() -> None:
    close = np.array([100.0, 101.0, 102.0, 104.0, 108.0])
    out = r2.log_return_n(close, 2)
    assert np.isnan(out[0])
    assert np.isnan(out[1])
    assert out[2] == pytest.approx(np.log(102.0 / 100.0))
    assert out[4] == pytest.approx(np.log(108.0 / 102.0))


def test_log_return_n_janela_maior_que_serie_da_tudo_nan() -> None:
    close = np.array([100.0, 101.0])
    out = r2.log_return_n(close, 5)
    assert np.all(np.isnan(out))


def test_rolling_corr_recupera_correlacao_perfeita() -> None:
    rng = np.random.default_rng(42)
    x = rng.normal(size=200)
    y = 2.0 * x + 3.0  # correlação perfeita, escala/deslocamento não importam
    out = r2.rolling_corr(x, y, 20)
    tail = out[~np.isnan(out)]
    assert tail.size > 0
    assert np.allclose(tail, 1.0, atol=1e-6)


def test_rolling_corr_recupera_correlacao_negativa() -> None:
    rng = np.random.default_rng(7)
    x = rng.normal(size=200)
    y = -1.5 * x
    out = r2.rolling_corr(x, y, 20)
    tail = out[~np.isnan(out)]
    assert np.allclose(tail, -1.0, atol=1e-6)


# ============================================================================
# K03 is_weekend — regressão travada. Bug real encontrado nesta rodada:
# a convenção de day_of_week desta implementação é 0=domingo/6=sábado
# (verificado contra 1970-01-01=quinta-feira), mas o check original usava
# {5,6} (sexta/sábado) -- fim de semana teria ficado deslocado 1 dia pra
# trás em TODA a série sem este teste.
# ============================================================================


def _ms(dt: datetime) -> float:
    return dt.timestamp() * 1000


def test_k03_is_weekend_sabado_e_domingo_marcados_sexta_nao() -> None:
    friday = datetime(2024, 1, 5, 12, 0, tzinfo=UTC)  # sexta-feira
    saturday = datetime(2024, 1, 6, 12, 0, tzinfo=UTC)  # sábado
    sunday = datetime(2024, 1, 7, 12, 0, tzinfo=UTC)  # domingo
    monday = datetime(2024, 1, 8, 12, 0, tzinfo=UTC)  # segunda-feira
    ts = np.array([_ms(friday), _ms(saturday), _ms(sunday), _ms(monday)])
    out = r2.group_k_research(ts)
    assert out["K03_is_weekend"].tolist() == [0.0, 1.0, 1.0, 0.0]


def test_k01_hour_sin_cos_ciclo_completo() -> None:
    midnight = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
    noon = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
    ts = np.array([_ms(midnight), _ms(noon)])
    out = r2.group_k_research(ts)
    assert out["K01_hour_sin"][0] == pytest.approx(0.0, abs=1e-9)
    assert out["K01_hour_cos"][0] == pytest.approx(1.0, abs=1e-9)
    assert out["K01_hour_cos"][1] == pytest.approx(-1.0, abs=1e-9)


def test_k08_days_since_halving_zero_antes_do_primeiro_halving() -> None:
    before_first_halving = datetime(2010, 1, 1, tzinfo=UTC)
    ts = np.array([_ms(before_first_halving)])
    out = r2.group_k_research(ts)
    assert np.isnan(out["K08_days_since_halving"][0])


def test_k08_days_since_halving_positivo_depois_de_2024() -> None:
    after_2024_halving = datetime(2024, 5, 1, tzinfo=UTC)
    ts = np.array([_ms(after_2024_halving)])
    out = r2.group_k_research(ts)
    assert out["K08_days_since_halving"][0] > 0
    assert out["K08_days_since_halving"][0] < 15  # 2024-04-20 -> 2024-05-01 = 11 dias


# ============================================================================
# Grupos A/B/D — smoke test sobre fixture sintética mínima (causalidade
# básica: primeiras barras NaN, sem erro de execução).
# ============================================================================


def _synthetic_bars(n: int = 200) -> pl.DataFrame:
    rng = np.random.default_rng(3)
    base = 100.0 + np.cumsum(rng.normal(scale=0.5, size=n))
    open_time = [1_700_000_000_000 + i * 900_000 for i in range(n)]
    close_time = [t + 900_000 - 1 for t in open_time]
    high = base + np.abs(rng.normal(scale=0.3, size=n))
    low = base - np.abs(rng.normal(scale=0.3, size=n))
    open_ = base + rng.normal(scale=0.1, size=n)
    volume = np.abs(rng.normal(loc=100, scale=10, size=n))
    quote_volume = volume * base
    taker_buy_volume = volume * rng.uniform(0.3, 0.7, size=n)
    count = rng.integers(50, 500, size=n).astype(float)
    return pl.DataFrame(
        {
            "open_time": open_time,
            "close_time": close_time,
            "open": open_,
            "high": high,
            "low": low,
            "close": base,
            "volume": volume,
            "quote_volume": quote_volume,
            "taker_buy_volume": taker_buy_volume,
            "count": count,
        }
    )


def test_group_a_research_roda_sem_erro_e_warmup_correto() -> None:
    bars = _synthetic_bars()
    close = bars["close"].cast(pl.Float64).to_numpy()
    atr_pct = np.full(close.shape[0], 0.01)
    out = r2.group_a_research(bars, atr_pct)
    assert np.isnan(out["A01_log_return_1"][0])
    assert np.isfinite(out["A01_log_return_1"][-1])
    assert out["A07_body_ratio"].shape[0] == close.shape[0]


def test_group_b_research_roda_sem_erro() -> None:
    bars = _synthetic_bars()
    close = bars["close"].cast(pl.Float64).to_numpy()
    atr_abs = np.full(close.shape[0], 1.0)
    out = r2.group_b_research(bars, atr_abs)
    assert np.isfinite(out["B02_rsi_48"][-1])
    assert np.isfinite(out["B10_stoch_k_14"][-1])


def test_group_d_research_roda_sem_erro() -> None:
    bars = _synthetic_bars()
    out = r2.group_d_research(bars, order_flow_imb_1m_agg=None)
    assert np.isfinite(out["D05f_taker_buy_ratio"][-1])
    assert "D07f_taker_imbalance_1m_agg" not in out  # deferida, não computada
