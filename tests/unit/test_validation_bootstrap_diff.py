"""Testes de `src/validation/bootstrap_diff.py` — núcleo genérico de
bootstrap estacionário por blocos, ADR-004 Fase 0 / AG-220. Casos
sintéticos deliberadamente extremos (margem grande entre H0 e H1) —
este é código estatístico novo, sem execução própria do autor pra
validar empiricamente (protocolo de execução, CLAUDE.md), então os
casos de teste precisam ser inambíguos por construção, não só
'provavelmente' corretos."""

from __future__ import annotations

import numpy as np

from src.validation import bootstrap_diff as bd


def test_stationary_bootstrap_ci_ruido_puro_media_zero_contem_zero() -> None:
    """H0 verdadeira por construção (gaussiano i.i.d., média 0) — o IC de
    95% deve conter zero. Seed fixa, N grande o suficiente pra não ser
    caso de canto."""
    rng = np.random.default_rng(1)
    x = rng.normal(loc=0.0, scale=1.0, size=500)  # noqa: magic-number
    result = bd.stationary_bootstrap_ci(x, n_boot=2000, confidence_level=0.95, seed=7)
    assert result.n_obs == 500  # noqa: magic-number
    assert result.ci_low <= 0.0 <= result.ci_high
    assert result.significant is False


def test_stationary_bootstrap_ci_diferenca_grande_exclui_zero() -> None:
    """H1 verdadeira por construção (deslocamento de média >> desvio) — o
    IC deve excluir zero e o ponto estimado deve ter o sinal certo."""
    rng = np.random.default_rng(2)
    x = rng.normal(loc=5.0, scale=1.0, size=500)  # noqa: magic-number
    result = bd.stationary_bootstrap_ci(x, n_boot=2000, confidence_level=0.95, seed=7)
    assert result.significant is True
    assert result.ci_low > 0.0
    assert result.point_estimate > 4.0  # noqa: magic-number -- folga generosa sobre a média real (5.0)


def test_stationary_bootstrap_ci_determinismo_mesma_seed_bit_exato() -> None:
    rng = np.random.default_rng(3)
    x = rng.normal(loc=0.3, scale=1.0, size=300)  # noqa: magic-number
    r1 = bd.stationary_bootstrap_ci(x, n_boot=500, confidence_level=0.95, seed=123)
    r2 = bd.stationary_bootstrap_ci(x, n_boot=500, confidence_level=0.95, seed=123)
    assert r1 == r2


def test_stationary_bootstrap_ci_amostra_pequena_retorna_nao_significante() -> None:
    x = np.array([0.1, 0.2, 0.3])  # noqa: magic-number -- abaixo de _MIN_OBS_BOOTSTRAP
    result = bd.stationary_bootstrap_ci(x, n_boot=100, confidence_level=0.95, seed=1)
    assert result.significant is False
    assert np.isnan(result.point_estimate)
    assert result.block_length == 0


def test_stationary_bootstrap_ci_ignora_nan() -> None:
    rng = np.random.default_rng(4)
    x = rng.normal(loc=5.0, scale=1.0, size=200)  # noqa: magic-number
    x_with_nan = np.concatenate([x, np.full(50, np.nan)])  # noqa: magic-number
    r_clean = bd.stationary_bootstrap_ci(x, n_boot=1000, confidence_level=0.95, seed=9)
    r_with_nan = bd.stationary_bootstrap_ci(x_with_nan, n_boot=1000, confidence_level=0.95, seed=9)
    assert r_clean.n_obs == r_with_nan.n_obs == 200  # noqa: magic-number
    assert r_clean == r_with_nan


def test_select_block_length_ruido_branco_da_bloco_pequeno() -> None:
    rng = np.random.default_rng(5)
    x = rng.normal(size=500)  # noqa: magic-number -- i.i.d., sem dependência serial
    bl = bd.select_block_length(x)
    assert 1 <= bl <= 15  # noqa: magic-number -- margem generosa; ACF de ruído branco deveria morrer cedo


def test_select_block_length_serie_persistente_da_bloco_maior() -> None:
    """AR(1) com phi=0.9 -- dependência serial forte e conhecida (meia-vida
    ~6-7 observações), a ACF deveria demorar bem mais pra cair abaixo do
    limiar de significância do que no caso de ruído branco acima."""
    rng = np.random.default_rng(6)
    n = 1000  # noqa: magic-number
    phi = 0.9  # noqa: magic-number
    eps = rng.normal(size=n)
    x = np.empty(n)
    x[0] = eps[0]
    for i in range(1, n):
        x[i] = phi * x[i - 1] + eps[i]
    bl_white = bd.select_block_length(rng.normal(size=n))
    bl_ar1 = bd.select_block_length(x)
    assert bl_ar1 > bl_white


def test_stationary_bootstrap_ci_block_length_respeita_teto_n_sobre_4() -> None:
    rng = np.random.default_rng(8)
    x = rng.normal(size=40)  # noqa: magic-number -- n//4 = 10, teto apertado
    result = bd.stationary_bootstrap_ci(x, n_boot=200, confidence_level=0.95, seed=1, block_length=1000)
    assert result.block_length <= 10  # noqa: magic-number
