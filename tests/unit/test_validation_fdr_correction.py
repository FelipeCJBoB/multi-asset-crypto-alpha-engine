"""Testes de `src.validation.fdr_correction` — núcleo puro, sem IO."""

from __future__ import annotations

import math

import pytest

from src.validation import fdr_correction as mod


def test_two_sided_p_from_z_valores_conhecidos() -> None:
    assert mod.two_sided_p_from_z(0.0) == pytest.approx(1.0)
    assert mod.two_sided_p_from_z(1.959964) == pytest.approx(0.05, abs=1e-4)
    assert mod.two_sided_p_from_z(-1.959964) == pytest.approx(0.05, abs=1e-4)  # simétrico
    assert mod.two_sided_p_from_z(3.18) == pytest.approx(0.00147, abs=1e-4)


def test_apply_fdr_correction_preserva_ordem_e_labels() -> None:
    p_values = {"XRPUSDT/R2": 0.0016, "BTCUSDT/R2": 0.5411, "SOLUSDT/R3": 0.0293}
    results = mod.apply_fdr_correction(p_values, significance_level=0.05)
    assert [r.label for r in results] == list(p_values.keys())
    assert [r.p_value_raw for r in results] == list(p_values.values())


def test_apply_fdr_correction_bh_bate_exemplo_livro_texto() -> None:
    """Benjamini & Hochberg (1995), exemplo canônico -- m=5, alpha=0,05,
    p=[0,01; 0,04; 0,03; 0,005; 0,20]. P-valores ajustados reais (passo-
    a-passo, step-up): p_adj=[0,025; 0,025; 0,05; 0,05; 0,20] pros ranks
    1..5 (p=0,005/0,01/0,03/0,04/0,20) -- ranks 3 e 4 EMPATAM exatamente
    no limiar (0,05), e pela definição operacional ESTRITA deste módulo
    (`< significance_level`, ver docstring de `apply_fdr_correction`),
    empate no limiar NÃO é significativo. Só os ranks 1-2 (p=0,005/0,01,
    os dois com p_adj=0,025 < 0,05) são significativos por BH aqui --
    achado real ao escrever este teste: minha expectativa inicial (reject
    ranks 1-4, convenção `<=` sobre o p BRUTO contra o valor crítico, não
    sobre o p AJUSTADO) estava errada, não a implementação -- as duas
    formulações do BH são equivalentes SALVO no tratamento de empate no
    limiar, exatamente o tipo de ambiguidade que a definição operacional
    explícita acima existe pra fechar."""
    p_values = {"a": 0.01, "b": 0.04, "c": 0.03, "d": 0.005, "e": 0.20}
    results = mod.apply_fdr_correction(p_values, significance_level=0.05)
    by_label = {r.label: r for r in results}
    assert by_label["a"].p_value_bh == pytest.approx(0.025)
    assert by_label["b"].p_value_bh == pytest.approx(0.05)
    assert by_label["c"].p_value_bh == pytest.approx(0.05)
    assert by_label["d"].p_value_bh == pytest.approx(0.025)
    assert by_label["e"].p_value_bh == pytest.approx(0.20)
    assert by_label["a"].significant_bh is True
    assert by_label["b"].significant_bh is False  # empate exato no limiar
    assert by_label["c"].significant_bh is False  # empate exato no limiar
    assert by_label["d"].significant_bh is True
    assert by_label["e"].significant_bh is False


def test_apply_fdr_correction_by_mais_conservador_que_bh() -> None:
    """BY controla FDR sob qualquer dependência (mais conservador) --
    p-valor ajustado por BY nunca é menor que o ajustado por BH pro mesmo
    teste (BY multiplica pelo termo harmônico adicional, sempre >= 1)."""
    p_values = {"a": 0.001, "b": 0.01, "c": 0.02, "d": 0.03, "e": 0.5}
    results = mod.apply_fdr_correction(p_values, significance_level=0.05)
    for r in results:
        assert r.p_value_by >= r.p_value_bh - 1e-12


def test_apply_fdr_correction_dict_vazio_retorna_tupla_vazia() -> None:
    assert mod.apply_fdr_correction({}) == ()


def test_apply_fdr_correction_default_le_de_constants_yaml() -> None:
    """`significance_level=None` resolve de `fdr_significance_level`
    (constants.yaml, 0,05 real) — mesmo resultado que passar 0,05
    explícito."""
    p_values = {"a": 0.01, "b": 0.20}
    explicit = mod.apply_fdr_correction(p_values, significance_level=0.05)
    default = mod.apply_fdr_correction(p_values)
    assert explicit == default


def test_apply_fdr_correction_15_combos_taxa_base_real() -> None:
    """Os 15 z-scores REAIS da tabela de taxa-base do artefato 'Alpha —
    Base de Pesquisa' (H0-H7, 2026-08-24) — prova que o pipeline
    z-score->p-valor->FDR roda de ponta a ponta sobre dado real do
    projeto, não só um exemplo sintético."""
    z_by_combo = {
        "BTCUSDT/R1": 3.18,
        "BTCUSDT/R2": -0.61,
        "BTCUSDT/R3": -0.74,
        "ETHUSDT/R1": 5.84,
        "ETHUSDT/R2": 1.47,
        "ETHUSDT/R3": 1.70,
        "SOLUSDT/R1": 0.92,
        "SOLUSDT/R2": -0.71,
        "SOLUSDT/R3": -2.18,
        "BNBUSDT/R1": 0.93,
        "BNBUSDT/R2": -1.58,
        "BNBUSDT/R3": -2.83,
        "XRPUSDT/R1": 2.18,
        "XRPUSDT/R2": 3.16,
        "XRPUSDT/R3": 2.04,
    }
    p_values = {combo: mod.two_sided_p_from_z(z) for combo, z in z_by_combo.items()}
    results = mod.apply_fdr_correction(p_values, significance_level=0.05)
    assert len(results) == 15  # noqa: magic-number -- 15 combos reais
    n_sig_raw = sum(1 for r in results if r.significant_raw)
    n_sig_bh = sum(1 for r in results if r.significant_bh)
    n_sig_by = sum(1 for r in results if r.significant_by)
    # BY (mais conservador) nunca acha MAIS significativos que BH, que
    # nunca acha mais que o teste bruto sem correção nenhuma.
    assert n_sig_by <= n_sig_bh <= n_sig_raw
    assert n_sig_raw == 7  # noqa: magic-number -- 7/15 "sig." já documentado no artefato (H0-H7)
