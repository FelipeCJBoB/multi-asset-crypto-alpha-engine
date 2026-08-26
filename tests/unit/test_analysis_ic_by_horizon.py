"""Testes do núcleo da curva de IC (`src.analysis.ic_by_horizon`).

Nenhum toca disco. O invariante que mais importa aqui é o do ERRO: uma
relação forte tem que sair com `|t|` alto e uma série de ruído puro tem que
sair com `|t|` baixo — se o erro estivesse subestimado (que é o que a
sobreposição de retornos causa), ruído passaria por sinal."""

from __future__ import annotations

import math

import numpy as np
import pytest

from src.analysis import ic_by_horizon as ic


def _rng() -> np.random.Generator:
    """Semente fixa — determinismo é requisito, não conveniência."""
    return np.random.default_rng(20260826)


# ============================================================================
# forward_log_return
# ============================================================================


def test_forward_log_return_alinha_por_posicao_e_deixa_nan_no_fim() -> None:
    close = np.array([100.0, 110.0, 121.0, 133.1], dtype=np.float64)
    out = ic.forward_log_return(close, 1)
    assert out.shape == close.shape
    assert np.isnan(out[-1])
    assert out[0] == pytest.approx(math.log(1.1))
    assert out[2] == pytest.approx(math.log(1.1))


def test_forward_log_return_horizonte_maior_deixa_h_nans() -> None:
    close = np.arange(1.0, 11.0, dtype=np.float64)
    out = ic.forward_log_return(close, 3)
    assert np.isnan(out[-3:]).all()
    assert np.isfinite(out[:-3]).all()


def test_forward_log_return_serie_curta_e_toda_nan() -> None:
    """Sem futuro para nenhuma posição — devolve NaN, não levanta."""
    out = ic.forward_log_return(np.array([100.0, 101.0]), 5)
    assert np.isnan(out).all()


def test_forward_log_return_rejeita_horizonte_invalido() -> None:
    with pytest.raises(ic.ICError, match=">= 1"):
        ic.forward_log_return(np.array([1.0, 2.0]), 0)


# ============================================================================
# spearman_ic
# ============================================================================


def test_spearman_de_relacao_monotona_crescente_e_um() -> None:
    x = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    assert ic.spearman_ic(x, x**3) == pytest.approx(1.0)


def test_spearman_de_relacao_monotona_decrescente_e_menos_um() -> None:
    x = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    assert ic.spearman_ic(x, -x) == pytest.approx(-1.0)


def test_spearman_de_lado_constante_e_nan_nao_zero() -> None:
    """Constante não tem relação INDEFINIDA, não relação NULA — devolver 0
    faria a feature degenerada parecer medida e sem sinal."""
    x = np.array([1.0, 2.0, 3.0, 4.0])
    assert math.isnan(ic.spearman_ic(x, np.ones(4)))


def test_spearman_trata_empates_por_media() -> None:
    """Colunas com massa em zero (flags) são comuns no vetor — resolver
    empate por ordem de chegada inventaria ordenação inexistente."""
    x = np.array([0.0, 0.0, 0.0, 1.0, 2.0])
    y = np.array([5.0, 5.0, 5.0, 6.0, 7.0])
    assert ic.spearman_ic(x, y) == pytest.approx(1.0)


def test_spearman_rejeita_shapes_diferentes() -> None:
    with pytest.raises(ic.ICError, match="shapes diferentes"):
        ic.spearman_ic(np.zeros(3), np.zeros(4))


# ============================================================================
# ic_disjoint — o coração do módulo
# ============================================================================


def test_ic_disjoint_usa_exatamente_h_subamostras() -> None:
    rng = _rng()
    n = 2000
    feature = rng.normal(size=n)
    fwd = rng.normal(size=n)
    for h in (1, 2, 4, 8):
        _, _, _, n_sub = ic.ic_disjoint(feature, fwd, h)
        assert n_sub == h


def test_ic_disjoint_recupera_relacao_forte_com_t_alto() -> None:
    rng = _rng()
    n = 4000
    feature = rng.normal(size=n)
    fwd = feature + 0.3 * rng.normal(size=n)
    ic_mean, stderr, _, _ = ic.ic_disjoint(feature, fwd, 4)
    assert ic_mean > 0.9
    assert stderr > 0.0
    assert abs(ic_mean / stderr) > ic._T_SIGNIFICANCE


def test_ruido_puro_nao_produz_pico_significativo() -> None:
    """O teste que justifica o desenho do erro: sem relação real, |t| tem
    que ficar baixo. Um erro subestimado transformaria ruído em achado."""
    rng = _rng()
    n = 5000
    feature = rng.normal(size=n)
    fwd = rng.normal(size=n)
    pontos = ic.ic_curve({"ruido": feature}, np.exp(np.cumsum(fwd) / 100.0))
    resumo = ic.peak_horizon(pontos)
    assert resumo["pico_significativo"] is False


def test_ic_disjoint_ignora_nan_sem_quebrar() -> None:
    rng = _rng()
    n = 1000
    feature = rng.normal(size=n)
    feature[:200] = np.nan  # warmup, como no Feature Engine real
    fwd = feature + 0.2 * rng.normal(size=n)
    ic_mean, _, n_points, _ = ic.ic_disjoint(feature, fwd, 2)
    assert n_points == n - 200
    assert math.isfinite(ic_mean)


def test_amostra_pequena_devolve_nan_em_vez_de_numero_fragil() -> None:
    feature = np.arange(10.0)
    fwd = np.arange(10.0)
    ic_mean, stderr, n_points, n_sub = ic.ic_disjoint(feature, fwd, 2)
    assert math.isnan(ic_mean) and math.isnan(stderr)
    assert n_points == 10
    assert n_sub == 0


def test_ic_disjoint_rejeita_shapes_diferentes() -> None:
    with pytest.raises(ic.ICError, match="shapes diferentes"):
        ic.ic_disjoint(np.zeros(200), np.zeros(300), 2)


def test_subamostras_disjuntas_nao_compartilham_indice() -> None:
    """Invariante estrutural do método: offsets 0..h-1 com passo h
    particionam a série sem interseção."""
    n, h = 100, 4
    idx = np.arange(n)
    fatias = [set(idx[o::h].tolist()) for o in range(h)]
    uniao: set[int] = set()
    for fatia in fatias:
        assert not (uniao & fatia)
        uniao |= fatia
    assert uniao == set(idx.tolist())


# ============================================================================
# ic_curve / peak_horizon
# ============================================================================


def test_ic_curve_cobre_todas_as_features_e_horizontes() -> None:
    rng = _rng()
    close = np.exp(np.cumsum(rng.normal(size=3000)) / 100.0)
    feats = {"a": rng.normal(size=3000), "b": rng.normal(size=3000)}
    pontos = ic.ic_curve(feats, close, horizons=(1, 2, 4))
    assert len(pontos) == 2 * 3
    assert {p.feature for p in pontos} == {"a", "b"}
    assert {p.horizon_bars for p in pontos} == {1, 2, 4}


def test_h_sobre_holding_usa_o_holding_medido() -> None:
    rng = _rng()
    close = np.exp(np.cumsum(rng.normal(size=1500)) / 100.0)
    (ponto,) = ic.ic_curve({"a": rng.normal(size=1500)}, close, horizons=(10,))
    assert ponto.h_sobre_holding == pytest.approx(10 / ic.HOLDING_BARS)


def test_peak_horizon_acha_o_maior_ic_em_modulo() -> None:
    """IC negativo forte é pico tanto quanto positivo forte — o sinal diz a
    direção, o módulo diz a força."""
    pontos = [
        ic.ICPoint("f", 1, 0.2, 0.01, 0.001, 1000, 1, 1000, 10.0, 0.0),
        ic.ICPoint("f", 4, 0.8, -0.30, 0.001, 1000, 4, 250, 300.0, 0.01),
        ic.ICPoint("f", 8, 1.6, 0.05, 0.001, 1000, 8, 125, 50.0, 0.01),
    ]
    resumo = ic.peak_horizon(pontos)
    assert resumo["pico_horizon_bars"] == 4
    assert resumo["pico_ic"] == pytest.approx(-0.30)


def test_peak_horizon_marca_pico_nao_significativo() -> None:
    pontos = [ic.ICPoint("f", 4, 0.8, 0.004, 0.01, 1000, 4, 250, 0.4, 0.01)]
    assert ic.peak_horizon(pontos)["pico_significativo"] is False


def test_peak_horizon_sem_ponto_finito_devolve_none() -> None:
    pontos = [ic.ICPoint("f", 4, 0.8, float("nan"), float("nan"), 10, 0, 2, float("nan"), float("nan"))]
    assert ic.peak_horizon(pontos)["pico_horizon_bars"] is None
