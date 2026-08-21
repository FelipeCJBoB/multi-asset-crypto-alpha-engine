"""Testes de `src/features/support.py` — as primitivas causais. Cada função
tem três provas exigidas por §2.0/§2.15: (1) valor numérico correto num
exemplo pequeno calculado à mão; (2) causalidade — mudar o futuro não muda
o passado; (3) determinismo — mesma entrada, mesma saída, sempre."""

from __future__ import annotations

import numpy as np
import pytest

from src.features import support


def _assert_causal(fn, base: np.ndarray, cutoff: int, **kwargs: object) -> None:
    """Prova genérica de causalidade (banned pattern B01/B02): perturba
    `base` a partir de `cutoff+1` (exclusive) e confirma que a saída de
    `fn` em `[0, cutoff]` não muda — se mudasse, `fn` estaria olhando para
    o futuro em algum índice `<= cutoff`."""
    out_base = fn(base, **kwargs)
    perturbed = base.copy()
    perturbed[cutoff + 1 :] = perturbed[cutoff + 1 :] * 3.7 + 991.0
    out_perturbed = fn(perturbed, **kwargs)
    np.testing.assert_array_equal(out_base[: cutoff + 1], out_perturbed[: cutoff + 1])


# ============================================================================
# true_range / wilder_smooth / atr_wilder
# ============================================================================


def test_true_range_valor_conhecido() -> None:
    high = np.array([10.0, 12.0, 11.0, 13.0])
    low = np.array([9.0, 10.0, 9.5, 11.5])
    close = np.array([9.5, 11.5, 10.0, 12.5])
    tr = support.true_range(high, low, close)
    assert tr[0] == pytest.approx(1.0)  # H-L, sem close anterior
    # t=1: max(12-10, |12-9.5|, |10-9.5|) = max(2, 2.5, 0.5) = 2.5
    assert tr[1] == pytest.approx(2.5)
    # t=2: max(11-9.5, |11-11.5|, |9.5-11.5|) = max(1.5, 0.5, 2.0) = 2.0
    assert tr[2] == pytest.approx(2.0)


def test_wilder_smooth_seed_e_recursao() -> None:
    values = np.array([1.0, 2.0, 3.0, 4.0, 6.0, 8.0])
    window = 3
    out = support.wilder_smooth(values, window)
    assert np.isnan(out[0]) and np.isnan(out[1])
    seed = (1.0 + 2.0 + 3.0) / 3.0
    assert out[2] == pytest.approx(seed)
    expected_3 = (seed * 2 + 4.0) / 3.0
    assert out[3] == pytest.approx(expected_3)
    expected_4 = (expected_3 * 2 + 6.0) / 3.0
    assert out[4] == pytest.approx(expected_4)


def test_wilder_smooth_janela_maior_que_serie_retorna_tudo_nan() -> None:
    values = np.array([1.0, 2.0, 3.0])
    out = support.wilder_smooth(values, window=10)
    assert np.isnan(out).all()


def test_atr_wilder_causalidade() -> None:
    rng = np.random.default_rng(42)
    n = 60
    close = 100.0 + np.cumsum(rng.normal(0, 1, n))
    high = close + rng.uniform(0.1, 1.0, n)
    low = close - rng.uniform(0.1, 1.0, n)

    def fn(c: np.ndarray) -> np.ndarray:
        return support.atr_wilder(high, low, c, window=14)

    _assert_causal(fn, close, cutoff=30)


def test_atr_wilder_determinismo() -> None:
    high = np.array([10.0, 12.0, 11.0, 13.0, 14.0, 15.0])
    low = np.array([9.0, 10.0, 9.5, 11.5, 12.0, 13.0])
    close = np.array([9.5, 11.5, 10.0, 12.5, 13.5, 14.5])
    out1 = support.atr_wilder(high, low, close, window=3)
    out2 = support.atr_wilder(high, low, close, window=3)
    np.testing.assert_array_equal(out1, out2)


# ============================================================================
# ema
# ============================================================================


def test_ema_converge_para_valor_constante() -> None:
    values = np.full(200, 42.0)
    out = support.ema(values, span=10)
    assert out[-1] == pytest.approx(42.0)


def test_ema_causalidade() -> None:
    rng = np.random.default_rng(7)
    values = 100.0 + np.cumsum(rng.normal(0, 1, 80))

    def fn(v: np.ndarray) -> np.ndarray:
        return support.ema(v, span=12)

    _assert_causal(fn, values, cutoff=40)


# ============================================================================
# rsi_wilder
# ============================================================================


def test_rsi_wilder_todo_ganho_da_100() -> None:
    close = np.arange(1.0, 40.0)  # estritamente crescente
    rsi = support.rsi_wilder(close, window=14)
    assert rsi[-1] == pytest.approx(100.0)


def test_rsi_wilder_todo_flat_da_50() -> None:
    close = np.full(40, 50.0)
    rsi = support.rsi_wilder(close, window=14)
    assert rsi[-1] == pytest.approx(50.0)


def test_rsi_wilder_faixa_0_100() -> None:
    rng = np.random.default_rng(3)
    close = 100.0 + np.cumsum(rng.normal(0, 1, 300))
    rsi = support.rsi_wilder(close, window=14)
    valid = rsi[~np.isnan(rsi)]
    assert (valid >= 0.0).all() and (valid <= 100.0).all()


def test_rsi_wilder_causalidade() -> None:
    rng = np.random.default_rng(11)
    close = 100.0 + np.cumsum(rng.normal(0, 1, 100))

    def fn(c: np.ndarray) -> np.ndarray:
        return support.rsi_wilder(c, window=14)

    _assert_causal(fn, close, cutoff=50)


# ============================================================================
# realized_vol / rolling_zscore / efficiency_ratio
# ============================================================================


def test_realized_vol_serie_constante_da_zero() -> None:
    log_ret = np.zeros(50)
    out = support.realized_vol(log_ret, window=10)
    valid = out[~np.isnan(out)]
    assert np.allclose(valid, 0.0)


def test_realized_vol_causalidade() -> None:
    rng = np.random.default_rng(5)
    log_ret = rng.normal(0, 0.01, 80)

    def fn(v: np.ndarray) -> np.ndarray:
        return support.realized_vol(v, window=12)

    _assert_causal(fn, log_ret, cutoff=40)


# ============================================================================
# downside_deviation (AG-119 -- espaço de observação estendido do Jump Model)
# ============================================================================


def test_downside_deviation_serie_so_positiva_da_zero() -> None:
    log_ret = np.abs(np.random.default_rng(1).normal(0, 0.01, 50)) + 0.001
    out = support.downside_deviation(log_ret, window=10)
    valid = out[~np.isnan(out)]
    assert np.allclose(valid, 0.0)


def test_downside_deviation_valor_conhecido_a_mao() -> None:
    # janela de 4 retornos: [-0.02, 0.01, -0.01, 0.03] -- só os negativos
    # entram no quadrado (positivos contam como 0): mean([0.02^2, 0, 0.01^2, 0]) = 0.000125
    log_ret = np.array([-0.02, 0.01, -0.01, 0.03])
    out = support.downside_deviation(log_ret, window=4)
    assert out[-1] == pytest.approx(np.sqrt(0.000125))
    assert np.isnan(out[:3]).all()  # janela incompleta antes do índice 3


def test_downside_deviation_causalidade() -> None:
    rng = np.random.default_rng(6)
    log_ret = rng.normal(0, 0.01, 80)

    def fn(v: np.ndarray) -> np.ndarray:
        return support.downside_deviation(v, window=12)

    _assert_causal(fn, log_ret, cutoff=40)


def test_downside_deviation_nunca_nan_por_cancelamento_de_ponto_flutuante() -> None:
    """AG-119, 2026-08-20 -- achado real: `mean_sq` (média de quadrados,
    matematicamente nunca negativa) saía como `-3,16e-20` por
    cancelamento de ponto flutuante em janelas quase todas positivas
    (30 barras reais de XRPUSDT/R1 afetadas), e `np.sqrt` desse negativo
    devolvia `NaN` silencioso. Reproduz com escala realista de
    log-retorno (~1e-4, mesma ordem de grandeza de dollar-bar real) e
    N grande o suficiente pra cancelamento de ponto flutuante ser
    plausível -- invariante: NENHUM `NaN` fora do prefixo de warmup
    (`window-1` primeiras posições), nunca no meio da série."""
    rng = np.random.default_rng(42)
    log_ret = rng.normal(0.0, 1e-4, 50_000)
    window = 12
    out = support.downside_deviation(log_ret, window=window)
    assert not np.isnan(out[window - 1 :]).any()


# ============================================================================
# parkinson_vol / garman_klass_vol (PRD_V4_1.md §3.2 M1)
# ============================================================================


def test_parkinson_vol_barra_constante_da_zero() -> None:
    # high == low em toda barra -> ln(H/L) = 0 em toda barra -> vol = 0
    high = np.full(30, 100.0)
    low = np.full(30, 100.0)
    out = support.parkinson_vol(high, low, window=10)
    valid = out[~np.isnan(out)]
    assert np.allclose(valid, 0.0)


def test_parkinson_vol_causalidade() -> None:
    rng = np.random.default_rng(11)
    n = 60
    close = 100.0 + np.cumsum(rng.normal(0, 1, n))
    low = close - rng.uniform(0.1, 1.0, n)

    def fn(high: np.ndarray) -> np.ndarray:
        return support.parkinson_vol(high, low, window=14)

    high_base = close + rng.uniform(0.1, 1.0, n)
    _assert_causal(fn, high_base, cutoff=30)


def test_parkinson_vol_warmup_e_janela_menos_um_nan() -> None:
    high = np.array([10.0, 12.0, 11.0, 13.0, 14.0, 15.0])
    low = np.array([9.0, 10.0, 9.5, 11.5, 12.0, 13.0])
    out = support.parkinson_vol(high, low, window=3)
    assert np.isnan(out[:2]).all()
    assert not np.isnan(out[2:]).any()


def test_garman_klass_vol_barra_constante_da_zero() -> None:
    high = np.full(30, 100.0)
    low = np.full(30, 100.0)
    open_ = np.full(30, 100.0)
    close = np.full(30, 100.0)
    out = support.garman_klass_vol(high, low, open_, close, window=10)
    valid = out[~np.isnan(out)]
    assert np.allclose(valid, 0.0)


def test_garman_klass_vol_causalidade() -> None:
    rng = np.random.default_rng(12)
    n = 60
    close = 100.0 + np.cumsum(rng.normal(0, 1, n))
    low = close - rng.uniform(0.1, 1.0, n)
    open_ = close + rng.normal(0, 0.05, n)

    def fn(high: np.ndarray) -> np.ndarray:
        return support.garman_klass_vol(high, low, open_, close, window=14)

    high_base = close + rng.uniform(0.1, 1.0, n)
    _assert_causal(fn, high_base, cutoff=30)


def test_rolling_zscore_causalidade() -> None:
    rng = np.random.default_rng(9)
    values = rng.normal(0, 1, 100)

    def fn(v: np.ndarray) -> np.ndarray:
        return support.rolling_zscore(v, window=20)

    _assert_causal(fn, values, cutoff=50)


def test_efficiency_ratio_movimento_puro_da_1() -> None:
    close = np.arange(1.0, 60.0)  # trend puro, sem reversão
    out = support.efficiency_ratio(close, window=48)
    valid = out[~np.isnan(out)]
    assert np.allclose(valid, 1.0)


def test_efficiency_ratio_faixa_0_1() -> None:
    rng = np.random.default_rng(13)
    close = 100.0 + np.cumsum(rng.normal(0, 1, 200))
    out = support.efficiency_ratio(close, window=48)
    valid = out[~np.isnan(out)]
    assert (valid >= 0.0).all() and (valid <= 1.0 + 1e-9).all()


def test_efficiency_ratio_causalidade() -> None:
    rng = np.random.default_rng(17)
    close = 100.0 + np.cumsum(rng.normal(0, 1, 150))

    def fn(c: np.ndarray) -> np.ndarray:
        return support.efficiency_ratio(c, window=48)

    _assert_causal(fn, close, cutoff=100)


# ============================================================================
# expanding_zscore_strict — B02: índice < t, nunca <= t
# ============================================================================


def test_expanding_zscore_strict_primeiros_dois_sao_nan() -> None:
    values = np.array([1.0, 2.0, 3.0, 4.0])
    out = support.expanding_zscore_strict(values)
    assert np.isnan(out[0]) and np.isnan(out[1])


def test_expanding_zscore_strict_valor_conhecido() -> None:
    values = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    out = support.expanding_zscore_strict(values)
    # em t=2: média/desvio de [1,2] -> média=1.5, desvio(ddof=1)=0.70710678
    assert out[2] == pytest.approx((3.0 - 1.5) / np.std([1.0, 2.0], ddof=1))
    # em t=3: média/desvio de [1,2,3]
    prior = np.array([1.0, 2.0, 3.0])
    assert out[3] == pytest.approx((4.0 - prior.mean()) / prior.std(ddof=1))


def test_expanding_zscore_strict_nao_usa_indice_t() -> None:
    """A prova mais direta de B02: mudar SÓ o valor em t não pode mudar
    z_t se z_t não incluísse t na normalização... mas z_t É função de x_t
    (numerador). O teste real é: mudar x_t não muda z em índices ANTERIORES
    a t, e mudar x_t não muda a MÉDIA/DESVIO usados para calcular o próprio
    z_t (ou seja, z_t não pode ser reproduzido incluindo x_t na janela de
    referência) — verificado indiretamente comparando contra um cálculo de
    referência que usa explicitamente `values[:t]`."""
    rng = np.random.default_rng(21)
    values = rng.normal(0, 1, 30)
    out = support.expanding_zscore_strict(values)
    for t in range(2, len(values)):
        prior = values[:t]
        expected = (values[t] - prior.mean()) / prior.std(ddof=1)
        assert out[t] == pytest.approx(expected), f"t={t}"


def test_expanding_zscore_strict_causalidade() -> None:
    rng = np.random.default_rng(23)
    values = rng.normal(0, 1, 60)

    def fn(v: np.ndarray) -> np.ndarray:
        return support.expanding_zscore_strict(v)

    _assert_causal(fn, values, cutoff=30)


def test_expanding_zscore_strict_determinismo() -> None:
    values = np.array([1.0, 5.0, 2.0, 9.0, 3.0, 7.0])
    out1 = support.expanding_zscore_strict(values)
    out2 = support.expanding_zscore_strict(values)
    np.testing.assert_array_equal(out1, out2)


# ============================================================================
# expanding_percentile_rank_strict — B02
# ============================================================================


def test_expanding_percentile_rank_strict_primeiro_ponto_e_nan() -> None:
    values = np.array([5.0, 1.0, 9.0])
    out = support.expanding_percentile_rank_strict(values)
    assert np.isnan(out[0])


def test_expanding_percentile_rank_strict_valor_conhecido() -> None:
    # série estritamente crescente: cada novo ponto é o MAIOR já visto,
    # então o posto deveria ser sempre 1.0 (100% dos pontos prévios são
    # menores).
    values = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    out = support.expanding_percentile_rank_strict(values)
    assert out[1] == pytest.approx(1.0)
    assert out[2] == pytest.approx(1.0)
    assert out[4] == pytest.approx(1.0)


def test_expanding_percentile_rank_strict_decrescente_da_zero() -> None:
    values = np.array([5.0, 4.0, 3.0, 2.0, 1.0])
    out = support.expanding_percentile_rank_strict(values)
    assert out[1] == pytest.approx(0.0)
    assert out[4] == pytest.approx(0.0)


def test_expanding_percentile_rank_strict_nao_usa_indice_t() -> None:
    rng = np.random.default_rng(29)
    values = rng.normal(0, 1, 40)
    out = support.expanding_percentile_rank_strict(values)
    for t in range(1, len(values)):
        prior = values[:t]
        expected = float(np.mean(prior < values[t]))
        # tie-break por ordem de chegada aproxima empates a "menor" — sem
        # empates de float aleatório contínuo, a igualdade deve ser exata.
        assert out[t] == pytest.approx(expected), f"t={t}"


def test_expanding_percentile_rank_strict_causalidade() -> None:
    rng = np.random.default_rng(31)
    values = rng.normal(0, 1, 60)

    def fn(v: np.ndarray) -> np.ndarray:
        return support.expanding_percentile_rank_strict(v)

    _assert_causal(fn, values, cutoff=30)


def test_expanding_percentile_rank_strict_com_nan_intercalado() -> None:
    values = np.array([1.0, np.nan, 3.0, 2.0, np.nan, 5.0])
    out = support.expanding_percentile_rank_strict(values)
    assert np.isnan(out[1])  # NaN nunca recebe posto
    assert np.isnan(out[4])
    # posto em t=3 (valor 2.0) usa só {1.0, 3.0} (não-NaN prévios): 1 de 2 é menor
    assert out[3] == pytest.approx(0.5)


# ============================================================================
# min_common_history_bars — AG-030 (T0.5, Opção A): cap no histórico comum
# entre os 5 ativos, aplicado às DUAS primitivas expansivas. `None` (default)
# preserva bit-exato o comportamento testado acima; os testes abaixo cobrem
# só o comportamento NOVO do parâmetro.
# ============================================================================


def test_expanding_zscore_strict_min_common_history_bars_none_ou_folgado_e_bit_exato() -> None:
    rng = np.random.default_rng(61)
    values = rng.normal(0, 1, 30)
    baseline = support.expanding_zscore_strict(values)
    # None explícito == omitir o kwarg (default já testado acima)
    assert np.array_equal(
        support.expanding_zscore_strict(values, min_common_history_bars=None),
        baseline,
        equal_nan=True,
    )
    # cap >= len(values): não há o que truncar, resultado idêntico ao sem cap
    assert np.array_equal(
        support.expanding_zscore_strict(values, min_common_history_bars=30),
        baseline,
        equal_nan=True,
    )
    assert np.array_equal(
        support.expanding_zscore_strict(values, min_common_history_bars=1000),
        baseline,
        equal_nan=True,
    )


def test_expanding_zscore_strict_min_common_history_bars_equivale_a_cauda_isolada() -> None:
    """Truncar as primeiras `n - cap` barras e calcular deve dar EXATAMENTE
    o mesmo resultado que chamar a função sem cap só sobre a cauda — é a
    definição do mecanismo (Opção A do AG-030): recomeçar a expansão no
    novo "início", não uma segunda implementação."""
    rng = np.random.default_rng(63)
    values = rng.normal(0, 1, 40)
    cap = 15
    offset = 40 - cap
    out = support.expanding_zscore_strict(values, min_common_history_bars=cap)
    assert np.isnan(out[:offset]).all()
    expected_tail = support.expanding_zscore_strict(values[offset:])
    np.testing.assert_array_equal(out[offset:], expected_tail)


def test_expanding_zscore_strict_min_common_history_bars_muda_resultado_vs_sem_cap() -> None:
    """Exemplo ilustrativo direto do achado do AG-030: um outlier "de
    história antiga" (só BTC teria) distorce o z-score calculado desde a
    origem verdadeira; capado no histórico comum, o outlier some da
    distribuição de referência e o resultado muda (prova de que o cap não é
    um no-op)."""
    values = np.array([1000.0, 1.0, 2.0, 3.0, 4.0, 5.0])
    uncapped = support.expanding_zscore_strict(values)
    capped = support.expanding_zscore_strict(values, min_common_history_bars=5)
    assert np.isnan(capped[0])  # barra com o outlier antigo, excluída
    assert not np.isnan(uncapped[5]) and not np.isnan(capped[5])
    assert capped[5] != pytest.approx(uncapped[5])
    # e bate com a cauda isolada, mesma prova do teste anterior
    expected_tail = support.expanding_zscore_strict(values[1:])
    np.testing.assert_array_equal(capped[1:], expected_tail)


def test_expanding_zscore_strict_min_common_history_bars_preserva_causalidade() -> None:
    rng = np.random.default_rng(65)
    values = rng.normal(0, 1, 60)

    def fn(v: np.ndarray) -> np.ndarray:
        return support.expanding_zscore_strict(v, min_common_history_bars=25)

    _assert_causal(fn, values, cutoff=40)


def test_expanding_zscore_strict_min_common_history_bars_determinismo() -> None:
    values = np.array([1.0, 5.0, 2.0, 9.0, 3.0, 7.0, 4.0, 8.0])
    out1 = support.expanding_zscore_strict(values, min_common_history_bars=5)
    out2 = support.expanding_zscore_strict(values, min_common_history_bars=5)
    np.testing.assert_array_equal(out1, out2)


def test_expanding_percentile_rank_strict_min_common_history_bars_none_ou_folgado_e_bit_exato() -> (
    None
):
    rng = np.random.default_rng(71)
    values = rng.normal(0, 1, 30)
    baseline = support.expanding_percentile_rank_strict(values)
    assert np.array_equal(
        support.expanding_percentile_rank_strict(values, min_common_history_bars=None),
        baseline,
        equal_nan=True,
    )
    assert np.array_equal(
        support.expanding_percentile_rank_strict(values, min_common_history_bars=30),
        baseline,
        equal_nan=True,
    )
    assert np.array_equal(
        support.expanding_percentile_rank_strict(values, min_common_history_bars=1000),
        baseline,
        equal_nan=True,
    )


def test_expanding_percentile_rank_strict_min_common_history_bars_equivale_a_cauda_isolada() -> (
    None
):
    rng = np.random.default_rng(73)
    values = rng.normal(0, 1, 40)
    cap = 15
    offset = 40 - cap
    out = support.expanding_percentile_rank_strict(values, min_common_history_bars=cap)
    assert np.isnan(out[:offset]).all()
    expected_tail = support.expanding_percentile_rank_strict(values[offset:])
    np.testing.assert_array_equal(out[offset:], expected_tail)


def test_expanding_percentile_rank_strict_min_common_history_bars_muda_resultado_vs_sem_cap() -> (
    None
):
    """Mesmo exemplo do z-score: `100.0` é um valor "de história antiga" que
    só existiria pro ativo com mais barras (BTC) — sem cap, ele entra na
    distribuição de referência e abaixa o posto de toda a série crescente
    que vem depois; com cap, ele é excluído e a série recomeça do zero."""
    values = np.array([100.0, 1.0, 2.0, 3.0, 4.0, 5.0])
    uncapped = support.expanding_percentile_rank_strict(values)
    capped = support.expanding_percentile_rank_strict(values, min_common_history_bars=5)
    assert np.isnan(capped[0])
    assert uncapped[5] == pytest.approx(0.8)  # 4 de 5 prévios (100,1,2,3,4) são < 5
    assert capped[5] == pytest.approx(1.0)  # 4 de 4 prévios (1,2,3,4) são < 5 -- outlier excluído
    expected_tail = support.expanding_percentile_rank_strict(values[1:])
    np.testing.assert_array_equal(capped[1:], expected_tail)


def test_expanding_percentile_rank_strict_min_common_history_bars_preserva_causalidade() -> None:
    rng = np.random.default_rng(75)
    values = rng.normal(0, 1, 60)

    def fn(v: np.ndarray) -> np.ndarray:
        return support.expanding_percentile_rank_strict(v, min_common_history_bars=25)

    _assert_causal(fn, values, cutoff=40)


def test_expanding_percentile_rank_strict_min_common_history_bars_determinismo() -> None:
    values = np.array([5.0, 1.0, 9.0, 2.0, 7.0, 3.0, 8.0, 4.0])
    out1 = support.expanding_percentile_rank_strict(values, min_common_history_bars=5)
    out2 = support.expanding_percentile_rank_strict(values, min_common_history_bars=5)
    np.testing.assert_array_equal(out1, out2)
