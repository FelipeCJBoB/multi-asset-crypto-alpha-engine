"""Testes de `src/models/alpha.py` — ADR-004 Fase 2 (fronteira `|mu| >
lambda`, `docs/ADR-004_reformulacao_alvo_regra_decisao_e_inferencia_
2026-08-25.md` §4, `docs/prompts/execucao_adr004_fases_1_a_3_2026-08-25.md`
Passo 1). Arquivo NOVO e separado de `test_models_alpha_ag208_217.py`
(sessão paralela ativa no mesmo dia) para evitar colisão de edição."""

from __future__ import annotations

import numpy as np
import pytest

from src.models import alpha


def test_implied_mu_from_prob_p_meio_da_mu_zero() -> None:
    """`P(TP) = 0.5` é o ponto de indiferença -- mu implicado deve ser
    exatamente zero, para qualquer payoff."""
    mu = alpha.implied_mu_from_prob(np.array([0.5, 0.5]), payoff_atr_mult=1.5)
    assert mu == pytest.approx([0.0, 0.0])


def test_implied_mu_from_prob_extremos_batem_o_payoff() -> None:
    mu = alpha.implied_mu_from_prob(np.array([0.0, 1.0]), payoff_atr_mult=1.5)
    assert mu == pytest.approx([-1.5, 1.5])


def test_implied_mu_from_prob_monotona_crescente_em_p() -> None:
    p = np.linspace(0.0, 1.0, 50)  # noqa: magic-number
    mu = alpha.implied_mu_from_prob(p, payoff_atr_mult=2.0)  # noqa: magic-number
    assert np.all(np.diff(mu) > 0.0)


def test_decide_side_cost_derived_reproduz_dominancia_mutuamente_exclusiva() -> None:
    rng = np.random.default_rng(21)
    p_long, p_short = rng.random(1_000), rng.random(1_000)  # noqa: magic-number
    cost = rng.uniform(0.0, 0.3, size=1_000)  # noqa: magic-number
    side = alpha.decide_side_cost_derived(
        p_long, p_short, cost, payoff_atr_mult=1.5, lambda_b=0.1
    )
    assert set(np.unique(side).tolist()) <= {-1, 0, 1}


def test_decide_side_cost_derived_barra_de_custo_alto_nunca_sinaliza_com_p_fraco() -> None:
    """Barra com custo MAIOR que o payoff máximo possível (mu <= payoff)
    nunca pode ser sinalizada -- nem no p mais otimista (p=1, mu=payoff)."""
    p_long = np.array([1.0])
    p_short = np.array([0.0])
    cost = np.array([2.0])  # noqa: magic-number -- maior que payoff_atr_mult abaixo
    side = alpha.decide_side_cost_derived(
        p_long, p_short, cost, payoff_atr_mult=1.5, lambda_b=0.0
    )
    assert side[0] == 0


def test_decide_side_cost_derived_lambda_b_maior_que_custo_e_o_binding() -> None:
    """Quando `lambda_b > cost_atr_ratio` em toda a população, o piso de
    custo nunca morde -- resultado idêntico a usar lambda_b como limiar
    fixo (ADR-004 §4 ponto 3, 'se lambda_B > c_t, o binding e o
    orcamento')."""
    rng = np.random.default_rng(22)
    p_long, p_short = rng.random(500), rng.random(500)  # noqa: magic-number
    cost_baixo = np.zeros(500)  # noqa: magic-number
    side_com_custo_zero = alpha.decide_side_cost_derived(
        p_long, p_short, cost_baixo, payoff_atr_mult=1.5, lambda_b=0.2
    )
    mu_long = alpha.implied_mu_from_prob(p_long, payoff_atr_mult=1.5)
    mu_short = alpha.implied_mu_from_prob(p_short, payoff_atr_mult=1.5)
    is_long = (mu_long > 0.2) & (mu_long > mu_short)  # noqa: magic-number
    is_short = (mu_short > 0.2) & (mu_short > mu_long) & ~is_long  # noqa: magic-number
    expected = np.zeros(500, dtype=np.int8)  # noqa: magic-number
    expected[is_long] = 1
    expected[is_short] = -1
    assert np.array_equal(side_com_custo_zero, expected)


def test_resolve_joint_lambda_taxa_total_bate_o_orcamento() -> None:
    rng = np.random.default_rng(23)
    n = 20_000  # noqa: magic-number
    p_long, p_short = rng.random(n), rng.random(n)
    cost = rng.uniform(0.0, 0.05, size=n)  # noqa: magic-number -- custo baixo, orcamento atingivel
    target = 0.0189  # noqa: magic-number -- mesmo alvo real de target_signal_rate

    lambda_b, rate = alpha.resolve_joint_lambda(
        p_long, p_short, cost, payoff_atr_mult=1.5, target_signal_rate=target
    )
    assert rate == pytest.approx(target, abs=1e-3)


def test_resolve_joint_lambda_alvo_inatingivel_pelo_piso_de_custo_satura_no_extremo() -> None:
    """Custo uniformemente MAIOR que o payoff máximo -- nenhuma taxa >0 é
    atingível, mesmo com lambda_b=-payoff (o mais permissivo). O solver
    não deve inventar uma taxa que não existe -- deve saturar em
    lambda_b=-payoff e reportar a taxa real (zero)."""
    rng = np.random.default_rng(24)
    n = 5_000  # noqa: magic-number
    p_long, p_short = rng.random(n), rng.random(n)
    cost = np.full(n, 10.0)  # noqa: magic-number -- impossivel de superar com payoff=1.5
    lambda_b, rate = alpha.resolve_joint_lambda(
        p_long, p_short, cost, payoff_atr_mult=1.5, target_signal_rate=0.0189
    )
    assert lambda_b == pytest.approx(-1.5)
    assert rate == pytest.approx(0.0)


def test_resolve_joint_lambda_teto_de_rate_hi_e_sempre_zero() -> None:
    """`mu` nunca EXCEDE `payoff_atr_mult` (limite matemático de `2p-1`
    com `p<=1`) -- então `lambda_b=+payoff` (o extremo mais restritivo)
    tem `rate=0.0` SEMPRE, mesmo custo zero e p concentrado perto de 1.
    Documenta por que o branch 'target < rate_hi' de `resolve_joint_lambda`
    é matematicamente inatingível sob custo não-negativo (real: `E27f_
    cost_atr_ratio` nunca é negativo) -- não é código morto por engano,
    é o mesmo tipo de guarda defensiva simétrica que `resolve_joint_tau`
    também carrega no seu extremo oposto."""
    rng = np.random.default_rng(26)
    n = 5_000  # noqa: magic-number
    p_long = np.clip(rng.normal(loc=0.999, scale=0.0005, size=n), 0.0, 1.0)  # noqa: magic-number
    p_short = np.zeros(n)
    cost = np.zeros(n)
    side_at_payoff_edge = alpha.decide_side_cost_derived(
        p_long, p_short, cost, payoff_atr_mult=1.5, lambda_b=1.5
    )
    assert np.mean(side_at_payoff_edge != 0) == pytest.approx(0.0)


def test_resolve_joint_lambda_valida_shapes() -> None:
    with pytest.raises(ValueError, match="MESMA população"):
        alpha.resolve_joint_lambda(
            np.zeros(10), np.zeros(10), np.zeros(5), payoff_atr_mult=1.5, target_signal_rate=0.1
        )


def test_resolve_joint_lambda_valida_target_signal_rate() -> None:
    with pytest.raises(ValueError, match="target_signal_rate"):
        alpha.resolve_joint_lambda(
            np.zeros(10), np.zeros(10), np.zeros(10), payoff_atr_mult=1.5, target_signal_rate=1.5
        )
