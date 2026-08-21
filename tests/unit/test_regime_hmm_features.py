"""Testes de `src/regime/hmm_features.py` -- porta bit-exata dos testes de
`_input_obs`/`_valid_start_idx` que já existiam em `src.analysis.
m4_regime_comparison` antes da extração (Fase B do plano
`wise-exploring-panda.md`, 2026-08-21). Mesmos casos de valor conhecido à
mão, chamando `input_obs`/`valid_start_idx` diretamente (não via `m4.
_input_obs`, que continua existindo como re-export -- ver `tests/unit/
test_analysis_m4_regime_comparison.py`, não duplicado aqui)."""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from src.features import support as features_support
from src.features._constants import load_constant as load_feature_constant
from src.regime import hmm_features

_SHORT_WINDOW = int(load_feature_constant("feature_c06_vol_ratio_short_window"))


def test_input_obs_log_return_1_valores_conhecidos() -> None:
    close = np.array([100.0, 101.0, 99.0, 102.0, 100.0], dtype=np.float64)
    bars_df = pl.DataFrame(
        {"open_time": np.arange(5, dtype=np.int64) * 86_400_000, "close": close}
    )
    log_return_1, obs_2d = hmm_features.input_obs(bars_df)

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

    log_return_1, obs_2d = hmm_features.input_obs(bars_df)

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

    log_return_1, obs_2d = hmm_features.input_obs(bars_df)
    idx = hmm_features.valid_start_idx(log_return_1, obs_2d[:, 1])
    assert idx == _SHORT_WINDOW


def test_valid_start_idx_levanta_value_error_serie_curta_demais() -> None:
    log_return_1 = np.full(3, np.nan, dtype=np.float64)
    realized_vol_short = np.full(3, np.nan, dtype=np.float64)
    with pytest.raises(ValueError, match="curta demais"):
        hmm_features.valid_start_idx(log_return_1, realized_vol_short)
