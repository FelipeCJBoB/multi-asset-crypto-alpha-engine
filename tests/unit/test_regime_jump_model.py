"""Testes de `src/regime/jump_model.py` -- M4 (`PRD_V4_1.md` §3.2). Foco
central (diferente de `test_regime_bocpd.py`): provar o COMPROMISSO de
causalidade documentado no módulo (decode em bloco, não barra-a-barra) --
os dois lados, não só o lado "seguro" (perturbar fora do fold não muda
nada) escondendo o lado "PODE mudar dentro do mesmo fold"."""

from __future__ import annotations

import numpy as np
import pytest
from sklearn.metrics import adjusted_rand_score

from src.regime.jump_model import JumpFit, fit_jump_model, predict_jump_model

# jump_penalty usado nos testes -- achado real de smoke test (2026-08-17,
# ver módulo docstring de jump_model.py, item 6): na escala das features
# sintéticas abaixo (~1e-2), qualquer coisa >= ~0.1 satura o modelo num
# único estado (penalidade domina a perda). Não é o valor calibrado de
# produção (fora do escopo deste módulo) -- só o suficiente pra exercitar
# o modelo com >1 estado nos testes.
_TEST_JUMP_PENALTY = 0.01


def _two_regime_obs(rng: np.random.Generator, n_each: int = 150) -> tuple[np.ndarray, np.ndarray]:
    """2 features `[log_return_1, realized_vol_short]`-like, 2 "regimes
    reais" bem separados, alternando A/B/A/B -- mesmo desenho do smoke
    test que confirmou a API real (2026-08-17)."""
    regime_a = rng.normal(loc=[-0.01, 0.02], scale=[0.002, 0.005], size=(n_each, 2))
    regime_b = rng.normal(loc=[0.01, 0.06], scale=[0.002, 0.005], size=(n_each, 2))
    obs = np.concatenate([regime_a, regime_b, regime_a, regime_b]).astype(np.float64)
    true_state = np.array([0] * n_each + [1] * n_each + [0] * n_each + [1] * n_each)
    return obs, true_state


class _StubJumpModel:
    """Dublê de `jumpmodels.jump.JumpModel` -- expõe só `centers_`/
    `.predict()`, o suficiente pra isolar o teste de canonicalização da
    própria `jumpmodels` (que não garante NENHUMA numeração bruta
    específica -- o ponto do teste de canonicalização é a fiação
    `predict_jump_model -> canonicalize_states`, não o comportamento do
    coordinate descent)."""

    def __init__(self, raw_labels: np.ndarray, n_features: int) -> None:
        self._raw_labels = raw_labels
        self.centers_ = np.zeros((int(raw_labels.max()) + 1, n_features))

    def predict(self, x: object) -> np.ndarray:
        return self._raw_labels


# ============================================================================
# Canonicalização -- de fato aplicada, não só "estados já vêm ordenados"
# ============================================================================


def test_predict_jump_model_canonicaliza_rotulos_brutos() -> None:
    """Rótulos brutos numerados DE PROPÓSITO na ordem OPOSTA da esperada
    pós-canonicalização (raw=0 -> retorno alto, raw=1 -> retorno baixo) --
    prova que `predict_jump_model` de fato chama `canonicalize_states`,
    não apenas repassa `labels_` cru."""
    obs_test_fold = np.array(
        [
            [1.0, 0.1],
            [1.0, 0.1],
            [-1.0, 0.1],
            [-1.0, 0.1],
            [1.0, 0.1],
            [-1.0, 0.1],
        ],
        dtype=np.float64,
    )
    raw_labels = np.array([0, 0, 1, 1, 0, 1], dtype=np.int64)
    stub = _StubJumpModel(raw_labels, n_features=2)
    fit = JumpFit(model=stub, n_states=2, train_end_idx=100)

    canonical = predict_jump_model(fit, obs_test_fold)

    # raw=1 (retorno médio -1, o mais baixo) -> canonical 0
    # raw=0 (retorno médio +1, o mais alto) -> canonical 1
    expected = np.array([1, 1, 0, 0, 1, 0], dtype=np.int64)
    np.testing.assert_array_equal(canonical, expected)


def test_predict_jump_model_levanta_value_error_obs_test_fold_vazio() -> None:
    stub = _StubJumpModel(np.array([0], dtype=np.int64), n_features=2)
    fit = JumpFit(model=stub, n_states=2, train_end_idx=10)
    with pytest.raises(ValueError, match="vazio"):
        predict_jump_model(fit, np.empty((0, 2), dtype=np.float64))


def test_predict_jump_model_levanta_value_error_shape_features_diferente() -> None:
    stub = _StubJumpModel(np.array([0, 1], dtype=np.int64), n_features=2)
    fit = JumpFit(model=stub, n_states=2, train_end_idx=10)
    obs_test_fold_3_features = np.zeros((5, 3), dtype=np.float64)
    with pytest.raises(ValueError, match="features"):
        predict_jump_model(fit, obs_test_fold_3_features)


def test_predict_jump_model_levanta_value_error_obs_test_fold_com_nan() -> None:
    """Achado de auditoria (2026-08-17): sem esta checagem explícita, NaN em
    `obs_test_fold` crashava com `AssertionError` opaca de dentro de
    `jumpmodels` (`"input numerical object contains NaNs."`, sem contexto de
    symbol/fold/classifier_id) em vez do `ValueError` limpo que as outras
    checagens de `predict_jump_model` já dão -- reproduzido empiricamente
    antes da correção, não só hipotético."""
    stub = _StubJumpModel(np.array([0, 1], dtype=np.int64), n_features=2)
    fit = JumpFit(model=stub, n_states=2, train_end_idx=10)
    obs_test_fold = np.array([[1.0, 0.1], [np.nan, 0.1]], dtype=np.float64)
    with pytest.raises(ValueError, match="não-finito"):
        predict_jump_model(fit, obs_test_fold)


def test_predict_jump_model_levanta_value_error_obs_test_fold_com_inf() -> None:
    """Achado de auditoria (2026-08-17), o lado mais grave: sem esta
    checagem, Inf em `obs_test_fold` não era pego por NENHUMA validação
    (nem deste módulo, nem de `jumpmodels` -- que só checa NaN via
    `pd.isna`, que não cobre Inf) -- decodificava SILENCIOSAMENTE, sem
    exceção nem log, com o Inf se propagando pra frente por todo o resto do
    fold dentro da DP tipo Viterbi (`values[t] = loss_mx[t] + (values[t-1]
    + penalty_mx).min(...)`), produzindo rótulos degenerados com aparência
    normal. Reproduzido empiricamente contra o CJM real (não o stub) antes
    da correção: 1 `inf` isolado bastava pra degenerar o resto do fold sem
    nenhum sinal de erro."""
    stub = _StubJumpModel(np.array([0, 1], dtype=np.int64), n_features=2)
    fit = JumpFit(model=stub, n_states=2, train_end_idx=10)
    obs_test_fold = np.array([[1.0, 0.1], [np.inf, 0.1]], dtype=np.float64)
    with pytest.raises(ValueError, match="não-finito"):
        predict_jump_model(fit, obs_test_fold)


def test_predict_jump_model_com_cjm_real_inf_nao_degenera_silenciosamente() -> None:
    """Mesmo achado do teste acima, mas contra o `JumpModel` REAL (não o
    stub) -- prova que a checagem intercepta ANTES de `.predict()` ser
    chamado na lib de verdade, não só contra um dublê que nunca exercitaria
    o caminho real da DP/`cdist`. Sem a correção, este teste falhava
    silenciosamente (nenhuma exceção, rótulos degenerados devolvidos como
    se nada tivesse acontecido)."""
    rng = np.random.default_rng(7)
    obs, _ = _two_regime_obs(rng)
    train_end_idx = 400

    fit = fit_jump_model(
        obs, n_states=2, jump_penalty=_TEST_JUMP_PENALTY, train_end_idx=train_end_idx, seed=3
    )
    assert fit is not None

    test_fold = obs[train_end_idx : train_end_idx + 50].copy()
    test_fold[10, 0] = np.inf
    with pytest.raises(ValueError, match="não-finito"):
        predict_jump_model(fit, test_fold)


# ============================================================================
# fit_jump_model -- validação estrutural vs. falha de dado (None)
# ============================================================================


def test_fit_jump_model_levanta_value_error_train_end_idx_fora_do_range() -> None:
    obs = np.zeros((10, 2), dtype=np.float64)
    with pytest.raises(ValueError, match="train_end_idx"):
        fit_jump_model(obs, n_states=2, jump_penalty=_TEST_JUMP_PENALTY, train_end_idx=0)
    with pytest.raises(ValueError, match="train_end_idx"):
        fit_jump_model(obs, n_states=2, jump_penalty=_TEST_JUMP_PENALTY, train_end_idx=11)


def test_fit_jump_model_levanta_value_error_n_states_menor_que_2() -> None:
    obs = np.zeros((10, 2), dtype=np.float64)
    with pytest.raises(ValueError, match="n_states"):
        fit_jump_model(obs, n_states=1, jump_penalty=_TEST_JUMP_PENALTY, train_end_idx=5)


def test_fit_jump_model_levanta_value_error_obs_nao_2d() -> None:
    obs_1d = np.zeros(10, dtype=np.float64)
    with pytest.raises(ValueError, match="2D"):
        fit_jump_model(obs_1d, n_states=2, jump_penalty=_TEST_JUMP_PENALTY, train_end_idx=5)


def test_fit_jump_model_retorna_none_quando_train_end_idx_pequeno_demais_para_n_states() -> None:
    """`train_end_idx` estruturalmente válido (`0 < train_end_idx <=
    len(obs)`), mas com MENOS barras que `n_states` -- k-means++ não
    consegue inicializar centros. Falha de DADO, não de chamada -- `None`,
    não `ValueError` (contrato documentado em `fit_jump_model`)."""
    rng = np.random.default_rng(1)
    obs = rng.normal(size=(20, 2)).astype(np.float64)
    result = fit_jump_model(
        obs, n_states=3, jump_penalty=_TEST_JUMP_PENALTY, train_end_idx=2, seed=0
    )
    assert result is None


# ============================================================================
# Determinismo -- mesma seed, mesmo input -> mesmo output
# ============================================================================


def test_determinismo_mesma_seed_mesmo_input() -> None:
    rng = np.random.default_rng(3)
    obs, _ = _two_regime_obs(rng)
    train_end_idx = 400

    fit1 = fit_jump_model(
        obs, n_states=2, jump_penalty=_TEST_JUMP_PENALTY, train_end_idx=train_end_idx, seed=7
    )
    fit2 = fit_jump_model(
        obs, n_states=2, jump_penalty=_TEST_JUMP_PENALTY, train_end_idx=train_end_idx, seed=7
    )
    assert fit1 is not None
    assert fit2 is not None

    test_fold = obs[train_end_idx:]
    labels1 = predict_jump_model(fit1, test_fold)
    labels2 = predict_jump_model(fit2, test_fold)
    np.testing.assert_array_equal(labels1, labels2)


# ============================================================================
# Correção estrutural -- CJM recupera separação de 2 regimes sintéticos
# ============================================================================


def test_recupera_separacao_estrutural_2_regimes_sinteticos() -> None:
    rng = np.random.default_rng(0)
    obs, true_state = _two_regime_obs(rng)

    fit = fit_jump_model(
        obs, n_states=2, jump_penalty=_TEST_JUMP_PENALTY, train_end_idx=obs.shape[0], seed=42
    )
    assert fit is not None

    labels = predict_jump_model(fit, obs)
    ari = adjusted_rand_score(true_state, labels)
    assert ari > 0.8, f"ARI baixo demais ({ari:.3f}) -- CJM não separou os 2 regimes sintéticos"


# ============================================================================
# Compromisso de causalidade -- os DOIS lados, não só o "seguro"
# ============================================================================


def test_perturbar_fora_do_fold_nao_muda_decode_do_fold() -> None:
    """Perturbar o array de origem FORA do intervalo `[train_end_idx,
    train_end_idx + K)` -- seja a região de treino (já consumida por
    `fit_jump_model`, que copia internamente via `jumpmodels`/`pandas`,
    não retém referência viva) seja uma região "futura" além do fold de
    teste -- não muda a decodificação do fold, DADO um `fit` já ajustado.
    `predict_jump_model` só enxerga o array explícito que recebe."""
    rng = np.random.default_rng(5)
    obs, _ = _two_regime_obs(rng)
    train_end_idx = 400
    fold_len = 50

    fit = fit_jump_model(
        obs, n_states=2, jump_penalty=_TEST_JUMP_PENALTY, train_end_idx=train_end_idx, seed=11
    )
    assert fit is not None

    test_fold = obs[train_end_idx : train_end_idx + fold_len].copy()
    labels_base = predict_jump_model(fit, test_fold)

    # perturba o array ORIGINAL fora do intervalo do fold -- treino inteiro
    # e o restante "futuro" além do fold -- SEM tocar `test_fold` (cópia
    # independente) nem re-ajustar `fit`.
    obs_perturbed = obs.copy()
    rng2 = np.random.default_rng(999)
    obs_perturbed[:train_end_idx] = rng2.normal(size=(train_end_idx, 2))
    obs_perturbed[train_end_idx + fold_len :] = rng2.normal(
        size=(obs.shape[0] - train_end_idx - fold_len, 2)
    )

    # o mesmo `fit` (já congelado), decodificando o MESMO `test_fold` --
    # perturbar `obs_perturbed` em outro lugar não pode ter afetado nem
    # `fit` nem `test_fold`.
    labels_after_outside_perturbation = predict_jump_model(fit, test_fold)
    np.testing.assert_array_equal(labels_base, labels_after_outside_perturbation)


def _regime_block(kind: str, n: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    if kind == "a":
        return rng.normal(loc=[-0.01, 0.02], scale=[0.002, 0.005], size=(n, 2))
    return rng.normal(loc=[0.01, 0.06], scale=[0.002, 0.005], size=(n, 2))


def test_perturbar_fim_do_fold_pode_mudar_inicio_do_mesmo_fold() -> None:
    """O lado NÃO escondido do compromisso: dentro do MESMO fold de
    teste, barras ambíguas (perto do meio-termo entre os 2 centros)
    podem ter o rótulo CANÔNICO alterado só por causa de observações
    POSTERIORES no mesmo fold -- consequência direta do traceback global
    da DP tipo Viterbi (`jumpmodels.jump.dp`), documentada no módulo, não
    escondida.

    Desenho "sanduíche" (`LEAD_A` fixo + `AMBIGUOUS` + `MID_SWITCH`
    variável + `TAIL_B` fixo) -- achado real ao escrever este teste
    (não hipotético): um desenho ingênuo (só `AMBIGUOUS` + cauda pura A
    OU pura B) faz o fold INTEIRO colapsar num único estado bruto em
    cada variante -- e como `predict_jump_model` canonicaliza POR FOLD
    (`canonicalize_states` sobre só os estados presentes NESSA chamada),
    um fold de 1 estado só sempre vira canônico `0` trivialmente, então
    as duas variantes (colapsadas em estados brutos DIFERENTES) davam o
    MESMO canônico -- um falso negativo que escondia o efeito em vez de
    provar o lado seguro por engano. `LEAD_A`/`TAIL_B` ancoram os 2
    estados em AMBAS as variantes (nunca degenera pra 1 estado só),
    isolando o efeito real: mover `MID_SWITCH` (que fica DEPOIS da zona
    ambígua dentro do fold) desloca a fronteira de decisão pra TRÁS,
    dentro da própria zona ambígua."""
    rng = np.random.default_rng(0)
    obs, _ = _two_regime_obs(rng)

    fit = fit_jump_model(
        obs, n_states=2, jump_penalty=_TEST_JUMP_PENALTY, train_end_idx=obs.shape[0], seed=42
    )
    assert fit is not None
    centers = fit.model.centers_
    midpoint = (centers[0] + centers[1]) / 2.0

    lead_a = _regime_block("a", 20, seed=111)  # ancora estado A -- sempre presente
    rng_ambiguous = np.random.default_rng(99)
    ambiguous = midpoint + rng_ambiguous.normal(0.0, 0.0005, size=(20, 2))
    tail_b = _regime_block("b", 20, seed=222)  # ancora estado B -- sempre presente

    fold_mid_a = np.concatenate(
        [lead_a, ambiguous, _regime_block("a", 10, seed=333), tail_b]
    ).astype(np.float64)
    fold_mid_b = np.concatenate(
        [lead_a, ambiguous, _regime_block("b", 10, seed=333), tail_b]
    ).astype(np.float64)

    labels_mid_a = predict_jump_model(fit, fold_mid_a)
    labels_mid_b = predict_jump_model(fit, fold_mid_b)

    ambiguous_slice = slice(20, 40)  # índices da zona ambígua -- idêntica nas 2 variantes
    n_differing = int(np.sum(labels_mid_a[ambiguous_slice] != labels_mid_b[ambiguous_slice]))
    assert n_differing > 0, (
        "nenhuma barra ambígua mudou -- compromisso de causalidade em bloco não reproduzido "
        "(ou o desenho sintético deste teste precisa de ajuste, não o módulo)"
    )

    # o lado "seguro" TAMBÉM vale dentro do mesmo teste: o LEAD (bem antes
    # da zona ambígua, índices 0:20) não muda -- só a região perto da
    # fronteira de decisão é afetada, não o fold inteiro indiscriminadamente.
    lead_slice = slice(0, 20)
    np.testing.assert_array_equal(labels_mid_a[lead_slice], labels_mid_b[lead_slice])
