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
# Estabilidade de canonicalização entre folds CONSECUTIVOS (achado F2,
# auditoria M4 2026-08-19) -- cada fold canonicaliza seus próprios estados
# pela média AJUSTADA daquele fold (docstring do módulo, "Canonicalização
# ancorada no FIT"); nada testava até aqui que `canonical_id=0` do fold N
# representa o MESMO regime econômico que `canonical_id=0` do fold N+1.
# ============================================================================


@pytest.mark.slow
def test_canonicalizacao_estavel_entre_folds_consecutivos_regime_fixo() -> None:
    """NÃO prova robustez em regime que MUDA de caráter entre folds (isso
    seria um achado de pesquisa, não um teste de regressão, ver task
    original) -- só confirma que, quando a estrutura GERADORA é ESTÁVEL
    (2 clusters bem separados intercalados em blocos ao longo de TODA a
    série -- diferente de `_two_cluster_obs`, que concatena cluster A
    inteiro e só depois cluster B inteiro, um único changepoint, não "mesma
    estrutura em toda a série"), a canonicalização É estável entre dois
    cortes de janela expansiva consecutivos (mesmo contrato de fold de
    `fit_hmm_gaussian`: `train_end_idx` cresce, ancorado em 0 -- mesmo
    padrão de `build_hmm.build_hmm_regimes`).

    Métrica: **não** `adjusted_rand_score` -- ARI é invariante a
    permutação de rótulo por construção, então NÃO detectaria um
    label-switch entre folds (exatamente o bug que este teste existe pra
    pegar: um ARI=1.0 entre fold N e fold N+1 com os rótulos TROCADOS
    ainda daria ARI=1.0). Em vez disso, decodifica um conjunto de PROBE
    comum (presente no treino dos DOIS folds, por construção da janela
    expansiva) com cada fit e mede a fração de `canonical_id` EXATAMENTE
    igual entre os dois -- um label-switch faria essa fração desabar
    (rótulos invertidos: quase toda posição discordaria), não apareceria
    como "partição equivalente"."""
    rng = np.random.default_rng(42)
    n_per_block = 40
    n_blocks = 12  # alternância cluster A/B repetida -- estrutura fixa em toda a série
    blocks = []
    for i in range(n_blocks):
        center = -1.0 if i % 2 == 0 else 1.0
        blocks.append(rng.normal(center, 0.1, size=(n_per_block, 2)))
    obs = np.concatenate(blocks).astype(np.float64)

    fold_1_end = n_per_block * 6  # fold N -- janela expansiva ancorada em 0
    fold_2_end = n_per_block * 10  # fold N+1 -- mais dado, MESMA estrutura geradora
    probe = obs[: n_per_block * 4]  # comum ao treino dos DOIS folds

    fit_1 = fit_hmm_gaussian(obs, n_states=2, train_end_idx=fold_1_end, seed=42)
    fit_2 = fit_hmm_gaussian(obs, n_states=2, train_end_idx=fold_2_end, seed=42)
    assert fit_1 is not None and fit_2 is not None

    canonical_probe_fit_1 = predict_hmm_gaussian(fit_1, probe)
    canonical_probe_fit_2 = predict_hmm_gaussian(fit_2, probe)

    # Sanity check -- se fit_1 nem recuperou a separação real (ex. colapsou
    # em 1 estado dominante por acidente de seed), o teste de agreement
    # abaixo ficaria vazio de sentido (dois fits igualmente ruins podem
    # concordar por acaso). Mesmo limiar (`> 0.7`) de
    # `test_recupera_separacao_de_2_clusters_bem_separados`.
    true_state_probe = np.array(
        [0 if (i // n_per_block) % 2 == 0 else 1 for i in range(probe.shape[0])]
    )
    ari_fit_1 = adjusted_rand_score(true_state_probe, canonical_probe_fit_1)
    assert ari_fit_1 > 0.7, (
        f"sanity check falhou -- fit_1 nem recuperou a separação real (ARI={ari_fit_1})"
    )

    agreement = float(np.mean(canonical_probe_fit_1 == canonical_probe_fit_2))
    assert agreement > 0.9, (
        f"agreement={agreement} -- canonical_id do fold N e do fold N+1 diverge no mesmo "
        "conjunto de probe, apesar da estrutura geradora ser idêntica nos dois folds "
        "(regime fixo); indica label-switch entre folds consecutivos (achado F2)"
    )


@pytest.mark.slow
def test_canonicalizacao_pode_trocar_de_significado_sob_mudanca_estrutural_entre_folds() -> None:
    """AG-134 (2026-08-21): o teste irmão acima só prova estabilidade
    quando a estrutura GERADORA é FIXA entre os 2 folds -- não diz nada
    sobre o risco real que AG-134 registra (mudança estrutural genuína,
    ex. transição de mercado lateral pra tendência sustentada mudando a
    composição intrínseca dos estados do HMM). Este teste CARACTERIZA
    esse risco -- não é uma correção de bug (não há bug de código; é um
    limite de identificabilidade do MÉTODO, mesma classe do achado
    original) -- não fecha AG-134 sozinho, só prova que o cenário de
    risco é alcançável de verdade, conforme a rota sugerida no próprio
    registro.

    Desenho: fold N vê só a estrutura alternada de 2 clusters moderados
    (idêntica ao teste irmão, mesmo `probe`). Fold N+1 vê a MESMA
    estrutura ATÉ o corte do fold N (nada muda ANTES do corte -- nunca
    contamina o `probe`) mais um 3º modo estruturalmente extremo (10,0,
    ~10x mais distante da origem que os 2 clusters originais) SÓ na
    porção exclusiva do fold N+1, com massa amostral comparável ao resto
    da série (não um blip). Um HMM de 2 estados forçado a reparticionar
    TODA a série tende, por construção do EM, a devotar 1 estado ao modo
    extremo novo e fundir os 2 clusters moderados originais no outro
    estado (ficam "próximos" um do outro relativo ao modo extremo) --
    isso faria o `probe` (que sob estrutura fixa split ~50/50 entre
    canonical_id 0/1, teste irmão) colapsar pra quase um único
    canonical_id sob o fold N+1: MESMOS pontos físicos, canonical_id
    diferente -- o risco de troca de SIGNIFICADO que AG-134 nomeia,
    distinto de label-switch (F2, teste irmão).

    Limiar abaixo (`<= 0.9`) reusa o MESMO valor que o teste irmão usa
    como piso de estabilidade (`> 0.9`) -- não um número novo inventado
    (B23). A asserção é "o piso de estabilidade do caso fixo NÃO se
    sustenta sob mudança estrutural real", não uma magnitude de
    degradação específica -- não medida antes de este teste rodar de
    verdade (protocolo de execução, `CLAUDE.md`: escrito, não executado
    por Claude). **Se este teste FALHAR ao rodar** (agreement > 0.9
    mesmo sob a mudança estrutural desenhada), é um achado real -- o
    método é mais robusto do que AG-134 supõe sob este cenário
    específico -- reportar e registrar, não afrouxar o limiar sem
    remedir."""
    rng = np.random.default_rng(77)
    n_per_block = 40
    n_blocks_moderate = 6  # mesma estrutura fixa do teste irmão, toda ela vista pelo fold N
    blocks = []
    for i in range(n_blocks_moderate):
        center = -1.0 if i % 2 == 0 else 1.0
        blocks.append(rng.normal(center, 0.1, size=(n_per_block, 2)))
    fold_1_end = n_per_block * n_blocks_moderate
    probe = np.concatenate(blocks)[: n_per_block * 4]  # comum aos 2 folds, igual ao teste irmão

    # Fold N+1 -- MESMOS blocos do fold N (nada muda ANTES do corte) + um
    # 3º modo estruturalmente extremo DEPOIS do corte, massa amostral
    # comparável (não um blip) -- mudança estrutural real, não label-switch
    # por acaso de seed (esse já é coberto pelo teste irmão em cenário fixo).
    extreme_block = rng.normal(10.0, 0.1, size=(n_per_block * n_blocks_moderate, 2))
    obs = np.concatenate([*blocks, extreme_block]).astype(np.float64)
    fold_2_end = obs.shape[0]

    fit_1 = fit_hmm_gaussian(obs, n_states=2, train_end_idx=fold_1_end, seed=77)
    fit_2 = fit_hmm_gaussian(obs, n_states=2, train_end_idx=fold_2_end, seed=77)
    assert fit_1 is not None and fit_2 is not None

    canonical_probe_fit_1 = predict_hmm_gaussian(fit_1, probe)
    canonical_probe_fit_2 = predict_hmm_gaussian(fit_2, probe)

    # Mesmo sanity check do teste irmão -- se fit_1 nem recuperou a
    # separação real, o teste de agreement abaixo ficaria vazio de sentido.
    true_state_probe = np.array(
        [0 if (i // n_per_block) % 2 == 0 else 1 for i in range(probe.shape[0])]
    )
    ari_fit_1 = adjusted_rand_score(true_state_probe, canonical_probe_fit_1)
    assert ari_fit_1 > 0.7, (
        f"sanity check falhou -- fit_1 nem recuperou a separação real (ARI={ari_fit_1})"
    )

    agreement = float(np.mean(canonical_probe_fit_1 == canonical_probe_fit_2))
    assert agreement <= 0.9, (
        f"agreement={agreement} -- esperava que a mudança estrutural real (3º modo "
        "extremo, massa comparável, na porção exclusiva do fold N+1) quebrasse o piso "
        "de estabilidade (> 0.9) que o teste irmão mede sob regime fixo -- se isso NÃO "
        "aconteceu, é achado real (AG-134): reportar a magnitude medida, não afrouxar "
        "este limiar sem remedir o cenário."
    )


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
