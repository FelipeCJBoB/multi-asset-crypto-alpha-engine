"""Testes de `src/analysis/feasibility.py` -- validados contra os números
JÁ PUBLICADOS no PRD_V4_1.md (§0.2, §1.3), não só auto-consistência: se a
fórmula aqui não reproduzir o que o PRD já afirma calculado à mão, a
fórmula está errada, não o texto."""

from __future__ import annotations

import math

import polars as pl
import pytest

from src.analysis import feasibility as fe

# ============================================================================
# breakeven_win_rate_naive -- contra PRD_V4_1.md §0.2 (tp_atr_mult=2.0,
# sl_atr_mult=1.5, custo_atr da tabela original)
# ============================================================================


@pytest.mark.parametrize(
    "custo_atr,expected_wr_pct",
    [
        (0.131, 46.5),  # SOL
        (0.147, 46.9),  # ETH
        (0.152, 47.1),  # XRP
        (0.199, 48.3),  # BTC
        (0.200, 48.4),  # BNB
    ],
)
def test_breakeven_win_rate_naive_bate_com_prd_sec0_2(
    custo_atr: float, expected_wr_pct: float
) -> None:
    wr = fe.breakeven_win_rate_naive(custo_atr=custo_atr, tp_atr_mult=2.0, sl_atr_mult=1.5)
    assert wr * 100.0 == pytest.approx(expected_wr_pct, abs=0.15)  # tolerância = precisão de exibição do PRD


# ============================================================================
# edge_liq_atr / captura -- contra PRD_V4_1.md §1.3 (edge_bruto_atr=0,25 fixo)
# ============================================================================


@pytest.mark.parametrize(
    "custo_atr,expected_edge_liq,expected_captura_pct",
    [
        (0.131, 0.119, 47.5),  # SOL
        (0.147, 0.103, 41.1),  # ETH
    ],
)
def test_edge_liq_e_captura_batem_com_prd_sec1_3(
    custo_atr: float, expected_edge_liq: float, expected_captura_pct: float
) -> None:
    edge_bruto = 0.25
    edge_liq = fe.edge_liq_atr(edge_bruto=edge_bruto, custo_atr_value=custo_atr)
    assert edge_liq == pytest.approx(expected_edge_liq, abs=1e-3)
    cap = fe.captura(edge_liq=edge_liq, edge_bruto=edge_bruto)
    assert cap * 100.0 == pytest.approx(expected_captura_pct, abs=0.15)


def test_captura_edge_bruto_zero_da_nan_nao_zero_division() -> None:
    assert math.isnan(fe.captura(edge_liq=0.05, edge_bruto=0.0))


# ============================================================================
# edge_bruto_atr -- fórmula literal §1.2
# ============================================================================


def test_edge_bruto_atr_formula_literal() -> None:
    # frac_TP=0.365, frac_SL=0.513 (distribuição real citada em
    # docs/SPRINT_LOG.md, Sprint 6) com tp=2.0/sl=1.5
    edge = fe.edge_bruto_atr(frac_tp=0.365, frac_sl=0.513, tp_atr_mult=2.0, sl_atr_mult=1.5)
    assert edge == pytest.approx(0.365 * 2.0 - 0.513 * 1.5)


# ============================================================================
# breakeven_win_rate (refinada, maker/taker por desfecho) -- sanity vs naive
# ============================================================================


def test_breakeven_win_rate_refinada_proxima_da_naive_para_geometria_atual() -> None:
    """Com tp=2,0/sl=1,5 (R:R grande vs a assimetria maker/taker de 2-5bps),
    as duas formulações devem concordar dentro de ~1pp -- não são a mesma
    fórmula, mas não deveriam divergir muito nesta geometria específica."""
    atr_pct = 0.003  # 0,3%, ordem de grandeza real medida em M1 (GK)
    wr_refined = fe.breakeven_win_rate(
        atr_pct=atr_pct, tp_atr_mult=2.0, sl_atr_mult=1.5, maker_fee=0.0002, taker_fee=0.0005
    )
    custo = fe.custo_atr(atr_pct=atr_pct, maker_fee=0.0002, taker_fee=0.0005)
    wr_naive = fe.breakeven_win_rate_naive(custo_atr=custo, tp_atr_mult=2.0, sl_atr_mult=1.5)
    assert abs(wr_refined - wr_naive) < 0.01


def test_breakeven_win_rate_refinada_mais_alta_que_naive() -> None:
    """A saída em SL/TIME é sempre taker (mais cara que a saída em TP,
    maker) -- a formulação por desfecho deveria pedir uma WR um pouco
    MAIOR que a naive (que assume 50/50, mais otimista sobre o lado
    barato) para compensar que perder custa relativamente mais caro."""
    atr_pct = 0.003
    wr_refined = fe.breakeven_win_rate(
        atr_pct=atr_pct, tp_atr_mult=2.0, sl_atr_mult=1.5, maker_fee=0.0002, taker_fee=0.0005
    )
    custo = fe.custo_atr(atr_pct=atr_pct, maker_fee=0.0002, taker_fee=0.0005)
    wr_naive = fe.breakeven_win_rate_naive(custo_atr=custo, tp_atr_mult=2.0, sl_atr_mult=1.5)
    assert wr_refined > wr_naive


# ============================================================================
# trades_per_year_budget -- ordem de grandeza vs PRD_V4_1.md §0.2 (não exato,
# ver docstring da função sobre o gap de ~4,6% não reconciliado)
# ============================================================================


@pytest.mark.parametrize(
    "custo_atr,expected_trades_year",
    [
        (0.131, 862),  # SOL
        (0.199, 568),  # BTC
    ],
)
def test_trades_per_year_budget_ordem_de_grandeza_vs_prd(
    custo_atr: float, expected_trades_year: float
) -> None:
    got = fe.trades_per_year_budget(
        custo_atr=custo_atr, sl_atr_mult=1.5, fee_budget_monthly=0.03, risk_per_trade=0.005
    )
    # tolerância larga (10%) -- gap de ~4,6% documentado e não reconciliado,
    # este teste trava ORDEM DE GRANDEZA, não a cifra exata do PRD
    assert got == pytest.approx(expected_trades_year, rel=0.10)


def test_trades_per_year_budget_nao_depende_de_equity() -> None:
    """Achado da derivação: `equity` se cancela da razão -- o orçamento de
    trades depende só de geometria (sl_atr_mult) e economia (custo_atr),
    nunca do tamanho do capital. Não há parâmetro `equity` na assinatura
    por isso -- este teste documenta a ausência como intencional."""
    import inspect

    params = inspect.signature(fe.trades_per_year_budget).parameters
    assert "equity" not in params
    assert "equity_usd" not in params


# ============================================================================
# frac_tp_sl_from_labels
# ============================================================================


def test_frac_tp_sl_from_labels_conta_certo() -> None:
    labels = pl.DataFrame(
        {"barrier_hit": ["TP", "TP", "TP", "SL", "SL", "SL", "SL", "TIME", "NOFILL", "NOFILL"]}
    )
    out = fe.frac_tp_sl_from_labels(labels)
    assert out.n == 10
    assert out.frac_tp == pytest.approx(0.3)
    assert out.frac_sl == pytest.approx(0.4)
    assert out.frac_time == pytest.approx(0.1)
    assert out.frac_nofill == pytest.approx(0.2)


def test_frac_tp_sl_from_labels_vazio_da_nan_nao_zero() -> None:
    labels = pl.DataFrame(schema={"barrier_hit": pl.Utf8})
    out = fe.frac_tp_sl_from_labels(labels)
    assert out.n == 0
    assert math.isnan(out.frac_tp)
    assert math.isnan(out.frac_sl)
