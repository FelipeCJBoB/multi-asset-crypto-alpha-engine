"""Testes de `src/regime/canonicalization.py` — M4 (`PRD_V4_1.md` §3.2),
banned pattern B21. Foco central: invariância a permutação do rótulo
bruto — é exatamente o defeito que motivou banir `hmmlearn`."""

from __future__ import annotations

import numpy as np
import pytest

from src.regime.canonicalization import canonicalize_states


def test_ordena_por_media_ascendente() -> None:
    raw = np.array([0, 0, 1, 1, 2, 2], dtype=np.int64)
    response = np.array([5.0, 5.0, -5.0, -5.0, 0.0, 0.0], dtype=np.float64)
    result = canonicalize_states(raw, response)
    # estado 1 (média -5) -> canonical 0; estado 2 (média 0) -> canonical 1;
    # estado 0 (média 5) -> canonical 2
    assert result.mapping == {1: 0, 2: 1, 0: 2}
    assert list(result.canonical_id) == [2, 2, 0, 0, 1, 1]


def test_desempate_por_variancia_ascendente_quando_media_empata() -> None:
    raw = np.array([0, 0, 0, 1, 1, 1], dtype=np.int64)
    # ambos com média 0.0, estado 0 com variância maior
    response = np.array([-2.0, 0.0, 2.0, -0.1, 0.0, 0.1], dtype=np.float64)
    result = canonicalize_states(raw, response)
    assert result.mean_by_raw_state[0] == pytest.approx(0.0)
    assert result.mean_by_raw_state[1] == pytest.approx(0.0)
    assert result.var_by_raw_state[1] < result.var_by_raw_state[0]
    # estado 1 (menor variância) vira canonical 0, estado 0 vira canonical 1
    assert result.mapping == {1: 0, 0: 1}


def test_determinismo_mesmo_input_mesmo_output() -> None:
    rng = np.random.default_rng(7)
    raw = rng.integers(0, 3, size=200).astype(np.int64)
    response = rng.normal(size=200)
    r1 = canonicalize_states(raw, response)
    r2 = canonicalize_states(raw, response)
    assert list(r1.canonical_id) == list(r2.canonical_id)
    assert r1.mapping == r2.mapping


def test_invariante_a_permutacao_do_rotulo_bruto() -> None:
    """O teste central desta lente -- o defeito real que motivou banir
    `hmmlearn` (B21): dois fits do "mesmo" modelo podem numerar os
    estados de forma diferente (arbitrária). Canonicalização precisa
    produzir o MESMO resultado (mesmos grupos, mesma ordem final por
    retorno) independente de como os rótulos brutos foram numerados."""
    rng = np.random.default_rng(11)
    n = 300
    # 3 "estados reais" com médias de retorno bem separadas
    true_group = rng.integers(0, 3, size=n)
    response = np.where(
        true_group == 0, rng.normal(-1.0, 0.1, n),
        np.where(true_group == 1, rng.normal(0.0, 0.1, n), rng.normal(1.0, 0.1, n)),
    )

    raw_a = true_group.astype(np.int64)  # numeração "natural": 0,1,2
    # mesma partição, rótulos brutos permutados (simula 2º fit com seed
    # diferente numerando os mesmos 3 grupos reais em outra ordem)
    permutation = {0: 2, 1: 0, 2: 1}
    raw_b = np.vectorize(permutation.get)(true_group).astype(np.int64)

    result_a = canonicalize_states(raw_a, response)
    result_b = canonicalize_states(raw_b, response)

    assert list(result_a.canonical_id) == list(result_b.canonical_id)


def test_ignore_value_excluido_do_calculo_e_preservado_no_output() -> None:
    raw = np.array([-1, -1, 0, 0, 1, 1], dtype=np.int64)
    response = np.array([999.0, 999.0, -1.0, -1.0, 1.0, 1.0], dtype=np.float64)
    result = canonicalize_states(raw, response, ignore_value=-1)
    assert -1 not in result.mean_by_raw_state
    assert -1 not in result.mapping
    assert list(result.canonical_id) == [-1, -1, 0, 0, 1, 1]


def test_levanta_value_error_se_shape_diferente() -> None:
    raw = np.array([0, 1, 2], dtype=np.int64)
    response = np.array([1.0, 2.0], dtype=np.float64)
    with pytest.raises(ValueError, match="mesmo shape"):
        canonicalize_states(raw, response)


def test_levanta_value_error_se_todo_input_e_ignore_value() -> None:
    raw = np.array([-1, -1, -1], dtype=np.int64)
    response = np.array([1.0, 2.0, 3.0], dtype=np.float64)
    with pytest.raises(ValueError, match="nenhum estado real"):
        canonicalize_states(raw, response, ignore_value=-1)
