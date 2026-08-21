"""Testes de `src/regime/build_hmm.py` -- builder de produção do candidato
HMM canônico (Fase B/E do plano `wise-exploring-panda.md`, 2026-08-21,
`PLANO_MESTRE_PRINCE2.md §15.13`). Núcleo com IO (`lake.query_dollar_bars`
stubado, mesmo padrão de `test_analysis_m4_regime_comparison.py`) --
walk-forward real (`fit_hmm_gaussian`/`predict_hmm_gaussian` de verdade,
não mockados) sobre dado sintético de 2 regimes bem separados, mesmos
parâmetros já validados em `test_analysis_m4_regime_comparison.
_synthetic_bars_df` ("o suficiente pra HMM/Jump Model encontrarem
estrutura real")."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import polars as pl
import pytest
from sklearn.metrics import adjusted_rand_score

from src.data import lake
from src.regime import build_hmm, hmm_features
from src.regime.hmm_gaussian import HMMFit
from src.regime.hmm_gaussian import fit_hmm_gaussian as _real_fit_hmm_gaussian
from src.validation import volatility_walkforward as vwf

_DAY_MS = 86_400_000


def _synthetic_bars_df_2regime(
    n_days: int, *, seed: int = 7, block: int = 30
) -> tuple[pl.DataFrame, np.ndarray]:
    """Granularidade diária (não dollar-bar real) só serve pra dar ao
    walk-forward (que corta por trimestre CIVIL) folds suficientes rápido
    -- mesma convenção de `test_analysis_m4_regime_comparison.
    _synthetic_bars_df`/`test_analysis_volatility_comparison.
    _synthetic_bars_df`. Devolve também `true_regime` (0/1 por dia,
    alinhado por POSIÇÃO com `bars_df`) pra checagem de ARI."""
    rng = np.random.default_rng(seed)
    open_time = np.arange(n_days, dtype=np.int64) * _DAY_MS
    close_time = open_time + _DAY_MS - 1

    log_returns = np.empty(n_days - 1, dtype=np.float64)
    true_regime = np.zeros(n_days, dtype=np.int64)
    for i in range(n_days - 1):
        state = (i // block) % 2
        if state == 0:
            log_returns[i] = rng.normal(-0.01, 0.002)
        else:
            log_returns[i] = rng.normal(0.01, 0.005)
        true_regime[i + 1] = state
    close = 100.0 * np.exp(np.concatenate([[0.0], np.cumsum(log_returns)]))
    bars_df = pl.DataFrame({"open_time": open_time, "close_time": close_time, "close": close})
    return bars_df, true_regime


def _stub_query_dollar_bars_returning(bars_df: pl.DataFrame) -> Callable[..., pl.DataFrame]:
    def _stub(
        symbol: str, start: str, end: str, *, resolution_id: str = "R1", **_kwargs: object
    ) -> pl.DataFrame:
        return bars_df

    return _stub


# ============================================================================
# Valor conhecido -- 2 clusters sintéticos bem separados
# ============================================================================


@pytest.mark.slow
def test_recupera_separacao_de_2_clusters_na_regiao_decodificada(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    n_days = 550
    bars_df, true_regime = _synthetic_bars_df_2regime(n_days, seed=7, block=30)
    monkeypatch.setattr(lake, "query_dollar_bars", _stub_query_dollar_bars_returning(bars_df))

    result = build_hmm.build_hmm_regimes(
        "TESTUSDT", "2020-01-01", "2021-07-04", n_states=2, initial_train_years=1, seed=11
    )

    log_return_1_full, obs_2d_full = hmm_features.input_obs(bars_df)
    start_idx = hmm_features.valid_start_idx(log_return_1_full, obs_2d_full[:, 1])
    true_regime_cropped = true_regime[start_idx:]
    assert true_regime_cropped.shape[0] == result.height

    canonical_id = result["canonical_id"].to_numpy()
    decoded_mask = canonical_id != -1
    assert decoded_mask.any(), "esperava pelo menos 1 fold decodificado com dado de 550 dias"

    ari = adjusted_rand_score(true_regime_cropped[decoded_mask], canonical_id[decoded_mask])
    assert ari > 0.6, f"ARI={ari} -- build_hmm_regimes não recuperou a separação real dos clusters"


# ============================================================================
# Caso degenerado -- histórico curto demais (sem folds)
# ============================================================================


def test_historico_curto_sem_folds_tudo_tradeable_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """`initial_train_years=1` exige >4 trimestres civis distintos
    (`generate_anchored_walk_forward_splits`) -- 200 dias a partir de
    2020-01-01 cobre só 3 (Q1/Q2/Q3 parcial de 2020), `splits` vazio.
    Nenhuma exceção -- toda barra sai `tradeable=False`/sentinela -1."""
    n_days = 200
    bars_df, _true_regime = _synthetic_bars_df_2regime(n_days, seed=3, block=30)
    monkeypatch.setattr(lake, "query_dollar_bars", _stub_query_dollar_bars_returning(bars_df))

    result = build_hmm.build_hmm_regimes(
        "TESTUSDT", "2020-01-01", "2020-07-19", n_states=2, initial_train_years=1, seed=0
    )

    assert result.height > 0
    assert not result["tradeable"].any()
    assert not result["is_stress_state"].any()
    assert (result["canonical_id"] == -1).all()
    assert (result["fold_id"] == -1).all()


# ============================================================================
# Fold individual degenerado -- sentinela local, resto segue normal
# ============================================================================


@pytest.mark.slow
def test_fold_degenerado_vira_sentinela_local_resto_segue_normal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Força o 1o fold a degenerar (`fit_hmm_gaussian` -> `None`, mesmo
    contrato de `_run_fold_refit_candidate` do M4) via monkeypatch da
    referência importada em `build_hmm` -- determinístico, não depende de
    o dado sintético degenerar "por sorte". Prova que 1 fold ruim não
    derruba o walk-forward inteiro: a região do fold 0 fica sentinela
    (-1/`tradeable=False`), os folds seguintes decodificam normalmente."""
    n_days = 550
    bars_df, _true_regime = _synthetic_bars_df_2regime(n_days, seed=7, block=30)
    monkeypatch.setattr(lake, "query_dollar_bars", _stub_query_dollar_bars_returning(bars_df))

    call_count = {"n": 0}

    def _flaky_fit(
        obs: np.ndarray, *, n_states: int, train_end_idx: int, seed: int
    ) -> HMMFit | None:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return None
        return _real_fit_hmm_gaussian(
            obs, n_states=n_states, train_end_idx=train_end_idx, seed=seed
        )

    monkeypatch.setattr(build_hmm, "fit_hmm_gaussian", _flaky_fit)

    result = build_hmm.build_hmm_regimes(
        "TESTUSDT", "2020-01-01", "2021-07-04", n_states=2, initial_train_years=1, seed=11
    )

    assert call_count["n"] >= 2, "teste precisa de >=2 folds pra isolar o 1o degenerado"
    canonical_id = result["canonical_id"].to_numpy()
    fold_id = result["fold_id"].to_numpy()
    tradeable = result["tradeable"].to_numpy()

    # fold_id 0 (do 1o split, forçado a falhar) nunca aparece no output --
    # a região correspondente fica no sentinela -1, nunca renumerada.
    assert not np.any(fold_id == 0)
    assert np.any(canonical_id == -1), "esperava sentinela -1 na região do fold degenerado"
    assert np.any(canonical_id != -1), "esperava >=1 fold decodificado normalmente"
    assert not tradeable[canonical_id == -1].any()


# ============================================================================
# Causalidade -- perturbar o ÚLTIMO fold não muda folds anteriores
# ============================================================================


@pytest.mark.slow
def test_causalidade_perturbar_ultimo_fold_nao_muda_canonical_id_anterior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prefix-invariance da ORQUESTRAÇÃO de fold (não redundante com a
    causalidade já provada em `test_regime_hmm_gaussian.py`/`hmm_gaussian.
    py` para `predict_hmm_gaussian` isolado -- aqui o alvo é o LOOP de
    `build_hmm_regimes`: cada fold só fita `obs[:train_end_idx]` e
    decodifica só `obs[test_start:test_end]`, então perturbar o preço a
    partir do início do ÚLTIMO fold não pode mudar `canonical_id` de
    nenhum fold anterior.

    Cobre TAMBÉM `is_stress_state`/`tradeable` (não só `canonical_id`) --
    fix de `AG-127` Ângulo 1 (`audit/architecture_gaps_log.yaml`): até
    2026-08-21, `stress_state_id` era identificado UMA ÚNICA VEZ, pós-loop,
    sobre o array OOS concatenado do símbolo/período INTEIRO -- vazamento
    temporal genuíno na canonicalização (perturbar o último fold mudava a
    rotulagem "stress" de folds passados, mesmo com `canonical_id`
    intocado). Corrigido: `identify_stress_state_by_volatility` agora roda
    DENTRO do loop, por fold, sobre `obs[:train_end_idx]` decodificado (o
    próprio treino do fold, nunca o OOS de folds futuros), e o
    `stress_state_id` resultante só é aplicado à fatia de TESTE do mesmo
    fold -- causal de ponta a ponta, mesma disciplina de prefix-invariance
    que já valia pra `canonical_id`, agora também pra `is_stress_state`/
    `tradeable`."""
    n_days = 550
    bars_df, _true_regime = _synthetic_bars_df_2regime(n_days, seed=7, block=30)

    log_return_1_full, obs_2d_full = hmm_features.input_obs(bars_df)
    start_idx = hmm_features.valid_start_idx(log_return_1_full, obs_2d_full[:, 1])
    open_time_ms_cropped = bars_df["open_time"].cast(pl.Int64).to_numpy()[start_idx:]
    splits = vwf.generate_anchored_walk_forward_splits(open_time_ms_cropped, initial_train_years=1)
    assert len(splits) >= 2, "teste precisa de >=2 folds pra isolar o último"
    last_split = splits[-1]
    perturb_from = start_idx + last_split.test_start_idx

    close = bars_df["close"].to_numpy().copy()
    rng = np.random.default_rng(999)
    close[perturb_from:] = close[perturb_from:] * (
        1.0 + rng.normal(0.0, 0.05, size=close.shape[0] - perturb_from)
    )
    bars_perturbed = bars_df.with_columns(pl.Series("close", close))

    state = {"df": bars_df}

    def _stub(
        symbol: str, start: str, end: str, *, resolution_id: str = "R1", **_kwargs: object
    ) -> pl.DataFrame:
        return state["df"]

    monkeypatch.setattr(lake, "query_dollar_bars", _stub)

    result_original = build_hmm.build_hmm_regimes(
        "TESTUSDT", "2020-01-01", "2021-07-04", n_states=2, initial_train_years=1, seed=11
    )
    state["df"] = bars_perturbed
    result_perturbed = build_hmm.build_hmm_regimes(
        "TESTUSDT", "2020-01-01", "2021-07-04", n_states=2, initial_train_years=1, seed=11
    )

    boundary = last_split.test_start_idx
    np.testing.assert_array_equal(
        result_original["canonical_id"].to_numpy()[:boundary],
        result_perturbed["canonical_id"].to_numpy()[:boundary],
    )
    np.testing.assert_array_equal(
        result_original["is_stress_state"].to_numpy()[:boundary],
        result_perturbed["is_stress_state"].to_numpy()[:boundary],
    )
    np.testing.assert_array_equal(
        result_original["tradeable"].to_numpy()[:boundary],
        result_perturbed["tradeable"].to_numpy()[:boundary],
    )


# ============================================================================
# Determinismo -- mesma seed, mesmo dado -> mesmo output bit-a-bit
# ============================================================================


@pytest.mark.slow
def test_determinismo_mesma_seed_mesmo_dado_mesmo_output(monkeypatch: pytest.MonkeyPatch) -> None:
    n_days = 550
    bars_df, _true_regime = _synthetic_bars_df_2regime(n_days, seed=7, block=30)
    monkeypatch.setattr(lake, "query_dollar_bars", _stub_query_dollar_bars_returning(bars_df))

    result_a = build_hmm.build_hmm_regimes(
        "TESTUSDT", "2020-01-01", "2021-07-04", n_states=2, initial_train_years=1, seed=5
    )
    result_b = build_hmm.build_hmm_regimes(
        "TESTUSDT", "2020-01-01", "2021-07-04", n_states=2, initial_train_years=1, seed=5
    )

    np.testing.assert_array_equal(
        result_a["canonical_id"].to_numpy(), result_b["canonical_id"].to_numpy()
    )
    np.testing.assert_array_equal(
        result_a["tradeable"].to_numpy(), result_b["tradeable"].to_numpy()
    )
    np.testing.assert_array_equal(
        result_a["is_stress_state"].to_numpy(), result_b["is_stress_state"].to_numpy()
    )
    np.testing.assert_array_equal(result_a["fold_id"].to_numpy(), result_b["fold_id"].to_numpy())
