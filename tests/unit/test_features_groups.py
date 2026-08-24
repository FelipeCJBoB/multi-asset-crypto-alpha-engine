"""Testes de `src/features/groups/*.py` — a fiação de cada feature T1
sobre as primitivas de `support.py`, incluindo a resolução de ambiguidade
de unidade (ATR absoluto vs `atr_20_pct`) documentada em `group_a.py`."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pytest

from src.features import support
from src.features.groups import group_a, group_b, group_c, group_d, group_e, group_k


def _make_ohlcv(n: int, seed: int = 1) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(seed)
    close = 65_000.0 + np.cumsum(rng.normal(0, 80, n))
    high = close + rng.uniform(10, 100, n)
    low = close - rng.uniform(10, 100, n)
    volume = rng.uniform(50, 500, n)
    taker_buy_volume = volume * rng.uniform(0.3, 0.7, n)
    # Lote A (H5, 2026-08-24) -- 2 chaves novas, adicionadas DEPOIS das
    # originais na mesma sequência de rng pra preservar close/high/low/
    # volume/taker_buy_volume bit-idênticos em todo teste pré-existente
    # que usa _make_ohlcv (nenhum depende de open_/trade_count).
    open_ = low + rng.uniform(0.0, 1.0, n) * (high - low)  # sempre dentro de [low, high]
    trade_count = rng.uniform(50, 500, n)
    return {
        "close": close,
        "high": high,
        "low": low,
        "volume": volume,
        "taker_buy_volume": taker_buy_volume,
        "open": open_,
        "trade_count": trade_count,
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
# C01 — variante Parkinson (2026-08-17, AG-036/065/074)
# ============================================================================


def test_c01_atr_20_parkinson_denormaliza_para_unidade_de_preco() -> None:
    """`c01_atr_20_parkinson` == `support.parkinson_vol(...) * close` --
    fiação, não mecanismo (o mecanismo de `parkinson_vol` já é testado em
    `test_features_support.py`). Prova a denormalização pra unidade de
    preço absoluta que `project_assurance` (2026-08-17) confirmou."""
    bars = _make_ohlcv(300)
    out = group_c.c01_atr_20_parkinson(bars["high"], bars["low"], bars["close"], window=20)
    expected = support.parkinson_vol(bars["high"], bars["low"], window=20) * bars["close"]
    np.testing.assert_array_equal(out, expected)


def test_c01_atr_20_parkinson_nao_negativo() -> None:
    bars = _make_ohlcv(300)
    out = group_c.c01_atr_20_parkinson(bars["high"], bars["low"], bars["close"], window=20)
    valid = out[~np.isnan(out)]
    assert valid.size > 0
    assert (valid >= 0.0).all()


def test_c01_atr_20_parkinson_diverge_de_atr_wilder() -> None:
    """Prova que a mudança de estimador é real, não um re-rótulo do mesmo
    número (docstring de `c01_atr_20_parkinson`): sob a mesma entrada
    sintética, Parkinson e ATR de Wilder não coincidem barra a barra."""
    bars = _make_ohlcv(300)
    parkinson = group_c.c01_atr_20_parkinson(bars["high"], bars["low"], bars["close"], window=20)
    wilder = group_c.c01_atr_20(bars["high"], bars["low"], bars["close"], window=20)
    valid = ~np.isnan(parkinson) & ~np.isnan(wilder)
    assert valid.sum() > 0
    assert not np.allclose(parkinson[valid], wilder[valid])


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


def test_c07_min_common_history_bars_e_repassado_a_primitiva() -> None:
    """AG-030 (T0.5): C07 não implementa o cap sozinho -- só repassa o
    kwarg pra `support.expanding_percentile_rank_strict` sobre a MESMA
    `realized_vol` já calculada. Prova de fiação, não de mecanismo (o
    mecanismo em si já é testado em `test_features_support.py`)."""
    bars = _make_ohlcv(300)
    log_ret = _log_return_1(bars["close"])
    cap = 200
    out = group_c.c07_vol_pctile_expanding(log_ret, window=48, min_common_history_bars=cap)
    rv = support.realized_vol(log_ret, window=48)
    expected = support.expanding_percentile_rank_strict(rv, min_common_history_bars=cap)
    np.testing.assert_array_equal(out, expected)
    assert np.isnan(out[: 300 - cap]).all()


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


def test_d03f_min_common_history_bars_e_repassado_a_primitiva() -> None:
    """AG-030 (T0.5) -- mesma prova de fiação de C07, para D03f."""
    bars = _make_ohlcv(200)
    cap = 120
    out = group_d.d03f_volume_z_expanding(bars["volume"], min_common_history_bars=cap)
    log_vol = np.log1p(bars["volume"])
    expected = support.expanding_zscore_strict(log_vol, min_common_history_bars=cap)
    np.testing.assert_array_equal(out, expected)
    assert np.isnan(out[: 200 - cap]).all()


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


def test_e02f_min_common_history_bars_e_repassado_a_primitiva() -> None:
    """AG-030 (T0.5) -- mesma prova de fiação de C07/D03f, para E02f."""
    rng = np.random.default_rng(51)
    funding = rng.normal(0.0001, 0.0002, 150)
    cap = 90
    out = group_e.e02f_funding_z_expanding(funding, min_common_history_bars=cap)
    expected = support.expanding_zscore_strict(funding, min_common_history_bars=cap)
    np.testing.assert_array_equal(out, expected)
    assert np.isnan(out[: 150 - cap]).all()


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


# ============================================================================
# Lote A da liberação de features (H5, 2026-08-24) — A01-A04, A06-A12, A14,
# B02-B06, B08, B09, B11, C09-C12, D01f-D09f, E01f-E12f, K01-K08. Todas T2
# (§0.2 R4/§2.13, nenhuma promovida a T1 por esta implementação).
# ============================================================================


def test_a01_a04_log_return_causalidade() -> None:
    bars = _make_ohlcv(300)
    cutoff = 150
    close2 = bars["close"].copy()
    close2[cutoff + 1 :] *= 1.5

    for fn, lag in (
        (group_a.a01_log_return_1, 1),
        (group_a.a02_log_return_2, 2),
        (group_a.a03_log_return_4, 4),
        (group_a.a04_log_return_12, 12),
    ):
        out_base = fn(bars["close"], lag)
        out_perturbed = fn(close2, lag)
        np.testing.assert_allclose(
            out_base[: cutoff + 1], out_perturbed[: cutoff + 1], err_msg=fn.__name__
        )
        expected = np.full(300, np.nan)
        expected[lag:] = np.log(bars["close"][lag:] / bars["close"][:-lag])
        np.testing.assert_allclose(out_base, expected, equal_nan=True, err_msg=fn.__name__)


def test_a06_causalidade() -> None:
    bars = _make_ohlcv(300)
    atr_abs = support.atr_wilder(bars["high"], bars["low"], bars["close"], window=20)
    atr_pct = atr_abs / bars["close"]
    cutoff = 150
    out_base = group_a.a06_ret_vol_norm_12(
        bars["close"], atr_pct, 12, variance_ref_lookback_bars=4, vol_norm_divisor=2.0
    )

    close2 = bars["close"].copy()
    close2[cutoff + 1 :] *= 1.5
    atr_abs2 = support.atr_wilder(bars["high"], bars["low"], close2, window=20)
    atr_pct2 = atr_abs2 / close2
    out_perturbed = group_a.a06_ret_vol_norm_12(
        close2, atr_pct2, 12, variance_ref_lookback_bars=4, vol_norm_divisor=2.0
    )
    np.testing.assert_allclose(out_base[: cutoff + 1], out_perturbed[: cutoff + 1])


def test_a06_variance_scale_reproduz_sqrt3() -> None:
    """PRD cita 'ATR_20 × √3 × 2' pra A06 (lookback=12 vs referência=4 de
    A05) — sqrt(12/4)=sqrt(3) precisa bater com o valor literal do
    texto, calculado em runtime a partir dos 2 lookbacks, não hardcoded."""
    close = 65_000.0 + np.cumsum(np.random.default_rng(7).normal(0, 80, 100))
    atr_pct = np.full(100, 0.003)
    out = group_a.a06_ret_vol_norm_12(
        close, atr_pct, 12, variance_ref_lookback_bars=4, vol_norm_divisor=2.0
    )
    log_ret_12 = np.full(100, np.nan)
    log_ret_12[12:] = np.log(close[12:] / close[:-12])
    expected = log_ret_12 / (atr_pct * np.sqrt(3.0) * 2.0)
    np.testing.assert_allclose(out, expected, equal_nan=True)


def test_a07_a10_h_eq_l_produz_zero() -> None:
    open_ = np.array([100.0, 100.0])
    high = np.array([105.0, 100.0])
    low = np.array([95.0, 100.0])
    close = np.array([102.0, 100.0])
    assert group_a.a07_body_ratio(open_, high, low, close)[1] == 0.0
    assert group_a.a08_upper_wick_ratio(open_, high, low, close)[1] == 0.0
    assert group_a.a09_lower_wick_ratio(open_, high, low, close)[1] == 0.0
    assert group_a.a10_close_location(high, low, close)[1] == 0.0


def test_a07_a10_faixas() -> None:
    bars = _make_ohlcv(200)
    body = group_a.a07_body_ratio(bars["open"], bars["high"], bars["low"], bars["close"])
    upper = group_a.a08_upper_wick_ratio(bars["open"], bars["high"], bars["low"], bars["close"])
    lower = group_a.a09_lower_wick_ratio(bars["open"], bars["high"], bars["low"], bars["close"])
    loc = group_a.a10_close_location(bars["high"], bars["low"], bars["close"])
    assert (body >= -1.0 - 1e-9).all() and (body <= 1.0 + 1e-9).all()
    assert (upper >= -1e-9).all() and (upper <= 1.0 + 1e-9).all()
    assert (lower >= -1e-9).all() and (lower <= 1.0 + 1e-9).all()
    assert (loc >= -1e-9).all() and (loc <= 1.0 + 1e-9).all()


def test_a11_causalidade() -> None:
    bars = _make_ohlcv(300)
    cutoff = 150
    out_base = group_a.a11_true_range_pct(bars["high"], bars["low"], bars["close"])

    high2, low2, close2 = bars["high"].copy(), bars["low"].copy(), bars["close"].copy()
    high2[cutoff + 1 :] *= 1.5
    low2[cutoff + 1 :] *= 1.5
    close2[cutoff + 1 :] *= 1.5
    out_perturbed = group_a.a11_true_range_pct(high2, low2, close2)
    np.testing.assert_allclose(out_base[: cutoff + 1], out_perturbed[: cutoff + 1])


def test_a11_reproduz_true_range_sobre_close_anterior() -> None:
    bars = _make_ohlcv(200)
    out = group_a.a11_true_range_pct(bars["high"], bars["low"], bars["close"])
    tr = support.true_range(bars["high"], bars["low"], bars["close"])
    prev_close = np.full(200, np.nan)
    prev_close[1:] = bars["close"][:-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        expected = tr / prev_close
    np.testing.assert_allclose(out, expected, equal_nan=True)


def test_a12_causalidade() -> None:
    bars = _make_ohlcv(300)
    cutoff = 150
    out_base = group_a.a12_gap_pct(bars["open"], bars["close"])

    open2, close2 = bars["open"].copy(), bars["close"].copy()
    open2[cutoff + 1 :] *= 1.5
    close2[cutoff + 1 :] *= 1.5
    out_perturbed = group_a.a12_gap_pct(open2, close2)
    np.testing.assert_allclose(out_base[: cutoff + 1], out_perturbed[: cutoff + 1])


def test_a14_causalidade() -> None:
    bars = _make_ohlcv(300)
    atr_abs = support.atr_wilder(bars["high"], bars["low"], bars["close"], window=20)
    ema12 = support.ema(bars["close"], span=12)
    cutoff = 150
    out_base = group_a.a14_dist_ema12_atr(bars["close"], ema12, atr_abs)

    close2 = bars["close"].copy()
    close2[cutoff + 1 :] *= 1.5
    atr_abs2 = support.atr_wilder(bars["high"], bars["low"], close2, window=20)
    ema12_2 = support.ema(close2, span=12)
    out_perturbed = group_a.a14_dist_ema12_atr(close2, ema12_2, atr_abs2)
    np.testing.assert_allclose(out_base[: cutoff + 1], out_perturbed[: cutoff + 1])


# ----------------------------------------------------------------------
# B02-B06, B08, B09, B11
# ----------------------------------------------------------------------


def test_b02_faixa_menos1_1() -> None:
    bars = _make_ohlcv(200)
    out = group_b.b02_rsi_48(bars["close"], window=48)
    valid = out[~np.isnan(out)]
    assert (valid >= -1.0 - 1e-9).all() and (valid <= 1.0 + 1e-9).all()


def test_b03_causalidade() -> None:
    bars = _make_ohlcv(300)
    cutoff = 150
    out_base = group_b.b03_roc_12(bars["close"], lookback_bars=12)

    close2 = bars["close"].copy()
    close2[cutoff + 1 :] *= 1.5
    out_perturbed = group_b.b03_roc_12(close2, lookback_bars=12)
    np.testing.assert_allclose(out_base[: cutoff + 1], out_perturbed[: cutoff + 1])


def test_b04_causalidade() -> None:
    bars = _make_ohlcv(300)
    atr_abs = support.atr_wilder(bars["high"], bars["low"], bars["close"], window=20)
    cutoff = 200
    out_base = group_b.b04_macd_hist_norm(
        bars["close"], atr_abs, fast_window=12, slow_window=26, signal_window=9
    )
    valid = out_base[~np.isnan(out_base)]
    assert valid.shape[0] > 0

    close2 = bars["close"].copy()
    close2[cutoff + 1 :] *= 1.5
    atr_abs2 = support.atr_wilder(bars["high"], bars["low"], close2, window=20)
    out_perturbed = group_b.b04_macd_hist_norm(
        close2, atr_abs2, fast_window=12, slow_window=26, signal_window=9
    )
    np.testing.assert_allclose(out_base[: cutoff + 1], out_perturbed[: cutoff + 1])


def test_b05_causalidade() -> None:
    bars = _make_ohlcv(300)
    atr_abs = support.atr_wilder(bars["high"], bars["low"], bars["close"], window=20)
    cutoff = 200
    out_base = group_b.b05_ema_slope_24(bars["close"], atr_abs, ema_window=24, slope_lag_bars=6)

    close2 = bars["close"].copy()
    close2[cutoff + 1 :] *= 1.5
    atr_abs2 = support.atr_wilder(bars["high"], bars["low"], close2, window=20)
    out_perturbed = group_b.b05_ema_slope_24(close2, atr_abs2, ema_window=24, slope_lag_bars=6)
    np.testing.assert_allclose(out_base[: cutoff + 1], out_perturbed[: cutoff + 1])


def test_b06_causalidade() -> None:
    bars = _make_ohlcv(300)
    atr_abs = support.atr_wilder(bars["high"], bars["low"], bars["close"], window=20)
    atr_pct = atr_abs / bars["close"]
    cutoff = 200
    out_base = group_b.b06_momentum_accel(bars["close"], atr_pct, lookback_bars=4)

    close2 = bars["close"].copy()
    close2[cutoff + 1 :] *= 1.5
    atr_abs2 = support.atr_wilder(bars["high"], bars["low"], close2, window=20)
    atr_pct2 = atr_abs2 / close2
    out_perturbed = group_b.b06_momentum_accel(close2, atr_pct2, lookback_bars=4)
    np.testing.assert_allclose(out_base[: cutoff + 1], out_perturbed[: cutoff + 1])


def test_b08_faixa_0_1() -> None:
    bars = _make_ohlcv(200)
    out = group_b.b08_efficiency_ratio_16(bars["close"], window=16)
    valid = out[~np.isnan(out)]
    assert (valid >= 0.0).all() and (valid <= 1.0 + 1e-9).all()


def test_b09_causalidade() -> None:
    bars = _make_ohlcv(200)
    out = group_b.b09_zscore_close_48(bars["close"], window=48)
    expected = support.rolling_zscore(bars["close"], window=48)
    np.testing.assert_array_equal(out, expected)


def test_b11_eh_metade_do_zscore() -> None:
    bars = _make_ohlcv(200)
    out = group_b.b11_bb_position_20(bars["close"], window=20, std_multiplier=2.0)
    z = support.rolling_zscore(bars["close"], window=20)
    np.testing.assert_allclose(out, z / 2.0, equal_nan=True)


# ----------------------------------------------------------------------
# C09-C12
# ----------------------------------------------------------------------


def test_c09_faixa_0_1_e_nao_usa_indice_t() -> None:
    bars = _make_ohlcv(300)
    trp = group_a.a11_true_range_pct(bars["high"], bars["low"], bars["close"])
    out = group_c.c09_range_pctile_expanding(trp)
    valid = out[~np.isnan(out)]
    assert (valid >= 0.0).all() and (valid <= 1.0).all()

    expected = support.expanding_percentile_rank_strict(trp)
    np.testing.assert_array_equal(out, expected)


def test_c10_c11_flags_consistentes_com_rank() -> None:
    rng = np.random.default_rng(61)
    vol_ratio = rng.uniform(0.5, 2.0, 300)
    flag_high = group_c.c10_vol_expansion_flag(vol_ratio, threshold=0.80)
    flag_low = group_c.c11_vol_compression_flag(vol_ratio, threshold=0.20)
    rank = support.expanding_percentile_rank_strict(vol_ratio)
    valid = ~np.isnan(rank)
    np.testing.assert_array_equal(flag_high[valid], (rank[valid] > 0.80).astype(np.float64))
    np.testing.assert_array_equal(flag_low[valid], (rank[valid] < 0.20).astype(np.float64))
    assert np.isnan(flag_high[~valid]).all()
    assert np.isnan(flag_low[~valid]).all()


def test_c12_causalidade() -> None:
    bars = _make_ohlcv(300)
    log_ret = _log_return_1(bars["close"])
    cutoff = 200
    out_base = group_c.c12_vol_of_vol_48(log_ret, inner_window=12, outer_window=48)

    log_ret2 = log_ret.copy()
    log_ret2[cutoff + 1 :] = log_ret2[cutoff + 1 :] * 5.0 + 0.1
    out_perturbed = group_c.c12_vol_of_vol_48(log_ret2, inner_window=12, outer_window=48)
    np.testing.assert_allclose(out_base[: cutoff + 1], out_perturbed[: cutoff + 1])


# ----------------------------------------------------------------------
# D01f-D09f
# ----------------------------------------------------------------------


def test_d01f_causalidade() -> None:
    bars = _make_ohlcv(300)
    out = group_d.d01f_volume_z_96(bars["volume"], window=96)
    expected = support.rolling_zscore(bars["volume"], window=96)
    np.testing.assert_array_equal(out, expected)


def test_d02f_positivo_e_causal() -> None:
    bars = _make_ohlcv(300)
    cutoff = 200
    out_base = group_d.d02f_rel_volume_48(bars["volume"], window=48)
    valid = out_base[~np.isnan(out_base)]
    assert (valid > 0.0).all()

    volume2 = bars["volume"].copy()
    volume2[cutoff + 1 :] *= 3.0
    out_perturbed = group_d.d02f_rel_volume_48(volume2, window=48)
    np.testing.assert_allclose(out_base[: cutoff + 1], out_perturbed[: cutoff + 1])


def test_d04f_causalidade() -> None:
    bars = _make_ohlcv(300)
    cutoff = 200
    out_base = group_d.d04f_volume_accel(bars["volume"], window=4)

    volume2 = bars["volume"].copy()
    volume2[cutoff + 1 :] *= 3.0
    out_perturbed = group_d.d04f_volume_accel(volume2, window=4)
    np.testing.assert_allclose(out_base[: cutoff + 1], out_perturbed[: cutoff + 1])


def test_d05f_faixa_0_1() -> None:
    bars = _make_ohlcv(200)
    out = group_d.d05f_taker_buy_ratio(bars["taker_buy_volume"], bars["volume"])
    assert (out >= 0.0).all() and (out <= 1.0).all()


def test_d08f_causalidade() -> None:
    bars = _make_ohlcv(300)
    cutoff = 200
    out_base = group_d.d08f_trade_count_z_48(bars["trade_count"], window=48)

    trade_count2 = bars["trade_count"].copy()
    trade_count2[cutoff + 1 :] *= 3.0
    out_perturbed = group_d.d08f_trade_count_z_48(trade_count2, window=48)
    np.testing.assert_allclose(out_base[: cutoff + 1], out_perturbed[: cutoff + 1])


def test_d09f_causalidade() -> None:
    bars = _make_ohlcv(300)
    cutoff = 200
    out_base = group_d.d09f_avg_trade_size_z(bars["volume"], bars["trade_count"], window=48)

    volume2 = bars["volume"].copy()
    volume2[cutoff + 1 :] *= 3.0
    out_perturbed = group_d.d09f_avg_trade_size_z(volume2, bars["trade_count"], window=48)
    np.testing.assert_allclose(out_base[: cutoff + 1], out_perturbed[: cutoff + 1])


# ----------------------------------------------------------------------
# E01f, E05f, E09f, E11f, E12f
# ----------------------------------------------------------------------


def test_e01f_e09f_sao_passthrough() -> None:
    rng = np.random.default_rng(71)
    funding = rng.normal(0.0001, 0.0002, 50)
    oi = 90_000.0 + np.cumsum(rng.normal(0, 200, 50))
    np.testing.assert_array_equal(group_e.e01f_funding_last(funding), funding)
    np.testing.assert_array_equal(group_e.e09f_oi_contracts(oi), oi)


def test_e05f_tempo_ate_funding_em_fronteiras_conhecidas() -> None:
    hour_ms = 3_600_000.0
    close_time_ms = np.array([0.0, 1 * hour_ms, 7 * hour_ms, 8 * hour_ms, 9 * hour_ms])
    out = group_e.e05f_time_to_funding_h(close_time_ms, funding_interval_hours=8)
    np.testing.assert_allclose(out, [0.0, 7.0, 1.0, 0.0, 7.0])


def test_e11f_causalidade() -> None:
    rng = np.random.default_rng(53)
    oi = 90_000.0 + np.cumsum(rng.normal(0, 200, 300))
    cutoff = 200
    out_base = group_e.e11f_oi_change_1d(oi, lag_bars=48)

    oi2 = oi.copy()
    oi2[cutoff + 1 :] *= 1.2
    out_perturbed = group_e.e11f_oi_change_1d(oi2, lag_bars=48)
    np.testing.assert_allclose(out_base[: cutoff + 1], out_perturbed[: cutoff + 1])


def test_e12f_sinais_em_menos1_0_1() -> None:
    close = np.array([100.0] * 12 + [110.0] * 12, dtype=np.float64)  # sobe -> ret_12 > 0
    ret_lag = group_a.a04_log_return_12(close, lag_bars=12)
    oi = np.array([1000.0] * 12 + [900.0] * 12, dtype=np.float64)  # cai -> oi_change < 0
    out = group_e.e12f_price_oi_divergence(ret_lag, oi, oi_lag_bars=12)
    valid = out[~np.isnan(out)]
    assert set(np.unique(valid)).issubset({-1.0, 0.0, 1.0})
    assert out[12] == pytest.approx(-1.0)  # ret_12>0 (sign+1) * oi_change<0 (sign-1) = -1


# ----------------------------------------------------------------------
# K01-K08 (núcleo puro, só timestamp -- sem OHLCV)
# ----------------------------------------------------------------------


def test_k01_valores_conhecidos() -> None:
    hour_ms = 3_600_000.0
    close_time_ms = np.array([0.0, 6 * hour_ms, 12 * hour_ms, 18 * hour_ms])
    sin_out = group_k.k01_hour_sin(close_time_ms)
    cos_out = group_k.k01_hour_cos(close_time_ms)
    np.testing.assert_allclose(sin_out, [0.0, 1.0, 0.0, -1.0], atol=1e-9)
    np.testing.assert_allclose(cos_out, [1.0, 0.0, -1.0, 0.0], atol=1e-9)


def test_k02_dow_valores_conhecidos() -> None:
    """Época Unix (1970-01-01T00:00:00Z) foi uma quinta-feira -> dow=0."""
    day_ms = 86_400_000.0
    close_time_ms = np.array([0.0, 3 * day_ms])  # epoch (quinta) e +3 dias (domingo)
    sin_out = group_k.k02_dow_sin(close_time_ms)
    cos_out = group_k.k02_dow_cos(close_time_ms)
    np.testing.assert_allclose(sin_out[0], 0.0, atol=1e-9)
    np.testing.assert_allclose(cos_out[0], 1.0, atol=1e-9)
    expected_sin_3 = np.sin(2.0 * np.pi * 3.0 / 7.0)
    expected_cos_3 = np.cos(2.0 * np.pi * 3.0 / 7.0)
    np.testing.assert_allclose(sin_out[1], expected_sin_3, atol=1e-9)
    np.testing.assert_allclose(cos_out[1], expected_cos_3, atol=1e-9)


def test_k03_is_weekend() -> None:
    day_ms = 86_400_000.0
    # dow: 0=qui,1=sex,2=sab,3=dom,4=seg,5=ter,6=qua (época Unix=quinta)
    close_time_ms = np.array([d * day_ms for d in range(7)])
    out = group_k.k03_is_weekend(close_time_ms)
    np.testing.assert_array_equal(out, [0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 0.0])


def test_k04_sessions_particionam_o_dia() -> None:
    hours = np.arange(0, 24, 1, dtype=np.float64)
    close_time_ms = hours * 3_600_000.0
    asia = group_k.k04_session_asia(close_time_ms, 0.0, 8.0)
    europe = group_k.k04_session_europe(close_time_ms, 8.0, 16.0)
    us = group_k.k04_session_us(close_time_ms, 16.0, 24.0)
    np.testing.assert_array_equal(asia + europe + us, np.ones(24))


def test_k08_days_since_halving_correto() -> None:
    def _to_ms(date_str: str) -> int:
        return int(
            datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=UTC).timestamp() * 1000
        )

    halving_dates_ms = tuple(
        _to_ms(s) for s in ("2012-11-28", "2016-07-09", "2020-05-11", "2024-04-20")
    )
    day_ms = 86_400_000.0
    close_time_ms = np.array(
        [
            float(_to_ms("2020-05-11")),  # exatamente no halving 3 -> 0 dias
            float(_to_ms("2020-05-11")) + day_ms,  # 1 dia depois -> 1.0
            float(_to_ms("2020-01-01")),  # antes do halving 3, depois do 2
        ]
    )
    out = group_k.k08_days_since_halving(close_time_ms, halving_dates_ms)
    assert out[0] == pytest.approx(0.0)
    assert out[1] == pytest.approx(1.0)
    expected_2 = (_to_ms("2020-01-01") - _to_ms("2016-07-09")) / day_ms
    assert out[2] == pytest.approx(expected_2)


def test_k08_days_since_halving_antes_do_1o_halving_e_nan() -> None:
    halving_dates_ms = (1_000_000_000_000,)
    out = group_k.k08_days_since_halving(np.array([0.0, 999_999_999_999.0]), halving_dates_ms)
    assert np.isnan(out).all()
