"""Testes do max-T de horizonte (`src.analysis.
eixo1_maxt_horizon_permutation`, `AG-327`).

Todo o módulo é núcleo puro (zero IO) -- inclusive `horizon_maxt_p_value`,
que faz um laço de permutação mas só sobre arrays já em memória."""

from __future__ import annotations

import math

import numpy as np
import pytest

from src.analysis import eixo1_maxt_horizon_permutation as maxt

# ============================================================================
# max_abs_spearman_over_horizons
# ============================================================================


def test_max_abs_spearman_over_horizons_pega_o_maior() -> None:
    rng = np.random.default_rng(0)
    n = 2000
    ref_forte = rng.standard_normal(n)
    feature = 0.4 * ref_forte + math.sqrt(1 - 0.4**2) * rng.standard_normal(n)
    ref_fraca = rng.standard_normal(n)  # independente de feature
    stat = maxt.max_abs_spearman_over_horizons(feature, {1: ref_forte, 2: ref_fraca})
    assert stat > 0.2  # deve capturar o horizonte forte, nao a media dos dois


def test_max_abs_spearman_over_horizons_sem_pontos_validos_e_nan() -> None:
    feature = np.array([1.0, 2.0, 3.0])
    fwd_by_h = {1: np.array([np.nan, np.nan, np.nan])}
    assert math.isnan(maxt.max_abs_spearman_over_horizons(feature, fwd_by_h))


def test_max_abs_spearman_over_horizons_levanta_com_shape_diferente() -> None:
    feature = np.zeros(10)
    fwd_by_h = {1: np.zeros(5)}
    with pytest.raises(maxt.Eixo1MaxTError, match="shape"):
        maxt.max_abs_spearman_over_horizons(feature, fwd_by_h)


# ============================================================================
# horizon_maxt_p_value
# ============================================================================


def test_horizon_maxt_p_value_levanta_com_serie_curta_demais() -> None:
    feature = np.arange(50, dtype=np.float64)
    fwd_by_h = {1: np.arange(50, dtype=np.float64)}
    with pytest.raises(maxt.Eixo1MaxTError, match="curta demais"):
        maxt.horizon_maxt_p_value(feature, fwd_by_h, min_shift_bars=96, seed=1, n_permutations=10)


def test_horizon_maxt_p_value_observado_nan_propaga_p_nan() -> None:
    feature = np.full(500, np.nan)
    fwd_by_h = {1: np.arange(500, dtype=np.float64)}
    observado, p_value = maxt.horizon_maxt_p_value(
        feature, fwd_by_h, min_shift_bars=50, seed=2, n_permutations=20
    )
    assert math.isnan(observado)
    assert math.isnan(p_value)


def test_horizon_maxt_p_value_sinal_forte_da_p_pequeno() -> None:
    """Feature fortemente correlacionada de verdade com o retorno futuro --
    o p-valor por permutacao deve ficar bem abaixo de 0,05."""
    rng = np.random.default_rng(3)
    n = 3000
    ref = rng.standard_normal(n)
    feature = 0.5 * ref + math.sqrt(1 - 0.5**2) * rng.standard_normal(n)
    fwd_by_h = {1: ref, 2: rng.standard_normal(n), 4: rng.standard_normal(n)}
    observado, p_value = maxt.horizon_maxt_p_value(
        feature, fwd_by_h, min_shift_bars=100, seed=4, n_permutations=200
    )
    assert observado > 0.3
    assert p_value < 0.05


def test_horizon_maxt_p_value_e_sempre_um_valor_valido_no_intervalo() -> None:
    """Propriedade que vale para QUALQUER sorteio, sem depender de um
    resultado probabilistico especifico (evita teste flaky): o p-valor cai
    em [1/(n_permutations+1), 1], nunca fora do intervalo, nunca None/NaN
    quando o observado e finito."""
    rng = np.random.default_rng(5)
    n = 2000
    fwd_by_h = {
        1: rng.standard_normal(n),
        2: rng.standard_normal(n),
        4: rng.standard_normal(n),
    }
    feature = rng.standard_normal(n)
    n_perm = 200
    observado, p_value = maxt.horizon_maxt_p_value(
        feature, fwd_by_h, min_shift_bars=100, seed=6, n_permutations=n_perm
    )
    assert math.isfinite(observado)
    assert 1.0 / (n_perm + 1) <= p_value <= 1.0


def test_horizon_maxt_p_value_e_deterministico_para_a_mesma_semente() -> None:
    """Mesma entrada + mesma semente -- mesmo resultado, bit-exato (nucleo
    puro, sem estado global)."""
    rng = np.random.default_rng(9)
    n = 1500
    ref = rng.standard_normal(n)
    feature = 0.1 * ref + math.sqrt(1 - 0.1**2) * rng.standard_normal(n)
    fwd_by_h = {1: ref, 2: rng.standard_normal(n)}
    r1 = maxt.horizon_maxt_p_value(feature, fwd_by_h, min_shift_bars=80, seed=42, n_permutations=50)
    r2 = maxt.horizon_maxt_p_value(feature, fwd_by_h, min_shift_bars=80, seed=42, n_permutations=50)
    assert r1 == r2


def test_horizon_maxt_p_value_add_one_nunca_e_zero() -> None:
    """Mesmo com sinal extremo (deveria zerar count_ge), a correcao
    add-one garante p_value > 0."""
    rng = np.random.default_rng(7)
    n = 3000
    ref = rng.standard_normal(n)
    feature = ref.copy()  # correlacao quase perfeita
    fwd_by_h = {1: ref}
    _observado, p_value = maxt.horizon_maxt_p_value(
        feature, fwd_by_h, min_shift_bars=100, seed=8, n_permutations=50
    )
    assert p_value > 0.0
    assert p_value == pytest.approx(1.0 / 51.0)
