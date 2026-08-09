"""Testes de `src/features/groups/*.py` — a fiação de cada feature T1
sobre as primitivas de `support.py`, incluindo a resolução de ambiguidade
de unidade (ATR absoluto vs `atr_20_pct`) documentada em `group_a.py`."""

from __future__ import annotations

import numpy as np
import pytest

from src.features import support
from src.features.groups import group_a, group_b, group_c, group_d, group_e


def _make_ohlcv(n: int, seed: int = 1) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(seed)
    close = 65_000.0 + np.cumsum(rng.normal(0, 80, n))
    high = close + rng.uniform(10, 100, n)
    low = close - rng.uniform(10, 100, n)
    volume = rng.uniform(50, 500, n)
    taker_buy_volume = volume * rng.uniform(0.3, 0.7, n)
    return {
        "close": close,
        "high": high,
        "low": low,
        "volume": volume,
        "taker_buy_volume": taker_buy_volume,
    }


def _log_return_1(close: np.ndarray) -> np.ndarray:
    out = np.full(close.shape[0], np.nan)
    out[1:] = np.log(close[1:] / close[:-1])
    return out


# ============================================================================
# A05 / A13 — resolução de unidade de ATR_20 (docstring de group_a.py)
# ============================================================================


def test_a05_escala_e_dimensionalmente_o1_nao_1e5() -> None:
    """A05 dividido por atr_20_pct (fração ~0.003) deve dar uma feature na
    faixa O(1)-O(10), não O(1e-5) — se alguém trocar por ATR absoluto (~US$
    centenas), o resultado vira 1e-5 e este teste falha."""
    bars = _make_ohlcv(400)
    atr_abs = support.atr_wilder(bars["high"], bars["low"], bars["close"], window=20)
    atr_pct = atr_abs / bars["close"]
    out = group_a.a05_ret_vol_norm_4(bars["close"], atr_pct, lookback_bars=4)
    valid = out[~np.isnan(out)]
    assert valid.shape[0] > 0
    assert np.median(np.abs(valid)) < 100.0  # ordem de grandeza razoável, não 1e-5 nem 1e5
    assert np.median(np.abs(valid)) > 1e-4


def test_a13_escala_e_dimensionalmente_o1_a_o10_nao_1e5() -> None:
    """A13 dividido por ATR absoluto (US$) deve dar uma "distância em
    unidades de ATR" O(1)-O(10) — se alguém trocar por atr_20_pct, o
    resultado vira ~1e5."""
    bars = _make_ohlcv(400)
    atr_abs = support.atr_wilder(bars["high"], bars["low"], bars["close"], window=20)
    ema48 = support.ema(bars["close"], span=48)
    out = group_a.a13_dist_ema48_atr(bars["close"], ema48, atr_abs)
    valid = out[~np.isnan(out)]
    assert valid.shape[0] > 0
    assert np.median(np.abs(valid)) < 1000.0
    assert np.median(np.abs(valid)) > 1e-3


def test_a05_causalidade() -> None:
    bars = _make_ohlcv(300)
    atr_abs = support.atr_wilder(bars["high"], bars["low"], bars["close"], window=20)
    atr_pct = atr_abs / bars["close"]
    cutoff = 150
    out_base = group_a.a05_ret_vol_norm_4(bars["close"], atr_pct, lookback_bars=4)

    close2 = bars["close"].copy()
    close2[cutoff + 1 :] *= 1.5
    atr_abs2 = support.atr_wilder(bars["high"], bars["low"], close2, window=20)
    atr_pct2 = atr_abs2 / close2
    out_perturbed = group_a.a05_ret_vol_norm_4(close2, atr_pct2, lookback_bars=4)

    np.testing.assert_allclose(out_base[: cutoff + 1], out_perturbed[: cutoff + 1])


def test_a13_causalidade() -> None:
    """Achado da auditoria de vazamento (`src.validation.leakage`, §11.5
    teste 2): `registry.yaml` já citava
    'testado em tests/unit/test_features_groups.py::test_a13_causalidade'
    para A13, mas essa função nunca existiu neste arquivo — só
    `test_a05_causalidade` cobria causalidade de fato, e cobria A05, não
    A13 (resíduo de copy-paste do Sprint 4, não vazamento real: A13 usa as
    mesmas primitivas causais que A05, `ema`/`atr_wilder`, ambas já
    verificadas causais em `test_features_support.py`). Gap de teste
    fechado aqui — mesma técnica de `test_a05_causalidade` (perturbar o
    futuro não muda o passado), agora com a função que a citação sempre
    afirmou existir."""
    bars = _make_ohlcv(300)
    atr_abs = support.atr_wilder(bars["high"], bars["low"], bars["close"], window=20)
    ema48 = support.ema(bars["close"], span=48)
    cutoff = 150
    out_base = group_a.a13_dist_ema48_atr(bars["close"], ema48, atr_abs)

    close2 = bars["close"].copy()
    close2[cutoff + 1 :] *= 1.5
    atr_abs2 = support.atr_wilder(bars["high"], bars["low"], close2, window=20)
    ema48_2 = support.ema(close2, span=48)
    out_perturbed = group_a.a13_dist_ema48_atr(close2, ema48_2, atr_abs2)

    np.testing.assert_allclose(out_base[: cutoff + 1], out_perturbed[: cutoff + 1])


# ============================================================================
# B01 / B07
# ============================================================================


def test_b01_faixa_menos1_1() -> None:
    bars = _make_ohlcv(200)
    out = group_b.b01_rsi_14(bars["close"], window=14)
    valid = out[~np.isnan(out)]
    assert (valid >= -1.0 - 1e-9).all() and (valid <= 1.0 + 1e-9).all()


def test_b07_faixa_0_1() -> None:
    bars = _make_ohlcv(200)
    out = group_b.b07_efficiency_ratio_48(bars["close"], window=48)
    valid = out[~np.isnan(out)]
    assert (valid >= 0.0).all() and (valid <= 1.0 + 1e-9).all()


# ============================================================================
# C06 / C07
# ============================================================================


def test_c06_causalidade() -> None:
    bars = _make_ohlcv(300)
    log_ret = _log_return_1(bars["close"])
    cutoff = 150

    out_base = group_c.c06_vol_ratio_12_96(log_ret, short_window=12, long_window=96)

    log_ret2 = log_ret.copy()
    log_ret2[cutoff + 1 :] = log_ret2[cutoff + 1 :] * 5.0 + 0.1
    out_perturbed = group_c.c06_vol_ratio_12_96(log_ret2, short_window=12, long_window=96)

    np.testing.assert_allclose(out_base[: cutoff + 1], out_perturbed[: cutoff + 1])


def test_c06_positivo() -> None:
    bars = _make_ohlcv(300)
    log_ret = _log_return_1(bars["close"])
    out = group_c.c06_vol_ratio_12_96(log_ret, short_window=12, long_window=96)
    valid = out[~np.isnan(out)]
    assert (valid >= 0.0).all()


def test_c07_faixa_0_1_e_nao_usa_indice_t() -> None:
    bars = _make_ohlcv(300)
    log_ret = _log_return_1(bars["close"])
    out = group_c.c07_vol_pctile_expanding(log_ret, window=48)
    valid = out[~np.isnan(out)]
    assert (valid >= 0.0).all() and (valid <= 1.0).all()

    # prova B02 direta: reproduz manualmente o posto usando só < t
    rv = support.realized_vol(log_ret, window=48)
    for t in range(60, 300, 37):  # amostra alguns índices, não todos (custo)
        prior = rv[:t]
        prior_finite = prior[~np.isnan(prior)]
        if prior_finite.size == 0 or np.isnan(rv[t]):
            continue
        expected = float(np.mean(prior_finite < rv[t]))
        assert out[t] == pytest.approx(expected), f"t={t}"


# ============================================================================
# D03f / D06f
# ============================================================================


def test_d03f_nao_usa_indice_t() -> None:
    bars = _make_ohlcv(200)
    out = group_d.d03f_volume_z_expanding(bars["volume"])
    log_vol = np.log1p(bars["volume"])
    for t in range(2, 200, 29):
        prior = log_vol[:t]
        expected = (log_vol[t] - prior.mean()) / prior.std(ddof=1)
        assert out[t] == pytest.approx(expected), f"t={t}"


def test_d06f_causalidade() -> None:
    bars = _make_ohlcv(300)
    cutoff = 150
    out_base = group_d.d06f_taker_imbalance_z_48(
        bars["taker_buy_volume"], bars["volume"], window=48
    )

    tbv2 = bars["taker_buy_volume"].copy()
    vol2 = bars["volume"].copy()
    tbv2[cutoff + 1 :] *= 2.0
    vol2[cutoff + 1 :] *= 1.3
    out_perturbed = group_d.d06f_taker_imbalance_z_48(tbv2, vol2, window=48)

    np.testing.assert_allclose(out_base[: cutoff + 1], out_perturbed[: cutoff + 1])


# ============================================================================
# E02f / E10f / E27f
# ============================================================================


def test_e02f_nao_usa_indice_t() -> None:
    rng = np.random.default_rng(51)
    funding = rng.normal(0.0001, 0.0002, 150)
    out = group_e.e02f_funding_z_expanding(funding)
    for t in range(2, 150, 23):
        prior = funding[:t]
        expected = (funding[t] - prior.mean()) / prior.std(ddof=1)
        assert out[t] == pytest.approx(expected), f"t={t}"


def test_e10f_causalidade() -> None:
    rng = np.random.default_rng(53)
    oi = 90_000.0 + np.cumsum(rng.normal(0, 200, 300))
    cutoff = 150
    out_base = group_e.e10f_oi_change_z_48(oi, window=48)

    oi2 = oi.copy()
    oi2[cutoff + 1 :] *= 1.2
    out_perturbed = group_e.e10f_oi_change_z_48(oi2, window=48)

    np.testing.assert_allclose(out_base[: cutoff + 1], out_perturbed[: cutoff + 1])


def test_e10f_oi_zero_ou_negativo_nao_quebra() -> None:
    """`np.log` de um valor <= 0 não pode lançar exceção — só produzir
    NaN/-inf que se propaga (o tratamento real de OI <= 0 acontece na
    fonte, `_sources.load_oi_series_deduped`; aqui só garante que a função
    da feature não quebra se receber um `oi` já com NaN)."""
    oi = np.array([90_000.0, 91_000.0, np.nan, 92_000.0, 93_000.0] * 20)
    out = group_e.e10f_oi_change_z_48(oi, window=48)
    assert out.shape[0] == oi.shape[0]  # não lança, comprimento preservado


def test_e27f_round_trip_cost_bps_reproduz_0_055_pct() -> None:
    """`c_médio(assimétrico) = 0,055%` citado textualmente em §0.2 R2 do
    PRD, dado maker_fee=0,0002 / taker_fee=0,0005 (constants.yaml)."""
    cost_bps = group_e.round_trip_cost_bps(maker_fee=0.0002, taker_fee=0.0005)
    assert cost_bps == pytest.approx(5.5)  # 0,055% = 5,5 bps


def test_e27f_causalidade_e_positivo() -> None:
    bars = _make_ohlcv(200)
    atr_abs = support.atr_wilder(bars["high"], bars["low"], bars["close"], window=20)
    atr_pct = atr_abs / bars["close"]
    out = group_e.e27f_cost_atr_ratio(atr_pct, maker_fee=0.0002, taker_fee=0.0005)
    valid = out[~np.isnan(out)]
    assert (valid > 0.0).all()

    cutoff = 100
    atr_pct2 = atr_pct.copy()
    atr_pct2[cutoff + 1 :] *= 3.0
    out_perturbed = group_e.e27f_cost_atr_ratio(atr_pct2, maker_fee=0.0002, taker_fee=0.0005)
    np.testing.assert_allclose(out[: cutoff + 1], out_perturbed[: cutoff + 1])
