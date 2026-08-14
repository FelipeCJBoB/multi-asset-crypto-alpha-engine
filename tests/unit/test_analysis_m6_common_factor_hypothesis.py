"""Testes de `src/analysis/m6_common_factor_hypothesis.py` — núcleo puro
(`_edge_bruto_se`, `stratum_metrics`, `cochrans_q_heterogeneity`), sem IO
real (`compute_metrics_for_symbol`/`run_and_save_m6_report` fazem IO real
via `dataset.build_modeling_frame`, não exercitados aqui — mesma
convenção de `test_models_dataset.py` sobre `build_modeling_frame`)."""

from __future__ import annotations

import math

import polars as pl
import pytest

from src.analysis.m6_common_factor_hypothesis import (
    StratumMetrics,
    _edge_bruto_se,
    cochrans_q_heterogeneity,
    stratum_metrics,
)


def test_edge_bruto_se_bate_com_formula_de_variancia_multinomial() -> None:
    """`Var(edge) = tp_mult²·Var(frac_TP) + sl_mult²·Var(frac_SL) -
    2·tp_mult·sl_mult·Cov(frac_TP,frac_SL)`, com `Var(frac_i)=p_i(1-p_i)/n`
    e `Cov(frac_TP,frac_SL)=-frac_TP·frac_SL/n` (propriedade padrão da
    distribuição multinomial) — recomputado aqui de forma independente
    (não chamando `_edge_bruto_se`) pra provar a função, não repetir a
    mesma fórmula duas vezes sem checagem cruzada."""
    frac_tp, frac_sl, n = 0.3, 0.2, 1000
    tp_mult, sl_mult = 2.0, 1.5

    var_tp = frac_tp * (1 - frac_tp) / n
    var_sl = frac_sl * (1 - frac_sl) / n
    cov = -frac_tp * frac_sl / n
    expected_var = tp_mult**2 * var_tp + sl_mult**2 * var_sl - 2 * tp_mult * sl_mult * cov
    expected_se = math.sqrt(expected_var)

    se = _edge_bruto_se(frac_tp, frac_sl, n, tp_mult=tp_mult, sl_mult=sl_mult)
    assert se == pytest.approx(expected_se, rel=1e-9)


def test_edge_bruto_se_n_zero_devolve_nan() -> None:
    assert math.isnan(_edge_bruto_se(0.3, 0.2, 0, tp_mult=2.0, sl_mult=1.5))


def _labels_with_barrier_hits(hits: list[str], atr: float = 0.01) -> pl.DataFrame:
    return pl.DataFrame({"barrier_hit": hits, "atr_at_t0": [atr] * len(hits)})


def test_stratum_metrics_bate_com_algebra_manual_do_prd() -> None:
    """§1.2: `edge_bruto_atr = frac_TP·tp_mult - frac_SL·sl_mult`,
    `edge_liq_atr = edge_bruto_atr - custo_atr`, `captura = edge_liq_atr /
    edge_bruto_atr` — 10 trades com contagem conhecida (4 TP, 3 SL, 2 TIME,
    1 NOFILL), `atr_at_t0` constante (mediana trivial) pra isolar a
    aritmética de `custo_atr` de qualquer efeito de distribuição."""
    labels = _labels_with_barrier_hits(["TP"] * 4 + ["SL"] * 3 + ["TIME"] * 2 + ["NOFILL"] * 1)
    tp_mult, sl_mult = 2.0, 1.5
    maker_fee, taker_fee = 0.0002, 0.0005

    metrics = stratum_metrics(
        labels, symbol="BTCUSDT", side=1, regime=None,
        tp_atr_mult=tp_mult, sl_atr_mult=sl_mult, maker_fee=maker_fee, taker_fee=taker_fee,
    )

    assert metrics.n == 10
    assert metrics.frac_tp == pytest.approx(0.4)
    assert metrics.frac_sl == pytest.approx(0.3)
    expected_edge_bruto = 0.4 * tp_mult - 0.3 * sl_mult
    assert metrics.edge_bruto_atr == pytest.approx(expected_edge_bruto)
    assert metrics.edge_liq_atr == pytest.approx(expected_edge_bruto - metrics.custo_atr)
    assert metrics.captura == pytest.approx(metrics.edge_liq_atr / metrics.edge_bruto_atr)


def test_stratum_metrics_n_zero_propaga_nan_sem_levantar() -> None:
    labels = _labels_with_barrier_hits([])
    metrics = stratum_metrics(
        labels, symbol="BTCUSDT", side=1, regime=None,
        tp_atr_mult=2.0, sl_atr_mult=1.5, maker_fee=0.0002, taker_fee=0.0005,
    )
    assert metrics.n == 0
    assert math.isnan(metrics.custo_atr)
    assert math.isnan(metrics.edge_bruto_atr_se)


def _stratum(symbol: str, edge: float, se: float, *, side: int = 1) -> StratumMetrics:
    return StratumMetrics(
        symbol=symbol, side=side, regime=None, n=100_000,
        frac_tp=0.4, frac_sl=0.3, frac_time=0.2, frac_nofill=0.1,
        edge_bruto_atr=edge, edge_bruto_atr_se=se,
        custo_atr=0.1, edge_liq_atr=edge - 0.1,
        captura=(edge - 0.1) / edge if edge else float("nan"),
    )


def test_cochrans_q_valores_identicos_da_q_zero_i2_zero_p_value_um() -> None:
    """Todos os símbolos com o MESMO `edge_bruto_atr` verdadeiro (SEs
    diferentes, não importa) -- heterogeneidade zero por construção:
    `Q=0` exato (cada desvio ao quadrado é zero), `I²=0%`, `p_value=1,0`
    exato (`chi2.sf(0, df)=1` sempre, pra qualquer df>=1 -- P(X<=0)=0 numa
    distribuição chi² contínua, então P(X>0)=1)."""
    strata = (
        _stratum("BTCUSDT", 0.5, 0.01),
        _stratum("ETHUSDT", 0.5, 0.02),
        _stratum("SOLUSDT", 0.5, 0.03),
    )
    het = cochrans_q_heterogeneity(strata)
    assert het.pooled_edge_bruto_atr == pytest.approx(0.5)
    assert het.q_statistic == pytest.approx(0.0, abs=1e-12)
    assert het.i_squared_pct == pytest.approx(0.0)
    assert het.p_value == pytest.approx(1.0)


def test_cochrans_q_dois_simbolos_bate_com_valor_conhecido_da_chi2() -> None:
    """k=2, valores [0,6; 0,4], SE=0,1 nos dois -- pesos iguais (100 cada),
    `pooled=0,5` exato, `Q=100·0,01+100·0,01=2,0` exato, `df=1`,
    `I²=max(0,(2-1)/2)·100=50%` exato. `p_value=chi2.sf(2,1)≈0,1573` --
    valor de referência bem estabelecido (chi²(1) é o quadrado de uma
    normal padrão: `P(X>2)=P(|Z|>√2)=2·(1-Φ(√2))≈0,15730`), não um número
    de scipy tomado de caixa-preta."""
    strata = (_stratum("BTCUSDT", 0.6, 0.1), _stratum("ETHUSDT", 0.4, 0.1))
    het = cochrans_q_heterogeneity(strata)

    assert het.pooled_edge_bruto_atr == pytest.approx(0.5)
    assert het.q_statistic == pytest.approx(2.0)
    assert het.df == 1
    assert het.i_squared_pct == pytest.approx(50.0)
    assert het.p_value == pytest.approx(0.15730, abs=1e-4)


def test_cochrans_q_side_misturado_levanta_erro() -> None:
    strata = (_stratum("BTCUSDT", 0.5, 0.1, side=1), _stratum("ETHUSDT", 0.5, 0.1, side=-1))
    with pytest.raises(ValueError, match="mesmo side"):
        cochrans_q_heterogeneity(strata)


def test_cochrans_q_se_invalido_devolve_nan_sem_levantar() -> None:
    strata = (_stratum("BTCUSDT", 0.5, 0.0), _stratum("ETHUSDT", 0.5, 0.1))
    het = cochrans_q_heterogeneity(strata)
    assert math.isnan(het.pooled_edge_bruto_atr)
    assert math.isnan(het.q_statistic)
    assert math.isnan(het.p_value)
