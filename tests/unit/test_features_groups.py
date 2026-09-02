"""Testes de `src/features/groups/*.py` — a fiação de cada feature T1
sobre as primitivas de `support.py`, incluindo a resolução de ambiguidade
de unidade (ATR absoluto vs `atr_20_pct`) documentada em `group_a.py`."""

from __future__ import annotations

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
    out = group_a.a05_ret_vol_norm_4(bars["close"], atr_pct, lookback_bars=4, vol_norm_divisor=2.0)
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
    out_base = group_a.a05_ret_vol_norm_4(
        bars["close"], atr_pct, lookback_bars=4, vol_norm_divisor=2.0
    )

    close2 = bars["close"].copy()
    close2[cutoff + 1 :] *= 1.5
    atr_abs2 = support.atr_wilder(bars["high"], bars["low"], close2, window=20)
    atr_pct2 = atr_abs2 / close2
    out_perturbed = group_a.a05_ret_vol_norm_4(
        close2, atr_pct2, lookback_bars=4, vol_norm_divisor=2.0
    )

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
# C04 / C05
# ============================================================================


def test_c04_escala_por_sqrt_window() -> None:
    """`c04_parkinson_vol_48` == `support.parkinson_vol(...) * sqrt(window)`
    -- fiação (o mecanismo de `parkinson_vol` já é testado em
    `test_features_support.py`). Corrigido 2026-08-27 (`AG-322`): prova a
    escala nova que iguala C04 à convenção de `C03_realized_vol_48`, sem
    tocar a primitiva compartilhada com `c01_atr_20_parkinson` (produção)."""
    bars = _make_ohlcv(300)
    out = group_c.c04_parkinson_vol_48(bars["high"], bars["low"], window=48)
    expected = support.parkinson_vol(bars["high"], bars["low"], window=48) * np.sqrt(48)
    np.testing.assert_array_equal(out, expected)


def test_c04_nao_afeta_c01_atr_20_parkinson() -> None:
    """A correção de escala de C04 é aplicada só no nível da FEATURE --
    `support.parkinson_vol` (compartilhada com `c01_atr_20_parkinson`,
    insumo de produção via `atr_20_abs`/`atr_20_pct`) continua sem
    `sqrt(window)`, mesmo comportamento de antes de `AG-322`."""
    bars = _make_ohlcv(300)
    c01_out = group_c.c01_atr_20_parkinson(bars["high"], bars["low"], bars["close"], window=20)
    expected_c01 = support.parkinson_vol(bars["high"], bars["low"], window=20) * bars["close"]
    np.testing.assert_array_equal(c01_out, expected_c01)


def test_c05_escala_por_sqrt_window() -> None:
    """`c05_garman_klass_48` == `support.garman_klass_vol(...) *
    sqrt(window)` -- mesma disciplina de `test_c04_escala_por_sqrt_window`
    (`AG-322`), sem tocar `support.garman_klass_vol`."""
    bars = _make_ohlcv(300)
    out = group_c.c05_garman_klass_48(
        bars["high"], bars["low"], bars["open"], bars["close"], window=48
    )
    expected = (
        support.garman_klass_vol(bars["high"], bars["low"], bars["open"], bars["close"], window=48)
        * np.sqrt(48)
    )
    np.testing.assert_array_equal(out, expected)


def test_c05_nao_negativo() -> None:
    bars = _make_ohlcv(300)
    out = group_c.c05_garman_klass_48(
        bars["high"], bars["low"], bars["open"], bars["close"], window=48
    )
    valid = out[~np.isnan(out)]
    assert valid.size > 0
    assert (valid >= 0.0).all()


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


# ============================================================================
# AG-295 -- proposta de correção pra E10f (ERRO_CATEGORICO): diferenciar OI
# na cadência NATIVA da fonte, antes do alinhamento a barra, em vez de
# diferenciar a série já alinhada/repetida (e10f_oi_change_z_48, produção,
# INTOCADA -- estes testes cobrem só a proposta nova).
# ============================================================================


def test_oi_change_native_from_levels_bate_com_diff_log_manual() -> None:
    oi_native = np.array([90_000.0, 90_450.0, 90_200.0, 91_000.0])
    out = group_e.oi_change_native_from_levels(oi_native)
    esperado = np.diff(np.log(oi_native))
    np.testing.assert_allclose(out[1:], esperado)
    assert np.isnan(out[0])


def test_oi_change_native_from_levels_primeiro_ponto_e_nan() -> None:
    """Sem observação anterior, o primeiro delta é indefinido -- NaN, não
    zero (zero afirmaria 'sem mudança', que é uma alegação diferente de
    'não sei')."""
    out = group_e.oi_change_native_from_levels(np.array([90_000.0, 91_000.0]))
    assert np.isnan(out[0])
    assert not np.isnan(out[1])


def test_e10f_from_native_delta_e_so_rolling_zscore_sem_diff_interno() -> None:
    """A versão corrigida não tem `Δln` interno -- a entrada já é delta.
    Passar a MESMA série de delta direto em `support.rolling_zscore` tem
    que bater exatamente."""
    rng = np.random.default_rng(54)
    delta = rng.normal(0, 0.01, 200)
    out = group_e.e10f_oi_change_z_48_from_native_delta(delta, window=48)
    esperado = support.rolling_zscore(delta, 48)
    np.testing.assert_array_equal(out, esperado)


def test_ag_295_diferenciar_antes_do_alinhamento_elimina_o_zero_mecanico() -> None:
    """Demonstração do defeito de `e10f_oi_change_z_48` (produção) e da
    correção proposta, com dado sintético que reproduz o mecanismo real:
    3 barras dollar consecutivas mais curtas que o intervalo da fonte
    (~5 min) mapeiam, via asof-join backward, pro MESMO ponto de OI.

    Caminho ANTIGO (produção): alinha o NÍVEL (3 barras repetem o mesmo
    valor), depois diferencia -- produz 2 zeros MECÂNICOS consecutivos
    que nada têm a ver com o mercado.

    Caminho NOVO (proposta): diferencia na cadência nativa (2 leituras
    reais, 1 delta real), depois alinha o DELTA -- as 3 barras recebem o
    MESMO delta real repetido (honesto: 'ainda não chegou leitura nova'),
    nunca um zero fabricado pelo encontro de duas repetições."""
    oi_native_level = np.array([100_000.0, 100_500.0])  # 2 leituras reais da fonte

    # Caminho antigo: 3 barras curtas, todas asof-joined pro MESMO ponto
    # (a 1a leitura), simulando barras mais rápidas que a fonte.
    oi_level_aligned_3_barras = np.array(
        [oi_native_level[0], oi_native_level[0], oi_native_level[0]]
    )
    delta_antigo = np.diff(np.log(oi_level_aligned_3_barras))
    assert delta_antigo == pytest.approx([0.0, 0.0])  # zero MECANICO, nao real

    # Caminho novo: delta calculado na cadencia nativa (1 delta real entre
    # as 2 leituras), DEPOIS repetido pras 3 barras via alinhamento.
    delta_nativo = group_e.oi_change_native_from_levels(oi_native_level)
    delta_real = delta_nativo[1]  # unico delta real disponivel
    assert delta_real != pytest.approx(0.0)
    delta_novo_alinhado_3_barras = np.array([delta_real, delta_real, delta_real])
    assert delta_novo_alinhado_3_barras == pytest.approx([delta_real] * 3)
    assert not np.any(delta_novo_alinhado_3_barras == pytest.approx(0.0))


def test_e27f_round_trip_cost_bps_le_maker_prob_medido_de_constants() -> None:
    """Corrigido 2026-08-24 (AG-027 fechado de verdade) -- não reproduz mais
    o `c_médio(assimétrico) = 0,055%` do PRD (§0.2 R2), citado sob a
    premissa 50/50 já refutada por medição real (42,06% pooled,
    `tools/diagnostics/measure_barrier_touch_probability.py`). Reconstrução
    independente a partir da constante real (não reimplementa
    `round_trip_cost_bps`, só o valor esperado) -- pega qualquer mudança
    futura em `round_trip_cost_bps_maker_prob` automaticamente, sem
    hardcode duplicado."""
    from src.features._constants import load_constant

    maker_fee, taker_fee = 0.0002, 0.0005
    maker_prob = load_constant("round_trip_cost_bps_maker_prob")
    expected_bps = (maker_fee + maker_prob * maker_fee + (1.0 - maker_prob) * taker_fee) * 10000
    cost_bps = group_e.round_trip_cost_bps(maker_fee=maker_fee, taker_fee=taker_fee)
    assert cost_bps == pytest.approx(expected_bps)


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


# ============================================================================
# Lote D (2026-08-28, AG-372/ADR-006) -- A16/A17/B12/B13/B14/B15.
# ============================================================================


def test_a16_causalidade() -> None:
    bars = _make_ohlcv(300)
    cutoff = 150
    out_base = group_a.a16_return_3(bars["close"], lag_bars=3)

    close2 = bars["close"].copy()
    close2[cutoff + 1 :] *= 1.5
    out_perturbed = group_a.a16_return_3(close2, lag_bars=3)

    np.testing.assert_allclose(out_base[: cutoff + 1], out_perturbed[: cutoff + 1])


def test_a17_causalidade() -> None:
    bars = _make_ohlcv(300)
    rng = np.random.default_rng(7)
    overshoot = rng.uniform(1.0, 1000.0, 300)
    threshold_quote = np.full(300, 5000.0)
    cutoff = 150
    out_base = group_a.a17_log_tr_per_overshoot_ratio(
        bars["high"], bars["low"], bars["close"], overshoot, threshold_quote
    )

    high2, low2, close2, overshoot2 = (
        bars["high"].copy(),
        bars["low"].copy(),
        bars["close"].copy(),
        overshoot.copy(),
    )
    high2[cutoff + 1 :] *= 1.5
    low2[cutoff + 1 :] *= 1.5
    close2[cutoff + 1 :] *= 1.5
    overshoot2[cutoff + 1 :] *= 3.0
    out_perturbed = group_a.a17_log_tr_per_overshoot_ratio(
        high2, low2, close2, overshoot2, threshold_quote
    )

    np.testing.assert_allclose(out_base[: cutoff + 1], out_perturbed[: cutoff + 1])


def test_a17_guarda_overshoot_e_threshold_nao_positivos() -> None:
    bars = _make_ohlcv(50)
    overshoot = np.full(50, 100.0)
    overshoot[10] = 0.0
    overshoot[20] = -5.0
    threshold_quote = np.full(50, 5000.0)
    threshold_quote[30] = 0.0
    threshold_quote[31] = -1.0
    out = group_a.a17_log_tr_per_overshoot_ratio(
        bars["high"], bars["low"], bars["close"], overshoot, threshold_quote
    )
    assert np.isnan(out[10])
    assert np.isnan(out[20])
    assert np.isnan(out[30])
    assert np.isnan(out[31])
    assert not np.isnan(out[40])


def test_a17_invariante_a_nivel_de_preco() -> None:
    """Prova direta do fix de `AG-373`: escalar high/low/close por uma
    constante (simulando outro nível de preço/época do mesmo ativo) NÃO
    muda a saída, porque `TR/C_{t-1}` (numerador) já é adimensional --
    diferente da v1 (`TR` bruto / `overshoot`), que tinha unidade
    residual `1/coin` e teria mudado sob este mesmo teste."""
    bars = _make_ohlcv(300)
    rng = np.random.default_rng(17)
    overshoot = rng.uniform(1.0, 1000.0, 300)
    threshold_quote = np.full(300, 5000.0)
    out_base = group_a.a17_log_tr_per_overshoot_ratio(
        bars["high"], bars["low"], bars["close"], overshoot, threshold_quote
    )
    scale = 37.0  # preço 37x maior; overshoot/threshold_quote inalterados
    out_scaled = group_a.a17_log_tr_per_overshoot_ratio(
        bars["high"] * scale,
        bars["low"] * scale,
        bars["close"] * scale,
        overshoot,
        threshold_quote,
    )
    np.testing.assert_allclose(out_base, out_scaled, equal_nan=True)


def test_b12_causalidade() -> None:
    bars = _make_ohlcv(300)
    cutoff = 150
    out_base = group_b.b12_close_location_h3(bars["high"], bars["low"], bars["close"], window=3)

    high2, low2, close2 = bars["high"].copy(), bars["low"].copy(), bars["close"].copy()
    high2[cutoff + 1 :] *= 1.5
    low2[cutoff + 1 :] *= 1.5
    close2[cutoff + 1 :] *= 1.5
    out_perturbed = group_b.b12_close_location_h3(high2, low2, close2, window=3)

    np.testing.assert_allclose(out_base[: cutoff + 1], out_perturbed[: cutoff + 1])


def test_b12_faixa_menos1_a_1() -> None:
    bars = _make_ohlcv(300)
    out = group_b.b12_close_location_h3(bars["high"], bars["low"], bars["close"], window=3)
    valid = out[~np.isnan(out)]
    assert (valid >= -1.0).all()
    assert (valid <= 1.0).all()


def test_b12_guarda_range_flat_produz_ponto_medio() -> None:
    """Range flat (high=low=close constantes na janela) é o caso
    degenerado real de par ilíquido em baixíssima volatilidade -- achado
    de `/audit_engineering` (2026-08-28): B12 tinha a guarda implementada
    (`range_==0 -> 0.5`) mas nenhum teste exercitava esse branch."""
    n = 10
    flat = np.full(n, 100.0)
    out = group_b.b12_close_location_h3(flat, flat, flat, window=3)
    valid = out[~np.isnan(out)]
    assert valid.shape[0] > 0
    np.testing.assert_allclose(valid, 0.0)


def test_b13_causalidade() -> None:
    rng = np.random.default_rng(11)
    n = 300
    ret_h = rng.normal(0, 0.01, n)
    realized_vol_h = rng.uniform(0.001, 0.05, n)
    cutoff = 150
    out_base = group_b.b13_extension_h3(ret_h, realized_vol_h)

    ret_h2, vol_h2 = ret_h.copy(), realized_vol_h.copy()
    ret_h2[cutoff + 1 :] *= 5.0
    vol_h2[cutoff + 1 :] *= 5.0
    out_perturbed = group_b.b13_extension_h3(ret_h2, vol_h2)

    np.testing.assert_allclose(out_base[: cutoff + 1], out_perturbed[: cutoff + 1])


def test_b13_guarda_realized_vol_zero() -> None:
    # achado de /audit_engineering (2026-08-28): 3 barras de retorno
    # idêntico (dollar bar, tick repetido em ativo de menor liquidez) ->
    # realized_vol_h=0 -- não pode virar inf silencioso.
    ret_h = np.array([0.02, 0.0, -0.01])
    realized_vol_h = np.array([0.01, 0.0, 0.005])
    out = group_b.b13_extension_h3(ret_h, realized_vol_h)
    assert np.isnan(out[1])
    assert not np.isnan(out[0])
    assert not np.isnan(out[2])


def test_b14_causalidade() -> None:
    rng = np.random.default_rng(13)
    n = 300
    ret_h_prior = rng.normal(0, 0.01, n)
    ret_1 = rng.normal(0, 0.005, n)
    atr_20_pct = rng.uniform(0.001, 0.02, n)
    cutoff = 150
    out_base = group_b.b14_rejection_after_extension(ret_h_prior, ret_1, atr_20_pct)

    a2, b2, c2 = ret_h_prior.copy(), ret_1.copy(), atr_20_pct.copy()
    a2[cutoff + 1 :] *= 5.0
    b2[cutoff + 1 :] *= 5.0
    c2[cutoff + 1 :] *= 2.0
    out_perturbed = group_b.b14_rejection_after_extension(a2, b2, c2)

    np.testing.assert_allclose(out_base[: cutoff + 1], out_perturbed[: cutoff + 1])


def test_b14_sinaliza_rejeicao_e_continuacao_corretamente() -> None:
    # extensão de alta (ret_h_prior>0) seguida de barra que reverte (ret_1<0)
    # -> sinal positivo (rejeição). extensão de alta confirmada (ret_1>0)
    # -> sinal negativo (continuação).
    ret_h_prior = np.array([0.02, 0.02])
    ret_1 = np.array([-0.01, 0.01])
    atr_20_pct = np.array([0.01, 0.01])
    out = group_b.b14_rejection_after_extension(ret_h_prior, ret_1, atr_20_pct)
    assert out[0] > 0.0  # rejeição
    assert out[1] < 0.0  # continuação


def test_b15_causalidade() -> None:
    bars = _make_ohlcv(300)
    cutoff = 150
    out_base = group_b.b15_efficiency_ratio_h3(bars["close"], window=3)

    close2 = bars["close"].copy()
    close2[cutoff + 1 :] *= 1.5
    out_perturbed = group_b.b15_efficiency_ratio_h3(close2, window=3)

    np.testing.assert_allclose(out_base[: cutoff + 1], out_perturbed[: cutoff + 1])


def test_b15_faixa_0_a_1() -> None:
    bars = _make_ohlcv(300)
    out = group_b.b15_efficiency_ratio_h3(bars["close"], window=3)
    valid = out[~np.isnan(out)]
    assert (valid >= 0.0).all()
    assert (valid <= 1.0).all()


# ============================================================================
# Lote D2 (2026-08-28, AG-372/ADR-006) -- validação da especificação de
# Candle Features: A18-A21/B16-B18.
# ============================================================================


def test_a18_causalidade() -> None:
    bars = _make_ohlcv(300)
    cutoff = 150
    out_base = group_a.a18_body_log(bars["open"], bars["close"])

    open2, close2 = bars["open"].copy(), bars["close"].copy()
    open2[cutoff + 1 :] *= 1.5
    close2[cutoff + 1 :] *= 1.5
    out_perturbed = group_a.a18_body_log(open2, close2)

    np.testing.assert_allclose(out_base[: cutoff + 1], out_perturbed[: cutoff + 1])


def test_a19_causalidade_e_flat_da_zero() -> None:
    bars = _make_ohlcv(300)
    cutoff = 150
    out_base = group_a.a19_log_range(bars["high"], bars["low"])

    high2, low2 = bars["high"].copy(), bars["low"].copy()
    high2[cutoff + 1 :] *= 1.5
    low2[cutoff + 1 :] *= 1.5
    out_perturbed = group_a.a19_log_range(high2, low2)
    np.testing.assert_allclose(out_base[: cutoff + 1], out_perturbed[: cutoff + 1])

    flat = np.full(5, 100.0)
    assert np.allclose(group_a.a19_log_range(flat, flat), 0.0)


def test_a20_causalidade_e_log1p_de_zero() -> None:
    rng = np.random.default_rng(21)
    n = 300
    open_time = np.cumsum(rng.uniform(500, 5000, n))
    close_time = open_time + rng.uniform(0, 3000, n)
    cutoff = 150
    out_base = group_a.a20_log_duration(open_time, close_time)

    open_time2, close_time2 = open_time.copy(), close_time.copy()
    open_time2[cutoff + 1 :] += 10_000.0
    close_time2[cutoff + 1 :] += 10_000.0
    out_perturbed = group_a.a20_log_duration(open_time2, close_time2)
    np.testing.assert_allclose(out_base[: cutoff + 1], out_perturbed[: cutoff + 1])

    assert group_a.a20_log_duration(np.array([0.0]), np.array([0.0]))[0] == 0.0


def test_a21_causalidade_e_guarda_duracao_zero() -> None:
    rng = np.random.default_rng(23)
    n = 300
    quote_volume = rng.uniform(1000.0, 50_000.0, n)
    duration_s = rng.uniform(0.1, 30.0, n)
    cutoff = 150
    out_base = group_a.a21_log_dollar_velocity(quote_volume, duration_s)

    qv2, dur2 = quote_volume.copy(), duration_s.copy()
    qv2[cutoff + 1 :] *= 5.0
    dur2[cutoff + 1 :] *= 5.0
    out_perturbed = group_a.a21_log_dollar_velocity(qv2, dur2)
    np.testing.assert_allclose(out_base[: cutoff + 1], out_perturbed[: cutoff + 1])

    # duração=0 (barra de 1 trade instantâneo) -- NaN, nunca inf.
    out_guard = group_a.a21_log_dollar_velocity(np.array([100.0]), np.array([0.0]))
    assert np.isnan(out_guard[0])


def test_b16_causalidade_e_guarda_range_zero() -> None:
    bars = _make_ohlcv(300)
    cutoff = 150
    out_base = group_b.b16_log_range_ratio_1(bars["high"], bars["low"], lag_bars=1)

    high2, low2 = bars["high"].copy(), bars["low"].copy()
    high2[cutoff + 1 :] *= 1.5
    low2[cutoff + 1 :] *= 1.5
    out_perturbed = group_b.b16_log_range_ratio_1(high2, low2, lag_bars=1)
    np.testing.assert_allclose(out_base[: cutoff + 1], out_perturbed[: cutoff + 1])

    # 2ª barra flat (range=0) -- razão indefinida, precisa virar NaN.
    high_flat = np.array([100.0, 100.0, 101.0])
    low_flat = np.array([99.0, 100.0, 99.0])
    out_guard = group_b.b16_log_range_ratio_1(high_flat, low_flat, lag_bars=1)
    assert np.isnan(out_guard[1])  # range[1]=0
    assert np.isnan(out_guard[2])  # range_prev=range[1]=0


def test_b17_causalidade_e_guarda_soma_body_zero() -> None:
    bars = _make_ohlcv(300)
    cutoff = 150
    out_base = group_b.b17_directional_pressure_h3(bars["open"], bars["close"], window=3)

    open2, close2 = bars["open"].copy(), bars["close"].copy()
    open2[cutoff + 1 :] *= 1.5
    close2[cutoff + 1 :] *= 1.5
    out_perturbed = group_b.b17_directional_pressure_h3(open2, close2, window=3)
    np.testing.assert_allclose(out_base[: cutoff + 1], out_perturbed[: cutoff + 1])

    # 3 barras de corpo exatamente zero (doji triplo) -- denom=0 -> NaN.
    open_flat = np.array([100.0, 100.0, 100.0])
    close_flat = np.array([100.0, 100.0, 100.0])
    out_guard = group_b.b17_directional_pressure_h3(open_flat, close_flat, window=3)
    assert np.isnan(out_guard[2])


def test_b18_causalidade() -> None:
    bars = _make_ohlcv(300)
    atr_abs = support.atr_wilder(bars["high"], bars["low"], bars["close"], window=20)
    cutoff = 150
    out_base = group_b.b18_engulfing_atr(bars["open"], bars["close"], atr_abs)

    open2, close2 = bars["open"].copy(), bars["close"].copy()
    open2[cutoff + 1 :] *= 1.5
    close2[cutoff + 1 :] *= 1.5
    atr_abs2 = support.atr_wilder(bars["high"], bars["low"], close2, window=20)
    out_perturbed = group_b.b18_engulfing_atr(open2, close2, atr_abs2)

    np.testing.assert_allclose(out_base[: cutoff + 1], out_perturbed[: cutoff + 1])


def test_b18_sinaliza_engolfo_e_continuacao_corretamente() -> None:
    # t-1 de baixa, t de alta com corpo MAIOR (em unidades de ATR) -> engolfo
    # (sinal positivo grande). t-1 e t mesma direção -> continuação (negativo).
    open_ = np.array([100.0, 95.0])
    close = np.array([95.0, 102.0])  # barra 0: corpo -5; barra 1: corpo +7
    atr_abs = np.array([5.0, 5.0])
    out = group_b.b18_engulfing_atr(open_, close, atr_abs)
    assert out[1] > 0.0  # engolfo real (reverte e supera em módulo)


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
    out_base = group_e.e11f_oi_change_z_1d(oi, lag_bars=48, zscore_window=48)

    oi2 = oi.copy()
    oi2[cutoff + 1 :] *= 1.2
    out_perturbed = group_e.e11f_oi_change_z_1d(oi2, lag_bars=48, zscore_window=48)
    np.testing.assert_allclose(out_base[: cutoff + 1], out_perturbed[: cutoff + 1])


def test_e11f_reproduz_delta_bruto_mais_zscore_rolante() -> None:
    """Corrigido 2026-08-27 (`AG-320`): `e11f_oi_change_z_1d` normaliza o
    delta bruto de `lag_bars` barras por z-score rolante (mesmo padrão de
    `e10f_oi_change_z_48`) -- prova de valor conhecido/composição das duas
    primitivas já testadas separadamente."""
    rng = np.random.default_rng(59)
    oi = 90_000.0 + np.cumsum(rng.normal(0, 200, 300))
    out = group_e.e11f_oi_change_z_1d(oi, lag_bars=48, zscore_window=48)

    log_oi = np.log(oi)
    raw_delta = np.full(300, np.nan)
    raw_delta[48:] = log_oi[48:] - log_oi[:-48]
    expected = support.rolling_zscore(raw_delta, 48)
    np.testing.assert_array_equal(out, expected)


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


# K08_days_since_halving REMOVIDA 2026-08-26 (AG-263, ADR-005 §11.4 item 3)
# -- testes de group_k.k08_days_since_halving removidos junto com a função.

# ============================================================================
# Lote B da liberação de features (H5, 2026-08-24) — A15, B10, C08, D07f,
# D10f, E03f. Todas T2 (§0.2 R4/§2.13, nenhuma promovida a T1).
# ============================================================================


def test_a15_causalidade_e_reset_diario() -> None:
    n = 150
    bars = _make_ohlcv(n)
    # barras de 15m consecutivas reais -- 96 barras/dia (24h), então a
    # barra de índice 96 é a 1ª do 2º dia UTC.
    close_time_ms = np.arange(n, dtype=np.float64) * 900_000.0 + 899_999.0
    atr_abs = support.atr_wilder(bars["high"], bars["low"], bars["close"], window=20)
    out = group_a.a15_dist_vwap_d_atr(
        bars["high"], bars["low"], bars["close"], bars["volume"], close_time_ms, atr_abs
    )

    boundary = 96
    day_id = close_time_ms.astype(np.int64) // 86_400_000
    assert day_id[boundary] != day_id[boundary - 1]  # confirma que É de fato a fronteira
    # na 1ª barra do dia novo, VWAP == preço típico DELA MESMA (acumulação
    # reiniciada, não carrega nada do dia anterior) -- reconstrói VWAP
    # invertendo (C-VWAP)/ATR = out.
    typical_price_boundary = (
        bars["high"][boundary] + bars["low"][boundary] + bars["close"][boundary]
    ) / 3.0
    vwap_boundary = bars["close"][boundary] - out[boundary] * atr_abs[boundary]
    assert vwap_boundary == pytest.approx(typical_price_boundary)

    cutoff = 100  # dentro do 2º dia (>= 96), perturbação não cruza fronteira de dia
    high2, low2, close2 = bars["high"].copy(), bars["low"].copy(), bars["close"].copy()
    high2[cutoff + 1 :] *= 1.5
    low2[cutoff + 1 :] *= 1.5
    close2[cutoff + 1 :] *= 1.5
    atr_abs2 = support.atr_wilder(high2, low2, close2, window=20)
    out_perturbed = group_a.a15_dist_vwap_d_atr(
        high2, low2, close2, bars["volume"], close_time_ms, atr_abs2
    )
    np.testing.assert_allclose(out[: cutoff + 1], out_perturbed[: cutoff + 1])


def test_b10_faixa_0_100_e_causalidade() -> None:
    bars = _make_ohlcv(200)
    out = group_b.b10_stoch_k_14(bars["high"], bars["low"], bars["close"], window=14)
    valid = out[~np.isnan(out)]
    assert valid.shape[0] > 0
    assert (valid >= -1e-9).all() and (valid <= 100.0 + 1e-9).all()

    cutoff = 100
    high2, low2, close2 = bars["high"].copy(), bars["low"].copy(), bars["close"].copy()
    high2[cutoff + 1 :] *= 1.5
    low2[cutoff + 1 :] *= 1.5
    close2[cutoff + 1 :] *= 1.5
    out_perturbed = group_b.b10_stoch_k_14(high2, low2, close2, window=14)
    np.testing.assert_allclose(out[: cutoff + 1], out_perturbed[: cutoff + 1])


def test_c08_reproduz_realized_vol_mais_rolling_rank_por_tempo() -> None:
    """Corrigido 2026-08-27 (`AG-317`): C08 v2 ancora a janela em TEMPO
    (`rolling_percentile_rank_strict_by_time`), não em contagem de barras.
    Sob barras equidistantes (caso deste teste), `window_ms = outer_window
    * duracao_bar_ms` é exatamente equivalente à janela de contagem antiga
    — mesma prova de `test_rolling_percentile_rank_strict_by_time_bate_com_
    bar_count_equidistante` em `test_features_support.py`, aplicada ao
    nível da feature completa."""
    bars = _make_ohlcv(300)
    log_ret = _log_return_1(bars["close"])
    bar_duration_ms = 900_000.0  # 15 minutos, constante
    close_time_ms = np.arange(300, dtype=np.float64) * bar_duration_ms
    out = group_c.c08_vol_pctile_rolling_1y(
        log_ret, close_time_ms, inner_window=12, outer_window_ms=int(48 * bar_duration_ms)
    )
    rv = support.realized_vol(log_ret, 12)
    expected = support.rolling_percentile_rank_strict(rv, 48)
    np.testing.assert_array_equal(out, expected)
    valid = out[~np.isnan(out)]
    assert valid.shape[0] > 0
    assert (valid >= 0.0).all() and (valid <= 1.0).all()


def test_d07f_causalidade_e_agregacao() -> None:
    """Núcleo puro (groupby-mean por bucket) — causalidade é estrutural
    por construção (cada bucket de 15m só agrega barras de 1m com o
    MESMO bucket_id, nunca outro), não uma propriedade de janela
    perturbável — prova aqui é de FÓRMULA (valor calculado à mão), não
    de perturbação como as demais."""
    bucket_id_1m = np.array([0, 0, 0, 1, 1], dtype=np.int64)
    taker_buy_volume_1m = np.array([4.0, 3.0, 4.0, 1.0, 1.0])
    volume_1m = np.array([4.0, 4.0, 4.0, 4.0, 2.0])
    bucket_id_15m = np.array([0, 1, 2], dtype=np.int64)

    out = group_d.d07f_taker_imbalance_1m_agg(
        taker_buy_volume_1m, volume_1m, bucket_id_1m, bucket_id_15m
    )
    # bucket 0: ratios=[1.0,0.75,1.0] -> imbalance=[1.0,0.5,1.0] -> média
    assert out[0] == pytest.approx((1.0 + 0.5 + 1.0) / 3.0)
    # bucket 1: ratios=[0.25,0.5] -> imbalance=[-0.5,0.0] -> média
    assert out[1] == pytest.approx((-0.5 + 0.0) / 2.0)
    assert np.isnan(out[2])  # bucket sem nenhuma barra de 1m correspondente -> NaN, não inventado


def test_d10f_causalidade() -> None:
    bars = _make_ohlcv(300)
    log_ret = _log_return_1(bars["close"])
    cutoff = 150
    out_base = group_d.d10f_vol_price_divergence(log_ret, bars["volume"], window=48)

    log_ret2 = log_ret.copy()
    volume2 = bars["volume"].copy()
    log_ret2[cutoff + 1 :] = log_ret2[cutoff + 1 :] * 5.0 + 0.1
    volume2[cutoff + 1 :] *= 3.0
    out_perturbed = group_d.d10f_vol_price_divergence(log_ret2, volume2, window=48)
    np.testing.assert_allclose(out_base[: cutoff + 1], out_perturbed[: cutoff + 1])


def test_d10f_faixa_menos1_1() -> None:
    bars = _make_ohlcv(300)
    log_ret = _log_return_1(bars["close"])
    out = group_d.d10f_vol_price_divergence(log_ret, bars["volume"], window=48)
    valid = out[~np.isnan(out)]
    assert valid.shape[0] > 0
    assert (valid >= -1.0 - 1e-9).all() and (valid <= 1.0 + 1e-9).all()


def test_e03f_soma_por_evento_nao_por_barra() -> None:
    """3 eventos de funding DISTINTOS, cada um "visível" por 32 barras de
    15m consecutivas (mesma repetição que o asof-join backward real
    produz, 8h/32 barras) -- uma soma ingênua sobre janela de BARRAS
    contaria o mesmo valor repetidas vezes; a soma por EVENTO não pode
    (prova direta do bug que este núcleo existe pra evitar)."""
    n_bars_per_event = 32
    n_events_total = 4
    n = n_bars_per_event * n_events_total
    close_time_ms = np.arange(n, dtype=np.float64) * 900_000.0 + 899_999.0
    funding_values = [0.0001, 0.0002, -0.0001, 0.0003]
    funding_last_aligned = np.repeat(funding_values, n_bars_per_event)

    out = group_e.e03f_funding_cum_3d(
        funding_last_aligned, close_time_ms, funding_interval_hours=8, n_events=3
    )
    # só 2 eventos distintos vistos até a barra 63 (0..63) -- indefinido
    assert np.isnan(out[:64]).all()
    expected_events_012 = funding_values[0] + funding_values[1] + funding_values[2]
    assert out[64] == pytest.approx(expected_events_012)
    assert out[95] == pytest.approx(expected_events_012)  # última barra do 3º evento
    expected_events_123 = funding_values[1] + funding_values[2] + funding_values[3]
    assert out[96] == pytest.approx(expected_events_123)  # 4º evento -- 1º evento cai da janela


# ============================================================================
# Lote C da liberação de features (H5, 2026-08-24) — E08f, E14f-E18f.
# Todas T2 (§0.2 R4/§2.13, nenhuma promovida a T1).
# ============================================================================


def test_e08f_e14f_e16f_e18f_sao_passthrough() -> None:
    rng = np.random.default_rng(83)
    values = rng.normal(0, 1, 50)
    np.testing.assert_array_equal(group_e.e08f_oi_notional(values), values)
    np.testing.assert_array_equal(group_e.e14f_toptrader_ls_ratio(values), values)
    np.testing.assert_array_equal(group_e.e16f_global_ls_ratio(values), values)
    np.testing.assert_array_equal(group_e.e18f_taker_ls_vol_ratio(values), values)


def test_e15f_reproduz_expanding_zscore_strict() -> None:
    rng = np.random.default_rng(89)
    values = rng.uniform(1.0, 3.0, 150)
    out = group_e.e15f_toptrader_ls_z(values)
    expected = support.expanding_zscore_strict(values)
    np.testing.assert_array_equal(out, expected)


def test_e15f_min_common_history_bars_e_repassado_a_primitiva() -> None:
    rng = np.random.default_rng(91)
    values = rng.uniform(1.0, 3.0, 150)
    cap = 80
    out = group_e.e15f_toptrader_ls_z(values, min_common_history_bars=cap)
    expected = support.expanding_zscore_strict(values, min_common_history_bars=cap)
    np.testing.assert_array_equal(out, expected)
    assert np.isnan(out[: 150 - cap]).all()


def test_e17f_reproduz_diferenca_de_dois_zscores() -> None:
    rng = np.random.default_rng(97)
    global_ls_ratio = rng.uniform(0.5, 2.0, 150)
    toptrader_ls_ratio = rng.uniform(0.5, 2.0, 150)
    toptrader_ls_z = support.expanding_zscore_strict(toptrader_ls_ratio)

    out = group_e.e17f_retail_vs_top_spread(global_ls_ratio, toptrader_ls_z)
    expected_global_z = support.expanding_zscore_strict(global_ls_ratio)
    np.testing.assert_array_equal(out, expected_global_z - toptrader_ls_z)


def test_e17f_min_common_history_bars_afeta_so_o_lado_global() -> None:
    """`min_common_history_bars` só é repassado pro z-score INTERNO
    (`global_ls_z`) — `toptrader_ls_z` chega já pronto do chamador
    (`E15f`, calculado com seu próprio cap, se houver), não é
    recalculado aqui."""
    rng = np.random.default_rng(101)
    global_ls_ratio = rng.uniform(0.5, 2.0, 150)
    toptrader_ls_z = rng.normal(0, 1, 150)  # já "pronto", valor arbitrário pro teste
    cap = 90

    out = group_e.e17f_retail_vs_top_spread(
        global_ls_ratio, toptrader_ls_z, min_common_history_bars=cap
    )
    expected_global_z = support.expanding_zscore_strict(
        global_ls_ratio, min_common_history_bars=cap
    )
    np.testing.assert_array_equal(out, expected_global_z - toptrader_ls_z)
