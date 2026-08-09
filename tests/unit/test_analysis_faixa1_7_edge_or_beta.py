"""Testes de `src/analysis/faixa1_7_edge_or_beta.py` — foco na PLUMBING
nova e mais arriscada desta rodada: sinal de tendência de 48 barras
(causal, off-by-one), o join com componentes de PnL (carry/direcional)
que faltavam em `faixa1_6_reconciliation._build_oof_population`, a
marcação de regime-de-origem do retorno bar-a-bar (B2-like), e a
matemática de residualização (OLS de 1 variável). Não retesta
`decompose`/`_spearman_ic`/`build_side_population` — já testados em seus
próprios módulos."""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from src.analysis import faixa1_7_edge_or_beta as f17

_T0_DTYPE = pl.Datetime(time_unit="ms", time_zone="UTC")


# ============================================================================
# _trend_direction_48b — causal, off-by-one, warmup
# ============================================================================


def _fake_mf_for_trend(prices: list[float]) -> pl.DataFrame:
    rows = []
    for i, px in enumerate(prices):
        for side in (1, -1):
            rows.append({"t0": i, "side": side, "entry_price_limit": px})
    return pl.DataFrame(rows).with_columns(pl.col("t0").cast(pl.Int64).cast(_T0_DTYPE))


def test_trend_direction_48b_sobe_da_sinal_positivo() -> None:
    # 60 pontos, subindo monotonicamente -> retorno de 48 barras > 0 a partir do indice 48
    prices = [100.0 + i for i in range(60)]
    mf = _fake_mf_for_trend(prices)
    out = f17._trend_direction_48b(mf)
    assert out.height == 60
    signs = out.sort("t0")["trend_sign_48b"].to_list()
    assert signs[:48] == [0] * 48  # warmup local -- sem 48 barras de historico ainda
    assert all(s == 1 for s in signs[48:])


def test_trend_direction_48b_desce_da_sinal_negativo() -> None:
    prices = [200.0 - i for i in range(60)]
    mf = _fake_mf_for_trend(prices)
    out = f17._trend_direction_48b(mf)
    signs = out.sort("t0")["trend_sign_48b"].to_list()
    assert all(s == -1 for s in signs[48:])


def test_trend_direction_48b_e_causal_nao_usa_futuro() -> None:
    """Sobe até o meio, desce depois -- o sinal em t=50 (janela [2,50])
    tem que refletir só o passado até t=50, não o formato completo da
    série (que desce no fim)."""
    up = [100.0 + i for i in range(50)]
    down = [149.0 - i for i in range(10)]
    prices = up + down
    mf = _fake_mf_for_trend(prices)
    out = f17._trend_direction_48b(mf)
    signs = out.sort("t0")["trend_sign_48b"].to_list()
    # em t=50, janela [2,50] ainda inteiramente na perna de subida -> positivo
    assert signs[50] == 1


# ============================================================================
# _build_oof_population_with_pnl_components — join carrega ret_gross/
# funding_bps que faltavam no helper reusado de faixa1_6
# ============================================================================


def _fake_predictions() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "t0": [1, 2, 3],
            "fold_id": [0, 0, 0],
            "side_hat": [1, -1, 0],
            "is_oof": [True, True, True],
        }
    ).with_columns(pl.col("t0").cast(pl.Int64).cast(_T0_DTYPE))


def _fake_mf_with_pnl() -> pl.DataFrame:
    rows = []
    for t0 in (1, 2, 3):
        for side in (1, -1):
            rows.append(
                {
                    "t0": t0,
                    "side": side,
                    "barrier_hit": "TP",
                    "ret_net": 0.01,
                    "ret_gross": 0.012,
                    "funding_bps": 0.5,
                    f17._E02F_FEATURE: 0.2,
                }
            )
    return pl.DataFrame(rows).with_columns(pl.col("t0").cast(pl.Int64).cast(_T0_DTYPE))


def test_build_oof_population_with_pnl_components_traz_ret_gross_e_funding() -> None:
    out = f17._build_oof_population_with_pnl_components(
        _fake_predictions(), _fake_mf_with_pnl(), side_filter=1
    )
    assert set(out.columns) >= {"ret_gross", "funding_bps", f17._E02F_FEATURE}
    assert out.height == 1  # só t0=1, side_hat=1
    assert out["side_hat"].to_list() == [1]


def test_build_oof_population_with_pnl_components_filtra_side_hat_zero() -> None:
    out = f17._build_oof_population_with_pnl_components(
        _fake_predictions(), _fake_mf_with_pnl(), side_filter=1
    )
    # t0=3 tem side_hat=0 -- nunca deveria aparecer em nenhum side_filter
    assert 3 not in out["t0"].dt.epoch(time_unit="ms").to_list()


# ============================================================================
# b2_continuous_exposure_by_regime — regime de ORIGEM do retorno (t-1),
# não do destino (t) -- off-by-one deliberado, causal.
# ============================================================================


def test_b2_continuous_exposure_marca_regime_de_origem_nao_destino() -> None:
    # 3 barras: R1 -> R1 -> R3. Preço sobe em cada passo.
    # 2 retornos: (t0->t1, origem R1) e (t1->t2, origem R1) -- regime R3
    # (só na barra destino) não deveria receber nenhum retorno.
    rows = []
    for t0, px, regime in ((0, 100.0, "R1"), (1, 101.0, "R1"), (2, 102.0, "R3")):
        rows.append({"t0": t0, "side": 1, "entry_price_limit": px, "regime": regime})
    mf = pl.DataFrame(rows).with_columns(pl.col("t0").cast(pl.Int64).cast(_T0_DTYPE))
    out = f17.b2_continuous_exposure_by_regime(mf)
    assert out["R1"]["n_bars"] == 2
    assert out["R3"]["n_bars"] == 0


def test_b2_continuous_exposure_retorno_positivo_da_sharpe_positivo() -> None:
    rows = []
    for t0, px in enumerate([100.0 * (1.001**i) for i in range(20)]):
        rows.append({"t0": t0, "side": 1, "entry_price_limit": px, "regime": "R1"})
    mf = pl.DataFrame(rows).with_columns(pl.col("t0").cast(pl.Int64).cast(_T0_DTYPE))
    out = f17.b2_continuous_exposure_by_regime(mf)
    assert out["R1"]["n_bars"] == 19
    assert out["R1"]["sharpe_naive"] > 0


# ============================================================================
# Residualização (dentro de orthogonalize_confidence_vs_vol) — testada via
# a matemática isolada, não a função inteira (que exige predictions/mf.data
# reais com build_side_population) -- prova que a regressão OLS de 1
# variável remove EXATAMENTE a componente linear conhecida.
# ============================================================================


def test_residualizacao_ols_remove_componente_linear_conhecida() -> None:
    rng = np.random.default_rng(0)
    vol = rng.normal(size=500)
    ruido = rng.normal(scale=0.01, size=500)
    beta_verdadeiro = 0.7
    conf = 0.5 + beta_verdadeiro * vol + ruido  # conf = intercepto + beta*vol + ruido

    vol_c = vol - vol.mean()
    beta_estimado = float(np.dot(vol_c, conf - conf.mean()) / np.dot(vol_c, vol_c))
    conf_resid = conf - beta_estimado * vol_c - conf.mean()

    assert beta_estimado == pytest.approx(beta_verdadeiro, abs=0.05)
    # resíduo não deve mais correlacionar com vol (componente linear removida)
    rho_resid_vol = float(np.corrcoef(conf_resid, vol)[0, 1])
    assert abs(rho_resid_vol) < 0.05


# ============================================================================
# nofill_x_cost_tercile_within_r2 -- amostra insuficiente não quebra
# ============================================================================


def test_nofill_x_cost_tercile_amostra_insuficiente_nao_quebra() -> None:
    mf = pl.DataFrame(
        {
            "t0": [1, 2],
            "side": [1, 1],
            "regime": ["R2", "R2"],
            "barrier_hit": ["TP", "NOFILL"],
            "E27f_cost_atr_ratio": [0.1, None],
        }
    ).with_columns(pl.col("t0").cast(pl.Int64).cast(_T0_DTYPE))
    out = f17.nofill_x_cost_tercile_within_r2(mf)
    assert out == {"aplicavel": False}
