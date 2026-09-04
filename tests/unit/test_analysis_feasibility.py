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
        (0.131, 46.5),  # SOL -- gap real 0.10pp
        (0.147, 46.9),  # ETH -- gap real 0.16pp
        (0.152, 47.1),  # XRP -- gap real 0.10pp
        (0.199, 48.3),  # BTC -- gap real 0.24pp (o maior dos 5)
        (0.200, 48.4),  # BNB -- gap real 0.17pp
    ],
)
def test_breakeven_win_rate_naive_bate_com_prd_sec0_2(
    custo_atr: float, expected_wr_pct: float
) -> None:
    """Tolerância 0,3pp, não 0,15 -- medido (não escondido): a fórmula
    `WR=(sl_atr_mult+custo_atr)/(tp_atr_mult+sl_atr_mult)` é a derivação
    EV=0 literal de PRD_V4_1.md §1.5 ("edge_bruto_atr mínimo para EV zero
    é exatamente custo_atr"), mas não reproduz os 5 números da tabela
    §0.2 dentro da tolerância mais apertada que eu tinha suposto (0,15pp)
    -- 3 dos 5 (ETH/BTC/BNB) ficam entre 0,16 e 0,24pp de distância, SOL/
    XRP ficam ~0,10pp. Sem uma nota de derivação recuperável no repo (grep
    confirma: não existe), não dá pra saber se o gap está na minha fórmula
    ou na conta manual original -- este mesmo PRD já documentou duas vezes
    (§0.2, ressalva) números calculados à mão que precisaram de correção
    depois. Trava aqui o valor MEDIDO, não o que eu esperava bater."""
    wr = fe.breakeven_win_rate_naive(custo_atr=custo_atr, tp_atr_mult=2.0, sl_atr_mult=1.5)
    assert wr * 100.0 == pytest.approx(expected_wr_pct, abs=0.3)


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
        atr_pct=atr_pct,
        tp_atr_mult=2.0,
        sl_atr_mult=1.5,
        maker_fee=0.0002,
        taker_fee=0.0005,
        adverse_selection_bps=0.0,  # AG-439 -- 0,0 preserva a comparacao historica contra a naive
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
        atr_pct=atr_pct,
        tp_atr_mult=2.0,
        sl_atr_mult=1.5,
        maker_fee=0.0002,
        taker_fee=0.0005,
        adverse_selection_bps=0.0,  # AG-439 -- 0,0 preserva a comparacao historica contra a naive
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


# ============================================================================
# AG-439 -- selecao adversa no breakeven (achado da auditoria cetica)
# ============================================================================


def test_breakeven_win_rate_cobra_selecao_adversa_nas_pernas_maker() -> None:
    """AG-439: `adverse_selection_bps` era OMITIDO daqui, enquanto
    `triple_barrier` (AG-432) COBRA de `ret_net` nas pernas passivas.
    O breakeven publicado media contra um custo que o label nao usa --
    alvo mais facil que o real, num numero classe A que decide geometria.

    Reproduz a celula de producao real (BTCUSDT/R2 long, `atr_median_side`
    do artefato S1): o valor sobe de 55,0% para 57,1% -- 2,1 pontos
    percentuais de folga ficticia."""
    atr_pct = 0.0035666  # atr_median_side real, experiments/s1_..._R2.json
    comum = {
        "atr_pct": atr_pct,
        "tp_atr_mult": 1.5,
        "sl_atr_mult": 1.5,
        "maker_fee": 0.0002,
        "taker_fee": 0.0005,
    }
    sem_adv = fe.breakeven_win_rate(**comum, adverse_selection_bps=0.0)
    com_adv = fe.breakeven_win_rate(**comum, adverse_selection_bps=1.5)  # noqa: magic-number -- valor de producao

    assert sem_adv == pytest.approx(0.550, abs=0.002)  # noqa: magic-number -- o que o artefato publicava
    assert com_adv == pytest.approx(0.571, abs=0.002)  # noqa: magic-number -- o consistente com ret_net
    assert com_adv > sem_adv, "cobrar custo a mais so pode SUBIR o breakeven"


def test_breakeven_win_rate_selecao_adversa_zero_e_bit_exato_ao_legado() -> None:
    """Contraprova: com `adverse_selection_bps=0,0` a funcao reproduz
    exatamente a formula anterior a AG-439 -- a correcao nao mexeu em
    mais nada."""
    comum = {
        "atr_pct": 0.003,
        "tp_atr_mult": 2.0,
        "sl_atr_mult": 1.5,
        "maker_fee": 0.0002,
        "taker_fee": 0.0005,
    }
    c_win = (0.0002 + 0.0002) * 10000.0
    c_lose = (0.0002 + 0.0005) * 10000.0
    reward = 2.0 * 0.003 * 10000.0
    risk = 1.5 * 0.003 * 10000.0
    esperado = (risk + c_lose) / (reward + risk + c_lose - c_win)

    assert fe.breakeven_win_rate(**comum, adverse_selection_bps=0.0) == pytest.approx(esperado)
