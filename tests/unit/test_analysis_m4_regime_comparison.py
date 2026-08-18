"""Testes de `src/analysis/m4_regime_comparison.py` -- harness de
orquestração da Fase 3 do plano M4 (`wise-exploring-panda.md`). Mesmo
estilo de `test_analysis_volatility_comparison.py`: núcleo puro
(`compare_regime_candidates_for_symbol`) exercitado com `bars_df`/
`baseline_df` SINTÉTICOS (sem tocar disco); `run_regime_comparison_for_
symbol` só tocado no teste `integration`/`slow` final.

Foco central diferente de `test_regime_bocpd.py`/`test_regime_hmm_
gaussian.py`/`test_regime_jump_model.py` (que já provam a correção
estatística/causal INTERNA de cada candidato): aqui o que importa é a
MONTAGEM -- o harness passa a fatia certa de dado pra cada candidato, sem
vazar fold futuro pro fit de um fold anterior, e sem inventar métrica
onde a definição já foi resolvida no plano (BOCPD/baseline `fold_
stability_by_construction=True`)."""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from src.analysis import m4_regime_comparison as m4
from src.data._paths import CAPACITY_DIR
from src.features import support as features_support
from src.features._constants import load_constant as load_feature_constant
from src.regime import classifier
from src.regime.bocpd import run_bocpd as _real_run_bocpd
from src.regime.classifier import QuantileRegimeClassifier
from src.regime.hmm_gaussian import fit_hmm_gaussian as _real_fit_hmm
from src.regime.hmm_gaussian import predict_hmm_gaussian as _real_predict_hmm
from src.regime.jump_model import fit_jump_model as _real_fit_jump
from src.regime.jump_model import predict_jump_model as _real_predict_jump
from src.validation import volatility_walkforward as vwf

_SHORT_WINDOW = int(load_feature_constant("feature_c06_vol_ratio_short_window"))


# ============================================================================
# Fixtures sintéticas -- bars_df (dollar bar minimalista) + baseline_df
# (schema mínimo real de build_regimes: t0/regime/vol_pctile/classifier_id)
# ============================================================================


def _synthetic_bars_df(n_days: int, *, seed: int = 7, block: int = 30) -> pl.DataFrame:
    """`close` construído a partir de 2 "regimes" reais bem separados
    (média/volatilidade distintas), alternando em blocos de `block` dias --
    mesmo espírito de `test_regime_jump_model._two_regime_obs`, o
    suficiente pra HMM/Jump Model encontrarem estrutura real nos testes
    que precisam de fits não-degenerados. Granularidade DIÁRIA (não
    dollar-bar real) só serve pra dar ao walk-forward (que corta por
    trimestre CIVIL) folds suficientes rápido -- mesma convenção de
    `test_analysis_volatility_comparison._synthetic_bars_df`."""
    rng = np.random.default_rng(seed)
    day_ms = 86_400_000
    open_time = np.arange(n_days, dtype=np.int64) * day_ms

    log_returns = np.empty(n_days - 1, dtype=np.float64)
    for i in range(n_days - 1):
        if (i // block) % 2 == 0:
            log_returns[i] = rng.normal(-0.01, 0.002)
        else:
            log_returns[i] = rng.normal(0.01, 0.005)
    close = 100.0 * np.exp(np.concatenate([[0.0], np.cumsum(log_returns)]))
    return pl.DataFrame({"open_time": open_time, "close": close})


def _synthetic_baseline_df(
    bars_df: pl.DataFrame, *, seed: int = 11, warmup: int = 20, block: int = 25
) -> pl.DataFrame:
    """Schema mínimo que `m4_regime_comparison.py` de fato lê de
    `baseline_df` (`t0`, `regime`, `vol_pctile`, `classifier_id`) -- não o
    schema completo de `classify_regimes` (11 colunas), decisão deliberada
    de manter a fixture pequena e focada no que é consumido. `t0`
    construído por round-trip exato de `open_time` (mesma fórmula de
    `classify_regimes`: `from_epoch(ms).replace_time_zone("UTC").
    cast_time_unit("ns")`) -- garante alinhamento com `bars_df` por
    construção nos testes que não estão testando desalinhamento de
    propósito. R0 só como PREFIXO (`warmup` dias) -- mesma invariante real
    de `classifier._run_state_machine` (R0 é puramente por índice, nunca
    reaparece depois)."""
    n = bars_df.height
    rng = np.random.default_rng(seed)
    open_time_ms = bars_df["open_time"].cast(pl.Int64).to_numpy()
    t0 = (
        pl.from_epoch(pl.Series(open_time_ms), time_unit="ms")
        .dt.replace_time_zone("UTC")
        .dt.cast_time_unit("ns")
    )

    regime = np.full(n, "R1", dtype=object)
    regime[:warmup] = "R0"
    cycle = ["R1", "R2", "R3"]
    for i in range(warmup, n):
        regime[i] = cycle[((i - warmup) // block) % len(cycle)]

    vol_pctile = rng.uniform(0.0, 1.0, size=n)
    classifier_id = QuantileRegimeClassifier(symbol="TESTUSDT").classifier_id

    return pl.DataFrame(
        {
            "t0": t0,
            "regime": pl.Series(regime).cast(pl.Enum(list(classifier.REGIME_LABELS))),
            "vol_pctile": vol_pctile,
            "classifier_id": pl.Series([classifier_id] * n),
        }
    )


_CANDIDATE_KWARGS: dict[str, object] = {
    "jump_n_states": 2,
    # 0.001, não 0.01 -- achado real ao rodar este teste: com o espaço de
    # features/dado sintético deste arquivo (blocos de 30 dias, ver
    # _synthetic_bars_df), 0.01 satura o CJM num único estado em TODA
    # janela de teste trimestral (mesmo achado de escala documentado em
    # src/regime/jump_model.py, item 6 -- jump_penalty é sensível à escala
    # REAL do dado de entrada, não um valor universal "razoável" que
    # funcione em qualquer fixture).
    "jump_penalty": 0.001,
    "bocpd_hazard_lambda": 100.0,
    "bocpd_n_canonical_buckets": 2,
}


# ============================================================================
# _input_obs / _valid_start_idx -- valores conhecidos à mão
# ============================================================================


def test_input_obs_log_return_1_valores_conhecidos() -> None:
    close = np.array([100.0, 101.0, 99.0, 102.0, 100.0], dtype=np.float64)
    bars_df = pl.DataFrame(
        {"open_time": np.arange(5, dtype=np.int64) * 86_400_000, "close": close}
    )
    log_return_1, obs_2d = m4._input_obs(bars_df)

    assert np.isnan(log_return_1[0])
    expected = np.log(close[1:] / close[:-1])
    np.testing.assert_allclose(log_return_1[1:], expected)
    # coluna 0 do obs_2d é log_return_1, bit-a-bit (mesmo array)
    np.testing.assert_allclose(obs_2d[:, 0], log_return_1, equal_nan=True)
    assert obs_2d.shape == (5, 2)


def test_input_obs_realized_vol_short_valor_conhecido_e_min_periods_estrito() -> None:
    """`realized_vol_short` reusa `support.realized_vol` (σ × √window,
    `min_samples=window` estrito) -- este teste verifica um valor
    calculado À MÃO (fórmula independente, não chamando `support.
    realized_vol`) numa posição conhecida, e confirma o achado real
    documentado no módulo: o primeiro índice finito é `window`, não
    `window-1` (o NaN estrutural de log_return_1[0] propaga por toda
    janela que o contém)."""
    n = _SHORT_WINDOW + 5
    rng = np.random.default_rng(123)
    log_returns = rng.normal(0.0, 0.01, size=n - 1)
    close = 100.0 * np.exp(np.concatenate([[0.0], np.cumsum(log_returns)]))
    bars_df = pl.DataFrame({"open_time": np.arange(n, dtype=np.int64), "close": close})

    log_return_1, obs_2d = m4._input_obs(bars_df)

    # 1 índice antes do primeiro valor finito esperado: ainda dentro da
    # janela que contém log_return_1[0] (NaN) -> NaN.
    assert np.isnan(obs_2d[_SHORT_WINDOW - 1, 1])

    t = _SHORT_WINDOW
    window_slice = log_return_1[t - _SHORT_WINDOW + 1 : t + 1]
    assert np.all(np.isfinite(window_slice)), "janela de teste não deveria conter o NaN inicial"
    expected = float(np.std(window_slice, ddof=1)) * np.sqrt(_SHORT_WINDOW)
    assert obs_2d[t, 1] == pytest.approx(expected)

    # cross-check independente: bate com a primitiva real de produção.
    expected_full = features_support.realized_vol(log_return_1, _SHORT_WINDOW)
    np.testing.assert_allclose(obs_2d[:, 1], expected_full, equal_nan=True)


def test_valid_start_idx_e_window_nao_window_menos_1() -> None:
    n = _SHORT_WINDOW + 5
    rng = np.random.default_rng(1)
    log_returns = rng.normal(0.0, 0.01, size=n - 1)
    close = 100.0 * np.exp(np.concatenate([[0.0], np.cumsum(log_returns)]))
    bars_df = pl.DataFrame({"open_time": np.arange(n, dtype=np.int64), "close": close})

    log_return_1, obs_2d = m4._input_obs(bars_df)
    idx = m4._valid_start_idx(log_return_1, obs_2d[:, 1])
    assert idx == _SHORT_WINDOW


def test_valid_start_idx_levanta_value_error_serie_curta_demais() -> None:
    log_return_1 = np.full(3, np.nan, dtype=np.float64)
    realized_vol_short = np.full(3, np.nan, dtype=np.float64)
    with pytest.raises(ValueError, match="curta demais"):
        m4._valid_start_idx(log_return_1, realized_vol_short)


# ============================================================================
# _run_fold_refit_candidate -- montagem do fold-refit (HMM/Jump Model
# compartilham este núcleo), causalidade da MONTAGEM via stub que grava
# argumentos recebidos.
# ============================================================================


def test_run_fold_refit_candidate_fit_recebe_train_end_idx_expansivo_predict_so_fatia_do_fold() -> (
    None
):
    n = 400
    obs_2d = np.column_stack(
        [np.arange(n, dtype=np.float64), np.arange(n, dtype=np.float64) * 2.0]
    )
    splits = (
        vwf.WalkForwardSplit(fold_id=0, train_end_idx=100, test_start_idx=100, test_end_idx=200),
        vwf.WalkForwardSplit(fold_id=1, train_end_idx=200, test_start_idx=200, test_end_idx=300),
        vwf.WalkForwardSplit(fold_id=2, train_end_idx=300, test_start_idx=300, test_end_idx=400),
    )

    fit_calls: list[tuple[int, int]] = []
    predict_calls: list[tuple[float, int]] = []

    def _stub_fit(obs: np.ndarray, train_end_idx: int) -> dict[str, int]:
        fit_calls.append((obs.shape[0], train_end_idx))
        return {"train_end_idx": train_end_idx}

    def _stub_predict(fit: dict[str, int], obs_slice: np.ndarray) -> np.ndarray:
        predict_calls.append((float(obs_slice[0, 0]), obs_slice.shape[0]))
        return (np.arange(obs_slice.shape[0]) % 2).astype(np.int64)

    forward_return = np.linspace(-1.0, 1.0, n)
    vol_pctile = np.linspace(0.0, 1.0, n)

    result = m4._run_fold_refit_candidate(
        "stub_id",
        2,
        obs_2d,
        splits,
        fit_fn=_stub_fit,
        predict_fn=_stub_predict,
        forward_return=forward_return,
        vol_pctile=vol_pctile,
    )

    # fit_fn sempre recebe o obs COMPLETO (não pré-fatiado -- fit_hmm_
    # gaussian/fit_jump_model fazem obs[:train_end_idx] internamente) +
    # train_end_idx estritamente EXPANSIVO, na ordem dos folds.
    assert fit_calls == [(400, 100), (400, 200), (400, 300)]

    # as 3 primeiras chamadas de predict são o decode principal de cada
    # fold -- cada uma começa exatamente em test_start_idx do próprio fold
    # (obs_slice[0,0] == valor naquele índice, já que obs_2d[:,0]==arange).
    main_decode_calls = predict_calls[:3]
    assert main_decode_calls == [(100.0, 100), (200.0, 100), (300.0, 100)]
    # nenhuma chamada de predict nunca recebe o array inteiro (400 linhas)
    assert all(n_rows < n for _, n_rows in predict_calls)

    assert result.n_folds_evaluated == 3
    assert result.n_oos_obs == 300  # 3 folds de 100 barras, nenhuma falha
    # stub é determinístico (mesmo input -> mesmo output) -- os pares
    # adjacentes usados na estabilidade entre folds dão ARI == 1.0 exato.
    assert result.fold_stability_adjusted_rand_mean == pytest.approx(1.0)
    assert result.fold_stability_adjusted_rand_min == pytest.approx(1.0)
    assert result.fold_stability_by_construction is False


def test_run_fold_refit_candidate_fold_com_fit_none_e_excluido_sem_derrubar_os_outros() -> None:
    """Achado de desenho documentado em `_compact_valid`: um fold que falha
    (`fit_fn` retorna `None`, ex. dado insuficiente) é excluído das
    métricas, não propaga exceção, e os pares de estabilidade que
    envolveriam esse fold ficam de fora (não geram ARI espúrio)."""
    n = 300
    obs_2d = np.column_stack([np.arange(n, dtype=np.float64), np.zeros(n)])
    splits = (
        vwf.WalkForwardSplit(fold_id=0, train_end_idx=100, test_start_idx=100, test_end_idx=200),
        vwf.WalkForwardSplit(fold_id=1, train_end_idx=200, test_start_idx=200, test_end_idx=300),
    )

    def _stub_fit(obs: np.ndarray, train_end_idx: int) -> dict[str, int] | None:
        if train_end_idx == 100:
            return None  # simula fold 0 degenerado
        return {"train_end_idx": train_end_idx}

    def _stub_predict(fit: dict[str, int], obs_slice: np.ndarray) -> np.ndarray:
        return (np.arange(obs_slice.shape[0]) % 2).astype(np.int64)

    forward_return = np.linspace(-1.0, 1.0, n)
    vol_pctile = np.linspace(0.0, 1.0, n)

    result = m4._run_fold_refit_candidate(
        "stub_id",
        2,
        obs_2d,
        splits,
        fit_fn=_stub_fit,
        predict_fn=_stub_predict,
        forward_return=forward_return,
        vol_pctile=vol_pctile,
    )

    assert result.n_folds_evaluated == 1
    assert result.n_oos_obs == 100  # só o fold 1 (100 barras) sobrevive
    # nenhum par adjacente com os DOIS fits bem-sucedidos -- sem medição.
    assert np.isnan(result.fold_stability_adjusted_rand_mean)
    assert np.isnan(result.fold_stability_adjusted_rand_min)


# ============================================================================
# _bocpd_candidate_result / _baseline_candidate_result -- "por construção"
# ============================================================================


def test_bocpd_candidate_result_fold_stability_by_construction() -> None:
    # Mudança de volatilidade a meio da série (mesmo desenho de
    # test_regime_bocpd.py::test_detecta_changepoint_unico_injetado_no_
    # ponto_certo) -- garante >=2 segmentos reais, diferente de uma série
    # estacionária pura (que pode colapsar em 1 segmento só e faria
    # segments_to_canonical_states levantar ValueError pra n_buckets=2).
    rng = np.random.default_rng(3)
    n_each = 200
    log_return_1 = np.concatenate(
        [rng.normal(0.0, 0.02, n_each), rng.normal(0.0, 0.08, n_each)]
    ).astype(np.float64)
    n = int(log_return_1.shape[0])
    forward_return = np.concatenate([log_return_1[1:], [np.nan]])
    vol_pctile = rng.uniform(0.0, 1.0, size=n)

    result = m4._bocpd_candidate_result(
        log_return_1,
        50,
        n,
        hazard_lambda=100.0,
        n_canonical_buckets=2,
        forward_return=forward_return,
        vol_pctile=vol_pctile,
    )
    assert result.classifier_id == "bocpd_v1"
    assert result.n_states == 2
    assert result.fold_stability_by_construction is True
    assert result.fold_stability_adjusted_rand_mean == 1.0
    assert result.fold_stability_adjusted_rand_min == 1.0
    assert result.n_folds_evaluated == 0
    assert result.n_oos_obs > 0


def test_run_fold_refit_candidate_candidato_degenerado_em_1_estado_nao_derruba_o_simbolo() -> None:
    """Achado real medido nesta sessão: `fit_jump_model` com `jump_penalty`
    mal calibrado pra escala do dado (mesmo achado #6 documentado em
    `src.regime.jump_model`) satura a região OOS inteira num único
    `canonical_id` -- tanto no fixture sintético deste arquivo quanto em
    BTCUSDT real (`jump_penalty=0.01`, ver `_CANDIDATE_KWARGS`/teste de
    integração). Antes da correção, `anova_by_group` levantava `ValueError`
    (k<2 grupos) e a exceção propagava até derrubar TODO o símbolo (baseline
    + os outros 4 candidatos junto) -- não só o candidato degenerado. Este
    teste prova a correção: `_run_fold_refit_candidate` reporta o
    degenerado como uma MEDIÇÃO (ω²/F-stat = NaN, `k_groups` real), não
    como falha do harness."""
    n = 200
    obs_2d = np.column_stack([np.arange(n, dtype=np.float64), np.zeros(n)])
    splits = (
        vwf.WalkForwardSplit(fold_id=0, train_end_idx=100, test_start_idx=100, test_end_idx=200),
    )

    def _stub_fit(obs: np.ndarray, train_end_idx: int) -> dict[str, int]:
        return {"train_end_idx": train_end_idx}

    def _stub_predict_sempre_mesmo_estado(fit: dict[str, int], obs_slice: np.ndarray) -> np.ndarray:
        # todo o fold decodifica pro MESMO canonical_id -- exatamente o
        # sintoma real medido (JumpModel saturado por jump_penalty alto
        # demais pra escala do dado).
        return np.zeros(obs_slice.shape[0], dtype=np.int64)

    forward_return = np.linspace(-1.0, 1.0, n)
    vol_pctile = np.linspace(0.0, 1.0, n)

    result = m4._run_fold_refit_candidate(
        "stub_degenerado",
        2,
        obs_2d,
        splits,
        fit_fn=_stub_fit,
        predict_fn=_stub_predict_sempre_mesmo_estado,
        forward_return=forward_return,
        vol_pctile=vol_pctile,
    )

    assert result.n_folds_evaluated == 1
    assert result.n_oos_obs == 100
    assert result.separation.k_groups == 1
    assert np.isnan(result.separation.omega_squared)
    assert np.isnan(result.separation.f_stat)
    assert result.orthogonality.k_groups == 1
    assert np.isnan(result.orthogonality.omega_squared)


def test_baseline_candidate_result_exclui_r0_das_metricas() -> None:
    n = 200
    regime_physical = np.empty(n, dtype=np.int64)
    regime_physical[:50] = 0  # R0 -- só prefixo, mesma invariante real
    regime_physical[50:125] = 1  # R1
    regime_physical[125:200] = 2  # R2
    forward_return = np.linspace(-1.0, 1.0, n)
    vol_pctile = np.linspace(0.0, 1.0, n)

    result = m4._baseline_candidate_result(
        regime_physical,
        0,
        n,
        forward_return=forward_return,
        vol_pctile=vol_pctile,
        classifier_id="quantile_regime_v1",
    )

    assert result.n_oos_obs == 150  # 200 - 50 barras R0 excluídas
    assert result.separation.k_groups == 2  # só R1/R2 sobrevivem no cálculo
    assert result.n_states == len(classifier.REGIME_LABELS)  # 6 -- nominal, não pós-filtro
    assert result.fold_stability_by_construction is True
    assert result.fold_stability_adjusted_rand_mean == 1.0
    assert result.n_folds_evaluated == 0


# ============================================================================
# compare_regime_candidates_for_symbol -- estrutura + alinhamento
# ============================================================================


def test_compare_regime_candidates_dado_insuficiente_retorna_none() -> None:
    bars_df = _synthetic_bars_df(200)  # ~6.5 meses, menos que 1 ano de treino inicial
    baseline_df = _synthetic_baseline_df(bars_df)
    result = m4.compare_regime_candidates_for_symbol(
        "TESTUSDT",
        bars_df,
        baseline_df,
        initial_train_years=1,
        hmm_states_grid=(2,),
        **_CANDIDATE_KWARGS,  # type: ignore[arg-type]
    )
    assert result is None


def test_compare_regime_candidates_levanta_value_error_altura_diferente() -> None:
    bars_df = _synthetic_bars_df(400)
    baseline_df = _synthetic_baseline_df(bars_df).slice(1, 399)
    with pytest.raises(ValueError, match="não alinhados"):
        m4.compare_regime_candidates_for_symbol(
            "TESTUSDT",
            bars_df,
            baseline_df,
            initial_train_years=1,
            hmm_states_grid=(2,),
            **_CANDIDATE_KWARGS,  # type: ignore[arg-type]
        )


def test_compare_regime_candidates_levanta_value_error_timestamp_divergente() -> None:
    bars_df = _synthetic_bars_df(400)
    baseline_df = _synthetic_baseline_df(bars_df)
    # mesma altura, mas 1 timestamp deliberadamente diferente
    bad_open_time = bars_df["open_time"].to_numpy().copy()
    bad_open_time[10] += 12345
    bars_df_bad = bars_df.with_columns(pl.Series("open_time", bad_open_time))
    with pytest.raises(ValueError, match="não estão alinhados"):
        m4.compare_regime_candidates_for_symbol(
            "TESTUSDT",
            bars_df_bad,
            baseline_df,
            initial_train_years=1,
            hmm_states_grid=(2,),
            **_CANDIDATE_KWARGS,  # type: ignore[arg-type]
        )


@pytest.mark.slow
def test_compare_regime_candidates_estrutura_do_resultado() -> None:
    bars_df = _synthetic_bars_df(1095)  # ~3 anos
    baseline_df = _synthetic_baseline_df(bars_df)

    result = m4.compare_regime_candidates_for_symbol(
        "TESTUSDT",
        bars_df,
        baseline_df,
        initial_train_years=2,
        hmm_states_grid=(2, 3),
        **_CANDIDATE_KWARGS,  # type: ignore[arg-type]
    )
    assert result is not None
    assert result.symbol == "TESTUSDT"
    assert result.n_bars == 1095
    assert result.n_folds > 0

    ids = [c.classifier_id for c in result.candidates]
    assert ids == ["hmm_gaussian_k2_v1", "hmm_gaussian_k3_v1", "jump_model_cjm_v1", "bocpd_v1"]
    n_states = [c.n_states for c in result.candidates]
    assert n_states == [2, 3, 2, 2]

    for c in result.candidates:
        assert c.n_oos_obs > 0
        assert c.separation.k_groups >= 1
        assert isinstance(c.fold_stability_by_construction, bool)

    assert result.baseline.classifier_id == "quantile_regime_v1"
    assert result.baseline.fold_stability_by_construction is True
    assert result.baseline.fold_stability_adjusted_rand_mean == 1.0
    assert result.baseline.n_folds_evaluated == 0

    hmm_k2 = result.candidates[0]
    assert hmm_k2.fold_stability_by_construction is False
    assert hmm_k2.n_folds_evaluated > 0

    jump = result.candidates[2]
    assert jump.fold_stability_by_construction is False

    bocpd = result.candidates[3]
    assert bocpd.fold_stability_by_construction is True
    assert bocpd.fold_stability_adjusted_rand_mean == 1.0
    assert bocpd.n_folds_evaluated == 0


# ============================================================================
# Causalidade da MONTAGEM (não da estatística interna, já provada em
# test_regime_bocpd.py/test_regime_hmm_gaussian.py/test_regime_jump_
# model.py) -- espiona os fit_*/predict_*/run_bocpd REAIS, tal como o
# harness os importa, prova que nenhum fold vê dado de um fold futuro.
# ============================================================================


@pytest.mark.slow
def test_harness_nao_vaza_dado_de_fold_futuro_e_bocpd_roda_uma_vez_sobre_serie_inteira(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bars_df = _synthetic_bars_df(1095)
    baseline_df = _synthetic_baseline_df(bars_df)

    hmm_fit_calls: list[tuple[int, int]] = []
    hmm_predict_calls: list[int] = []
    jump_fit_calls: list[tuple[int, int]] = []
    jump_predict_calls: list[int] = []
    bocpd_calls: list[int] = []

    def _spy_fit_hmm(
        obs: np.ndarray, *, n_states: int, train_end_idx: int, seed: int
    ) -> object | None:
        hmm_fit_calls.append((obs.shape[0], train_end_idx))
        return _real_fit_hmm(obs, n_states=n_states, train_end_idx=train_end_idx, seed=seed)

    def _spy_predict_hmm(fit: object, obs: np.ndarray) -> np.ndarray:
        hmm_predict_calls.append(obs.shape[0])
        return _real_predict_hmm(fit, obs)  # type: ignore[arg-type]

    def _spy_fit_jump(
        obs: np.ndarray, *, n_states: int, jump_penalty: float, train_end_idx: int, seed: int
    ) -> object | None:
        jump_fit_calls.append((obs.shape[0], train_end_idx))
        return _real_fit_jump(
            obs,
            n_states=n_states,
            jump_penalty=jump_penalty,
            train_end_idx=train_end_idx,
            seed=seed,
        )

    def _spy_predict_jump(fit: object, obs: np.ndarray) -> np.ndarray:
        jump_predict_calls.append(obs.shape[0])
        return _real_predict_jump(fit, obs)  # type: ignore[arg-type]

    def _spy_run_bocpd(obs: np.ndarray, *, hazard_lambda: float) -> object:
        bocpd_calls.append(obs.shape[0])
        return _real_run_bocpd(obs, hazard_lambda=hazard_lambda)

    monkeypatch.setattr(m4, "fit_hmm_gaussian", _spy_fit_hmm)
    monkeypatch.setattr(m4, "predict_hmm_gaussian", _spy_predict_hmm)
    monkeypatch.setattr(m4, "fit_jump_model", _spy_fit_jump)
    monkeypatch.setattr(m4, "predict_jump_model", _spy_predict_jump)
    monkeypatch.setattr(m4, "run_bocpd", _spy_run_bocpd)

    result = m4.compare_regime_candidates_for_symbol(
        "TESTUSDT",
        bars_df,
        baseline_df,
        initial_train_years=2,
        hmm_states_grid=(2,),
        **_CANDIDATE_KWARGS,  # type: ignore[arg-type]
    )
    assert result is not None

    open_time_ms = bars_df["open_time"].cast(pl.Int64).to_numpy()[_SHORT_WINDOW:]
    splits = vwf.generate_anchored_walk_forward_splits(open_time_ms, initial_train_years=2)
    assert len(splits) >= 1
    n_pos_trim = int(open_time_ms.shape[0])

    expected_train_end_idx = [s.train_end_idx for s in splits]
    assert [c[1] for c in hmm_fit_calls] == expected_train_end_idx
    assert [c[1] for c in jump_fit_calls] == expected_train_end_idx
    # fit_fn recebe sempre o array COMPLETO pós-trim (nunca pré-fatiado) --
    # fit_hmm_gaussian/fit_jump_model cortam obs[:train_end_idx] por conta
    # própria (contrato já provado na Fase 2).
    assert all(c[0] == n_pos_trim for c in hmm_fit_calls)
    assert all(c[0] == n_pos_trim for c in jump_fit_calls)

    fold_sizes = {s.test_end_idx - s.test_start_idx for s in splits}
    assert all(n_rows in fold_sizes for n_rows in hmm_predict_calls)
    assert all(n_rows in fold_sizes for n_rows in jump_predict_calls)
    assert all(n_rows < n_pos_trim for n_rows in hmm_predict_calls)
    assert all(n_rows < n_pos_trim for n_rows in jump_predict_calls)

    # BOCPD -- exatamente 1 chamada, sobre a série INTEIRA pós-trim (não
    # restrita à janela OOS, não repetida por fold).
    assert bocpd_calls == [n_pos_trim]


# ============================================================================
# run_regime_comparison_for_symbol -- IO real (integration/slow)
# ============================================================================

_INTEGRATION_SYMBOL = "BTCUSDT"
_INTEGRATION_START = "2020-01-01"
_INTEGRATION_END = "2021-01-08"


def _skip_if_no_backfill() -> None:
    path = CAPACITY_DIR / "dollar_bars_r1" / _INTEGRATION_SYMBOL / f"{_INTEGRATION_START}.parquet"
    if not path.exists():
        pytest.skip(f"backfill local de dollar_bars_r1/{_INTEGRATION_SYMBOL} ausente: {path}")


@pytest.mark.integration
@pytest.mark.slow
def test_run_regime_comparison_for_symbol_btcusdt_sobre_dado_real() -> None:
    """Smoke test ponta a ponta -- prova que a integração real (`lake.
    query_dollar_bars` + `build_regimes` + os 3 candidatos novos) não
    quebra, não é o run de produção completo (5 símbolos, hiperparâmetros
    calibrados). `initial_train_years=1` (não os 2 de produção) + janela
    de ~1 ano -- o MÍNIMO que produz >=1 fold de teste não-degenerado sob
    o walk-forward trimestral (o próprio 1º trimestre disponível tende a
    ter poucas barras, ver docstring de `generate_anchored_walk_forward_
    splits`/achado real medido nesta sessão)."""
    _skip_if_no_backfill()
    result = m4.run_regime_comparison_for_symbol(
        _INTEGRATION_SYMBOL,
        _INTEGRATION_START,
        _INTEGRATION_END,
        initial_train_years=1,
        hmm_states_grid=(2,),
        jump_n_states=2,
        jump_penalty=0.01,
        bocpd_hazard_lambda=200.0,
        bocpd_n_canonical_buckets=2,
    )
    assert result is not None
    assert result.symbol == _INTEGRATION_SYMBOL
    assert result.n_folds >= 1
    assert len(result.candidates) == 3  # HMM k=2 + Jump Model + BOCPD

    assert result.baseline.n_oos_obs > 0
    for c in result.candidates:
        assert c.n_oos_obs >= 0  # candidato pode ter todos os folds falhos em dado real ruidoso
