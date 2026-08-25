"""Testes de `src/validation/pbo_cscv.py` — PBO via CSCV (Bailey et al.
2017). Casos sintéticos deliberadamente extremos (ruído puro vs.
candidato genuinamente dominante) — código estatístico novo, sem
execução própria do autor pra validar empiricamente fora deste teste,
então os casos precisam ser inambíguos por construção."""

from __future__ import annotations

import numpy as np
import pytest

from src.validation import pbo_cscv as pbo_mod


def test_compute_pbo_ruido_puro_fica_perto_de_meio() -> None:
    """N candidatos i.i.d., MESMA distribuição -- nenhum carrega
    informação real sobre os outros. O vencedor IS deveria ser
    essencialmente aleatório em relação ao ranking OOS -- PBO perto de
    0,5 (moeda honesta), não perto de 0 nem de 1."""
    rng = np.random.default_rng(1)
    returns = rng.normal(loc=0.0, scale=1.0, size=(480, 8))  # noqa: magic-number
    result = pbo_mod.compute_pbo(returns, n_blocks=16)  # noqa: magic-number
    assert result.n_combinations > 0
    assert 0.3 <= result.pbo <= 0.7  # noqa: magic-number -- folga generosa em torno de 0.5


def test_compute_pbo_candidato_dominante_da_pbo_baixo() -> None:
    """1 candidato com vantagem de média GRANDE e CONSISTENTE (mesma
    distribuição em todo período, não só num trecho) sobre os outros 4 --
    deveria vencer o IS quase sempre E ficar bem ranqueado no OOS quase
    sempre, dando PBO baixo (a seleção IS carrega informação real)."""
    rng = np.random.default_rng(2)
    n_periods = 480  # noqa: magic-number
    weak = rng.normal(loc=0.0, scale=1.0, size=(n_periods, 4))  # noqa: magic-number
    strong = rng.normal(loc=3.0, scale=1.0, size=(n_periods, 1))  # noqa: magic-number -- vantagem grande e estavel
    returns = np.concatenate([weak, strong], axis=1)
    result = pbo_mod.compute_pbo(returns, n_blocks=16)  # noqa: magic-number
    assert result.pbo < 0.15  # noqa: magic-number -- deveria ficar bem abaixo de 0.5


def test_compute_pbo_rejeita_menos_de_2_candidatos() -> None:
    with pytest.raises(ValueError, match="n_candidates"):
        pbo_mod.compute_pbo(np.zeros((100, 1)), n_blocks=10)  # noqa: magic-number


def test_compute_pbo_rejeita_n_blocks_impar() -> None:
    with pytest.raises(ValueError, match="par"):
        pbo_mod.compute_pbo(np.zeros((100, 3)), n_blocks=7)  # noqa: magic-number


def test_compute_pbo_rejeita_n_blocks_maior_que_periodos() -> None:
    with pytest.raises(ValueError, match="n_periods"):
        pbo_mod.compute_pbo(np.zeros((10, 3)), n_blocks=20)  # noqa: magic-number


def test_compute_pbo_rejeita_matriz_1d() -> None:
    with pytest.raises(ValueError, match="ndim"):
        pbo_mod.compute_pbo(np.zeros(100), n_blocks=10)  # noqa: magic-number


def test_compute_pbo_n_combinations_bate_binomial_quando_nao_degenerado() -> None:
    """Sem colunas degeneradas (todas com variância real), nenhuma
    combinação deveria ser pulada -- `n_combinations == C(n_blocks,
    n_blocks/2)` exatamente."""
    from math import comb

    rng = np.random.default_rng(3)
    returns = rng.normal(size=(200, 4))  # noqa: magic-number
    result = pbo_mod.compute_pbo(returns, n_blocks=8)  # noqa: magic-number
    assert result.n_combinations == comb(8, 4)  # noqa: magic-number


def test_compute_pbo_determinismo_mesma_entrada_mesmo_resultado() -> None:
    rng = np.random.default_rng(4)
    returns = rng.normal(size=(160, 5))  # noqa: magic-number
    r1 = pbo_mod.compute_pbo(returns, n_blocks=8)  # noqa: magic-number
    r2 = pbo_mod.compute_pbo(returns, n_blocks=8)  # noqa: magic-number
    assert r1 == r2


def test_relative_rank_extremos() -> None:
    values = np.array([1.0, 2.0, 3.0, 4.0, 5.0])  # noqa: magic-number
    assert pbo_mod._relative_rank(values, 4) == pytest.approx(5.0 / 6.0)  # maior valor
    assert pbo_mod._relative_rank(values, 0) == pytest.approx(1.0 / 6.0)  # menor valor


def test_relative_rank_empates_usa_posto_medio() -> None:
    values = np.array([1.0, 2.0, 2.0, 2.0, 5.0])  # noqa: magic-number -- 3 empatados no meio
    # 1 valor abaixo (1.0), 3 empatados (incluindo o proprio) -- posto medio = 1 + (3+1)/2 = 3.0
    assert pbo_mod._relative_rank(values, 1) == pytest.approx(3.0 / 6.0)
