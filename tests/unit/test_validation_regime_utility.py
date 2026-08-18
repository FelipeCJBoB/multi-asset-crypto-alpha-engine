"""Testes de `src/validation/regime_utility.py` — M4 (`PRD_V4_1.md` §3.2).
Casos sintéticos com resultado calculável à mão, mesmo padrão de
`test_validation_volatility_walkforward.py` (M1)."""

from __future__ import annotations

import numpy as np
import pytest

from src.validation.regime_utility import (
    adjusted_rand,
    anova_by_group,
    regime_persistence,
)

# ============================================================================
# anova_by_group
# ============================================================================


def test_anova_grupos_bem_separados_da_f_alto_omega_alto_p_baixo() -> None:
    rng = np.random.default_rng(1)
    labels = np.concatenate([np.zeros(200, dtype=np.int64), np.ones(200, dtype=np.int64)])
    response = np.concatenate([rng.normal(-5.0, 0.5, 200), rng.normal(5.0, 0.5, 200)])
    result = anova_by_group(labels, response)
    assert result.f_stat > 100.0
    assert result.omega_squared > 0.8
    assert result.p_value < 1e-6
    assert result.k_groups == 2
    assert result.n == 400


def test_anova_grupos_identicos_da_f_baixo_omega_perto_de_zero() -> None:
    rng = np.random.default_rng(2)
    labels = np.concatenate([np.zeros(300, dtype=np.int64), np.ones(300, dtype=np.int64)])
    response = rng.normal(0.0, 1.0, 600)  # mesma distribuição pros 2 grupos
    result = anova_by_group(labels, response)
    assert result.omega_squared < 0.05
    assert result.p_value > 0.01


def test_anova_filtra_nan_da_response_antes_de_calcular() -> None:
    labels = np.array([0, 0, 0, 1, 1, 1], dtype=np.int64)
    response = np.array([1.0, np.nan, 1.0, 5.0, 5.0, np.nan], dtype=np.float64)
    result = anova_by_group(labels, response)
    assert result.n == 4  # 2 NaN filtrados


def test_anova_levanta_value_error_shape_diferente() -> None:
    with pytest.raises(ValueError, match="mesmo shape"):
        anova_by_group(np.array([0, 1]), np.array([1.0, 2.0, 3.0]))


def test_anova_levanta_value_error_menos_de_2_grupos() -> None:
    labels = np.zeros(10, dtype=np.int64)
    response = np.arange(10, dtype=np.float64)
    with pytest.raises(ValueError, match=">=2 grupos"):
        anova_by_group(labels, response)


def test_anova_levanta_value_error_n_insuficiente() -> None:
    labels = np.array([0, 1], dtype=np.int64)
    response = np.array([1.0, 2.0], dtype=np.float64)
    with pytest.raises(ValueError, match="graus de liberdade"):
        anova_by_group(labels, response)


# ============================================================================
# regime_persistence
# ============================================================================


def test_persistence_segmentos_conhecidos_a_mao() -> None:
    # 3 segmentos: [0,0,0,0] [1,1] [0,0,0] -> durações 4, 2, 3
    labels = np.array([0, 0, 0, 0, 1, 1, 0, 0, 0], dtype=np.int64)
    result = regime_persistence(labels)
    assert result.n_segments == 3
    assert result.median_duration_bars == pytest.approx(3.0)  # mediana de [4,2,3]
    # 2 trocas em 8 transições possíveis (n-1=8)
    assert result.switch_rate == pytest.approx(2.0 / 8.0)


def test_persistence_serie_constante_1_segmento_switch_rate_zero() -> None:
    labels = np.zeros(50, dtype=np.int64)
    result = regime_persistence(labels)
    assert result.n_segments == 1
    assert result.median_duration_bars == pytest.approx(50.0)
    assert result.switch_rate == pytest.approx(0.0)


def test_persistence_single_bar_switch_rate_zero() -> None:
    result = regime_persistence(np.array([0], dtype=np.int64))
    assert result.n_segments == 1
    assert result.switch_rate == 0.0


def test_persistence_levanta_value_error_vazio() -> None:
    with pytest.raises(ValueError, match="vazio"):
        regime_persistence(np.array([], dtype=np.int64))


# ============================================================================
# adjusted_rand
# ============================================================================


def test_adjusted_rand_particoes_identicas_e_1() -> None:
    labels = np.array([0, 0, 1, 1, 2, 2, 0, 1], dtype=np.int64)
    assert adjusted_rand(labels, labels) == pytest.approx(1.0)


def test_adjusted_rand_particoes_identicas_com_rotulo_permutado_e_1() -> None:
    """ARI é invariante a permutação de rótulo -- mesma propriedade que
    justifica reusar sklearn em vez de comparar rótulo bruto diretamente."""
    labels_a = np.array([0, 0, 1, 1, 2, 2], dtype=np.int64)
    labels_b = np.array([2, 2, 0, 0, 1, 1], dtype=np.int64)  # mesma partição, outros nomes
    assert adjusted_rand(labels_a, labels_b) == pytest.approx(1.0)


def test_adjusted_rand_levanta_value_error_shape_diferente() -> None:
    with pytest.raises(ValueError, match="mesmo shape"):
        adjusted_rand(np.array([0, 1, 2]), np.array([0, 1]))
