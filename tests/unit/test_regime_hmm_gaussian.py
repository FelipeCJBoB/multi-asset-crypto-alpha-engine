"""Testes de `src/regime/hmm_gaussian.py` — M4 (`PRD_V4_1.md` §3.2), candidato
HMM gaussiano (`dynamax`). Mesmo padrão de `test_regime_bocpd.py`: prova
correção estatística contra caso sintético conhecido (separação de cluster,
causalidade, determinismo), não só estrutura/wiring.

Todos os testes usam dado sintético gerado com `numpy.random.default_rng`
com seed fixa -- reprodutíveis, sem tocar disco (núcleo puro, sem IO)."""

from __future__ import annotations

import jax.numpy as jnp
import numpy as np
import pytest
from sklearn.metrics import adjusted_rand_score

# `_all_finite` é privado -- importado direto mesmo assim, mesmo padrão de
# `test_regime_classifier.py` (`_run_state_machine = classifier._run_state_machine`):
# disparar o caminho NaN/Inf via `fit_em` real exigiria injetar NaN no
# `obs` de entrada, o que `sklearn.KMeans` (usado na inicialização) rejeita
# antes mesmo de chegar no EM -- não alcançável por uma chamada pública
# "normal" de `fit_hmm_gaussian` (ver teste dedicado mais abaixo), então o
# helper que detectaria esse ramo é testado isoladamente aqui.
from src.regime.hmm_gaussian import (
    HMMFit,
    _all_finite,
    fit_hmm_gaussian,
    hmm_gaussian_classifier_id,
    predict_hmm_gaussian,
)


def _two_cluster_obs(
    n_per_cluster: int, seed: int, sep: float = 1.0, scale: float = 0.1
) -> tuple[np.ndarray, np.ndarray]:
    """2 clusters gaussianos bem separados em 2D, concatenados no tempo
    (cluster 0 primeiro, cluster 1 depois) -- caso sintético canônico pra
    provar que o HMM recupera a separação real (ARI alto)."""
    rng = np.random.default_rng(seed)
    obs_a = rng.normal(-sep, scale, size=(n_per_cluster, 2))
    obs_b = rng.normal(sep, scale, size=(n_per_cluster, 2))
    obs = np.concatenate([obs_a, obs_b]).astype(np.float64)
    true_state = np.concatenate(
        [np.zeros(n_per_cluster, dtype=np.int64), np.ones(n_per_cluster, dtype=np.int64)]
    )
    return obs, true_state


# ============================================================================
# fit_hmm_gaussian / predict_hmm_gaussian -- correção estatística
# ============================================================================


@pytest.mark.slow
def test_recupera_separacao_de_2_clusters_bem_separados() -> None:
    """Caso canônico: 2 estados reais claramente separados em média (mesmo
    espírito do teste de changepoint único de `test_regime_bocpd.py`) --
    o HMM k=2 precisa recuperar essa separação, medido via Rand ajustado
    (`sklearn.metrics.adjusted_rand_score`) contra o rótulo sintético
    verdadeiro. Não precisa acertar o RÓTULO (0 vs 1), só a PARTIÇÃO --
    exatamente o que ARI mede (invariante a permutação de rótulo)."""
    obs, true_state = _two_cluster_obs(n_per_cluster=150, seed=11)

    fit = fit_hmm_gaussian(obs, n_states=2, train_end_idx=obs.shape[0], seed=11)
    assert fit is not None, "fit não deveria degenerar num caso de separação clara"

    canonical_id = predict_hmm_gaussian(fit, obs)
    ari = adjusted_rand_score(true_state, canonical_id)
    assert ari > 0.7, f"ARI={ari} -- HMM não recuperou a separação real dos 2 clusters"


@pytest.mark.slow
def test_canonicalizacao_ordena_por_retorno_medio_ascendente() -> None:
    """Critério literal do PRD (§3.2 M4): estado de menor retorno médio
    (`log_return_1`, coluna 0 de `obs` por convenção) vira `canonical_id=0`,
    o de maior vira `canonical_id=k-1`. Usa o mesmo par de clusters do
    teste de separação, mas verifica a ORDEM, não só a partição."""
    obs, _true_state = _two_cluster_obs(n_per_cluster=150, seed=11)

    fit = fit_hmm_gaussian(obs, n_states=2, train_end_idx=obs.shape[0], seed=11)
    assert fit is not None
    canonical_id = predict_hmm_gaussian(fit, obs)

    assert set(np.unique(canonical_id).tolist()) == {0, 1}
    mean_state_0 = float(np.mean(obs[canonical_id == 0, 0]))
    mean_state_1 = float(np.mean(obs[canonical_id == 1, 0]))
    assert mean_state_0 < mean_state_1, (
        f"canonical_id=0 devia ter a menor média de log_return_1 "
        f"(mean_0={mean_state_0}, mean_1={mean_state_1})"
    )


@pytest.mark.slow
def test_causalidade_perturbar_futuro_nao_muda_passado() -> None:
    """Mesmo padrão de `test_regime_bocpd.py::
    test_causalidade_perturbar_futuro_nao_muda_passado`: perturbar `obs`
    depois de um corte não pode mudar a decodificação (`canonical_id`)
    antes do corte. `fit` vem de um dado de TREINO totalmente separado do
    `obs` decodificado abaixo (2 clusters bem separados, garante um fit
    não-degenerado -- ver `test_fit_retorna_none_quando_estado_colapsa`:
    dado estacionário sem estrutura real pode legitimamente colapsar
    estado e não é o ponto deste teste) -- isola a causalidade da
    DECODIFICAÇÃO (`hmm.filter`, uma recursão forward pura) e da
    CANONICALIZAÇÃO (ancorada em `fit.params`, nunca no `obs` passado a
    `predict_hmm_gaussian` -- ver docstring do módulo, seção
    "Canonicalização ancorada no FIT"), sem depender de o `obs` de TESTE
    ter estrutura nenhuma."""
    train_obs, _ = _two_cluster_obs(n_per_cluster=100, seed=3)
    fit = fit_hmm_gaussian(train_obs, n_states=2, train_end_idx=train_obs.shape[0], seed=3)
    assert fit is not None

    rng = np.random.default_rng(30)
    n = 300
    cutoff = 150
    obs = rng.normal(0.0, 0.05, size=(n, 2)).astype(np.float64)

    canonical_base = predict_hmm_gaussian(fit, obs)

    obs_perturbed = obs.copy()
    obs_perturbed[cutoff + 1 :] = rng.normal(5.0, 0.05, size=(n - cutoff - 1, 2))
    canonical_perturbed = predict_hmm_gaussian(fit, obs_perturbed)

    np.testing.assert_array_equal(
        canonical_base[: cutoff + 1], canonical_perturbed[: cutoff + 1]
    )


@pytest.mark.slow
def test_determinismo_fit_e_predict_mesma_seed_mesmo_input() -> None:
    """EM tem múltiplos ótimos locais dependendo da inicialização --
    mesma seed, mesmo `obs`, precisa dar o MESMO resultado sempre (fit E
    predict), nunca variar entre execuções."""
    obs, _true_state = _two_cluster_obs(n_per_cluster=100, seed=5)

    fit_1 = fit_hmm_gaussian(obs, n_states=2, train_end_idx=obs.shape[0], seed=5)
    fit_2 = fit_hmm_gaussian(obs, n_states=2, train_end_idx=obs.shape[0], seed=5)
    assert fit_1 is not None and fit_2 is not None

    np.testing.assert_allclose(
        np.asarray(fit_1.params.emissions.means), np.asarray(fit_2.params.emissions.means)
    )
    assert fit_1.final_log_prob == pytest.approx(fit_2.final_log_prob)

    canonical_1 = predict_hmm_gaussian(fit_1, obs)
    canonical_2 = predict_hmm_gaussian(fit_2, obs)
    np.testing.assert_array_equal(canonical_1, canonical_2)


@pytest.mark.slow
def test_classifier_id_deterministico_a_partir_de_n_states() -> None:
    """`classifier_id = f"hmm_gaussian_k{n_states}_v1"` -- única fonte
    (`hmm_gaussian_classifier_id`), `HMMFit.classifier_id` só chama essa
    função, não reimplementa o template."""
    assert hmm_gaussian_classifier_id(2) == "hmm_gaussian_k2_v1"
    assert hmm_gaussian_classifier_id(3) == "hmm_gaussian_k3_v1"
    assert hmm_gaussian_classifier_id(4) == "hmm_gaussian_k4_v1"

    obs, _ = _two_cluster_obs(n_per_cluster=60, seed=1)
    fit = fit_hmm_gaussian(obs, n_states=2, train_end_idx=obs.shape[0], seed=1)
    assert fit is not None
    assert fit.classifier_id == hmm_gaussian_classifier_id(fit.n_states) == "hmm_gaussian_k2_v1"


# ============================================================================
# fit_hmm_gaussian -- convergência degenerada detectável (retorna None)
# ============================================================================


@pytest.mark.slow
def test_fit_retorna_none_quando_estado_colapsa() -> None:
    """Achado real medido nesta sessão (ver docstring do módulo): prior
    sticky MUITO forte (`sticky_concentration` extremo) sobre dado
    estacionário sem estrutura real faz o EM convergir usando MENOS
    estados do que `n_states` pedido -- `params`/`log_probs` continuam
    finitos (não é o ramo NaN/Inf), mas é uma convergência degenerada
    pro propósito do M4 (um "k=4" que na prática usa 1 estado não é o
    candidato k=4 que o trial paga pra medir). Reproduzido de forma
    determinística (20 seeds testadas manualmente antes deste teste,
    100% colapsam sob estes parâmetros exatos -- não é sorte de seed)."""
    rng = np.random.default_rng(1)
    obs = rng.normal(0.0, 0.02, size=(50, 2)).astype(np.float64)

    fit = fit_hmm_gaussian(
        obs, n_states=4, train_end_idx=50, seed=1, sticky_concentration=100_000.0
    )
    assert fit is None


def test_all_finite_helper_detecta_nan_e_inf() -> None:
    """`_all_finite` é o backstop pro ramo "NaN/Inf em params ou log_probs"
    do contrato de `fit_hmm_gaussian` (`return None` documentado) --
    testado isoladamente aqui porque disparar esse ramo organicamente via
    `fit_em` real exigiria `obs` com NaN, que `sklearn.KMeans` (usado na
    inicialização) rejeita antes do EM sequer rodar -- não é um caminho
    alcançável por uma chamada pública "normal" de `fit_hmm_gaussian`,
    mas o helper que o detectaria continua testado."""
    finite_pytree = {"a": jnp.array([1.0, 2.0]), "b": jnp.array([[0.1, 0.2], [0.3, 0.4]])}
    assert _all_finite(finite_pytree) is True

    nan_pytree = {"a": jnp.array([1.0, float("nan")]), "b": jnp.array([[0.1, 0.2], [0.3, 0.4]])}
    assert _all_finite(nan_pytree) is False

    inf_pytree = {"a": jnp.array([1.0, float("inf")])}
    assert _all_finite(inf_pytree) is False


# ============================================================================
# Erros de precondição -- entrada inválida falha rápido, mensagem clara
# ============================================================================


def test_fit_levanta_value_error_train_end_idx_menor_que_n_states() -> None:
    obs = np.zeros((10, 2), dtype=np.float64)
    with pytest.raises(ValueError, match="menos que n_states"):
        fit_hmm_gaussian(obs, n_states=5, train_end_idx=3, seed=0)


def test_fit_levanta_value_error_obs_nao_2d() -> None:
    obs_1d = np.zeros(10, dtype=np.float64)
    with pytest.raises(ValueError, match="2D"):
        fit_hmm_gaussian(obs_1d, n_states=2, train_end_idx=5, seed=0)


def test_fit_levanta_value_error_n_states_invalido() -> None:
    obs = np.zeros((10, 2), dtype=np.float64)
    with pytest.raises(ValueError, match="n_states"):
        fit_hmm_gaussian(obs, n_states=0, train_end_idx=5, seed=0)


def test_fit_levanta_value_error_train_end_idx_fora_dos_limites() -> None:
    obs = np.zeros((10, 2), dtype=np.float64)
    with pytest.raises(ValueError, match="train_end_idx"):
        fit_hmm_gaussian(obs, n_states=2, train_end_idx=0, seed=0)
    with pytest.raises(ValueError, match="train_end_idx"):
        fit_hmm_gaussian(obs, n_states=2, train_end_idx=11, seed=0)


@pytest.mark.slow
def test_predict_levanta_value_error_emission_dim_diferente() -> None:
    obs, _ = _two_cluster_obs(n_per_cluster=30, seed=2)
    fit = fit_hmm_gaussian(obs, n_states=2, train_end_idx=obs.shape[0], seed=2)
    assert fit is not None

    obs_errado = np.zeros((10, 3), dtype=np.float64)
    with pytest.raises(ValueError, match="emission_dim"):
        predict_hmm_gaussian(fit, obs_errado)


@pytest.mark.slow
def test_predict_levanta_value_error_obs_vazio() -> None:
    obs, _ = _two_cluster_obs(n_per_cluster=30, seed=2)
    fit = fit_hmm_gaussian(obs, n_states=2, train_end_idx=obs.shape[0], seed=2)
    assert fit is not None

    obs_vazio = np.zeros((0, 2), dtype=np.float64)
    with pytest.raises(ValueError, match="vazio"):
        predict_hmm_gaussian(fit, obs_vazio)


@pytest.mark.slow
def test_hmmfit_e_dataclass_frozen() -> None:
    """`HMMFit` precisa ser imutável (`frozen=True`) -- mesmo contrato de
    `BOCPDResult`/`CanonicalizationResult`, resultado de fit não deve ser
    mutável depois de criado."""
    obs, _ = _two_cluster_obs(n_per_cluster=30, seed=4)
    fit = fit_hmm_gaussian(obs, n_states=2, train_end_idx=obs.shape[0], seed=4)
    assert fit is not None
    assert isinstance(fit, HMMFit)
    with pytest.raises(AttributeError):
        fit.n_states = 99  # type: ignore[misc]
