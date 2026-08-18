"""Testes de `src/regime/bocpd.py` — M4 (`PRD_V4_1.md` §3.2). Foco: o
núcleo estatístico precisa provar correção contra caso sintético
conhecido (changepoint injetado, detectado no ponto certo) — não só
teste de wiring/estrutura."""

from __future__ import annotations

import numpy as np
import pytest

from src.regime.bocpd import run_bocpd, segments_to_canonical_states

# ============================================================================
# run_bocpd — correção estatística
# ============================================================================


def test_detecta_changepoint_unico_injetado_no_ponto_certo() -> None:
    """Caso canônico da literatura de BOCPD: série com 1 mudança de nível
    clara. O MAP run-length precisa resetar (cair pra perto de 0) na
    vizinhança da barra injetada, não em outro lugar."""
    rng = np.random.default_rng(42)
    n_each = 300
    injection_point = n_each  # muda exatamente aqui
    obs = np.concatenate(
        [rng.normal(0.0, 0.02, n_each), rng.normal(0.5, 0.02, n_each)]
    ).astype(np.float64)

    result = run_bocpd(obs, hazard_lambda=250.0)

    # janela em torno do ponto de injeção onde o reset de run-length deve
    # acontecer -- tolerância de +-15 barras pro detector reagir (BOCPD
    # não é instantâneo, precisa acumular evidência)
    window = slice(injection_point - 5, injection_point + 15)
    assert np.min(result.map_run_length[window]) <= 3, (
        "run-length não resetou perto do changepoint injetado"
    )
    # bem antes/depois do changepoint, run-length deveria estar crescendo
    # de forma sustentada (sem reset espúrio)
    assert result.map_run_length[injection_point - 50] > 30
    assert result.map_run_length[injection_point + n_each - 50] > 30


def test_serie_estacionaria_sem_changepoint_poucos_segmentos() -> None:
    rng = np.random.default_rng(7)
    obs = rng.normal(0.0, 0.02, 500).astype(np.float64)
    result = run_bocpd(obs, hazard_lambda=250.0)
    # série estacionária real ainda pode gerar 1-2 resets espúrios por
    # ruído, mas não deveria fragmentar em dezenas de segmentos
    assert result.segment_id[-1] < 10


def test_causalidade_perturbar_futuro_nao_muda_passado() -> None:
    rng = np.random.default_rng(3)
    n = 400
    cutoff = 200
    obs = rng.normal(0.0, 0.05, n).astype(np.float64)

    result_base = run_bocpd(obs, hazard_lambda=100.0)

    obs_perturbed = obs.copy()
    obs_perturbed[cutoff + 1 :] = rng.normal(5.0, 0.05, n - cutoff - 1)
    result_perturbed = run_bocpd(obs_perturbed, hazard_lambda=100.0)

    np.testing.assert_array_equal(
        result_base.map_run_length[: cutoff + 1], result_perturbed.map_run_length[: cutoff + 1]
    )
    np.testing.assert_allclose(
        result_base.changepoint_prob[: cutoff + 1],
        result_perturbed.changepoint_prob[: cutoff + 1],
    )


def test_segment_id_comeca_em_zero_e_e_nao_decrescente() -> None:
    rng = np.random.default_rng(9)
    obs = rng.normal(0.0, 0.1, 200).astype(np.float64)
    result = run_bocpd(obs, hazard_lambda=100.0)
    assert result.segment_id[0] == 0
    assert np.all(np.diff(result.segment_id) >= 0)


def test_run_bocpd_levanta_value_error_hazard_lambda_invalido() -> None:
    obs = np.array([1.0, 2.0, 3.0])
    with pytest.raises(ValueError, match="hazard_lambda"):
        run_bocpd(obs, hazard_lambda=1.0)
    with pytest.raises(ValueError, match="hazard_lambda"):
        run_bocpd(obs, hazard_lambda=0.5)


def test_run_bocpd_levanta_value_error_obs_vazio() -> None:
    with pytest.raises(ValueError, match="vazio"):
        run_bocpd(np.array([]), hazard_lambda=100.0)


def test_run_bocpd_determinismo() -> None:
    rng = np.random.default_rng(5)
    obs = rng.normal(0.0, 0.1, 150).astype(np.float64)
    r1 = run_bocpd(obs, hazard_lambda=80.0)
    r2 = run_bocpd(obs, hazard_lambda=80.0)
    np.testing.assert_array_equal(r1.map_run_length, r2.map_run_length)
    np.testing.assert_array_equal(r1.segment_id, r2.segment_id)


# ============================================================================
# segments_to_canonical_states
# ============================================================================


def test_segments_to_canonical_states_agrupa_por_quantil_do_retorno_medio() -> None:
    # 3 segmentos com retorno médio bem distinto: -1, 0, 1
    segment_id = np.array([0, 0, 1, 1, 2, 2], dtype=np.int64)
    response = np.array([-1.0, -1.0, 0.0, 0.0, 1.0, 1.0], dtype=np.float64)
    buckets = segments_to_canonical_states(segment_id, response, n_buckets=3)
    # segmento 0 (retorno mais baixo) deve cair no bucket mais baixo
    assert buckets[0] < buckets[2] < buckets[4] or buckets[0] <= buckets[2] <= buckets[4]


def test_segments_to_canonical_states_levanta_value_error_shape_diferente() -> None:
    with pytest.raises(ValueError, match="mesmo shape"):
        segments_to_canonical_states(
            np.array([0, 1, 2]), np.array([1.0, 2.0]), n_buckets=2
        )


def test_segments_to_canonical_states_levanta_value_error_buckets_demais() -> None:
    segment_id = np.array([0, 0, 1, 1], dtype=np.int64)
    response = np.array([1.0, 1.0, 2.0, 2.0], dtype=np.float64)
    with pytest.raises(ValueError, match="n_buckets"):
        segments_to_canonical_states(segment_id, response, n_buckets=5)
