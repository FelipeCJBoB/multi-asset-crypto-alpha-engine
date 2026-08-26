"""Testes do item 11 de `ADR-005 §13.17` (`§13.16.4`) -- `p̂ >
breakeven(linha)` como regra de decisão, substituindo `p̂ > tau` (limiar
global). Arquivo separado de `test_models_alpha_adr004_fase2.py` (o
mecanismo de que este item deriva) para isolar o achado novo: o GATE já
existia sem ter sido reconhecido como tal; só o teto de capacidade por
RANKING de margem é código novo.

Nenhuma das funções aqui é chamada por `run_fold` -- são núcleo puro,
opt-in, mesmo status de medição que `decide_side_cost_derived` teve antes
de virar mecanismo nomeado."""

from __future__ import annotations

import numpy as np
import pytest

from src.models import alpha


def test_breakeven_from_cost_atr_ratio_custo_zero_e_meio() -> None:
    """Sem custo, o breakeven é o ponto de indiferença -- P(TP)=0,5,
    qualquer que seja o payoff."""
    be = alpha.breakeven_from_cost_atr_ratio(np.array([0.0, 0.0]), payoff_atr_mult=1.5)  # noqa: magic-number
    assert be == pytest.approx([0.5, 0.5])


def test_breakeven_from_cost_atr_ratio_bate_a_formula_do_adr() -> None:
    """`breakeven = 0,5 + cost_atr_ratio/(2*payoff)` -- número fechado,
    calculado à mão, não só reproduzido pela própria função."""
    cost_atr_ratio = np.array([0.1, 0.3, 0.6])  # noqa: magic-number
    payoff = 1.5  # noqa: magic-number
    esperado = np.array([0.5 + c / (2 * payoff) for c in cost_atr_ratio])
    be = alpha.breakeven_from_cost_atr_ratio(cost_atr_ratio, payoff_atr_mult=payoff)
    assert be == pytest.approx(esperado)


def test_decide_side_breakeven_e_o_caso_degenerado_de_cost_derived() -> None:
    """O achado central: `decide_side_breakeven` PRECISA bater
    bit-a-bit com `decide_side_cost_derived(..., lambda_b=-payoff)`,
    porque é definido como um wrapper dessa chamada -- prova que a
    equivalência algébrica declarada na docstring não regrediu."""
    rng = np.random.default_rng(11)
    n = 2_000  # noqa: magic-number
    p_long, p_short = rng.random(n), rng.random(n)
    cost_atr_ratio = rng.uniform(0.0, 0.5, size=n)  # noqa: magic-number
    payoff = 1.5  # noqa: magic-number

    via_breakeven = alpha.decide_side_breakeven(
        p_long, p_short, cost_atr_ratio, payoff_atr_mult=payoff
    )
    via_cost_derived = alpha.decide_side_cost_derived(
        p_long, p_short, cost_atr_ratio, payoff_atr_mult=payoff, lambda_b=-payoff
    )
    assert np.array_equal(via_breakeven, via_cost_derived)


def test_decide_side_breakeven_bate_formula_fechada_independente() -> None:
    """Verificação INDEPENDENTE, não contra a função irmã: recalcula
    `p > breakeven(linha)` com dominância a partir de `breakeven_from_
    cost_atr_ratio` sozinho, sem passar por `decide_side_cost_derived`
    nem por `implied_mu_from_prob`. Se as duas famílias de fórmula
    (mu-baseada e p-baseada) divergissem por um erro de sinal ou de
    escala, só esta comparação pegaria."""
    rng = np.random.default_rng(12)
    n = 2_000  # noqa: magic-number
    p_long, p_short = rng.random(n), rng.random(n)
    cost_atr_ratio = rng.uniform(0.0, 0.5, size=n)  # noqa: magic-number
    payoff = 1.5  # noqa: magic-number

    breakeven = alpha.breakeven_from_cost_atr_ratio(cost_atr_ratio, payoff_atr_mult=payoff)
    is_long = (p_long > breakeven) & (p_long > p_short)
    is_short = (p_short > breakeven) & (p_short > p_long) & ~is_long
    esperado = np.zeros(n, dtype=np.int8)
    esperado[is_long] = 1
    esperado[is_short] = -1

    side = alpha.decide_side_breakeven(p_long, p_short, cost_atr_ratio, payoff_atr_mult=payoff)
    assert np.array_equal(side, esperado)


def test_decide_side_breakeven_p_exatamente_no_breakeven_nao_sinaliza() -> None:
    """Fronteira estrita (`>`, não `>=`) -- mesma convenção de `decide_
    side`/`decide_side_cost_derived` (`p_long > tau_long`)."""
    cost_atr_ratio = np.array([0.2])  # noqa: magic-number
    payoff = 1.5  # noqa: magic-number
    breakeven = alpha.breakeven_from_cost_atr_ratio(cost_atr_ratio, payoff_atr_mult=payoff)
    side = alpha.decide_side_breakeven(
        breakeven, np.array([0.0]), cost_atr_ratio, payoff_atr_mult=payoff
    )
    assert side[0] == 0


def test_select_top_q_by_margin_mantem_exatamente_top_k() -> None:
    margin = np.array([0.5, 0.3, 0.1, -0.2, 0.4, -1.0, 0.05])  # noqa: magic-number
    keep = alpha.select_top_q_by_margin(margin, q=3 / 7)  # top 3
    assert int(keep.sum()) == 3
    assert set(np.where(keep)[0].tolist()) == {0, 1, 4}  # os 3 maiores: 0.5, 0.4, 0.3


def test_select_top_q_by_margin_nunca_inclui_margem_nao_positiva() -> None:
    """`q` generoso o bastante para cobrir a população inteira ainda
    assim não seleciona linha com margem <= 0 -- inclusive `-inf`
    (inadmissível por construção)."""
    margin = np.array([0.1, -0.1, 0.0, -np.inf])  # noqa: magic-number
    keep = alpha.select_top_q_by_margin(margin, q=1.0)
    assert keep.tolist() == [True, False, False, False]


def test_select_top_q_by_margin_q_fora_do_intervalo_levanta() -> None:
    with pytest.raises(ValueError):
        alpha.select_top_q_by_margin(np.array([0.1]), q=0.0)  # noqa: magic-number
    with pytest.raises(ValueError):
        alpha.select_top_q_by_margin(np.array([0.1]), q=1.5)  # noqa: magic-number


def test_select_top_q_by_margin_populacao_vazia() -> None:
    keep = alpha.select_top_q_by_margin(np.array([]), q=0.5)
    assert keep.shape == (0,)


def test_decide_side_breakeven_topq_e_subconjunto_do_gate_puro() -> None:
    """O teto de capacidade só REMOVE sinal do gate absoluto, nunca
    adiciona: toda linha marcada por `decide_side_breakeven_topq` também
    é marcada (mesmo lado) por `decide_side_breakeven`."""
    rng = np.random.default_rng(13)
    n = 5_000  # noqa: magic-number
    p_long, p_short = rng.random(n), rng.random(n)
    cost_atr_ratio = rng.uniform(0.0, 0.5, size=n)  # noqa: magic-number
    payoff = 1.5  # noqa: magic-number
    target_rate = 0.05  # noqa: magic-number

    gate_puro = alpha.decide_side_breakeven(
        p_long, p_short, cost_atr_ratio, payoff_atr_mult=payoff
    )
    com_topq = alpha.decide_side_breakeven_topq(
        p_long,
        p_short,
        cost_atr_ratio,
        payoff_atr_mult=payoff,
        target_signal_rate=target_rate,
    )
    sinalizado = com_topq != 0
    assert np.array_equal(com_topq[sinalizado], gate_puro[sinalizado])
    assert np.mean(com_topq != 0) <= np.mean(gate_puro != 0) + 1e-9  # noqa: magic-number


def test_decide_side_breakeven_topq_taxa_realizada_bate_o_alvo_quando_ha_oferta() -> None:
    """Quando o gate admite mais linhas do que o orçamento pede, o top-q
    realiza a taxa alvo (dentro de 1 linha de arredondamento)."""
    rng = np.random.default_rng(14)
    n = 10_000  # noqa: magic-number
    # custo baixo o bastante para que a maioria das linhas passe o gate.
    p_long, p_short = rng.random(n), rng.random(n)
    cost_atr_ratio = rng.uniform(0.0, 0.05, size=n)  # noqa: magic-number
    payoff = 1.5  # noqa: magic-number
    target_rate = 0.1  # noqa: magic-number

    side = alpha.decide_side_breakeven_topq(
        p_long,
        p_short,
        cost_atr_ratio,
        payoff_atr_mult=payoff,
        target_signal_rate=target_rate,
    )
    taxa = float(np.mean(side != 0))
    assert taxa == pytest.approx(target_rate, abs=2 / n)


def test_decide_side_breakeven_topq_diverge_de_lambda_threshold_quando_custo_varia() -> None:
    """A diferença que a docstring do bloco declara: `resolve_joint_
    lambda`/`decide_side_cost_derived` aplicam um limiar ESCALAR sobre
    `mu`; `decide_side_breakeven_topq` rankeia por MARGEM
    (`mu - cost_atr_ratio`). Construído para que os dois DIVIRJAM: duas
    linhas de `mu` idêntico e custo bem diferente -- o limiar em mu as
    trata igual, o ranking por margem não."""
    payoff = 1.5  # noqa: magic-number
    # 4 linhas, mu implícito idêntico (mesmo p_long), custo bem diferente.
    # margem = mu - custo: a de custo baixo tem margem MAIOR.
    p_long = np.array([0.70, 0.70, 0.70, 0.70])  # noqa: magic-number
    p_short = np.zeros(4)
    cost_atr_ratio = np.array([0.05, 0.55, 0.05, 0.55])  # noqa: magic-number
    mu = alpha.implied_mu_from_prob(p_long, payoff_atr_mult=payoff)
    assert np.all(mu > cost_atr_ratio)  # todas passam o gate de breakeven

    # top-q pedindo metade (2 de 4): por MARGEM, deve reter as 2 de custo
    # BAIXO (índices 0 e 2), não uma de cada.
    side_topq = alpha.decide_side_breakeven_topq(
        p_long, p_short, cost_atr_ratio, payoff_atr_mult=payoff, target_signal_rate=0.5
    )
    assert (side_topq != 0).tolist() == [True, False, True, False]

    # o mecanismo de limiar-em-mu (resolve_joint_lambda) não consegue
    # distinguir as 4 linhas por margem -- mu é idêntico nas 4, então
    # QUALQUER lambda_b ou seleciona as 4 ou nenhuma (nunca 2 de 4 por
    # margem). Confirma a divergência estrutural, não só o resultado
    # numérico do bloco acima.
    lambda_b, taxa = alpha.resolve_joint_lambda(
        p_long, p_short, cost_atr_ratio, payoff_atr_mult=payoff, target_signal_rate=0.5
    )
    side_lambda = alpha.decide_side_cost_derived(
        p_long, p_short, cost_atr_ratio, payoff_atr_mult=payoff, lambda_b=lambda_b
    )
    assert int(np.sum(side_lambda != 0)) in (0, 4)
    assert (side_lambda != 0).tolist() != (side_topq != 0).tolist()
