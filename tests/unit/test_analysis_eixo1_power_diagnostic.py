"""Testes do diagnóstico de poder do eixo 1 (`src.analysis.
eixo1_power_diagnostic`, `AG-327`).

Cobrem o NÚCLEO PURO (`synthetic_correlated_series`, `peak_abs_t_for_series`,
`p_values_with_synthetic`, `synthetic_is_discovered`) -- nenhum toca disco.
A casca (`run_eixo1_power_diagnostic_report`) lê barras/relatórios reais e
roda Monte Carlo -- fora do escopo deste arquivo (precisaria de
`integration`/`slow`/skip-if-ausente, não escrito aqui, mesmo padrão de
`test_analysis_feature_promotion_criterion.py`)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from src.analysis import eixo1_power_diagnostic as epd
from src.analysis.ic_by_horizon import spearman_ic

# ============================================================================
# synthetic_correlated_series
# ============================================================================


def test_synthetic_correlated_series_levanta_fora_de_menos1_1() -> None:
    rng = np.random.default_rng(0)
    ref = rng.standard_normal(50)
    with pytest.raises(epd.Eixo1PowerDiagnosticError, match=r"fora de \[-1, 1\]"):
        epd.synthetic_correlated_series(ref, 1.5, rng)


def test_synthetic_correlated_series_preserva_nan_por_posicao() -> None:
    rng = np.random.default_rng(1)
    ref = np.array([1.0, 2.0, np.nan, 4.0, 5.0, np.nan])
    out = epd.synthetic_correlated_series(ref, 0.05, rng)
    assert out.shape == ref.shape
    assert math.isnan(out[2])
    assert math.isnan(out[5])
    assert not math.isnan(out[0])
    assert not math.isnan(out[3])


def test_synthetic_correlated_series_rho_1_e_transformacao_monotona_exata() -> None:
    """`rho_true=1,0` zera o peso de ruído -- a saída é uma função
    estritamente monótona dos postos da referência, então o Spearman entre
    as duas deve ser exatamente 1,0 (sem empates, série contínua real)."""
    rng = np.random.default_rng(2)
    ref = rng.standard_normal(500)
    out = epd.synthetic_correlated_series(ref, 1.0, rng)
    ic = spearman_ic(out, ref)
    assert ic == pytest.approx(1.0, abs=1e-9)


def test_synthetic_correlated_series_rho_menos_1_e_perfeitamente_inversa() -> None:
    rng = np.random.default_rng(3)
    ref = rng.standard_normal(500)
    out = epd.synthetic_correlated_series(ref, -1.0, rng)
    ic = spearman_ic(out, ref)
    assert ic == pytest.approx(-1.0, abs=1e-9)


def test_synthetic_correlated_series_rho_0_nao_correlaciona_sistematicamente() -> None:
    """Não é um teste de valor único (rho amostral varia por sorteio) -- mede
    que a MÉDIA sobre muitos sorteios independentes fica perto de 0, não que
    um sorteio isolado seja exatamente 0."""
    ref_rng = np.random.default_rng(4)
    ref = ref_rng.standard_normal(2000)
    ics = []
    for seed in range(30):
        rng = np.random.default_rng(1000 + seed)
        out = epd.synthetic_correlated_series(ref, 0.0, rng)
        ics.append(spearman_ic(out, ref))
    assert abs(float(np.mean(ics))) < 0.05


def test_synthetic_correlated_series_menos_de_2_pontos_validos_e_tudo_nan() -> None:
    rng = np.random.default_rng(5)
    ref = np.array([1.0, np.nan, np.nan])
    out = epd.synthetic_correlated_series(ref, 0.03, rng)
    assert np.all(np.isnan(out))


def test_synthetic_correlated_series_referencia_constante_e_tudo_nan() -> None:
    """`rank_std == 0` (todos os valores válidos iguais) não tem posto pra
    correlacionar -- indefinido, não zero."""
    rng = np.random.default_rng(6)
    ref = np.array([3.0, 3.0, 3.0, 3.0])
    out = epd.synthetic_correlated_series(ref, 0.03, rng)
    assert np.all(np.isnan(out))


# ============================================================================
# measure_achieved_spearman_rho
# ============================================================================


def test_measure_achieved_spearman_rho_extremos_batem_exato() -> None:
    """rho_true=1,0/-1,0 sao os casos degenerados onde a identidade e
    exata (peso de ruido zerado) -- serve de sanidade pra funcao de
    medicao em si, nao so pra synthetic_correlated_series."""
    assert epd.measure_achieved_spearman_rho(1.0, seed=100) == pytest.approx(1.0, abs=1e-6)
    assert epd.measure_achieved_spearman_rho(-1.0, seed=101) == pytest.approx(-1.0, abs=1e-6)


def test_measure_achieved_spearman_rho_zero_fica_perto_de_zero() -> None:
    assert abs(epd.measure_achieved_spearman_rho(0.0, seed=102)) < 0.02


def test_measure_achieved_spearman_rho_propaga_erro_de_rho_invalido() -> None:
    with pytest.raises(epd.Eixo1PowerDiagnosticError, match=r"fora de \[-1, 1\]"):
        epd.measure_achieved_spearman_rho(2.0, seed=103)


# ============================================================================
# peak_abs_t_for_series
# ============================================================================


def test_peak_abs_t_for_series_pega_o_maior_entre_horizontes() -> None:
    rng = np.random.default_rng(7)
    n = 3000
    ref = rng.standard_normal(n)
    # h=1: sinal forte; h=2: sem sinal (ruido puro independente).
    feature = 0.3 * ref + math.sqrt(1 - 0.3**2) * rng.standard_normal(n)
    fwd_by_h = {1: ref, 2: rng.standard_normal(n)}
    peak = epd.peak_abs_t_for_series(feature, fwd_by_h)
    assert math.isfinite(peak)
    assert peak > 2.0  # sinal de 0,3 sobre 3000 pontos deve ser bem distinguivel de 0


def test_peak_abs_t_for_series_todos_horizontes_invalidos_e_nan() -> None:
    feature = np.array([1.0, 2.0, 3.0])
    fwd_by_h = {1: np.array([np.nan, np.nan, np.nan])}
    assert math.isnan(epd.peak_abs_t_for_series(feature, fwd_by_h))


def test_peak_abs_t_for_series_seleciona_por_max_ic_nao_por_max_t(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regressão do achado da revisão independente (2026-08-26): a selecao
    tem que ser por MAIOR |ic| (como `ic_by_horizon.peak_horizon` faz),
    NAO por maior |ic/stderr| direto -- as duas divergem porque `stderr`
    varia por horizonte. Horizonte A tem |ic| menor mas |t| MAIOR (stderr
    pequeno); horizonte B tem |ic| maior mas |t| menor (stderr grande). O
    pico correto e o de B (maior |ic|), com o |t| DELE (0,2) -- nao o |t|
    de A (5,0), que seria o resultado da implementacao antiga (errada)."""
    fixed = {
        1: (0.05, 0.01, 1000, 10),  # |ic|=0,05, |t|=5,0
        2: (0.10, 0.50, 1000, 2),  # |ic|=0,10 (maior), |t|=0,2
    }

    def fake_ic_disjoint(
        feature: object, fwd_return: object, horizon_bars: int
    ) -> tuple[float, float, int, int]:
        return fixed[horizon_bars]

    monkeypatch.setattr(epd, "ic_disjoint", fake_ic_disjoint)
    feature = np.zeros(10)
    fwd_by_h = {1: np.zeros(10), 2: np.zeros(10)}
    peak = epd.peak_abs_t_for_series(feature, fwd_by_h)
    assert peak == pytest.approx(0.10 / 0.50)
    assert peak != pytest.approx(0.05 / 0.01)


# ============================================================================
# p_values_with_synthetic / synthetic_is_discovered
# ============================================================================


def test_p_values_with_synthetic_none_e_nan_viram_1() -> None:
    real = {"A": 2.5, "B": None, "C": float("nan")}
    out = epd.p_values_with_synthetic(real, 3.0)
    assert out["B"] == 1.0
    assert out["C"] == 1.0
    assert out[epd._SYNTHETIC_NAME] == pytest.approx(epd.two_sided_p_from_t(3.0))
    assert out["A"] == pytest.approx(epd.two_sided_p_from_t(2.5))


def test_p_values_with_synthetic_sintetica_sem_pico_vira_1() -> None:
    out = epd.p_values_with_synthetic({"A": 2.0}, float("nan"))
    assert out[epd._SYNTHETIC_NAME] == 1.0


def test_synthetic_is_discovered_falso_quando_tudo_e_ruido() -> None:
    """72 p-valores reais = 1,0 (nunca descobertos) + sintetica tambem sem
    pico -- BH nao descobre nada."""
    real = {f"f{i}": None for i in range(72)}
    assert epd.synthetic_is_discovered(real, float("nan"), q=0.10) is False


def test_synthetic_is_discovered_verdadeiro_quando_sintetica_e_extrema() -> None:
    """72 reais com p=1,0 + sintetica com |t| muito alto (p astronomicamente
    pequeno) -- deve sobreviver ao corte de BH mesmo dividido por m=73."""
    real = {f"f{i}": None for i in range(72)}
    assert epd.synthetic_is_discovered(real, 10.0, q=0.10) is True


def test_synthetic_is_discovered_nao_descobre_com_significancia_fraca_isolada() -> None:
    """Sintetica com |t| moderado (perto do limiar de significancia simples,
    2,0) nao deve sobreviver ao BH com m=73 e nenhum outro suporte real."""
    real = {f"f{i}": None for i in range(72)}
    assert epd.synthetic_is_discovered(real, 2.1, q=0.10) is False
