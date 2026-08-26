"""Testes do eixo 1 corrigido (`src.analysis.feature_promotion_criterion`).

Cobrem o NÚCLEO PURO (`two_sided_p_from_t`, `benjamini_hochberg`,
`symbol_is_majority_discovery`, `expected_count_at_least_k`,
`build_symbol_counts`, `empirical_p_symbol`) -- nenhum toca disco. A casca
(`run_feature_promotion_criterion_report`) lê os 3 relatórios reais de IC
por horizonte -- fora do escopo deste arquivo (precisaria de
`integration`/skip-if-ausente, não escrito aqui)."""

from __future__ import annotations

import pytest

from src.analysis import feature_promotion_criterion as fpc

# ============================================================================
# two_sided_p_from_t
# ============================================================================


def test_two_sided_p_from_t_zero_e_um() -> None:
    assert fpc.two_sided_p_from_t(0.0) == pytest.approx(1.0)


def test_two_sided_p_from_t_bate_com_1_96_e_005() -> None:
    """|t|=1,96 é o quantil de 95% bilateral -- p deve ficar perto de 0,05."""
    assert fpc.two_sided_p_from_t(1.959964) == pytest.approx(0.05, abs=1e-4)


def test_two_sided_p_from_t_decresce_com_t() -> None:
    assert fpc.two_sided_p_from_t(3.0) < fpc.two_sided_p_from_t(2.0) < fpc.two_sided_p_from_t(1.0)


def test_two_sided_p_from_t_levanta_com_t_negativo() -> None:
    with pytest.raises(fpc.FeaturePromotionCriterionError, match="negativo"):
        fpc.two_sided_p_from_t(-1.0)


# ============================================================================
# p_value_from_feature_entry -- caso de borda real: coluna 100% morta
# (D07f_taker_imbalance_1m_agg, sem pico_abs_t nas 15 celulas)
# ============================================================================


def test_p_value_from_feature_entry_usa_pico_abs_t_quando_presente() -> None:
    entry = {"pico_abs_t": 1.959964}
    assert fpc.p_value_from_feature_entry(entry) == pytest.approx(0.05, abs=1e-4)


def test_p_value_from_feature_entry_e_1_quando_pico_abs_t_ausente() -> None:
    """Coluna 100% morta (D07f_taker_imbalance_1m_agg real: pico_abs_t
    ausente nas 15 celulas, ic=NaN em todo horizonte) -- p=1,0 (nunca
    descoberta), nao um erro."""
    entry = {"pico_horizon_bars": None, "pico_ic": None, "pico_significativo": None}
    assert fpc.p_value_from_feature_entry(entry) == pytest.approx(1.0)


def test_p_value_from_feature_entry_dead_column_nunca_e_bh_discovery() -> None:
    dead = {"pico_horizon_bars": None, "pico_ic": None, "pico_significativo": None}
    p_values = [fpc.p_value_from_feature_entry(dead), 0.001, 0.5]
    assert fpc.benjamini_hochberg(p_values, q=0.10)[0] is False


# ============================================================================
# benjamini_hochberg
# ============================================================================


def test_benjamini_hochberg_lista_vazia() -> None:
    assert fpc.benjamini_hochberg([], q=0.10) == []


def test_benjamini_hochberg_todos_muito_pequenos_sao_descobertas() -> None:
    p_values = [0.0001, 0.0002, 0.0003, 0.0004]
    assert fpc.benjamini_hochberg(p_values, q=0.10) == [True, True, True, True]


def test_benjamini_hochberg_todos_grandes_nao_sao_descobertas() -> None:
    p_values = [0.8, 0.9, 0.95, 0.99]
    assert fpc.benjamini_hochberg(p_values, q=0.10) == [False, False, False, False]


def test_benjamini_hochberg_caso_misto_classico() -> None:
    """m=4, q=0,10: cortes BH em i/m*q = 0,025/0,05/0,075/0,10. Só o menor
    p (0,01 <= 0,025) sobrevive."""
    p_values = [0.01, 0.20, 0.50, 0.80]
    assert fpc.benjamini_hochberg(p_values, q=0.10) == [True, False, False, False]


def test_benjamini_hochberg_preserva_ordem_original() -> None:
    """O maior p-valor vem primeiro na lista -- o resultado tem que
    respeitar a posição de entrada, não a ordem interna de ordenação."""
    p_values = [0.80, 0.01]
    assert fpc.benjamini_hochberg(p_values, q=0.10) == [False, True]


def test_benjamini_hochberg_levanta_com_q_fora_de_0_1() -> None:
    with pytest.raises(fpc.FeaturePromotionCriterionError, match="q="):
        fpc.benjamini_hochberg([0.01, 0.02], q=0.0)


# ============================================================================
# symbol_is_majority_discovery
# ============================================================================


@pytest.mark.parametrize(
    ("resolutions", "expected"),
    [
        ((True, True, True), True),
        ((True, True, False), True),
        ((True, False, False), False),
        ((False, False, False), False),
    ],
)
def test_symbol_is_majority_discovery(resolutions: tuple[bool, ...], expected: bool) -> None:
    assert fpc.symbol_is_majority_discovery(resolutions) is expected


def test_symbol_is_majority_discovery_levanta_com_numero_errado_de_resolucoes() -> None:
    with pytest.raises(fpc.FeaturePromotionCriterionError, match="3 resoluções"):
        fpc.symbol_is_majority_discovery((True, False))


# ============================================================================
# expected_count_at_least_k
# ============================================================================


def test_expected_count_at_least_k_k_zero_e_todas_as_features() -> None:
    assert fpc.expected_count_at_least_k(
        n_features=72, n_symbols=5, p_symbol=0.146, k=0
    ) == pytest.approx(72.0)


def test_expected_count_at_least_k_k_maior_que_n_symbols_e_zero() -> None:
    assert fpc.expected_count_at_least_k(
        n_features=72, n_symbols=5, p_symbol=0.146, k=6
    ) == pytest.approx(0.0)


def test_expected_count_at_least_k_bate_com_formula_binomial_fechada() -> None:
    """P(X>=3) sob binomial(5; 0,146) calculada à mão via soma de termos
    discretos -- verificação independente da chamada a scipy."""
    from math import comb

    n, p, k = 5, 0.146, 3
    prob_at_least_k = sum(comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(k, n + 1))
    esperado = 72 * prob_at_least_k
    assert fpc.expected_count_at_least_k(
        n_features=72, n_symbols=n, p_symbol=p, k=k
    ) == pytest.approx(esperado, rel=1e-6)


def test_expected_count_at_least_k_decresce_com_k() -> None:
    vals = [
        fpc.expected_count_at_least_k(n_features=72, n_symbols=5, p_symbol=0.146, k=k)
        for k in range(1, 6)
    ]
    assert vals == sorted(vals, reverse=True)


def test_expected_count_at_least_k_levanta_com_p_fora_de_0_1() -> None:
    with pytest.raises(fpc.FeaturePromotionCriterionError, match="p_symbol"):
        fpc.expected_count_at_least_k(n_features=72, n_symbols=5, p_symbol=1.5, k=1)


# ============================================================================
# build_symbol_counts / empirical_p_symbol
# ============================================================================


def test_build_symbol_counts_ordena_decrescente() -> None:
    discovery = {
        "F1": {"BTC": True, "ETH": False, "SOL": False},
        "F2": {"BTC": True, "ETH": True, "SOL": True},
        "F3": {"BTC": False, "ETH": False, "SOL": False},
    }
    rows = fpc.build_symbol_counts(discovery)
    assert [r.feature for r in rows] == ["F2", "F1", "F3"]
    assert rows[0].n_symbols_discovery == 3
    assert rows[0].symbols_discovery == ("BTC", "ETH", "SOL")
    assert rows[2].n_symbols_discovery == 0


def test_empirical_p_symbol_e_a_fracao_observada() -> None:
    discovery = {
        "F1": {"BTC": True, "ETH": False},
        "F2": {"BTC": True, "ETH": True},
    }
    # 3 hits em 4 pares feature x simbolo
    assert fpc.empirical_p_symbol(discovery) == pytest.approx(0.75)


def test_empirical_p_symbol_levanta_com_painel_vazio() -> None:
    with pytest.raises(fpc.FeaturePromotionCriterionError, match="vazio"):
        fpc.empirical_p_symbol({})


def test_empirical_p_symbol_reproduz_o_caso_e16f_do_ag_270() -> None:
    """`AG-270` mediu E16f como BTC 3/3, SOL 3/3, BNB 1/3, ETH 0/3, XRP
    0/3 -- sob maioria (>=2/3), isso vira 2 símbolos-descoberta (BTC, SOL),
    não os ~2,3 fracionários do cálculo original (metodologia diferente,
    mesma direção: bem abaixo de 5, e não distinguível do acaso)."""
    e16f_by_symbol = {"BTC": True, "SOL": True, "BNB": False, "ETH": False, "XRP": False}
    counts = fpc.build_symbol_counts({"E16f": e16f_by_symbol})
    assert counts[0].n_symbols_discovery == 2
    assert counts[0].symbols_discovery == ("BTC", "SOL")
