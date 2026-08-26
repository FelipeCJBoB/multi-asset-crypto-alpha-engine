"""Testes do gate de produção (`src.analysis.production_grade_gate`).

Cobrem o NÚCLEO PURO (`stop_max_pct`, `cost_usd_per_trade`,
`capacity_trades_per_month`, `inverse_mills_ratio`, `rho_minimo`,
`build_grade_gate_row`) -- nenhum toca disco. A casca
(`run_production_grade_gate_report`) lê relatórios S1 reais e barras reais
via `data.lake` -- fora do escopo deste arquivo (precisaria de
`integration`/skip-if-ausente, não escrito aqui)."""

from __future__ import annotations

import math

import pytest

from src.analysis import production_grade_gate as pgg

# ============================================================================
# stop_max_pct / r1_ceiling_violated
# ============================================================================


def test_stop_max_pct_bate_com_a_formula_fechada() -> None:
    esperado = (196.85 * 0.005) / (2.0 * 0.001 * 76_558.70)
    assert pgg.stop_max_pct(
        equity=196.85, risk_per_trade=0.005, step_size=0.001, price=76_558.70
    ) == pytest.approx(esperado)


def test_stop_max_pct_btc_reproduz_a_ordem_de_grandeza_do_adr_005() -> None:
    """§12.2: teto de BTC ~0,643% ao preço de US$ 76.558,70 -- não bit-exato
    (o ADR arredonda na tabela), só a ordem de grandeza que sustenta a
    decisão de excluir BTCUSDT/R3."""
    smax = pgg.stop_max_pct(equity=196.85, risk_per_trade=0.005, step_size=0.001, price=76_558.70)
    assert smax == pytest.approx(0.00643, rel=0.02)


def test_stop_max_pct_levanta_com_unit_notional_nao_positivo() -> None:
    with pytest.raises(pgg.ProductionGradeGateError, match="unit_notional"):
        pgg.stop_max_pct(equity=196.85, risk_per_trade=0.005, step_size=0.0, price=100.0)


def test_r1_ceiling_violated_true_quando_stop_pct_excede_o_teto() -> None:
    assert pgg.r1_ceiling_violated(stop_pct=0.00767, stop_max=0.00643) is True


def test_r1_ceiling_violated_false_quando_stop_pct_esta_dentro_do_teto() -> None:
    assert pgg.r1_ceiling_violated(stop_pct=0.00922, stop_max=0.1778) is False


def test_r1_ceiling_violated_e_estrito_na_fronteira() -> None:
    """Igual ao teto não viola -- a restrição é `>`, não `>=` (§0.2 R1 exige
    N_req/unit >= 2, que é exatamente o ponto de igualdade)."""
    assert pgg.r1_ceiling_violated(stop_pct=0.005, stop_max=0.005) is False


# ============================================================================
# cost_usd_per_trade -- §12.1/§12.7: custo é função de stop_pct, não fixo
# ============================================================================


def test_cost_usd_per_trade_bate_com_a_formula_fechada() -> None:
    equity, risk, stop_pct, cost_bps = 196.85, 0.005, 0.005, 5.5173
    notional = equity * risk / stop_pct
    esperado = notional * (cost_bps / 10_000.0)
    assert pgg.cost_usd_per_trade(
        equity=equity, risk_per_trade=risk, stop_pct=stop_pct, cost_bps=cost_bps
    ) == pytest.approx(esperado)


def test_cost_usd_per_trade_cai_quando_stop_pct_sobe() -> None:
    """O erro-v1 corrigido em §12.7: stop maior => nocional menor => MENOS
    fee por trade, não o mesmo custo em toda grade."""
    c_r1 = pgg.cost_usd_per_trade(
        equity=196.85, risk_per_trade=0.005, stop_pct=0.0037, cost_bps=5.5
    )
    c_r3 = pgg.cost_usd_per_trade(
        equity=196.85, risk_per_trade=0.005, stop_pct=0.0092, cost_bps=5.5
    )
    assert c_r3 < c_r1


def test_cost_usd_per_trade_levanta_com_stop_pct_nao_positivo() -> None:
    with pytest.raises(pgg.ProductionGradeGateError, match="stop_pct"):
        pgg.cost_usd_per_trade(equity=196.85, risk_per_trade=0.005, stop_pct=0.0, cost_bps=5.5173)


# ============================================================================
# capacity_trades_per_month -- §12.4: orçamento COMPARTILHADO, não x5
# ============================================================================


def test_capacity_trades_per_month_bate_com_a_formula_fechada() -> None:
    fee_budget, equity, cost = 0.03, 196.85, 0.1230
    esperado = (fee_budget * equity) / cost
    assert pgg.capacity_trades_per_month(
        fee_budget_monthly=fee_budget, equity=equity, cost_per_trade_usd=cost
    ) == pytest.approx(esperado)


def test_capacity_trades_per_month_sobe_quando_custo_por_trade_cai() -> None:
    cap_r1 = pgg.capacity_trades_per_month(
        fee_budget_monthly=0.03, equity=196.85, cost_per_trade_usd=0.123
    )
    cap_r3 = pgg.capacity_trades_per_month(
        fee_budget_monthly=0.03, equity=196.85, cost_per_trade_usd=0.057
    )
    assert cap_r3 > cap_r1


def test_capacity_trades_per_month_levanta_com_custo_nao_positivo() -> None:
    with pytest.raises(pgg.ProductionGradeGateError, match="cost_per_trade_usd"):
        pgg.capacity_trades_per_month(
            fee_budget_monthly=0.03, equity=196.85, cost_per_trade_usd=0.0
        )


# ============================================================================
# inverse_mills_ratio / rho_minimo
# ============================================================================


def test_inverse_mills_ratio_decresce_conforme_q_sobe() -> None:
    """Selecionar uma fração maior da população reduz o retorno esperado
    (em desvios) do topo selecionado -- lambda(q) é decrescente em q."""
    lam_apertado = pgg.inverse_mills_ratio(0.01)
    lam_frouxo = pgg.inverse_mills_ratio(0.10)
    assert lam_apertado > lam_frouxo > 0.0


def test_inverse_mills_ratio_levanta_fora_de_0_1() -> None:
    with pytest.raises(pgg.ProductionGradeGateError, match="fração de seleção"):
        pgg.inverse_mills_ratio(0.0)
    with pytest.raises(pgg.ProductionGradeGateError, match="fração de seleção"):
        pgg.inverse_mills_ratio(1.0)


def test_rho_minimo_bate_com_a_formula_fechada() -> None:
    mu, sigma, q = -0.00065, 0.0060, 0.00333
    lam = pgg.inverse_mills_ratio(q)
    esperado = -mu / (sigma * lam)
    assert pgg.rho_minimo(mu=mu, sigma=sigma, q=q) == pytest.approx(esperado)


def test_rho_minimo_menor_em_r3_do_que_em_r1_mesmo_mu() -> None:
    """§12.5 -- núcleo do argumento de §12: com `mu` comum entre grades, o
    `sigma` maior de R3 exige MENOS `rho` para o mesmo cruzamento de zero."""
    mu = -0.00065
    rho_r1 = pgg.rho_minimo(mu=mu, sigma=0.00607, q=0.00333)
    rho_r3 = pgg.rho_minimo(mu=mu, sigma=0.01202, q=0.03596)
    assert 0.0 < rho_r3 < rho_r1


def test_rho_minimo_levanta_com_sigma_nao_positivo() -> None:
    with pytest.raises(pgg.ProductionGradeGateError, match="sigma"):
        pgg.rho_minimo(mu=-0.0006, sigma=0.0, q=0.01)


# ============================================================================
# build_grade_gate_row -- composição, ainda núcleo puro
# ============================================================================


def _base_kwargs() -> dict[str, float]:
    return {
        "equity": 196.85,
        "risk_per_trade": 0.005,
        "fee_budget_monthly": 0.03,
        "cost_bps": 5.5173,
    }


def test_build_grade_gate_row_marca_excluida_teto_r1_quando_viola() -> None:
    row = pgg.build_grade_gate_row(
        symbol="BTCUSDT",
        resolution_id="R3",
        step_size=0.001,
        price_mediano=76_558.70,
        stop_pct_producao=0.00767,
        demanda_trades_mes_medida=10.0,
        **_base_kwargs(),
    )
    assert row.r1_teto_violado is True
    assert row.veredito == "excluida_teto_r1"


def test_build_grade_gate_row_marca_cabe_quando_demanda_abaixo_da_capacidade() -> None:
    row = pgg.build_grade_gate_row(
        symbol="ETHUSDT",
        resolution_id="R3",
        step_size=0.001,
        price_mediano=2_768.28,
        stop_pct_producao=0.00922,
        demanda_trades_mes_medida=1.0,
        **_base_kwargs(),
    )
    assert row.r1_teto_violado is False
    assert row.veredito == "cabe"


def test_build_grade_gate_row_marca_estoura_orcamento_quando_demanda_excede() -> None:
    row = pgg.build_grade_gate_row(
        symbol="BTCUSDT",
        resolution_id="R1",
        step_size=0.001,
        price_mediano=76_558.70,
        stop_pct_producao=0.0037,
        demanda_trades_mes_medida=1_000_000.0,
        **_base_kwargs(),
    )
    assert row.r1_teto_violado is False
    assert row.veredito == "estoura_orcamento"


def test_build_grade_gate_row_marca_sem_demanda_medida_quando_none() -> None:
    row = pgg.build_grade_gate_row(
        symbol="ETHUSDT",
        resolution_id="R3",
        step_size=0.001,
        price_mediano=2_768.28,
        stop_pct_producao=0.00922,
        demanda_trades_mes_medida=None,
        **_base_kwargs(),
    )
    assert row.veredito == "sem_demanda_medida"


def test_build_grade_gate_row_teto_r1_vence_mesmo_com_demanda_baixa() -> None:
    """Violar o teto R1 exclui a célula independente de capacidade/demanda
    -- não é uma questão de orçamento, é quantização inválida (§0.2 R1)."""
    row = pgg.build_grade_gate_row(
        symbol="BTCUSDT",
        resolution_id="R3",
        step_size=0.001,
        price_mediano=76_558.70,
        stop_pct_producao=0.00767,
        demanda_trades_mes_medida=0.001,
        **_base_kwargs(),
    )
    assert row.veredito == "excluida_teto_r1"


def test_build_grade_gate_row_unit_notional_e_step_size_vezes_preco() -> None:
    row = pgg.build_grade_gate_row(
        symbol="XRPUSDT",
        resolution_id="R2",
        step_size=0.1,
        price_mediano=1.41,
        stop_pct_producao=0.006,
        demanda_trades_mes_medida=None,
        **_base_kwargs(),
    )
    assert row.unit_notional == pytest.approx(0.1 * 1.41)


def test_build_grade_gate_row_nao_levanta_para_grade_bem_formada() -> None:
    """Smoke: nenhuma exceção para um input plausível -- serve de guarda
    contra regressão de assinatura ao mexer nas funções puras acima."""
    row = pgg.build_grade_gate_row(
        symbol="SOLUSDT",
        resolution_id="R1",
        step_size=0.01,
        price_mediano=145.92,
        stop_pct_producao=0.004,
        demanda_trades_mes_medida=5.0,
        **_base_kwargs(),
    )
    assert math.isfinite(row.cost_usd_por_trade)
    assert math.isfinite(row.capacidade_trades_mes)
