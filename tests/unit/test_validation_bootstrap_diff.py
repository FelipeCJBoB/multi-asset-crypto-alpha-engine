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


def test_stationary_bootstrap_indices_devolve_n_indices_validos() -> None:
    """Vetorização (AG-241-ADDENDUM) -- forma e faixa de valores, o
    invariante mais básico que qualquer reescrita precisa preservar."""
    rng = np.random.default_rng(30)
    n = 777  # noqa: magic-number -- não múltiplo redondo de nada, pega off-by-one
    idx = bd._stationary_bootstrap_indices(n, block_length=15, rng=rng)  # noqa: magic-number
    assert idx.shape == (n,)
    assert idx.dtype == np.int64
    assert int(idx.min()) >= 0
    assert int(idx.max()) < n


def test_stationary_bootstrap_indices_block_length_1_e_essencialmente_iid() -> None:
    """`block_length=1` -- geometric(p=1) sempre devolve 1 (nunca > 1),
    então todo bloco tem tamanho 1 -- equivalente a bootstrap i.i.d.
    comum. Sanidade da reescrita vetorizada no caso degenerado."""
    rng = np.random.default_rng(31)
    n = 500  # noqa: magic-number
    idx = bd._stationary_bootstrap_indices(n, block_length=1, rng=rng)
    assert idx.shape == (n,)
    assert int(idx.min()) >= 0
    assert int(idx.max()) < n


def test_stationary_bootstrap_indices_comprimento_medio_de_bloco_bate_o_alvo() -> None:
    """Propriedade distribucional (não bit-exata contra a versão em loop
    -- RNG consome em ordem diferente, ver docstring da função): o
    comprimento médio de corrida (run-length) contígua na sequência
    gerada deve ficar perto do `block_length` pedido, dentro de folga
    estatística generosa (múltiplas réplicas, `n` grande)."""
    rng = np.random.default_rng(32)
    n = 20_000  # noqa: magic-number
    block_length = 25  # noqa: magic-number
    run_lengths: list[int] = []
    for _ in range(20):  # noqa: magic-number -- réplicas suficientes pra estabilizar a média
        idx = bd._stationary_bootstrap_indices(n, block_length=block_length, rng=rng)
        is_contiguous = np.diff(idx) % n == 1  # noqa: magic-number
        # conta o comprimento de cada corrida contígua (True) entre quebras (False)
        breaks = np.flatnonzero(~is_contiguous)
        boundaries = np.concatenate([[-1], breaks, [n - 2]])
        run_lengths.extend((np.diff(boundaries)).tolist())
    mean_run = float(np.mean(run_lengths))
    assert block_length * 0.5 <= mean_run <= block_length * 1.5  # noqa: magic-number -- folga generosa
